#!/usr/bin/env python
"""Independently re-verify the 11 thesis-cited exact rows that rest only on h48h7.

The h48h7 pruning table was shown to contain race-stale nibbles, so every
thesis-cited exact length whose only evidence is an h48h7 search needs an
independent check. Exactly 11 such rows exist:

* ``extra_random_1_25`` .. ``extra_random_10_25`` from
  ``results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json``
  (recorded exact lengths 4x17 and 6x18), and
* ``deterministic_depth_25`` from
  ``results/processed/h48_oracle_certification_seed_2026_thesis.json``
  (recorded exact length 18).

This script re-solves each state with the EXTERNAL Nissy 2.0.8 optimal HTM
backend (``solve_nissy_optimal``), which uses the vendored Nissy 2.0.8 sources
and the public ``pt_nxopt31_HTM``/``pt_corners_HTM`` pruning tables under
``.codex_external/`` -- code and tables fully independent of the h48 stack.
The cube is passed as a direct cubie state (no representative scramble), each
returned solution is replayed on the repository cube model, and the resulting
optimal length is compared against the recorded h48 claim.

The recorded h48 claims are re-read from the source artifacts at run time so
the comparison is script-traceable. The artifact is rewritten after every row,
so an interrupted run still leaves honest per-row status on disk.

Exit codes: 0 = all rows definitive exact AND every length matches the
recorded h48 value; 2 = all rows definitive but at least one length DISAGREES
with the recorded h48 value (critical finding); 1 = at least one row did not
reach a definitive verified-exact outcome (timeout/failure/unavailable
backend).
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

STRESS_ARTIFACT = Path("results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json")
CERTIFICATION_ARTIFACT = Path("results/processed/h48_oracle_certification_seed_2026_thesis.json")
EXTRA_RANDOM_CASE_IDS = tuple(f"extra_random_{index}_25" for index in range(1, 11))
DETERMINISTIC_CASE_ID = "deterministic_depth_25"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument(
        "--timeout",
        type=float,
        default=1500.0,
        help="Per-row wall-clock budget for the external Nissy optimal solve (seconds).",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Optional subset of case_ids to run (default: all 11 h48-only rows).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip rows already recorded as verified exact in the output artifact.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "results"
        / "processed"
        / "h48only_rows_independent_reverify_seed_2026_thesis.json",
    )
    return parser.parse_args()


def load_target_rows() -> list[dict[str, object]]:
    """Collect the 11 h48-only rows with their recorded h48 claims."""

    targets: list[dict[str, object]] = []

    stress = json.loads((ROOT / STRESS_ARTIFACT).read_text(encoding="utf-8"))
    stress_rows = {row["case_id"]: row for row in stress["rows"]}
    for case_id in EXTRA_RANDOM_CASE_IDS:
        row = stress_rows[case_id]
        targets.append(
            {
                "case_id": case_id,
                "source_artifact": str(STRESS_ARTIFACT),
                "state": row["state"],
                "scramble": row["scramble"],
                "recorded_h48_solver": row["solver"],
                "recorded_h48_status": row["status"],
                "recorded_h48_solution_length": row["solution_length"],
            }
        )

    certification = json.loads((ROOT / CERTIFICATION_ARTIFACT).read_text(encoding="utf-8"))
    det = next(row for row in certification["rows"] if row["case_id"] == DETERMINISTIC_CASE_ID)
    targets.append(
        {
            "case_id": DETERMINISTIC_CASE_ID,
            "source_artifact": str(CERTIFICATION_ARTIFACT),
            "state": det["state"],
            "scramble": det.get("scramble"),
            "recorded_h48_solver": det.get("solver") or det.get("notes", "")[:120] or "h48h7",
            "recorded_h48_status": det["status"],
            "recorded_h48_solution_length": det["solution_length"],
        }
    )
    return targets


def summarize(rows: list[dict[str, object]], expected_total: int) -> dict[str, object]:
    completed = [row for row in rows if row.get("nissy_status") is not None]
    definitive = [
        row
        for row in completed
        if row.get("nissy_status") == "exact"
        and row.get("nissy_is_verified")
        and row.get("replay_valid")
    ]
    matches = [row for row in definitive if row.get("match") is True]
    mismatches = [row for row in definitive if row.get("match") is False]
    non_definitive = [row for row in completed if row not in definitive]
    return {
        "rows_expected": expected_total,
        "rows_attempted": len(completed),
        "rows_definitive_exact": len(definitive),
        "rows_match": len(matches),
        "rows_mismatch": len(mismatches),
        "rows_not_definitive": len(non_definitive),
        "mismatch_case_ids": [row["case_id"] for row in mismatches],
        "not_definitive_case_ids": [row["case_id"] for row in non_definitive],
        "all_definitive": len(definitive) == expected_total,
        "all_match": len(definitive) == expected_total and len(mismatches) == 0,
    }


def write_payload(out: Path, payload: dict[str, object]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    targets = load_target_rows()
    if args.cases:
        selected = set(args.cases)
        unknown = selected - {target["case_id"] for target in targets}
        if unknown:
            print(f"unknown case_ids: {sorted(unknown)}", file=sys.stderr)
            return 1
        targets = [target for target in targets if target["case_id"] in selected]

    previous_rows: dict[str, dict[str, object]] = {}
    if args.resume and args.out.exists():
        previous = json.loads(args.out.read_text(encoding="utf-8"))
        previous_rows = {row["case_id"]: row for row in previous.get("rows", [])}

    source_state = capture_source_state(ROOT)
    expected_total = len(targets)
    # Solve recorded-length-17 rows first so a partial run banks the faster rows.
    run_targets = sorted(
        targets,
        key=lambda target: (
            target["recorded_h48_solution_length"] is None,
            target["recorded_h48_solution_length"],
        ),
    )

    rows: list[dict[str, object]] = []
    payload: dict[str, object] = {
        "schema_version": 1,
        "probe_name": "h48only_rows_independent_reverify",
        "profile": args.profile,
        "seed": args.seed,
        "purpose": (
            "Independent re-verification of the only 11 thesis-cited exact lengths whose "
            "sole evidence is the h48h7 pruning table, after that table was shown to "
            "contain race-stale pruning nibbles."
        ),
        "backend": "nissy2_state_optimal_external (external Nissy 2.0.8 + public pt_nxopt31_HTM/pt_corners_HTM tables)",
        "independence": (
            "External Nissy 2.0.8 vendored sources and its own public pruning tables under "
            ".codex_external/nissy_data/tables/; no h48 code or h48 table is touched. Input is "
            "the direct cubie state (no representative scramble); every solution is replayed on "
            "the repository cube model before being reported."
        ),
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "uses_h48_or_nissy": True,
        "recorded_claims_reproduced_from": [str(STRESS_ARTIFACT), str(CERTIFICATION_ARTIFACT)],
        "rows": rows,
        "summary": summarize(rows, expected_total),
        "source_state": source_state["state"],
        "source_state_details": source_state,
        "source_snapshot_reproducible": source_state["is_reproducible_checkout"],
        "source_snapshot_limitation": source_state["limitation"],
        "source_reproduction_plan": source_state["reproduction_plan"],
    }
    write_payload(args.out, payload)

    for target in run_targets:
        case_id = str(target["case_id"])
        previous_row = previous_rows.get(case_id)
        if (
            previous_row is not None
            and previous_row.get("nissy_status") == "exact"
            and previous_row.get("nissy_is_verified")
            and previous_row.get("replay_valid")
        ):
            rows.append(previous_row)
            payload["summary"] = summarize(rows, expected_total)
            write_payload(args.out, payload)
            print(f"{case_id}: reused verified exact row from previous artifact")
            continue

        cube = CubeState.from_facelets(str(target["state"]))
        scramble = target["scramble"]
        scramble_reproduces_state = (
            CubeState.from_sequence(str(scramble)) == cube if scramble else None
        )

        begin = time.perf_counter()
        result = solve_nissy_optimal(
            cube,
            source_sequence=None,
            timeout_seconds=args.timeout,
            threads=args.threads,
        )
        elapsed = time.perf_counter() - begin

        replay_valid = False
        if result.status == "exact" and result.solution_moves is not None:
            replay_valid = cube.apply_sequence(result.solution_moves).is_solved()

        recorded_length = target["recorded_h48_solution_length"]
        match: bool | None = None
        if result.status == "exact" and result.is_verified and replay_valid:
            match = result.solution_length == recorded_length

        row = {
            "case_id": case_id,
            "source_artifact": target["source_artifact"],
            "state": target["state"],
            "scramble": scramble,
            "scramble_reproduces_state": scramble_reproduces_state,
            "recorded_h48_solver": target["recorded_h48_solver"],
            "recorded_h48_status": target["recorded_h48_status"],
            "recorded_h48_solution_length": recorded_length,
            "nissy_solver_name": result.solver_name,
            "nissy_status": result.status,
            "nissy_solution": " ".join(result.solution_moves or []),
            "nissy_solution_length": result.solution_length,
            "nissy_is_verified": result.is_verified,
            "nissy_runtime_seconds": result.runtime_seconds,
            "elapsed_seconds": elapsed,
            "replay_valid": replay_valid,
            "match": match,
            "nissy_notes": result.notes,
        }
        rows.append(row)
        payload["summary"] = summarize(rows, expected_total)
        write_payload(args.out, payload)
        print(
            f"{case_id}: recorded={recorded_length} nissy={result.solution_length} "
            f"status={result.status} replay_valid={replay_valid} match={match} "
            f"elapsed={elapsed:.1f}s"
        )

    summary = summarize(rows, expected_total)
    payload["summary"] = summary
    write_payload(args.out, payload)
    print(json.dumps(summary, indent=2, sort_keys=True))

    if not summary["all_definitive"]:
        return 1
    if not summary["all_match"]:
        print(
            "CRITICAL: at least one independently re-verified optimal length disagrees "
            f"with the recorded h48 value: {summary['mismatch_case_ids']}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
