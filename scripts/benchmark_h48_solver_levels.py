#!/usr/bin/env python
"""Compare generated H48 oracle-grade table levels on direct 3x3 states."""

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
from rubik_optimal.tables.h48 import canonical_h48_solver, h48_metadata_path, h48_table_path


@dataclass(frozen=True)
class CompareCase:
    case_id: str
    cube: CubeState
    expected_distance: int | None


def _cases(seed: int) -> list[CompareCase]:
    return [
        CompareCase("shallow_r_u_f2", CubeState.from_sequence("R U F2"), 3),
        CompareCase("deterministic_depth_25", CubeState.from_sequence(deterministic_scramble(25, seed, offset=2001)), None),
        CompareCase("superflip_distance_20", CubeState(eo=(1,) * 12), 20),
    ]


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, payload: dict[str, object]) -> Path:
    table_path = root / "thesis" / "tables" / "h48_solver_level_comparison.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in payload["summary_rows"]:
        body.append(
            f"{_tex(row['solver'])} & {_tex(row['table_size_bytes'])} & "
            f"{_tex(row['exact_count'])} & {_tex(row['max_runtime_seconds'])} & "
            f"{_tex(row['superflip_runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Solver & Bytes & Exact rows & Max seconds & Superflip seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solvers", nargs="+", default=["h48h7", "h48h8"])
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--runtime-target", type=float, default=120.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solvers = [canonical_h48_solver(solver) for solver in args.solvers]
    cases = _cases(args.seed)
    rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    errors: list[str] = []

    for solver in solvers:
        table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
        metadata_path = h48_metadata_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
        if not table_path.exists():
            errors.append(f"missing H48 table for {solver}: {table_path}")
            continue
        table_size = table_path.stat().st_size
        for case in cases:
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
            expected_matches = case.expected_distance is None or result.solution_length == case.expected_distance
            row = {
                "solver": solver,
                "case_id": case.case_id,
                "expected_distance": case.expected_distance,
                "status": result.status,
                "solution": " ".join(result.solution_moves),
                "solution_length": result.solution_length,
                "runtime_seconds": round(result.runtime_seconds, 6),
                "expanded_nodes": result.expanded_nodes,
                "table_size_bytes": result.table_bytes or table_size,
                "verified": result.is_verified,
                "expected_distance_matches": expected_matches,
                "metadata_path": str(metadata_path.relative_to(root)),
                "notes": result.notes,
            }
            rows.append(row)
            if result.status != "exact" or result.is_verified is not True:
                errors.append(f"{solver}/{case.case_id}: expected exact verified row, got {result.status}")
            if not expected_matches:
                errors.append(f"{solver}/{case.case_id}: expected {case.expected_distance}, got {result.solution_length}")
            if result.runtime_seconds > args.runtime_target:
                errors.append(
                    f"{solver}/{case.case_id}: runtime {result.runtime_seconds:.6f}s exceeds {args.runtime_target:.6f}s"
                )
        solver_rows = [row for row in rows if row["solver"] == solver]
        summary_rows.append(
            {
                "solver": solver,
                "table_size_bytes": table_size,
                "exact_count": sum(1 for row in solver_rows if row["status"] == "exact" and row["verified"] is True),
                "case_count": len(solver_rows),
                "max_runtime_seconds": round(max((float(row["runtime_seconds"]) for row in solver_rows), default=0.0), 6),
                "superflip_runtime_seconds": next(
                    (
                        row["runtime_seconds"]
                        for row in solver_rows
                        if row["case_id"] == "superflip_distance_20"
                    ),
                    None,
                ),
            }
        )

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solvers": solvers,
        "timeout_seconds": args.timeout,
        "runtime_target_seconds": args.runtime_target,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "rows": rows,
        "summary_rows": summary_rows,
        "all_exact": bool(rows) and all(row["status"] == "exact" and row["verified"] is True for row in rows),
        "all_expected_distances_match": bool(rows) and all(row["expected_distance_matches"] is True for row in rows),
        "within_runtime_target": bool(rows) and all(float(row["runtime_seconds"]) <= args.runtime_target for row in rows),
        "errors": errors,
        "passed": not errors and bool(rows),
    }
    output = root / "results" / "processed" / f"h48_solver_level_comparison_seed_{args.seed}_{args.profile}.json"
    write_json(output, payload)
    table = _write_table(root, payload)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
