#!/usr/bin/env python
"""Probe superflip distances in larger edge-subset projections.

This is a lightweight decision tool for WORSTCASE Path 2.  The complete 8+ edge
PDBs are too large for the existing byte-indexed generator, so this script does
not build a table.  Instead it runs an exact bidirectional BFS in the projected
state graph for one chosen subset and target state, stopping once the frontiers
meet or the configured depth cap is exhausted.

The result answers a narrow design question before committing to a large native
build: does increasing the edge subset size actually raise the projected
superflip distance above the 6/7-edge value of 8?
"""

from __future__ import annotations

import argparse
from itertools import combinations
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from math import comb, factorial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.coordinates.permutation import rank_permutation
from rubik_optimal.cube import EDGE_COLORS, CubeState
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.symmetry import CUBE_ROTATIONS


@dataclass(frozen=True)
class ProbeResult:
    subset_edges: tuple[int, ...]
    subset_size: int
    projected_state_count: int
    target_label: str
    found_distance: int | None
    proved_greater_than: int | None
    max_depth: int
    elapsed_seconds: float
    start_seen: int
    target_seen: int
    start_frontier: int
    target_frontier: int


def _rank_combination(positions: list[int], subset_size: int) -> int:
    rank = 0
    next_value = 0
    for index, position in enumerate(positions):
        for value in range(next_value, position):
            rank += comb(12 - value - 1, subset_size - index - 1)
        next_value = position + 1
    return rank


def edge_subset_coord(cube: CubeState, subset_edges: tuple[int, ...]) -> int:
    """Return the full edge-subset projection coordinate for any subset size."""

    subset_size = len(subset_edges)
    if not 1 <= subset_size <= 12:
        raise ValueError(f"subset size must be in [1, 12], got {subset_size}")
    if len(set(subset_edges)) != subset_size or any(edge < 0 or edge >= 12 for edge in subset_edges):
        raise ValueError("subset edges must be distinct ids in [0, 11]")

    edge_to_subset_index = {edge: index for index, edge in enumerate(subset_edges)}
    positions: list[int] = []
    permutation: list[int] = []
    orientation = 0
    for position, edge in enumerate(cube.ep):
        subset_index = edge_to_subset_index.get(edge)
        if subset_index is None:
            continue
        orientation_index = len(positions)
        positions.append(position)
        permutation.append(subset_index)
        if cube.eo[position] & 1:
            orientation |= 1 << orientation_index
    if len(positions) != subset_size:
        raise ValueError("cube state does not contain every requested subset edge")
    return (
        _rank_combination(positions, subset_size) * factorial(subset_size)
        + rank_permutation(permutation)
    ) * (1 << subset_size) + orientation


def _superflip() -> CubeState:
    return CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)


def projected_state_count(subset_size: int) -> int:
    return comb(12, subset_size) * factorial(subset_size) * (1 << subset_size)


def _rotation_edge_maps() -> tuple[tuple[int, ...], ...]:
    edge_by_color_set = {frozenset(colors): index for index, colors in enumerate(EDGE_COLORS)}
    maps: list[tuple[int, ...]] = []
    for rotation in CUBE_ROTATIONS:
        edge_map: list[int] = []
        for colors in EDGE_COLORS:
            mapped = frozenset(rotation.face_map[color] for color in colors)
            edge_map.append(edge_by_color_set[mapped])
        maps.append(tuple(edge_map))
    return tuple(maps)


ROTATION_EDGE_MAPS = _rotation_edge_maps()


def rotational_subset_representatives(subset_size: int) -> tuple[tuple[int, ...], ...]:
    """Return one representative per 24-rotation orbit of edge subsets."""

    representatives: set[tuple[int, ...]] = set()
    for subset in combinations(range(12), subset_size):
        orbit = {
            tuple(sorted(edge_map[edge] for edge in subset))
            for edge_map in ROTATION_EDGE_MAPS
        }
        representatives.add(min(orbit))
    return tuple(sorted(representatives))


