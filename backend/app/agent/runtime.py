r"""Agent runtime: policy gate + tool-calling loop + hand-offs + owner decisions.

  trigger -> snapshot (detectors) -> Orchestrator picks tools -> policy gate -> execute -> ledger -> repeat
                                        \-- ask_brief / ask_offer / ... / ask_analyst -> the specialist runs the same loop
                                            on its own model with its own tools, then reports back
A loop ends when its model stops calling tools or a budget is reached. Every agent goes through the same gate.
"""

import asyncio
import dataclasses
import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from app import ledger, services
from app.agent import situation
from app.agent.team import ORCHESTRATOR, AgentSpec, owner_of
from app.agent.tools import REGISTRY, ToolContext
from app.db import connection, fetch_one, jsonb
from app.providers.base import ProviderError
from app.providers.router import NoProviderAvailable, call_scope

log = logging.getLogger(__name__)
GATED = {"customer_facing", "fact"}
CONTINUE = ("If you said you would do something, do it now by calling the tools. If everything you can do is done "
            "or waiting for the owner, reply with your final one- or two-sentence note for the owner.")
_running: set[str] = set()
# Triggers that arrived while a run was going (an owner's answer, a new instruction). The run that holds the key
# takes them up when it ends, so an answer given mid-run is never dropped.
_queued: dict[str, list[str]] = {}


def is_running(key: Any) -> bool:
    return str(key) in _running


def _unwrap_json_strings(args: dict[str, Any]) -> dict[str, Any]:
    """Agnes sometimes sends list/object arguments JSON-encoded as strings. Used only as a retry after
    validation fails, so genuine string fields are never touched on the normal path."""
    out = dict(args)
    for key, value in args.items():
        if isinstance(value, str) and value.lstrip()[:1] in ("[", "{"):
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return out


def _validate_args(model: type[BaseModel], args: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(args)
    except ValidationError:
        unwrapped = _unwrap_json_strings(args)
        if unwrapped == args:
            raise
        return model.model_validate(unwrapped)


def _tags(ctx: ToolContext, task: str) -> dict[str, str | None]:
    return {"business_id": str(ctx.business["id"]), "campaign_id": str(ctx.campaign_id) if ctx.campaign_id else None,
            "task": task}


async def execute(ctx: ToolContext, name: str, raw_args: str | dict[str, Any]) -> dict[str, Any]:
    with call_scope(**_tags(ctx, name)):
        return await _execute(ctx, name, raw_args)


async def _execute(ctx: ToolContext, name: str, raw_args: str | dict[str, Any]) -> dict[str, Any]:
    tool = REGISTRY.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown tool '{name}'."}
    try:
        parsed = json.loads(raw_args or "{}") if isinstance(raw_args, str) else raw_args
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "Arguments must be a JSON object."}
        args = _validate_args(tool.args, parsed)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Arguments are not valid JSON: {e.msg}"}
    except ValidationError as e:
        return {"ok": False, "error": f"Invalid arguments: {e.errors(include_url=False)[:3]}"}

    for pre in tool.preconditions:
        if reason := await pre(ctx, args):
            return {"ok": False, "precondition_failed": reason}

    if tool.effect in GATED and not ctx.approved:
        async with connection() as conn:
            title = getattr(args, "summary", None) or f"Approve: {name.replace('_', ' ')}"
            item = await fetch_one(
                conn,
                """insert into inbox_items (business_id, campaign_id, kind, title, payload, priority)
                   values (%s, %s, 'approval', %s, %s, 1) returning id""",
                (ctx.business["id"], ctx.campaign_id, title,
                 jsonb({"tool": name, "args": args.model_dump(mode="json"), "effect": tool.effect})),
            )
            await ledger.record(conn, ctx.business["id"], "approval.requested", title, actor="agent",
                                campaign_id=ctx.campaign_id, payload={"tool": name, "inbox_item_id": str(item["id"])})  # type: ignore[index]
        return {"ok": False, "queued_for_owner_approval": str(item["id"]),  # type: ignore[index]
                "message": "The owner has been asked. Continue with other work or stop."}

    try:
        result = await tool.handler(ctx, args)
    except (services.Conflict, services.NotFound) as e:
        return {"ok": False, "error": str(e)}
    except NoProviderAvailable as e:
        return {"ok": False, "error": f"Model unavailable: {e}"}
    except ProviderError as e:  # e.g. the model replied without valid JSON twice; the agent can retry smaller
        return {"ok": False, "error": f"The model's reply was unusable ({str(e)[:200]}). Try again, with fewer cells."}
    return {"ok": "error" not in result, **result}


