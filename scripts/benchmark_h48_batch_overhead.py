#!/usr/bin/env python
"""Benchmark H48 table-load amortization for repeated oracle calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.solvers.h48_native import solve_h48_native_batch, solve_h48_native_optimal
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path


def _extract_batch_wall(notes: str) -> float | None:
    marker = "batch_wall_seconds="
    if marker not in notes:
        return None
    tail = notes.split(marker, 1)[1]
    value = tail.split(";", 1)[0]
    try:
        return float(value)
    except ValueError:
        return None


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_batch_overhead{suffix}.tex" if suffix else "h48_batch_overhead.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrr}\n"
        "\\hline\n"
        "Mode & Total seconds & Exact rows \\\\\n"
        "\\hline\n"
        f"Single process per solve & {payload['sequential_total_seconds']} & {payload['sequential_exact_count']} \\\\\n"
        f"Batch table loaded once & {payload['batch_wall_seconds']} & {payload['batch_exact_count']} \\\\\n"
        f"Throughput speedup & {payload['throughput_speedup']} & -- \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--skip-tex", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    if args.repetitions <= 0:
        raise SystemExit("--repetitions must be positive")

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        if solver == ORACLE_H48_SOLVER and not args.trusted_table:
            artifact_suffix = ""
        else:
            parts = []
            if solver != ORACLE_H48_SOLVER:
                parts.append(solver)
            if args.trusted_table:
                parts.append("trusted")
            if args.preload_table:
                parts.append("preload")
            artifact_suffix = "_".join(parts)
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    cube = CubeState.from_sequence("R U F2")
    cubes = [cube for _ in range(args.repetitions)]

    # Warm-up: one untimed solve with the same table mode as both arms, so neither
    # timed arm pays the one-time cold page-in of the mmapped table inside its
    # measured window.
    warmup_begin = time.perf_counter()
    warmup_result = solve_h48_native_optimal(
        cube,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout_seconds=args.timeout,
        threads=args.threads,
        skip_table_check=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    warmup_wall = time.perf_counter() - warmup_begin

    sequential_rows = []
    sequential_walls: list[float] = []
    sequential_begin = time.perf_counter()
    for _ in range(args.repetitions):
        call_begin = time.perf_counter()
        result = solve_h48_native_optimal(
            cube,
            solver=solver,
            profile=args.profile,
            seed=args.seed,
            timeout_seconds=args.timeout,
            threads=args.threads,
            skip_table_check=args.trusted_table,
            preload_table=args.preload_table,
            root=root,
        )
        sequential_walls.append(time.perf_counter() - call_begin)
        sequential_rows.append(result.to_dict())
    sequential_total = time.perf_counter() - sequential_begin

    batch_begin = time.perf_counter()
    batch_results = solve_h48_native_batch(
        cubes,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout_seconds=args.timeout,
        threads=args.threads,
        skip_table_check=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    fallback_batch_wall = time.perf_counter() - batch_begin
    batch_wall = next(
        (wall for wall in (_extract_batch_wall(result.notes) for result in batch_results) if wall is not None),
        fallback_batch_wall,
    )

    sequential_steady = sum(sequential_walls[1:]) if len(sequential_walls) > 1 else None
    steady_speedup = None
    if sequential_steady is not None and batch_wall > 0 and args.repetitions > 1:
        steady_speedup = round(
            (sequential_steady / (args.repetitions - 1)) / (batch_wall / args.repetitions), 3
        )

    payload = {
        "schema_version": 2,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "case": "R U F2 repeated direct CubeState",
        "repetitions": args.repetitions,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "sequential_total_seconds": round(sequential_total, 6),
        "sequential_sum_reported_seconds": round(
            sum(float(row["runtime_seconds"]) for row in sequential_rows), 6
        ),
        "sequential_max_reported_seconds": round(
            max(float(row["runtime_seconds"]) for row in sequential_rows), 6
        ),
        "sequential_exact_count": sum(1 for row in sequential_rows if row["status"] == "exact" and row["is_verified"]),
        "batch_wall_seconds": round(batch_wall, 6),
        "batch_sum_backend_seconds": round(sum(result.runtime_seconds for result in batch_results), 6),
        "batch_max_backend_seconds": round(max(result.runtime_seconds for result in batch_results), 6),
        "batch_exact_count": sum(1 for result in batch_results if result.status == "exact" and result.is_verified),
        "throughput_speedup": round(sequential_total / batch_wall, 3) if batch_wall > 0 else None,
        "arm_order": ["sequential", "batch"],
        "warmup": {
            "performed": True,
            "mode": "single_process_solve",
            "trusted_table": args.trusted_table,
            "wall_seconds": round(warmup_wall, 6),
            "status": warmup_result.status,
            "is_verified": warmup_result.is_verified,
        },
        "sequential_call_wall_seconds": [round(wall, 6) for wall in sequential_walls],
        "sequential_steady_state_seconds": round(sequential_steady, 6) if sequential_steady is not None else None,
        "throughput_speedup_steady_state": steady_speedup,
        "cache_accounting": (
            "The H48 table is mmapped, so the OS page cache is shared state across arms and "
            "their native processes. A warm-up solve with the same table mode runs before "
            "either timed arm, so neither arm pays the one-time cold page-in of the table "
            "inside its measured window. Arm execution order is fixed and recorded in "
            "arm_order. throughput_speedup compares the full sequential-arm wall against the "
            "batch wall; throughput_speedup_steady_state compares mean per-state cost with the "
            "sequential arm's first timed call excluded, computed as "
            "(sequential_steady_state_seconds / (repetitions - 1)) / "
            "(batch_wall_seconds / repetitions). The batch arm is a single warm invocation, so "
            "no first-call exclusion applies to it."
        ),
        "sequential_rows": sequential_rows,
        "batch_rows": [result.to_dict() for result in batch_results],
    }
    payload["passed"] = (
        payload["sequential_exact_count"] == args.repetitions
        and payload["batch_exact_count"] == args.repetitions
        and (payload["throughput_speedup"] or 0) >= 1.0
    )

    output = root / "results" / "processed" / f"h48_batch_overhead_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = None if args.skip_tex else _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table) if table else None, "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
