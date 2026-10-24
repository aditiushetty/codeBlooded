"""How a campaign is doing, read the same way by the campaign page and by the Analyst agent.

Wraps domain/analytics.summarize with the database reads around it: live posts, tracked outcomes, experiments,
visit ratings, channel delivery and come-back codes.
"""

import asyncio
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import services, usage
from app.channels import instagram, whatsapp
from app.config import get_settings
from app.db import Conn, connection, fetch_all, fetch_one
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


async def business_hours(conn: Conn, business_id: Any) -> list[dict[str, Any]] | None:
    """When the business's customers were active in the last 60 days, by hour: every campaign's link opens, claims
    and visits, and every Instagram comment (spam left out). None when there is nothing yet."""
    times = [r["at"] for r in await fetch_all(
        conn, """select o.occurred_at at time zone 'Asia/Kolkata' as at from outcome_events o
                 join campaigns c on c.id = o.campaign_id
                 where c.business_id = %s and not c.is_historical and o.type in ('scan', 'click', 'redeem')
                   and o.occurred_at > now() - interval '60 days'
                 union all
                 select occurred_at at time zone 'Asia/Kolkata' from customer_interactions
                 where business_id = %s and source = 'instagram_comment' and coalesce(category, '') <> 'spam'
                   and occurred_at > now() - interval '60 days'""", (business_id, business_id))]
    return analytics.hour_profile(times) if times else None


async def _on_own(fn: Any, *args: Any, **kw: Any) -> Any:
    """Run a read on its own pooled connection, so independent reads go out together: each one is a round trip to
    the database, and a campaign page needs about twenty."""
    async with connection() as conn:
        return await fn(conn, *args, **kw)


async def campaign(conn: Conn, c: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Read-only; `conn` is the caller's, the reads themselves run side by side on their own connections."""
    cid = c["id"]
    posts, events, exp_ids, ratings, accounts, repeat, comments, effort_out, spent = await asyncio.gather(
        _on_own(fetch_all, """select a.id::text as asset_id, t.code, a.channel, a.language, a.segment, a.variant,
                                     r.rendered->>'headline' as headline
                              from touchpoints t join assets a on a.id = t.asset_id
                              left join asset_revisions r on r.asset_id = a.id and r.n = a.current_revision
                              where t.campaign_id = %s order by a.created_at""", (cid,)),
        _on_own(fetch_all, """select asset_id::text, type, qty, source, occurred_at at time zone 'Asia/Kolkata' as at,
                        o.meta->>'via' as via, o.meta ? 'claim' as with_claim,
                        (meta->>'bill_amount')::float as bill, coalesce((meta->>'return')::boolean, false) as is_return,
                        (coalesce((o.meta->>'from_link')::boolean, false) or exists (
                              select 1 from claims cl where cl.code = o.meta->>'claim' and cl.via = 'web')) as from_link
                 from outcome_events o where campaign_id = %s""", (cid,)),
        _on_own(fetch_all, "select id from experiments where campaign_id = %s and status <> 'decided'", (cid,)),
        _on_own(fetch_all, """select asset_id::text as asset_id, count(*)::int as n,
                                     round(avg(rating)::numeric, 1)::float as average
                              from customer_interactions where campaign_id = %s and source = 'visit_review'
                                and rating is not null group by asset_id""", (cid,)),
        _on_own(fetch_all, """select channel from channel_accounts where business_id = %s
                              and channel in ('instagram', 'whatsapp')""", (b["id"],)),
        _on_own(fetch_one, """select count(*)::int as issued, count(*) filter (where status = 'redeemed')::int as came_back,
                        count(*) filter (where status = 'claimed' and valid_until >= %s)::int as waiting
                 from claims where campaign_id = %s and kind = 'return'""", (today(), cid)),
        _on_own(fetch_all, """select ci.occurred_at at time zone 'Asia/Kolkata' as at from customer_interactions ci
                              join instagram_media m on m.media_id = ci.media_id
                              join assets a on a.id = m.asset_id
                              where a.campaign_id = %s and ci.source = 'instagram_comment'
                                and coalesce(ci.category, '') <> 'spam'""", (cid,)),
        _on_own(effort_for, cid),
        _on_own(usage.spent, campaign_id=cid))
    ids = [p["asset_id"] for p in posts]
    wa_stats, ig_stats, *exps = await asyncio.gather(
        _on_own(whatsapp.stats, ids), _on_own(instagram.stats, ids),
        *(_on_own(services.experiment_status, e["id"]) for e in exp_ids))
    ratings = {r["asset_id"]: {"n": r["n"], "average": r["average"]} for r in ratings}
    connected = {r["channel"] for r in accounts}
    channels = {"whatsapp": wa_stats, "instagram": ig_stats, "instagram_connected": "instagram" in connected,
                "whatsapp_connected": "whatsapp" in connected}
    comments = [r["at"] for r in comments]
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
                                     e["decision"]["winner"]), "arms": e["arms"]} for e in exps],
        comments=comments)
    if not any(h["active"] for h in out["hours"]):
        # Nothing for this campaign yet: the business's last 60 days say when its customers are around.
        out["hours_overall"] = await business_hours(conn, b["id"])
    out["channels"] = channels
    out["ratings"] = ratings  # stars from verified visits, per post that brought them
    out["repeat"] = {"days": c.get("return_days"), **(repeat or {}),
                     "rate": round(repeat["came_back"] / repeat["issued"], 4) if repeat and repeat["issued"] else None}
    out["effort"] = effort_out
    out["ai"] = {**spent, **economics.return_on_ai(spent["rupees"], out["totals"]["sales"], out["totals"]["redeems"])}
    out["experiments"] = [{"id": str(e["experiment"]["id"]), "hypothesis": e["experiment"]["hypothesis"],
                           "arms": e["arms"], "decision": e["decision"]} for e in exps]
    return out
