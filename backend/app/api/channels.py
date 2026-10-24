"""Connecting WhatsApp and Instagram, the WhatsApp webhook, and sending or posting through them."""

import base64
import binascii
import hmac
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import ledger, services
from app.api.deps import get_router, require_owner
from app.auth import CurrentUser, business_for, require_member
from app.channels import google_business, instagram, meta, whatsapp
from app.config import get_settings
from app.db import connection, fetch_all, fetch_one, jsonb
from app.domain import redeem, wa_template

channels_api = APIRouter(prefix="/api", dependencies=[Depends(require_owner)])
webhook = APIRouter(prefix="/api/public")


def _meta_error(e: meta.MetaError) -> services.Conflict:
    return services.Conflict(f"Meta said: {e}")


async def _not_taken(conn: Any, business_id: Any, channel: str, external_id: str, what: str) -> None:
    """One WhatsApp number or Instagram account belongs to one business (incoming messages and comments are routed
    by it), so connecting it to a second business is refused with a reason instead of a database error."""
    other = await fetch_one(conn, """select b.name from channel_accounts ca join businesses b on b.id = ca.business_id
                                     where ca.channel = %s and ca.external_id = %s and ca.business_id <> %s""",
                            (channel, external_id, business_id))
    if other:
        raise services.Conflict(f"This {what} is already connected to {other['name']}. "
                                "Disconnect it there first, or use a different one for this business.")


@channels_api.get("/businesses/{slug}/channels")
async def channels_status(user: CurrentUser, slug: str) -> dict[str, Any]:
    s = get_settings()
    base = s.public_base_url.rstrip("/")
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        rows = {r["channel"]: r for r in await fetch_all(
            conn, "select channel, display, external_id, meta, connected_at, token_expires_at from channel_accounts "
                  "where business_id = %s", (b["id"],))}
        contacts = await fetch_one(
            conn, """select count(*)::int as all, count(*) filter (where opted_out_at is null)::int as reachable,
                            count(*) filter (where opted_out_at is null and last_inbound_at > now() - interval '24 hours')::int
                              as free_now from wa_contacts where business_id = %s""", (b["id"],))
        last_in = await fetch_one(conn, """select max(created_at) as at from channel_messages
                                           where business_id = %s and direction = 'in'""", (b["id"],))
        media = await fetch_one(conn, "select count(*)::int as n from instagram_media where business_id = %s", (b["id"],))
    wa, ig, gb = rows.get("whatsapp"), rows.get("instagram"), rows.get("google_business")
    return {
        "public_url": base, "public_ok": base.startswith("https://"),
        "webhook": {"url": f"{base}/api/public/whatsapp/webhook", "verify_token_set": s.whatsapp_verify_token is not None,
                    "app_secret_set": s.meta_app_secret is not None, "last_message_at": last_in and last_in["at"]},
        "instagram_webhook": {"url": f"{base}/api/public/instagram/webhook",
                              "secret_set": (s.instagram_app_secret or s.meta_app_secret) is not None},
        "whatsapp": wa and {"display": wa["display"], "phone_number_id": wa["external_id"],
                            "template": (wa["meta"] or {}).get("template"), "connected_at": wa["connected_at"],
                            "contacts": contacts},
        "instagram": ig and {"username": ig["display"], "connected_at": ig["connected_at"], "posts_linked": media["n"]},
        "google": {"configured": google_business.configured(),
                   "account": gb and {"display": gb["display"], "connected_at": gb["connected_at"],
                                      "location": (gb["meta"] or {}).get("location"),
                                      "locations": (gb["meta"] or {}).get("locations") or []}},
    }


class WhatsAppConnect(BaseModel):
    phone_number_id: str = Field(min_length=5, max_length=40, pattern=r"^\d+$")
    token: str = Field(min_length=20, max_length=1000)
    template: str | None = Field(None, max_length=120, pattern=r"^[a-z0-9_]+$",
                                 description="Approved marketing template with 3 body variables: business, headline, link.")
    template_language: str = Field("en", max_length=10)
    waba_id: str | None = Field(None, max_length=40, pattern=r"^\d+$",
                                description="WhatsApp Business Account id, needed to submit message templates.")


