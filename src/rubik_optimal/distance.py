"""Distance recognition with explicit result kinds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .cube import CubeState
from .search.bfs import exact_distance_bfs
from .search.heuristics import combined_table_lower_bound
from .search.ida_star import ida_star_solve
from .tables.h48 import DEFAULT_H48_SOLVER


@dataclass(frozen=True)
class DistanceResult:
    distance_value: int | None
    kind: str
    method: str
    runtime_seconds: float
    expanded_nodes: int
    proof_notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def recognize_distance(
    cube: CubeState,
    *,
    bfs_depth: int = 5,
    ida_depth: int = 8,
    timeout_seconds: float = 5.0,
    native_optimal: bool = False,
    h48_native: bool = False,
    h48_solver: str = DEFAULT_H48_SOLVER,
    h48_profile: str = "thesis",
    h48_table_path: Path | None = None,
    threads: int = 8,
    h48_skip_table_check: bool = False,
    h48_preload_table: bool = False,
    h48_auto_min_depth: bool = False,
) -> DistanceResult:
    code, message = cube.verify_physical()
    if code != 0:
        return DistanceResult(None, "invalid_state", "validity", 0.0, 0, message)
    bfs_distance, bfs_result = exact_distance_bfs(cube, max_depth=bfs_depth)
    if bfs_distance is not None:
        return DistanceResult(
            bfs_distance,
            "exact_distance",
            f"bfs_depth_{bfs_depth}",
            0.0,
            bfs_result.expanded_nodes,
            "Breadth-first search exhaustively proves the shallow distance",
        )
    if native_optimal:
        from .solvers.optimal_native import solve_korf_native_optimal

        optimal = solve_korf_native_optimal(cube, max_depth=20, timeout_seconds=timeout_seconds)
        if optimal.status == "exact" and optimal.solution_length is not None:
            return DistanceResult(
                optimal.solution_length,
                "exact_distance",
                "native_corner_edge_pdb_ida_star_depth_20",
                optimal.runtime_seconds,
                optimal.expanded_nodes or 0,
                "Native full-cube IDA* with complete corner and edge PDB lower bounds completed",
            )
        lower = combined_table_lower_bound(cube)
        return DistanceResult(
            lower,
            "lower_bound" if optimal.status != "timeout" else "unknown_timeout",
            "native_corner_edge_pdb_ida_star_depth_20",
            optimal.runtime_seconds,
            optimal.expanded_nodes or 0,
            f"Native optimal search did not complete exactly; solver_status={optimal.status}; {optimal.notes}",
        )
    if h48_native:
        from .solvers.h48_native import solve_h48_native_optimal

        optimal = solve_h48_native_optimal(
            cube,
            source_sequence=None,
            solver=h48_solver,
            profile=h48_profile,
            table_path=h48_table_path,
            timeout_seconds=timeout_seconds,
            threads=threads,
            max_depth=20,
            skip_table_check=h48_skip_table_check,
            preload_table=h48_preload_table,
            auto_min_depth=h48_auto_min_depth,
        )
        if optimal.status == "exact" and optimal.solution_length is not None and optimal.is_verified:
            return DistanceResult(
                optimal.solution_length,
                "exact_distance",
                f"h48_native_{h48_solver}_depth_20",
                optimal.runtime_seconds,
                optimal.expanded_nodes or 0,
                f"H48-native exact state-input search completed; {optimal.notes}",
            )
        lower = combined_table_lower_bound(cube)
        return DistanceResult(
            lower,
            "unknown_timeout" if optimal.status == "timeout" else "lower_bound",
            f"h48_native_{h48_solver}_depth_20",
            optimal.runtime_seconds,
            optimal.expanded_nodes or 0,
            f"H48-native exact state-input search did not complete exactly; solver_status={optimal.status}; {optimal.notes}",
        )
    ida = ida_star_solve(
        cube,
        max_depth=ida_depth,
        timeout_seconds=timeout_seconds,
        heuristic=combined_table_lower_bound,
    )
    if ida.solution is not None:
        return DistanceResult(
            len(ida.solution),
            "exact_distance",
            f"ida_star_depth_{ida_depth}",
            ida.runtime_seconds,
            ida.expanded_nodes,
            "IDA* with admissible lower bound completed",
        )
    distance_value = combined_table_lower_bound(cube)
    if ida.status == "timeout":
        return DistanceResult(
            distance_value,
            "unknown_timeout",
            "combined_table_lower_bound",
            ida.runtime_seconds,
            bfs_result.expanded_nodes + ida.expanded_nodes,
            (
                "IDA* exhausted its time/node budget before proving optimality; "
                "the reported value is only an admissible lower bound, "
                "not the exact distance; "
                f"ida_status={ida.status}; {ida.notes}"
            ),
        )
    return DistanceResult(
        distance_value,
        "lower_bound",
        "combined_table_lower_bound",
        ida.runtime_seconds,
        bfs_result.expanded_nodes + ida.expanded_nodes,
        (
            "Completed depth-bounded IDA* search found no shorter solution within "
            "the configured depth; the reported value is an admissible lower bound, "
            "not a proven exact distance; "
            f"ida_status={ida.status}; {ida.notes}"
        ),
    )
