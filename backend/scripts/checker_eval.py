"""The Checker test: how many of 50 known-bad drafts the checks catch, and how many good ones they wrongly block.

    uv run python -m scripts.checker_eval           # rules only (no model, free)
    uv run python -m scripts.checker_eval --live    # rules + the meaning check on the verification models

Writes data/eval/checker_report.json, which the AI team page shows.
"""

import asyncio
import json
import sys

from app import checker_eval
from app.config import get_settings
from app.providers import build_router


async def main(live: bool) -> None:
    report = await checker_eval.run(build_router(get_settings()) if live else None)
    checker_eval.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"Caught {report['caught']} of {report['bad_total']} bad drafts "
          f"({', '.join(f'{k}: {v}' for k, v in report['by_layer'].items())}); "
          f"wrongly blocked {report['false_alarms']} of {report['good_total']} good ones.")
    for m in report["missed"]:
        print(f"  missed #{m['id']} {m['category']} ({m['language']}): {m['headline']}")
    if report["no_verdict"]:
        print(f"  no verdict from the model (would be held for a re-check): {report['no_verdict']}")
    for m in report["wrongly_blocked"]:
        print(f"  blocked good #{m['id']}: {m['headline']} -> {m['reason']}")


if __name__ == "__main__":
    asyncio.run(main("--live" in sys.argv))