@channels_api.put("/businesses/{slug}/channels/whatsapp")
async def connect_whatsapp(user: CurrentUser, slug: str, body: WhatsAppConnect) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    try:
        info = await whatsapp.check(body.phone_number_id, body.token.strip())
    except meta.MetaError as e:
        raise _meta_error(e) from e
    template = {"name": body.template, "language": body.template_language} if body.template else None
    async with connection() as conn:
        await _not_taken(conn, b["id"], "whatsapp", body.phone_number_id, "WhatsApp number")
        await conn.execute(
            """insert into channel_accounts (business_id, channel, external_id, display, token, meta)
               values (%s, 'whatsapp', %s, %s, %s, %s)
               on conflict (business_id, channel) do update set external_id = excluded.external_id,
                 display = excluded.display, token = excluded.token, meta = excluded.meta, connected_at = now()""",
            (b["id"], body.phone_number_id, info["display"], body.token.strip(), jsonb({"template": template, "name": info["name"], "waba_id": body.waba_id})))
        await ledger.record(conn, b["id"], "channel.connected", f"WhatsApp connected: {info['display']}", actor="owner")
    return {"ok": True, **info}


class InstagramConnect(BaseModel):
    token: str = Field(min_length=20, max_length=1000)


@channels_api.put("/businesses/{slug}/channels/instagram")
async def connect_instagram(user: CurrentUser, slug: str, body: InstagramConnect) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    try:
        info = await instagram.check(body.token.strip())
    except meta.MetaError as e:
        raise _meta_error(e) from e
    async with connection() as conn:
        await _not_taken(conn, b["id"], "instagram", info["user_id"], "Instagram account")
        await conn.execute(
            """insert into channel_accounts (business_id, channel, external_id, display, token, token_expires_at)
               values (%s, 'instagram', %s, %s, %s, now() + interval '60 days')
               on conflict (business_id, channel) do update set external_id = excluded.external_id,
                 display = excluded.display, token = excluded.token, connected_at = now(),
                 token_expires_at = excluded.token_expires_at""",
            (b["id"], info["user_id"], f"@{info['username']}", body.token.strip()))
        await ledger.record(conn, b["id"], "channel.connected", f"Instagram connected: @{info['username']}", actor="owner")
        acct = await instagram.account(conn, b["id"])
    try:  # DMs and comments as they happen; without it comments are still read on the watch's pace
        await instagram.subscribe(acct)
    except meta.MetaError:
        pass
    return {"ok": True, **info}