async def run(ctx: ToolContext, trigger: str) -> dict[str, Any]:
    """One agent run, then one more for anything that arrived while it ran."""
    key = str(ctx.campaign_id or ctx.business["id"])
    out = await _run_limited(ctx, trigger)
    while out.get("status") != "busy" and (more := _queued.pop(key, None)):
        out = await _run_limited(ctx, "While you were working: " + " | ".join(more))
    return out


async def _run_limited(ctx: ToolContext, trigger: str) -> dict[str, Any]:
    """One agent run, with a time limit so a stuck model never leaves the owner watching a spinner."""
    limit = ctx.settings.agent_run_timeout_s
    try:
        return await asyncio.wait_for(_run(ctx, trigger), timeout=limit)
    except TimeoutError:
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.failed",
                                f"I stopped after {limit // 60} minutes because the AI models were too slow or busy. "
                                "Everything done so far is saved. Try again in a few minutes.",
                                actor="system", campaign_id=ctx.campaign_id, payload={"timeout_s": limit})
        return {"status": "timeout", "message": "The run took too long and was stopped."}


async def _run(ctx: ToolContext, trigger: str) -> dict[str, Any]:
    key = str(ctx.campaign_id or ctx.business["id"])
    if key in _running:
        _queued.setdefault(key, []).append(trigger)
        return {"status": "busy", "message": "Already working on this; I'll take it up when this run ends."}
    _running.add(key)
    s = ctx.settings
    steps: list[dict[str, Any]] = []
    try:
        async with connection() as conn:
            snap = await situation.snapshot(conn, ctx.business, ctx.campaign_id)
            await ledger.record(conn, ctx.business["id"], "agent.started", f"Started: {trigger}", actor="agent",
                                campaign_id=ctx.campaign_id, payload={"findings": snap["findings"]})
        final, llm_calls = await _loop(ctx, ORCHESTRATOR, {"trigger": trigger, "situation": snap},
                                       max_calls=s.agent_max_llm_calls, steps=steps)
        status = "done" if final is not None else "budget_reached"
        steps = [{k: v for k, v in st.items() if k != "result"} for st in steps]  # results are in each tool event
        async with connection() as conn:
            if final is None:
                waiting = await fetch_one(
                    conn, """select title from inbox_items where business_id = %s and status = 'pending'
                             and campaign_id is not distinct from %s order by created_at desc limit 1""",
                    (ctx.business["id"], ctx.campaign_id))
                final = (f"I've done what I can for now. Waiting for you: {waiting['title']}" if waiting
                         else "I paused here because I reached this run's budget.")
            await ledger.record(conn, ctx.business["id"], "agent.finished", final, actor="agent",
                                campaign_id=ctx.campaign_id, payload={"steps": steps, "llm_calls": llm_calls})
        return {"status": status, "message": final, "steps": steps, "llm_calls": llm_calls}
    except NoProviderAvailable as e:
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.failed", f"Model unavailable: {e}", actor="system",
                                campaign_id=ctx.campaign_id)
        return {"status": "unavailable", "message": str(e), "steps": steps}
    except Exception as e:  # never leave a run looking "in progress" on the owner's screen
        log.exception("agent run failed")
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.failed",
                                "I stopped because of an internal error. Your data is safe; try again.",
                                actor="system", campaign_id=ctx.campaign_id, payload={"error": repr(e)[:500]})
        return {"status": "failed", "message": str(e), "steps": steps}
    finally:
        _running.discard(key)


