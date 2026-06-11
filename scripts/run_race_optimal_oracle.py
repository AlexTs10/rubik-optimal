#!/usr/bin/env python
"""Generate evidence for the concurrent exact 3x3 oracle race."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.oracle import FastOptimalOracleConfig, RaceOptimalOracle, RaceOptimalOracleConfig
from rubik_optimal.results import write_json
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path
from scripts.run_h48_oracle_certification import certification_cases


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_value(notes: str, key: str) -> str | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    return match.group(1).strip() if match else None


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"race_optimal_oracle{suffix}.tex" if suffix else "race_optimal_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['selected_backend'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{llrrr}\n"
        "\\hline\n"
        "Case & Backend & Status & Length & Seconds \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--no-h48", action="store_true")
    parser.add_argument("--no-nissy-core-direct", action="store_true")
    parser.add_argument("--case-id", action="append", default=["shallow_r_u_f2"])
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    wanted = set(args.case_id)
    cases = [case for case in certification_cases(args.seed) if case.case_id in wanted]
    if not cases:
        raise SystemExit(f"no matching certification cases for: {sorted(wanted)}")

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
    config = RaceOptimalOracleConfig(
        h48=h48_config,
        timeout_seconds=args.timeout,
        nissy_threads=max(1, min(args.threads, 2)),
        include_h48=not args.no_h48,
        include_nissy=True,
        include_nissy_core_direct=not args.no_nissy_core_direct,
    )

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    oracle = RaceOptimalOracle(config)
    for case in cases:
        result = oracle.solve(case.cube)
        row = {
            "case_id": case.case_id,
            "description": case.description,
            "state": case.cube.to_facelets(),
            "status": result.status,
            "verified": result.is_verified,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": round(result.runtime_seconds, 6),
            "selected_backend": _note_value(result.notes, "selected_backend"),
            "started_backends": _note_value(result.notes, "started_backends"),
            "killed_backends": _note_value(result.notes, "killed_backends"),
            "notes": result.notes,
        }
        rows.append(row)
        if result.status != "exact" or not result.is_verified:
            errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")

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
        "nissy_threads": config.nissy_threads,
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "h48_enabled": not args.no_h48,
        "nissy_core_direct_enabled": not args.no_nissy_core_direct,
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "oracle_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "latency_strategy": (
                "start native H48 and a Nissy-side exact subprocess concurrently when enabled; "
                "for source-less states, the Nissy side prefers direct nissy-core cube-state input before "
                "representative-scramble recovery"
            ),
            "exactness_policy": "exact only after independent verification from the original input state",
            "runtime_claim": "this artifact is corpus evidence for race behavior, not an exhaustive every-state timing proof",
        },
        "errors": errors,
        "passed": not errors,
    }

    output = root / "results" / "processed" / f"race_optimal_oracle_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
