"""The business's own customer list and the WhatsApp messages the owner sends from their own phone: personal codes for
a campaign, then a review link once the code was used. See app/contacts.py."""

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import contacts, services
from app.api.deps import require_owner
from app.auth import CurrentUser, business_for, require_member
from app.config import get_settings
from app.db import connection, fetch_one

reach_api = APIRouter(prefix="/api", dependencies=[Depends(require_owner)])


class ContactsPaste(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    consent: bool  # the owner confirms these people agreed to hear from the business


@reach_api.get("/businesses/{slug}/contacts")
async def list_contacts(user: CurrentUser, slug: str) -> dict[str, Any]:
    base = get_settings().public_base_url
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = await contacts.listed(conn, b["id"])
    return {"contacts": rows, "segments": list(contacts.SEGMENTS), "links_public": base.startswith("https://")}


@reach_api.post("/businesses/{slug}/contacts")
async def add_contacts(user: CurrentUser, slug: str, body: ContactsPaste) -> dict[str, Any]:
    if not body.consent:
        raise services.Conflict("Add only customers who agreed to hear from you, and tick the box to say so.")
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        return await contacts.add(conn, b["id"], body.text, "Owner confirmed the customer agreed to hear from them")


class ContactEdit(BaseModel):
    opted_out: bool | None = None
    name: str | None = Field(None, max_length=80)
    language: Literal["en", "kn", "hi"] | None = None


async def _contact(conn: Any, user: Any, contact_id: str) -> dict[str, Any]:
    c = await fetch_one(conn, "select * from customers where id = %s", (contact_id,))
    if not c:
        raise services.NotFound("not found")
    await require_member(conn, user, c["business_id"])
    return c


@reach_api.patch("/contacts/{contact_id}")
async def edit_contact(user: CurrentUser, contact_id: str, body: ContactEdit) -> dict[str, Any]:
    async with connection() as conn:
        c = await _contact(conn, user, contact_id)
        await conn.execute(
            """update customers set name = coalesce(%s, name), language = coalesce(%s, language),
                 opted_out_at = case when %s::boolean is null then opted_out_at when %s::boolean then coalesce(opted_out_at, now()) end
               where id = %s""", (body.name, body.language, body.opted_out, body.opted_out, c["id"]))
    return {"ok": True}


@reach_api.delete("/contacts/{contact_id}")
async def delete_contact(user: CurrentUser, contact_id: str) -> dict[str, Any]:
    async with connection() as conn:
        c = await _contact(conn, user, contact_id)
        await conn.execute("delete from customers where id = %s", (c["id"],))
    return {"ok": True}


class InviteBody(BaseModel):
    segment: Literal["all", "new", "visited", "regulars", "lapsed"] = "all"
    contact_ids: list[str] | None = None


async def _campaign(conn: Any, user: Any, campaign_id: str) -> dict[str, Any]:
    c = await services.get_campaign(conn, campaign_id)
    await require_member(conn, user, c["business_id"])
    return c


@reach_api.get("/campaigns/{campaign_id}/invites")
async def campaign_invites(user: CurrentUser, campaign_id: str) -> dict[str, Any]:
    async with connection() as conn:
        c = await _campaign(conn, user, campaign_id)
        rows = await contacts.invites(conn, c)
    counts = {k: sum(r["status"] == k for r in rows) for k in ("ready", "sent", "came_in", "reviewed")}
    return {"invites": rows, "counts": counts, "links_public": get_settings().public_base_url.startswith("https://")}


@reach_api.post("/campaigns/{campaign_id}/invites")
async def make_invites(user: CurrentUser, campaign_id: str, body: InviteBody) -> dict[str, Any]:
    async with connection() as conn:
        c = await _campaign(conn, user, campaign_id)
    return {"made": await contacts.invite(c, body.segment, body.contact_ids)}


class SentBody(BaseModel):
    kind: Literal["invite", "review"]


@reach_api.post("/claims/{code}/sent")
async def mark_sent(user: CurrentUser, code: str, body: SentBody) -> dict[str, Any]:
    """The owner opened the prepared WhatsApp message: count it as sent (WhatsApp tells us nothing without the API)."""
    async with connection() as conn:
        cl = await fetch_one(conn, "select code, campaign_id from claims where code = %s", (code.upper(),))
        if not cl:
            raise services.NotFound("not found")
        await _campaign(conn, user, str(cl["campaign_id"]))
        col = "invited_at" if body.kind == "invite" else "review_asked_at"
        await conn.execute(f"update claims set {col} = coalesce({col}, now()) where code = %s", (cl["code"],))
    return {"ok": True}
