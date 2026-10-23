"""The Checker test (TODO #8): 50 posts that must never go out against one locked offer, and 10 good ones.

Each draft goes through the same checks a real post does: the rules (L1 numbers and script, L2 claims, voice and
offer slots, channel limits) and, with a model, the meaning check (L3: every promise read back against the
offer). The report says how many bad drafts were caught and by which layer, and how many good ones were wrongly
blocked. `uv run python -m scripts.checker_eval [--live]` writes data/eval/checker_report.json; the AI team page
shows it.
"""

import json
import time
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.domain import audit as audit_mod
from app.domain.facts import AssetContent, FactSheet, deterministic_checks, render

DATA = REPO_ROOT / "data" / "eval" / "bad_drafts.json"
REPORT = REPO_ROOT / "data" / "eval" / "checker_report.json"
INTENT = {"core_message": "a study break for college students after class", "tone": "warm and plain"}
BATCH = 10


def load(path: Path = DATA) -> tuple[FactSheet, list[dict[str, Any]]]:
    d = json.loads(path.read_text())
    sheet = FactSheet(version=1, facts=d["facts"], forbidden_claims=d.get("forbidden_claims", {}))
    return sheet, [{**x, "bad": True} for x in d["bad"]] + [{**x, "bad": False} for x in d["good"]]


def content(draft: dict[str, Any]) -> AssetContent:
    seg = lambda t: [{"text": t, "sources": ["brand:voice"]}] if t else []  # noqa: E731
    return AssetContent.model_validate({"headline": seg(draft["headline"]), "body": seg(draft["body"]), "cta": [],
                                        "hashtags": draft.get("hashtags", [])})


def rules(draft: dict[str, Any], sheet: FactSheet) -> list[dict[str, str]]:
    """Blocking failures from the rule layers, as [{layer, detail}]."""
    checks = deterministic_checks(content(draft), sheet, lang=draft["language"], channel=draft["channel"])
    return [{"layer": c.layer, "detail": c.detail} for c in checks if not c.passed and c.severity == "block"]


NO_VERDICT = "Auditor returned no result for this asset."


async def meaning(router: Any, drafts: list[dict[str, Any]], sheet: FactSheet) -> dict[int, list[dict[str, str]]]:
    """L3 failures per draft id, in batches like the real Checker. A draft the model skipped is asked again once,
    alone in a smaller batch; if it is still skipped it is marked no_verdict (the live Checker would hold it)."""
    out: dict[int, list[dict[str, str]]] = {}

    async def ask(batch: list[dict[str, Any]]) -> None:
        items = [{"ref": str(x["id"]), "language": x["language"], "channel": x["channel"],
                  "rendered": render(content(x), sheet, x["language"])} for x in batch]
        checks, _ = await audit_mod.audit(router, items, sheet, INTENT)
        for x in batch:
            out[x["id"]] = [{"layer": c.layer, "detail": c.detail} for c in checks.get(str(x["id"]), []) if not c.passed]

    for i in range(0, len(drafts), BATCH):
        await ask(drafts[i:i + BATCH])
    skipped = [x for x in drafts if any(f["detail"] == NO_VERDICT for f in out.get(x["id"], []))]
    for i in range(0, len(skipped), 5):
        await ask(skipped[i:i + 5])
    return out


def summarize(drafts: list[dict[str, Any]], found: dict[int, list[dict[str, str]]], *, live: bool,
              model: str | None) -> dict[str, Any]:
    bad = [x for x in drafts if x["bad"]]
    good = [x for x in drafts if not x["bad"]]
    unanswered = {x["id"] for x in drafts if found[x["id"]] and all(f["detail"] == NO_VERDICT for f in found[x["id"]])}
    found = {k: ([] if k in unanswered else v) for k, v in found.items()}
    first = {x["id"]: (found[x["id"]][0]["layer"] if found[x["id"]] else None) for x in drafts}
    by_layer: dict[str, int] = {}
    for x in bad:
        if layer := first[x["id"]]:
            key = "rules" if layer != "L3" else "meaning check"
            by_layer[key] = by_layer.get(key, 0) + 1
    cats: dict[str, dict[str, int]] = {}
    for x in bad:
        c = cats.setdefault(x["category"], {"total": 0, "caught": 0})
        c["total"] += 1
        c["caught"] += bool(found[x["id"]])
    return {
        "ran_at": int(time.time()), "live": live, "model": model,
        "caught": sum(bool(found[x["id"]]) for x in bad), "bad_total": len(bad),
        "false_alarms": sum(bool(found[x["id"]]) for x in good), "good_total": len(good),
        "by_layer": by_layer, "by_category": cats,
        "no_verdict": sorted(unanswered),
        "missed": [{"id": x["id"], "category": x["category"], "language": x["language"], "headline": x["headline"],
                    "why_bad": x["why_bad"]} for x in bad if not found[x["id"]] and x["id"] not in unanswered],
        "wrongly_blocked": [{"id": x["id"], "headline": x["headline"], "reason": found[x["id"]][0]["detail"]}
                            for x in good if found[x["id"]]],
        "note": None if live else "Rules only: the meaning check (L3) needs a model; run with --live.",
    }


async def run(router: Any | None = None) -> dict[str, Any]:
    sheet, drafts = load()
    found = {x["id"]: rules(x, sheet) for x in drafts}
    model = None
    if router is not None:
        l3 = await meaning(router, drafts, sheet)
        for x in drafts:
            found[x["id"]] += l3.get(x["id"], [])
        used = [c.model for c in router.calls if c.ok and c.role == "verification" and not c.replayed]
        model = ", ".join(dict.fromkeys(used)) or None
    return summarize(drafts, found, live=router is not None, model=model)


def saved() -> dict[str, Any] | None:
    try:
        return json.loads(REPORT.read_text())
    except (OSError, ValueError):
        return None
