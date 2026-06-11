#!/usr/bin/env python
"""Generate a deterministic comparison of admissible IDA* heuristic bounds."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.results import write_json
from rubik_optimal.scramble import deterministic_scramble
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    additive_edge_cpdb_bytes,
    additive_edge_cpdb_lower_bound,
    combined_table_lower_bound,
    corner_pattern_database_bytes,
    edge_pattern_database_bytes,
    heuristic_lower_bound_components,
)
from rubik_optimal.tables.corner_pdb import corner_pdb_available, default_corner_pdb_path
from rubik_optimal.tables.edge_pdb import (
    additive_edge_pdbs_available,
    default_additive_edge_pdb_paths,
    default_edge_pdb_paths,
    edge_pdbs_available,
)


COMPONENT_KEYS = ("misplaced_cubie", "coordinate_pruning", "corner_pdb", "edge_pdb")


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("_", "\\_")


def _sequence_text(moves: list[str]) -> str:
    return " ".join(moves)


def _fixed_shallow_cases(seed: int) -> list[tuple[str, list[str], int]]:
    return [
        ("solved", [], 0),
        ("single_R", ["R"], 1),
        ("two_R_U", ["R", "U"], 2),
        ("three_F_R_U", ["F", "R", "U"], 3),
        ("commutator_R_U_Ri_Ui", ["R", "U", "R'", "U'"], 4),
        ("deterministic_depth_5_a", deterministic_scramble(5, seed, offset=0), 5),
        ("deterministic_depth_5_b", deterministic_scramble(5, seed, offset=1), 5),
    ]


def _sample_cases(seed: int, depths: tuple[int, ...], cases_per_depth: int) -> list[tuple[str, list[str], int | None]]:
    cases: list[tuple[str, list[str], int | None]] = []
    for depth in depths:
        for offset in range(cases_per_depth):
            cases.append(
                (
                    f"sample_depth_{depth}_{offset}",
                    deterministic_scramble(depth, seed, offset=1000 + depth * 100 + offset),
                    None,
                )
            )
    return cases


def _mean(rows: list[dict[str, object]], key: str) -> float:
    return round(statistics.mean(int(row[key]) for row in rows), 3) if rows else 0.0


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "corpus",
        "source_depth",
        "exact_distance",
        "bfs_status",
        "misplaced_cubie_lower_bound",
        "coordinate_pruning_lower_bound",
        "corner_pdb_lower_bound",
        "edge_pdb_lower_bound",
        "combined_lower_bound",
        "additive_edge_cpdb_lower_bound",
        "combined_with_optional_cpdb_lower_bound",
        "dominant_default_component",
        "sequence",
        "exact_admissible",
        "combined_not_weaker_than_components",
        "optional_cpdb_not_weaker_than_default",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_table(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "{\\scriptsize\n",
        "\\setlength{\\tabcolsep}{3pt}\n",
        "\\begin{tabular}{lrrrrrrrrr}\n",
        "\\hline\n",
        "Corpus & Cases & Exact & Mis. & Co. & Cor. & Ed. & Comb. & CPDB & Adm. \\\\\n",
        "\\hline\n",
    ]
    for row in payload["by_corpus"]:
        lines.append(
            f"{_tex(row['corpus'])} & {_tex(row['case_count'])} & {_tex(row['exact_case_count'])} & "
            f"{_tex(row['average_misplaced_cubie'])} & {_tex(row['average_coordinate_pruning'])} & "
            f"{_tex(row['average_corner_pdb'])} & {_tex(row['average_edge_pdb'])} & "
            f"{_tex(row['average_combined'])} & {_tex(row.get('average_additive_edge_cpdb'))} & "
            f"{_tex(row['exact_rows_admissible'])} \\\\\n"
        )
    lines.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    path.write_text("".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument("--sample-depth", type=int, action="append", default=None)
    parser.add_argument("--sample-cases-per-depth", type=int, default=2)
    parser.add_argument("--include-optional-cpdb", action="store_true")
    parser.add_argument("--allow-missing-pdbs", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    corner_path = default_corner_pdb_path(root=root, profile=args.profile, seed=args.seed)
    edge_paths = default_edge_pdb_paths(root=root, profile=args.profile, seed=args.seed)
    cpdb_paths = default_additive_edge_pdb_paths(root=root, profile=args.profile, seed=args.seed)
    corner_available = corner_pdb_available(corner_path)
    edges_available = edge_pdbs_available(edge_paths)
    cpdb_available = additive_edge_pdbs_available(cpdb_paths)
    if not args.allow_missing_pdbs:
        missing = []
        if not corner_available:
            missing.append(str(corner_path))
        missing.extend(str(path) for path in edge_paths if not path.exists())
        if missing:
            raise SystemExit(f"missing required PDB artifacts: {missing}")
    if args.include_optional_cpdb and not cpdb_available:
        raise SystemExit(f"missing optional CPDB artifacts: {[str(path) for path in cpdb_paths if not path.exists()]}")

    sample_depths = tuple(args.sample_depth or [8, 12, 16])
    cases = [(case_id, moves, exact_depth, "shallow_exact") for case_id, moves, exact_depth in _fixed_shallow_cases(args.seed)]
    cases.extend(
        (case_id, moves, exact_depth, "deterministic_sample")
        for case_id, moves, exact_depth in _sample_cases(args.seed, sample_depths, args.sample_cases_per_depth)
    )

    begin = time.perf_counter()
    rows: list[dict[str, object]] = []
    for case_id, moves, exact_depth, corpus in cases:
        cube = CubeState.from_sequence(moves)
        exact_distance = None
        bfs_status = None
        if exact_depth is not None:
            exact_distance, bfs = exact_distance_bfs(cube, max_depth=max(0, exact_depth))
            bfs_status = bfs.status
            if exact_distance is None:
                raise RuntimeError(f"BFS did not prove exact distance for {case_id}")
        components = heuristic_lower_bound_components(cube)
        combined = combined_table_lower_bound(cube)
        optional_cpdb = additive_edge_cpdb_lower_bound(cube) if args.include_optional_cpdb and cpdb_available else None
        combined_with_cpdb = max(combined, optional_cpdb) if optional_cpdb is not None else combined
        component_values = [components[key] for key in COMPONENT_KEYS]
        dominant_value = max(component_values, default=0)
        dominant_default_component = ",".join(key for key in COMPONENT_KEYS if components[key] == dominant_value)
        exact_admissible = None
        if exact_distance is not None:
            exact_admissible = (
                all(value <= exact_distance for value in component_values)
                and combined <= exact_distance
                and (optional_cpdb is None or optional_cpdb <= exact_distance)
            )
        rows.append(
            {
                "case_id": case_id,
                "corpus": corpus,
                "source_depth": len(moves),
                "exact_distance": exact_distance,
                "bfs_status": bfs_status,
                "misplaced_cubie_lower_bound": components["misplaced_cubie"],
                "coordinate_pruning_lower_bound": components["coordinate_pruning"],
                "corner_pdb_lower_bound": components["corner_pdb"],
                "edge_pdb_lower_bound": components["edge_pdb"],
                "combined_lower_bound": combined,
                "additive_edge_cpdb_lower_bound": optional_cpdb,
                "combined_with_optional_cpdb_lower_bound": combined_with_cpdb,
                "dominant_default_component": dominant_default_component,
                "sequence": _sequence_text(moves),
                "exact_admissible": exact_admissible,
                "combined_not_weaker_than_components": combined >= max(component_values, default=0),
                "optional_cpdb_not_weaker_than_default": combined_with_cpdb >= combined,
            }
        )
    runtime_seconds = time.perf_counter() - begin

    by_corpus: list[dict[str, object]] = []
    for corpus in sorted({str(row["corpus"]) for row in rows}):
        corpus_rows = [row for row in rows if row["corpus"] == corpus]
        exact_rows = [row for row in corpus_rows if row["exact_distance"] is not None]
        by_corpus.append(
            {
                "corpus": corpus,
                "case_count": len(corpus_rows),
                "exact_case_count": len(exact_rows),
                "average_misplaced_cubie": _mean(corpus_rows, "misplaced_cubie_lower_bound"),
                "average_coordinate_pruning": _mean(corpus_rows, "coordinate_pruning_lower_bound"),
                "average_corner_pdb": _mean(corpus_rows, "corner_pdb_lower_bound"),
                "average_edge_pdb": _mean(corpus_rows, "edge_pdb_lower_bound"),
                "average_combined": _mean(corpus_rows, "combined_lower_bound"),
                "average_additive_edge_cpdb": _mean(
                    [row for row in corpus_rows if row["additive_edge_cpdb_lower_bound"] is not None],
                    "additive_edge_cpdb_lower_bound",
                )
                if args.include_optional_cpdb and cpdb_available
                else None,
                "max_combined": max(int(row["combined_lower_bound"]) for row in corpus_rows),
                "exact_rows_admissible": all(row["exact_admissible"] is True for row in exact_rows) if exact_rows else None,
            }
        )

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    json_path = root / "results" / "processed" / f"heuristic_comparison_seed_{args.seed}_{args.profile}{suffix}.json"
    csv_path = root / "results" / "processed" / f"heuristic_comparison_seed_{args.seed}_{args.profile}{suffix}.csv"
    table_path = root / "thesis" / "tables" / f"heuristic_comparison{suffix}.tex"
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "script": "scripts/compare_heuristics.py",
        "heuristic_stack": "IDA* lower bound = max(misplaced cubie, coordinate pruning, corner PDB, edge PDB)",
        "a_star_variant": "IDA*",
        "metric": "HTM",
        "corner_pdb_available": corner_available,
        "edge_pdbs_available": edges_available,
        "optional_cpdb_included": bool(args.include_optional_cpdb and cpdb_available),
        "optional_cpdb_available": cpdb_available,
        "corner_pdb_bytes": corner_pattern_database_bytes(),
        "edge_pdb_bytes": edge_pattern_database_bytes(),
        "additive_edge_cpdb_bytes": additive_edge_cpdb_bytes() if cpdb_available else 0,
        "case_count": len(rows),
        "exact_case_count": sum(1 for row in rows if row["exact_distance"] is not None),
        "all_exact_rows_admissible": all(
            row["exact_admissible"] is True for row in rows if row["exact_distance"] is not None
        ),
        "all_combined_not_weaker_than_components": all(
            row["combined_not_weaker_than_components"] is True for row in rows
        ),
        "all_optional_cpdb_not_weaker_than_default": all(
            row["optional_cpdb_not_weaker_than_default"] is True for row in rows
        ),
        "runtime_seconds": round(runtime_seconds, 6),
        "rows": rows,
        "by_corpus": by_corpus,
        "artifacts": {
            "json": str(json_path.relative_to(root)),
            "csv": str(csv_path.relative_to(root)),
            "latex_table": str(table_path.relative_to(root)),
        },
        "claim_boundary": (
            "The default IDA* heuristic is an admissible lower-bound stack for exact search. "
            "Rows without exact_distance compare lower bounds only; they do not prove exact 3x3 distance."
        ),
        "fast_runtime_proven_for_every_possible_state": False,
    }
    payload["passed"] = (
        payload["corner_pdb_available"] is True
        and payload["edge_pdbs_available"] is True
        and payload["all_exact_rows_admissible"] is True
        and payload["all_combined_not_weaker_than_components"] is True
    )

    write_json(json_path, payload)
    _write_csv(csv_path, rows)
    _write_table(table_path, payload)
    print(json.dumps({"output": str(json_path), "csv": str(csv_path), "table": str(table_path), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
