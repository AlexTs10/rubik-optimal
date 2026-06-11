#!/usr/bin/env python
"""Record that H48 lower-bound timeouts keep completed rows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.solvers import h48_native  # noqa: E402
from rubik_optimal.tables.h48 import h48_table_path, repository_root  # noqa: E402


def _lower_bound_row(result: h48_native.H48LowerBoundResult) -> dict[str, Any]:
    return {
        "solver_name": result.solver_name,
        "status": result.status,
        "lower_bound": result.lower_bound,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "table_bytes": result.table_bytes,
        "notes": result.notes,
    }


def _solver_row(result) -> dict[str, Any]:
    return {
        "solver_name": result.solver_name,
        "status": result.status,
        "solution_length": result.solution_length,
        "verified": result.is_verified,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "expanded_nodes": result.expanded_nodes,
        "table_bytes": result.table_bytes,
        "notes": result.notes,
    }


def run_probe(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    timeout_seconds: float,
    artifact_suffix: str,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    binary = h48_native.build_h48_backend(root=root, threads=1)
    original_build = h48_native.build_h48_backend
    original_run = h48_native.subprocess.run
    original_popen = h48_native.subprocess.Popen
    started_commands: list[list[str]] = []
    begin = time.perf_counter()

    partial_stdout = "\n".join(
        [
            (
                '{"status":"lower_bound","lower_bound":1,"runtime_seconds":0.01,'
                f'"table_size_bytes":{table.stat().st_size if table.exists() else 0},'
                '"table_check":"verified","table_storage":"mmap",'
                '"table_preload":"disabled"}'
            ),
            (
                '{"status":"lower_bound","lower_bound":9,"runtime_seconds":0.02,'
                f'"table_size_bytes":{table.stat().st_size if table.exists() else 0},'
                '"table_check":"verified","table_storage":"mmap",'
                '"table_preload":"disabled"}'
            ),
        ]
    ) + "\n"

    def timeout_after_partial_lower_bounds(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["h48-lower-bound-batch"],
            timeout=timeout_seconds,
            output=partial_stdout,
        )

    class FailedCandidateProcess:
        def __init__(self, command, **_kwargs) -> None:
            self.command = [str(part) for part in command]
            started_commands.append(self.command)

        def poll(self):
            return 0

        def communicate(self):
            return (
                '{"status":"failed","solution":"","solution_length":null,'
                '"expanded_nodes":null,"table_lookups":0,"table_fallbacks":0}',
                "",
            )

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    try:
        h48_native.build_h48_backend = lambda **_kwargs: binary
        h48_native.subprocess.run = timeout_after_partial_lower_bounds
        lower_result = h48_native.compute_h48_native_rotational_lower_bound(
            CubeState.from_sequence("R U F2"),
            variant_count=2,
            include_identity=True,
            solver=solver,
            profile=profile,
            seed=seed,
            table_path=table,
            timeout_seconds=timeout_seconds,
            threads=1,
            root=root,
        )

        h48_native.subprocess.Popen = FailedCandidateProcess
        ordered_race_result = h48_native.solve_h48_native_rotational_race(
            CubeState.from_sequence("R U F2"),
            variant_count=2,
            include_identity=True,
            max_concurrency=1,
            solver=solver,
            profile=profile,
            seed=seed,
            table_path=table,
            timeout_seconds=timeout_seconds,
            threads=1,
            order_by_lower_bound=True,
            lower_bound_order_timeout_seconds=timeout_seconds,
            root=root,
        )
    finally:
        h48_native.subprocess.Popen = original_popen
        h48_native.subprocess.run = original_run
        h48_native.build_h48_backend = original_build

    rows = [
        {"case_id": "rotational_lower_bound_partial_timeout", **_lower_bound_row(lower_result)},
        {"case_id": "parallel_order_partial_timeout", **_solver_row(ordered_race_result)},
    ]
    partial_lower_bound_preserved = (
        lower_result.status == "lower_bound"
        and lower_result.lower_bound == 9
        and "partial_timeout_recovered=true" in lower_result.notes
        and "partial_completed_count=2" in lower_result.notes
    )
    partial_ordering_preserved = (
        "order_status=partial_timeout_recovered" in ordered_race_result.notes
        and "partial_completed_count=2" in ordered_race_result.notes
        and len(started_commands) == 3
    )
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "timeout_seconds": timeout_seconds,
        "table_path": str(table.relative_to(root)),
        "table_exists": table.exists(),
        "table_size_bytes": table.stat().st_size if table.exists() else None,
        "row_count": len(rows),
        "partial_lower_bound_preserved": partial_lower_bound_preserved,
        "partial_ordering_preserved": partial_ordering_preserved,
        "passed": partial_lower_bound_preserved and partial_ordering_preserved,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "started_candidate_count_after_partial_order": len(started_commands),
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": rows,
        "notes": (
            "This probe simulates an outer H48 lower-bound batch timeout after two JSON rows "
            "have already been printed. It proves the Python wrapper keeps the admissible "
            "partial lower bound and still uses partial rows to order a later rotational race. "
            "It is not an all-state runtime proof."
        ),
    }
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"h48_lower_bound_partial_timeout_recovery_seed_{seed}_{profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h0")
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=repository_root())
    args = parser.parse_args()

    payload, output = run_probe(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        timeout_seconds=args.timeout,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": payload["passed"],
                "partial_lower_bound_preserved": payload["partial_lower_bound_preserved"],
                "partial_ordering_preserved": payload["partial_ordering_preserved"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
