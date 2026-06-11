#!/usr/bin/env python
"""Generate arbitrary-state corpus evidence for the RubikOptimal backend."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
from rubik_optimal.scramble import deterministic_scramble  # noqa: E402
from rubik_optimal.solvers.base import SolverResult  # noqa: E402
from rubik_optimal.solvers.rubikoptimal_external import (  # noqa: E402
    RUBIKOPTIMAL_TABLE_SIZES,
    default_rubikoptimal_table_dir,
    rubikoptimal_table_bytes,
    rubikoptimal_table_inventory,
    rubikoptimal_tables_ready,
    solve_rubikoptimal_external_batch,
)
from rubik_optimal.validity import validate_cube  # noqa: E402
from scripts.run_h48_oracle_certification import superflip_cube  # noqa: E402


@dataclass(frozen=True)
class RubikOptimalCase:
    case_id: str
    cube: CubeState
    source_sequence: list[str] | None
    expected_distance: int | None
    description: str


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def build_cases(
    *,
    seed: int,
    depths: list[int],
    cases_per_depth: int,
    include_superflip: bool,
) -> list[RubikOptimalCase]:
    rows = [
        RubikOptimalCase("solved", CubeState.solved(), [], 0, "solved identity state"),
        RubikOptimalCase(
            "shallow_r_u_f2",
            CubeState.from_sequence("R U F2"),
            ["R", "U", "F2"],
            3,
            "known shallow three-move state",
        ),
    ]
    for depth in depths:
        for index in range(max(1, cases_per_depth)):
            sequence = deterministic_scramble(depth, seed, offset=9000 + depth * 100 + index)
            rows.append(
                RubikOptimalCase(
                    f"random_depth_{depth}_{index}",
                    CubeState.from_sequence(sequence),
                    sequence,
                    None,
                    f"deterministic source-depth-{depth} direct state",
                )
            )
    if include_superflip:
        rows.append(
            RubikOptimalCase(
                "superflip_distance_20",
                superflip_cube(),
                None,
                20,
                "standard all-edges-flipped superflip state",
            )
        )
    return rows


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"rubikoptimal_oracle_corpus{suffix}.tex" if suffix else "rubikoptimal_oracle_corpus.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['source_depth'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrr}\n"
        "\\hline\n"
        "Case & Source depth & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def run_corpus(
    *,
    root: Path,
    profile: str,
    seed: int,
    cases: list[RubikOptimalCase],
    timeout_seconds: float,
    executable: Path | None,
    package_path: Path | None,
    table_dir: Path,
    artifact_suffix: str,
    batch_solver_func=solve_rubikoptimal_external_batch,
) -> tuple[dict[str, object], Path, Path]:
    table_ready = rubikoptimal_tables_ready(table_dir)
    table_bytes = rubikoptimal_table_bytes(table_dir)
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    runtimes: list[float] = []

    validation: dict[int, tuple[bool, str]] = {}
    valid_indices: list[int] = []
    for index, case in enumerate(cases):
        valid, validation_message = validate_cube(case.cube)
        validation[index] = (valid, validation_message)
        if valid:
            valid_indices.append(index)

    batch_results: dict[int, SolverResult] = {}
    batch_wall_seconds = 0.0
    if valid_indices:
        batch_begin = time.perf_counter()
        solved = batch_solver_func(
            [cases[index].cube for index in valid_indices],
            timeout_seconds=timeout_seconds * max(1, len(valid_indices)),
            executable=executable,
            package_path=package_path,
            table_dir=table_dir,
            root=root,
        )
        batch_wall_seconds = time.perf_counter() - batch_begin
        batch_results = {index: result for index, result in zip(valid_indices, solved, strict=True)}

    for index, case in enumerate(cases):
        valid, validation_message = validation[index]
        if valid:
            result = batch_results[index]
        else:
            result = SolverResult(
                solver_name="rubikoptimal_external",
                input_state=case.cube.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.0,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=table_bytes,
                status="failed",
                is_verified=False,
                notes=f"invalid generated corpus state: {validation_message}",
            )
        expected_distance_matches = (
            case.expected_distance is None
            or (result.status == "exact" and result.solution_length == case.expected_distance)
        )
        runtime = round(result.runtime_seconds, 6)
        runtimes.append(float(runtime))
        row = {
            "case_id": case.case_id,
            "description": case.description,
            "source_sequence": " ".join(case.source_sequence or []),
            "source_sequence_provided_to_solver": False,
            "source_depth": len(case.source_sequence or []),
            "state": case.cube.to_facelets(),
            "valid": valid,
            "validation_message": validation_message,
            "expected_distance": case.expected_distance,
            "expected_distance_matches": expected_distance_matches,
            "solver": result.solver_name,
            "selected_backend": (
                "rubikoptimal_external_batch"
                if "selected_backend=rubikoptimal_external_batch" in result.notes
                else "rubikoptimal_external"
            ),
            "status": result.status,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": runtime,
            "expanded_nodes": result.expanded_nodes,
            "generated_nodes": result.generated_nodes,
            "table_bytes": result.table_bytes,
            "verified": result.is_verified,
            "notes": result.notes,
        }
        rows.append(row)
        if result.status != "exact" or result.is_verified is not True:
            errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
        if not expected_distance_matches:
            errors.append(
                f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}"
            )

    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    payload: dict[str, object] = {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "backend": "rubikoptimal_external",
        "api": "rubik_optimal.solvers.rubikoptimal_external.solve_rubikoptimal_external_batch",
        "case_count": len(cases),
        "timeout_seconds": timeout_seconds,
        "batch_wall_seconds": round(batch_wall_seconds, 6),
        "table_dir": str(table_dir.relative_to(root)) if table_dir.is_relative_to(root) else str(table_dir),
        "table_ready": table_ready,
        "table_bytes": table_bytes,
        "expected_table_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "table_inventory": rubikoptimal_table_inventory(table_dir),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "all_expected_distances_match": all(row["expected_distance_matches"] is True for row in rows),
        "all_rubikoptimal_batch": all(row["selected_backend"] == "rubikoptimal_external_batch" for row in rows),
        "selected_backends": sorted({str(row["selected_backend"]) for row in rows}),
        "max_runtime_seconds": max(runtimes, default=0.0),
        "mean_runtime_seconds": round(statistics.fmean(runtimes), 6) if runtimes else 0.0,
        "algorithmic_contract": {
            "state_scope": "physically valid 3x3 facelet/cubie states accepted by the local verifier",
            "input_mode": "the solver receives only the cube state, never the generating scramble",
            "metric": "HTM / face-turn metric",
            "exactness_rule": "a row is exact only when RubikOptimal returns an optimal line and the local verifier accepts it",
            "runtime_claim": "this artifact proves the recorded corpus, not exhaustive every-state timing",
        },
        "rubikoptimal_table_complete": table_ready and table_bytes == sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }
    output = root / "results" / "processed" / f"rubikoptimal_oracle_corpus_seed_{seed}_{profile}{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, rows, suffix)
    return payload, output, table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--depth", type=int, action="append", default=None)
    parser.add_argument("--cases-per-depth", type=int, default=1)
    parser.add_argument("--include-superflip", action="store_true")
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    parser.add_argument("--rubikoptimal-executable", type=Path, default=None)
    parser.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    depths = args.depth or [5, 10, 15, 20]
    cases = build_cases(
        seed=args.seed,
        depths=depths,
        cases_per_depth=args.cases_per_depth,
        include_superflip=args.include_superflip,
    )
    if args.case_id is not None:
        wanted = set(args.case_id)
        cases = [case for case in cases if case.case_id in wanted]
        missing = wanted - {case.case_id for case in cases}
        if missing:
            raise SystemExit(f"case-id not found: {', '.join(sorted(missing))}")

    table_dir = args.rubikoptimal_table_dir or default_rubikoptimal_table_dir(args.root)
    payload, output, table = run_corpus(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        cases=cases,
        timeout_seconds=args.timeout,
        executable=args.rubikoptimal_executable,
        package_path=args.rubikoptimal_package_path,
        table_dir=table_dir,
        artifact_suffix=args.artifact_suffix,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "passed": payload["passed"],
                "case_count": payload["case_count"],
                "max_runtime_seconds": payload["max_runtime_seconds"],
            },
            indent=2,
        )
    )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