def bidirectional_projected_distance(
    *,
    subset_edges: tuple[int, ...],
    target: CubeState,
    target_label: str,
    max_depth: int,
    progress: bool = False,
) -> ProbeResult:
    """Return the exact projected distance if found within ``max_depth``."""

    start_time = time.perf_counter()
    start = CubeState.solved()
    start_coord = edge_subset_coord(start, subset_edges)
    target_coord = edge_subset_coord(target, subset_edges)
    if start_coord == target_coord:
        return ProbeResult(
            subset_edges=subset_edges,
            subset_size=len(subset_edges),
            projected_state_count=projected_state_count(len(subset_edges)),
            target_label=target_label,
            found_distance=0,
            proved_greater_than=None,
            max_depth=max_depth,
            elapsed_seconds=time.perf_counter() - start_time,
            start_seen=1,
            target_seen=1,
            start_frontier=1,
            target_frontier=1,
        )

    start_frontier = [start]
    target_frontier = [target]
    start_seen = {start_coord}
    target_seen = {target_coord}
    start_depth = 0
    target_depth = 0

    def expand(frontier: list[CubeState], own_seen: set[int], other_seen: set[int]) -> tuple[list[CubeState], bool]:
        next_frontier: list[CubeState] = []
        for cube in frontier:
            for move in ALL_MOVES:
                child = cube.apply_move(move)
                coord = edge_subset_coord(child, subset_edges)
                if coord in other_seen:
                    return next_frontier, True
                if coord not in own_seen:
                    own_seen.add(coord)
                    next_frontier.append(child)
        return next_frontier, False

    while start_depth + target_depth < max_depth:
        expand_start = len(start_frontier) <= len(target_frontier)
        if progress:
            side = "start" if expand_start else "target"
            print(
                f"subset={len(subset_edges)} depths={start_depth}/{target_depth} "
                f"frontiers={len(start_frontier)}/{len(target_frontier)} "
                f"seen={len(start_seen)}/{len(target_seen)} expand={side}",
                flush=True,
            )
        if expand_start:
            start_frontier, found = expand(start_frontier, start_seen, target_seen)
            start_depth += 1
        else:
            target_frontier, found = expand(target_frontier, target_seen, start_seen)
            target_depth += 1
        if found:
            return ProbeResult(
                subset_edges=subset_edges,
                subset_size=len(subset_edges),
                projected_state_count=projected_state_count(len(subset_edges)),
                target_label=target_label,
                found_distance=start_depth + target_depth,
                proved_greater_than=None,
                max_depth=max_depth,
                elapsed_seconds=time.perf_counter() - start_time,
                start_seen=len(start_seen),
                target_seen=len(target_seen),
                start_frontier=len(start_frontier),
                target_frontier=len(target_frontier),
            )

    return ProbeResult(
        subset_edges=subset_edges,
        subset_size=len(subset_edges),
        projected_state_count=projected_state_count(len(subset_edges)),
        target_label=target_label,
        found_distance=None,
        proved_greater_than=max_depth,
        max_depth=max_depth,
        elapsed_seconds=time.perf_counter() - start_time,
        start_seen=len(start_seen),
        target_seen=len(target_seen),
        start_frontier=len(start_frontier),
        target_frontier=len(target_frontier),
    )


def _parse_subset_size(value: str) -> int:
    size = int(value)
    if not 1 <= size <= 12:
        raise argparse.ArgumentTypeError("subset sizes must be in [1, 12]")
    return size


def _parse_subset_edges(value: str) -> tuple[int, ...]:
    try:
        subset = tuple(int(part) for part in value.split(",") if part != "")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("subset must be comma-separated edge ids") from exc
    if not 1 <= len(subset) <= 12:
        raise argparse.ArgumentTypeError("subset must contain 1..12 edge ids")
    if len(set(subset)) != len(subset) or any(edge < 0 or edge >= 12 for edge in subset):
        raise argparse.ArgumentTypeError("subset edges must be distinct ids in [0, 11]")
    return subset


def requested_subsets(
    *,
    subset_sizes: tuple[int, ...],
    explicit_subsets: tuple[tuple[int, ...], ...],
    all_subsets_sizes: tuple[int, ...],
    orbit_subsets_sizes: tuple[int, ...],
) -> tuple[tuple[int, ...], ...]:
    mode_count = sum(bool(mode) for mode in (explicit_subsets, subset_sizes, all_subsets_sizes, orbit_subsets_sizes))
    if mode_count > 1:
        raise ValueError("subset selection modes cannot be combined")
    if explicit_subsets:
        return explicit_subsets
    if orbit_subsets_sizes:
        return tuple(
            subset
            for size in orbit_subsets_sizes
            for subset in rotational_subset_representatives(size)
        )
    if all_subsets_sizes:
        return tuple(
            subset
            for size in all_subsets_sizes
            for subset in combinations(range(12), size)
        )
    sizes = subset_sizes or (6, 7, 8, 9)
    return tuple(tuple(range(size)) for size in sizes)


