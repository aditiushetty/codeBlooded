"""The agent team: the Orchestrator hands writing to the Writer and checking to the Checker, each on its own model
with its own tools, and every tool still goes through the policy gate."""

import json
import os
from pathlib import Path

from app.agent import runtime
from app.agent.team import CHECKER, ORCHESTRATOR, TEAM, WRITER
from app.db import connection, fetch_all
from app.providers.replay import ReplayCache
from app.providers.router import ModelRouter
from tests.fakes import ProviderError, ScriptedLLM, calls, text
from tests.test_flow import FACTS, content, ctx_for, wording

FEATS = {"hook": "value", "cta_strength": 2, "tone": "warm"}


def test_each_agent_has_its_own_job_and_model():
    assert {a.role for a in TEAM.values()} == {"reasoning", "generation", "verification"}
    assert WRITER.role != CHECKER.role  # a post is never checked by the model chain that wrote it
    # writing and checking belong to the specialists only
    assert "generate_copy" not in ORCHESTRATOR.tools and "validate_assets" not in ORCHESTRATOR.tools
    assert {"ask_writer", "ask_checker"} <= set(ORCHESTRATOR.tools)
    # specialists cannot change the offer, publish or hand work on
    for a in (WRITER, CHECKER):
        assert not {"lock_facts", "draft_offer_facts", "publish_assets", "ask_writer", "ask_checker"} & set(a.tools)
    assert "generate_copy" not in CHECKER.tools and "validate_assets" not in WRITER.tools