async def run_specialist(ctx: ToolContext, agent: AgentSpec, task: str) -> dict[str, Any]:
    """The owner calls one specialist directly (the Analyst from the results, the Customer listener from the
    Customers page), without an Orchestrator turn in front of it. Same gate, budget and ledger."""
    key = str(ctx.campaign_id or ctx.business["id"])
    if key in _running:
        return {"status": "busy", "message": "Already working on this."}
    _running.add(key)
    try:
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.started", f"Started: {task}", actor="agent",
                                campaign_id=ctx.campaign_id, payload={"agent": agent.key})
        out = await asyncio.wait_for(delegate(ctx, agent, {"task": task}, handoff=False),
                                     timeout=ctx.settings.agent_run_timeout_s)
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.finished", out["summary"], actor="agent",
                                campaign_id=ctx.campaign_id, payload={"agent": agent.key, "llm_calls": out["llm_calls"]})
        return {"status": "done", "message": out["summary"]}
    except (NoProviderAvailable, TimeoutError) as e:
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.failed",
                                f"The {agent.name} stopped: the AI models were too slow or busy. Try again soon.",
                                actor="system", campaign_id=ctx.campaign_id, payload={"error": repr(e)[:300]})
        return {"status": "unavailable", "message": str(e)}
    except Exception as e:
        log.exception("specialist run failed")
        async with connection() as conn:
            await ledger.record(conn, ctx.business["id"], "agent.failed",
                                "I stopped because of an internal error. Your data is safe; try again.",
                                actor="system", campaign_id=ctx.campaign_id, payload={"error": repr(e)[:500]})
        return {"status": "failed", "message": str(e)}
    finally:
        _running.discard(key)


async def delegate(ctx: ToolContext, agent: AgentSpec, task: dict[str, Any], *, handoff: bool = True) -> dict[str, Any]:
    """A hand-off: the specialist works on the task with its own model and tools, then reports back."""
    async with connection() as conn:
        snap = await situation.snapshot(conn, ctx.business, ctx.campaign_id)
        if handoff:
            await ledger.record(conn, ctx.business["id"], "agent.handoff", f"Asked the {agent.name}: {task['task']}",
                                actor="agent", campaign_id=ctx.campaign_id, payload={"agent": agent.key, "task": task})
    steps: list[dict[str, Any]] = []
    final, llm_calls = await _loop(ctx, agent, {"task": task, "situation": snap},
                                   max_calls=ctx.settings.agent_specialist_max_llm_calls, steps=steps)
    summary = final or f"The {agent.name} stopped at its budget."
    async with connection() as conn:
        await ledger.record(conn, ctx.business["id"], "agent.reported", f"{agent.name}: {summary}", actor="agent",
                            campaign_id=ctx.campaign_id, payload={"agent": agent.key, "llm_calls": llm_calls})
    return {"agent": agent.name, "summary": summary, "llm_calls": llm_calls,
            "steps": [{"tool": st["tool"], "ok": st["ok"], "result": st["result"]} for st in steps]}


