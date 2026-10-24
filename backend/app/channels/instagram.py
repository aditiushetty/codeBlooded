"""Instagram API with Instagram Login: publish a post, link posts the owner made themselves, read their insights,
and read the comments people leave as reviews (sorted into praise, complaint, question, suggestion, mention, spam).

Engagement rate = (likes + comments + saves + shares) / reach, per post, from Meta's own numbers. Instagram captions
cannot carry a clickable link, so each caption prints the post's code: a customer who shows it at the counter is
counted for that exact post, the same as a link open.
"""

import asyncio
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app import ledger, reviews, services
from app.channels import meta
from app.config import get_settings
from app.db import Conn, connection, fetch_all, fetch_one, jsonb
from app.storage import SupabaseStorage, get_storage

log = logging.getLogger(__name__)

METRICS = ["reach", "likes", "comments", "saved", "shares", "views", "total_interactions"]
CORE = ["reach", "likes", "comments", "saved", "shares", "total_interactions"]  # every image post has these
FRESH = timedelta(hours=1)  # insights are re-read at most this often; Meta's own data lags up to 48 hours

# A comment asking for the offer ("CODE", "coupon", "offer", the post's own code, ಕೋಡ್, कोड) gets a personal one-time
# code in a private reply, the same as a WhatsApp message with the post's code. The caption invites it.
ASK_FOR_CODE = "Comment CODE and we'll send you your own one-time code."
WANTS_CODE = re.compile(r"(?<![a-z])(code|coupon|offer)(?![a-z])|ಕೋಡ್|कोड", re.IGNORECASE)


async def account(conn: Conn, business_id: Any) -> dict[str, Any] | None:
    return await fetch_one(conn, "select * from channel_accounts where business_id = %s and channel = 'instagram'",
                           (business_id,))


def _get(acct: dict[str, Any], path: str, **params: Any) -> Any:
    return meta.graph("GET", meta.url(meta.IG, path), token=acct["token"], params=params, bearer=False)


async def check(token: str) -> dict[str, Any]:
    """Who the token belongs to. Only professional (Business or Creator) accounts have insights and publishing."""
    d = await meta.graph("GET", meta.url(meta.IG, "me"), token=token, bearer=False,
                         params={"fields": "user_id,username,account_type"})
    if d.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
        raise meta.MetaError("This is a personal Instagram account. Switch it to a Business or Creator account in the "
                             "Instagram app (Settings, Account type), then connect again.")
    return {"user_id": str(d.get("user_id") or d.get("id")), "username": d.get("username")}


async def refresh_if_due(acct: dict[str, Any]) -> dict[str, Any]:
    """Long-lived tokens last 60 days. Renew one that is older than 50 days, so the connection never lapses."""
    if datetime.now(UTC) - acct["connected_at"] < timedelta(days=50):
        return acct
    d = await meta.graph("GET", f"{meta.IG}/refresh_access_token", token=acct["token"], bearer=False,
                         params={"grant_type": "ig_refresh_token"})
    async with connection() as conn:
        row = await fetch_one(conn, """update channel_accounts set token = %s, connected_at = now(),
                                       token_expires_at = now() + make_interval(secs => %s)
                                       where business_id = %s and channel = 'instagram' returning *""",
                              (d["access_token"], int(d.get("expires_in") or 5_184_000), acct["business_id"]))
    return row or acct


