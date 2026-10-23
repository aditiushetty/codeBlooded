"""Moments around the business (domain/moments.py) and the Scout agent that turns them into campaign ideas.

Weather comes from Open-Meteo (free, no key), cached per city for 30 minutes; if it is unreachable the other
moments still show. The Scout makes one model call; every idea it returns must name a real moment and only real
menu items, or it is dropped.
"""

import json
import logging
import time
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.db import Conn, fetch_all
from app.domain import moments as rules
from app.providers.router import ModelRouter, call_scope

log = logging.getLogger(__name__)
GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TTL = 30 * 60
_weather: dict[str, tuple[float, list[dict[str, Any]]]] = {}


async def forecast(city: str) -> list[dict[str, Any]]:
    """[{date, evening_rain_pct, tmax}] for the next 4 days, or [] when the forecast is unavailable."""
    hit = _weather.get(city.casefold())
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            g = (await c.get(GEO, params={"name": city, "count": 1, "country": "IN"})).json().get("results") or []
            if not g:
                return []
            r = await c.get(FORECAST, params={
                "latitude": g[0]["latitude"], "longitude": g[0]["longitude"], "timezone": "Asia/Kolkata",
                "forecast_days": 4, "daily": "temperature_2m_max", "hourly": "precipitation_probability"})
            body = r.json()
    except (httpx.HTTPError, ValueError, KeyError):
        log.info("forecast unavailable for %s", city, exc_info=True)
        return []
    evening: dict[str, int] = {}
    for t, p in zip(body["hourly"]["time"], body["hourly"]["precipitation_probability"], strict=False):
        if 16 <= int(t[11:13]) <= 21 and p is not None:
            evening[t[:10]] = max(evening.get(t[:10], 0), int(p))
    days = [{"date": d, "evening_rain_pct": evening.get(d, 0), "tmax": tmax}
            for d, tmax in zip(body["daily"]["time"], body["daily"]["temperature_2m_max"], strict=False)]
    _weather[city.casefold()] = (time.time(), days)
    return days


def cached_forecast(city: str) -> list[dict[str, Any]]:
    """The last forecast fetched for this city, without a network call (for the agent's snapshot)."""
    hit = _weather.get(city.casefold())
    return hit[1] if hit and time.time() - hit[0] < TTL else []


async def event_rows(conn: Conn, business_id: Any) -> list[dict[str, Any]]:
    return await fetch_all(conn, """select key, period_start, period_end, data from customer_insights
                                    where business_id = %s and kind = 'event' order by period_start""", (business_id,))


def combine(rows: list[dict[str, Any]], weather: list[dict[str, Any]], today: date, days: int = 14) -> list[dict[str, Any]]:
    return rules.merge(rules.from_events(rows, today, days), rules.from_weather(weather, today),
                       rules.calendar(today, min(days, 10)))


# ------------------------------------------------------------------ the Scout agent

SCOUT_SYSTEM = """You are the Scout on the marketing team of {name}, a {kind} in {locality}, {city}.
You look at what is happening around the business in the next days and spot campaigns worth running.

You get the moments (each with a key and where it came from), the menu, and what customers say. Suggest at most
three campaigns, best first. Each one:
- rides on one moment from the list (moment_key exactly as given); never invent an event, match, date or weather;
- uses only items from the menu, spelled exactly as on it;
- has a brief the owner could send as is: what the offer is, for whom, when (e.g. "Hot filter coffee and onion
  pakoda combo at 10% off for rainy evenings this week, 4 to 8 pm"). Suggest a modest discount only when it helps;
- says in one plain sentence why it fits this business now (cite what customers say when it helps).
Skip a moment that does not suit this business. Plain words, no hype, no long dashes, at most one "!".
Reply with JSON: {{"ideas": [{{"moment_key", "title", "brief", "audience", "why", "items"}}]}}."""


class Idea(BaseModel):
    moment_key: str
    title: str = Field(max_length=80)
    brief: str = Field(max_length=300)
    audience: str = Field(max_length=80)
    why: str = Field(max_length=300)
    items: list[str] = Field(default_factory=list)


class Ideas(BaseModel):
    ideas: list[Idea] = Field(default_factory=list, max_length=5)


def checked(ideas: list[Idea], found: list[dict[str, Any]], menu: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ideas that name a real moment and only real menu items, with the moment attached."""
    by_key = {m["key"]: m for m in found}
    names = {m["name"].casefold(): m["name"] for m in menu}
    out = []
    for i in ideas:
        if i.moment_key not in by_key or any(n.casefold() not in names for n in i.items):
            continue
        out.append({**i.model_dump(), "items": [names[n.casefold()] for n in i.items], "moment": by_key[i.moment_key]})
    return out[:3]


async def scout(router: ModelRouter, business: dict[str, Any], found: list[dict[str, Any]],
                themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile = business.get("profile") or {}
    menu = profile.get("menu") or []
    system = SCOUT_SYSTEM.format(name=business["name"], kind=profile.get("kind", "business"),
                                 locality=business["locality"], city=business["city"])
    user = {"today": date.today().isoformat(),
            "moments": [{k: m.get(k) for k in ("key", "title", "when", "detail", "source", "hint")} for m in found],
            "menu": [{"name": m["name"], "price": m.get("price")} for m in menu],
            "what_customers_say": themes[:8]}
    with call_scope(business_id=str(business["id"]), campaign_id=None, task="find_opportunities", agent="scout"):
        result, _ = await router.chat_json(
            "reasoning", [{"role": "system", "content": system},
                          {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}],
            Ideas, temperature=0.4)
    return checked(result.ideas, found, menu)
