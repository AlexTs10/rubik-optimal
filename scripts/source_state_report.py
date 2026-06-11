#!/usr/bin/env python
"""Write a lightweight report for the current source snapshot state."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.source_state import capture_source_state


def build_report(root: Path) -> dict[str, object]:
    source_state = capture_source_state(root)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "current_source_state": source_state,
        "final_submission_source_state_required": {
            "requires_commit_or_archive": True,
            "requires_clean_checkout_metadata": True,
            "current_checkout_is_reproducible": source_state["is_reproducible_checkout"],
            "current_limitation": source_state["limitation"],
        },
        "safe_regeneration_plan": [
            "Review git status --short and decide the exact files that form the thesis baseline.",
            "Create an intentional commit, or create and record an approved immutable source archive if a commit is not allowed.",
            "From that baseline, rerun the generation commands whose result metadata currently records no_commit+dirty.",
            "Run python scripts/source_state_report.py and python scripts/thesis_audit.py.",
            "Do not set or claim final_submission_ready=true while generated metadata still records no_commit+dirty or any dirty source snapshot.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/processed/source_state_report.json"),
        help="Output path relative to --root unless absolute.",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    report = build_report(args.root)
    write_json(output, report)
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
