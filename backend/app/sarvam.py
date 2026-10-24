"""Sarvam AI, for the two jobs where general LLMs are weakest in Kannada and Hindi.

- Speech to text (`saaras`): the owner speaks a brief in Kannada, Hindi or English.
- Translation (`mayura`): an independent translation of a post or an offer wording into English, made by a
  dedicated translation model rather than the model that wrote it. The checker compares meanings against it.
- Text to speech (`bulbul`): the voice-over of a photo reel, reading the post's own checked words.

Optional. Every caller works without a key: voice falls back to the browser, the checker to its own reading.
"""

import asyncio
import base64
import hashlib
import logging
import re
from typing import Any

import httpx

from app import keys
from app.config import get_settings

log = logging.getLogger(__name__)

LANG = {"en": "en-IN", "kn": "kn-IN", "hi": "hi-IN"}
FROM_CODE = {v: k for k, v in LANG.items()}
MAX_CHARS = 1000  # mayura:v1 per request
MAX_AUDIO = 3 * 1024 * 1024  # the REST endpoint is for clips under 30 seconds


class SarvamError(Exception):
    pass


def available() -> bool:
    return get_settings().sarvam_api_key is not None


def _headers() -> dict[str, str]:
    key = get_settings().sarvam_api_key
    if key is None:
        raise SarvamError("Sarvam is not set up.")
    return {"api-subscription-key": key.get_secret_value()}


def _raise_for(r: httpx.Response) -> None:
    if r.status_code == 200:
        keys.sarvam_result(True)
        return
    try:
        msg = (r.json().get("error") or {}).get("message") or r.text[:200]
    except ValueError:
        msg = r.text[:200]
    keys.sarvam_result(False, f"{r.status_code} {msg}")
    raise SarvamError(f"Sarvam {r.status_code}: {msg}")


async def transcribe(audio: bytes, mime: str, language: str | None) -> dict[str, Any]:
    """Audio clip -> {"transcript", "language"} (language as en/kn/hi when recognised)."""
    if len(audio) > MAX_AUDIO:
        raise SarvamError("That recording is too long. Keep it under 30 seconds.")
    s = get_settings()
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}
    name = f"brief.{ext.get(mime.split(';')[0], 'webm')}"
    data = {"model": s.sarvam_stt_model, "language_code": LANG.get(language or "", "unknown")}
    async with httpx.AsyncClient(timeout=40) as c:
        r = await c.post(f"{s.sarvam_base_url}/speech-to-text", headers=_headers(), data=data,
                         files={"file": (name, audio, mime.split(";")[0] or "audio/webm")})
    _raise_for(r)
    body = r.json()
    code = body.get("language_code") or ""
    return {"transcript": (body.get("transcript") or "").strip(), "language": FROM_CODE.get(code, code or language)}


def _chunks(text: str) -> list[str]:
    """Split on sentence ends so each request stays under the model's character limit."""
    out, cur = [], ""
    for part in re.split(r"(?<=[.!?।\n])\s+", text.strip()):
        while len(part) > MAX_CHARS:
            out.append(part[:MAX_CHARS])
            part = part[MAX_CHARS:]
        if len(cur) + len(part) + 1 > MAX_CHARS and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur} {part}".strip()
    return [*out, cur] if cur else out


def _cache_key(model: str, source: str, target: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{source}|{target}|{text}".encode()).hexdigest()


async def _cached(key: str) -> str | None:
    from app.db import connection, fetch_one

    try:
        async with connection() as conn:
            row = await fetch_one(conn, "select translated from translation_cache where key = %s", (key,))
    except Exception:  # no database (scripts) or no table yet: just translate
        return None
    return row and row["translated"]


async def _remember(key: str, model: str, source: str, target: str, text: str, out: str) -> None:
    from app.db import connection

    try:
        async with connection() as conn:
            await conn.execute(
                """insert into translation_cache (key, model, source_lang, target_lang, source, translated)
                   values (%s, %s, %s, %s, %s, %s) on conflict (key) do nothing""",
                (key, model, source, target, text, out))
    except Exception:
        log.debug("translation cache unavailable", exc_info=True)


async def translate(text: str, source: str, target: str = "en") -> str:
    """Sarvam translation, paid for once per distinct text (translation_cache)."""
    s = get_settings()
    key = _cache_key(s.sarvam_translate_model, source, target, text.strip())
    if (hit := await _cached(key)) is not None:
        return hit
    out = await _translate(text, source, target)
    if out:
        await _remember(key, s.sarvam_translate_model, source, target, text.strip(), out)
    return out


async def _translate(text: str, source: str, target: str) -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30) as c:
        parts = []
        for chunk in _chunks(text):
            r = await c.post(f"{s.sarvam_base_url}/translate", headers=_headers(), json={
                "input": chunk, "source_language_code": LANG.get(source, "auto"),
                "target_language_code": LANG[target], "model": s.sarvam_translate_model,
                "mode": "formal", "numerals_format": "international",
            })
            _raise_for(r)
            parts.append((r.json().get("translated_text") or "").strip())
    return " ".join(p for p in parts if p)


async def to_english(text: str, language: str) -> str | None:
    """Independent English reading of Kannada or Hindi text, or None (no key, other language, or Sarvam failed)."""
    if not available() or language not in ("kn", "hi") or not text.strip():
        return None
    try:
        return await translate(text, language, "en") or None
    except (SarvamError, httpx.HTTPError):
        return None


async def many_to_english(items: list[tuple[str, str]]) -> list[str | None]:
    """[(text, language)] -> English for each, in parallel (a few at a time to respect rate limits)."""
    sem = asyncio.Semaphore(4)

    async def one(t: str, lang: str) -> str | None:
        async with sem:
            return await to_english(t, lang)

    return list(await asyncio.gather(*(one(t, lang) for t, lang in items)))


async def speak(text: str, language: str) -> str:
    """A voice-over of `text` (bulbul), stored once: -> storage key of the WAV. The same text in the same language
    is never paid for twice (the key is remembered in translation_cache under the TTS model's name)."""
    from app.storage import get_storage

    s = get_settings()
    text = re.sub(r"\s+", " ", text).strip()
    key = _cache_key(s.sarvam_tts_model, language, "speech", text)
    if (hit := await _cached(key)) is not None:
        return hit
    body: dict[str, Any] = {"text": text[:2400], "target_language_code": LANG.get(language, "en-IN"),
                            "model": s.sarvam_tts_model}
    if s.sarvam_tts_speaker:
        body["speaker"] = s.sarvam_tts_speaker
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{s.sarvam_base_url}/text-to-speech", headers=_headers(), json=body)
    _raise_for(r)
    audios = r.json().get("audios") or []
    if not audios:
        raise SarvamError("Sarvam returned no audio.")
    data = b"".join(base64.b64decode(a) for a in audios[:1])
    stored = await get_storage().put(f"voice/{key[:40]}.wav", data, "audio/wav")
    await _remember(key, s.sarvam_tts_model, language, "speech", text, stored)
    return stored
