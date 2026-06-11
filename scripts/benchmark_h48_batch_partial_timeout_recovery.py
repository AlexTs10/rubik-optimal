#!/usr/bin/env python
"""Record that native H48 batch timeout keeps completed rows."""

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


def _row(result) -> dict[str, Any]:
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
    begin = time.perf_counter()

    def timeout_after_first_row(*_args, **_kwargs):
        stdout = (
            '{"status":"exact","solution":"R\\u0027","solution_length":1,'
            '"proved_lower_bound":0,"runtime_seconds":0.01,'
            '"expanded_nodes":1,"table_lookups":1,"table_fallbacks":0,'
            f'"table_size_bytes":{table.stat().st_size if table.exists() else 0},'
            '"table_check":"verified","table_storage":"mmap",'
            '"table_preload":"disabled","auto_min_depth":"disabled",'
            '"lower_bound":0,"min_depth":0,"max_depth":20,'
            '"search_timeout_ms":1000,"timed_out_by_poll":false,'
            '"search_deadline_expired":false}\n'
        )
        raise subprocess.TimeoutExpired(cmd=["h48-batch"], timeout=timeout_seconds, output=stdout)

    try:
        h48_native.build_h48_backend = lambda **_kwargs: binary
        h48_native.subprocess.run = timeout_after_first_row
        results = h48_native.solve_h48_native_batch(
            [CubeState.from_sequence("R"), CubeState.from_sequence("R U F2")],
            solver=solver,
            profile=profile,
            seed=seed,
            table_path=table,
            timeout_seconds=timeout_seconds,
            threads=1,
            root=root,
        )
    finally:
        h48_native.subprocess.run = original_run
        h48_native.build_h48_backend = original_build

    rows = [
        {"case_id": "completed_before_outer_timeout", **_row(results[0])},
        {"case_id": "unfinished_when_outer_timeout_fired", **_row(results[1])},
    ]
    partial_rows_preserved = (
        len(rows) == 2
        and rows[0]["status"] == "exact"
        and rows[0]["verified"] is True
        and rows[1]["status"] == "timeout"
        and "partial_timeout_recovered=true" in str(rows[0]["notes"])
        and "partial_completed_count=1" in str(rows[1]["notes"])
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
        "partial_rows_preserved": partial_rows_preserved,
        "passed": partial_rows_preserved,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": rows,
        "notes": (
            "This probe simulates an outer native H48 batch process timeout after one JSON row "
            "has already been printed. It proves the Python wrapper keeps completed exact rows "
            "instead of marking the whole batch as timeout. It is not an all-state runtime proof."
        ),
    }
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"h48_batch_partial_timeout_recovery_seed_{seed}_{profile}_{solver}{suffix}.json"
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
                "partial_rows_preserved": payload["partial_rows_preserved"],
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
