#!/usr/bin/env python
"""Certify the h48h7 exact-oracle path on direct 3x3 states.

This script is intentionally separate from the random stress corpus.  It checks
the all-state oracle contract surface: the generated h48h7 table, direct
CubeState input, an ordinary shallow state, and the standard superflip
distance-20 state.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.solvers.h48_native import solve_h48_native_optimal
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_metadata_path, h48_table_path


@dataclass(frozen=True)
class CertificationCase:
    case_id: str
    cube: CubeState
    expected_distance: int
    description: str


def superflip_cube() -> CubeState:
    """Return the standard superflip state: all 12 edges flipped."""

    return CubeState(eo=(1,) * 12)


def certification_cases(seed: int) -> list[CertificationCase]:
    return [
        CertificationCase(
            "solved",
            CubeState.solved(),
            0,
            "solved identity state",
        ),
        CertificationCase(
            "shallow_r_u_f2",
            CubeState.from_sequence("R U F2"),
            3,
            "direct facelet/cubie state for a shallow three-move scramble",
        ),
        CertificationCase(
            "deterministic_depth_25",
            CubeState.from_sequence(deterministic_scramble(25, seed, offset=2001)),
            -1,
            "deterministic depth-25 state; exact distance is discovered by the oracle",
        ),
        CertificationCase(
            "superflip_distance_20",
            superflip_cube(),
            20,
            "standard all-edges-flipped superflip state, a known HTM distance-20 representative",
        ),
    ]


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"h48_oracle_certification{suffix}.tex" if suffix else "h48_oracle_certification.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        expected = row["expected_distance"] if row["expected_distance"] is not None else "--"
        body.append(
            f"{_tex(row['case_id'])} & {_tex(expected)} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Case & Expected & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--runtime-target", type=float, default=60.0)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        artifact_suffix = "" if solver == ORACLE_H48_SOLVER else solver
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    metadata_path = h48_metadata_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for case in certification_cases(args.seed):
        code, message = case.cube.verify_physical()
        if code != 0:
            errors.append(f"{case.case_id}: invalid case cube: {message}")
            continue
        result = solve_h48_native_optimal(
            case.cube,
            source_sequence=None,
            solver=solver,
            profile=args.profile,
            seed=args.seed,
            timeout_seconds=args.timeout,
            threads=args.threads,
            skip_table_check=args.trusted_table,
            preload_table=args.preload_table,
            root=root,
        )
        expected_matches = (
            case.expected_distance < 0
            or (result.status == "exact" and result.solution_length == case.expected_distance)
        )
        row = {
            "case_id": case.case_id,
            "description": case.description,
            "expected_distance": case.expected_distance if case.expected_distance >= 0 else None,
            "state": case.cube.to_facelets(),
            "status": result.status,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": round(result.runtime_seconds, 6),
            "expanded_nodes": result.expanded_nodes,
            "table_size_bytes": result.table_bytes,
            "verified": result.is_verified,
            "expected_distance_matches": expected_matches,
            "notes": result.notes,
        }
        rows.append(row)
        if result.status != "exact" or not result.is_verified:
            errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
        if not expected_matches:
            errors.append(
                f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}"
            )
        if result.runtime_seconds > args.runtime_target:
            errors.append(
                f"{case.case_id}: runtime {result.runtime_seconds:.6f}s exceeds target {args.runtime_target:.6f}s"
            )

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "table_path": str(table_path.relative_to(root)),
        "metadata_path": str(metadata_path.relative_to(root)),
        "metadata": metadata,
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "runtime_target_seconds": args.runtime_target,
        "rows": rows,
        "all_exact": all(row.get("status") == "exact" and row.get("verified") is True for row in rows),
        "all_expected_distances_match": all(row.get("expected_distance_matches") is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "within_runtime_target": all(float(row["runtime_seconds"]) <= args.runtime_target for row in rows),
        "algorithmic_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "metric": "HTM / face-turn metric",
            "external_depth_bound": "God's Number: every valid 3x3 state has an optimal solution of length at most 20",
            "solver_contract": "nissy-core documents H48 as an HTM-optimal solver with no prerequisites; 'optimal' aliases to h48h7 and larger h48hN tables provide stronger H48 pruning",
            "wrapper_contract": "the in-repo wrapper calls nissy_solve with optimal=0 and max_depth=20, then independently verifies the returned sequence",
            "runtime_claim": "runtime target is machine-checked for this certification corpus, including superflip; it is not an exhaustive timing proof over all states",
        },
        "errors": errors,
        "passed": not errors,
    }

    output = root / "results" / "processed" / f"h48_oracle_certification_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, rows, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
