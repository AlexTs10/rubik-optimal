"""Native Korf-style optimal 3x3 solver wrapper."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.symmetry import root_symmetry_representative_moves
from rubik_optimal.tables.corner_pdb import corner_pdb_size_bytes, default_corner_pdb_path
from rubik_optimal.tables.edge_pdb import (
    additive_edge_pdb_size_bytes,
    default_additive_edge_pdb_paths,
    default_edge_pdb_paths,
    default_edge_pdb_paths_7,
    edge_pdb_7_size_bytes,
    edge_pdbs_7_available,
    edge_pdb_size_bytes,
)
from rubik_optimal.verify import verify_solution


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _compile(root: Path, compiler: str = "c++", *, with_nissy: bool = False) -> Path:
    source = root / "native" / "optimal_solver" / "optimal_solver.cpp"
    binary = root / "native" / "build" / "optimal_solver"
    if with_nissy:
        binary = root / "native" / "build" / "optimal_solver_nissy"
    binary.parent.mkdir(parents=True, exist_ok=True)
    nissy_root = root / ".codex_external" / "nissy-2.0.8"
    nissy_sources = [
        root / "native" / "optimal_solver" / "nissy_bridge.c",
        nissy_root / "src" / "alg.c",
        nissy_root / "src" / "coord.c",
        nissy_root / "src" / "cube.c",
        nissy_root / "src" / "env.c",
        nissy_root / "src" / "moves.c",
        nissy_root / "src" / "pf.c",
        nissy_root / "src" / "pruning.c",
        nissy_root / "src" / "symcoord.c",
        nissy_root / "src" / "trans.c",
        nissy_root / "src" / "utils.c",
    ]
    if with_nissy:
        missing = [str(path) for path in nissy_sources if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Nissy heuristic bridge sources are missing: {missing}")
    dependencies = [source] + (nissy_sources if with_nissy else [])
    if binary.exists() and binary.stat().st_mtime >= max(path.stat().st_mtime for path in dependencies):
        return binary
    if not with_nissy:
        # -O3 + native tuning for the per-node hot loop. -march=native is a
        # portable-on-this-host optimization; if the toolchain rejects it (e.g.
        # an unusual cross-compiler) we transparently fall back to plain -O3.
        base_flags = ["-std=c++17", "-O3", "-DNDEBUG", "-funroll-loops"]
        native_flags = base_flags + ["-march=native"]
        try:
            subprocess.run(
                [compiler, *native_flags, str(source), "-o", str(binary)],
                cwd=root,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            subprocess.run(
                [compiler, *base_flags, str(source), "-o", str(binary)],
                cwd=root,
                check=True,
            )
        return binary
    object_dir = root / "native" / "build" / "nissy_bridge_objects"
    object_dir.mkdir(parents=True, exist_ok=True)
    objects: list[Path] = []
    cc = "cc"
    include_flags = [
        "-I",
        str(root / "native" / "optimal_solver"),
        "-I",
        str(nissy_root / "src"),
    ]
    for index, c_source in enumerate(nissy_sources):
        obj = object_dir / f"{index:02d}_{c_source.stem}.o"
        if not obj.exists() or obj.stat().st_mtime < c_source.stat().st_mtime:
            subprocess.run(
                [cc, "-std=c11", "-O3", "-DNDEBUG", *include_flags, "-c", str(c_source), "-o", str(obj)],
                cwd=root,
                check=True,
            )
        objects.append(obj)
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O3",
            "-DNDEBUG",
            "-DRUBIK_WITH_NISSY_BRIDGE",
            *include_flags,
            str(source),
            *(str(obj) for obj in objects),
            "-lpthread",
            "-o",
            str(binary),
        ],
        cwd=root,
        check=True,
    )
    return binary


def _csv(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def _root_move_mask_csv(cube: CubeState) -> str | None:
    representatives = root_symmetry_representative_moves(cube)
    if len(representatives) >= len(ALL_MOVES):
        return None
    return ",".join(representatives)


def solve_korf_native_optimal(
    cube: CubeState,
    *,
    max_depth: int = 20,
    timeout_seconds: float = 300.0,
    node_limit: int = 0,
    transposition_entries: int = 0,
    threads: int = 1,
    split_depth: int = 3,
    child_order: str = "heuristic-desc",
    dual_heuristic: bool = False,
    nissy_heuristic: bool = False,
    nissy_axis_transforms: bool = True,
    nissy_data_dir: Path | None = None,
    source_sequence: list[str] | tuple[str, ...] | None = None,
    upper_solution: list[str] | tuple[str, ...] | None = None,
    upper_bound_proof_strategy: str = "single-bound",
    additive_edge_pdbs: bool = False,
    use_seven_edge_pdbs: bool = False,
    root_symmetry_prune: bool = False,
    symmetry_transpositions: bool = False,
    full_symmetry_transpositions: bool = False,
    compact_transpositions: bool = False,
    root: Path | None = None,
    compiler: str = "c++",
) -> SolverResult:
    """Run the native full-cube IDA* solver.

    A returned `exact` result is an optimal HTM solution for the input state.
    Timeout and lower-bound statuses do not prove the distance.

    When ``root_symmetry_prune`` forwards a root move mask, the binary reports
    the conditional status ``exact_under_root_mask``.  This wrapper restores
    ``exact`` only because it derived that mask itself from the full
    48-element whole-cube symmetry stabilizer of the input
    (:func:`rubik_optimal.symmetry.root_symmetry_representative_moves`), which
    makes masked-tree optimality imply unconditional optimality; the upgrade
    is recorded in ``notes``.  An ``exact_under_root_mask`` status arriving
    without an in-wrapper derived mask is passed through unchanged and is
    never marked verified.
    """

    root = root or repository_root()
    corner_pdb = default_corner_pdb_path(root=root)
    edge_pdbs = default_edge_pdb_paths(root=root)
    # Optional 7-edge PDBs (WORSTCASE Path 1): strictly opt-in via
    # use_seven_edge_pdbs=True (and only when all are present), so a default
    # invocation uses exactly the frozen 6-edge thesis configuration. The native
    # engine folds them into the same admissible MAX via its subset-size dispatch.
    seven_edge_paths = (
        default_edge_pdb_paths_7(root=root) if use_seven_edge_pdbs and edge_pdbs_7_available(default_edge_pdb_paths_7(root=root)) else ()
    )
    additive_edge_paths = default_additive_edge_pdb_paths(root=root) if additive_edge_pdbs else ()
    if not corner_pdb.exists():
        return SolverResult(
            solver_name="korf_native_optimal",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=0,
            status="failed",
            is_verified=False,
            notes=f"missing required corner PDB: {corner_pdb}",
        )
    missing_edges = [str(path) for path in edge_pdbs if not path.exists()]
    if missing_edges:
        return SolverResult(
            solver_name="korf_native_optimal",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=corner_pdb_size_bytes(corner_pdb),
            status="failed",
            is_verified=False,
            notes=f"missing required edge PDBs: {missing_edges}",
        )
    missing_additive_edges = [str(path) for path in additive_edge_paths if not path.exists()]
    if missing_additive_edges:
        return SolverResult(
            solver_name="korf_native_optimal",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.0,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=corner_pdb_size_bytes(corner_pdb) + edge_pdb_size_bytes(edge_pdbs),
            status="failed",
            is_verified=False,
            notes=f"missing requested additive edge PDBs: {missing_additive_edges}",
        )

    begin = time.perf_counter()
    binary = _compile(root, compiler, with_nissy=nissy_heuristic)
    nissy_data_dir = nissy_data_dir or root / ".codex_external" / "nissy_data"
    command = [
        str(binary),
        "--corner-pdb",
        str(corner_pdb),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
        "--max-depth",
        str(max_depth),
        "--timeout",
        str(timeout_seconds),
        "--node-limit",
        str(node_limit),
        "--tt-entries",
        str(transposition_entries),
        "--threads",
        str(max(1, threads)),
        "--split-depth",
        str(max(1, split_depth)),
        "--child-order",
        child_order,
    ]
    if dual_heuristic:
        command.append("--dual-heuristic")
    if nissy_heuristic:
        command.extend(["--nissy-heuristic", "--nissy-data", str(nissy_data_dir)])
        if nissy_axis_transforms:
            command.append("--nissy-axis-transforms")
        if source_sequence:
            command.extend(["--nissy-sequence", " ".join(source_sequence)])
    if upper_solution:
        command.extend(["--upper-solution", " ".join(upper_solution)])
        command.extend(["--upper-bound-proof-strategy", upper_bound_proof_strategy])
    root_move_mask = _root_move_mask_csv(cube) if root_symmetry_prune else None
    if root_move_mask is not None:
        command.extend(["--root-move-mask", root_move_mask])
    if symmetry_transpositions:
        command.append("--symmetry-transpositions")
    if full_symmetry_transpositions:
        command.append("--full-symmetry-transpositions")
    if compact_transpositions:
        command.append("--compact-transpositions")
    for path in edge_pdbs:
        command.extend(["--edge-pdb", str(path)])
    for path in seven_edge_paths:
        command.extend(["--edge-pdb", str(path)])
    for path in additive_edge_paths:
        command.extend(["--additive-edge-pdb", str(path)])
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    runtime_seconds = time.perf_counter() - begin
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "solution_moves": [],
            "solution_length": None,
            "expanded_nodes": None,
            "generated_nodes": None,
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }

    solution = list(payload.get("solution_moves") or [])
    status = str(payload.get("status", "failed"))
    root_mask_note = ""
    if status == "exact_under_root_mask" and root_move_mask is not None:
        # The binary reports conditional exactness whenever --root-move-mask is
        # active.  This wrapper derived that exact mask itself from the full
        # 48-element whole-cube symmetry stabilizer of the input
        # (root_symmetry_representative_moves): every excluded first move has a
        # stabilizer image inside the mask, so a shortest solution over the
        # masked root tree is a shortest solution outright.  Only this
        # in-wrapper certified derivation justifies restoring the
        # unconditional "exact" status; any other exact_under_root_mask result
        # is passed through unchanged.
        status = "exact"
        root_mask_note = (
            "native status exact_under_root_mask upgraded to exact: root move mask "
            "derived in-wrapper from the 48-symmetry stabilizer via "
            "root_symmetry_representative_moves, so masked-tree optimality implies "
            "unconditional optimality; "
        )
    verification = verify_solution(cube, solution) if status == "exact" else None
    return SolverResult(
        solver_name="korf_native_optimal",
        input_state=cube.to_facelets(),
        solution_moves=solution,
        solution_length=int(payload["solution_length"]) if payload.get("solution_length") is not None else None,
        metric="HTM",
        runtime_seconds=float(payload.get("runtime_seconds") or runtime_seconds),
        expanded_nodes=int(payload["expanded_nodes"]) if payload.get("expanded_nodes") is not None else None,
        generated_nodes=int(payload["generated_nodes"]) if payload.get("generated_nodes") is not None else None,
        table_bytes=(
            corner_pdb_size_bytes(corner_pdb)
            + edge_pdb_size_bytes(edge_pdbs)
            + edge_pdb_7_size_bytes(seven_edge_paths)
            + additive_edge_pdb_size_bytes(additive_edge_paths)
        ),
        status=status,
        is_verified=bool(status == "exact" and verification and verification.ok),
        notes=(
            f"{root_mask_note}"
            f"native C++ IDA* with corner+edge PDB heuristic; "
            f"initial_lower_bound={payload.get('initial_lower_bound')}; "
            f"final_bound={payload.get('final_bound')}; "
            f"edge_pdb_count={payload.get('edge_pdb_count')}; "
            f"additive_edge_pdb_count={payload.get('additive_edge_pdb_count')}; "
            f"threads={payload.get('threads')}; "
            f"split_depth={payload.get('split_depth')}; "
            f"split_tasks={payload.get('split_tasks')}; "
            f"child_order={payload.get('child_order')}; "
            f"dual_heuristic={payload.get('dual_heuristic')}; "
            f"nissy_heuristic={payload.get('nissy_heuristic')}; "
            f"nissy_axis_transforms={payload.get('nissy_axis_transforms')}; "
            f"upper_solution_verified={payload.get('upper_solution_verified')}; "
            f"exact_certified_by_upper_bound={payload.get('exact_certified_by_upper_bound')}; "
            f"upper_bound_solution_length={payload.get('upper_bound_solution_length')}; "
            f"upper_bound_proof_strategy={payload.get('upper_bound_proof_strategy')}; "
            f"upper_bound_proof_search_bound={payload.get('upper_bound_proof_search_bound')}; "
            f"upper_bound_proof_exhaustive={payload.get('upper_bound_proof_exhaustive')}; "
            f"upper_bound_shorter_solution_found={payload.get('upper_bound_shorter_solution_found')}; "
            f"root_symmetry_prune={root_symmetry_prune}; "
            f"root_move_count={payload.get('root_move_count')}; "
            f"root_move_mask_enabled={payload.get('root_move_mask_enabled')}; "
            f"symmetry_transpositions={payload.get('symmetry_transpositions')}; "
            f"symmetry_rotation_count={payload.get('symmetry_rotation_count')}; "
            f"full_symmetry_transpositions={payload.get('full_symmetry_transpositions')}; "
            f"symmetry_transform_count={payload.get('symmetry_transform_count')}; "
            f"compact_transpositions={payload.get('compact_transpositions')}; "
            f"tt_entry_limit={payload.get('tt_entry_limit')}; "
            f"tt_hits={payload.get('tt_hits')}; "
            f"tt_capacity_skips={payload.get('tt_capacity_skips')}; "
            f"return_code={completed.returncode}; error={payload.get('error', '')}"
        ),
    )