async def _loop(ctx: ToolContext, agent: AgentSpec, opening: dict[str, Any], *, max_calls: int,
                steps: list[dict[str, Any]]) -> tuple[str | None, int]:
    """One agent's tool-calling loop. Returns its final note (None if it hit a budget) and its model calls."""
    s = ctx.settings
    tools = [REGISTRY[t].schema() for t in agent.tools]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": agent.system.format(
            business_name=ctx.business["name"], business_kind=ctx.business["profile"].get("kind", "business"),
            locality=ctx.business["locality"], city=ctx.business["city"], max_llm_calls=max_calls)},
        {"role": "user", "content": json.dumps(opening, ensure_ascii=False, default=str)},
    ]
    ctx = dataclasses.replace(ctx, agent=agent.key)
    llm_calls = 0
    nudged = False
    mine = 0  # this agent's own steps (hand-offs report the specialist's steps separately)
    while llm_calls < max_calls and mine < s.agent_max_steps:
        with call_scope(**_tags(ctx, "plan"), agent=agent.key):
            res = await ctx.router.chat(agent.role, messages, tools=tools, tool_choice="auto", temperature=0.2)
        llm_calls += 1
        if not res.tool_calls:
            reply = (res.content or "").strip()
            # Seen live: the model announces its next step in prose ("Now locking the facts...") and stops.
            # After it has done some work, ask once to either act or give the final note.
            if mine and not nudged and llm_calls < max_calls:
                nudged = True
                messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": CONTINUE}]
                continue
            return reply, llm_calls
        # Send back the provider's own message when we have it: Gemini 3 attaches thought signatures to tool
        # calls (extra_content) and rejects the next turn without them.
        raw = res.raw_message if res.raw_message.get("tool_calls") else None
        messages.append({"role": "assistant", "content": res.content or "", "tool_calls": raw["tool_calls"]} if raw
                        else {"role": "assistant", "content": res.content or "",
                              "tool_calls": [{"id": c.id, "type": "function",
                                              "function": {"name": c.name, "arguments": c.arguments}}
                                             for c in res.tool_calls]})
        for call in res.tool_calls:
            with call_scope(agent=agent.key):
                out = (await execute(ctx, call.name, call.arguments) if call.name in agent.tools
                       else _not_yours(agent, call.name))
            mine += 1
            steps.append({"agent": agent.key, "tool": call.name, "ok": out.get("ok"), "saved_output": res.replayed,
                          "result": out})
            async with connection() as conn:
                await ledger.record(
                    conn, ctx.business["id"], f"tool.{call.name}", f"{agent.name}: {_describe(call.name, out)}",
                    actor="agent", campaign_id=ctx.campaign_id,
                    payload={"agent": agent.key, "args": _safe_json(call.arguments), "result": out,
                             "saved_output": res.replayed})
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
    return None, llm_calls


def _not_yours(agent: AgentSpec, name: str) -> dict[str, Any]:
    owner = owner_of(name)
    if owner and f"ask_{owner.key}" in agent.tools:
        return {"ok": False, "error": f"{name} belongs to the {owner.name}. Hand the work over with ask_{owner.key}."}
    return {"ok": False, "error": f"{name} is not one of your tools. Use only: {', '.join(agent.tools)}."}


async def decide_inbox(ctx: ToolContext, item_id: str, *, approve: bool, note: str | None) -> dict[str, Any]:
    """Owner decision. Approving a gated item executes exactly the stored tool call."""
    async with connection() as conn:
        item = await fetch_one(conn, "select * from inbox_items where id = %s and business_id = %s",
                               (item_id, ctx.business["id"]))
    if not item:
        raise services.NotFound("inbox item not found")
    if item["status"] != "pending":
        raise services.Conflict(f"Already {item['status']}.")

    if item["kind"] == "question" and approve and not (note or "").strip():
        raise services.Conflict("Type or pick an answer first.")
    result: dict[str, Any] | None = None
    tool_name = item["payload"].get("tool")
    if approve and tool_name:
        run_ctx = ToolContext(business=ctx.business, campaign_id=str(item["campaign_id"]) if item["campaign_id"] else None,
                              router=ctx.router, settings=ctx.settings, actor="owner", approved=True)
        result = await execute(run_ctx, tool_name, item["payload"].get("args", {}))
        if not result.get("ok"):
            raise services.Conflict(result.get("error") or result.get("precondition_failed") or "Could not apply.")

    async with connection() as conn:
        await conn.execute(
            "update inbox_items set status = %s, decided_at = now(), decision = %s where id = %s",
            ("approved" if approve else "rejected", jsonb({"note": note, "result": result}), item_id))
        await ledger.record(conn, ctx.business["id"], "approval.decided",
                            f"{'Approved' if approve else 'Declined'}: {item['title']}", actor="owner",
                            campaign_id=item["campaign_id"], payload={"inbox_item_id": item_id, "note": note})
    return {"status": "approved" if approve else "rejected", "result": result}


def _safe_json(s: str) -> Any:
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


def _describe(name: str, out: dict[str, Any]) -> str:
    label = name.replace("_", " ")
    if out.get("queued_for_owner_approval"):
        return f"Asked the owner to approve: {label}"
    if out.get("precondition_failed"):
        return f"Could not {label}: {out['precondition_failed']}"
    if out.get("error"):
        return f"{label.capitalize()} failed: {out['error']}"
    return label.capitalize()
