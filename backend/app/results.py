"""How a campaign is doing, read the same way by the campaign page and by the Analyst agent.

Wraps domain/analytics.summarize with the database reads around it: live posts, tracked outcomes, experiments,
visit ratings, channel delivery and come-back codes.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import services, usage
from app.channels import instagram, whatsapp
from app.config import get_settings
from app.db import Conn, fetch_all, fetch_one
from app.domain import analytics, culture, economics, effort

IST = ZoneInfo("Asia/Kolkata")
CHANNEL_NAMES = {"instagram_post": "Instagram posts", "instagram_story": "Instagram stories", "poster": "Counter posters",
                 "whatsapp": "WhatsApp"}
LANGUAGE_NAMES = {"en": "English", "kn": "Kannada", "hi": "Hindi"}


async def effort_for(conn: Conn, campaign_id: Any) -> dict[str, Any] | None:
    events = await fetch_all(conn, "select type, actor, created_at from ledger_events where campaign_id = %s",
                             (campaign_id,))
    return effort.summarize(events)


def today() -> date:
    return datetime.now(IST).date()


async def campaign(conn: Conn, c: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    cid = c["id"]
    posts = await fetch_all(
        conn, """select a.id::text as asset_id, t.code, a.channel, a.language, a.segment, a.variant,
                        r.rendered->>'headline' as headline
                 from touchpoints t join assets a on a.id = t.asset_id
                 left join asset_revisions r on r.asset_id = a.id and r.n = a.current_revision
                 where t.campaign_id = %s order by a.created_at""", (cid,))
    events = await fetch_all(
        conn, """select asset_id::text, type, qty, source, occurred_at at time zone 'Asia/Kolkata' as at,
                        (meta->>'bill_amount')::float as bill, coalesce((meta->>'return')::boolean, false) as is_return
                 from outcome_events where campaign_id = %s""", (cid,))
    exps = [await services.experiment_status(conn, e["id"]) for e in await fetch_all(
        conn, "select id from experiments where campaign_id = %s and status <> 'decided'", (cid,))]
    ids = [p["asset_id"] for p in posts]
    ratings = {r["asset_id"]: {"n": r["n"], "average": r["average"]} for r in await fetch_all(
        conn, """select asset_id::text as asset_id, count(*)::int as n, round(avg(rating)::numeric, 1)::float as average
                 from customer_interactions where campaign_id = %s and source = 'visit_review' and rating is not null
                 group by asset_id""", (cid,))}
    channels = {"whatsapp": await whatsapp.stats(conn, ids), "instagram": await instagram.stats(conn, ids),
                "instagram_connected": await instagram.account(conn, b["id"]) is not None,
                "whatsapp_connected": await whatsapp.account(conn, b["id"]) is not None}
    repeat = await fetch_one(
        conn, """select count(*)::int as issued, count(*) filter (where status = 'redeemed')::int as came_back,
                        count(*) filter (where status = 'claimed' and valid_until >= %s)::int as waiting
                 from claims where campaign_id = %s and kind = 'return'""", (today(), cid))
    now = today()
    created = c["created_at"].astimezone(IST).date()
    first = min((e["at"].date() for e in events), default=created)
    langs = b.get("languages") or ["en"]
    festivals = {}
    if get_settings().festivals:
        text = f"{c['name']} {c.get('brief') or ''}"
        festivals = {f.key: f for f in culture.relevant(text, c.get("starts_on"), c.get("ends_on"))}
        festivals.update({f.key: f for f, *_ in culture.upcoming(now, days=14)})
    out = analytics.summarize(
        posts, events, today=now, since=min(first, created),
        labels={"channel": CHANNEL_NAMES, "language": LANGUAGE_NAMES},
        festivals=[culture.card(f, langs, today=now) for f in festivals.values()],
        experiments=[{"winner": next((a["variant"] for a in e["arms"] if a["asset_id"] == e["decision"]["winner"]),
                                     e["decision"]["winner"]), "arms": e["arms"]} for e in exps])
    out["channels"] = channels
    out["ratings"] = ratings  # stars from verified visits, per post that brought them
    out["repeat"] = {"days": c.get("return_days"), **(repeat or {}),
                     "rate": round(repeat["came_back"] / repeat["issued"], 4) if repeat and repeat["issued"] else None}
    out["effort"] = await effort_for(conn, cid)
    spent = await usage.spent(conn, campaign_id=cid)
    out["ai"] = {**spent, **economics.return_on_ai(spent["rupees"], out["totals"]["sales"], out["totals"]["redeems"])}
    out["experiments"] = [{"id": str(e["experiment"]["id"]), "hypothesis": e["experiment"]["hypothesis"],
                           "arms": e["arms"], "decision": e["decision"]} for e in exps]
    return out