def _compile_native(root: Path, compiler: str = "c++") -> Path:
    source = root / "native" / "edge_projection_probe" / "edge_projection_probe.cpp"
    binary = root / "native" / "build" / "edge_projection_probe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    if binary.exists() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O3",
            "-DNDEBUG",
            str(source),
            "-o",
            str(binary),
        ],
        cwd=root,
        check=True,
    )
    return binary


def native_projected_distance(
    *,
    subset_edges: tuple[int, ...],
    max_depth: int,
    progress: bool = False,
    compiler: str = "c++",
) -> ProbeResult:
    binary = _compile_native(ROOT, compiler)
    command = [
        str(binary),
        "--subset",
        ",".join(str(edge) for edge in subset_edges),
        "--max-depth",
        str(max_depth),
    ]
    if progress:
        command.append("--progress")
    completed = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
    if progress and completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    payload = json.loads(completed.stdout)
    return ProbeResult(
        subset_edges=tuple(int(edge) for edge in payload["subset_edges"]),
        subset_size=int(payload["subset_size"]),
        projected_state_count=int(payload["projected_state_count"]),
        target_label="superflip",
        found_distance=(
            int(payload["found_distance"]) if payload.get("found_distance") is not None else None
        ),
        proved_greater_than=(
            int(payload["proved_greater_than"]) if payload.get("proved_greater_than") is not None else None
        ),
        max_depth=int(payload["max_depth"]),
        elapsed_seconds=float(payload["elapsed_seconds"]),
        start_seen=int(payload["start_seen"]),
        target_seen=int(payload["target_seen"]),
        start_frontier=int(payload["start_frontier"]),
        target_frontier=int(payload["target_frontier"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset-size", type=_parse_subset_size, action="append", dest="subset_sizes")
    parser.add_argument("--subset", type=_parse_subset_edges, action="append", dest="explicit_subsets")
    parser.add_argument(
        "--all-subsets-size",
        type=_parse_subset_size,
        action="append",
        dest="all_subsets_sizes",
        help="Enumerate every subset of this size; intended for native subset-shape sweeps.",
    )
    parser.add_argument(
        "--rotation-orbit-subsets-size",
        type=_parse_subset_size,
        action="append",
        dest="orbit_subsets_sizes",
        help="Enumerate one edge-subset representative per 24-rotation orbit.",
    )
    parser.add_argument("--max-depth", type=int, default=11)
    parser.add_argument("--backend", choices=("python", "native"), default="python")
    parser.add_argument("--compiler", default="c++")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "edge_projection_superflip_probe_seed_2026.json",
    )
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    subsets = requested_subsets(
        subset_sizes=tuple(args.subset_sizes or ()),
        explicit_subsets=tuple(args.explicit_subsets or ()),
        all_subsets_sizes=tuple(args.all_subsets_sizes or ()),
        orbit_subsets_sizes=tuple(args.orbit_subsets_sizes or ()),
    )
    target = _superflip()
    results: list[ProbeResult] = []
    for subset_edges in subsets:
        if args.backend == "native":
            result = native_projected_distance(
                subset_edges=subset_edges,
                max_depth=args.max_depth,
                progress=args.progress,
                compiler=args.compiler,
            )
        else:
            result = bidirectional_projected_distance(
                subset_edges=subset_edges,
                target=target,
                target_label="superflip",
                max_depth=args.max_depth,
                progress=args.progress,
            )
        results.append(result)
        status = (
            f"distance={result.found_distance}"
            if result.found_distance is not None
            else f">{result.proved_greater_than}"
        )
        print(
            f"subset={','.join(str(edge) for edge in subset_edges)} "
            f"states={result.projected_state_count} {status} "
            f"elapsed={result.elapsed_seconds:.3f}s",
            flush=True,
        )

    payload = {
        "schema_version": 1,
        "target": "superflip",
        "metric": "HTM",
        "algorithm": "bidirectional BFS in full edge-subset projection",
        "backend": args.backend,
        "max_depth": args.max_depth,
        "subset_count": len(subsets),
        "results": [asdict(result) for result in results],
        "notes": (
            "This is design evidence for WORSTCASE Path 2. It does not build a runtime heuristic table; "
            "it identifies the first edge projection size that raises the projected superflip distance."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
