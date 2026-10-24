"""Reaching customers who already came in, without the WhatsApp API: the business's own list (pasted with consent, or
added by a customer on their code page), a personal code per customer per campaign, and the WhatsApp message the owner
sends from their own phone (wa.me opens it ready to send). Once the code is redeemed, the same way asks for a review,
which lands on the code page as a verified visit review.

A customer's code uses the same device id as the WhatsApp bot (`whatsapp.device_for(phone)`), so if the API is
connected later, the same person messaging in gets the same code back."""

from typing import Any

from app import ledger, services
from app.channels import whatsapp
from app.config import get_settings
from app.db import Conn, connection, fetch_all, fetch_one
from app.domain import contacts

SEGMENTS = {
    "all": "true",
    "new": "s.visits = 0",
    "visited": "s.visits >= 1",
    "regulars": "s.visits >= 2",
    "lapsed": "s.visits >= 1 and s.last_visit < now() - interval '30 days'",
}
_STATS = """select c.*, coalesce(s.visits, 0) as visits, s.last_visit, coalesce(s.codes, 0) as codes,
                   coalesce(s.reviews, 0) as reviews
            from customers c left join lateral (
              select count(*) filter (where cl.status = 'redeemed')::int as visits, max(cl.redeemed_at) as last_visit,
                     count(*)::int as codes, count(ci.id)::int as reviews
              from claims cl left join customer_interactions ci on ci.claim_code = cl.code
              where cl.customer_id = c.id) s on true"""


async def add(conn: Conn, business_id: Any, text: str, consent: str) -> dict[str, Any]:
    """Paste of customers -> {added, updated, skipped}. A known number keeps its row; a new name or language fills in."""
    rows, skipped = contacts.parse(text)
    added = 0
    for r in rows:
        row = await fetch_one(
            conn, """insert into customers (business_id, phone, name, language, source, consent)
                     values (%s, %s, %s, %s, 'owner_import', %s)
                     on conflict (business_id, phone) do update set name = coalesce(excluded.name, customers.name),
                       language = coalesce(excluded.language, customers.language)
                     returning (xmax = 0) as inserted""", (business_id, r["phone"], r["name"], r["language"], consent))
        added += bool(row and row["inserted"])
    if rows:
        await ledger.record(conn, business_id, "customers.imported",
                            f"Added {added} customer{'s' if added != 1 else ''} to the WhatsApp list", actor="owner",
                            payload={"added": added, "updated": len(rows) - added, "skipped": len(skipped)})
    return {"added": added, "updated": len(rows) - added, "skipped": skipped}


async def listed(conn: Conn, business_id: Any) -> list[dict[str, Any]]:
    return await fetch_all(conn, _STATS + " where c.business_id = %s order by c.created_at desc", (business_id,))


async def _posts(conn: Conn, campaign_id: Any) -> list[dict[str, Any]]:
    """Live posts with their code, WhatsApp ones first: the code a customer gets is attributed to that post."""
    return await fetch_all(
        conn, """select distinct on (a.id) a.id, a.language, a.channel, t.code as post_code,
                        r.rendered->>'headline' as headline
                 from assets a join touchpoints t on t.asset_id = a.id
                 left join asset_revisions r on r.asset_id = a.id and r.n = a.current_revision
                 where a.campaign_id = %s and a.status = 'live' order by a.id, t.code""", (campaign_id,))


def _pick(posts: list[dict[str, Any]], lang: str | None) -> dict[str, Any]:
    def score(p: dict[str, Any]) -> tuple[int, int]:
        return (p["language"] == lang, p["channel"] == "whatsapp")
    return max(posts, key=score)


async def invite(campaign: dict[str, Any], segment: str, ids: list[str] | None) -> int:
    """Give each chosen customer their personal code for this campaign. -> codes made (already made ones are kept)."""
    async with connection() as conn:
        posts = await _posts(conn, campaign["id"])
        if not posts:
            raise services.Conflict("Approve a post for this campaign first: the code each customer gets belongs to one.")
        who = await fetch_all(
            conn, _STATS + f" where c.business_id = %s and c.opted_out_at is null and ({SEGMENTS[segment]})"
                           " and (%s::uuid[] is null or c.id = any(%s::uuid[]))",
            (campaign["business_id"], ids, ids))
        made = 0
        for c in who:
            claim, new = await services.claim(conn, _pick(posts, c["language"])["post_code"],
                                              device=whatsapp.device_for(c["phone"]), via="invite")
            await conn.execute("update claims set customer_id = %s where code = %s and customer_id is null",
                               (c["id"], claim["code"]))
            made += new
        if made:
            await ledger.record(conn, campaign["business_id"], "customers.invited",
                                f"Made personal codes for {made} customer{'s' if made != 1 else ''}", actor="owner",
                                campaign_id=campaign["id"], payload={"segment": segment, "made": made})
    return made


