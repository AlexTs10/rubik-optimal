#!/usr/bin/env python
"""Generate evidence for the persistent learned exact-certificate cache."""

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
from rubik_optimal.results import read_jsonl, write_json  # noqa: E402
from rubik_optimal.scramble import deterministic_scramble  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402
from rubik_optimal.validity import validate_cube  # noqa: E402


@dataclass(frozen=True)
class LearnedCacheCase:
    case_id: str
    cube: CubeState
    source_depth: int


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_value(notes: str, key: str) -> str | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    return match.group(1).strip() if match else None


def _cases(seed: int, depths: list[int], cases_per_depth: int) -> list[LearnedCacheCase]:
    cases: list[LearnedCacheCase] = []
    for depth in depths:
        for index in range(cases_per_depth):
            sequence = deterministic_scramble(depth, seed, offset=9100 + depth * 100 + index)
            cases.append(
                LearnedCacheCase(
                    case_id=f"learned_random_depth_{depth}_{index}",
                    cube=CubeState.from_sequence(sequence),
                    source_depth=depth,
                )
            )
    return cases


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"learned_certificate_cache{suffix}.tex" if suffix else "learned_certificate_cache.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrllrrr}\n",
        "\\hline\n",
        "Case & Depth & First path & Replay path & Length & First s & Replay s \\\\\n",
        "\\hline\n",
    ]
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['source_depth'])} & "
            f"{_tex(row['first_selected_backend'])} & {_tex(row['replay_selected_backend'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['first_runtime_seconds'])} & "
            f"{_tex(row['replay_runtime_seconds'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def _first_pass_config(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    threads: int,
    timeout: float,
    resident_h48_batch_timeout: float,
    trusted_table: bool,
    learned_log: Path,
) -> UniversalOptimalOracleConfig:
    h48_config = FastOptimalOracleConfig(
        profile=profile,
        seed=seed,
        solver=solver,
        threads=max(1, threads),
        timeout_seconds=timeout,
        max_depth=20,
        trusted_table=trusted_table,
        root=root,
    )
    return UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=h48_config,
            timeout_seconds=timeout,
            nissy_threads=max(1, min(threads, 2)),
            include_h48=True,
            include_nissy=True,
            h48_start_delay_seconds=0.0,
            include_nissy_core_direct=True,
        ),
        try_certificate_cache=True,
        certificate_artifacts=(),
        learned_certificate_artifact=learned_log,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        resident_h48_batch_timeout_seconds=resident_h48_batch_timeout,
        try_portfolio_batch_before_resident_h48_batch=True,
    )


