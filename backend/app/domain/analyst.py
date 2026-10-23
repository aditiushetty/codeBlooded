"""Rules for the Analyst agent's suggestions. Pure: the campaign's results (results.campaign) are passed in.

The Analyst reads the funnel and A/B results and proposes the next move. A suggestion is only as good as the
numbers it quotes, so every number in it must be one the results actually contain: a count, a rate as a whole
percent, or the ratio between two conversion rates. Anything else is refused with the numbers it may use, the same
way the fact guard refuses a price the owner never gave.
"""

import re
from itertools import combinations
from typing import Any

MIN_OPENS = 10  # fewer link opens than this and no redemptions: too early to suggest anything but "share more"
_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(%|x\b|×)?", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# Dates and clock times are not results; the Analyst may name a day ("by 31 Oct") or an hour ("around 6 pm").
_NOT_RESULTS = re.compile(rf"\b\d{{1,2}}\s+{_MONTH}\b|\b{_MONTH}\s+\d{{1,2}}\b|\b\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm)\b", re.I)


def too_early(results: dict[str, Any]) -> str | None:
    t = results["totals"]
    if not t["posts"]:
        return "Nothing is live yet, so there are no results to read."
    if t["scans"] < MIN_OPENS and not t["redeems"]:
        return (f"Only {t['scans']} link opens and no redemptions so far: too early to judge. The only sound "
                "suggestion now is to share the posts more.")
    return None


def _rates(results: dict[str, Any]) -> list[float]:
    t = results["totals"]
    rates = [t.get(k) for k in ("claim_rate", "redeem_rate", "conversion", "return_rate")]
    for rows in results["by"].values():
        rates += [r.get("conversion") for r in rows]
        rates += [x for r in rows for x in (r.get("likely") or [])]
    rates += [p.get("conversion") for p in results["posts"]]
    rates += [(results.get("repeat") or {}).get("rate")]
    for e in results.get("experiments", []):
        rates += [a.get("p_best") for a in e.get("arms", [])] + [a.get("mean") for a in e.get("arms", [])]
    return [float(r) for r in rates if isinstance(r, int | float)]


def allowed_numbers(results: dict[str, Any]) -> tuple[set[float], set[int], set[float]]:
    """-> (counts, percents, ratios) a suggestion may quote."""
    counts: set[float] = set()

    def walk(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, int | float):
            counts.add(round(float(o), 2))
        elif isinstance(o, dict):
            for k, v in o.items():
                if k not in ("asset_id", "code", "id"):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk({k: results.get(k) for k in ("totals", "by", "posts", "daily", "hours", "repeat", "experiments", "ratings")})
    rates = _rates(results)
    percents = {round(r * 100) for r in rates if 0 <= r <= 1}
    convs = [r for r in rates if r > 0]
    ratios = {round(x / y, 1) for a, b in combinations(convs, 2) for x, y in ((a, b), (b, a))}
    return counts, percents, ratios


def unsupported(text: str, results: dict[str, Any]) -> list[str]:
    """Numbers in `text` that the results do not contain."""
    counts, percents, ratios = allowed_numbers(results)
    bad = []
    text = _NOT_RESULTS.sub(" ", re.sub(r"(?<=\d),(?=\d{3})", "", text))
    for m in _NUM.finditer(text):
        n, unit = float(m.group(1)), (m.group(2) or "").lower()
        if unit == "%":
            ok = any(abs(n - p) <= 1 for p in percents)
        elif unit in ("x", "×"):
            ok = any(abs(n - r) <= 0.15 for r in ratios)
        else:
            ok = n in counts or (n.is_integer() and n <= 3)  # "one or two posts", "3 days" are plain words
        if not ok:
            bad.append(m.group(0).strip())
    return bad


SURE_TIPS = ("best_channel", "best_language", "best_segment", "ab_winner")


def sure_findings(results: dict[str, Any]) -> list[str]:
    """Comparisons the results support at analytics.SURE (90%) or an A/B winner: the only ones worth acting on."""
    return [t["title"] for t in results.get("tips", []) if t.get("kind") in SURE_TIPS]


def unsupported_move(kind: str, results: dict[str, Any]) -> str | None:
    """Seen live: 1 redemption from stories against 0 from WhatsApp became "focus on stories". A move that bets
    on one option over another needs a difference the data make likely, not a lucky one."""
    if kind == "more_of_what_works" and not any(t.startswith("best_") for t in _tip_kinds(results)):
        return ("The results cannot tell yet which channel, language or audience works better (no difference is at "
                f"least 90% likely; {numbers_hint(results)}). Suggest sharing more or reminding people who claimed "
                "a code instead, or wait for more data.")
    if kind == "use_ab_winner" and "ab_winner" not in _tip_kinds(results):
        return "The A/B test has no winner yet; it needs more link opens."
    return None


def _tip_kinds(results: dict[str, Any]) -> set[str]:
    return {t.get("kind") for t in results.get("tips", [])}


def numbers_hint(results: dict[str, Any]) -> str:
    t = results["totals"]
    return (f"{t['scans']} opens, {t['claims']} codes claimed, {t['redeems']} redeemed"
            + (f", conversion {round(t['conversion'] * 100)}%" if t.get("conversion") is not None else ""))
