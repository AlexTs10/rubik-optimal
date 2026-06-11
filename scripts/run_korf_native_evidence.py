#!/usr/bin/env python
"""Generate native-only Korf/IDA* evidence rows.

This script is intentionally separate from the H48/Nissy optimal-oracle
artifacts.  It exercises the in-repository Python Korf-style IDA* solver with
the native admissible heuristic stack and records which shallow rows also have
a BFS cross-check.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    combined_table_lower_bound,
    coordinate_pruning_table_bytes,
    corner_pattern_database_bytes,
    edge_pattern_database_bytes,
)
from rubik_optimal.solvers.korf import solve_korf_ida
from rubik_optimal.verify import verify_solution


@dataclass(frozen=True)
class KorfEvidenceCase:
    case_id: str
    scramble: tuple[str, ...]
    bfs_max_depth: int | None = None
    expected_exact_depth: int | None = None


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def default_cases(seed: int, *, include_depth12_probe: bool = True) -> list[KorfEvidenceCase]:
    cases = [
        KorfEvidenceCase("solved_bfs_exact", (), bfs_max_depth=0, expected_exact_depth=0),
        KorfEvidenceCase("shallow_r_u_f2_bfs_exact", ("R", "U", "F2"), bfs_max_depth=3, expected_exact_depth=3),
        KorfEvidenceCase(
            "deterministic_depth_6_native_ida",
            tuple(deterministic_scramble(6, seed, offset=601)),
            expected_exact_depth=6,
        ),
        KorfEvidenceCase(
            "deterministic_depth_8_native_ida",
            tuple(deterministic_scramble(8, seed, offset=801)),
            expected_exact_depth=8,
        ),
        KorfEvidenceCase(
            "deterministic_depth_10_native_ida",
            tuple(deterministic_scramble(10, seed, offset=1001)),
            expected_exact_depth=10,
        ),
    ]
    if include_depth12_probe:
        cases.append(
            KorfEvidenceCase(
                "deterministic_depth_12_native_probe",
                tuple(deterministic_scramble(12, seed, offset=1201)),
                expected_exact_depth=None,
            )
        )
    return cases


def evaluate_case(
    case: KorfEvidenceCase,
    *,
    max_depth: int,
    timeout_seconds: float,
    node_limit: int,
) -> dict[str, object]:
    cube = CubeState.from_sequence(case.scramble)
    bfs_distance = None
    bfs_status = "not_run_too_expensive"
    bfs_expanded_nodes = None
    bfs_generated_nodes = None
    if case.bfs_max_depth is not None:
        bfs_distance, bfs = exact_distance_bfs(cube, max_depth=case.bfs_max_depth)
        bfs_status = bfs.status
        bfs_expanded_nodes = bfs.expanded_nodes
        bfs_generated_nodes = bfs.generated_nodes

    result = solve_korf_ida(
        cube,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        node_limit=node_limit,
    )
    verification = verify_solution(cube, result.solution_moves) if result.status == "exact" else None
    bfs_cross_checked = (
        result.status == "exact"
        and bfs_distance is not None
        and result.solution_length == bfs_distance
        and result.is_verified
    )
    native_exact_proof = result.status == "exact" and result.is_verified
    expected_exact_matches = (
        case.expected_exact_depth is None
        or (result.status == "exact" and result.solution_length == case.expected_exact_depth)
    )
    exact_claim_supported = native_exact_proof and expected_exact_matches

    if bfs_cross_checked:
        proof_method = "bfs_cross_check_plus_native_ida_star"
    elif native_exact_proof:
        proof_method = "native_ida_star_complete_admissible_search"
    elif result.status in {"timeout", "lower_bound"}:
        proof_method = "no_exact_distance_claim"
    else:
        proof_method = "failed"

    return {
        "case_id": case.case_id,
        "scramble": " ".join(case.scramble),
        "scramble_depth": len(case.scramble),
        "state": cube.to_facelets(),
        "solver": result.solver_name,
        "backend_family": "native_korf_ida_star",
        "uses_h48": False,
        "uses_nissy": False,
        "uses_external_optimal_backend": False,
        "heuristic": "max(misplaced cubie, coordinate pruning, corner PDB, edge PDB)",
        "initial_lower_bound": combined_table_lower_bound(cube),
        "status": result.status,
        "solution": " ".join(result.solution_moves),
        "solution_length": result.solution_length,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "expanded_nodes": result.expanded_nodes,
        "generated_nodes": result.generated_nodes,
        "table_size_bytes": result.table_bytes,
        "verified": result.is_verified,
        "verification_message": verification.message if verification is not None else None,
        "bfs_max_depth": case.bfs_max_depth,
        "bfs_status": bfs_status,
        "bfs_distance": bfs_distance,
        "bfs_expanded_nodes": bfs_expanded_nodes,
        "bfs_generated_nodes": bfs_generated_nodes,
        "bfs_cross_checked": bfs_cross_checked,
        "expected_exact_depth": case.expected_exact_depth,
        "expected_exact_matches": expected_exact_matches,
        "exact_claim_supported": exact_claim_supported,
        "proof_method": proof_method,
        "notes": result.notes,
    }


def _write_table(root: Path, rows: Iterable[dict[str, object]], profile: str, artifact_suffix: str) -> Path:
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    table_path = root / "thesis" / "tables" / f"korf_native_evidence_{profile}{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"{_tex(row['case_id'])} & {_tex(row['scramble_depth'])} & "
        f"{_tex(row['initial_lower_bound'])} & {_tex(row['status'])} & "
        f"{_tex(row['solution_length'])} & {_tex(row['proof_method'])} \\\\"
        for row in rows
    ]
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrrrl}\n"
        "\\hline\n"
        "Case & Depth & Initial LB & Status & Length & Proof method \\\\\n"
        "\\hline\n"
        + "\n".join(body)
        + "\n\\hline\n\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def build_payload(
    *,
    root: Path,
    profile: str,
    seed: int,
    max_depth: int,
    timeout_seconds: float,
    node_limit: int,
    include_depth12_probe: bool,
) -> dict[str, object]:
    cases = default_cases(seed, include_depth12_probe=include_depth12_probe)
    rows = [
        evaluate_case(
            case,
            max_depth=max_depth,
            timeout_seconds=timeout_seconds,
            node_limit=node_limit,
        )
        for case in cases
    ]
    exact_rows = [row for row in rows if row["status"] == "exact"]
    bfs_rows = [row for row in rows if row["bfs_max_depth"] is not None]
    return {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "solver_track": "Korf/IDA*",
        "backend_family": "native_korf_ida_star",
        "uses_h48": False,
        "uses_nissy": False,
        "uses_external_optimal_backend": False,
        "max_depth": max_depth,
        "timeout_seconds": timeout_seconds,
        "node_limit": node_limit,
        "include_depth12_probe": include_depth12_probe,
        "corner_pdb_bytes": corner_pattern_database_bytes(),
        "edge_pdb_bytes": edge_pattern_database_bytes(),
        "coordinate_pruning_table_bytes": coordinate_pruning_table_bytes(),
        "rows": rows,
        "exact_row_count": len(exact_rows),
        "bfs_cross_checked_exact_row_count": sum(row["bfs_cross_checked"] is True for row in rows),
        "all_exact_rows_verified": all(row["verified"] is True for row in exact_rows),
        "all_exact_claims_supported": all(row["exact_claim_supported"] is True for row in exact_rows),
        "all_bfs_rows_cross_checked": all(row["bfs_cross_checked"] is True for row in bfs_rows),
        "all_rows_native_only": all(
            row["uses_h48"] is False
            and row["uses_nissy"] is False
            and row["uses_external_optimal_backend"] is False
            for row in rows
        ),
        "has_depth_6_or_deeper_exact_native_row": any(
            row["status"] == "exact" and int(row["scramble_depth"]) >= 6 for row in rows
        ),
        "has_depth_8_or_deeper_exact_native_row": any(
            row["status"] == "exact" and int(row["scramble_depth"]) >= 8 for row in rows
        ),
        "fast_runtime_proven_for_every_possible_state": False,
        "notes": (
            "Native-only Korf/IDA* evidence. Shallow rows include BFS cross-checks; deeper exact rows "
            "are exact only when the in-repository admissible IDA* search completes. H48, Nissy, "
            "RubikOptimal, and public known-distance certificate evidence are intentionally excluded."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--node-limit", type=int, default=20_000_000)
    parser.add_argument("--no-depth12-probe", action="store_false", dest="include_depth12_probe")
    parser.add_argument("--artifact-suffix", default="native_only")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    payload = build_payload(
        root=args.root,
        profile=args.profile,
        seed=args.seed,
        max_depth=args.max_depth,
        timeout_seconds=args.timeout,
        node_limit=args.node_limit,
        include_depth12_probe=args.include_depth12_probe,
    )
    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    output = args.root / "results" / "processed" / f"korf_native_evidence_seed_{args.seed}_{args.profile}{suffix}.json"
    write_json(output, payload)
    table = _write_table(args.root, payload["rows"], args.profile, args.artifact_suffix)
    passed = (
        payload["all_exact_rows_verified"] is True
        and payload["all_exact_claims_supported"] is True
        and payload["all_bfs_rows_cross_checked"] is True
        and payload["all_rows_native_only"] is True
        and payload["has_depth_6_or_deeper_exact_native_row"] is True
        and payload["has_depth_8_or_deeper_exact_native_row"] is True
    )
    print(json.dumps({"output": str(output), "table": str(table), "passed": passed}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
