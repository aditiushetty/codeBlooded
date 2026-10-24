"""The key indicator (which API keys work and which need replacing) and an owner's answer that arrives while an
agent is still running."""

import time
from types import SimpleNamespace

from pydantic import SecretStr

from app import keys
from app.agent import runtime
from app.config import get_settings
from app.db import connection
from app.providers.router import CallRecord


def test_errors_are_sorted_into_what_the_owner_does_about_them():
    assert keys.classify("429 RESOURCE_EXHAUSTED: You exceeded your current quota") == "used_up"
    assert keys.classify("Sarvam 402 insufficient credits") == "used_up"
    assert keys.classify("400 API key not valid. Please pass a valid API key.") == "rejected"
    assert keys.classify("401 Invalid API Key") == "rejected"
    assert keys.classify("ReadTimeout") == "error"


def _call(provider: str, ok: bool, error: str | None = None) -> CallRecord:
    return CallRecord(time.time(), "generation", provider, provider, ok, False, 10, 10, 0.0, 100, error)


async def test_key_state_comes_from_real_calls(client, monkeypatch):
    s = get_settings().model_copy(update={"gemini_api_key": SecretStr("g"), "gemini_api_key_2": None,
                                          "groq_api_key": SecretStr("q"), "cerebras_api_key": None,
                                          "agnes_api_key": None, "gemini_models": "gem-a,gem-b"})
    monkeypatch.setattr(keys, "get_settings", lambda: s)
    monkeypatch.setattr(keys, "_checked", {})
    router = SimpleNamespace(calls=[_call("gem-a", False, "429 quota"), _call("gem-b", True), _call("groq", False, "401 Invalid API Key")])

    async with connection() as conn:
        out = await keys.status(conn, router)
    by = {k["id"]: k for k in out["keys"]}
    assert by["gemini"]["state"] == "ok" and "1 of its models ran out" in by["gemini"]["note"]
    assert by["groq"]["state"] == "rejected"
    assert by["gemini_2"]["state"] == by["cerebras"]["state"] == "off"
    assert out["overall"] == "amber" and "Groq" in out["summary"]

    router.calls = [_call("gem-a", False, "429 quota"), _call("gem-b", False, "429 RESOURCE_EXHAUSTED"),
                    _call("groq", False, "401 Invalid API Key")]
    async with connection() as conn:
        out = await keys.status(conn, router)
    assert {k["id"]: k["state"] for k in out["keys"]}["gemini"] == "used_up"
    assert out["overall"] == "red"  # nothing can write a post


async def test_key_route_never_returns_a_key_and_is_members_only(client):
    r = await client.get("/api/businesses/kaapi-kone/keys")
    assert r.status_code == 200
    body = r.text
    for k in keys.KEYS:
        secret = getattr(get_settings(), keys._SECRET[k.id])
        if secret is not None:
            assert secret.get_secret_value() not in body
    assert {"overall", "keys", "channels", "summary"} <= set(r.json())
    client.user["id"] = "00000000-0000-0000-0000-00000000dead"
    assert (await client.get("/api/businesses/kaapi-kone/keys")).status_code == 404


async def test_an_answer_given_mid_run_is_taken_up_when_the_run_ends(monkeypatch):
    ctx = SimpleNamespace(campaign_id="c-mid-run", business={"id": "b"})
    key = "c-mid-run"

    # A second trigger while the first run holds the campaign: queued, not dropped.
    runtime._running.add(key)
    try:
        out = await runtime._run(ctx, "The owner answered: ₹50 off")
    finally:
        runtime._running.discard(key)
    assert out["status"] == "busy" and runtime._queued[key] == ["The owner answered: ₹50 off"]

    seen: list[str] = []

    async def fake_run(_ctx, trigger):
        seen.append(trigger)
        return {"status": "done"}

    monkeypatch.setattr(runtime, "_run_limited", fake_run)
    await runtime.run(ctx, "New brief")
    assert seen == ["New brief", "While you were working: The owner answered: ₹50 off"]
    assert key not in runtime._queued


async def test_campaign_list_says_whether_an_agent_is_on_it(client):
    c = (await client.get("/api/businesses/kaapi-kone")).json()["campaigns"][0]
    assert {"working", "ready", "facts", "last_run"} <= set(c)
    assert c["working"] is False
