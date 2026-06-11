#!/usr/bin/env python
"""Certify the resident H48 oracle on hard direct 3x3 states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.solvers.h48_native import H48NativeOracleSession
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path
from scripts.run_h48_oracle_certification import certification_cases


def hard_case_ids() -> set[str]:
    return {"deterministic_depth_25", "superflip_distance_20"}


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _default_artifact_suffix(solver: str, *, trusted_table: bool, preload_table: bool) -> str:
    parts = [solver]
    if trusted_table:
        parts.append("trusted")
    if preload_table:
        parts.append("preload")
    return "_".join(parts)


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_resident_certification{suffix}.tex" if suffix else "h48_resident_certification.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrrrr}\n",
        "\\hline\n",
        "Case & Expected & Status & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in payload["rows"]:
        expected = row["expected_distance"] if row["expected_distance"] is not None else "--"
        body.append(
            f"{_tex(row['case_id'])} & {_tex(expected)} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\\n"
        )
    body.extend(
        [
            "\\hline\n",
            "\\end{tabular}\n",
            "}\n",
        ]
    )
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--runtime-target", type=float, default=240.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        artifact_suffix = _default_artifact_suffix(
            solver,
            trusted_table=args.trusted_table,
            preload_table=args.preload_table,
        )
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    cases = certification_cases(args.seed)
    resident_begin = time.perf_counter()
    with H48NativeOracleSession(
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        threads=args.threads,
        max_depth=20,
        skip_table_check=args.trusted_table,
        preload_table=args.preload_table,
        search_timeout_seconds=args.timeout,
        root=root,
    ) as session:
        for case in cases:
            code, message = case.cube.verify_physical()
            if code != 0:
                errors.append(f"{case.case_id}: invalid case cube: {message}")
                continue
            result = session.solve(case.cube, timeout_seconds=args.timeout)
            expected_matches = (
                case.expected_distance < 0
                or (result.status == "exact" and result.solution_length == case.expected_distance)
            )
            row = {
                "case_id": case.case_id,
                "description": case.description,
                "hard_case": case.case_id in hard_case_ids(),
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
                    f"{case.case_id}: runtime {result.runtime_seconds:.6f}s exceeds target "
                    f"{args.runtime_target:.6f}s"
                )
    resident_wall_seconds = time.perf_counter() - resident_begin

    hard_rows = [row for row in rows if row.get("hard_case") is True]
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "timeout_seconds": args.timeout,
        "runtime_target_seconds": args.runtime_target,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "resident_wall_seconds": round(resident_wall_seconds, 6),
        "rows": rows,
        "hard_case_ids": sorted(hard_case_ids()),
        "all_exact": all(row.get("status") == "exact" and row.get("verified") is True for row in rows),
        "all_hard_cases_exact": bool(hard_rows)
        and all(row.get("status") == "exact" and row.get("verified") is True for row in hard_rows),
        "all_expected_distances_match": all(row.get("expected_distance_matches") is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "within_runtime_target": all(float(row["runtime_seconds"]) <= args.runtime_target for row in rows),
        "algorithmic_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "metric": "HTM / face-turn metric",
            "resident_interface": "one native H48 process keeps the generated table mapped across all rows",
            "hard_rows": "deterministic depth-25 state plus standard superflip distance-20 state",
            "claim_boundary": "exactness is certified for recorded rows; this is not an exhaustive timing proof over all states",
        },
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"h48_resident_certification_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