async def _locked_campaign(client, scripted):
    r = await client.post("/api/businesses/kaapi-kone/campaigns", json={"brief": "weekday combo", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    scripted.push(wording())
    await runtime.execute(ctx, "draft_offer_facts", {"facts": FACTS, "forbidden_claims": {}, "reason": "b"})
    lock = await client.post(f"/api/campaigns/{ctx.campaign_id}/facts/lock", params={"resume": False})
    assert lock.status_code == 200
    return ctx


def _team_router() -> tuple[ModelRouter, ScriptedLLM, ScriptedLLM, ScriptedLLM]:
    orch, writer, checker = ScriptedLLM("orch"), ScriptedLLM("writer"), ScriptedLLM("checker")
    router = ModelRouter(llms={"orch": orch, "writer": writer, "checker": checker}, images={},
                         roles={"reasoning": ["orch"], "generation": ["writer"], "verification": ["checker"],
                                "image": []},
                         replay=ReplayCache(Path(os.environ["REPLAY_DIR"])))
    return router, orch, writer, checker


async def test_orchestrator_hands_off_to_writer_then_checker(client, scripted):
    ctx = await _locked_campaign(client, scripted)
    router, orch, writer, checker = _team_router()
    ctx.router = router

    # --- 1. the Orchestrator asks the Writer; the Writer plans the cell and calls generate_copy
    orch.push(calls(("ask_writer", {"task": "Write the WhatsApp post for students"})),
              *[text("The Writer wrote the post; it is waiting for its meaning check.")] * 2)
    writer.push(
        calls(("generate_copy", {"cells": [{"segment": "students", "channel": "whatsapp", "language": "en",
                                            "angle": "exam-week break"}]})),
        text(json.dumps({"assets": [{"cell": 0, "content": content("{{discount}} on {{combo}}, {{days}}. {{dine_in}}"),
                                     "features": FEATS}]})),
        *[text("Wrote 1 post; its meaning check is pending.")] * 2,  # asked once more after working
    )
    checker.push(ProviderError("busy"))  # generate_copy's automatic meaning check: left pending
    out = await runtime.run(ctx, "Facts locked")
    assert out["status"] == "done", out
    assert [(s["agent"], s["tool"]) for s in out["steps"]] == [("orchestrator", "ask_writer")]

    # the Writer worked on its own model, with only its own tools
    assert {t["function"]["name"] for t in writer.requests[0]["tools"]} == set(WRITER.tools)
    assert json.loads(writer.requests[0]["messages"][1]["content"])["task"]["task"].startswith("Write the WhatsApp")
    # the hand-off result told the Orchestrator what the Writer did
    report = json.loads(next(m["content"] for m in orch.requests[1]["messages"] if m["role"] == "tool"))
    assert report["agent"] == "Writer" and report["summary"].startswith("Wrote 1 post")
    (piece,) = report["steps"][0]["result"]["assets"]
    assert piece["status"] == "valid"

    # --- 2. the Orchestrator asks the Checker, on a different model, to re-check it
    orch.push(calls(("ask_checker", {"task": "Re-check the pending post", "asset_ids": [piece["asset_id"]]})),
              *[text("The Checker passed the post.")] * 2)
    checker.push(
        calls(("validate_assets", {"asset_ids": [piece["asset_id"]]})),
        text(json.dumps({"audits": [{
            "ref": piece["asset_id"], "back_translation": "20% off filter coffee + masala vada this weekend.",
            "claims": [{"claim": "20% off", "supported": True, "fact_key": "discount"}],
            "intent_preserved": True}]})),
        *[text("1 post passed.")] * 2,
    )
    out = await runtime.run(ctx, "Check pending posts")
    assert out["status"] == "done", out
    assert {t["function"]["name"] for t in checker.requests[1]["tools"]} == set(CHECKER.tools)
    report = json.loads(next(m["content"] for m in orch.requests[-1]["messages"] if m["role"] == "tool"))
    assert report["agent"] == "Checker"
    assert report["steps"][0]["result"]["results"][piece["asset_id"]] == {"passed": True, "l3": "passed"}

    # the owner's work log shows each hand-off and who did what
    async with connection() as conn:
        events = await fetch_all(conn, "select type, summary from ledger_events where campaign_id = %s order by id",
                                 (ctx.campaign_id,))
    summaries = [e["summary"] for e in events]
    assert "Asked the Writer: Write the WhatsApp post for students" in summaries
    assert any(s.startswith("Writer: Generate copy") for s in summaries)
    assert "Checker: 1 post passed." in summaries
    # model calls are tagged with the team member that made them
    assert {c["agent"] for c in router.calls_for(str(ctx.business["id"]))} >= {"orchestrator", "writer", "checker"}


async def test_orchestrator_cannot_write_posts_itself(client, scripted):
    ctx = await _locked_campaign(client, scripted)
    router, orch, _writer, _checker = _team_router()
    ctx.router = router
    orch.push(calls(("generate_copy", {"cells": [{"segment": "students", "channel": "whatsapp", "language": "en",
                                                  "angle": "x"}]})),
              text("Handing it over."), text("Done."))
    out = await runtime.run(ctx, "Write posts")
    assert out["steps"][0]["ok"] is False
    told = json.loads(next(m["content"] for m in orch.requests[1]["messages"] if m["role"] == "tool"))
    assert "belongs to the Writer" in told["error"] and "ask_writer" in told["error"]


async def test_specialists_cannot_publish_or_lock(client, scripted):
    """If the Writer's model tries to publish, it is refused before the tool runs; nothing is queued either."""
    ctx = await _locked_campaign(client, scripted)
    router, orch, writer, _checker = _team_router()
    ctx.router = router
    orch.push(calls(("ask_writer", {"task": "Write and publish"})), *[text("Done.")] * 2)
    writer.push(calls(("publish_assets", {"asset_ids": ["x"], "summary": "go live"})), *[text("Could not.")] * 2)
    await runtime.run(ctx, "Write and publish")
    told = json.loads(next(m["content"] for m in writer.requests[1]["messages"] if m["role"] == "tool"))
    assert "not one of your tools" in told["error"]
    async with connection() as conn:
        queued = await fetch_all(conn, "select id from inbox_items where campaign_id = %s and kind = 'approval'",
                                 (ctx.campaign_id,))
    assert queued == []
