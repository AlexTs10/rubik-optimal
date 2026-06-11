#!/usr/bin/env python
"""Generate evidence for the unified optimized exact 3x3 oracle."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.oracle import (  # noqa: E402
    FastOptimalOracleConfig,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
)
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402
from scripts.run_h48_oracle_certification import certification_cases  # noqa: E402


SOURCE_SEQUENCES = {
    "shallow_r_u_f2": "R U F2",
}


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_value(notes: str, key: str) -> str | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    return match.group(1).strip() if match else None


def _note_values(notes: str, key: str) -> list[str]:
    return [match.strip() for match in re.findall(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)]


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"universal_optimal_oracle{suffix}.tex" if suffix else "universal_optimal_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['selected_backend'])} & "
            f"{_tex(row['backend_solver'])} & {_tex(row['status'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lllrrr}\n"
        "\\hline\n"
        "Case & Path & Backend & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _row_from_result(
    case_id: str,
    description: str,
    expected_distance: int,
    state: str,
    result,
    *,
    source_sequence_provided_to_solver: bool,
) -> dict[str, object]:
    selected_backends = _note_values(result.notes, "selected_backend")
    backend_solvers = _note_values(result.notes, "backend_solver")
    selected_backend = selected_backends[0] if selected_backends else None
    backend_solver = backend_solvers[0] if backend_solvers else None
    return {
        "case_id": case_id,
        "description": description,
        "expected_distance": expected_distance if expected_distance >= 0 else None,
        "state": state,
        "status": result.status,
        "verified": result.is_verified,
        "solution": " ".join(result.solution_moves),
        "solution_length": result.solution_length,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "selected_backend": selected_backend,
        "backend_solver": backend_solver,
        "nested_selected_backends": selected_backends,
        "nested_backend_solvers": backend_solvers,
        "started_backends": _note_value(result.notes, "started_backends"),
        "stopped_backends": _note_value(result.notes, "stopped_backends"),
        "h48_start_delay_seconds": _note_value(result.notes, "h48_start_delay_seconds"),
        "source_sequence_provided_to_solver": source_sequence_provided_to_solver,
        "direct_nissy_core_used": (
            "selected_backend=nissy-core-direct" in result.notes
            and "input_mode=cube_state" in result.notes
            and "table_symlink=true" in result.notes
        ),
        "resident_h48_symmetry_used": "selected_backend=resident-h48-symmetry-batch" in result.notes,
        "selected_rotation": _note_value(result.notes, "selected_rotation"),
        "resident_h48_symmetry_variants": _note_value(result.notes, "symmetry_variants"),
        "fast_runtime_proven_for_every_possible_state": (
            "fast_runtime_proven_for_every_possible_state=false" in result.notes
        ),
        "notes": result.notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--h48-start-delay", type=float, default=10.0)
    parser.add_argument("--no-h48", action="store_true", help="Disable resident H48 in the live race.")
    parser.add_argument("--no-nissy", action="store_true", help="Disable Nissy in the live race.")
    parser.add_argument("--h48-symmetry-variants", type=int, default=0)
    parser.add_argument("--h48-symmetry-timeout", type=float, default=5.0)
    parser.add_argument(
        "--rubikoptimal-race-timeout",
        type=float,
        default=-1.0,
        help="Enable table-complete RubikOptimal as a concurrent resident-race competitor.",
    )
    parser.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    parser.add_argument("--rubikoptimal-executable", type=Path, default=None)
    parser.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    parser.add_argument("--no-certificate-cache", action="store_true")
    parser.add_argument("--no-upper-lower-certificate", action="store_true")
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument(
        "--state-input-only",
        action="store_true",
        help="Do not pass known source sequences to the oracle; exercise raw CubeState input paths.",
    )
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    requested_case_ids = args.case_id or ["solved", "superflip_distance_20", "shallow_r_u_f2"]
    case_map = {case.case_id: case for case in certification_cases(args.seed)}
    missing_cases = [case_id for case_id in requested_case_ids if case_id not in case_map]
    if missing_cases:
        raise SystemExit(f"unknown certification case id(s): {', '.join(missing_cases)}")

    h48_config = FastOptimalOracleConfig(
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=max(1, args.threads),
        timeout_seconds=args.timeout,
        max_depth=20,
        trusted_table=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    resident_race = ResidentRaceOptimalOracleConfig(
        h48=h48_config,
        timeout_seconds=args.timeout,
        nissy_threads=max(1, min(args.threads, 2)),
        include_h48=not args.no_h48,
        include_nissy=not args.no_nissy,
        h48_start_delay_seconds=max(0.0, args.h48_start_delay),
    )
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for case_id in requested_case_ids:
        live_race_probe = case_id == "shallow_r_u_f2"
        config = UniversalOptimalOracleConfig(
            resident_race=resident_race,
            try_certificate_cache=(not live_race_probe) and not args.no_certificate_cache,
            try_upper_lower_certificate=(not live_race_probe) and not args.no_upper_lower_certificate,
            lower_bound_timeout_seconds=min(args.timeout, 30.0),
            resident_h48_symmetry_variants=max(0, args.h48_symmetry_variants),
            resident_h48_symmetry_timeout_seconds=(
                None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
            ),
            rubikoptimal_race_timeout_seconds=(
                None if args.rubikoptimal_race_timeout < 0 else args.rubikoptimal_race_timeout
            ),
            rubikoptimal_executable=args.rubikoptimal_executable,
            rubikoptimal_package_path=args.rubikoptimal_package_path,
            rubikoptimal_table_dir=args.rubikoptimal_table_dir,
        )
        with UniversalOptimalOracle(config) as oracle:
            case = case_map[case_id]
            source_sequence = None if args.state_input_only else SOURCE_SEQUENCES.get(case.case_id)
            result = oracle.solve(case.cube, source_sequence=source_sequence)
            row = _row_from_result(
                case.case_id,
                case.description,
                case.expected_distance,
                case.cube.to_facelets(),
                result,
                source_sequence_provided_to_solver=source_sequence is not None,
            )
            rows.append(row)
            if result.status != "exact" or not result.is_verified:
                errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
            if case.expected_distance >= 0 and result.solution_length != case.expected_distance:
                errors.append(
                    f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}"
                )
            if not row["fast_runtime_proven_for_every_possible_state"]:
                errors.append(f"{case.case_id}: universal oracle notes did not preserve fast-runtime boundary")

    selected_backends = sorted({str(row["selected_backend"]) for row in rows if row.get("selected_backend")})
    expected_paths = set()
    if "solved" in requested_case_ids:
        expected_paths.add("solved_fast_path")
    if "superflip_distance_20" in requested_case_ids:
        expected_paths.add("exact-certificate-cache")
    if "shallow_r_u_f2" in requested_case_ids:
        if args.rubikoptimal_race_timeout >= 0 and args.no_h48 and args.no_nissy:
            expected_paths.add("rubikoptimal-race")
        else:
            expected_paths.add(
                "resident-h48-symmetry-batch" if args.h48_symmetry_variants > 0 else "resident-race"
            )
    missing_expected_paths = sorted(expected_paths - set(selected_backends))
    if missing_expected_paths:
        errors.append(f"missing expected universal oracle path(s): {', '.join(missing_expected_paths)}")

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "table_path": str(table_path.relative_to(root)),
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "nissy_threads": resident_race.nissy_threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "h48_start_delay_seconds": max(0.0, args.h48_start_delay),
        "include_h48": not args.no_h48,
        "include_nissy": not args.no_nissy,
        "resident_h48_symmetry_variants": max(0, args.h48_symmetry_variants),
        "resident_h48_symmetry_timeout_seconds": (
            None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
        ),
        "rubikoptimal_race_timeout_seconds": (
            None if args.rubikoptimal_race_timeout < 0 else args.rubikoptimal_race_timeout
        ),
        "rubikoptimal_table_dir": (
            str(args.rubikoptimal_table_dir) if args.rubikoptimal_table_dir is not None else None
        ),
        "try_certificate_cache": not args.no_certificate_cache,
        "try_upper_lower_certificate": not args.no_upper_lower_certificate,
        "state_input_only": args.state_input_only,
        "case_ids": requested_case_ids,
        "selected_backends": selected_backends,
        "nested_selected_backends": sorted(
            {
                str(backend)
                for row in rows
                for backend in row.get("nested_selected_backends", [])
                if backend
            }
        ),
        "direct_nissy_core_rows": sum(1 for row in rows if row.get("direct_nissy_core_used") is True),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "oracle_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "latency_strategy": "exact certificate cache, upper/lower certificate, then resident exact-backend race",
            "resident_h48_symmetry_strategy": (
                "optional bounded non-identity whole-cube rotations before the resident race"
            ),
            "exactness_policy": "exact only after independent verification from the original input state or revalidated saved certificate",
            "runtime_claim": "this artifact proves optimized universal-oracle control flow on a corpus, not exhaustive every-state timing",
        },
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"universal_optimal_oracle_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