async def recent(acct: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    d = await _get(acct, "me/media", limit=limit,
                   fields="id,caption,media_type,media_product_type,permalink,timestamp,thumbnail_url,media_url")
    return d.get("data") or []


def caption(rendered: dict[str, Any], code: str | None) -> str:
    parts = [rendered.get("headline", ""), rendered.get("body", ""), "\n".join(rendered.get("offer") or [])]
    if code:
        parts.append(f"Show code {code} at the counter. {ASK_FOR_CODE}")
    if tags := rendered.get("hashtags"):
        parts.append(" ".join(t if t.startswith("#") else f"#{t}" for t in tags))
    return "\n\n".join(p for p in parts if p).strip()[:2200]


_publishing: set[str] = set()  # one upload per post at a time (two open tabs auto-posting the same post)


async def publish(business: dict[str, Any], asset_id: str, jpeg: bytes) -> dict[str, Any]:
    """Post a live picture post to the connected account. The picture is the post as drawn in Counterpart."""
    if asset_id in _publishing:
        raise services.Conflict("This post is being posted to Instagram already.")
    _publishing.add(asset_id)
    try:
        return await _publish(business, asset_id, jpeg)
    finally:
        _publishing.discard(asset_id)


async def _publish(business: dict[str, Any], asset_id: str, jpeg: bytes) -> dict[str, Any]:
    async with connection() as conn:
        acct = await account(conn, business["id"])
        if not acct:
            raise services.Conflict("Connect Instagram first, on the Channels page.")
        asset = await services.get_asset(conn, asset_id)
        if asset["status"] != "live":
            raise services.Conflict("Approve the post first.")
        if await fetch_one(conn, "select 1 from instagram_media where asset_id = %s", (asset["id"],)):
            raise services.Conflict("This post is already on Instagram.")
        tp = await fetch_one(conn, "select code from touchpoints where asset_id = %s", (asset["id"],))
        rev = await services.current_revision(conn, asset["id"])
    acct = await refresh_if_due(acct)
    key = f"instagram/{asset['id']}-{rev['n'] if rev else 0}.jpg"
    store = get_storage()
    s = get_settings()
    if not isinstance(store, SupabaseStorage) and s.supabase_url and s.supabase_service_role_key:
        # Meta must download the picture: Supabase Storage is public over https even while the app runs on a laptop
        store = SupabaseStorage(s.supabase_url, s.supabase_service_role_key.get_secret_value(), s.supabase_bucket)
    try:
        if isinstance(store, SupabaseStorage):
            await store.ensure_bucket()  # the app may run on local storage, so the bucket may not exist yet
        where = store.url(await store.put(key, jpeg, "image/jpeg"))
    except httpx.HTTPError as e:
        raise services.Conflict("Could not upload the picture for Instagram to download (Supabase Storage "
                                f"answered {getattr(getattr(e, 'response', None), 'status_code', 'nothing')}). "
                                "Try again in a minute.") from e
    image_url = where if where.startswith("http") else s.public_base_url.rstrip("/") + where
    if not image_url.startswith("https://"):
        raise services.Conflict("Instagram downloads the picture from a public https address. Start the tunnel "
                                "(see docs/CHANNELS.md) and set PUBLIC_BASE_URL to it, then try again.")
    text = caption((rev or {}).get("rendered") or {}, tp and tp["code"])
    made = await meta.graph("POST", meta.url(meta.IG, f"{acct['external_id']}/media"), token=acct["token"],
                            bearer=False, params={"image_url": image_url, "caption": text})
    for _ in range(20):  # Meta fetches and checks the picture before it can be published
        st = await _get(acct, made["id"], fields="status_code")
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise meta.MetaError("Instagram could not use the picture. It must be a JPEG under 8 MB, 4:5 to 1.91:1.")
        await asyncio.sleep(1.5)
    else:
        raise meta.MetaError("Instagram is still processing the picture. Try again in a minute.")
    done = await meta.graph("POST", meta.url(meta.IG, f"{acct['external_id']}/media_publish"), token=acct["token"],
                            bearer=False, params={"creation_id": made["id"]})
    info = await _get(acct, done["id"], fields="permalink,timestamp,media_type")
    async with connection() as conn:
        await conn.execute(
            """insert into instagram_media (media_id, business_id, asset_id, permalink, caption, media_type, posted_at,
                                            published_by, code_line) values (%s, %s, %s, %s, %s, %s, %s, 'counterpart', %s)""",
            (done["id"], business["id"], asset["id"], info.get("permalink"), text, info.get("media_type"),
             info.get("timestamp"), "caption" if ASK_FOR_CODE in text else None))
        await ledger.record(conn, business["id"], "instagram.published", "Posted to Instagram", actor="owner",
                            campaign_id=asset["campaign_id"], payload={"media_id": done["id"], "permalink": info.get("permalink")})
    return {"media_id": done["id"], "permalink": info.get("permalink")}


async def link(business: dict[str, Any], asset_id: str, media_id: str) -> dict[str, Any]:
    """Tie a post the owner made in the Instagram app to a Counterpart post, so its insights are counted."""
    async with connection() as conn:
        acct = await account(conn, business["id"])
        if not acct:
            raise services.Conflict("Connect Instagram first, on the Channels page.")
        asset = await services.get_asset(conn, asset_id)
        campaign = await services.get_campaign(conn, asset["campaign_id"])
        if campaign["business_id"] != business["id"]:
            raise services.NotFound("not found")
    info = await _get(acct, media_id, fields="id,caption,permalink,timestamp,media_type")  # proves it is theirs
    async with connection() as conn:
        await conn.execute(
            """insert into instagram_media (media_id, business_id, asset_id, permalink, caption, media_type, posted_at,
                                            published_by, code_line) values (%s, %s, %s, %s, %s, %s, %s, 'owner', %s)
               on conflict (media_id) do update set asset_id = excluded.asset_id,
                 code_line = coalesce(instagram_media.code_line, excluded.code_line)""",
            (info["id"], business["id"], asset["id"], info.get("permalink"), info.get("caption"), info.get("media_type"),
             info.get("timestamp"), "caption" if ASK_FOR_CODE in (info.get("caption") or "") else None))
    return {"media_id": info["id"], "permalink": info.get("permalink")}


def _values(data: list[dict[str, Any]]) -> dict[str, int]:
    out = {}
    for m in data:
        v = (m.get("values") or [{}])[0].get("value") if m.get("values") else (m.get("total_value") or {}).get("value")
        if isinstance(v, int | float):
            out[m["name"]] = int(v)
    return out


def engagement(m: dict[str, int]) -> float | None:
    """(likes + comments + saves + shares) / reach. None until Meta reports a reach."""
    if not m.get("reach"):
        return None
    acts = m.get("total_interactions")
    if acts is None:
        acts = sum(m.get(k, 0) for k in ("likes", "comments", "saved", "shares"))
    return round(acts / m["reach"], 4)


async def sync(business_id: Any, *, force: bool = False) -> int:
    """Re-read insights for the business's linked posts that are older than an hour. -> posts updated."""
    async with connection() as conn:
        acct = await account(conn, business_id)
        if not acct:
            return 0
        rows = await fetch_all(conn, """select media_id from instagram_media where business_id = %s
                                        and (%s or metrics_at is null or metrics_at < now() - %s)""",
                               (business_id, force, FRESH))
    n = 0
    for r in rows:
        try:
            d = await _get(acct, f"{r['media_id']}/insights", metric=",".join(METRICS))
        except meta.MetaError:
            try:  # some media types lack a metric (and older posts lack views): ask for the ones every post has
                d = await _get(acct, f"{r['media_id']}/insights", metric=",".join(CORE))
            except meta.MetaError:
                continue
        m = _values(d.get("data") or [])
        async with connection() as conn:
            await conn.execute("update instagram_media set metrics = %s, metrics_at = now() where media_id = %s",
                               (jsonb(m), r["media_id"]))
        n += 1
    return n


COMMENT_POSTS = 25  # comments are read on the account's latest posts, whether or not they are linked to a campaign
COMMENTS_EVERY = timedelta(minutes=3)  # listing comments is two cheap reads; only new ones go to the model


def wants_code(text: str, post_code: str | None) -> bool:
    return bool(WANTS_CODE.search(text)) or bool(post_code and post_code in text.upper())


def device_for(username: str) -> str:
    """A stable id for an Instagram user, so the same person gets the same personal code back."""
    return "ig-" + hashlib.sha256(username.lower().encode()).hexdigest()[:24]


def _script(text: str) -> str:
    """A first guess at the language from the letters used; the model's reading replaces it."""
    if re.search(r"[ಀ-೿]", text):
        return "kn"
    return "hi" if re.search(r"[ऀ-ॿ]", text) else "en"


async def sync_comments(router: Any, business: dict[str, Any], *, force: bool = False) -> int:
    """Store new comments on the account's latest posts as reviews, then sort and read them. -> comments added.

    The business's own comments are skipped. Runs at most every few minutes unless forced; claiming the slot is one
    atomic update, so page loads that arrive together do not read twice.

    While the Meta app is in development mode Instagram counts every comment but lists only those written by
    accounts with a role on the app; the difference is kept as `comments_hidden` so the owner is told why."""
    async with connection() as conn:
        acct = await fetch_one(
            conn, """update channel_accounts set meta = meta || jsonb_build_object('comments_at', now())
                     where business_id = %s and channel = 'instagram'
                       and (%s or meta->>'comments_at' is null or (meta->>'comments_at')::timestamptz < now() - %s)
                     returning *""", (business["id"], force, COMMENTS_EVERY))
        if not acct:
            return 0
        linked = {r["media_id"]: r for r in await fetch_all(
            conn, """select m.media_id, m.asset_id, a.campaign_id, a.language, t.code as post_code from instagram_media m
                     left join assets a on a.id = m.asset_id left join touchpoints t on t.asset_id = m.asset_id
                     where m.business_id = %s""", (business["id"],))}
    acct = await refresh_if_due(acct)
    own = (acct["display"] or "").lstrip("@").lower()
    found: list[tuple[str, dict[str, Any]]] = []
    hidden_by_post: dict[str, int] = {}
    for m in (await _get(acct, "me/media", limit=COMMENT_POSTS, fields="id,comments_count")).get("data") or []:
        if m.get("comments_count"):
            got = (await _get(acct, f"{m['id']}/comments", limit=50,
                              fields="id,text,timestamp,username,replies{id}")).get("data") or []
            listed = len(got) + sum(len((c.get("replies") or {}).get("data") or []) for c in got)  # count has replies
            if held := max(0, min(m["comments_count"], 50) - listed):
                hidden_by_post[m["id"]] = held
            found += [(m["id"], c) for c in got
                      if (c.get("text") or "").strip() and (c.get("username") or "").lower() != own]
    added = 0
    asking: list[tuple[dict[str, Any], dict[str, Any]]] = []  # (comment, linked post) for new comments asking for a code
    async with connection() as conn:
        await conn.execute("""update channel_accounts set meta = meta || jsonb_build_object('comments_hidden', %s::int,
                                'comments_hidden_by_post', %s::jsonb)
                              where business_id = %s and channel = 'instagram'""",
                           (sum(hidden_by_post.values()), jsonb(hidden_by_post), business["id"]))
        for media_id, c in found:
            post = linked.get(media_id) or {}
            row = await fetch_one(
                conn, """insert into customer_interactions (business_id, source, language, body, occurred_at, external_id,
                                                            author, campaign_id, asset_id, is_synthetic, media_id)
                         values (%s, 'instagram_comment', %s, %s, coalesce(%s::timestamptz, now()), %s, %s, %s, %s, false, %s)
                         on conflict (business_id, source, external_id) where external_id is not null
                           do update set media_id = coalesce(customer_interactions.media_id, excluded.media_id)
                         returning id, (xmax = 0) as inserted""",
                (business["id"], _script(c["text"]), c["text"].strip(), c.get("timestamp"), c["id"], c.get("username"),
                 post.get("campaign_id"), post.get("asset_id"), media_id))
            row = row if row and row["inserted"] else None
            added += row is not None
            if row and post.get("post_code") and c.get("username") and wants_code(c["text"], post["post_code"]):
                asking.append((c, post))
    for c, post in asking:
        await send_code(acct, business, c, post)
    read = await reviews.read_comments(router, business)
    if added or read:
        async with connection() as conn:
            await ledger.record(conn, business["id"], "customers.instagram",
                                f"Read {added} new Instagram comment{'s' if added != 1 else ''}", actor="agent",
                                payload={"added": added, "read": read})
    return added


CODE_TEXT = {
    "your_code": {"en": "Your code", "kn": "ನಿಮ್ಮ ಕೋಡ್", "hi": "आपका कोड"},
    "show": {"en": "Show it at the counter", "kn": "ಕೌಂಟರ್‌ನಲ್ಲಿ ತೋರಿಸಿ", "hi": "काउंटर पर दिखाएँ"},
}  # the same checked words the WhatsApp reply uses


async def _offer_message(business: dict[str, Any], post: dict[str, Any], device: str
                         ) -> tuple[dict[str, Any], str] | None:
    """A personal one-time code for this person and the words that carry it. The same person always gets the same
    code back. -> (claim, text), or None when the post is no longer live (say nothing rather than promise an offer)."""
    lang = post.get("language") if post.get("language") in ("en", "kn", "hi") else "en"
    t = {k: v[lang] for k, v in CODE_TEXT.items()}
    async with connection() as conn:
        try:
            claim, _ = await services.claim(conn, post["post_code"], device=device, via="instagram")
        except services.NotFound:
            return None
        sheet = await services.locked_sheet(conn, post["campaign_id"])
    lines = [f.display.get(lang) or f.display.get("en", "") for f in sheet.facts] if sheet else []
    base = get_settings().public_base_url.rstrip("/")
    if claim["status"] == "redeemed":
        return claim, f"{business['name']}: this code was already used. Thank you for coming in!"
    qr = f" {base}/c/{claim['code']}" if base.startswith("https://") else ""
    return claim, "\n".join([business["name"], *lines, "", f"{t['your_code']}: {claim['code']}", f"{t['show']}.{qr}"])


async def _message(acct: dict[str, Any], recipient: dict[str, str], text: str) -> None:
    await meta.graph("POST", meta.url(meta.IG, f"{acct['external_id']}/messages"), token=acct["token"], bearer=False,
                     json={"recipient": recipient, "message": {"text": text}})


async def send_code(acct: dict[str, Any], business: dict[str, Any], comment: dict[str, Any],
                    post: dict[str, Any]) -> bool:
    """Answer a comment asking for the offer with a personal one-time code, in a private reply (Instagram allows one
    per comment, within 7 days). -> sent."""
    made = await _offer_message(business, post, device_for(comment["username"]))
    if not made:
        return False
    claim, body = made
    try:
        await _message(acct, {"comment_id": comment["id"]}, body)
    except meta.MetaError as e:
        async with connection() as conn:
            await ledger.record(conn, business["id"], "instagram.code_failed",
                                f"Could not send @{comment['username']} their code on Instagram: {e}", actor="agent",
                                campaign_id=post["campaign_id"], payload={"comment_id": comment["id"]})
        return False
    async with connection() as conn:
        await conn.execute("""update customer_interactions set reply = %s, replied_at = now()
                              where business_id = %s and source = 'instagram_comment' and external_id = %s""",
                           (f"Sent their personal code {claim['code']} in a private message.", business["id"],
                            comment["id"]))
        await ledger.record(conn, business["id"], "instagram.code_sent",
                            f"Sent @{comment['username']} a personal code on Instagram", actor="agent",
                            campaign_id=post["campaign_id"], payload={"claim": claim["code"], "comment_id": comment["id"]})
    return True


# ------------------------------------------------------------------ webhook: DMs and new comments as they happen
# Instagram calls /api/public/instagram/webhook for the connected account (fields `messages` and `comments`, after
# `subscribe`). In development mode only accounts with a role on the app are delivered, as with comment listing.


def signature_ok(raw: bytes, header: str | None) -> bool:
    s = get_settings()
    if not header or not header.startswith("sha256="):
        return False
    return any(hmac.compare_digest(hmac.new(k.get_secret_value().encode(), raw, hashlib.sha256).hexdigest(),
                                   header.removeprefix("sha256="))
               for k in (s.instagram_app_secret, s.meta_app_secret) if k is not None)


async def subscribe(acct: dict[str, Any]) -> None:
    """Ask Instagram to send this account's DMs and comments to the webhook."""
    await meta.graph("POST", meta.url(meta.IG, "me/subscribed_apps"), token=acct["token"], bearer=False,
                     params={"subscribed_fields": "comments,messages"})


async def _username(acct: dict[str, Any], sender: str) -> str | None:
    try:
        return (await _get(acct, sender, fields="username")).get("username")
    except meta.MetaError:
        return None


async def answer_dm(acct: dict[str, Any], business: dict[str, Any], sender: str, text: str) -> bool:
    """A DM naming a post's code gets that post's offer; one saying CODE/coupon/offer gets the newest live post's.
    Free to answer: a reply inside 24 hours of the customer's message. -> sent."""
    async with connection() as conn:
        posts = await fetch_all(
            conn, """select t.code as post_code, a.campaign_id, a.language from instagram_media m
                     join assets a on a.id = m.asset_id join touchpoints t on t.asset_id = a.id
                     where m.business_id = %s and a.status = 'live' order by m.posted_at desc nulls last""",
            (business["id"],))
    post = next((p for p in posts if p["post_code"] in text.upper()), None)
    if post is None and posts and WANTS_CODE.search(text):
        post = posts[0]
    if post is None:
        return False
    username = await _username(acct, sender)
    made = await _offer_message(business, post, device_for(username or f"id:{sender}"))
    if not made:
        return False
    claim, body = made
    who = f"@{username}" if username else "someone"
    try:
        await _message(acct, {"id": sender}, body)
    except meta.MetaError as e:
        async with connection() as conn:
            await ledger.record(conn, business["id"], "instagram.code_failed",
                                f"Could not send {who} their code in an Instagram DM: {e}", actor="agent",
                                campaign_id=post["campaign_id"], payload={"sender": sender})
        return False
    async with connection() as conn:
        await ledger.record(conn, business["id"], "instagram.code_sent", f"Sent {who} a personal code by Instagram DM",
                            actor="agent", campaign_id=post["campaign_id"], payload={"claim": claim["code"], "dm": True})
    return True


async def handle(payload: dict[str, Any], router: Any) -> None:
    """One webhook delivery: answer DMs asking for the offer; read new comments at once instead of on the next pass."""
    if payload.get("object") != "instagram":
        return
    for entry in payload.get("entry") or []:
        async with connection() as conn:
            acct = await fetch_one(conn, "select * from channel_accounts where channel = 'instagram' and external_id = %s",
                                   (str(entry.get("id")),))
            business = acct and await fetch_one(conn, "select * from businesses where id = %s", (acct["business_id"],))
        if not acct or not business:
            continue
        acct = await refresh_if_due(acct)
        for ev in entry.get("messaging") or []:
            msg = ev.get("message") or {}
            sender = (ev.get("sender") or {}).get("id")
            if msg.get("is_echo") or not msg.get("text") or not sender or sender == acct["external_id"]:
                continue
            await answer_dm(acct, business, str(sender), msg["text"])
        if any(c.get("field") == "comments" for c in entry.get("changes") or []):
            await sync_comments(router, business, force=True)


async def forget(user_id: str) -> str | None:
    """Meta's deauthorize and data deletion callbacks: the person removed Counterpart from their Instagram account or
    asked for their data to be deleted. The connection (token included) and what was read through it go now.
    -> a confirmation code, or None when nothing is connected for that id."""
    async with connection() as conn:
        acct = await fetch_one(conn, """delete from channel_accounts where channel = 'instagram' and external_id = %s
                                        returning business_id""", (user_id,))
        if not acct:
            return None
        await conn.execute("delete from instagram_media where business_id = %s", (acct["business_id"],))
        await conn.execute("""delete from customer_interactions where business_id = %s and source = 'instagram_comment'""",
                           (acct["business_id"],))
        code = hashlib.sha256(f"{user_id}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:12].upper()
        await ledger.record(conn, acct["business_id"], "channel.data_deleted",
                            "Instagram disconnected and its data deleted, as asked through Instagram", actor="system",
                            payload={"confirmation": code})
    return code


# ------------------------------------------------------------------ the "Comment CODE" line on older posts


async def add_code_line(business: dict[str, Any], asset_id: str) -> dict[str, Any]:
    """Posts published before captions invited "Comment CODE" get the line as the business's own comment (Instagram's
    API cannot edit a caption: it answers that only `comment_enabled` may change). -> {comment_id}."""
    async with connection() as conn:
        acct = await account(conn, business["id"])
        if not acct:
            raise services.Conflict("Connect Instagram first, on the Channels page.")
        m = await fetch_one(conn, """select m.media_id, m.code_line, t.code from instagram_media m
                                     join touchpoints t on t.asset_id = m.asset_id
                                     where m.asset_id = %s and m.business_id = %s""", (asset_id, business["id"]))
    if not m:
        raise services.NotFound("This post is not on Instagram.")
    if m["code_line"]:
        raise services.Conflict("This post already asks people to comment CODE.")
    acct = await refresh_if_due(acct)
    made = await meta.graph("POST", meta.url(meta.IG, f"{m['media_id']}/comments"), token=acct["token"], bearer=False,
                            params={"message": f"Show code {m['code']} at the counter. {ASK_FOR_CODE}"})
    async with connection() as conn:
        await conn.execute("update instagram_media set code_line = 'comment' where media_id = %s", (m["media_id"],))
        await ledger.record(conn, business["id"], "instagram.code_line", "Asked people to comment CODE on an older post",
                            actor="owner", payload={"media_id": m["media_id"], "comment_id": made.get("id")})
    return {"comment_id": made.get("id")}


async def reply(review: dict[str, Any], text: str) -> None:
    """Answer an Instagram comment publicly, under the comment, as the business."""
    async with connection() as conn:
        acct = await account(conn, review["business_id"])
    if not acct:
        raise services.Conflict("Connect Instagram first, on the Channels page.")
    await meta.graph("POST", meta.url(meta.IG, f"{review['external_id']}/replies"), token=acct["token"], bearer=False,
                     params={"message": text})


# ------------------------------------------------------------------ the account at a glance (Results page)

OVERVIEW_DAYS = 28
OVERVIEW_EVERY = timedelta(minutes=15)  # about 15 reads per refresh; Meta's own numbers lag anyway
ACCOUNT_METRICS = ["reach", "views", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves",
                   "profile_views", "website_clicks"]
POST_METRICS = ["reach", "saved", "shares", "views", "total_interactions"]


async def _read_overview(acct: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    span = {"since": int((now - timedelta(days=OVERVIEW_DAYS - 1)).timestamp()), "until": int(now.timestamp())}

    async def insights() -> tuple[dict[str, int], list[dict[str, Any]]]:
        try:  # a new or small account may have no insights yet: show what there is
            t, r = await asyncio.gather(
                _get(acct, "me/insights", metric=",".join(ACCOUNT_METRICS), period="day", metric_type="total_value", **span),
                _get(acct, "me/insights", metric="reach", period="day", **span))
        except meta.MetaError:
            return {}, []
        return _values(t.get("data") or []), [
            {"day": v["end_time"][:10], "reach": v.get("value", 0)} for v in ((r.get("data") or [{}])[0].get("values") or [])]

    async def post_insights(media_id: str) -> dict[str, int]:
        try:
            return _values((await _get(acct, f"{media_id}/insights", metric=",".join(POST_METRICS))).get("data") or [])
        except meta.MetaError:
            return {}

    # One round trip at a time took 8 s for 12 posts; Meta answers these in parallel.
    profile, (totals, series), media = await asyncio.gather(
        _get(acct, "me", fields="username,name,followers_count,follows_count,media_count,profile_picture_url"),
        insights(),
        _get(acct, "me/media", limit=12, fields="id,caption,media_type,permalink,timestamp,like_count,"
                                                "comments_count,thumbnail_url,media_url"))
    media = media.get("data") or []
    each = await asyncio.gather(*(post_insights(m["id"]) for m in media))
    posts = [{**{k: ins[k] for k in POST_METRICS if k in ins},
              "id": m["id"], "caption": (m.get("caption") or "")[:300], "media_type": m.get("media_type"),
              "permalink": m.get("permalink"), "timestamp": m.get("timestamp"),
              "picture": m.get("thumbnail_url") or m.get("media_url"),
              "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0)} for m, ins in zip(media, each, strict=True)]
    return {"at": now.isoformat(), "days": OVERVIEW_DAYS, "profile": {k: profile.get(k) for k in (
        "username", "name", "followers_count", "follows_count", "media_count", "profile_picture_url")},
            "totals": totals, "series": series, "posts": posts}


_overview_refreshing: set[str] = set()
_background: set[asyncio.Task[None]] = set()


async def _refresh_overview(acct: dict[str, Any]) -> dict[str, Any]:
    acct = await refresh_if_due(acct)
    data = await _read_overview(acct)
    async with connection() as conn:
        await conn.execute("""update channel_accounts set meta = meta || jsonb_build_object('overview', %s::jsonb)
                              where business_id = %s and channel = 'instagram'""", (jsonb(data), acct["business_id"]))
    return data


async def _refresh_overview_quietly(acct: dict[str, Any]) -> None:
    key = str(acct["business_id"])
    if key in _overview_refreshing:
        return
    _overview_refreshing.add(key)
    try:
        await _refresh_overview(acct)
    except meta.MetaError:
        log.info("instagram overview refresh failed", exc_info=True)
    finally:
        _overview_refreshing.discard(key)


async def overview(business: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
    """Followers, 28-day reach and interactions, a daily reach line, and the latest posts with their likes, comments,
    reach, saves and shares, each with the comments Counterpart has read and how many Instagram still holds back.
    Meta is read at most every 15 minutes (cached on the account); comments come from the database each time."""
    async with connection() as conn:
        acct = await account(conn, business["id"])
    if not acct:
        return None
    held = (acct["meta"] or {}).get("comments_hidden_by_post") or {}  # from the last comment read
    data = (acct["meta"] or {}).get("overview")
    if force or not data:
        data = await _refresh_overview(acct)
    elif datetime.fromisoformat(data["at"]) < datetime.now(UTC) - OVERVIEW_EVERY:
        # Show the last numbers now and fetch new ones behind them; the next load has them.
        task = asyncio.get_running_loop().create_task(_refresh_overview_quietly(acct))
        _background.add(task)
        task.add_done_callback(_background.discard)
    async with connection() as conn:
        linked = {r["media_id"]: r for r in await fetch_all(
            conn, """select m.media_id, m.asset_id::text as asset_id, c.id::text as campaign_id, c.name as campaign,
                            t.code as post_code from instagram_media m left join assets a on a.id = m.asset_id
                     left join campaigns c on c.id = a.campaign_id left join touchpoints t on t.asset_id = m.asset_id
                     where m.business_id = %s""", (business["id"],))}
        said = await fetch_all(
            conn, """select id::text as id, media_id, author, body, category, sentiment, translation, language, occurred_at,
                            reply from customer_interactions
                     where business_id = %s and source = 'instagram_comment' and category is distinct from 'spam'
                     order by occurred_at desc""", (business["id"],))
    posts = []
    for p in data["posts"]:
        mine = [c for c in said if c["media_id"] == p["id"]]
        posts.append({**p, **{k: v for k, v in (linked.get(p["id"]) or {}).items() if k != "media_id"},
                      "engagement_rate": engagement({**p, "likes": p.get("likes", 0), "comments": p.get("comments", 0)}),
                      "read": mine[:20], "held_back": int(held.get(p["id"], 0))})
    return {**data, "posts": posts, "held_back": sum(p["held_back"] for p in posts),
            "unplaced": [c for c in said if c["media_id"] is None][:20]}


async def stats(conn: Conn, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = await fetch_all(conn, """select asset_id::text as asset_id, media_id, permalink, metrics, metrics_at,
                                           published_by from instagram_media where asset_id = any(%s::uuid[])""",
                           (asset_ids,))
    return {r["asset_id"]: {**{k: v for k, v in r.items() if k not in ("asset_id", "metrics")},
                            **(r["metrics"] or {}), "engagement_rate": engagement(r["metrics"] or {})} for r in rows}
