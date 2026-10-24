"""The Brief agent, the Analyst and the Customer listener; and come-back codes, bill matching, WhatsApp templates,
Google Business Profile offers, the spoken menu and photo reels."""

import json
from datetime import date, datetime, timedelta

import pytest

from app.agent import runtime
from app.agent.team import ANALYST, BRIEF, LISTENER, ORCHESTRATOR
from app.channels import google_business
from app.db import connection, fetch_one, jsonb
from app.domain import analyst, bills, brief, wa_template
from tests.fakes import calls, text
from tests.test_channels import fake_meta, live_post  # noqa: F401  (fixture)
from tests.test_flow import ctx_for

# ------------------------------------------------------------------ who may do what


def test_new_agents_own_their_tools():
    assert {"ask_brief", "ask_analyst", "ask_listener"} <= set(ORCHESTRATOR.tools)
    # the plan, results and reviews belong to their agents now
    assert not {"set_campaign_plan", "propose_next_move", "draft_replies", "decide_experiment"} & set(ORCHESTRATOR.tools)
    assert "set_campaign_plan" in BRIEF.tools and "propose_next_move" in ANALYST.tools
    for a in (BRIEF, ANALYST, LISTENER):  # nobody but the owner locks or publishes
        assert not {"lock_facts", "publish_assets", "draft_offer_facts"} & set(a.tools)
    assert ANALYST.role != ORCHESTRATOR.role  # results are judged on another model chain than the one that planned


# ------------------------------------------------------------------ Brief agent


def test_plan_rules():
    good = {"cells": [{"segment": "students", "channel": "whatsapp", "language": "kn"}]}
    goal = {"statement": "x", "kpi": {"metric": "redemptions", "target": 40, "window_days": 14}}
    assert brief.problems(goal, good, ["kn", "en"]) == []
    bad = {"cells": [{"segment": "students", "channel": "billboard", "language": "ta"}]}
    out = " ".join(brief.problems({"statement": "more sales"}, bad, ["kn", "en"]))
    assert "billboard" in out and "'ta'" in out and "number" in out
    # The owner connected Instagram so campaigns post there: a plan without an Instagram post is sent back.
    assert "instagram_post" in " ".join(brief.problems(goal, good, ["kn", "en"], frozenset({"instagram"})))
    assert brief.problems(goal, {"cells": [*good["cells"], {"segment": "students", "channel": "instagram_post",
                                                             "language": "en"}]}, ["kn", "en"], frozenset({"instagram"})) == []


