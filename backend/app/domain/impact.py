"""Change propagation: which assets does a fact change actually touch?"""

from typing import Any

from app.domain.facts import FactSheet


def changed_fact_keys(old: FactSheet, new: FactSheet) -> set[str]:
    old_by = {f.key: f for f in old.facts}
    new_by = {f.key: f for f in new.facts}
    changed = set(old_by) ^ set(new_by)
    for k in set(old_by) & set(new_by):
        if old_by[k].model_dump() != new_by[k].model_dump():
            changed.add(k)
    return changed


def forbidden_changed(old: FactSheet, new: FactSheet) -> bool:
    return old.forbidden_claims != new.forbidden_claims


def affected_assets(revisions: list[dict[str, Any]], changed: set[str], *, all_if: bool = False) -> list[str]:
    """revisions: [{asset_id, fact_keys}] for each asset's current revision."""
    if all_if:
        return [str(r["asset_id"]) for r in revisions]
    return [str(r["asset_id"]) for r in revisions if changed & set(r.get("fact_keys") or [])]


def change_plan(revisions: list[dict[str, Any]], changed: set[str], *, all_if: bool = False) -> dict[str, list[str]]:
    """What an offer change means for each post. revisions: [{asset_id, fact_keys, written_keys}], where
    written_keys are the slots in the text the Writer wrote (headline, body).

      rewrite   - its own text uses a changed detail: the Writer writes it again
      refill    - only the offer box under it changes: the system refills it from the new offer and re-checks it
      untouched - shows nothing that changed
    """
    out: dict[str, list[str]] = {"rewrite": [], "refill": [], "untouched": []}
    for r in revisions:
        shows = set(r.get("fact_keys") or [])
        if not (all_if or changed & shows):
            out["untouched"].append(str(r["asset_id"]))
        elif changed & set(r.get("written_keys") or []):
            out["rewrite"].append(str(r["asset_id"]))
        else:
            out["refill"].append(str(r["asset_id"]))
    return out
