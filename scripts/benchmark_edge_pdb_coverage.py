#!/usr/bin/env python
"""Measure lower-bound coverage from the expanded 6-edge PDB set."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.results import write_json
from rubik_optimal.tables.edge_pdb import (
    DEFAULT_EDGE_SUBSETS,
    default_additive_edge_pdb_paths,
    default_edge_pdb_path,
    additive_edge_pdb_size_bytes,
    edge_pdb_size_bytes,
    load_edge_pdb,
)

BASELINE_EDGE_SUBSETS = DEFAULT_EDGE_SUBSETS[:4]


def _random_sequence(rng: random.Random, depth: int) -> list[str]:
    moves: list[str] = []
    last_face: str | None = None
    for _ in range(depth):
        choices = [move for move in ALL_MOVES if move[0] != last_face]
        move = rng.choice(choices)
        moves.append(move)
        last_face = move[0]
    return moves


def _edge_lower_bound(cube: CubeState, subsets: tuple[tuple[int, ...], ...], *, root: Path, profile: str, seed: int) -> int:
    distances: list[int] = []
    for subset in subsets:
        path = default_edge_pdb_path(subset, root=root, profile=profile, seed=seed)
        distance = load_edge_pdb(path).distance(cube)
        distances.append(0 if distance is None else distance)
    return max(distances, default=0)


def _additive_edge_lower_bound(cube: CubeState, paths: tuple[Path, ...]) -> int:
    total = 0
    for path in paths:
        distance = load_edge_pdb(path).distance(cube)
        total += 0 if distance is None else distance
    return total


def _tex(value: object) -> str:
    return "--" if value is None else str(value).replace("_", "\\_")


def _write_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"edge_pdb_coverage{suffix}.tex"
    by_depth = payload["by_depth"]
    body = [
        "{\\small\n",
        "\\begin{tabular}{rrrrrrr}\n",
        "\\hline\n",
        "Depth & Cases & Improved & Avg. base & Avg. expanded & Avg. combined & Max gain \\\\\n",
        "\\hline\n",
    ]
    for row in by_depth:
        body.append(
            f"{_tex(row['depth'])} & {_tex(row['case_count'])} & {_tex(row['improved_count'])} & "
            f"{_tex(row['baseline_average'])} & {_tex(row['expanded_average'])} & "
            f"{_tex(row.get('combined_average'))} & "
            f"{_tex(row['max_improvement'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--depth", type=int, action="append", default=None)
    parser.add_argument("--cases-per-depth", type=int, default=16)
    parser.add_argument("--artifact-suffix", default="expanded8")
    parser.add_argument(
        "--include-additive",
        action="store_true",
        help="Also include the default compatible cost-partitioned edge-PDB sum",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    depths = tuple(args.depth or [8, 12, 16, 20, 25])
    missing = [
        str(default_edge_pdb_path(subset, root=root, profile=args.profile, seed=args.seed))
        for subset in DEFAULT_EDGE_SUBSETS
        if not default_edge_pdb_path(subset, root=root, profile=args.profile, seed=args.seed).exists()
    ]
    if missing:
        raise SystemExit(f"missing edge PDBs: {missing}")
    additive_paths = default_additive_edge_pdb_paths(root=root, profile=args.profile, seed=args.seed)
    missing_additive = [str(path) for path in additive_paths if not path.exists()]
    if args.include_additive and missing_additive:
        raise SystemExit(f"missing additive edge CPDBs: {missing_additive}")

    rng = random.Random(args.seed)
    rows: list[dict[str, object]] = []
    begin = time.perf_counter()
    for depth in depths:
        for index in range(args.cases_per_depth):
            sequence = _random_sequence(rng, depth)
            cube = CubeState.from_sequence(sequence)
            baseline = _edge_lower_bound(cube, BASELINE_EDGE_SUBSETS, root=root, profile=args.profile, seed=args.seed)
            expanded = _edge_lower_bound(cube, DEFAULT_EDGE_SUBSETS, root=root, profile=args.profile, seed=args.seed)
            additive = _additive_edge_lower_bound(cube, additive_paths) if args.include_additive else None
            combined = max(expanded, additive) if additive is not None else expanded
            rows.append(
                {
                    "case_id": f"depth_{depth}_{index}",
                    "depth": depth,
                    "sequence": " ".join(sequence),
                    "baseline_edge_lower_bound": baseline,
                    "expanded_edge_lower_bound": expanded,
                    "additive_edge_lower_bound": additive,
                    "combined_edge_lower_bound": combined,
                    "improvement": expanded - baseline,
                    "combined_improvement": combined - expanded,
                    "expanded_not_weaker": expanded >= baseline,
                    "combined_not_weaker": combined >= expanded,
                }
            )
    runtime_seconds = time.perf_counter() - begin

    by_depth: list[dict[str, object]] = []
    for depth in depths:
        depth_rows = [row for row in rows if row["depth"] == depth]
        baseline_values = [int(row["baseline_edge_lower_bound"]) for row in depth_rows]
        expanded_values = [int(row["expanded_edge_lower_bound"]) for row in depth_rows]
        combined_values = [int(row["combined_edge_lower_bound"]) for row in depth_rows]
        improvements = [int(row["improvement"]) for row in depth_rows]
        combined_improvements = [int(row["combined_improvement"]) for row in depth_rows]
        by_depth.append(
            {
                "depth": depth,
                "case_count": len(depth_rows),
                "improved_count": sum(1 for value in improvements if value > 0),
                "baseline_average": round(statistics.mean(baseline_values), 3),
                "expanded_average": round(statistics.mean(expanded_values), 3),
                "combined_average": round(statistics.mean(combined_values), 3),
                "average_improvement": round(statistics.mean(improvements), 3),
                "average_combined_improvement": round(statistics.mean(combined_improvements), 3),
                "max_improvement": max(improvements, default=0),
                "max_combined_improvement": max(combined_improvements, default=0),
            }
        )

    improved_case_count = sum(1 for row in rows if int(row["improvement"]) > 0)
    additive_improved_case_count = sum(1 for row in rows if int(row["combined_improvement"]) > 0)
    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "baseline_subset_count": len(BASELINE_EDGE_SUBSETS),
        "expanded_subset_count": len(DEFAULT_EDGE_SUBSETS),
        "additive_cost_partition_count": len(additive_paths) if args.include_additive else 0,
        "baseline_subsets": [list(subset) for subset in BASELINE_EDGE_SUBSETS],
        "expanded_subsets": [list(subset) for subset in DEFAULT_EDGE_SUBSETS],
        "case_count": len(rows),
        "depths": list(depths),
        "cases_per_depth": args.cases_per_depth,
        "improved_case_count": improved_case_count,
        "additive_improved_case_count": additive_improved_case_count,
        "all_expanded_not_weaker": all(row["expanded_not_weaker"] is True for row in rows),
        "all_combined_not_weaker": all(row["combined_not_weaker"] is True for row in rows),
        "edge_pdb_total_size_bytes": edge_pdb_size_bytes(
            tuple(default_edge_pdb_path(subset, root=root, profile=args.profile, seed=args.seed) for subset in DEFAULT_EDGE_SUBSETS)
        ),
        "additive_edge_pdb_total_size_bytes": additive_edge_pdb_size_bytes(additive_paths) if args.include_additive else 0,
        "runtime_seconds": round(runtime_seconds, 6),
        "rows": rows,
        "by_depth": by_depth,
        "passed": (
            all(row["expanded_not_weaker"] is True for row in rows)
            and all(row["combined_not_weaker"] is True for row in rows)
            and (improved_case_count > 0 or additive_improved_case_count > 0)
        ),
        "claim_boundary": (
            "Expanded 6-edge PDB coverage strengthens sampled admissible edge lower bounds. "
            "It does not prove fast optimal solving for every 3x3 state."
        ),
        "fast_runtime_proven_for_every_possible_state": False,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"edge_pdb_coverage_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
