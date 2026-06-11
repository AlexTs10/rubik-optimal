#!/usr/bin/env python
"""Benchmark H48 lower-bound table-load amortization for batch certification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.solvers.h48_native import (  # noqa: E402
    compute_h48_native_lower_bound,
    compute_h48_native_lower_bound_batch,
)
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402


def _cases() -> list[CubeState]:
    return [
        CubeState.from_sequence("R U F2"),
        CubeState.from_sequence("R U"),
        CubeState.from_sequence("F R U R' U'"),
        CubeState.from_sequence("L2 D B U2"),
    ]


def _row(result) -> dict[str, object]:
    return {
        "solver_name": result.solver_name,
        "status": result.status,
        "lower_bound": result.lower_bound,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "table_bytes": result.table_bytes,
        "notes": result.notes,
    }


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_lower_bound_batch{suffix}.tex" if suffix else "h48_lower_bound_batch.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrr}\n"
        "\\hline\n"
        "Mode & Total seconds & Lower-bound rows \\\\\n"
        "\\hline\n"
        f"Single process per lower bound & {payload['sequential_total_seconds']} & {payload['sequential_lower_bound_count']} \\\\\n"
        f"Batch table loaded once & {payload['batch_wall_seconds']} & {payload['batch_lower_bound_count']} \\\\\n"
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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
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

    cases = _cases()
    sequential_rows = []
    sequential_begin = time.perf_counter()
    for cube in cases:
        sequential_rows.append(
            compute_h48_native_lower_bound(
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
        )
    sequential_total = time.perf_counter() - sequential_begin

    batch_begin = time.perf_counter()
    batch_rows = compute_h48_native_lower_bound_batch(
        cases,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout_seconds=args.timeout,
        threads=args.threads,
        skip_table_check=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    batch_wall = time.perf_counter() - batch_begin

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "case_count": len(cases),
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "sequential_total_seconds": round(sequential_total, 6),
        "sequential_lower_bound_count": sum(1 for row in sequential_rows if row.status == "lower_bound"),
        "batch_wall_seconds": round(batch_wall, 6),
        "batch_lower_bound_count": sum(1 for row in batch_rows if row.status == "lower_bound"),
        "throughput_speedup": round(sequential_total / batch_wall, 3) if batch_wall > 0 else None,
        "sequential_rows": [_row(result) for result in sequential_rows],
        "batch_rows": [_row(result) for result in batch_rows],
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "This benchmark measures the exact-safe H48 lower-bound batch path used by "
            "upper/lower certificate routing. It proves table-load amortization for the "
            "saved corpus only; it is not an all-state practical-runtime proof."
        ),
    }
    payload["passed"] = (
        payload["sequential_lower_bound_count"] == len(cases)
        and payload["batch_lower_bound_count"] == len(cases)
        and (payload["throughput_speedup"] or 0) >= 1.0
        and all("table_loaded_once=true" in row["notes"] for row in payload["batch_rows"])
    )

    output = (
        root
        / "results"
        / "processed"
        / f"h48_lower_bound_batch_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