def _replay_config(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
    learned_log: Path,
) -> UniversalOptimalOracleConfig:
    h48_config = FastOptimalOracleConfig(
        profile=profile,
        seed=seed,
        solver=solver,
        threads=1,
        timeout_seconds=1.0,
        max_depth=20,
        trusted_table=True,
        root=root,
    )
    return UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=h48_config,
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
            include_nissy_core_direct=False,
        ),
        try_certificate_cache=True,
        certificate_artifacts=(),
        learned_certificate_artifact=learned_log,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--depth", type=int, action="append", default=None)
    parser.add_argument("--cases-per-depth", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--resident-h48-batch-timeout", type=float, default=30.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--artifact-suffix", default="lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    depths = args.depth or [4, 6]
    cases = _cases(args.seed, depths, max(1, args.cases_per_depth))
    if not cases:
        raise SystemExit("no learned-cache cases selected")

    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    learned_log = (
        root
        / "results"
        / "processed"
        / f"learned_exact_certificates_seed_{args.seed}_{args.profile}_{solver}{suffix}.jsonl"
    )
    if learned_log.exists():
        learned_log.unlink()

    first_config = _first_pass_config(
        root=root,
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=args.threads,
        timeout=args.timeout,
        resident_h48_batch_timeout=args.resident_h48_batch_timeout,
        trusted_table=args.trusted_table,
        learned_log=learned_log,
    )
    with UniversalOptimalOracle(first_config) as oracle:
        first_results = oracle.solve_many([case.cube for case in cases], source_sequences=[None] * len(cases))

    replay_config = _replay_config(
        root=root,
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        learned_log=learned_log,
    )
    with UniversalOptimalOracle(replay_config) as oracle:
        replay_results = oracle.solve_many([case.cube for case in cases], source_sequences=[None] * len(cases))

    learned_rows = read_jsonl(learned_log) if learned_log.exists() else []
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for case, first, replay in zip(cases, first_results, replay_results, strict=True):
        valid, validation_message = validate_cube(case.cube)
        first_backend = _note_value(first.notes, "selected_backend")
        replay_backend = _note_value(replay.notes, "selected_backend")
        row = {
            "case_id": case.case_id,
            "source_depth": case.source_depth,
            "state": case.cube.to_facelets(),
            "valid": valid,
            "validation_message": validation_message,
            "first_solver": first.solver_name,
            "first_selected_backend": first_backend,
            "first_status": first.status,
            "first_verified": first.is_verified,
            "first_runtime_seconds": round(first.runtime_seconds, 6),
            "replay_solver": replay.solver_name,
            "replay_selected_backend": replay_backend,
            "replay_status": replay.status,
            "replay_verified": replay.is_verified,
            "replay_runtime_seconds": round(replay.runtime_seconds, 6),
            "solution": " ".join(first.solution_moves),
            "solution_moves": first.solution_moves,
            "solution_length": first.solution_length,
            "replay_solution_length": replay.solution_length,
            "first_notes": first.notes,
            "replay_notes": replay.notes,
        }
        rows.append(row)
        if not valid:
            errors.append(f"{case.case_id}: invalid generated cube: {validation_message}")
        if first.status != "exact" or first.is_verified is not True:
            errors.append(f"{case.case_id}: first pass was not exact/verified: {first.status}")
        if first_backend == "exact-certificate-cache":
            errors.append(f"{case.case_id}: first pass unexpectedly used certificate cache")
        if replay.status != "exact" or replay.is_verified is not True:
            errors.append(f"{case.case_id}: replay pass was not exact/verified: {replay.status}")
        if replay_backend != "exact-certificate-cache":
            errors.append(f"{case.case_id}: replay did not use learned certificate cache: {replay_backend}")
        if replay.solution_length != first.solution_length:
            errors.append(
                f"{case.case_id}: replay length {replay.solution_length} != first length {first.solution_length}"
            )

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "certificate_store": "ExactCertificateStore",
        "learned_certificate_log": str(learned_log.relative_to(root)),
        "table_path": str(table_path.relative_to(root)),
        "depths": depths,
        "cases_per_depth": max(1, args.cases_per_depth),
        "case_count": len(cases),
        "timeout_seconds": args.timeout,
        "resident_h48_batch_timeout_seconds": args.resident_h48_batch_timeout,
        "threads": args.threads,
        "trusted_table": args.trusted_table,
        "first_pass_certificate_artifacts": [],
        "replay_live_backends_enabled": False,
        "learned_jsonl_row_count": len(learned_rows),
        "learned_jsonl_all_exact": bool(learned_rows)
        and all(row.get("status") == "exact" and row.get("verified") is True for row in learned_rows),
        "rows": rows,
        "first_pass_all_exact": all(row["first_status"] == "exact" for row in rows),
        "first_pass_all_verified": all(row["first_verified"] is True for row in rows),
        "first_pass_all_cache_miss": all(
            row["first_selected_backend"] != "exact-certificate-cache" for row in rows
        ),
        "replay_all_exact": all(row["replay_status"] == "exact" for row in rows),
        "replay_all_verified": all(row["replay_verified"] is True for row in rows),
        "replay_all_certificate_cache": all(
            row["replay_selected_backend"] == "exact-certificate-cache" for row in rows
        ),
        "max_first_runtime_seconds": max((float(row["first_runtime_seconds"]) for row in rows), default=0.0),
        "max_replay_runtime_seconds": max((float(row["replay_runtime_seconds"]) for row in rows), default=0.0),
        "fast_runtime_proven_for_every_possible_state": False,
        "claim_boundary": (
            "The learned certificate cache proves exact zero-search replay for states solved and verified "
            "earlier in this run. It increases repeat-query coverage; it is not an exhaustive all-state "
            "runtime proof."
        ),
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"learned_certificate_cache_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
