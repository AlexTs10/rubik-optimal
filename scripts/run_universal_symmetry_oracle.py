#!/usr/bin/env python
"""Generate evidence for live symmetry-raced exact universal-oracle solving."""

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


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"universal_symmetry_oracle{suffix}.tex" if suffix else "universal_symmetry_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['selected_backend'])} & "
            f"{_tex(row['selected_rotation'])} & {_tex(row['status'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lllrrr}\n"
        "\\hline\n"
        "Case & Path & Rotation & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _row_from_result(case_id: str, description: str, expected_distance: int, state: str, result) -> dict[str, object]:
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
        "selected_backend": _note_value(result.notes, "selected_backend"),
        "backend_solver": _note_value(result.notes, "backend_solver"),
        "symmetry_variants": _note_value(result.notes, "symmetry_variants"),
        "selected_rotation": _note_value(result.notes, "selected_rotation"),
        "rotated_backend_solver": _note_value(result.notes, "rotated_backend_solver"),
        "rotated_runtime_seconds": _note_value(result.notes, "rotated_runtime_seconds"),
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
    parser.add_argument("--symmetry-variants", type=int, default=2)
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    requested_case_ids = args.case_id or ["shallow_r_u_f2"]
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
        include_h48=True,
        include_nissy=True,
        h48_start_delay_seconds=args.timeout,
    )
    config = UniversalOptimalOracleConfig(
        resident_race=resident_race,
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        lower_bound_timeout_seconds=min(args.timeout, 30.0),
        nissy_symmetry_variants=max(1, args.symmetry_variants),
    )

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    with UniversalOptimalOracle(config) as oracle:
        for case_id in requested_case_ids:
            case = case_map[case_id]
            result = oracle.solve(case.cube, source_sequence=SOURCE_SEQUENCES.get(case.case_id))
            row = _row_from_result(case.case_id, case.description, case.expected_distance, case.cube.to_facelets(), result)
            rows.append(row)
            if result.status != "exact" or not result.is_verified:
                errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
            if row["selected_backend"] != "nissy-symmetry-batch":
                errors.append(f"{case.case_id}: expected nissy-symmetry-batch, got {row['selected_backend']}")
            if row["backend_solver"] != "nissy_symmetry_batch_oracle":
                errors.append(f"{case.case_id}: expected nissy_symmetry_batch_oracle, got {row['backend_solver']}")
            if not row["selected_rotation"]:
                errors.append(f"{case.case_id}: missing selected rotation")
            if case.expected_distance >= 0 and result.solution_length != case.expected_distance:
                errors.append(f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}")
            if not row["fast_runtime_proven_for_every_possible_state"]:
                errors.append(f"{case.case_id}: universal oracle notes did not preserve fast-runtime boundary")

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
        "symmetry_variants": max(1, args.symmetry_variants),
        "case_ids": requested_case_ids,
        "selected_backends": sorted({str(row["selected_backend"]) for row in rows if row.get("selected_backend")}),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "all_nissy_symmetry_batch": all(row["selected_backend"] == "nissy-symmetry-batch" for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "oracle_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "latency_strategy": (
                "race an identity-plus-whole-cube-rotation exact Nissy batch against resident H48; "
                "the saved low-load artifact delays H48 so the Nissy symmetry competitor can prove the shallow row without launching H48"
            ),
            "exactness_policy": "exact only after the rotated exact solution is mapped back and verified on the original input state",
            "runtime_claim": "this artifact proves the optimized symmetry-batch control path on a small corpus, not exhaustive every-state timing",
        },
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"universal_symmetry_oracle_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