async def invites(conn: Conn, campaign: dict[str, Any]) -> list[dict[str, Any]]:
    """Every customer with a code for this campaign: where they are (ready, sent, came in, reviewed) and the message
    to send next, ready for wa.me."""
    base = get_settings().public_base_url.rstrip("/")
    business = await services.get_business_by_id(conn, campaign["business_id"])
    rows = await fetch_all(
        conn, """select cl.code, cl.status, cl.invited_at, cl.review_asked_at, cl.redeemed_at, cl.campaign_id,
                        c.id as customer_id, c.name, c.phone, c.opted_out_at, coalesce(c.language, a.language, 'en') as lang,
                        r.rendered->>'headline' as headline, a.language as post_language,
                        exists (select 1 from customer_interactions ci where ci.claim_code = cl.code) as reviewed
                 from claims cl join customers c on c.id = cl.customer_id
                 left join assets a on a.id = cl.asset_id
                 left join asset_revisions r on r.asset_id = a.id and r.n = a.current_revision
                 where cl.campaign_id = %s order by cl.created_at""", (campaign["id"],))
    sheet = await services.locked_sheet(conn, campaign["id"])
    out = []
    for r in rows:
        lang = r["lang"] if r["lang"] in ("en", "kn", "hi") else "en"
        offer = [f.display.get(lang) or f.display.get("en", "") for f in sheet.facts] if sheet else []
        status = ("reviewed" if r["reviewed"] else "came_in" if r["status"] == "redeemed"
                  else "sent" if r["invited_at"] else "ready")
        message = None
        if r["opted_out_at"] is None and status in ("ready", "sent"):
            text = contacts.invite_text(business["name"], r["headline"] if r["post_language"] == lang else None,
                                        offer, r["code"], base, lang)
            message = {"kind": "invite", "text": text, "link": contacts.wa_link(r["phone"], text)}
        elif r["opted_out_at"] is None and status == "came_in":
            text = contacts.review_text(business["name"], r["code"], base, lang)
            message = {"kind": "review", "text": text, "link": contacts.wa_link(r["phone"], text)}
        out.append({"code": r["code"], "customer_id": r["customer_id"], "name": r["name"], "phone": r["phone"],
                    "language": lang, "status": status, "invited_at": r["invited_at"],
                    "review_asked_at": r["review_asked_at"], "redeemed_at": r["redeemed_at"],
                    "opted_out": r["opted_out_at"] is not None, "message": message})
    return out


async def opt_in(code: str, number: str, name: str | None) -> dict[str, Any]:
    """A customer adds their WhatsApp number on their own code page, ticking that they want the next offers."""
    p = contacts.phone(number)
    if not p:
        raise services.Conflict("Type a mobile number, with +country code if it isn't Indian.")
    async with connection() as conn:
        cl = await fetch_one(conn, """select cl.code, cl.customer_id, c.business_id, a.language from claims cl
                                      join campaigns c on c.id = cl.campaign_id left join assets a on a.id = cl.asset_id
                                      where cl.code = %s""", (code.upper(),))
        if not cl:
            raise services.NotFound("This code does not exist.")
        row = await fetch_one(
            conn, """insert into customers (business_id, phone, name, language, source, consent)
                     values (%s, %s, %s, %s, 'code_page', 'Ticked "send me offers on WhatsApp" on their code page')
                     on conflict (business_id, phone) do update set opted_out_at = null,
                       name = coalesce(customers.name, excluded.name)
                     returning id""", (cl["business_id"], p, (name or "").strip()[:80] or None, cl["language"]))
        if cl["customer_id"] is None:
            await conn.execute("update claims set customer_id = %s where code = %s", (row["id"], cl["code"]))
        await ledger.record(conn, cl["business_id"], "customers.opted_in", "A customer asked for offers on WhatsApp",
                            actor="system", payload={"claim": cl["code"]})
    return {"ok": True}
