#!/usr/bin/env python
"""Persist the FlipUDSlice sym-table vs raw phase-1 BFS verification as an artifact.

The thesis cites a byte-for-byte comparison of the 16-symmetry phase-1 pruning
table against the raw CO x EO x UD-slice BFS table on all known (<=9) entries
(959,761,462 entries, zero mismatches).  The native ``verify-sym-phase1`` mode
prints that payload to stdout only; this wrapper runs the gate and saves the
JSON to ``results/processed/`` so the cited numbers come from a saved result
file, as required by the repository's integrity rules.

The check is fully deterministic; the ``--seed`` flag only keeps the artifact
naming consistent with sibling thesis artifacts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.source_state import capture_source_state

from scripts.probe_native_kociemba_phase2_superflip import compile_native


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--sym-phase1-max-depth", type=int, default=12)
    parser.add_argument(
        "--sym-tables",
        type=Path,
        default=ROOT / "data" / "generated" / "phase1_sym_tables.bin",
        help="Path to the phase-1 symmetry reduction tables (generate_phase1_sym_tables.py).",
    )
    parser.add_argument(
        "--sym-phase1-cache",
        type=Path,
        default=ROOT / "data" / "generated" / "kociemba_phase1_sym_depth12.bin",
        help="Cache path for the symmetry-reduced phase-1 pruning table.",
    )
    parser.add_argument(
        "--raw-phase1-table",
        type=Path,
        default=ROOT / "data" / "generated" / "kociemba_phase1_full_depth9.bin",
        help="Raw CO x EO x UD-slice phase-1 BFS table to compare against (depth-9 build).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_sym_phase1_verify_seed_2026_thesis.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = [path for path in (args.sym_tables, args.sym_phase1_cache, args.raw_phase1_table) if not path.exists()]
    if missing:
        for path in missing:
            print(f"required input table missing: {path}", file=sys.stderr)
        return 2

    binary = compile_native()
    source_state = capture_source_state(ROOT)
    command = [
        str(binary),
        "--mode",
        "verify-sym-phase1",
        "--sym-phase1-max-depth",
        str(args.sym_phase1_max_depth),
        "--sym-tables",
        str(args.sym_tables),
        "--sym-phase1-cache",
        str(args.sym_phase1_cache),
        "--raw-phase1-table",
        str(args.raw_phase1_table),
    ]
    begin = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "schema_version": 1,
            "solver_name": "kociemba_sym_phase1_verify",
            "mode": "verify-sym-phase1",
            "status": "failed",
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    payload.update(
        {
            "profile": args.profile,
            "seed": args.seed,
            "deterministic": True,
            "return_code": completed.returncode,
            "wrapper_elapsed_seconds": elapsed,
            "command": command,
            "parameters": {
                "sym_phase1_max_depth": args.sym_phase1_max_depth,
                "sym_tables": str(args.sym_tables.relative_to(ROOT) if args.sym_tables.is_relative_to(ROOT) else args.sym_tables),
                "sym_phase1_cache": str(
                    args.sym_phase1_cache.relative_to(ROOT) if args.sym_phase1_cache.is_relative_to(ROOT) else args.sym_phase1_cache
                ),
                "raw_phase1_table": str(
                    args.raw_phase1_table.relative_to(ROOT) if args.raw_phase1_table.is_relative_to(ROOT) else args.raw_phase1_table
                ),
            },
            "verification_policy": (
                "matches_raw_on_all_known=true only when the raw phase-1 BFS table loaded and every known "
                "(non-0xff) raw entry equals the symmetry-reduced table value at the same coordinate; "
                "compared_entries counts exactly those known raw entries"
            ),
            "source_state": source_state["state"],
            "source_state_details": source_state,
            "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
            "source_snapshot_limitation": source_state["limitation"],
            "source_reproduction_plan": source_state["reproduction_plan"],
            "stderr": completed.stderr,
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if completed.returncode != 0:
        return completed.returncode
    return 0 if payload.get("matches_raw_on_all_known") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
