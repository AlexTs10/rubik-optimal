#!/usr/bin/env python
"""Validate generated benchmark result files."""

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
from rubik_optimal.pocket.optimal import (
    POCKET_ANTIPODE_COUNT,
    POCKET_DISTANCE_DISTRIBUTION,
    POCKET_GODS_NUMBER,
)
from rubik_optimal.results import read_jsonl
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import coordinate_pruning_table_bytes
from rubik_optimal.tables.corner_pdb import CORNER_STATE_COUNT, CornerPatternDatabase
from rubik_optimal.tables.edge_pdb import EDGE_PDB_STATE_COUNT, EdgePatternDatabase
from rubik_optimal.tables.metadata import sha256_file
from rubik_optimal.verify import verify_solution

REQUIRED_FIELDS = {
    "case_id",
    "seed",
    "scramble",
    "scramble_depth",
    "state",
    "known_exact_distance",
    "solver",
    "solution",
    "solution_length",
    "metric",
    "runtime_seconds",
    "expanded_nodes",
    "generated_nodes",
    "table_size_bytes",
    "status",
    "verified",
    "notes",
}


def _notes_int(notes: object, key: str) -> int | None:
    for part in str(notes).split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == key:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _load_processed_json(root: Path, relative: str) -> dict[str, object] | None:
    path = root / relative
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _pdb_byte_errors(
    row: dict[str, object],
    idx: int,
    expected_corner_pdb_bytes: int | None,
    expected_edge_pdb_bytes: int | None,
    expected_coordinate_bytes: int,
) -> list[str]:
    if row.get("solver") != "korf_ida_star_scoped":
        return []
    errors: list[str] = []
    expected_korf_table_bytes = (
        expected_coordinate_bytes + expected_corner_pdb_bytes + expected_edge_pdb_bytes
        if expected_corner_pdb_bytes is not None and expected_edge_pdb_bytes is not None
        else None
    )
    note_corner_bytes = _notes_int(row.get("notes", ""), "corner_pdb_bytes")
    note_edge_bytes = _notes_int(row.get("notes", ""), "edge_pdb_bytes")
    if expected_corner_pdb_bytes is not None and note_corner_bytes != expected_corner_pdb_bytes:
        errors.append(
            f"row {idx}: corner_pdb_bytes in notes {note_corner_bytes} "
            f"!= current corner metadata size_bytes {expected_corner_pdb_bytes}"
        )
    if expected_edge_pdb_bytes is not None and note_edge_bytes != expected_edge_pdb_bytes:
        errors.append(
            f"row {idx}: edge_pdb_bytes in notes {note_edge_bytes} "
            f"!= current edge metadata total_size_bytes {expected_edge_pdb_bytes}"
        )
    if (
        expected_korf_table_bytes is not None
        and row.get("table_size_bytes") is not None
        and int(row["table_size_bytes"]) != expected_korf_table_bytes
    ):
        errors.append(
            f"row {idx}: table_size_bytes {row.get('table_size_bytes')} "
            f"!= current coordinate+corner+edge PDB bytes {expected_korf_table_bytes}"
        )
    return errors


