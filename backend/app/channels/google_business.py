"""Google Business Profile: a live post becomes an "Offer" post on the business's own Google listing (Search and
Maps), with its dates, its code as the coupon and its tracked link.

Connecting needs Google sign-in (OAuth, scope business.manage) with GOOGLE_OAUTH_CLIENT_ID/SECRET, and Google
must have enabled the Business Profile APIs for that Cloud project. Without them the owner still gets every field
ready to paste into business.google.com (`offer_post` is the same either way). `http` is the only network caller;
tests replace it.
"""

import hashlib
import hmac
import time
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.db import Conn, connection, fetch_one, jsonb

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
ACCOUNTS = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
POSTS = "https://mybusiness.googleapis.com/v4"
SCOPE = "https://www.googleapis.com/auth/business.manage"
MAX_SUMMARY, MAX_TITLE = 1500, 58


class GoogleError(Exception):
    """Google refused or failed; the message is Google's own and safe to show."""


def configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret)


def redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/public/google/callback"


async def http(method: str, url: str, *, token: str | None = None, data: dict[str, Any] | None = None,
               json: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, url, headers=headers, data=data, json=json, params=params)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else body.get("error_description") or err) or f"Google answered {r.status_code}."
        raise GoogleError(str(msg))
    return body


# ------------------------------------------------------------------ the post itself (pure)


def _sentence(text: str) -> str:
    t = text.strip()
    return t[:1].upper() + t[1:] + ("" if t[-1:] in ".!?।" else ".")


def _gdate(d: date) -> dict[str, int]:
    return {"year": d.year, "month": d.month, "day": d.day}


def offer_post(*, language: str, headline: str, body: str, offer: list[str], conditions: list[str], code: str,
               link: str, starts_on: date | None, ends_on: date | None, photo_url: str | None) -> dict[str, Any]:
    """The localPost Google takes for an OFFER. Text is the post's own checked words and locked offer wording."""
    summary = "\n".join(x for x in [body.strip(), "", *offer] if x is not None).strip()[:MAX_SUMMARY]
    post: dict[str, Any] = {
        "languageCode": language, "topicType": "OFFER", "summary": summary,
        "event": {"title": headline.strip()[:MAX_TITLE] or "Offer", "schedule": {}},
        "offer": {"couponCode": code, "redeemOnlineUrl": link,
                  "termsConditions": " ".join([*(_sentence(c) for c in conditions if c.strip()),
                                               "One code per customer. Show it at the counter."])[:1500]},
    }
    if starts_on:
        post["event"]["schedule"]["startDate"] = _gdate(starts_on)
    if ends_on:
        post["event"]["schedule"]["endDate"] = _gdate(ends_on)
    if photo_url and photo_url.startswith("https://"):
        post["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": photo_url}]
    return post


def problems(post: dict[str, Any], headline: str = "") -> list[str]:
    out = []
    sched = post["event"]["schedule"]
    if "startDate" not in sched or "endDate" not in sched:
        out.append("Google needs the offer's start and end dates; the locked offer has no date range.")
    if not post["summary"]:
        out.append("The post has no text.")
    if len(headline.strip()) > MAX_TITLE:
        out.append(f"The headline was cut to {MAX_TITLE} characters for Google's offer title.")
    if "media" not in post:
        out.append("No photo: Google shows offers with a photo far more. (Photos need a public https address.)")
    return out


# ------------------------------------------------------------------ connecting (OAuth)


