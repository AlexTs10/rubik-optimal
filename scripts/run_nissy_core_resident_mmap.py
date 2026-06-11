#!/usr/bin/env python
"""Generate evidence for resident nissy-core mmap-backed direct-state solving."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.solvers.nissy_external import solve_nissy_core_direct_optimal_batch
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path
from rubik_optimal.validity import validate_cube


@dataclass(frozen=True)
class MmapCase:
    case_id: str
    cube: CubeState
    source_sequence: list[str]
    expected_distance: int
    description: str


def _cases() -> list[MmapCase]:
    return [
        MmapCase(
            "shallow_ru",
            CubeState.from_sequence("R U"),
            ["R", "U"],
            2,
            "two-move direct cubie state",
        ),
        MmapCase(
            "shallow_ruf2",
            CubeState.from_sequence("R U F2"),
            ["R", "U", "F2"],
            3,
            "three-move direct cubie state",
        ),
    ]


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"nissy_core_resident_mmap{suffix}.tex" if suffix else "nissy_core_resident_mmap.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrrrr}\n",
        "\\hline\n",
        "Case & Expected & Length & Seconds & mmap \\\\\n",
        "\\hline\n",
    ]
    for row in payload["rows"]:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['expected_distance'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} & "
            f"{_tex(row['table_data_mode'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def _note_value(notes: str, key: str) -> str | None:
    prefix = f"{key}="
    for token in notes.split("; "):
        if token.startswith(prefix):
            return token.split("=", 1)[1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--max-depth", type=int, default=20)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    selected_table = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not selected_table.exists():
        raise SystemExit(f"missing H48 table: {selected_table}")

    cases = _cases()
    begin = time.perf_counter()
    results = solve_nissy_core_direct_optimal_batch(
        [case.cube for case in cases],
        solver=solver,
        profile=args.profile,
        seed=args.seed,
        table_path=selected_table,
        timeout_seconds=args.timeout,
        threads=args.threads,
        max_depth=args.max_depth,
        binary_path=root / ".missing-nissy-core-shell-for-mmap-evidence",
        root=root,
    )
    wrapper_wall_seconds = time.perf_counter() - begin

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for case, result in zip(cases, results, strict=True):
        valid, validation_message = validate_cube(case.cube)
        table_data_mode = _note_value(result.notes, "table_data_mode")
        solve_buffer_available = _note_value(result.notes, "solve_buffer_available")
        expected_distance_matches = (
            result.status == "exact" and result.solution_length == case.expected_distance
        )
        used_resident_mmap = (
            result.solver_name == f"nissy_core_python_resident_{solver}"
            and table_data_mode == "mmap"
            and solve_buffer_available == "True"
        )
        row = {
            "case_id": case.case_id,
            "description": case.description,
            "source_sequence": " ".join(case.source_sequence),
            "source_sequence_provided_to_solver": False,
            "expected_distance": case.expected_distance,
            "expected_distance_matches": expected_distance_matches,
            "state": case.cube.to_facelets(),
            "valid": valid,
            "validation_message": validation_message,
            "solver": result.solver_name,
            "status": result.status,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": round(result.runtime_seconds, 6),
            "table_size_bytes": result.table_bytes,
            "verified": result.is_verified,
            "table_data_mode": table_data_mode,
            "solve_buffer_available": solve_buffer_available,
            "used_resident_mmap": used_resident_mmap,
            "notes": result.notes,
        }
        rows.append(row)
        if result.status != "exact" or not result.is_verified:
            errors.append(f"{case.case_id}: expected exact verified, got {result.status}")
        if not expected_distance_matches:
            errors.append(
                f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}"
            )
        if not used_resident_mmap:
            errors.append(f"{case.case_id}: did not use resident nissy-core mmap path")

    runtimes = [float(row["runtime_seconds"]) for row in rows]
    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "table_path": str(selected_table.relative_to(root)),
        "table_size_bytes": selected_table.stat().st_size,
        "threads": args.threads,
        "timeout_seconds": args.timeout,
        "max_depth": args.max_depth,
        "input_mode": "cube_state",
        "source_sequences_provided_to_solver": False,
        "shell_fallback_disabled_by_missing_binary": True,
        "rows": rows,
        "row_count": len(rows),
        "all_exact": all(row.get("status") == "exact" for row in rows),
        "all_verified": all(row.get("verified") is True for row in rows),
        "all_expected_distances_match": all(
            row.get("expected_distance_matches") is True for row in rows
        ),
        "all_used_resident_mmap": all(row.get("used_resident_mmap") is True for row in rows),
        "table_data_modes": sorted({str(row.get("table_data_mode")) for row in rows}),
        "max_runtime_seconds": round(max(runtimes, default=0.0), 6),
        "wrapper_wall_seconds": round(wrapper_wall_seconds, 6),
        "fast_runtime_proven_for_every_possible_state": False,
        "claim_boundary": (
            "This artifact proves mmap-backed resident nissy-core direct-state solving on a "
            "saved h48 table corpus. It is not an exhaustive runtime proof over all 3x3 states."
        ),
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"nissy_core_resident_mmap_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, payload, f"_{solver}{suffix}" if suffix else f"_{solver}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
