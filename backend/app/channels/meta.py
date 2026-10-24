"""The one place that talks to Meta's Graph API. Tests replace `graph` with a fake."""

import base64
import hashlib
import hmac
import json as jsonlib
from typing import Any

import httpx

from app.config import get_settings

FB = "https://graph.facebook.com"  # WhatsApp Cloud API
IG = "https://graph.instagram.com"  # Instagram API with Instagram Login


class MetaError(Exception):
    """Meta refused or failed. The message is Meta's own, safe to show the owner (it never contains the token)."""


def signed_request(value: str, *secrets: str) -> dict[str, Any] | None:
    """Meta's `signed_request` (data deletion and deauthorize callbacks): base64url signature '.' base64url JSON,
    signed with HMAC-SHA256 by the app secret. -> the payload, or None when no secret signed it."""
    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    try:
        sig, payload = value.split(".", 1)
        given = unb64(sig)
        if not any(hmac.compare_digest(given, hmac.new(k.encode(), payload.encode(), hashlib.sha256).digest())
                   for k in secrets):
            return None
        data = jsonlib.loads(unb64(payload))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("algorithm", "").upper() == "HMAC-SHA256" else None


def url(host: str, path: str) -> str:
    return f"{host}/{get_settings().meta_graph_version}/{path.lstrip('/')}"


async def graph(method: str, full_url: str, *, token: str, params: dict[str, Any] | None = None,
                json: dict[str, Any] | None = None, bearer: bool = True) -> dict[str, Any]:
    params = dict(params or {})
    headers = {"Authorization": f"Bearer {token}"} if bearer else {}
    if not bearer:
        params["access_token"] = token
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, full_url, params=params, json=json, headers=headers)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise MetaError(err.get("error_user_msg") or err.get("message") or f"Meta answered {r.status_code}.")
    return data