def _sign(payload: str) -> str:
    key = get_settings().google_oauth_client_secret
    assert key is not None
    return hmac.new(key.get_secret_value().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def state_for(business_id: Any, slug: str) -> str:
    payload = f"{business_id}.{slug}.{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def read_state(state: str, max_age: int = 900) -> tuple[str, str] | None:
    try:
        bid, slug, ts, sig = state.split(".")
    except ValueError:
        return None
    payload = f"{bid}.{slug}.{ts}"
    if not hmac.compare_digest(sig, _sign(payload)) or time.time() - int(ts) > max_age:
        return None
    return bid, slug


def auth_url(state: str) -> str:
    s = get_settings()
    return f"{AUTH}?" + urlencode({"client_id": s.google_oauth_client_id, "redirect_uri": redirect_uri(),
                                   "response_type": "code", "scope": SCOPE, "access_type": "offline",
                                   "prompt": "consent", "state": state})


async def exchange(code: str) -> dict[str, Any]:
    s = get_settings()
    assert s.google_oauth_client_secret is not None
    return await http("POST", TOKEN, data={"code": code, "client_id": s.google_oauth_client_id,
                                           "client_secret": s.google_oauth_client_secret.get_secret_value(),
                                           "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})


async def locations(access_token: str) -> list[dict[str, Any]]:
    """Every location the signed-in Google account manages: [{name: accounts/../locations/.., title, address}]."""
    out = []
    for acc in (await http("GET", ACCOUNTS, token=access_token)).get("accounts") or []:
        res = await http("GET", f"{INFO}/{acc['name']}/locations", token=access_token,
                         params={"readMask": "name,title,storefrontAddress", "pageSize": 100})
        for loc in res.get("locations") or []:
            addr = loc.get("storefrontAddress") or {}
            out.append({"name": f"{acc['name']}/{loc['name']}", "title": loc.get("title"),
                        "address": ", ".join([*(addr.get("addressLines") or []), addr.get("locality") or ""]).strip(", ")})
    return out


async def connect(business_id: Any, code: str) -> dict[str, Any]:
    tok = await exchange(code)
    if not tok.get("refresh_token"):
        raise GoogleError("Google did not give a lasting sign-in. Remove Counterpart's access in your Google account "
                          "settings and connect again.")
    locs = await locations(tok["access_token"])
    if not locs:
        raise GoogleError("This Google account manages no Business Profile. Sign in with the account that owns the "
                          "listing.")
    chosen = locs[0] if len(locs) == 1 else None
    async with connection() as conn:
        await conn.execute(
            """insert into channel_accounts (business_id, channel, external_id, display, token, token_expires_at, meta)
               values (%s, 'google_business', %s, %s, %s, now() + make_interval(secs => %s), %s)
               on conflict (business_id, channel) do update set external_id = excluded.external_id,
                 display = excluded.display, token = excluded.token, token_expires_at = excluded.token_expires_at,
                 meta = excluded.meta, connected_at = now()""",
            (business_id, chosen["name"] if chosen else f"choose:{business_id}",
             chosen["title"] if chosen else None, tok["refresh_token"], int(tok.get("expires_in", 3600)),
             jsonb({"access_token": tok["access_token"], "locations": locs, "location": chosen and chosen["name"]})))
    return {"locations": locs, "chosen": chosen}


async def account(conn: Conn, business_id: Any) -> dict[str, Any] | None:
    return await fetch_one(conn, "select * from channel_accounts where business_id = %s and channel = 'google_business'",
                           (business_id,))


async def _access(acct: dict[str, Any]) -> str:
    """A fresh access token (they last an hour; the refresh token is kept)."""
    meta = acct.get("meta") or {}
    exp = acct.get("token_expires_at")
    if meta.get("access_token") and exp and exp.timestamp() - time.time() > 120:
        return meta["access_token"]
    s = get_settings()
    assert s.google_oauth_client_secret is not None
    tok = await http("POST", TOKEN, data={"client_id": s.google_oauth_client_id, "grant_type": "refresh_token",
                                          "client_secret": s.google_oauth_client_secret.get_secret_value(),
                                          "refresh_token": acct["token"]})
    async with connection() as conn:
        await conn.execute(
            """update channel_accounts set meta = meta || %s, token_expires_at = now() + make_interval(secs => %s)
               where business_id = %s and channel = 'google_business'""",
            (jsonb({"access_token": tok["access_token"]}), int(tok.get("expires_in", 3600)), acct["business_id"]))
    return tok["access_token"]


async def publish(acct: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
    location = (acct.get("meta") or {}).get("location")
    if not location:
        raise GoogleError("Pick which Google listing to post to first, on the Channels page.")
    return await http("POST", f"{POSTS}/{location}/localPosts", token=await _access(acct), json=post)
