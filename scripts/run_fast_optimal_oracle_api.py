#!/usr/bin/env python
"""Generate evidence for the package-level FastOptimalOracle API."""

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
from rubik_optimal.oracle import FastOptimalOracle, FastOptimalOracleConfig
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path
from scripts.run_h48_oracle_certification import certification_cases


@dataclass(frozen=True)
class ApiCase:
    case_id: str
    input_kind: str
    cube: CubeState
    expected_distance: int | None
    description: str


def api_cases(seed: int, *, include_hard: bool = False) -> list[ApiCase]:
    cases = [
        ApiCase("solved", "cube_state", CubeState.solved(), 0, "solved identity state"),
        ApiCase(
            "sequence_shallow",
            "sequence",
            CubeState.from_sequence("R U F2"),
            3,
            "three-move sequence converted to CubeState",
        ),
        ApiCase(
            "facelets_shallow",
            "facelets",
            CubeState.from_facelets(CubeState.from_sequence("R U F2").to_facelets()),
            3,
            "facelet string parsed back into CubeState",
        ),
        ApiCase(
            "deterministic_depth_10",
            "deterministic_scramble",
            CubeState.from_sequence(deterministic_scramble(10, seed, offset=3001)),
            None,
            "deterministic depth-10 state; exact distance is discovered by the oracle",
        ),
    ]
    if include_hard:
        for case in certification_cases(seed):
            if case.case_id in {"deterministic_depth_25", "superflip_distance_20"}:
                cases.append(
                    ApiCase(
                        case.case_id,
                        "hard_certification",
                        case.cube,
                        case.expected_distance if case.expected_distance >= 0 else None,
                        case.description,
                    )
                )
    return cases


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((percentile / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"fast_optimal_oracle_api{suffix}.tex" if suffix else "fast_optimal_oracle_api.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{llrrr}\n",
        "\\hline\n",
        "Case & Input & Expected & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in payload["rows"]:
        expected = row["expected_distance"] if row["expected_distance"] is not None else "--"
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['input_kind'])} & {_tex(expected)} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--runtime-target", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true", default=True)
    parser.add_argument("--checked-table", action="store_false", dest="trusted_table")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--include-hard", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        parts = [solver]
        if args.trusted_table:
            parts.append("trusted")
        if args.include_hard:
            parts.append("hard")
        artifact_suffix = "_".join(parts)
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""

    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    config = FastOptimalOracleConfig(
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=args.threads,
        timeout_seconds=args.timeout,
        max_depth=20,
        trusted_table=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    oracle = FastOptimalOracle(config)
    try:
        for case in api_cases(args.seed, include_hard=args.include_hard):
            ok, message = case.cube.verify_physical()
            if ok != 0:
                errors.append(f"{case.case_id}: invalid case cube: {message}")
                continue
            result = oracle.solve(case.cube)
            expected_matches = (
                case.expected_distance is None
                or (result.status == "exact" and result.solution_length == case.expected_distance)
            )
            row = {
                "case_id": case.case_id,
                "input_kind": case.input_kind,
                "description": case.description,
                "expected_distance": case.expected_distance,
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
                    f"{case.case_id}: runtime {result.runtime_seconds:.6f}s exceeds target "
                    f"{args.runtime_target:.6f}s"
                )
    finally:
        oracle.close()

    runtimes = [float(row["runtime_seconds"]) for row in rows]
    hard_reference_path = (
        root
        / "results"
        / "processed"
        / f"h48_resident_certification_seed_{args.seed}_{args.profile}_{solver}_trusted.json"
    )
    hard_reference = json.loads(hard_reference_path.read_text(encoding="utf-8")) if hard_reference_path.exists() else None
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "api_class": "FastOptimalOracle",
        "solver": solver,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "runtime_target_seconds": args.runtime_target,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "include_hard": args.include_hard,
        "rows": rows,
        "row_count": len(rows),
        "all_exact": all(row.get("status") == "exact" and row.get("verified") is True for row in rows),
        "all_verified": all(row.get("verified") is True for row in rows),
        "all_expected_distances_match": all(row.get("expected_distance_matches") is True for row in rows),
        "all_under_runtime_target": all(float(row["runtime_seconds"]) <= args.runtime_target for row in rows),
        "max_runtime_seconds": round(max(runtimes, default=0.0), 6),
        "p95_runtime_seconds": round(_percentile(runtimes, 95.0), 6),
        "hard_certification_reference": {
            "path": str(hard_reference_path.relative_to(root)),
            "present": hard_reference is not None,
            "passed": hard_reference.get("passed") if hard_reference else None,
            "all_exact": hard_reference.get("all_exact") if hard_reference else None,
            "all_hard_cases_exact": hard_reference.get("all_hard_cases_exact") if hard_reference else None,
            "max_runtime_seconds": hard_reference.get("max_runtime_seconds") if hard_reference else None,
        },
        "all_state_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by validate_cube",
            "metric": "HTM / face-turn metric",
            "backend": "resident native nissy-core H48 h48h7",
            "depth_bound": "max_depth=20, matching the cited God's Number depth bound",
            "verification": "every returned sequence is replayed by the independent verifier",
            "runtime_boundary": "this artifact times an API corpus and references hard certification; it is not exhaustive over every state",
        },
        "fast_optimal_oracle_implemented_for_every_valid_3x3_state": True,
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root / "results" / "processed" / f"fast_optimal_oracle_api_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
