#!/usr/bin/env python
"""Measure the heuristic-strength gain from the 7-edge PDB (WORSTCASE Path 1).

Adapts ``scripts/measure_heuristic_strength.py`` (§5 reusable scaffold) to the
7-edge follow-up. For a fixed-seed sample of deep random states plus the
superflip it tabulates each admissible component and the combined MAX with and
without the 7-edge layer, reports the mean h-gain and the implied IDA* node
factor (~13.3 per +1 to h), and runs the §5.1 admissibility check (h <= exact
BFS distance, BFS depth <= 5). Results are written to results/processed/ so the
measurement is reproducible evidence rather than console-only output.

Run: PYTHONPATH=src python3 scripts/measure_seven_edge_strength.py
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    corner_pattern_database_lower_bound,
    edge_pattern_database_lower_bound,
    heuristic_lower_bound_components,
)
from rubik_optimal.tables.edge_pdb import default_edge_pdb_paths_7, load_edge_pdb

BRANCHING = 13.3  # mean HTM branching factor used for the node-factor estimate


def _present_seven_edge_paths() -> list:
    """Return the 7-edge PDB paths that currently exist (subset of the default set).

    Measured directly (not via the heuristic's all-present gate) so a meaningful
    number can be reported as soon as the FIRST 7-edge table is generated; the
    final run with both subsets reports the fuller max-over-both bound.
    """

    return [path for path in default_edge_pdb_paths_7(root=ROOT) if path.exists()]


def _present_seven_edge_h(cube: CubeState, paths: list) -> int:
    best = 0
    for path in paths:
        distance = load_edge_pdb(str(path)).distance(cube)
        if distance is not None and distance > best:
            best = distance
    return best


def _scramble(rng: random.Random, length: int) -> list[str]:
    moves: list[str] = []
    previous = None
    while len(moves) < length:
        move = rng.choice(ALL_MOVES)
        if same_face(previous, move):
            continue
        moves.append(move)
        previous = move
    return moves


def _components_without_seven(cube: CubeState) -> int:
    components = heuristic_lower_bound_components(cube)
    return max(value for key, value in components.items() if key != "edge_pdb7")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--depths", type=int, nargs="+", default=[10, 12, 14, 16, 18, 20])
    parser.add_argument("--bfs-depth", type=int, default=5, help="admissibility BFS cap (<=6)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "processed" / "seven_edge_strength_seed_2026.json")
    args = parser.parse_args()

    present_paths = _present_seven_edge_paths()
    rng = random.Random(args.seed)

    print("=== 7-edge PDB heuristic strength (WORSTCASE Path 1) ===", flush=True)
    print(f"7-edge PDBs present: {len(present_paths)}/{len(default_edge_pdb_paths_7(root=ROOT))} "
          f"({[p.name for p in present_paths]})", flush=True)
    print(f"{'state':14}{'corner':>7}{'edge6':>7}{'edge7':>7}{'current':>8}{'improved':>9}{'gain':>6}", flush=True)

    rows: list[dict[str, object]] = []
    gains: list[int] = []

    def row(label: str, cube: CubeState) -> dict[str, object]:
        corner = corner_pattern_database_lower_bound(cube)
        edge6 = edge_pattern_database_lower_bound(cube)
        edge7 = _present_seven_edge_h(cube, present_paths)
        current = _components_without_seven(cube)
        improved = max(current, edge7)
        print(
            f"{label:14}{corner:7d}{edge6:7d}{edge7:7d}{current:8d}{improved:9d}{improved - current:6d}",
            flush=True,
        )
        return {
            "state": label,
            "corner": corner,
            "edge6_max": edge6,
            "edge7_max": edge7,
            "current": current,
            "improved": improved,
            "gain": improved - current,
        }

    for depth in args.depths:
        record = row(f"rand_d{depth}", CubeState.from_sequence(_scramble(rng, depth)))
        rows.append(record)
        gains.append(int(record["gain"]))

    superflip = CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)
    sf = row("superflip20", superflip)
    rows.append(sf)
    sf_gain = int(sf["gain"])

    mean_gain = statistics.mean(gains) if gains else 0.0
    print(
        f"\n  superflip: current h={sf['current']} -> improved h={sf['improved']} (+{sf_gain}); "
        f"node factor ~{BRANCHING}^{sf_gain} = {BRANCHING ** sf_gain:.2e}",
        flush=True,
    )
    print(f"  mean h-gain on random deep states: +{mean_gain:.2f}", flush=True)

    # §5.1 admissibility gate (BFS depth <= bfs_depth).
    print(f"\n=== admissibility (BFS depth <= {args.bfs_depth}) ===", flush=True)
    inadmissible = checked = 0
    adm_rng = random.Random(args.seed + 1)
    for length in range(1, args.bfs_depth + 1):
        for _ in range(3):
            cube = CubeState.from_sequence(_scramble(adm_rng, length))
            distance, result = exact_distance_bfs(cube, max_depth=args.bfs_depth)
            if distance is None or result.status != "exact":
                continue
            checked += 1
            improved = max(_components_without_seven(cube), _present_seven_edge_h(cube, present_paths))
            if improved > distance:
                inadmissible += 1
                print(f"  INADMISSIBLE improved h={improved} > d={distance}", flush=True)
    print(f"  checked {checked}: inadmissible={inadmissible}", flush=True)

    summary = {
        "schema_version": 1,
        "seed": args.seed,
        "seven_edge_pdbs_present": [p.name for p in present_paths],
        "seven_edge_pdbs_present_count": len(present_paths),
        "branching_factor": BRANCHING,
        "rows": rows,
        "superflip_gain": sf_gain,
        "superflip_node_factor": BRANCHING ** sf_gain,
        "mean_random_gain": mean_gain,
        "admissibility_checked": checked,
        "admissibility_inadmissible": inadmissible,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}", flush=True)
    return 1 if inadmissible else 0


if __name__ == "__main__":
    raise SystemExit(main())