def _default_raw_path(root: Path) -> Path:
    candidates = sorted((root / "results" / "raw").glob("benchmarks_*.jsonl"))
    if not candidates:
        raise FileNotFoundError("No benchmark JSONL files found under results/raw")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=None)
    args = parser.parse_args()
    root = Path.cwd()
    raw_path = args.raw or _default_raw_path(root)
    rows = read_jsonl(raw_path)
    errors: list[str] = []
    expected_coordinate_bytes = coordinate_pruning_table_bytes()
    corner_metadata = _load_processed_json(root, "results/processed/corner_pdb_metadata_seed_2026_thesis.json")
    edge_metadata = _load_processed_json(root, "results/processed/edge_pdb_metadata_seed_2026_thesis.json")
    expected_corner_pdb_bytes = (
        int(corner_metadata["size_bytes"])
        if corner_metadata and "size_bytes" in corner_metadata
        else None
    )
    expected_edge_pdb_bytes = (
        int(edge_metadata["total_size_bytes"])
        if edge_metadata and "total_size_bytes" in edge_metadata
        else None
    )
    if not rows:
        errors.append(f"{raw_path} is empty")

    # Independent BFS cross-check of exact rows is capped at this depth; deeper
    # exact rows are counted (not silently skipped) so the coverage gap is
    # explicit in this tool's output.
    bfs_crosscheck_depth_cap = 5
    exact_rows_bfs_crosschecked = 0
    exact_rows_beyond_bfs_cap = 0

    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            errors.append(f"row {idx}: missing fields {sorted(missing)}")
            continue
        cube = CubeState.from_facelets(str(row["state"]))
        status = str(row["status"])
        solution = str(row["solution"])
        if row["verified"] is True:
            verification = verify_solution(cube, solution)
            if not verification.ok:
                errors.append(f"row {idx}: marked verified but verifier failed: {verification.message}")
            if row["solution_length"] != verification.move_count:
                errors.append(f"row {idx}: solution_length does not match parsed move count")
        if status == "exact" and row["solution_length"] is not None:
            exact_distance, _ = exact_distance_bfs(cube, max_depth=bfs_crosscheck_depth_cap)
            if exact_distance is None:
                exact_rows_beyond_bfs_cap += 1
            else:
                exact_rows_bfs_crosschecked += 1
                if exact_distance != row["solution_length"]:
                    errors.append(
                        f"row {idx}: exact solver length {row['solution_length']} != BFS distance {exact_distance}"
                    )
        errors.extend(
            _pdb_byte_errors(
                row,
                idx,
                expected_corner_pdb_bytes,
                expected_edge_pdb_bytes,
                expected_coordinate_bytes,
            )
        )

    required_generated = [
        root / "thesis" / "tables" / "benchmark_summary.tex",
        root / "thesis" / "tables" / "algorithm_status.tex",
        root / "thesis" / "figures" / "runtime_depth_data.tex",
    ]
    for path in required_generated:
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"missing generated thesis artifact: {path}")

    pocket_candidates = sorted((root / "results" / "processed").glob("pocket_cube_summary_seed_*_thesis.json"))
    if pocket_candidates:
        pocket_path = pocket_candidates[-1]
        pocket = json.loads(pocket_path.read_text(encoding="utf-8"))
        distribution = pocket.get("distribution", {})
        expected = int(pocket.get("expected_state_count", -1))
        observed = int(distribution.get("state_count", -2))
        counts = distribution.get("distribution", {})
        if not distribution.get("complete"):
            errors.append(f"{pocket_path}: pocket cube distribution is not complete")
        if expected != 3_674_160:
            errors.append(f"{pocket_path}: expected_state_count should be 3674160, got {expected}")
        if observed != expected:
            errors.append(f"{pocket_path}: state_count {observed} != expected {expected}")
        if sum(int(value) for value in counts.values()) != observed:
            errors.append(f"{pocket_path}: distribution counts do not sum to state_count")
        max_distance = int(distribution.get("max_distance", -1))
        if max_distance != POCKET_GODS_NUMBER:
            errors.append(
                f"{pocket_path}: max_distance {max_distance} != normalized 2x2x2 "
                f"God's Number {POCKET_GODS_NUMBER}"
            )
        observed_counts = {str(depth): int(value) for depth, value in counts.items()}
        expected_counts = {str(depth): value for depth, value in POCKET_DISTANCE_DISTRIBUTION.items()}
        if observed_counts != expected_counts:
            errors.append(
                f"{pocket_path}: distance distribution does not match the canonical "
                f"normalized 2x2x2 God's-Number distribution"
            )
        antipodes = int(observed_counts.get(str(POCKET_GODS_NUMBER), -1))
        if antipodes != POCKET_ANTIPODE_COUNT:
            errors.append(
                f"{pocket_path}: antipode count {antipodes} != expected {POCKET_ANTIPODE_COUNT}"
            )
        for representative in pocket.get("representative_solutions", []):
            if representative.get("status") != "exact" or representative.get("verified") is not True:
                errors.append(f"{pocket_path}: representative {representative.get('case_id')} is not verified exact")
        for path in [
            root / "thesis" / "tables" / "pocket_cube_distribution.tex",
            root / "thesis" / "tables" / "pocket_cube_representatives.tex",
        ]:
            if not path.exists() or path.stat().st_size == 0:
                errors.append(f"missing generated pocket thesis artifact: {path}")

    corner_candidates = sorted((root / "results" / "processed").glob("corner_pdb_metadata_seed_*_thesis.json"))
    if corner_candidates:
        corner_path = corner_candidates[-1]
        corner = json.loads(corner_path.read_text(encoding="utf-8"))
        pdb_path = root / str(corner.get("file_path", ""))
        if corner.get("state_count") != CORNER_STATE_COUNT:
            errors.append(f"{corner_path}: state_count should be {CORNER_STATE_COUNT}, got {corner.get('state_count')}")
        if corner.get("complete") is not True:
            errors.append(f"{corner_path}: corner PDB is not complete")
        if corner.get("visited_states") != CORNER_STATE_COUNT:
            errors.append(
                f"{corner_path}: visited_states should be {CORNER_STATE_COUNT}, got {corner.get('visited_states')}"
            )
        if not pdb_path.exists():
            errors.append(f"{corner_path}: missing binary PDB artifact {pdb_path}")
        else:
            if corner.get("checksum_sha256") != sha256_file(pdb_path):
                errors.append(f"{corner_path}: checksum does not match {pdb_path}")
            try:
                with CornerPatternDatabase(pdb_path) as pdb:
                    if not pdb.header.complete:
                        errors.append(f"{pdb_path}: binary header does not mark complete PDB")
                    if pdb.distance(CubeState.solved()) != 0:
                        errors.append(f"{pdb_path}: solved corner distance is not zero")
                    if pdb.distance(CubeState.from_sequence("R")) != 1:
                        errors.append(f"{pdb_path}: one-move corner distance is not one")
            except ValueError as exc:
                errors.append(f"{pdb_path}: invalid corner PDB binary header: {exc}")
        table_path = root / "thesis" / "tables" / "corner_pdb_metadata.tex"
        if not table_path.exists() or table_path.stat().st_size == 0:
            errors.append(f"missing generated corner PDB thesis artifact: {table_path}")

    edge_candidates = sorted((root / "results" / "processed").glob("edge_pdb_metadata_seed_*_thesis.json"))
    if edge_candidates:
        edge_path = edge_candidates[-1]
        edge = json.loads(edge_path.read_text(encoding="utf-8"))
        subsets = edge.get("subsets", [])
        if edge.get("complete") is not True:
            errors.append(f"{edge_path}: edge PDB set is not complete")
        if edge.get("total_state_count") != EDGE_PDB_STATE_COUNT * len(subsets):
            errors.append(f"{edge_path}: total_state_count does not match subset count")
        if len(subsets) < 8:
            errors.append(f"{edge_path}: expected the expanded eight-subset edge PDB set, got {len(subsets)}")
        for subset in subsets:
            pdb_path = root / str(subset.get("file_path", ""))
            if subset.get("state_count") != EDGE_PDB_STATE_COUNT:
                errors.append(
                    f"{edge_path}: subset {subset.get('subset_label')} state_count should be {EDGE_PDB_STATE_COUNT}"
                )
            if subset.get("complete") is not True:
                errors.append(f"{edge_path}: subset {subset.get('subset_label')} is not complete")
            if subset.get("visited_states") != EDGE_PDB_STATE_COUNT:
                errors.append(
                    f"{edge_path}: subset {subset.get('subset_label')} visited_states should be {EDGE_PDB_STATE_COUNT}"
                )
            if not pdb_path.exists():
                errors.append(f"{edge_path}: missing binary edge PDB artifact {pdb_path}")
                continue
            if subset.get("checksum_sha256") != sha256_file(pdb_path):
                errors.append(f"{edge_path}: checksum does not match {pdb_path}")
            try:
                with EdgePatternDatabase(pdb_path) as pdb:
                    if not pdb.header.complete:
                        errors.append(f"{pdb_path}: binary header does not mark complete PDB")
                    if pdb.distance(CubeState.solved()) != 0:
                        errors.append(f"{pdb_path}: solved edge distance is not zero")
                    if pdb.distance(CubeState.from_sequence("R")) != 1:
                        errors.append(f"{pdb_path}: one-move edge distance is not one")
            except ValueError as exc:
                errors.append(f"{pdb_path}: invalid edge PDB binary header: {exc}")
        table_path = root / "thesis" / "tables" / "edge_pdb_metadata.tex"
        if not table_path.exists() or table_path.stat().st_size == 0:
            errors.append(f"missing generated edge PDB thesis artifact: {table_path}")

    optimal_path = root / "results" / "processed" / "optimal_3x3_seed_2026_thesis.json"
    if optimal_path.exists():
        optimal = json.loads(optimal_path.read_text(encoding="utf-8"))
        if optimal.get("backend") != "native":
            errors.append(
                f"{optimal_path}: canonical thesis optimal artifact must use backend=native; "
                f"got {optimal.get('backend')!r}"
            )
        bad_solvers = [
            row.get("solver")
            for row in optimal.get("rows", [])
            if str(row.get("solver", "")).startswith(("h48_", "nissy_"))
        ]
        if bad_solvers:
            errors.append(f"{optimal_path}: native artifact contains non-native solvers {bad_solvers}")

    h48_candidates = sorted((root / "results" / "processed").glob("h48_metadata_seed_*_*.json"))
    for h48_path in h48_candidates:
        h48 = json.loads(h48_path.read_text(encoding="utf-8"))
        table_path = root / str(h48.get("file_path", ""))
        if h48.get("table_kind") != "h48_pruning_table":
            errors.append(f"{h48_path}: table_kind should be h48_pruning_table")
        if h48.get("backend_source") != "vendored_nissy_core_h48":
            errors.append(f"{h48_path}: backend_source should identify the vendored H48 backend")
        if h48.get("license") != "GPL-3.0-or-later":
            errors.append(f"{h48_path}: license should be GPL-3.0-or-later")
        if not table_path.exists():
            errors.append(f"{h48_path}: missing binary H48 table artifact {table_path}")
            continue
        if h48.get("checksum_sha256") != sha256_file(table_path):
            errors.append(f"{h48_path}: checksum does not match {table_path}")
        if h48.get("table_size_bytes") != table_path.stat().st_size:
            errors.append(f"{h48_path}: table_size_bytes does not match {table_path}")
        if "estimated_table_size_bytes" in h48 and h48.get("estimated_table_size_bytes") != table_path.stat().st_size:
            errors.append(f"{h48_path}: estimated_table_size_bytes does not match {table_path}")
        if "estimated_size_matches_actual" in h48 and h48.get("estimated_size_matches_actual") is not True:
            errors.append(f"{h48_path}: estimated_size_matches_actual should be true")
    if h48_candidates:
        table_path = root / "thesis" / "tables" / "h48_metadata.tex"
        if not table_path.exists() or table_path.stat().st_size == 0:
            errors.append(f"missing generated H48 thesis artifact: {table_path}")

    result = {
        "raw": str(raw_path),
        "rows": len(rows),
        "bfs_crosscheck_depth_cap": bfs_crosscheck_depth_cap,
        "exact_rows_bfs_crosschecked": exact_rows_bfs_crosschecked,
        "exact_rows_beyond_bfs_crosscheck_cap": exact_rows_beyond_bfs_cap,
        "errors": errors,
    }
    if exact_rows_beyond_bfs_cap:
        result["bfs_crosscheck_note"] = (
            f"{exact_rows_beyond_bfs_cap} exact row(s) have solution_length > "
            f"{bfs_crosscheck_depth_cap} and receive no independent BFS distance "
            "cross-check from this tool; their exactness rests on the solver's own "
            "optimality proof and the replay verification above."
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
