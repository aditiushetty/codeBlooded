"""The agent team: the Orchestrator hands writing to the Writer and checking to the Checker, each on its own model
with its own tools, and every tool still goes through the policy gate."""

import json
import os
from pathlib import Path

from app.agent import runtime
from app.agent.team import CHECKER, OFFER, ORCHESTRATOR, TEAM, WRITER
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


def test_offer_agent_drafts_but_never_locks():
    assert OFFER.role == "reasoning" and OFFER.key in TEAM
    assert {"draft_offer_facts", "revise_offer_facts", "ask_owner", "evaluate_offer"} <= set(OFFER.tools)
    assert not {"lock_facts", "publish_assets", "generate_copy", "validate_assets"} & set(OFFER.tools)
    # drafting moved off the Orchestrator; asking the owner to lock stays with it (and goes through the gate)
    assert "draft_offer_facts" not in ORCHESTRATOR.tools and "ask_owner" not in ORCHESTRATOR.tools
    assert {"ask_offer", "lock_facts"} <= set(ORCHESTRATOR.tools)


async def test_offer_agent_asks_the_owner_and_the_answer_comes_back(client, scripted):
    from tests.test_flow import ctx_for

    r = await client.post("/api/businesses/kaapi-kone/campaigns",
                          json={"brief": "15% off for students", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    router, orch, offer, checker = _team_router()
    ctx.router = router
    vague = [{"key": "discount", "label": "Discount", "type": "percent", "value": 15,
              "display": {"en": "15% off", "kn": "೧೫% ರಿಯಾಯಿತಿ"}}]
    question = {"question": "Until which date does the offer run?", "options": ["This week", "Till Diwali"],
                "why": "Without an end date the counter cannot tell when to stop."}
    # The Offer agent runs on the same reasoning role as the Orchestrator, so one script serves both, in turn.
    orch.push(
        calls(("ask_offer", {"task": "Turn the brief into offer facts"})),                     # Orchestrator
        calls(("get_menu", {})),                                                              # Offer agent
        calls(("draft_offer_facts", {"facts": vague, "forbidden_claims": {}, "reason": "brief"})),
        calls(("ask_owner", question), ("ask_owner", question)),  # the same question twice is asked once
        *[text("15% off for students; not ready, waiting for the end date.")] * 2,
        calls(("lock_facts", {"summary": "Lock 15% off"})),  # Orchestrator tries anyway: refused, nothing queued
        *[text("The Offer agent asked you one question.")] * 2,
    )
    checker.push(text(json.dumps({"checks": [{"key": "discount", "language": "kn", "back_translation": "15% off",
                                              "same_meaning": True, "issue": None}]})))
    out = await runtime.run(ctx, "New brief")
    assert out["status"] == "done", out
    assert [(s["tool"], s["ok"]) for s in out["steps"]] == [("ask_offer", True), ("lock_facts", False)]
    tool_msgs = [json.loads(m["content"]) for m in orch.requests[-1]["messages"] if m["role"] == "tool"]
    report, refused = tool_msgs
    assert report["agent"] == "Offer agent" and {t["function"]["name"] for t in orch.requests[1]["tools"]} == set(OFFER.tools)
    menu, drafted, first, again = (st["result"] for st in report["steps"])
    assert "Filter coffee" in {m["name"] for m in menu["menu"]}
    assert drafted["can_ask_to_lock"] is False and any("no end date" in g["issue"] for g in drafted["gaps"])
    assert again == {"ok": True, "question_id": first["question_id"], "already_asked": True}
    assert "leaves customers guessing" in refused["precondition_failed"]

    camp = (await client.get(f"/api/campaigns/{ctx.campaign_id}")).json()
    (q,) = camp["inbox"]
    assert q["kind"] == "question" and q["payload"]["options"] == ["This week", "Till Diwali"]
    # an answer is required; then it is stored with the decision
    assert (await client.post(f"/api/inbox/{q['id']}/decision", json={"approve": True, "resume": False})).status_code == 409
    r = await client.post(f"/api/inbox/{q['id']}/decision", json={"approve": True, "note": "This week", "resume": False})
    assert r.status_code == 200, r.text
    async with connection() as conn:
        (row,) = await fetch_all(conn, "select status, decision from inbox_items where id = %s", (q["id"],))
    assert row["status"] == "approved" and row["decision"]["note"] == "This week"


async def test_an_owner_answer_revises_the_draft_without_redrafting(client, scripted):
    from tests.test_flow import ctx_for

    r = await client.post("/api/businesses/kaapi-kone/campaigns", json={"brief": "15% off", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    pct = {"key": "discount", "label": "Discount", "type": "percent", "value": 15, "display": {"en": "15% off"}}
    await runtime.execute(ctx, "draft_offer_facts", {"facts": [pct], "forbidden_claims": {}, "reason": "brief"})
    # the answer adds the end date to the unlocked draft; nothing else is retyped
    end = {"key": "days", "label": "Days", "type": "date_range", "value": ["2026-10-26", "2099-11-13"],
           "display": {"en": "until 13 Nov"}}
    out = await runtime.execute(ctx, "revise_offer_facts", {"changes": [end], "reason": "owner answered"})
    assert out["ok"] and out["draft_version"] == 1, out
    assert not any("end date" in g["issue"] for g in out["gaps"])
    half = await runtime.execute(ctx, "revise_offer_facts", {"changes": [{"key": "hours", "value": "16:00-19:00"}],
                                                             "reason": "x"})
    assert "give its label, type, value and display" in half["error"]
    async with connection() as conn:
        (row,) = await fetch_all(conn, "select facts from offer_facts where campaign_id = %s", (ctx.campaign_id,))
    assert [f["key"] for f in row["facts"]] == ["discount", "days"]


def test_language_and_change_agents_never_lock_or_publish():
    from app.agent.team import CHANGE, LANGUAGE

    for a in (OFFER, CHANGE, LANGUAGE):
        assert not {"lock_facts", "publish_assets", "generate_copy", "ask_writer", "ask_offer"} & set(a.tools)
    assert LANGUAGE.tools == ("get_situation", "translate_offer") and LANGUAGE.role != CHECKER.role
    assert {"preview_change", "revise_offer_facts", "ask_owner"} <= set(CHANGE.tools)
    assert {"ask_change", "ask_language"} <= set(ORCHESTRATOR.tools)
    assert "translate_offer" not in ORCHESTRATOR.tools and "preview_change" not in ORCHESTRATOR.tools


async def test_language_agent_fixes_what_sarvam_got_wrong(client, scripted, monkeypatch):
    from app import sarvam
    from tests.test_flow import ctx_for, wording

    machine = {("Monday to Friday", "kn"): "ಶುಕ್ರವಾರ",  # fluent, and wrong: Friday only
               ("Monday to Friday", "hi"): "सोमवार से शुक्रवार", ("20% off", "kn"): "೨೦% ರಿಯಾಯಿತಿ.",
               ("20% off", "hi"): "20% छूट"}
    sent: list[tuple[str, str]] = []

    async def fake_translate(text: str, source: str, target: str = "en") -> str:
        sent.append((text, target))
        return machine.get((text, target), "same in English")

    monkeypatch.setattr(sarvam, "available", lambda: True)
    monkeypatch.setattr(sarvam, "translate", fake_translate)
    r = await client.post("/api/businesses/kaapi-kone/campaigns", json={"brief": "20% off weekdays", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    english = [{"key": "discount", "label": "Discount", "type": "percent", "value": 20, "display": {"en": "20% off"}},
               {"key": "days", "label": "Days", "type": "date_range", "value": ["2026-10-26", "2099-10-30"],
                "display": {"en": "Monday to Friday"}}]
    await runtime.execute(ctx, "draft_offer_facts", {"facts": english, "forbidden_claims": {}, "reason": "brief"})
    refused = await runtime.execute(ctx, "lock_facts", {"summary": "Lock"})
    assert "ask the Language agent" in refused["precondition_failed"] and "Discount (kn)" in refused["precondition_failed"]

    scripted.push(wording(keys=["discount", "days"], langs=("kn", "hi")))  # the model reading is satisfied...
    first = await runtime.execute(ctx, "translate_offer", {})
    rows = {(w["key"], w["language"]): w for w in first["wording"]}
    assert rows["discount", "kn"] == {"key": "discount", "language": "kn", "wording": "೨೦% ರಿಯಾಯಿತಿ", "from": "sarvam",
                                      "issue": None}  # trailing full stop dropped: it sits mid-sentence
    assert "different days" in rows["days", "kn"]["issue"]  # ...but the day rule is not
    assert first["ready"] is False and first["wording_check"] == "failed"

    scripted.push(wording(keys=["discount", "days"], langs=("kn", "hi")))
    fixed = await runtime.execute(ctx, "translate_offer", {"wording": {"days": {"kn": "ಸೋಮವಾರದಿಂದ ಶುಕ್ರವಾರದವರೆಗೆ"}}})
    rows = {(w["key"], w["language"]): w for w in fixed["wording"]}
    assert rows["days", "kn"]["from"] == "agent" and rows["days", "hi"]["from"] == "kept"
    assert fixed["ready"] is True and fixed["wording_check"] == "passed"
    assert ("Monday to Friday", "kn") in sent and sent.count(("Monday to Friday", "kn")) == 1  # not re-translated


async def test_an_offer_change_rewrites_only_what_it_must(client, scripted):
    from tests.test_flow import content, wording

    ctx = await _locked_campaign(client, scripted)
    says_days = content("{{discount}} on {{combo}}, {{days}}. {{dine_in}}")
    box_only = content("Your evening kaapi is waiting.") | {
        "body": [{"text": "Your evening kaapi is waiting.", "sources": ["brand:voice"]}]}
    scripted.push(text(json.dumps({"assets": [{"cell": 0, "content": says_days, "features": FEATS},
                                              {"cell": 1, "content": box_only, "features": FEATS}]})),
                  ProviderError("verifier down"))
    res = await runtime.execute(ctx, "generate_copy", {"cells": [
        {"segment": "students", "channel": "whatsapp", "language": "en", "variant": "A", "angle": "days"},
        {"segment": "students", "channel": "whatsapp", "language": "en", "variant": "B", "angle": "mood"}]})
    a, b = (x["asset_id"] for x in res["assets"])

    change = {"key": "days", "value": ["2099-10-11"], "display": {"en": "this Sunday", "kn": "ಈ ಭಾನುವಾರ"}}
    preview = await runtime.execute(ctx, "preview_change", {"changes": [change]})
    assert preview["changed"] == ["days"]
    assert [p["asset_id"] for p in preview["posts"]["rewrite"]] == [a]
    assert [p["asset_id"] for p in preview["posts"]["refill"]] == [b]

    scripted.push(wording())
    await runtime.execute(ctx, "revise_offer_facts", {"changes": [change], "reason": "Saturday is booked"})
    r = await client.post(f"/api/campaigns/{ctx.campaign_id}/facts/lock", params={"resume": False})
    assert r.json()["stale_assets"] == [a] and r.json()["refilled"] == [b]
    detail = (await client.get(f"/api/campaigns/{ctx.campaign_id}")).json()
    by_id = {x["id"]: x for x in detail["assets"]}
    assert by_id[a]["status"] == "stale"
    refilled = by_id[b]
    assert refilled["status"] == "valid" and refilled["revision"]["validation"]["l3"] == "pending"
    assert refilled["revision"]["facts_version"] == 2 and "this Sunday" in json.dumps(refilled["revision"]["rendered"])
