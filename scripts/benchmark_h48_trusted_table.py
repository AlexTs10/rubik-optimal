#!/usr/bin/env python
"""Benchmark per-call H48 table verification against trusted table loading."""

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
from rubik_optimal.solvers.h48_native import solve_h48_native_optimal
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_trusted_table_speedup{suffix}.tex" if suffix else "h48_trusted_table_speedup.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Mode & Total seconds & Exact rows & Speedup \\\\\n"
        "\\hline\n"
        f"Verified each call & {payload['checked_total_seconds']} & {payload['checked_exact_count']} & -- \\\\\n"
        f"Trusted generated table & {payload['trusted_total_seconds']} & {payload['trusted_exact_count']} & {payload['trusted_speedup']} \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _run_mode(
    *,
    cube: CubeState,
    solver: str,
    profile: str,
    seed: int,
    timeout: float,
    threads: int,
    repetitions: int,
    trusted: bool,
    root: Path,
) -> tuple[float, list[dict[str, object]], list[float]]:
    rows = []
    call_walls: list[float] = []
    begin = time.perf_counter()
    for _ in range(repetitions):
        call_begin = time.perf_counter()
        result = solve_h48_native_optimal(
            cube,
            solver=solver,
            profile=profile,
            seed=seed,
            timeout_seconds=timeout,
            threads=threads,
            skip_table_check=trusted,
            root=root,
        )
        call_walls.append(time.perf_counter() - call_begin)
        rows.append(result.to_dict())
    return time.perf_counter() - begin, rows, call_walls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--skip-tex", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    if args.repetitions <= 0:
        raise SystemExit("--repetitions must be positive")

    root = args.root
    solver = canonical_h48_solver(args.solver)
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""

    cube = CubeState.from_sequence("R U F2")
    # Warm-up: one untimed checked solve scans the full mmapped table and performs
    # the same lookups as both arms, so neither timed arm pays the one-time cold
    # page-in of the table inside its measured window.
    warmup_begin = time.perf_counter()
    warmup_result = solve_h48_native_optimal(
        cube,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout_seconds=args.timeout,
        threads=args.threads,
        skip_table_check=False,
        root=root,
    )
    warmup_wall = time.perf_counter() - warmup_begin

    checked_total, checked_rows, checked_walls = _run_mode(
        cube=cube,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout=args.timeout,
        threads=args.threads,
        repetitions=args.repetitions,
        trusted=False,
        root=root,
    )
    trusted_total, trusted_rows, trusted_walls = _run_mode(
        cube=cube,
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        timeout=args.timeout,
        threads=args.threads,
        repetitions=args.repetitions,
        trusted=True,
        root=root,
    )

    checked_exact = sum(1 for row in checked_rows if row["status"] == "exact" and row["is_verified"])
    trusted_exact = sum(1 for row in trusted_rows if row["status"] == "exact" and row["is_verified"])
    checked_steady = sum(checked_walls[1:]) if len(checked_walls) > 1 else None
    trusted_steady = sum(trusted_walls[1:]) if len(trusted_walls) > 1 else None
    steady_speedup = (
        round(checked_steady / trusted_steady, 3)
        if checked_steady is not None and trusted_steady is not None and trusted_steady > 0
        else None
    )
    payload = {
        "schema_version": 2,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "case": "R U F2 repeated direct CubeState",
        "repetitions": args.repetitions,
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "checked_total_seconds": round(checked_total, 6),
        "trusted_total_seconds": round(trusted_total, 6),
        "checked_exact_count": checked_exact,
        "trusted_exact_count": trusted_exact,
        "trusted_speedup": round(checked_total / trusted_total, 3) if trusted_total > 0 else None,
        "arm_order": ["checked", "trusted"],
        "warmup": {
            "performed": True,
            "mode": "checked",
            "wall_seconds": round(warmup_wall, 6),
            "status": warmup_result.status,
            "is_verified": warmup_result.is_verified,
        },
        "checked_call_wall_seconds": [round(wall, 6) for wall in checked_walls],
        "trusted_call_wall_seconds": [round(wall, 6) for wall in trusted_walls],
        "checked_steady_state_seconds": round(checked_steady, 6) if checked_steady is not None else None,
        "trusted_steady_state_seconds": round(trusted_steady, 6) if trusted_steady is not None else None,
        "trusted_speedup_steady_state": steady_speedup,
        "cache_accounting": (
            "The H48 table is mmapped, so the OS page cache is shared state across arms and "
            "their per-call native processes. A warm-up checked solve (full table scan plus the "
            "same lookups as both arms) runs before either timed arm, so neither arm pays the "
            "one-time cold page-in of the table inside its measured window. Arm execution order "
            "is fixed and recorded in arm_order. trusted_speedup compares full arm totals; "
            "trusted_speedup_steady_state excludes each arm's first timed call to remove any "
            "residual first-call effects."
        ),
        "checked_rows": checked_rows,
        "trusted_rows": trusted_rows,
    }
    payload["passed"] = (
        checked_exact == args.repetitions
        and trusted_exact == args.repetitions
        and (payload["trusted_speedup"] or 0) >= 2.0
    )

    output = root / "results" / "processed" / f"h48_trusted_table_speedup_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    write_json(output, payload)
    table = None if args.skip_tex else _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table) if table else None, "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
