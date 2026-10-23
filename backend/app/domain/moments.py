"""What is happening around the business in the next days, as "moments" a campaign can ride on.

Every moment says where it came from, so the Scout agent never has to invent one:
  weather   - the Open-Meteo forecast for the business's city (rain this evening, a hot afternoon)
  calendar  - plain calendar facts (the weekend, salary week)
  event     - the business's own calendar, and things the owner added ("IPL final on Sunday", "college fest")
Pure: the forecast and event rows are passed in.
"""

from datetime import date, timedelta
from typing import Any

RAIN = 60  # % chance of rain in the evening that makes "rainy evening" a moment
HOT = 33  # °C afternoon high


def _label(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return d.strftime("%a %-d %b")


def from_weather(days: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """days: [{date, evening_rain_pct, tmax}] from the forecast."""
    out = []
    for d in days:
        day = date.fromisoformat(d["date"])
        when = _label(day, today)
        if (d.get("evening_rain_pct") or 0) >= RAIN:
            evening = "this evening" if day == today else f"{when} evening"
            out.append({"key": f"rain-{day}", "kind": "weather", "title": f"Rain likely {evening}",
                        "starts_on": day.isoformat(), "ends_on": day.isoformat(), "when": when,
                        "detail": f"{d['evening_rain_pct']}% chance of rain between 4 and 9 pm",
                        "source": "Open-Meteo forecast", "hint": "people stay in or look for somewhere warm nearby"})
        elif (d.get("tmax") or 0) >= HOT:
            out.append({"key": f"hot-{day}", "kind": "weather", "title": f"Hot afternoon {when}",
                        "starts_on": day.isoformat(), "ends_on": day.isoformat(), "when": when,
                        "detail": f"up to {round(d['tmax'])}°C", "source": "Open-Meteo forecast",
                        "hint": "cold drinks and a cool place to sit"})
    return out


def calendar(today: date, days: int = 10) -> list[dict[str, Any]]:
    out = []
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    if sat <= today + timedelta(days=days):
        sun = sat + timedelta(days=1)
        when = "this weekend" if (sat - today).days < 6 else f"weekend of {sat:%-d %b}"
        out.append({"key": f"weekend-{sat}", "kind": "calendar", "title": f"The weekend ({sat:%a %-d} and {sun:%a %-d %b})",
                    "starts_on": sat.isoformat(), "ends_on": sun.isoformat(), "when": when, "detail": None,
                    "source": "Calendar", "hint": "families and friends out together, slower mornings"})
    # Salary week: the last days of the month and the first of the next, when people spend more freely.
    first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    start = first_next - timedelta(days=3)
    if start <= today + timedelta(days=days) and today <= first_next + timedelta(days=2):
        out.append({"key": f"payday-{first_next:%Y-%m}", "kind": "calendar", "title": "Salary week",
                    "starts_on": max(start, today).isoformat(), "ends_on": (first_next + timedelta(days=2)).isoformat(),
                    "when": _label(max(start, today), today), "detail": "end of the month and the first days of the next",
                    "source": "Calendar", "hint": "people treat themselves and their teams"})
    return out


def from_events(rows: list[dict[str, Any]], today: date, days: int = 14) -> list[dict[str, Any]]:
    """rows: customer_insights events {key, period_start, period_end, data}. Ongoing or starting within `days`."""
    out = []
    horizon = today + timedelta(days=days)
    for r in rows:
        start, end = r.get("period_start"), r.get("period_end") or r.get("period_start")
        if not start or start > horizon or (end and end < today):
            continue
        data = r.get("data") or {}
        owner = data.get("added_by") == "owner"
        out.append({"key": f"event-{r['key']}", "kind": "event", "title": data.get("name", r["key"]),
                    "starts_on": start.isoformat(), "ends_on": (end or start).isoformat(),
                    "when": "on now" if start <= today else _label(start, today),
                    "detail": data.get("note") or data.get("time"),
                    "source": "You added this" if owner else "Your business calendar",
                    "hint": data.get("hook"), "removable": owner})
    return out


def merge(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for m in sorted((m for g in groups for m in g), key=lambda m: (m["starts_on"], m["kind"] != "event")):
        if m["key"] not in seen:
            seen.add(m["key"])
            out.append(m)
    return out
