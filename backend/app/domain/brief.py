"""Rules for the Brief agent's plan. Pure.

A plan is audience x channel x language cells. The Brief agent proposes it; these rules refuse a plan that the
rest of the team could not carry out: a language the business does not use, a channel that does not exist, too
many posts for one campaign, or a goal without a number to judge it by.
"""

from typing import Any

CHANNELS = ("instagram_post", "instagram_story", "whatsapp", "poster")
MAX_CELLS = 12
MAX_AUDIENCES = 3


def problems(goal: dict[str, Any], plan: dict[str, Any], languages: list[str]) -> list[str]:
    out = []
    cells = plan.get("cells") or []
    if not cells:
        out.append("The plan has no posts: add at least one audience x channel x language cell.")
    if len(cells) > MAX_CELLS:
        out.append(f"{len(cells)} posts is too many for one campaign; keep it to {MAX_CELLS} or fewer.")
    for c in cells:
        if not isinstance(c, dict):
            out.append("Each cell needs segment, channel and language.")
            break
        if c.get("channel") not in CHANNELS:
            out.append(f"Unknown channel {c.get('channel')!r}; use one of {', '.join(CHANNELS)}.")
        if c.get("language") not in languages:
            out.append(f"The business does not use language {c.get('language')!r}; it uses {', '.join(languages)}.")
        if not str(c.get("segment") or "").strip():
            out.append("Every cell needs an audience (segment).")
    audiences = {str(c.get("segment")).casefold() for c in cells if isinstance(c, dict) and c.get("segment")}
    if len(audiences) > MAX_AUDIENCES:
        out.append(f"{len(audiences)} audiences spreads one campaign thin; pick at most {MAX_AUDIENCES}.")
    kpi = goal.get("kpi") if isinstance(goal, dict) else None
    if not isinstance(kpi, dict) or not kpi.get("metric") or not isinstance(kpi.get("target"), int | float):
        out.append("The goal needs a number to judge it by: kpi {metric, target, window_days}, e.g. 40 redemptions "
                   "in 14 days.")
    return list(dict.fromkeys(out))
