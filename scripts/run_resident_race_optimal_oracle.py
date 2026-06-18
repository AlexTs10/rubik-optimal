#!/usr/bin/env python
"""Generate evidence for the resident-H48 exact 3x3 oracle race."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.oracle import (  # noqa: E402
    FastOptimalOracleConfig,
    ResidentRaceOptimalOracle,
    ResidentRaceOptimalOracleConfig,
)
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402
from scripts.run_h48_oracle_certification import certification_cases  # noqa: E402


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_value(notes: str, key: str) -> str | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    return match.group(1).strip() if match else None


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"resident_race_optimal_oracle{suffix}.tex" if suffix else "resident_race_optimal_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['mode'])} & {_tex(row['case_id'])} & {_tex(row['selected_backend'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lllrrr}\n"
        "\\hline\n"
        "Mode & Case & Backend & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def _row_from_result(mode: str, case_id: str, description: str, state: str, result) -> dict[str, object]:
    return {
        "mode": mode,
        "case_id": case_id,
        "description": description,
        "state": state,
        "status": result.status,
        "verified": result.is_verified,
        "solution": " ".join(result.solution_moves),
        "solution_length": result.solution_length,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "selected_backend": _note_value(result.notes, "selected_backend"),
        "started_backends": _note_value(result.notes, "started_backends"),
        "stopped_backends": _note_value(result.notes, "stopped_backends"),
        "notes": result.notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--h48-start-delay", type=float, default=0.0)
    parser.add_argument("--no-nissy-core-direct", action="store_true")
    parser.add_argument("--no-nissy-core-python-resident", action="store_true")
    parser.add_argument("--case-id", default="shallow_r_u_f2")
    parser.add_argument("--h48-repetitions", type=int, default=2)
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    cases = [case for case in certification_cases(args.seed) if case.case_id == args.case_id]
    if not cases:
        raise SystemExit(f"no matching certification case for: {args.case_id}")
    case = cases[0]

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

    rows: list[dict[str, object]] = []
    errors: list[str] = []

    race_config = ResidentRaceOptimalOracleConfig(
        h48=h48_config,
        timeout_seconds=args.timeout,
        nissy_threads=max(1, min(args.threads, 2)),
        include_h48=True,
        include_nissy=True,
        include_nissy_core_direct=not args.no_nissy_core_direct,
        include_nissy_core_python_resident=not args.no_nissy_core_python_resident,
        h48_start_delay_seconds=args.h48_start_delay,
    )
    with ResidentRaceOptimalOracle(race_config) as oracle:
        result = oracle.solve(case.cube)
        rows.append(
            _row_from_result(
                "resident_race",
                case.case_id,
                case.description,
                case.cube.to_facelets(),
                result,
            )
        )
        if result.status != "exact" or not result.is_verified:
            errors.append(f"{case.case_id}: resident race expected exact verified, got {result.status}")

    reuse_repetitions = max(0, args.h48_repetitions)
    reuse_begin = time.perf_counter()
    if reuse_repetitions > 0:
        reuse_config = ResidentRaceOptimalOracleConfig(
            h48=h48_config,
            timeout_seconds=args.timeout,
            include_h48=True,
            include_nissy=False,
        )
        with ResidentRaceOptimalOracle(reuse_config) as oracle:
            for index in range(reuse_repetitions):
                result = oracle.solve(case.cube)
                rows.append(
                    _row_from_result(
                        "resident_h48_reuse",
                        f"{case.case_id}_repeat_{index + 1}",
                        case.description,
                        case.cube.to_facelets(),
                        result,
                    )
                )
                if result.status != "exact" or not result.is_verified:
                    errors.append(f"{case.case_id} repeat {index + 1}: expected exact verified, got {result.status}")
    reuse_wall_seconds = time.perf_counter() - reuse_begin

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "table_path": str(table_path.relative_to(root)),
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "nissy_threads": race_config.nissy_threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "h48_start_delay_seconds": args.h48_start_delay,
        "nissy_core_direct_enabled": not args.no_nissy_core_direct,
        "nissy_core_python_resident_enabled": not args.no_nissy_core_python_resident,
        "h48_repetitions": reuse_repetitions,
        "h48_reuse_wall_seconds": round(reuse_wall_seconds, 6),
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "oracle_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "latency_strategy": (
                "race resident mmap-backed direct nissy-core cube-state solving, shell direct "
                "nissy-core, or external Nissy optimal against a resident FastOptimalOracle H48 session"
            ),
            "exactness_policy": "exact only after independent verification from the original input state",
            "runtime_claim": "this artifact proves low-overhead resident race behavior on a corpus, not exhaustive every-state timing",
        },
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"resident_race_optimal_oracle_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
