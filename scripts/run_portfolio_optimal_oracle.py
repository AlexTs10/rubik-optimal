#!/usr/bin/env python
"""Generate evidence for the Nissy/H48 exact 3x3 oracle portfolio."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.oracle import (
    FastOptimalOracleConfig,
    PortfolioOptimalOracle,
    PortfolioOptimalOracleConfig,
)
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, h48_table_path, resolve_h48_solver
from rubik_optimal.validity import validate_cube
from scripts.run_h48_oracle_certification import superflip_cube


@dataclass(frozen=True)
class PortfolioCase:
    case_id: str
    cube: CubeState
    source_sequence: list[str] | None
    expected_distance: int | None
    description: str


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _case_specs(seed: int, case_set: str) -> list[PortfolioCase]:
    random_1_10 = deterministic_scramble(10, seed, offset=101)
    random_2_15 = deterministic_scramble(15, seed, offset=102)
    random_3_20 = deterministic_scramble(20, seed, offset=103)
    depth_25 = deterministic_scramble(25, seed, offset=2001)
    light = [
        PortfolioCase("solved", CubeState.solved(), [], 0, "solved identity state"),
        PortfolioCase(
            "shallow_sequence",
            CubeState.from_sequence("R U F2"),
            ["R", "U", "F2"],
            3,
            "known shallow three-move state",
        ),
    ]
    thesis = light + [
        PortfolioCase(
            "random_1_10",
            CubeState.from_sequence(random_1_10),
            random_1_10,
            None,
            "deterministic thesis scramble at source depth 10",
        ),
        PortfolioCase(
            "random_2_15",
            CubeState.from_sequence(random_2_15),
            random_2_15,
            None,
            "deterministic thesis scramble at source depth 15",
        ),
        PortfolioCase(
            "random_3_20",
            CubeState.from_sequence(random_3_20),
            random_3_20,
            None,
            "deterministic stress scramble at source depth 20",
        ),
    ]
    hard = [
        PortfolioCase(
            "deterministic_depth_25",
            CubeState.from_sequence(depth_25),
            depth_25,
            None,
            "deterministic depth-25 direct state",
        ),
        PortfolioCase(
            "superflip_distance_20",
            superflip_cube(),
            None,
            20,
            "standard all-edges-flipped superflip state",
        ),
    ]
    if case_set == "light":
        return light
    if case_set == "hard":
        return hard
    if case_set == "full":
        return thesis + hard
    return thesis


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"portfolio_optimal_oracle{suffix}.tex" if suffix else "portfolio_optimal_oracle.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrrrr}\n",
        "\\hline\n",
        "Case & Source depth & Status & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in payload["rows"]:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['source_depth'])} & "
            f"{_tex(row['status'])} & {_tex(row['solution_length'])} & "
            f"{_tex(row['runtime_seconds'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--case-set", choices=["light", "thesis", "hard", "full"], default="thesis")
    parser.add_argument("--case-id", action="append", default=None, help="Run only the named case; repeatable")
    parser.add_argument("--nissy-timeout", type=float, default=30.0)
    parser.add_argument("--nissy-threads", type=int, default=2)
    parser.add_argument("--h48-timeout", type=float, default=300.0)
    parser.add_argument("--h48-threads", type=int, default=8)
    parser.add_argument("--h48-solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--h48-table-profile", choices=["quick", "thesis", "stress"], default="thesis")
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument(
        "--state-input-only",
        action="store_true",
        help="Do not pass the generating scramble to the portfolio; exercise arbitrary state-input behavior",
    )
    parser.add_argument(
        "--no-certificate-cache",
        action="store_true",
        help="Disable revalidated exact-certificate cache reuse for this evidence run",
    )
    parser.add_argument(
        "--no-upper-lower-certificate",
        action="store_true",
        help="Disable the upper/lower-bound certification shortcut for this evidence run",
    )
    parser.add_argument("--h48-upper-bound-proof-timeout", type=float, default=0.0)
    parser.add_argument("--h48-upper-bound-proof-max-gap", type=int, default=1)
    parser.add_argument("--native-korf-upper-bound-proof-timeout", type=float, default=0.0)
    parser.add_argument("--native-korf-upper-bound-proof-max-gap", type=int, default=1)
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    h48_solver = resolve_h48_solver(
        args.h48_solver,
        root=root,
        profile=args.h48_table_profile,
        seed=args.seed,
    )
    h48_config = FastOptimalOracleConfig(
        profile=args.h48_table_profile,
        seed=args.seed,
        solver=h48_solver,
        threads=args.h48_threads,
        timeout_seconds=args.h48_timeout,
        trusted_table=args.trusted_table,
        preload_table=args.preload_table,
        root=root,
    )
    config = PortfolioOptimalOracleConfig(
        h48=h48_config,
        nissy_timeout_seconds=args.nissy_timeout,
        nissy_threads=args.nissy_threads,
        try_certificate_cache=not args.no_certificate_cache,
        try_upper_lower_certificate=not args.no_upper_lower_certificate,
        h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
        h48_upper_bound_proof_max_gap=max(1, args.h48_upper_bound_proof_max_gap),
        native_korf_upper_bound_proof_timeout_seconds=max(
            0.0,
            args.native_korf_upper_bound_proof_timeout,
        ),
        native_korf_upper_bound_proof_max_gap=max(
            1,
            args.native_korf_upper_bound_proof_max_gap,
        ),
    )

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    cases = _case_specs(args.seed, args.case_set)
    if args.case_id is not None:
        selected_ids = set(args.case_id)
        cases = [case for case in cases if case.case_id in selected_ids]
        missing_ids = selected_ids - {case.case_id for case in cases}
        errors.extend(f"case-id not found in {args.case_set}: {case_id}" for case_id in sorted(missing_ids))

    with PortfolioOptimalOracle(config) as oracle:
        results = oracle.solve_many(
            [case.cube for case in cases],
            source_sequences=[None if args.state_input_only else case.source_sequence for case in cases],
        )
        for case, result in zip(cases, results, strict=True):
            valid, validation_message = validate_cube(case.cube)
            expected_matches = (
                case.expected_distance is None
                or (result.status == "exact" and result.solution_length == case.expected_distance)
            )
            selected_backend = "unknown"
            for token in result.notes.split("; "):
                if token.startswith("selected_backend="):
                    selected_backend = token.split("=", 1)[1]
                    break
            row = {
                "case_id": case.case_id,
                "description": case.description,
                "profile": args.profile,
                "seed": args.seed,
                "source_sequence": " ".join(case.source_sequence or []),
                "source_sequence_provided_to_solver": False if args.state_input_only else case.source_sequence is not None,
                "source_depth": len(case.source_sequence or []),
                "state": case.cube.to_facelets(),
                "valid": valid,
                "validation_message": validation_message,
                "expected_distance": case.expected_distance,
                "expected_distance_matches": expected_matches,
                "solver": result.solver_name,
                "selected_backend": selected_backend,
                "status": result.status,
                "solution": " ".join(result.solution_moves),
                "solution_length": result.solution_length,
                "runtime_seconds": round(result.runtime_seconds, 6),
                "expanded_nodes": result.expanded_nodes,
                "generated_nodes": result.generated_nodes,
                "table_size_bytes": result.table_bytes,
                "verified": result.is_verified,
                "notes": result.notes,
            }
            rows.append(row)
            if result.status != "exact" or not result.is_verified:
                errors.append(f"{case.case_id}: expected exact verified result, got {result.status}")
            if not expected_matches:
                errors.append(
                    f"{case.case_id}: expected distance {case.expected_distance}, got {result.solution_length}"
                )

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    table_path = h48_table_path(
        root=root,
        profile=args.h48_table_profile,
        seed=args.seed,
        solver=h48_solver,
    )
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "case_set": args.case_set,
        "case_ids": args.case_id,
        "nissy_timeout_seconds": args.nissy_timeout,
        "nissy_threads": args.nissy_threads,
        "nissy_core_direct_first": config.try_nissy_core_direct_first,
        "nissy_core_direct_timeout_seconds": config.nissy_core_direct_timeout_seconds,
        "h48_timeout_seconds": args.h48_timeout,
        "h48_threads": args.h48_threads,
        "h48_solver": h48_solver,
        "h48_table_profile": args.h48_table_profile,
        "h48_table_path": str(table_path.relative_to(root)),
        "h48_table_exists": table_path.exists(),
        "trusted_table": args.trusted_table,
        "preload_table": args.preload_table,
        "state_input_only": args.state_input_only,
        "certificate_cache_enabled": not args.no_certificate_cache,
        "upper_lower_certificate_enabled": not args.no_upper_lower_certificate,
        "h48_upper_bound_proof_timeout_seconds": config.h48_upper_bound_proof_timeout_seconds,
        "h48_upper_bound_proof_max_gap": config.h48_upper_bound_proof_max_gap,
        "native_korf_upper_bound_proof_timeout_seconds": (
            config.native_korf_upper_bound_proof_timeout_seconds
        ),
        "native_korf_upper_bound_proof_max_gap": config.native_korf_upper_bound_proof_max_gap,
        "rows": rows,
        "all_exact": all(row.get("status") == "exact" and row.get("verified") is True for row in rows),
        "all_expected_distances_match": all(row.get("expected_distance_matches") is True for row in rows),
        "selected_backends": sorted({str(row["selected_backend"]) for row in rows}),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "algorithmic_contract": {
            "state_scope": "every physically valid 3x3 CubeState accepted by the local verifier",
            "metric": "HTM / face-turn metric",
            "portfolio_order": (
                "for source-less CubeState rows, try nissy-core direct H48 first; "
                "then try Nissy optimal table for a bounded interval, then fall back to resident H48"
            ),
            "exactness_rule": "exact is propagated only from a backend row that independently verified the solution",
            "runtime_claim": "this artifact proves the recorded corpus, not every-state practical worst-case runtime",
        },
        "errors": errors,
        "passed": not errors,
    }

    output = root / "results" / "processed" / f"portfolio_optimal_oracle_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
