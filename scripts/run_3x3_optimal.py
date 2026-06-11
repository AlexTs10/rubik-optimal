#!/usr/bin/env python
"""Generate explicit native optimal 3x3 evidence with corner+edge PDB IDA*."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.search.heuristics import combined_table_lower_bound
from rubik_optimal.solvers.h48_native import solve_h48_native_optimal
from rubik_optimal.solvers.nissy_external import (
    solve_nissy_core_direct_optimal,
    solve_nissy_light_optimal,
    solve_nissy_optimal,
)
from rubik_optimal.solvers.optimal_native import solve_korf_native_optimal
from rubik_optimal.tables.h48 import DEFAULT_H48_SOLVER, ORACLE_H48_SOLVER, generate_h48_table
from rubik_optimal.validity import validate_cube


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_int(notes: str, key: str) -> int | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=(\d+)", notes)
    return int(match.group(1)) if match else None


def _case_specs(
    seed: int,
    include_hard: bool,
    *,
    extra_random_cases: int = 0,
    extra_random_depth: int = 25,
) -> list[tuple[str, list[str]]]:
    cases = [
        ("solved", []),
        ("shallow_sequence", ["R", "U", "F2"]),
        ("random_1_10", deterministic_scramble(10, seed, offset=101)),
        ("random_2_15", deterministic_scramble(15, seed, offset=102)),
    ]
    if include_hard:
        cases.append(("random_3_20", deterministic_scramble(20, seed, offset=103)))
    for index in range(extra_random_cases):
        cases.append(
            (
                f"extra_random_{index + 1}_{extra_random_depth}",
                deterministic_scramble(extra_random_depth, seed, offset=1000 + index),
            )
        )
    return cases


def _write_table(root: Path, rows: list[dict[str, object]], profile: str, artifact_suffix: str = "") -> Path:
    if artifact_suffix:
        filename = f"optimal_3x3_status_{profile}_{artifact_suffix}.tex"
    else:
        filename = "optimal_3x3_status.tex" if profile == "thesis" else f"optimal_3x3_status_{profile}.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_rows = []
    for row in rows:
        table_rows.append(
            f"{_tex(row['case_id'])} & {_tex(row['scramble_depth'])} & "
            f"{_tex(row['initial_lower_bound'])} & {_tex(row['status'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrrr}\n"
        "\\hline\n"
        "Case & Depth & Initial LB & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(table_rows)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _backend_notes(backend: str) -> str:
    descriptions = {
        "native": (
            "Selected backend: native full-cube IDA* using the maximum of complete corner plus "
            "6-edge pattern databases; optional flags may add the Nissy DR/UD lower-bound bridge "
            "or external upper-bound certification, but exactness is native only when the "
            "admissible search proves the row."
        ),
        "nissy-light": "Selected backend: external Nissy `solve light -o`.",
        "nissy-optimal": (
            "Selected backend: external Nissy `solve optimal -o` with the public "
            "pt_nxopt31_HTM table."
        ),
        "nissy-core-direct": (
            "Selected backend: local nissy-core shell H48 optimal solver fed by direct "
            "cubie-state conversion and a symlinked generated H48 table, with no representative "
            "scramble recovery."
        ),
        "h48-native": (
            "Selected backend: in-repository native wrapper around vendored nissy-core H48 "
            "tables, fed by direct cubie-state conversion rather than the source scramble."
        ),
    }
    return (
        descriptions[backend]
        + " Exact is claimed only for rows where the selected backend completed with status exact."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--hard-timeout", type=float, default=None)
    parser.add_argument("--tt-entries", type=int, default=0)
    parser.add_argument(
        "--backend",
        choices=["native", "nissy-light", "nissy-optimal", "nissy-core-direct", "h48-native"],
        default="native",
    )
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--split-depth", type=int, default=3)
    parser.add_argument(
        "--native-child-order",
        choices=["heuristic-desc", "heuristic-asc", "move"],
        default="heuristic-desc",
        help="Native IDA* child ordering for exact Korf-style search",
    )
    parser.add_argument("--dual-heuristic", action="store_true")
    parser.add_argument(
        "--nissy-heuristic",
        action="store_true",
        help="Use the optional native C++ bridge to Nissy's DR/UD symmetry pruning table as an admissible heuristic.",
    )
    parser.add_argument(
        "--no-nissy-axis-transforms",
        action="store_false",
        dest="nissy_axis_transforms",
        help="Disable axis-transform variants in the native Nissy lower-bound bridge.",
    )
    parser.add_argument("--nissy-data-dir", type=Path, default=None)
    parser.add_argument(
        "--nissy-certificate",
        action="store_true",
        help="For the native backend, obtain a verified Nissy-light candidate solution and let native IDA* certify the matching lower bound.",
    )
    parser.add_argument(
        "--native-upper-bound-proof-strategy",
        choices=["single-bound", "iterative"],
        default="single-bound",
        help=(
            "For native --nissy-certificate rows, prove exactness with one exhaustive "
            "upper_length-1 search or classic iterative IDA* bounds."
        ),
    )
    parser.add_argument("--include-hard", action="store_true", help="Include the depth-20 thesis random case")
    parser.add_argument("--extra-random-cases", type=int, default=0, help="Add deterministic extra random states to the evidence corpus")
    parser.add_argument("--extra-random-depth", type=int, default=25, help="Scramble length for extra deterministic random states")
    parser.add_argument("--h48-solver", default=DEFAULT_H48_SOLVER)
    parser.add_argument("--h48-oracle", action="store_true", help="Use h48h7, nissy-core's oracle-grade optimal H48 profile")
    parser.add_argument("--h48-table-profile", choices=["quick", "thesis", "stress"], default=None)
    parser.add_argument("--h48-generate", action="store_true", help="Generate or reuse the selected in-repo H48 table before running")
    parser.add_argument("--artifact-suffix", default="", help="Optional suffix for processed JSON/table outputs")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    include_hard = args.include_hard or args.profile == "stress"
    hard_timeout = args.hard_timeout if args.hard_timeout is not None else args.timeout
    selected_h48_profile = args.h48_table_profile or args.profile
    selected_h48_solver = ORACLE_H48_SOLVER if args.h48_oracle else args.h48_solver
    h48_metadata = None
    if args.backend in {"h48-native", "nissy-core-direct"} and args.h48_generate:
        h48_metadata = generate_h48_table(
            root=args.root,
            profile=selected_h48_profile,
            seed=args.seed,
            solver=selected_h48_solver,
            threads=args.threads,
        )
    rows: list[dict[str, object]] = []
    for case_id, scramble in _case_specs(
        args.seed,
        include_hard,
        extra_random_cases=max(0, args.extra_random_cases),
        extra_random_depth=max(0, args.extra_random_depth),
    ):
        cube = CubeState.from_sequence(scramble)
        valid, validation_message = validate_cube(cube)
        timeout = hard_timeout if case_id == "random_3_20" else args.timeout
        if args.backend in {"nissy-light", "nissy-optimal"}:
            solver = solve_nissy_optimal if args.backend == "nissy-optimal" else solve_nissy_light_optimal
            result = solver(
                cube,
                source_sequence=scramble,
                timeout_seconds=timeout,
                threads=args.threads,
                root=args.root,
            )
            upper_bound_solver = None
            upper_solution_length = None
            upper_bound_runtime_seconds = None
        elif args.backend == "nissy-core-direct":
            result = solve_nissy_core_direct_optimal(
                cube,
                solver=selected_h48_solver,
                profile=selected_h48_profile,
                seed=args.seed,
                timeout_seconds=timeout,
                threads=args.threads,
                root=args.root,
            )
            upper_bound_solver = None
            upper_solution_length = None
            upper_bound_runtime_seconds = None
        elif args.backend == "h48-native":
            result = solve_h48_native_optimal(
                cube,
                source_sequence=None,
                solver=selected_h48_solver,
                profile=selected_h48_profile,
                seed=args.seed,
                timeout_seconds=timeout,
                threads=args.threads,
                root=args.root,
            )
            upper_bound_solver = None
            upper_solution_length = None
            upper_bound_runtime_seconds = None
        else:
            upper_solution: list[str] | None = None
            upper_bound_solver = None
            upper_solution_length = None
            upper_bound_runtime_seconds = None
            if args.nissy_certificate:
                certificate = solve_nissy_light_optimal(
                    cube,
                    source_sequence=scramble,
                    timeout_seconds=timeout,
                    threads=args.threads,
                    root=args.root,
                )
                if certificate.status == "exact" and certificate.is_verified:
                    upper_solution = certificate.solution_moves
                    upper_bound_solver = certificate.solver_name
                    upper_solution_length = certificate.solution_length
                    upper_bound_runtime_seconds = round(certificate.runtime_seconds, 6)
            result = solve_korf_native_optimal(
                cube,
                max_depth=20,
                timeout_seconds=timeout,
                transposition_entries=args.tt_entries,
                threads=args.threads,
                split_depth=args.split_depth,
                child_order=args.native_child_order,
                dual_heuristic=args.dual_heuristic,
                nissy_heuristic=args.nissy_heuristic,
                nissy_axis_transforms=args.nissy_axis_transforms,
                nissy_data_dir=args.nissy_data_dir,
                source_sequence=scramble,
                upper_solution=upper_solution,
                upper_bound_proof_strategy=args.native_upper_bound_proof_strategy,
            )
        reported_initial_lower_bound = _note_int(result.notes, "initial_lower_bound")
        row = {
            "case_id": case_id,
            "profile": args.profile,
            "seed": args.seed,
            "scramble": " ".join(scramble),
            "scramble_depth": len(scramble),
            "state": cube.to_facelets(),
            "valid": valid,
            "validation_message": validation_message,
            "initial_lower_bound": reported_initial_lower_bound
            if reported_initial_lower_bound is not None
            else combined_table_lower_bound(cube),
            "projection_initial_lower_bound": combined_table_lower_bound(cube),
            "final_bound": _note_int(result.notes, "final_bound"),
            "solver": result.solver_name,
            "status": result.status,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": round(result.runtime_seconds, 6),
            "expanded_nodes": result.expanded_nodes,
            "generated_nodes": result.generated_nodes,
            "table_size_bytes": result.table_bytes,
            "verified": result.is_verified,
            "upper_bound_solver": upper_bound_solver,
            "upper_solution_length": upper_solution_length,
            "upper_bound_runtime_seconds": upper_bound_runtime_seconds,
            "notes": result.notes,
        }
        rows.append(row)

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    output = args.root / "results" / "processed" / f"optimal_3x3_seed_{args.seed}_{args.profile}{suffix}.json"
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "timeout_seconds": args.timeout,
        "hard_timeout_seconds": hard_timeout,
        "transposition_entries": args.tt_entries,
        "backend": args.backend,
        "threads": args.threads,
        "split_depth": args.split_depth,
        "native_child_order": args.native_child_order,
        "dual_heuristic": args.dual_heuristic,
        "nissy_heuristic": args.nissy_heuristic,
        "nissy_axis_transforms": args.nissy_axis_transforms,
        "nissy_data_dir": str(args.nissy_data_dir) if args.nissy_data_dir is not None else None,
        "nissy_certificate": args.nissy_certificate,
        "native_upper_bound_proof_strategy": args.native_upper_bound_proof_strategy,
        "h48_solver": selected_h48_solver if args.backend in {"h48-native", "nissy-core-direct"} else None,
        "h48_table_profile": selected_h48_profile if args.backend in {"h48-native", "nissy-core-direct"} else None,
        "h48_metadata": h48_metadata,
        "include_hard": include_hard,
        "extra_random_cases": max(0, args.extra_random_cases),
        "extra_random_depth": max(0, args.extra_random_depth),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" and row["verified"] is True for row in rows),
        "notes": _backend_notes(args.backend),
    }
    write_json(output, payload)
    table = _write_table(args.root, rows, args.profile, args.artifact_suffix)
    print(json.dumps({"output": str(output), "table": str(table), "all_exact": payload["all_exact"]}, indent=2))
    return 0 if payload["all_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
