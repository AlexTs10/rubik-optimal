#!/usr/bin/env python
"""Measure own-code native Korf symmetry modes on the superflip.

This is a WORSTCASE Path 2 decision tool. It deliberately uses the student's
native Korf/IDA* path only: no H48, no Nissy heuristic bridge, and no external
oracle. Rows may time out or return lower bounds; the script records that
honestly and never upgrades a bounded result to an exact distance claim.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.solvers.optimal_native import solve_korf_native_optimal


def superflip_cube() -> CubeState:
    return CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)


@dataclass(frozen=True)
class ProbeMode:
    mode_id: str
    root_symmetry_prune: bool
    symmetry_transpositions: bool
    full_symmetry_transpositions: bool
    compact_transpositions: bool


MODES = {
    "root48": ProbeMode("root48", True, False, False, False),
    "rot24_tt": ProbeMode("rot24_tt", True, True, False, False),
    "full48_tt": ProbeMode("full48_tt", True, True, True, False),
    "full48_compact_tt": ProbeMode("full48_compact_tt", True, True, True, True),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--split-depth", type=int, default=3)
    parser.add_argument("--tt-entries", type=int, default=1_000_000)
    parser.add_argument("--max-depth", type=int, default=20)
    parser.add_argument("--mode", choices=tuple(MODES), action="append", dest="modes")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_symmetry_superflip_probe_seed_2026.json",
    )
    return parser.parse_args()


def row_for_mode(mode: ProbeMode, args: argparse.Namespace) -> dict[str, object]:
    begin = time.perf_counter()
    result = solve_korf_native_optimal(
        superflip_cube(),
        max_depth=args.max_depth,
        timeout_seconds=args.timeout,
        transposition_entries=args.tt_entries,
        threads=args.threads,
        split_depth=args.split_depth,
        nissy_heuristic=False,
        root_symmetry_prune=mode.root_symmetry_prune,
        symmetry_transpositions=mode.symmetry_transpositions,
        full_symmetry_transpositions=mode.full_symmetry_transpositions,
        compact_transpositions=mode.compact_transpositions,
    )
    return {
        "mode_id": mode.mode_id,
        "root_symmetry_prune": mode.root_symmetry_prune,
        "symmetry_transpositions": mode.symmetry_transpositions,
        "full_symmetry_transpositions": mode.full_symmetry_transpositions,
        "compact_transpositions": mode.compact_transpositions,
        "status": result.status,
        "solution_length": result.solution_length,
        "runtime_seconds": result.runtime_seconds,
        "wrapper_elapsed_seconds": time.perf_counter() - begin,
        "expanded_nodes": result.expanded_nodes,
        "generated_nodes": result.generated_nodes,
        "is_verified": result.is_verified,
        "notes": result.notes,
    }


def main() -> int:
    args = parse_args()
    selected_modes = args.modes or ["root48", "rot24_tt", "full48_tt"]
    rows = [row_for_mode(MODES[mode], args) for mode in selected_modes]
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "target": "superflip",
        "solver": "korf_native_optimal",
        "uses_h48_or_nissy": False,
        "max_depth": args.max_depth,
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "split_depth": args.split_depth,
        "tt_entries": args.tt_entries,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
