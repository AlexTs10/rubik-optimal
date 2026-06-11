#!/usr/bin/env python
"""Persist a bounded external Nissy optimal superflip probe as an artifact.

The thesis cites that the external Nissy full optimal HTM step, run as a
separate bounded probe on the superflip, timed out at 120s with 2 threads and
at 240s with 8 threads.  Those probes were originally run as direct CLI
commands (docs/progress.md, 2026-05-27) and left no saved result file.  This
wrapper reruns one bounded probe through ``solve_nissy_optimal`` and writes the
outcome (status, threads, timeout_seconds, elapsed) to ``results/processed/``
so the cited behaviour comes from a saved result file.

A ``status=timeout`` row documents only that Nissy's optimal step did not
finish within the budget on this machine; it proves nothing about the
superflip distance.  Exit code 0 requires a definitive probe outcome
(``timeout`` or verified ``exact``); a missing binary/table or a failure exits
nonzero so an unusable environment cannot masquerade as evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.source_state import capture_source_state
from rubik_optimal.solvers.nissy_external import solve_nissy_optimal

from scripts.probe_native_kociemba_phase2_superflip import superflip_cube

# Standard 20-move superflip generator; verified against the repository move
# model by the source_sequence check inside the Nissy bridge (the bridge falls
# back to a derived scramble if this did not reproduce the target state).
SUPERFLIP_SCRAMBLE = "U R2 F B R B2 R U2 L B2 R U' D' R2 F R' L B2 U2 F2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output artifact path; defaults to results/processed/"
            "nissy_optimal_superflip_probe_seed_{seed}_{profile}_threads{threads}_timeout{timeout}s.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = args.out
    if out is None:
        out = (
            ROOT
            / "results"
            / "processed"
            / (
                f"nissy_optimal_superflip_probe_seed_{args.seed}_{args.profile}"
                f"_threads{args.threads}_timeout{int(args.timeout)}s.json"
            )
        )
    cube = superflip_cube()
    assert cube == CubeState.from_sequence(SUPERFLIP_SCRAMBLE)
    source_state = capture_source_state(ROOT)

    begin = time.perf_counter()
    result = solve_nissy_optimal(
        cube,
        source_sequence=SUPERFLIP_SCRAMBLE,
        timeout_seconds=args.timeout,
        threads=args.threads,
    )
    elapsed = time.perf_counter() - begin

    payload = {
        "schema_version": 1,
        "probe_name": "nissy_optimal_superflip_bounded_probe",
        "profile": args.profile,
        "seed": args.seed,
        "target": "superflip",
        "scramble": SUPERFLIP_SCRAMBLE,
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "elapsed": elapsed,
        "status": result.status,
        "uses_h48_or_nissy": True,
        "result": result.to_dict(),
        "probe_policy": (
            "status=timeout records only that the external Nissy `solve optimal` step did not finish "
            "within timeout_seconds at this thread count on this machine; it is not a distance bound. "
            "Any exact row is independently replay-verified before being reported."
        ),
        "source_state": source_state["state"],
        "source_state_details": source_state,
        "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
        "source_snapshot_limitation": source_state["limitation"],
        "source_reproduction_plan": source_state["reproduction_plan"],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if result.status == "timeout":
        return 0
    if result.status == "exact" and result.is_verified:
        return 0
    print(f"probe did not produce a definitive outcome: status={result.status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
