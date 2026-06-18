#!/usr/bin/env python
"""Generate corpus evidence for the batched universal exact 3x3 oracle."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.oracle import (  # noqa: E402
    FastOptimalOracleConfig,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
)
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.scramble import deterministic_scramble  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402
from rubik_optimal.validity import validate_cube  # noqa: E402


@dataclass(frozen=True)
class BatchCase:
    case_id: str
    cube: CubeState
    source_sequence: list[str]
    source_depth: int


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_value(notes: str, key: str) -> str | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    return match.group(1).strip() if match else None


def _cases(seed: int, depths: list[int], cases_per_depth: int) -> list[BatchCase]:
    rows: list[BatchCase] = []
    for depth in depths:
        for index in range(cases_per_depth):
            offset = 7000 + depth * 100 + index
            sequence = deterministic_scramble(depth, seed, offset=offset)
            rows.append(
                BatchCase(
                    case_id=f"random_depth_{depth}_{index}",
                    cube=CubeState.from_sequence(sequence),
                    source_sequence=sequence,
                    source_depth=depth,
                )
            )
    return rows


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"universal_batch_oracle_corpus{suffix}.tex" if suffix else "universal_batch_oracle_corpus.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['source_depth'])} & "
            f"{_tex(row['selected_backend'])} & {_tex(row['nested_selected_backend'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrlllrr}\n"
        "\\hline\n"
        "Case & Depth & Universal path & Nested backend & Status & Length & Seconds \\\\\n"
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
    parser.add_argument("--depth", type=int, action="append", default=None)
    parser.add_argument("--cases-per-depth", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument(
        "--state-input-only",
        action="store_true",
        help="Do not pass the generating scramble to the oracle; exercise direct-state recovery.",
    )
    parser.add_argument(
        "--resident-h48-batch",
        action="store_true",
        help="For state-input-only live states, use the universal resident H48 batch path instead of the portfolio batch.",
    )
    parser.add_argument("--artifact-suffix", default="batch_lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    depths = args.depth or [5, 10, 15]
    case_list = _cases(args.seed, depths, max(1, args.cases_per_depth))
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
    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=h48_config,
            timeout_seconds=args.timeout,
            nissy_threads=max(1, min(args.threads, 2)),
            include_h48=True,
            include_nissy=True,
            h48_start_delay_seconds=0.0,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=args.resident_h48_batch,
    )

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    source_sequences = [None if args.state_input_only else case.source_sequence for case in case_list]
    with UniversalOptimalOracle(config) as oracle:
        results = oracle.solve_many([case.cube for case in case_list], source_sequences=source_sequences)

    for case, source_sequence, result in zip(case_list, source_sequences, results, strict=True):
        valid, validation_message = validate_cube(case.cube)
        selected_backend = _note_value(result.notes, "selected_backend")
        nested_selected_backend = _note_value(result.notes, "selected_backend")
        all_selected_backends = re.findall(r"(?:^|; )selected_backend=([^;]+)", result.notes)
        if len(all_selected_backends) > 1:
            nested_selected_backend = all_selected_backends[1]
        row = {
            "case_id": case.case_id,
            "source_depth": case.source_depth,
            "source_sequence_provided_to_solver": source_sequence is not None,
            "state": case.cube.to_facelets(),
            "valid": valid,
            "validation_message": validation_message,
            "solver": result.solver_name,
            "selected_backend": selected_backend,
            "nested_selected_backend": nested_selected_backend,
            "status": result.status,
            "verified": result.is_verified,
            "solution": " ".join(result.solution_moves),
            "solution_length": result.solution_length,
            "runtime_seconds": round(result.runtime_seconds, 6),
            "notes": result.notes,
        }
        rows.append(row)
        if not valid:
            errors.append(f"{case.case_id}: invalid generated cube: {validation_message}")
        if result.status != "exact" or not result.is_verified:
            errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
        expected_backend = "resident-h48-batch" if args.resident_h48_batch else "portfolio-batch"
        if selected_backend != expected_backend:
            errors.append(f"{case.case_id}: expected universal {expected_backend} path, got {selected_backend}")

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "table_path": str(table_path.relative_to(root)),
        "depths": depths,
        "cases_per_depth": max(1, args.cases_per_depth),
        "case_count": len(case_list),
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "nissy_threads": max(1, min(args.threads, 2)),
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "state_input_only": args.state_input_only,
        "resident_h48_batch": args.resident_h48_batch,
        "rows": rows,
        "all_exact": all(row["status"] == "exact" for row in rows),
        "all_verified": all(row["verified"] is True for row in rows),
        "all_universal_portfolio_batch": all(row["selected_backend"] == "portfolio-batch" for row in rows),
        "all_universal_resident_h48_batch": all(
            row["selected_backend"] == "resident-h48-batch" for row in rows
        ),
        "selected_backends": sorted({str(row["selected_backend"]) for row in rows if row.get("selected_backend")}),
        "nested_selected_backends": sorted(
            {str(row["nested_selected_backend"]) for row in rows if row.get("nested_selected_backend")}
        ),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "oracle_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "batch_strategy": (
                "universal solve_many applies certificate/upper-lower filters, then one resident H48 batch for live states"
                if args.resident_h48_batch
                else "universal solve_many applies certificate/upper-lower filters, then one portfolio batch for live states"
            ),
            "exactness_policy": "exact only after independent verification from the original input state",
            "runtime_claim": "this artifact proves the recorded deterministic corpus, not exhaustive every-state timing",
        },
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"universal_batch_oracle_corpus_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
