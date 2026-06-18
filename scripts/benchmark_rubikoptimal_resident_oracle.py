#!/usr/bin/env python
"""Benchmark repeated RubikOptimal calls through one resident subprocess."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.solvers.rubikoptimal_external import (  # noqa: E402
    RUBIKOPTIMAL_TABLE_SIZES,
    RubikOptimalOracleSession,
    default_rubikoptimal_table_dir,
    rubikoptimal_table_bytes,
    rubikoptimal_table_inventory,
    rubikoptimal_tables_ready,
)
from rubik_optimal.validity import validate_cube  # noqa: E402


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = (
        f"rubikoptimal_resident_oracle{suffix}.tex"
        if suffix
        else "rubikoptimal_resident_oracle.tex"
    )
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"{_tex(row['case_id'])} & {_tex(row['iteration'])} & {_tex(row['status'])} & "
        f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\"
        for row in rows
    ]
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Case & Iteration & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def run_benchmark(
    *,
    root: Path,
    profile: str,
    seed: int,
    repetitions: int,
    timeout_seconds: float,
    executable: Path | None,
    package_path: Path | None,
    table_dir: Path,
    artifact_suffix: str,
) -> tuple[dict[str, object], Path, Path]:
    case_id = "shallow_r_u_f2"
    cube = CubeState.from_sequence("R U F2")
    source_sequence = ["R", "U", "F2"]
    valid, validation_message = validate_cube(cube)
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    runtimes: list[float] = []
    begin = time.perf_counter()

    with RubikOptimalOracleSession(
        executable=executable,
        package_path=package_path,
        table_dir=table_dir,
        root=root,
    ) as session:
        for iteration in range(max(1, repetitions)):
            if valid:
                result = session.solve(cube, timeout_seconds=timeout_seconds)
            else:
                raise RuntimeError(f"benchmark case is invalid: {validation_message}")
            runtime = round(result.runtime_seconds, 6)
            runtimes.append(float(runtime))
            row = {
                "case_id": case_id,
                "iteration": iteration,
                "state": cube.to_facelets(),
                "source_sequence": " ".join(source_sequence),
                "source_sequence_provided_to_solver": False,
                "valid": valid,
                "validation_message": validation_message,
                "solver": result.solver_name,
                "selected_backend": (
                    "rubikoptimal_resident"
                    if "selected_backend=rubikoptimal_resident" in result.notes
                    else "unknown"
                ),
                "status": result.status,
                "solution": " ".join(result.solution_moves),
                "solution_length": result.solution_length,
                "runtime_seconds": runtime,
                "table_bytes": result.table_bytes,
                "verified": result.is_verified,
                "notes": result.notes,
                "resident_process_reused": "resident_process_reused=true" in result.notes,
            }
            rows.append(row)
            if result.status != "exact" or result.is_verified is not True:
                errors.append(f"{case_id}#{iteration}: expected exact verified result, got {result.status}")
            if result.solution_length != len(source_sequence):
                errors.append(f"{case_id}#{iteration}: expected length 3, got {result.solution_length}")
        resident_start_count = session.start_count

    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    table_ready = rubikoptimal_tables_ready(table_dir)
    table_bytes = rubikoptimal_table_bytes(table_dir)
    payload: dict[str, object] = {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "backend": "rubikoptimal_resident",
        "api": "rubik_optimal.solvers.rubikoptimal_external.RubikOptimalOracleSession.solve",
        "case_count": len(rows),
        "repetitions": max(1, repetitions),
        "timeout_seconds": timeout_seconds,
        "wall_seconds": round(time.perf_counter() - begin, 6),
        "table_dir": str(table_dir.relative_to(root)) if table_dir.is_relative_to(root) else str(table_dir),
        "table_ready": table_ready,
        "table_bytes": table_bytes,
        "expected_table_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "table_inventory": rubikoptimal_table_inventory(table_dir),
        "resident_start_count": resident_start_count,
        "resident_process_reused_rows": sum(1 for row in rows if row["resident_process_reused"] is True),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "all_resident_backend": all(row["selected_backend"] == "rubikoptimal_resident" for row in rows),
        "max_runtime_seconds": max(runtimes, default=0.0),
        "mean_runtime_seconds": round(statistics.fmean(runtimes), 6) if runtimes else 0.0,
        "rubikoptimal_table_complete": table_ready and table_bytes == sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }
    output = (
        root
        / "results"
        / "processed"
        / f"rubikoptimal_resident_oracle_seed_{seed}_{profile}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, suffix)
    return payload, output, table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    parser.add_argument("--rubikoptimal-executable", type=Path, default=None)
    parser.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    parser.add_argument("--artifact-suffix", default="lowload")
    args = parser.parse_args()

    table_dir = args.rubikoptimal_table_dir or default_rubikoptimal_table_dir(ROOT)
    payload, output, table = run_benchmark(
        root=ROOT,
        profile=args.profile,
        seed=args.seed,
        repetitions=args.repetitions,
        timeout_seconds=args.timeout,
        executable=args.rubikoptimal_executable,
        package_path=args.rubikoptimal_package_path,
        table_dir=table_dir,
        artifact_suffix=args.artifact_suffix,
    )
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
