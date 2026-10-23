"""What an offer draft is still missing, found by rules rather than by a model.

The Offer agent drafts facts from the owner's half-formed idea ("15% off coffee for students"). Before anything is
locked, these checks say what a customer or the counter would still have to guess: what they get, on what, and
when. A gap that `blocks` stops the agent from asking for the lock; the owner can still lock it themselves.
"""

from datetime import date
from typing import Any

from app.domain import redeem

BENEFIT = ("percent", "price")


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [p.strip() for p in value.replace("+", ",").split(",") if p.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def gaps(facts: list[dict[str, Any]], menu: list[dict[str, Any]], *, today: date,
         starts_on: date | None = None, ends_on: date | None = None) -> list[dict[str, Any]]:
    """[{key, issue, ask, blocks}] for a facts draft. `ask` is the question to put to the owner."""
    out: list[dict[str, Any]] = []

    def gap(key: str | None, issue: str, ask: str, blocks: bool = True) -> None:
        out.append({"key": key, "issue": issue, "ask": ask, "blocks": blocks})

    by_type: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_type.setdefault(f.get("type", "text"), []).append(f)

    benefits = [f for t in BENEFIT for f in by_type.get(t, [])]
    if not benefits:
        gap(None, "The offer does not say what the customer gets.",
            "What does the customer get: a percentage off, a set price, or something free?")
    for f in by_type.get("percent", []):
        v = f.get("value")
        if not isinstance(v, int | float) or not 0 < v <= 90:
            gap(f["key"], f"A discount of {v!r} is not a usable percentage.", "What percentage off is it?")
    for f in by_type.get("price", []):
        v = f.get("value")
        if not isinstance(v, int | float) or v <= 0:
            gap(f["key"], f"A price of {v!r} is not usable.", "What price does the customer pay?")

    on_menu = {m["name"].casefold() for m in menu}
    items = by_type.get("item", [])
    for f in items:
        names = _names(f.get("value"))
        if not names:
            gap(f["key"], "The items are not named.", "Which items is the offer on?")
        elif on_menu and (missing := [n for n in names if n.casefold() not in on_menu]):
            gap(f["key"], f"Not on the menu: {', '.join(missing)}.",
                f"{', '.join(missing)} is not on your menu. Which menu item did you mean?")
    if benefits and not items and on_menu:
        gap(None, "The discount does not say which items it applies to.",
            "Is it on the whole bill, or only on certain items?", blocks=False)

    dated = by_type.get("date_range", [])
    for f in dated:
        ds = redeem._dates(f.get("value"))
        if len(ds) != 2:
            gap(f["key"], "The dates are not a start and an end (YYYY-MM-DD).", "Which day does it start and end?")
            continue
        start, end = ds
        if end < start:
            gap(f["key"], "The offer ends before it starts.", "Which day does it start and end?")
        elif end < today:
            gap(f["key"], f"The offer already ended on {end.isoformat()}.", "Which dates should it run on?")
    if not dated and not (starts_on and ends_on):
        gap(None, "The offer has no end date, so it would run forever.", "Until which date does the offer run?")

    for f in by_type.get("time_range", []):
        if redeem.rules([f]).hours is None:
            gap(f["key"], "The hours are not written as HH:MM-HH:MM.", "Which hours does it run, for example 16:00-19:00?")
    return out


def blocking(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in found if g["blocks"]]


def summary(found: list[dict[str, Any]]) -> str:
    return "; ".join(g["issue"] for g in found)