async def test_brief_agent_saves_a_plan_the_team_can_carry_out(client, scripted):
    r = await client.post("/api/businesses/kaapi-kone/campaigns", json={"brief": "exam week coffee", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    plan = {"name": "Exam week", "goal": {"statement": "Fill evenings", "kpi": {"metric": "redemptions", "target": 30,
                                                                                 "window_days": 10}},
            "intent": {"core_message": "a break from studying", "tone": "warm"}}
    refused = await runtime.execute(ctx, "set_campaign_plan", {**plan, "plan": {"cells": [
        {"segment": "students", "channel": "whatsapp", "language": "ta"}]}})
    assert "does not use language 'ta'" in refused["error"]
    reach = await runtime.execute(ctx, "get_reach", {})
    assert reach["languages"] == ["kn", "en", "hi"] and reach["channels"]["poster"]["connected"]
    ok = await runtime.execute(ctx, "set_campaign_plan", {**plan, "plan": {"cells": [
        {"segment": "students", "channel": "whatsapp", "language": "kn"},
        {"segment": "students", "channel": "instagram_post", "language": "en"},
        {"segment": "students", "channel": "poster", "language": "en"}]}})
    assert ok["ok"], ok


async def test_brief_questions_wake_the_brief_agent(client, scripted, monkeypatch):
    r = await client.post("/api/businesses/kaapi-kone/campaigns", json={"brief": "something for diwali", "run_agent": False})
    ctx = await ctx_for(client, r.json()["id"])
    ctx.agent = "brief"
    q = await runtime.execute(ctx, "ask_owner", {"question": "Who is this mainly for?", "options": ["Families", "Students"],
                                                 "why": "It decides the channels and language."})
    seen = []

    async def fake_run(_ctx, trigger):
        seen.append(trigger)

    monkeypatch.setattr(runtime, "run", fake_run)
    d = await client.post(f"/api/inbox/{q['question_id']}/decision", json={"approve": True, "note": "Families"})
    assert d.status_code == 200
    assert "Brief agent" in seen[0] and "finish the campaign plan" in seen[0]


# ------------------------------------------------------------------ Analyst


def _results(scans=40, redeems=9, claims=15) -> dict:
    return {"totals": {"posts": 2, "scans": scans, "claims": claims, "redeems": redeems, "returns": 2,
                       "claim_rate": claims / scans, "redeem_rate": redeems / claims, "conversion": redeems / scans,
                       "return_rate": 2 / 9, "sales": 4200.0},
            "by": {"language": [{"key": "kn", "scans": 30, "redeems": 8, "conversion": 8 / 30, "likely": [0.15, 0.4]},
                                {"key": "en", "scans": 10, "redeems": 1, "conversion": 0.1, "likely": [0.02, 0.3]}]},
            "posts": [], "daily": [], "hours": [], "repeat": {"issued": 9, "came_back": 2}, "experiments": []}


def test_analyst_may_quote_only_numbers_in_the_results():
    r = _results()
    assert analyst.unsupported("Kannada: 8 of 30 who opened came in (27%), 2.7x the English rate; ₹4,200 so far", r) == []
    assert analyst.unsupported("Kannada converts 45% and brought 120 people", r) == ["45%", "120"]
    assert analyst.unsupported("Run it till 31 Oct, around 6 pm", r) == []  # dates and hours are not results
    assert analyst.too_early(_results(scans=4, redeems=0, claims=1))


def test_analyst_cannot_bet_on_a_lucky_difference():
    r = {**_results(), "tips": [{"kind": "weak_redeem", "title": "Only 9% of claimed codes are redeemed"}]}
    assert "cannot tell yet" in analyst.unsupported_move("more_of_what_works", r)  # type: ignore[operator]
    assert analyst.unsupported_move("remind_claimers", r) is None
    sure = {**r, "tips": [{"kind": "best_language", "title": "Kannada converts 2.7x as often as English"}]}
    assert analyst.unsupported_move("more_of_what_works", sure) is None and analyst.sure_findings(sure)


async def _live_campaign_with_results() -> tuple[str, str]:
    asset_id, code = await live_post("whatsapp")
    async with connection() as conn:
        a = await fetch_one(conn, "select campaign_id from assets where id = %s", (asset_id,))
        rows = [("scan",)] * 30 + [("click",)] * 12 + [("redeem",)] * 6
        for (t,) in rows:  # the redemptions are codes got from the link
            await conn.execute("""insert into outcome_events (campaign_id, asset_id, touchpoint_code, type, source, meta)
                                  values (%s, %s, %s, %s, 'live', %s)""",
                               (a["campaign_id"], asset_id, code, t, jsonb({"from_link": True} if t == "redeem" else {})))
    return str(a["campaign_id"]), asset_id


async def test_analyst_proposes_a_move_backed_by_real_numbers(client, scripted):
    cid, _ = await _live_campaign_with_results()
    ctx = await ctx_for(client, cid)
    res = await runtime.execute(ctx, "get_results", {})
    assert res["totals"]["scans"] == 30 and res["totals"]["redeems"] == 6 and res["too_early"] is None
    move = {"kind": "share_more", "title": "Share the WhatsApp post again", "instruction": "Send the post to regulars"}
    bad = await runtime.execute(ctx, "propose_next_move", {**move, "why": "It converts 45%.", "evidence": ["45% came in"]})
    assert "not in the results" in bad["error"] and "45%" in bad["error"]
    ok = await runtime.execute(ctx, "propose_next_move", {**move, "why": "6 of 30 who opened came in (20%).",
                                                          "evidence": ["30 opens, 12 codes claimed, 6 redeemed"]})
    assert ok["ok"]
    item = await fetch_one_item(ok["inbox_item_id"])
    assert item["payload"]["instruction"] == "Send the post to regulars" and item["payload"]["asked_by"] == "analyst"


async def fetch_one_item(item_id: str) -> dict:
    async with connection() as conn:
        return await fetch_one(conn, "select * from inbox_items where id = %s", (item_id,))  # type: ignore[return-value]


async def test_owner_runs_the_analyst_directly_and_a_yes_becomes_the_teams_task(client, scripted, monkeypatch):
    cid, _ = await _live_campaign_with_results()
    scripted.push(calls(("get_results", {})),
                  calls(("propose_next_move", {"kind": "share_more", "title": "Put the QR on the counter too",
                                               "why": "12 claimed a code but 6 came in.", "evidence": ["6 of 12 redeemed"],
                                               "instruction": "Make a counter poster for regulars"})),
                  *[text("30 opens, 6 redeemed; suggested a counter poster.")] * 2)
    ctx = await ctx_for(client, cid)
    out = await runtime.run_specialist(ctx, ANALYST, "Read the results")
    assert out["status"] == "done"
    async with connection() as conn:
        item = await fetch_one(conn, """select id from inbox_items where campaign_id = %s and kind = 'recommendation'
                                        and status = 'pending'""", (cid,))
        kinds = [r["type"] for r in await (await conn.execute(
            "select type from ledger_events where campaign_id = %s order by id", (cid,))).fetchall()]
    assert "agent.started" in kinds and "analyst.suggested" in kinds and "agent.handoff" not in kinds
    seen = []

    async def fake_run(_ctx, trigger):
        seen.append(trigger)

    monkeypatch.setattr(runtime, "run", fake_run)
    await client.post(f"/api/inbox/{item['id']}/decision", json={"approve": True})
    assert "Do it: Make a counter poster for regulars" in seen[0]
    assert (await client.post(f"/api/campaigns/{cid}/analyst")).status_code == 200


# ------------------------------------------------------------------ Customer listener


async def _reviews(theme: str, n: int) -> list[str]:
    async with connection() as conn:
        b = await fetch_one(conn, "select id from businesses where slug = 'kaapi-kone'")
        ids = []
        for i in range(n):
            row = await fetch_one(conn, """insert into customer_interactions (business_id, source, language, rating, body,
                                                 sentiment, themes, occurred_at, category)
                                           values (%s, 'google_review', 'en', 2, %s, -0.6, %s, now(), 'complaint')
                                           returning id""",
                                  (b["id"], f"Waited 20 minutes in the evening queue ({i})", [theme]))
            ids.append(str(row["id"]))  # type: ignore[index]
    return ids


async def test_listener_raises_issues_drafts_replies_and_suggests_a_follow_up(client, scripted, monkeypatch):
    ids = await _reviews("slow_evening_queue", 2)
    ctx = await ctx_for(client, None)  # type: ignore[arg-type]
    todo = await runtime.execute(ctx, "get_reviews_to_answer", {})
    assert set(ids) <= {r["id"] for r in todo["reviews"]}

    assert "at least two" in (await runtime.execute(ctx, "raise_issue", {
        "theme": "slow_evening_queue", "title": "Evening queue too long", "detail": "2 said so", "review_ids": [ids[0], ids[0]]}
    ))["error"]
    wrong = await runtime.execute(ctx, "raise_issue", {"theme": "parking", "title": "No parking at all",
                                                       "detail": "x", "review_ids": ids})
    assert "tagged with 'parking'" in wrong["error"]
    issue = await runtime.execute(ctx, "raise_issue", {"theme": "slow_evening_queue", "title": "Evening queue too long",
                                                       "detail": "2 people this week", "review_ids": ids})
    assert issue["ok"]

    scripted.push(text(json.dumps({"reply": "Sorry about the wait. We have added a second counter in the evening."})),
                  text(json.dumps({"reply": "Thank you for telling us. Come by again soon."})))
    drafted = await runtime.execute(ctx, "draft_replies", {"review_ids": ids})
    assert len(drafted["drafts"]) == 2
    rows = (await client.get("/api/businesses/kaapi-kone/customers")).json()["recent"]
    assert any(r["reply_draft"] for r in rows if r["id"] in ids) and all(r["reply"] is None for r in rows if r["id"] in ids)

    assert "Not on the menu" in (await runtime.execute(ctx, "suggest_campaign", {
        "title": "Win back the evening crowd", "brief": "Free croissant with coffee for people who waited",
        "why": "x", "items": ["Croissant"], "review_ids": ids}))["error"]
    s = await runtime.execute(ctx, "suggest_campaign", {
        "title": "Win back the evening crowd", "brief": "Filter coffee and masala vada combo at 10% off on weekday "
        "evenings for two weeks, now that the queue is shorter", "why": "Two people left after waiting",
        "items": ["Filter coffee", "Masala vada"], "review_ids": ids})
    monkeypatch.setattr(runtime, "run", lambda *_a: None)
    d = (await client.post(f"/api/inbox/{s['inbox_item_id']}/decision", json={"approve": True, "resume": False})).json()
    async with connection() as conn:
        c = await fetch_one(conn, "select brief from campaigns where id = %s", (d["campaign_id"],))
    assert c["brief"].startswith("Filter coffee and masala vada combo")  # type: ignore[index]


# ------------------------------------------------------------------ come-back codes


async def test_come_back_codes_bring_a_second_visit_and_count_apart(client):
    asset_id, post = await live_post("whatsapp")
    async with connection() as conn:
        cid = (await fetch_one(conn, "select campaign_id from assets where id = %s", (asset_id,)))["campaign_id"]  # type: ignore[index]
    assert (await client.put(f"/api/campaigns/{cid}/return-codes", json={"days": 14})).status_code == 200
    code = (await client.post(f"/api/public/r/{post}/claim", json={"device": "phone-aaaaaaaa"})).json()["code"]
    used = (await client.post("/api/counter/redeem", json={"code": code, "bill_amount": 180})).json()
    back = used["return_code"]
    assert back and back["valid_until"] == str(date.today() + timedelta(days=14))
    status = (await client.get(f"/api/public/claims/{code}")).json()
    assert status["come_back"]["code"] == back["code"]

    # not on the same day: it is for the next visit
    chk = (await client.post("/api/counter/check", json={"code": back["code"]})).json()
    assert chk["verdict"] == "not_valid" and "works from" in chk["reason"] and chk["come_back"]
    async with connection() as conn:
        await conn.execute("update claims set valid_from = current_date - 1 where code = %s", (back["code"],))
    again = (await client.post("/api/counter/redeem", json={"code": back["code"], "bill_amount": 150})).json()
    assert again["verdict"] == "redeemed" and "return_code" not in again  # no chain of codes

    a = (await client.get(f"/api/campaigns/{cid}/analytics")).json()
    assert a["totals"]["redeems"] == 1 and a["totals"]["returns"] == 1 and a["totals"]["sales"] == 330
    assert a["repeat"] == {"days": 14, "issued": 1, "came_back": 1, "waiting": 0, "rate": 1.0}


# ------------------------------------------------------------------ bills


STATEMENT = """Statement of account
Date,Time,Narration,Amount,Dr/Cr
{d},{t1},UPI/ravi/{code},180.00,CR
{d},{t2},UPI/asha,95.00,CR
{d},{t3},UPI/refund,40.00,DR
"""


def test_statement_payments_match_codes_by_note_then_by_time():
    ps, problems = bills.parse(STATEMENT.format(d="23/10/2026", t1="06:42 PM", t2="07:10 PM", t3="07:30 PM", code="K7QF3MA"))
    assert [p["amount"] for p in ps] == [180.0, 95.0] and not problems
    red = [{"code": "K7QF3MA", "post_code": "K7QF3M", "at": datetime(2026, 10, 23, 19, 30), "bill_amount": None},
           {"code": "ABCDEFG", "post_code": "K7QF3M", "at": datetime(2026, 10, 23, 19, 5), "bill_amount": None},
           {"code": "HJKMNPQ", "post_code": "K7QF3M", "at": datetime(2026, 10, 23, 19, 12), "bill_amount": None}]
    out = bills.match(ps, red)
    assert [(m["code"], m["how"]) for m in out["matches"]] == [("K7QF3MA", "code")]
    # 95 at 7:10 sits between two redemptions: left unmatched rather than guessed
    assert set(out["unmatched_codes"]) == {"ABCDEFG", "HJKMNPQ"}
    assert bills.parse("name,phone\nx,1")[0] == []


async def test_bill_import_fills_sales_per_post(client):
    asset_id, post = await live_post("poster")
    code = (await client.post(f"/api/public/r/{post}/claim", json={"device": "phone-bbbbbbbb"})).json()["code"]
    await client.post("/api/counter/redeem", json={"code": code})
    # at an hour no other test redeems, so only this redemption is near the payment
    now = datetime.now(runtime_tz()).replace(hour=3, minute=17, second=0, microsecond=0)
    async with connection() as conn:
        await conn.execute("""update outcome_events set occurred_at = %s where meta->>'claim' = %s""", (now, code))
    csv_text = STATEMENT.format(d=now.strftime("%d/%m/%Y"), t1=(now + timedelta(minutes=3)).strftime("%I:%M %p"),
                                t2=(now + timedelta(hours=3)).strftime("%I:%M %p"), t3="11:59 PM", code="NOCODE")
    preview = (await client.post("/api/businesses/kaapi-kone/bills/import", json={"text": csv_text})).json()
    assert [m["code"] for m in preview["matches"]] == [code] and preview["matches"][0]["how"] == "time"
    async with connection() as conn:
        assert (await fetch_one(conn, "select bill_amount from claims where code = %s", (code,)))["bill_amount"] is None  # type: ignore[index]
    done = (await client.post("/api/businesses/kaapi-kone/bills/import", json={"text": csv_text, "apply": True})).json()
    assert done["applied"]
    async with connection() as conn:
        assert float((await fetch_one(conn, "select bill_amount from claims where code = %s", (code,)))["bill_amount"]) == 180  # type: ignore[index]


def runtime_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Kolkata")


# ------------------------------------------------------------------ WhatsApp templates


def test_template_rules_catch_what_meta_rejects():
    t = wa_template.draft(business_slug="kaapi-kone", post_code="K7QF3M", language="kn", headline="ಸಂಜೆ ಕಾಫಿ",
                          body="ಬನ್ನಿ.", offer=["15% ರಿಯಾಯಿತಿ"], link="https://x.app/r/K7QF3M")
    assert t["name"] == "kaapi_kone_k7qf3m_kn" and wa_template.problems(t) == []
    assert "{{1}}" in t["body"] and not t["body"].rstrip(".").endswith("}}")
    bad = {**t, "name": "Kaapi Kone!", "body": "{{1}} {{2}}", "footer": "x" * 61, "example": []}
    out = " ".join(wa_template.problems(bad))
    assert "lowercase" in out and "first or last" in out and "side by side" in out and "footer" in out and "example" in out


async def test_template_is_drafted_submitted_and_approved_by_webhook(client, fake_meta, monkeypatch):  # noqa: F811
    from tests.test_channels import signed

    asset_id, _ = await live_post("whatsapp")

    async def graph(method, url, *, token, params=None, json=None, bearer=True):
        if url.endswith("/message_templates") and method == "POST":
            fake_meta.calls.append((method, url, json))
            return {"id": "tmpl-1", "status": "PENDING", "category": "MARKETING"}
        return await fake_meta(method, url, token=token, params=params, json=json, bearer=bearer)

    monkeypatch.setattr("app.channels.meta.graph", graph)
    await client.put("/api/businesses/kaapi-kone/channels/whatsapp",
                     json={"phone_number_id": "1234567890", "token": "EAAG" + "x" * 40, "waba_id": "555"})
    t = (await client.post(f"/api/assets/{asset_id}/whatsapp/template")).json()
    assert t["status"] == "draft" and t["problems"] == [] and "Evening coffee" in t["body"] and "15% off" in t["body"]
    sent = (await client.post(f"/api/whatsapp-templates/{t['id']}/submit")).json()
    assert sent["status"] == "pending"
    body = fake_meta.calls[-1][2]
    assert body["category"] == "MARKETING" and body["components"][0]["example"]["body_text"][0][0].endswith("/r/" + t["name"].split("_")[-2].upper())

    raw, headers = signed({"object": "whatsapp_business_account", "entry": [{"id": "555", "changes": [{
        "field": "message_template_status_update", "value": {"event": "APPROVED", "message_template_id": "tmpl-1",
                                                              "message_template_name": t["name"],
                                                              "message_template_language": "en"}}]}]})
    assert (await client.post("/api/public/whatsapp/webhook", content=raw, headers=headers)).status_code == 200
    listed = (await client.get("/api/businesses/kaapi-kone/whatsapp-templates")).json()
    assert next(x for x in listed["templates"] if x["id"] == t["id"])["status"] == "approved"
    async with connection() as conn:
        await conn.execute("delete from channel_accounts where channel = 'whatsapp'")


# ------------------------------------------------------------------ Google Business Profile


def test_google_offer_post_uses_the_locked_offer():
    post = google_business.offer_post(language="en", headline="Evening coffee", body="Come by.", offer=["15% off"],
                                      conditions=["With a college ID"], code="K7QF3M", link="https://x.app/r/K7QF3M",
                                      starts_on=date(2026, 10, 24), ends_on=date(2026, 11, 2), photo_url=None)
    assert post["topicType"] == "OFFER" and post["offer"]["couponCode"] == "K7QF3M"
    assert post["event"]["schedule"]["endDate"] == {"year": 2026, "month": 11, "day": 2}
    assert "With a college ID" in post["offer"]["termsConditions"] and "15% off" in post["summary"]
    assert any("photo" in p for p in google_business.problems(post))


async def test_google_connect_and_publish(client, monkeypatch):
    from pydantic import SecretStr

    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "google_oauth_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_oauth_client_secret", SecretStr("shh"))
    seen = []

    async def http(method, url, *, token=None, data=None, json=None, params=None):
        seen.append((method, url, json or data))
        if url == google_business.TOKEN:
            return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
        if url == google_business.ACCOUNTS:
            return {"accounts": [{"name": "accounts/1"}]}
        if url.endswith("accounts/1/locations"):
            return {"locations": [{"name": "locations/9", "title": "Kaapi Kone"}]}
        if url.endswith("/localPosts"):
            return {"name": "accounts/1/locations/9/localPosts/p1", "searchUrl": "https://g.page/x", "state": "LIVE"}
        raise AssertionError(url)

    monkeypatch.setattr(google_business, "http", http)
    url = (await client.get("/api/businesses/kaapi-kone/channels/google/connect")).json()["url"]
    state = url.split("state=")[1]
    assert (await client.get("/api/public/google/callback", params={"state": "forged.x.1.y", "code": "c"})).status_code == 303
    r = await client.get("/api/public/google/callback", params={"state": state.replace("%2E", "."), "code": "c"})
    assert r.status_code == 303 and r.headers["location"].endswith("google=connected")

    asset_id, _ = await live_post("instagram_post")
    async with connection() as conn:
        cid = (await fetch_one(conn, "select campaign_id from assets where id = %s", (asset_id,)))["campaign_id"]  # type: ignore[index]
        await conn.execute("update campaigns set starts_on = current_date, ends_on = current_date + 7 where id = %s", (cid,))
    g = (await client.get(f"/api/assets/{asset_id}/google-post")).json()
    assert g["connected"] and g["post"]["offer"]["couponCode"]
    out = (await client.post(f"/api/assets/{asset_id}/google-post")).json()
    assert out["state"] == "LIVE" and seen[-1][1].endswith("accounts/1/locations/9/localPosts")
    async with connection() as conn:
        await conn.execute("delete from channel_accounts where channel = 'google_business'")


# ------------------------------------------------------------------ spoken menu, reels


async def test_spoken_menu_fills_the_form_and_marks_prices_not_heard(client, scripted):
    scripted.push(text(json.dumps({"items": [
        {"name": "Masala Dosa", "price": 60, "said": "ಮಸಾಲೆ ದೋಸೆ"},
        {"name": "Filter Coffee", "price": 25, "said": "ಫಿಲ್ಟರ್ ಕಾಫಿ"}]})))
    r = await client.post("/api/onboarding/menu-speech", json={
        "text": "ಮಸಾಲೆ ದೋಸೆ 60 ರೂಪಾಯಿ, ಫಿಲ್ಟರ್ ಕಾಫಿ ಇಪ್ಪತ್ತೈದು", "language": "kn"})
    items = r.json()["items"]
    assert [(i["name"], i["check"]) for i in items] == [("Masala Dosa", False), ("Filter Coffee", True)]


async def test_reel_uses_own_photos_and_only_checked_words(client):
    asset_id, _ = await live_post("instagram_story")
    r = await client.post(f"/api/assets/{asset_id}/reel")
    if r.status_code == 409:  # the seed has no photos: the reel refuses rather than using AI pictures
        assert "own photos" in r.json()["detail"]
        async with connection() as conn:
            b = await fetch_one(conn, "select id from businesses where slug = 'kaapi-kone'")
            await conn.execute("""insert into business_photos (business_id, image_key, source, caption, kind, status)
                                  values (%s, 'photos/test-reel.jpg', 'upload', 'filter coffee in a steel tumbler',
                                          'drink', 'active')""", (b["id"],))  # type: ignore[index]
        r = await client.post(f"/api/assets/{asset_id}/reel")
    out = r.json()
    assert out["photos"] and out["script"].startswith("Evening coffee. Come by. 15% off")
    assert out["voice_url"] is None and "Sarvam" in out["voice_note"]


@pytest.fixture(autouse=True)
async def _clean_inbox(db):
    yield
    async with connection() as conn:
        await conn.execute("update inbox_items set status = 'dismissed' where status = 'pending' and "
                           "payload->>'asked_by' in ('analyst', 'listener', 'brief')")
        await conn.execute("update campaigns set return_days = null")


async def test_model_calls_are_kept_and_set_against_sales(client, scripted):
    from app import usage
    from app.main import app as fastapi_app

    cid, asset_id = await _live_campaign_with_results()
    router = fastapi_app.state.router
    router.on_call = usage.keep
    try:
        ctx = await ctx_for(client, cid)
        scripted.push(*[text("ok")] * 2)
        await runtime.run_specialist(ctx, ANALYST, "Read the results")
        import asyncio

        await asyncio.gather(*list(usage._pending))
    finally:
        router.on_call = None
    async with connection() as conn:
        await conn.execute("update outcome_events set meta = meta || '{\"bill_amount\": 300}' where campaign_id = %s "
                           "and type = 'redeem'", (cid,))
    a = (await client.get(f"/api/campaigns/{cid}/analytics")).json()
    assert a["ai"]["calls"] >= 1 and a["ai"]["input_tokens"] > 0 and a["ai"]["sales"] == 1800
    assert a["ai"]["sales_per_ai_rupee"] and a["ai"]["sales_per_ai_rupee"] > 1000
    r = (await client.get("/api/businesses/kaapi-kone/results")).json()
    assert r["ai"]["calls"] >= 1 and "effort" in r