@channels_api.post("/assets/{asset_id}/instagram/code-line")
async def instagram_code_line(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    """An older post gets "Comment CODE" as the business's own comment (Instagram captions cannot be edited)."""
    b = await _business_of_asset(user, asset_id)
    try:
        return await instagram.add_code_line(b, asset_id)
    except meta.MetaError as e:
        raise _meta_error(e) from e


@channels_api.delete("/businesses/{slug}/channels/{channel}")
async def disconnect(user: CurrentUser, slug: str, channel: str) -> dict[str, Any]:
    if channel not in ("whatsapp", "instagram", "google_business"):
        raise services.NotFound("not found")
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        await conn.execute("delete from channel_accounts where business_id = %s and channel = %s", (b["id"], channel))
        await ledger.record(conn, b["id"], "channel.disconnected", f"{channel.title()} disconnected", actor="owner")
    return {"ok": True}


async def _business_of_asset(user: Any, asset_id: str) -> dict[str, Any]:
    async with connection() as conn:
        asset = await services.get_asset(conn, asset_id)
        c = await services.get_campaign(conn, asset["campaign_id"])
        await require_member(conn, user, c["business_id"])
        return await services.get_business_by_id(conn, c["business_id"])


@channels_api.post("/assets/{asset_id}/whatsapp/send")
async def send_on_whatsapp(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    """Send a live post to customers who messaged the business (free inside 24 hours, a template otherwise)."""
    b = await _business_of_asset(user, asset_id)
    return await whatsapp.broadcast(b, asset_id)


def _template_out(t: dict[str, Any]) -> dict[str, Any]:
    return {**{k: t[k] for k in ("id", "asset_id", "name", "language", "category", "body", "footer", "example", "status",
                                  "reason", "submitted_at", "updated_at")},
            "problems": wa_template.problems(t) if t["status"] in ("draft", "rejected") else []}


@channels_api.post("/assets/{asset_id}/whatsapp/template")
async def draft_whatsapp_template(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    """A message template drafted from a live post (its checked text and locked offer wording), checked against
    Meta's rules. Templates are what may be sent to customers outside the free 24-hour window."""
    b = await _business_of_asset(user, asset_id)
    async with connection() as conn:
        asset = await services.get_asset(conn, asset_id)
        tp = await fetch_one(conn, "select code from touchpoints where asset_id = %s", (asset_id,))
        if asset["status"] != "live" or not tp:
            raise services.Conflict("Approve the post first; a template needs the post's tracked link.")
        rendered = ((await services.current_revision(conn, asset_id)) or {}).get("rendered") or {}
        t = wa_template.draft(business_slug=b["slug"], post_code=tp["code"], language=asset["language"],
                              headline=rendered.get("headline", ""), body=rendered.get("body", ""),
                              offer=rendered.get("offer", []),
                              link=f"{get_settings().public_base_url.rstrip('/')}/r/{tp['code']}")
        row = await fetch_one(
            conn, """insert into wa_templates (business_id, asset_id, name, language, category, body, footer, example)
                     values (%s, %s, %s, %s, %s, %s, %s, %s)
                     on conflict (business_id, name, language) do update set body = excluded.body,
                       footer = excluded.footer, example = excluded.example, updated_at = now()
                       where wa_templates.status in ('draft', 'rejected')
                     returning *""",
            (b["id"], asset_id, t["name"], t["language"], t["category"], t["body"], t["footer"], jsonb(t["example"])))
        row = row or await fetch_one(conn, "select * from wa_templates where business_id = %s and name = %s and language = %s",
                                     (b["id"], t["name"], t["language"]))
        if row and row["status"] == "rejected":  # redrafted: back to a draft the owner can submit again
            row = await fetch_one(conn, "update wa_templates set status = 'draft' where id = %s returning *", (row["id"],))
    return _template_out(row)  # type: ignore[arg-type]


class TemplateEdit(BaseModel):
    body: str = Field(min_length=1, max_length=1100)
    footer: str | None = Field(None, max_length=80)


async def _template_for(conn: Any, user: Any, template_id: str) -> dict[str, Any]:
    t = await fetch_one(conn, "select * from wa_templates where id = %s", (template_id,))
    if not t:
        raise services.NotFound("not found")
    await require_member(conn, user, t["business_id"])
    return t


@channels_api.put("/whatsapp-templates/{template_id}")
async def edit_whatsapp_template(user: CurrentUser, template_id: str, body: TemplateEdit) -> dict[str, Any]:
    async with connection() as conn:
        t = await _template_for(conn, user, template_id)
        if t["status"] not in ("draft", "rejected"):
            raise services.Conflict("This template is already with Meta; draft a new one to change it.")
        row = await fetch_one(conn, """update wa_templates set body = %s, footer = %s, status = 'draft', updated_at = now()
                                       where id = %s returning *""", (body.body, body.footer, template_id))
    return _template_out(row)  # type: ignore[arg-type]


@channels_api.post("/whatsapp-templates/{template_id}/submit")
async def submit_whatsapp_template(user: CurrentUser, template_id: str) -> dict[str, Any]:
    async with connection() as conn:
        t = await _template_for(conn, user, template_id)
        acct = await whatsapp.account(conn, t["business_id"])
    if t["status"] not in ("draft", "rejected"):
        raise services.Conflict(f"Already {t['status']}.")
    if problems := wa_template.problems(t):
        raise services.Conflict("Fix this first: " + " ".join(problems))
    if not acct:
        raise services.Conflict("Connect WhatsApp first, on the Channels page.")
    try:
        res = await whatsapp.submit_template(acct, t)
    except meta.MetaError as e:
        raise _meta_error(e) from e
    async with connection() as conn:
        row = await fetch_one(conn, """update wa_templates set status = %s, meta_id = %s, reason = null,
                                         submitted_at = now(), updated_at = now() where id = %s returning *""",
                              (res["status"], res["id"], template_id))
        await ledger.record(conn, t["business_id"], "whatsapp.template", f"Sent WhatsApp template {t['name']} to Meta "
                            "for approval", actor="owner", payload={"template_id": template_id})
    return _template_out(row)  # type: ignore[arg-type]


@channels_api.get("/businesses/{slug}/whatsapp-templates")
async def list_whatsapp_templates(user: CurrentUser, slug: str) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        acct = await whatsapp.account(conn, b["id"])
        waiting = await fetch_one(conn, "select count(*)::int as n from wa_templates where business_id = %s and status = 'pending'",
                                  (b["id"],))
    synced, error = False, None
    if acct and waiting and waiting["n"] and (acct.get("meta") or {}).get("waba_id"):
        try:
            await whatsapp.sync_templates(acct)
            synced = True
        except meta.MetaError as e:
            error = f"Meta said: {e}"
    async with connection() as conn:
        rows = await fetch_all(conn, "select * from wa_templates where business_id = %s order by updated_at desc", (b["id"],))
    return {"templates": [_template_out(r) for r in rows], "synced": synced, "error": error,
            "can_submit": bool(acct and (acct.get("meta") or {}).get("waba_id"))}


class Picture(BaseModel):
    data_url: str = Field(max_length=12_000_000, description="The post drawn by the browser, as a JPEG data URL.")


@channels_api.post("/assets/{asset_id}/instagram/publish")
async def publish_on_instagram(user: CurrentUser, asset_id: str, body: Picture) -> dict[str, Any]:
    b = await _business_of_asset(user, asset_id)
    head, _, data = body.data_url.partition(",")
    if head != "data:image/jpeg;base64":
        raise services.Conflict("Instagram needs a JPEG picture.")
    try:
        jpeg = base64.b64decode(data, validate=True)
    except binascii.Error as e:
        raise services.Conflict("The picture did not arrive whole. Try again.") from e
    if len(jpeg) > 8 * 1024 * 1024:
        raise services.Conflict("The picture is over Instagram's 8 MB limit.")
    try:
        return await instagram.publish(b, asset_id, jpeg)
    except meta.MetaError as e:
        raise _meta_error(e) from e


@channels_api.get("/businesses/{slug}/instagram/recent")
async def instagram_recent(user: CurrentUser, slug: str) -> dict[str, Any]:
    """The account's latest posts, to link one the owner posted in the Instagram app."""
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        acct = await instagram.account(conn, b["id"])
        linked = {r["media_id"]: str(r["asset_id"]) for r in await fetch_all(
            conn, "select media_id, asset_id from instagram_media where business_id = %s", (b["id"],))}
    if not acct:
        raise services.Conflict("Connect Instagram first, on the Channels page.")
    try:
        media = await instagram.recent(acct)
    except meta.MetaError as e:
        raise _meta_error(e) from e
    return {"media": [{**m, "linked_asset": linked.get(m["id"])} for m in media]}


class LinkBody(BaseModel):
    media_id: str = Field(min_length=3, max_length=40, pattern=r"^\d+$")


@channels_api.post("/assets/{asset_id}/instagram/link")
async def instagram_link(user: CurrentUser, asset_id: str, body: LinkBody) -> dict[str, Any]:
    b = await _business_of_asset(user, asset_id)
    try:
        out = await instagram.link(b, asset_id, body.media_id)
        await instagram.sync(b["id"])
    except meta.MetaError as e:
        raise _meta_error(e) from e
    return out


@channels_api.get("/businesses/{slug}/instagram/overview")
async def instagram_overview(user: CurrentUser, slug: str, refresh: bool = False) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    try:
        data = await instagram.overview(b, force=refresh)
    except meta.MetaError as e:
        raise _meta_error(e) from e
    return {"connected": data is not None, **(data or {})}


@channels_api.post("/businesses/{slug}/instagram/sync")
async def instagram_sync(user: CurrentUser, slug: str, request: Request) -> dict[str, Any]:
    """Re-read insights and read new comments now."""
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    try:
        return {"updated": await instagram.sync(b["id"], force=True),
                "comments": await instagram.sync_comments(get_router(request), b, force=True)}
    except meta.MetaError as e:
        raise _meta_error(e) from e


# ------------------------------------------------------------------ WhatsApp webhook (called by Meta)


def _handshake(request: Request) -> Response:
    """Meta's one-time handshake when a webhook URL is saved in the app dashboard (same verify token for both)."""
    q = request.query_params
    want = get_settings().whatsapp_verify_token
    if q.get("hub.mode") == "subscribe" and want and hmac.compare_digest(q.get("hub.verify_token", ""), want.get_secret_value()):
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403, "verification failed")


@webhook.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request) -> Response:
    return _handshake(request)


@webhook.get("/instagram/webhook")
async def instagram_verify(request: Request) -> Response:
    return _handshake(request)


@webhook.post("/instagram/webhook")
async def instagram_events(request: Request, bg: BackgroundTasks) -> dict[str, str]:
    """DMs and new comments on a connected Instagram account. Signed by Meta; answered at once, processed after."""
    raw = await request.body()
    if not instagram.signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    try:
        payload = await request.json()
    except ValueError as e:
        raise HTTPException(400, "not json") from e
    bg.add_task(instagram.handle, payload, get_router(request))
    return {"ok": "received"}


@webhook.post("/whatsapp/webhook")
async def whatsapp_events(request: Request, bg: BackgroundTasks) -> dict[str, str]:
    """Customer messages and delivery receipts. Signed by Meta; answered at once and processed after."""
    raw = await request.body()
    if not whatsapp.signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    try:
        payload = await request.json()
    except ValueError as e:
        raise HTTPException(400, "not json") from e
    bg.add_task(whatsapp.handle, payload, get_router(request))
    return {"ok": "received"}


@webhook.post("/meta/data-deletion")
async def meta_data_deletion(request: Request) -> dict[str, str]:
    """Meta's Deauthorize and Data deletion request callbacks (same URL for both). Form body `signed_request`."""
    s = get_settings()
    form = parse_qs((await request.body()).decode(errors="replace"))
    secrets = [k.get_secret_value() for k in (s.instagram_app_secret, s.meta_app_secret) if k is not None]
    data = meta.signed_request((form.get("signed_request") or [""])[0], *secrets)
    if not data or not data.get("user_id"):
        raise HTTPException(400, "bad signed_request")
    code = await instagram.forget(str(data["user_id"])) or "NOTHING-STORED"
    return {"url": f"{s.public_base_url.rstrip('/')}/data-deletion?code={code}", "confirmation_code": code}


@webhook.get("/meta/data-deletion/{code}")
async def meta_data_deletion_status(code: str) -> dict[str, Any]:
    if code == "NOTHING-STORED":
        return {"code": code, "status": "done", "note": "Nothing was stored for this account."}
    async with connection() as conn:
        row = await fetch_one(conn, """select created_at from ledger_events where type = 'channel.data_deleted'
                                       and payload->>'confirmation' = %s""", (code.upper(),))
    if not row:
        raise services.NotFound("No deletion request has this code.")
    return {"code": code.upper(), "status": "done", "deleted_at": row["created_at"]}


# ------------------------------------------------------------------ Google Business Profile


async def _google_post(conn: Any, asset_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """-> (localPost, asset, headline) for a live post."""
    from app.storage import get_storage

    asset = await services.get_asset(conn, asset_id)
    tp = await fetch_one(conn, "select code from touchpoints where asset_id = %s", (asset_id,))
    if asset["status"] != "live" or not tp:
        raise services.Conflict("Approve the post first; the Google offer needs its code and tracked link.")
    c = await services.get_campaign(conn, asset["campaign_id"])
    rev = (await services.current_revision(conn, asset_id)) or {}
    rendered = rev.get("rendered") or {}
    sheet = await services.locked_sheet(conn, c["id"])
    facts = [f.model_dump() for f in sheet.facts] if sheet else []
    rules = redeem.rules(facts, starts_on=c.get("starts_on"), ends_on=c.get("ends_on"))
    lang = asset["language"]
    post = google_business.offer_post(
        language=lang, headline=rendered.get("headline", ""), body=rendered.get("body", ""),
        offer=[f["display"].get(lang) or f["display"].get("en", "") for f in facts if f["type"] != "condition"],
        conditions=[f["display"].get(lang) or f["display"].get("en", "") for f in facts if f["type"] == "condition"],
        code=tp["code"], link=f"{get_settings().public_base_url.rstrip('/')}/r/{tp['code']}",
        starts_on=rules.start, ends_on=rules.end,
        photo_url=get_storage().url(rev["image_key"]) if rev.get("image_key") else None)
    return post, asset, rendered.get("headline", "")


@channels_api.get("/assets/{asset_id}/google-post")
async def google_post(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    """The post as a Google Business Profile offer: ready to publish, or to paste into business.google.com."""
    b = await _business_of_asset(user, asset_id)
    async with connection() as conn:
        post, _asset, headline = await _google_post(conn, asset_id)
        acct = await google_business.account(conn, b["id"])
        done = await fetch_all(conn, "select name, search_url, state, created_at from google_posts where asset_id = %s "
                                     "order by created_at desc", (asset_id,))
    return {"post": post, "problems": google_business.problems(post, headline), "configured": google_business.configured(),
            "connected": bool(acct and (acct["meta"] or {}).get("location")), "posted": done}


@channels_api.post("/assets/{asset_id}/google-post")
async def publish_google_post(user: CurrentUser, asset_id: str) -> dict[str, Any]:
    b = await _business_of_asset(user, asset_id)
    async with connection() as conn:
        post, asset, _ = await _google_post(conn, asset_id)
        acct = await google_business.account(conn, b["id"])
    if not acct:
        raise services.Conflict("Connect your Google Business Profile first, on the Channels page.")
    if "startDate" not in post["event"]["schedule"] or "endDate" not in post["event"]["schedule"]:
        raise services.Conflict("Google needs the offer's start and end dates; add a date range to the offer.")
    try:
        res = await google_business.publish(acct, post)
    except google_business.GoogleError as e:
        raise services.Conflict(f"Google said: {e}") from e
    async with connection() as conn:
        await conn.execute("""insert into google_posts (name, business_id, asset_id, search_url, state)
                              values (%s, %s, %s, %s, %s) on conflict (name) do nothing""",
                           (res.get("name"), b["id"], asset_id, res.get("searchUrl"), res.get("state")))
        await ledger.record(conn, b["id"], "google.posted", f"Posted the {services.asset_label(asset)} as an offer on "
                            "Google", actor="owner", campaign_id=asset["campaign_id"], payload={"name": res.get("name")})
    return {"ok": True, "search_url": res.get("searchUrl"), "state": res.get("state")}


@channels_api.get("/businesses/{slug}/channels/google/connect")
async def google_connect(user: CurrentUser, slug: str) -> dict[str, str]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
    if not google_business.configured():
        raise services.Conflict("Google sign-in is not set up on this server (GOOGLE_OAUTH_CLIENT_ID and "
                                "GOOGLE_OAUTH_CLIENT_SECRET). Use 'Copy for Google' on a post meanwhile.")
    return {"url": google_business.auth_url(google_business.state_for(b["id"], b["slug"]))}


class GoogleLocation(BaseModel):
    location: str = Field(pattern=r"^accounts/[^/]+/locations/[^/]+$")


@channels_api.put("/businesses/{slug}/channels/google")
async def google_choose(user: CurrentUser, slug: str, body: GoogleLocation) -> dict[str, Any]:
    async with connection() as conn:
        b = await business_for(conn, user, slug)
        acct = await google_business.account(conn, b["id"])
        locs = {loc["name"]: loc for loc in ((acct or {}).get("meta") or {}).get("locations") or []}
        if body.location not in locs:
            raise services.NotFound("not found")
        await conn.execute(
            """update channel_accounts set external_id = %s, display = %s, meta = meta || %s
               where business_id = %s and channel = 'google_business'""",
            (body.location, locs[body.location]["title"], jsonb({"location": body.location}), b["id"]))
        await ledger.record(conn, b["id"], "channel.connected", f"Google Business Profile: {locs[body.location]['title']}",
                            actor="owner")
    return {"ok": True}


@webhook.get("/google/callback")
async def google_callback(state: str = "", code: str | None = None, error: str | None = None) -> RedirectResponse:
    """Google sends the owner back here after sign-in. The state is signed, so only a connect we started counts."""
    base = get_settings().public_base_url.rstrip("/")
    who = google_business.read_state(state) if google_business.configured() else None
    if not who or not code:
        return RedirectResponse(f"{base}/channels?google=error&why={'cancelled' if error else 'expired'}", 303)
    try:
        res = await google_business.connect(who[0], code)
    except google_business.GoogleError as e:
        from urllib.parse import quote

        return RedirectResponse(f"{base}/channels?google=error&why={quote(str(e)[:200])}", 303)
    async with connection() as conn:
        await ledger.record(conn, who[0], "channel.connected", "Google Business Profile connected", actor="owner")
    return RedirectResponse(f"{base}/channels?google={'connected' if res['chosen'] else 'choose'}", 303)
