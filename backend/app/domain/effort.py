"""How much of the owner's attention a campaign took, from idea to live posts. Pure: ledger events are passed in.

  taps     owner actions up to the first live post (sending the brief, answering a question, locking the offer,
           approving posts). Actions within a few seconds of each other are one tap: one "approve and publish"
           writes several events.
  minutes  from the brief to the first live post, split into the time the team was working and the time it
           was waiting for the owner (from a question or an approval request until the owner's next action).
"""

from datetime import datetime
from typing import Any

SAME_TAP_S = 3
NOT_EFFORT = ("outcome.", "brand.", "photos.", "moment.", "channel.", "bills.")  # not part of making the campaign
ASKS = ("approval.requested", "question.asked")


def summarize(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """events: [{type, actor, created_at}] of one campaign, any order. None before the campaign has a brief."""
    ev = sorted(events, key=lambda e: e["created_at"])
    start = next((e["created_at"] for e in ev if e["type"] == "campaign.created"), ev[0]["created_at"] if ev else None)
    if start is None:
        return None
    live = next((e["created_at"] for e in ev if e["type"] == "assets.published"), None)
    end: datetime = live or ev[-1]["created_at"]
    window = [e for e in ev if start <= e["created_at"] <= end]

    taps, last = [], None
    for e in window:
        if e["actor"] != "owner" or e["type"].startswith(NOT_EFFORT):
            continue
        if last is None or (e["created_at"] - last).total_seconds() > SAME_TAP_S:
            taps.append({"type": e["type"], "at": e["created_at"]})
        last = e["created_at"]

    team = waiting = 0.0
    running = asked = None
    for e in window:
        t = e["created_at"]
        if e["type"] == "agent.started":
            running = running or t
        elif e["type"] in ("agent.finished", "agent.failed") and running:
            team += (t - running).total_seconds()
            running = None
        if e["type"] in ASKS and e["actor"] != "owner":
            asked = asked or t
        elif e["actor"] == "owner" and asked:
            waiting += (t - asked).total_seconds()
            asked = None
    if running:
        team += (end - running).total_seconds()
    if asked and not live:
        waiting += (end - asked).total_seconds()
    return {"live": live is not None, "started_at": start, "live_at": live, "taps": len(taps),
            "tap_list": [t["type"] for t in taps], "minutes": round((end - start).total_seconds() / 60, 1),
            "team_minutes": round(team / 60, 1), "waiting_minutes": round(waiting / 60, 1)}


def typical(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The median taps and minutes over campaigns that went live."""
    done = [r for r in rows if r and r["live"]]
    if not done:
        return None

    def median(xs: list[float]) -> float:
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2, 1)

    return {"campaigns": len(done), "taps": median([r["taps"] for r in done]),
            "minutes": median([r["minutes"] for r in done]), "waiting_minutes": median([r["waiting_minutes"] for r in done])}
