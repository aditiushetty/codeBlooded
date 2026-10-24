"""Which API keys are set, which work, and which need replacing.

The owner sees one dot in the header: green when everything works, amber when a key has run out or a backup is
missing, red when no AI model can answer. Each key's state comes from what actually happened: the router's recent
calls (in memory since the server started), the last successful call stored in `model_calls`, Sarvam's last
answer, and an explicit check (`check`) that asks each provider whether the key is valid. That check only lists
models or reads the account, so it never spends generation quota or credits.

Keys are never returned, only whether they are set.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

from app.config import Settings, get_settings
from app.db import Conn, fetch_all
from app.providers import SECOND_KEY
from app.providers.router import ModelRouter

State = Literal["ok", "used_up", "rejected", "error", "unchecked", "off"]
WORST: list[State] = ["rejected", "used_up", "error", "unchecked", "ok", "off"]


@dataclass(frozen=True)
class Key:
    id: str
    name: str
    env: str
    job: str
    get_url: str
    ai: bool = False  # a text model key: when none of these work, nothing gets written


KEYS = [
    Key("gemini", "Gemini", "GEMINI_API_KEY", "Writes, checks and plans. The main AI.",
        "https://aistudio.google.com/apikey", ai=True),
    Key("gemini_2", "Gemini, second key", "GEMINI_API_KEY_2", "More free Gemini quota from a second Google project.",
        "https://aistudio.google.com/apikey", ai=True),
    Key("groq", "Groq", "GROQ_API_KEY", "Free backup when Gemini runs out.", "https://console.groq.com/keys", ai=True),
    Key("cerebras", "Cerebras", "CEREBRAS_API_KEY", "Free backup, and the checker's own model.",
        "https://cloud.cerebras.ai", ai=True),
    Key("agnes", "Agnes", "AGNES_API_KEY", "AI pictures and the last text backup.", "https://apihub.agnes-ai.com",
        ai=True),
    Key("sarvam", "Sarvam", "SARVAM_API_KEY", "Voice briefs, Kannada and Hindi translation checks, reel voice.",
        "https://dashboard.sarvam.ai"),
    Key("google_maps", "Google Maps", "GOOGLE_MAPS_API_KEY", "Photos and details from your Google Maps listing.",
        "https://console.cloud.google.com/apis/credentials"),
    Key("supabase", "Supabase storage", "SUPABASE_SERVICE_ROLE_KEY",
        "Keeps pictures online, which Instagram needs to publish.", "https://supabase.com/dashboard"),
    Key("meta", "Meta app secret", "META_APP_SECRET", "Proves WhatsApp and Instagram messages really come from Meta.",
        "https://developers.facebook.com/apps"),
]
_SECRET = {"gemini": "gemini_api_key", "gemini_2": "gemini_api_key_2", "groq": "groq_api_key",
           "cerebras": "cerebras_api_key", "agnes": "agnes_api_key", "sarvam": "sarvam_api_key",
           "google_maps": "google_maps_api_key", "supabase": "supabase_service_role_key", "meta": "meta_app_secret"}

# Last result of `check` per key, and Sarvam's last answer (reported by app.sarvam).
_checked: dict[str, tuple[float, State, str]] = {}
_sarvam: dict[str, Any] = {}


def classify(error: str) -> State:
    t = error.lower()
    if any(x in t for x in ("401", "403", "api key not valid", "invalid api key", "invalid_api_key", "incorrect api key",
                            "unauthorized", "permission_denied", "forbidden", "invalid authentication")):
        return "rejected"
    if any(x in t for x in ("quota", "resource_exhausted", "429", "rate limit", "rate_limit", "credits", "402",
                            "insufficient", "too many requests")):
        return "used_up"
    return "error"


def sarvam_result(ok: bool, error: str | None = None) -> None:
    _sarvam.update(at=time.time(), state="ok" if ok else classify(error or ""), error=(error or "")[:200] or None)


def _owner(provider: str, s: Settings) -> str | None:
    gemini = {m.strip() for m in s.gemini_models.split(",") if m.strip()}
    if provider.endswith(SECOND_KEY) and provider[: -len(SECOND_KEY)] in gemini:
        return "gemini_2"
    if provider in gemini:
        return "gemini"
    return provider if provider in ("groq", "cerebras", "agnes") else None


def _models_url(key: str, s: Settings) -> str | None:
    return {"gemini": f"{s.gemini_base_url}/models", "gemini_2": f"{s.gemini_base_url}/models",
            "groq": f"{s.groq_base_url}/models", "cerebras": f"{s.cerebras_base_url}/models",
            "agnes": f"{s.agnes_base_url}/models"}.get(key)


async def check(s: Settings | None = None) -> None:
    """Ask each AI provider to list its models with the key. Free: no generation, no quota spent."""
    s = s or get_settings()
    async with httpx.AsyncClient(timeout=15) as c:
        for k in KEYS:
            secret, url = getattr(s, _SECRET[k.id]), _models_url(k.id, s)
            if secret is None or url is None:
                continue
            try:
                r = await c.get(url, headers={"Authorization": f"Bearer {secret.get_secret_value()}"})
                state: State = "ok" if r.status_code == 200 else classify(f"{r.status_code} {r.text[:200]}")
                note = "" if state == "ok" else f"{r.status_code}: {r.text[:160]}"
            except httpx.HTTPError as e:
                state, note = "error", f"Could not reach it: {type(e).__name__}"
            _checked[k.id] = (time.time(), state, note)


def _when(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


async def status(conn: Conn, router: ModelRouter, *, business: dict[str, Any] | None = None) -> dict[str, Any]:
    s = get_settings()
    # Latest call per model, since the server started.
    latest: dict[str, Any] = {}
    for c in router.calls:
        if not c.replayed:
            latest[c.provider] = c
    worked = {r["provider"]: r["at"] for r in await fetch_all(
        conn, """select provider, max(created_at) as at from model_calls
                 where ok and not replayed and created_at > now() - interval '7 days' group by provider""")}

    out = []
    for k in KEYS:
        set_ = getattr(s, _SECRET[k.id]) is not None
        item: dict[str, Any] = {"id": k.id, "name": k.name, "env": k.env, "job": k.job, "get_url": k.get_url,
                                "ai": k.ai, "set": set_, "state": "off" if not set_ else "unchecked", "note": None,
                                "last_ok": None}
        if not set_:
            out.append(item)
            continue
        if k.ai:
            mine = {p: c for p, c in latest.items() if _owner(p, s) == k.id}
            states = [("ok" if c.ok else classify(c.error or "")) for c in mine.values()]
            last_ok = max((w for p, w in worked.items() if _owner(p, s) == k.id), default=None)
            item["last_ok"] = last_ok
            used_up = states.count("used_up")
            if "ok" in states:
                item["state"] = "ok"
                if used_up:
                    item["note"] = f"{used_up} of its models ran out today; the others still answer."
            elif "rejected" in states:
                item["state"], item["note"] = "rejected", "The provider refused this key."
            elif states and used_up == len(states):
                item["state"] = "used_up"
                item["note"] = ("Every model tried on this key is out of free quota. It usually comes back the "
                                "next day." if k.id.startswith("gemini") else "Out of quota for now.")
            elif states:
                item["state"] = "error"
                item["note"] = next((c.error for c in mine.values() if not c.ok and c.error), None)
            elif last_ok:
                item["state"] = "ok"
        elif k.id == "sarvam" and _sarvam:
            item["state"], item["note"], item["last_ok"] = _sarvam["state"], _sarvam.get("error"), (
                _when(_sarvam["at"]) if _sarvam["state"] == "ok" else None)
            if _sarvam["state"] == "used_up":
                item["note"] = "Sarvam says the credits are used up. Top up or use a new key."
        elif k.id in ("supabase", "meta", "google_maps"):
            item["state"] = "ok"  # set; used only when needed, and failures show where they happen
        if (chk := _checked.get(k.id)) and (item["state"] in ("unchecked", "ok") or chk[1] == "rejected"):
            at, state, note = chk
            if state != "ok" or item["state"] == "unchecked":
                item["state"], item["note"] = state, note or item["note"]
            item["checked_at"] = _when(at)
        out.append(item)

    channels = []
    if business:
        rows = await fetch_all(conn, """select channel, display, token_expires_at from channel_accounts
                                        where business_id = %s and channel in ('instagram', 'whatsapp')""",
                               (business["id"],))
        now = datetime.now(UTC)
        for r in rows:
            exp = r["token_expires_at"]
            state: State = "ok"
            note = None
            if exp and exp < now:
                state, note = "rejected", "The login expired. Connect it again on the Channels page."
            elif exp and exp - now < timedelta(days=7):
                state, note = "used_up", f"The login expires in {max(1, (exp - now).days)} days. Connect it again."
            channels.append({"id": r["channel"], "name": "Instagram" if r["channel"] == "instagram" else "WhatsApp",
                             "display": r["display"], "state": state, "note": note, "expires_at": exp})

    ai = [i for i in out if i["ai"] and i["set"]]
    writing = any(i["state"] in ("ok", "unchecked", "error") for i in ai)
    trouble = [i for i in out + channels if i["state"] in ("rejected", "used_up", "error")]
    overall = "red" if not writing else "amber" if trouble or not any(i["state"] == "ok" for i in ai) else "green"
    if overall == "green" and not trouble and len(ai) < 2:
        overall = "amber"  # one AI key and no backup: the first busy day stops everything
    return {"overall": overall, "keys": out, "channels": channels,
            "summary": _summary(overall, ai, trouble), "how_to_set": "uv run python -m scripts.set_secret NAME"}


def _summary(overall: str, ai: list[dict[str, Any]], trouble: list[dict[str, Any]]) -> str:
    if overall == "red":
        return "No AI key works right now, so nothing new can be written. Add or replace a key below."
    if trouble:
        names = ", ".join(t["name"] for t in trouble[:3])
        return f"Needs attention: {names}."
    if len(ai) < 2:
        return "Everything works, but there is only one AI key. Add a free backup (Groq or Cerebras)."
    working = sum(i["state"] == "ok" for i in ai)
    return f"{working} AI keys answer, so when one runs out the next takes over."
