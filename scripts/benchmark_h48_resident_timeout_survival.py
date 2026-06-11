#!/usr/bin/env python
"""Record whether resident H48 survives a native timeout row."""

from __future__ import annotations

import argparse
import json
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
from rubik_optimal.solvers.h48_native import H48NativeOracleSession  # noqa: E402
from rubik_optimal.tables.h48 import h48_table_path, repository_root  # noqa: E402
from scripts.run_h48_oracle_certification import superflip_cube  # noqa: E402


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
    threads: int,
    timeout_seconds: float,
    artifact_suffix: str,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    table = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    begin = time.perf_counter()
    rows = []
    with H48NativeOracleSession(
        solver=solver,
        profile=profile,
        seed=seed,
        table_path=table,
        threads=max(1, threads),
        search_timeout_seconds=timeout_seconds,
        skip_table_check=True,
        root=root,
    ) as session:
        timeout_result = session.solve(superflip_cube(), timeout_seconds=timeout_seconds)
        rows.append({"case_id": "superflip_tiny_timeout", **_row(timeout_result)})
        exact_result = session.solve(CubeState.from_sequence("R"), timeout_seconds=timeout_seconds)
        rows.append({"case_id": "post_timeout_simple_exact", **_row(exact_result)})

    first = rows[0]
    second = rows[1]
    process_reused_after_timeout = (
        first["status"] == "timeout"
        and "timed_out_by_poll=True" in str(first["notes"])
        and second["status"] == "exact"
        and second["verified"] is True
        and "table_loaded_once=true" in str(second["notes"])
        and "stdout_wait_timeout_seconds=" in str(first["notes"])
    )
    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "threads": max(1, threads),
        "timeout_seconds": timeout_seconds,
        "table_path": str(table.relative_to(root)),
        "table_exists": table.exists(),
        "table_size_bytes": table.stat().st_size if table.exists() else None,
        "row_count": len(rows),
        "process_reused_after_timeout": process_reused_after_timeout,
        "passed": process_reused_after_timeout,
        "runtime_seconds": round(time.perf_counter() - begin, 6),
        "fast_runtime_proven_for_every_possible_state": False,
        "rows": rows,
        "notes": (
            "This probe checks an implementation optimization only: a resident H48 native timeout "
            "row should not force a table reload before the next query. It is not an all-state "
            "runtime proof."
        ),
    }
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    output = (
        root
        / "results"
        / "processed"
        / f"h48_resident_timeout_survival_seed_{seed}_{profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default="h48h0")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=0.001)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=repository_root())
    args = parser.parse_args()

    payload, output = run_probe(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        solver=args.solver,
        threads=args.threads,
        timeout_seconds=args.timeout,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": payload["passed"],
                "process_reused_after_timeout": payload["process_reused_after_timeout"],
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
