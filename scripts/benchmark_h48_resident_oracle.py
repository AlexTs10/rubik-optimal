#!/usr/bin/env python
"""Benchmark a resident H48 oracle process against per-call processes."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.solvers.h48_native import H48NativeOracleSession, solve_h48_native_optimal
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"h48_resident_oracle{suffix}.tex" if suffix else "h48_resident_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrr}\n"
        "\\hline\n"
        "Mode & Total seconds & Exact rows \\\\\n"
        "\\hline\n"
        f"Separate native process & {_tex(payload['separate_total_seconds'])} & {_tex(payload['separate_exact_count'])} \\\\\n"
        f"Resident native process & {_tex(payload['resident_total_seconds'])} & {_tex(payload['resident_exact_count'])} \\\\\n"
        f"Resident speedup & {_tex(payload['resident_speedup'])} & -- \\\\\n"
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
    parser.add_argument("--repetitions", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--scramble", default="R U F2")
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

    cube = CubeState.from_sequence(args.scramble)
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

    separate_rows = []
    separate_walls: list[float] = []
    separate_begin = time.perf_counter()
    for cube_to_solve in cubes:
        call_begin = time.perf_counter()
        result = solve_h48_native_optimal(
            cube_to_solve,
            solver=solver,
            profile=args.profile,
            seed=args.seed,
            timeout_seconds=args.timeout,
            threads=args.threads,
            skip_table_check=args.trusted_table,
            preload_table=args.preload_table,
            root=root,
        )
        separate_walls.append(time.perf_counter() - call_begin)
        separate_rows.append(result.to_dict())
    separate_total = time.perf_counter() - separate_begin

    resident_rows = []
    resident_walls: list[float] = []
    resident_begin = time.perf_counter()
    with H48NativeOracleSession(
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        threads=args.threads,
        skip_table_check=args.trusted_table,
        preload_table=args.preload_table,
        search_timeout_seconds=args.timeout,
        root=root,
    ) as session:
        for cube_to_solve in cubes:
            call_begin = time.perf_counter()
            row = session.solve(cube_to_solve, timeout_seconds=args.timeout).to_dict()
            resident_walls.append(time.perf_counter() - call_begin)
            resident_rows.append(row)
    resident_total = time.perf_counter() - resident_begin

    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        parts = [solver]
        if args.trusted_table:
            parts.append("trusted")
        if args.preload_table:
            parts.append("preload")
        artifact_suffix = "_".join(parts)
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""

    separate_steady = sum(separate_walls[1:]) if len(separate_walls) > 1 else None
    resident_steady = sum(resident_walls[1:]) if len(resident_walls) > 1 else None
    steady_speedup = (
        round(separate_steady / resident_steady, 3)
        if separate_steady is not None and resident_steady is not None and resident_steady > 0
        else None
    )

    payload = {
        "schema_version": 2,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "case": args.scramble,
        "repetitions": args.repetitions,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "timeout_seconds": args.timeout,
        "table_path": str(table_path.relative_to(root)),
        "table_size_bytes": table_path.stat().st_size,
        "separate_total_seconds": round(separate_total, 6),
        "separate_exact_count": sum(
            1 for row in separate_rows if row["status"] == "exact" and row["is_verified"]
        ),
        "resident_total_seconds": round(resident_total, 6),
        "resident_exact_count": sum(
            1 for row in resident_rows if row["status"] == "exact" and row["is_verified"]
        ),
        "resident_speedup": round(separate_total / resident_total, 3) if resident_total > 0 else None,
        "arm_order": ["separate", "resident"],
        "warmup": {
            "performed": True,
            "mode": "single_process_solve",
            "trusted_table": args.trusted_table,
            "wall_seconds": round(warmup_wall, 6),
            "status": warmup_result.status,
            "is_verified": warmup_result.is_verified,
        },
        "separate_call_wall_seconds": [round(wall, 6) for wall in separate_walls],
        "resident_call_wall_seconds": [round(wall, 6) for wall in resident_walls],
        "resident_session_startup_seconds": round(resident_total - sum(resident_walls), 6),
        "separate_steady_state_seconds": round(separate_steady, 6) if separate_steady is not None else None,
        "resident_steady_state_seconds": round(resident_steady, 6) if resident_steady is not None else None,
        "resident_speedup_steady_state": steady_speedup,
        "cache_accounting": (
            "The H48 table is mmapped, so the OS page cache is shared state across arms and "
            "their native processes. A warm-up solve with the same table mode runs before "
            "either timed arm, so neither arm pays the one-time cold page-in of the table "
            "inside its measured window. Arm execution order is fixed and recorded in "
            "arm_order. resident_speedup compares full arm totals (the resident total "
            "includes session startup, reported separately as "
            "resident_session_startup_seconds); resident_speedup_steady_state excludes each "
            "arm's first timed call and the resident session startup."
        ),
        "separate_rows": separate_rows,
        "resident_rows": resident_rows,
    }
    payload["passed"] = (
        payload["separate_exact_count"] == args.repetitions
        and payload["resident_exact_count"] == args.repetitions
        and (payload["resident_speedup"] or 0) >= 1.0
    )

    output = root / "results" / "processed" / f"h48_resident_oracle_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = None if args.skip_tex else _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table) if table else None, "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
