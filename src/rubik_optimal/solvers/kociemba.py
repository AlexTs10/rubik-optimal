"""Native scoped Kociemba-style solver plus optional package adapter.

Both Kociemba paths intentionally report verified solves as non_exact. They
prove that the returned sequence solves the input, but they do not prove global
HTM optimality for that input.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import sys
import time
from array import array
from functools import lru_cache
from pathlib import Path

from rubik_optimal.coordinates import (
    CORNER_ORIENTATION_SPEC,
    EDGE_ORIENTATION_SPEC,
    PHASE2_MOVE_TABLE_SPECS,
    UD_SLICE_SPEC,
)
from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, PHASE2_MOVES, parse_sequence, same_face
from rubik_optimal.search.heuristics import (
    coordinate_pruning_table_bytes,
    phase2_pruning_table_bytes,
)
from rubik_optimal.search.ida_star import IDAStarCandidatesResult, IDAStarResult
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.tables.move_tables import build_move_table
from rubik_optimal.tables.pruning_tables import build_pruning_table
from rubik_optimal.verify import verify_solution

# ---------------------------------------------------------------------------
# Deterministic on-disk cache for the Kociemba coordinate move/pruning tables.
#
# Building these move + pruning tables in-memory costs several seconds (the
# phase-2 8! permutation projections dominate), and it was being repeated in
# every fresh process. We persist them to a deterministic JSON cache under
# data/generated/ so a second process loads the tables (cheap file reads)
# instead of recomputing them. Determinism is enforced with a per-file SHA-256
# checksum recorded in a sidecar manifest: a file is only trusted if its bytes
# hash to the recorded value AND its declared structure (table_name, kind,
# moves order, schema, domain size) matches the spec we expect. If a cache
# entry is missing, structurally incompatible, or fails its checksum, the
# table is regenerated in-memory and re-saved with a fresh checksum.
#
# The in-process lru_cache layer below still memoises the parsed tables so a
# single process never reads or rebuilds them more than once.
# ---------------------------------------------------------------------------

_TABLE_SCHEMA_VERSION = 1
_CACHE_PROFILE = "thesis"
_CACHE_SEED = 2026
_CACHE_MANIFEST_NAME = "kociemba_coordinate_cache_manifest.json"


def _cache_root() -> Path:
    """Return the directory holding the generated coordinate-table cache.

    Honours RUBIK_OPTIMAL_DATA_DIR / RUBIK_GENERATED_DATA_DIR if set (so the
    cache location can be redirected, e.g. in tests); otherwise defaults to
    the repository's data/generated directory resolved relative to this file.
    """

    override = os.environ.get("RUBIK_OPTIMAL_DATA_DIR") or os.environ.get(
        "RUBIK_GENERATED_DATA_DIR"
    )
    if override:
        return Path(override).expanduser()
    # solvers/kociemba.py -> rubik_optimal -> src -> repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "generated"


def _cache_table_path(spec_name: str, kind: str) -> Path:
    return _cache_root() / f"{_CACHE_PROFILE}_seed_{_CACHE_SEED}_{spec_name}_{kind}.json"


def _manifest_path() -> Path:
    return _cache_root() / _CACHE_MANIFEST_NAME


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest() -> dict[str, str]:
    path = _manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    checksums = payload.get("checksums")
    if not isinstance(checksums, dict):
        return {}
    return {str(key): str(value) for key, value in checksums.items()}


def _write_manifest(checksums: dict[str, str]) -> None:
    path = _manifest_path()
    payload = {
        "schema_version": _TABLE_SCHEMA_VERSION,
        "profile": _CACHE_PROFILE,
        "seed": _CACHE_SEED,
        "description": (
            "SHA-256 checksums of the cached Kociemba coordinate move/pruning "
            "tables consumed by rubik_optimal.solvers.kociemba. Used to verify "
            "the on-disk cache is the deterministic table set before trusting it."
        ),
        "checksums": dict(sorted(checksums.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _expected_moves(spec, *, phase2: bool) -> tuple[str, ...]:
    declared = getattr(spec, "moves", None)
    if declared is not None:
        return tuple(declared)
    return PHASE2_MOVES if phase2 else ALL_MOVES


def _load_cached_rows(
    spec,
    kind: str,
    *,
    phase2: bool,
    manifest: dict[str, str],
) -> list | None:
    """Load and validate a cached table file, or return None if untrusted.

    A cache hit requires: the file exists, its raw bytes match the SHA-256
    recorded in the manifest, and its declared metadata (schema, table_name,
    kind, move order, domain size) matches what the solver expects. This
    guarantees the loaded numbers are the same deterministic table the solver
    would have computed in-memory.
    """

    path = _cache_table_path(spec.name, kind)
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    digest = _sha256_bytes(raw)
    expected_digest = manifest.get(path.name)
    if expected_digest is not None and digest != expected_digest:
        return None  # checksum mismatch -> distrust, force regeneration

    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _TABLE_SCHEMA_VERSION:
        return None
    if payload.get("table_name") != spec.name or payload.get("table_kind") != kind:
        return None
    if tuple(payload.get("moves") or ()) != _expected_moves(spec, phase2=phase2):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    if len(rows) != int(spec.domain_size):
        return None

    # When the manifest had no entry for this file (e.g. pre-existing artifacts),
    # adopt the validated file's checksum so subsequent loads are checksum-gated.
    if expected_digest is None:
        manifest[path.name] = digest
    return rows


def _save_cached_rows(
    spec,
    kind: str,
    rows: list,
    *,
    phase2: bool,
    manifest: dict[str, str],
) -> None:
    path = _cache_table_path(spec.name, kind)
    payload = {
        "schema_version": _TABLE_SCHEMA_VERSION,
        "table_name": spec.name,
        "table_kind": kind,
        "profile": _CACHE_PROFILE,
        "seed": _CACHE_SEED,
        "moves": list(_expected_moves(spec, phase2=phase2)),
        "rows": rows,
    }
    # Compact, key-sorted serialisation makes the on-disk bytes deterministic
    # so the recorded checksum is stable across regenerations.
    data = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    manifest[path.name] = _sha256_bytes(data)


def _coordinate_tables_for_specs(
    specs,
    *,
    phase2: bool,
) -> tuple[tuple[list[list[int]], ...], tuple[tuple[int, ...], ...]]:
    """Obtain move + pruning tables for ``specs``, preferring the disk cache.

    Each table is loaded from its checksummed cache file when available and
    valid; otherwise it is regenerated in-memory and written back to the cache.
    The manifest is rewritten only if anything was generated or newly adopted.
    """

    moves = PHASE2_MOVES if phase2 else ALL_MOVES
    manifest = _read_manifest()
    manifest_before = dict(manifest)

    move_tables: list[list[list[int]]] = []
    pruning_tables: list[tuple[int, ...]] = []

    for spec in specs:
        move_table = _load_cached_rows(spec, "move_table", phase2=phase2, manifest=manifest)
        if move_table is None:
            move_table = build_move_table(spec, moves=moves)
            _save_cached_rows(spec, "move_table", move_table, phase2=phase2, manifest=manifest)

        pruning_rows = _load_cached_rows(spec, "pruning_table", phase2=phase2, manifest=manifest)
        if pruning_rows is None:
            pruning_rows = build_pruning_table(move_table, solved_coord=spec.solved_coord)
            _save_cached_rows(spec, "pruning_table", pruning_rows, phase2=phase2, manifest=manifest)

        move_tables.append(move_table)
        pruning_tables.append(tuple(pruning_rows))

    # Persist manifest when tables were (re)generated or pre-existing files were
    # adopted (manifest grew/changed), so the checksum gate is in force next time.
    if manifest != manifest_before:
        try:
            _write_manifest(manifest)
        except OSError:
            pass  # read-only cache dir: solving still works, just no checksum gate

    return tuple(move_tables), tuple(pruning_tables)


def _native_table_bytes() -> int:
    return coordinate_pruning_table_bytes() + phase2_pruning_table_bytes()


@lru_cache(maxsize=1)
def _phase1_coordinate_tables() -> tuple[
    tuple[list[list[int]], ...],
    tuple[tuple[int, ...], ...],
]:
    return _coordinate_tables_for_specs(
        (CORNER_ORIENTATION_SPEC, EDGE_ORIENTATION_SPEC, UD_SLICE_SPEC),
        phase2=False,
    )


@lru_cache(maxsize=1)
def _phase2_coordinate_tables() -> tuple[
    tuple[list[list[int]], ...],
    tuple[tuple[int, ...], ...],
]:
    return _coordinate_tables_for_specs(PHASE2_MOVE_TABLE_SPECS, phase2=True)


def is_kociemba_phase1_goal(cube: CubeState) -> bool:
    return (
        CORNER_ORIENTATION_SPEC.encode(cube) == CORNER_ORIENTATION_SPEC.solved_coord
        and EDGE_ORIENTATION_SPEC.encode(cube) == EDGE_ORIENTATION_SPEC.solved_coord
        and UD_SLICE_SPEC.encode(cube) == UD_SLICE_SPEC.solved_coord
    )


def _phase1_lower_bound_from_tables(coord: tuple[int, int, int], pruning_tables: tuple[tuple[int, ...], ...]) -> int:
    return max(pruning_tables[index][coord[index]] for index in range(3))


def _phase2_lower_bound_from_tables(coord: tuple[int, ...], pruning_tables: tuple[tuple[int, ...], ...]) -> int:
    return max(pruning_tables[index][coord[index]] for index in range(len(coord)))


# ---------------------------------------------------------------------------
# Optional exact phase-1 heuristic backed by the symmetry-reduced distance
# table (Kociemba's FlipUDSlice x twist 16-symmetry reduction).
#
# scripts/generate_phase1_sym_tables.py emits the reduction tables
# (data/generated/phase1_sym_tables.bin) and the native probe's BFS sweep
# persists the depth-12 distance table
# (data/generated/kociemba_phase1_sym_depth12.bin).  Depth 12 is the phase-1
# diameter, so for every reachable state the stored value IS the exact
# phase-1 distance of the (CO, EO, UD-slice) projection -- the strongest
# possible admissible heuristic for the phase-1 search, strictly dominating
# the max over the three 1-D coordinate projections.  Both files are
# structurally validated before being trusted; on any mismatch the solver
# falls back to the projection heuristic.  Soundness note: every solution the
# scoped solver returns is replay-verified against the cube model, so a
# corrupt table could only slow the search down or miss candidates, never
# yield a wrong solution; lookups additionally fail loudly on impossible
# stored values instead of inventing a bound.
# ---------------------------------------------------------------------------

_SYM_TABLES_FILENAME = "phase1_sym_tables.bin"
_SYM_DIST_FILENAME = "kociemba_phase1_sym_depth12.bin"
_SYM_TABLES_MAGIC = b"P1SYMR03"
_SYM_DIST_MAGIC = b"P1SYMRD1"
_SYM_COUNT = 16
_SYM_FLIP_COUNT = 2048
_SYM_UDSLICE_COUNT = 495
_SYM_TWIST_COUNT = 2187
_SYM_FLIPUDSLICE_COUNT = _SYM_FLIP_COUNT * _SYM_UDSLICE_COUNT  # 1,013,760
_SYM_CLASS_COUNT = 64430
_SYM_PHASE1_DOMAIN = _SYM_CLASS_COUNT * _SYM_TWIST_COUNT  # 140,908,410
# Canonical (class, reduced-twist) pairs produced by the canonicalisation; the
# remaining domain slots are provably unreachable and stay 0xff in the file.
_SYM_PHASE1_CANONICAL_COUNT = 138_639_780
_SYM_PHASE1_DIAMETER = 12


class _SymPhase1Heuristic:
    """Exact phase-1 distance lookups over the symmetry-reduced table."""

    __slots__ = ("classidx", "fus_sym", "sym_twist", "stab_mask", "dist", "depth", "table_bytes")

    def __init__(
        self,
        classidx: list[int],
        fus_sym: bytes,
        sym_twist: list[list[int]],
        stab_mask: list[int],
        dist: bytes,
        depth: int,
        table_bytes: int,
    ) -> None:
        self.classidx = classidx
        self.fus_sym = fus_sym
        self.sym_twist = sym_twist
        self.stab_mask = stab_mask
        self.dist = dist
        self.depth = depth
        self.table_bytes = table_bytes

    def lookup(self, co: int, eo: int, slice_coord: int) -> int:
        raw_index = eo * _SYM_UDSLICE_COUNT + slice_coord
        cls = self.classidx[raw_index]
        base = self.sym_twist[self.fus_sym[raw_index]][co]
        # Canonicalise the twist over the representative's stabilizer coset
        # (orbit minimum), mirroring sym_phase1_reduced_index in the native probe.
        reduced = base
        mask = self.stab_mask[cls] & ~1  # drop identity bit
        while mask:
            low = mask & -mask
            candidate = self.sym_twist[low.bit_length() - 1][base]
            if candidate < reduced:
                reduced = candidate
            mask &= mask - 1
        value = self.dist[cls * _SYM_TWIST_COUNT + reduced]
        if value > self.depth:
            # 0xff (or any value above the recorded BFS depth) marks a slot the
            # canonicalisation can never produce for a real state.  Hitting one
            # means the table and the canonicalisation disagree; fail loudly
            # instead of returning a made-up bound.
            raise RuntimeError(
                "sym-reduced phase-1 distance table returned impossible value "
                f"{value} for (co={co}, eo={eo}, slice={slice_coord}); "
                "refusing to invent a bound from an unvisited entry"
            )
        return value


@lru_cache(maxsize=1)
def _sym_phase1_heuristic() -> _SymPhase1Heuristic | None:
    """Load the exact symmetry-reduced phase-1 heuristic, or None if untrusted.

    Validates magic strings, declared counts, byte sizes, and the recorded
    visited-count bookkeeping (unvisited 0xff slots must exactly match
    domain - visited).  Any mismatch returns None so callers fall back to the
    projection heuristic rather than trusting unverified data.
    """

    root = _cache_root()
    try:
        raw = (root / _SYM_TABLES_FILENAME).read_bytes()
        dist_raw = (root / _SYM_DIST_FILENAME).read_bytes()
    except OSError:
        return None

    if len(raw) < 32 or raw[:8] != _SYM_TABLES_MAGIC:
        return None
    counts = struct.unpack_from("<6I", raw, 8)
    if counts != (
        _SYM_COUNT,
        _SYM_FLIP_COUNT,
        _SYM_UDSLICE_COUNT,
        _SYM_TWIST_COUNT,
        _SYM_CLASS_COUNT,
        _SYM_FLIPUDSLICE_COUNT,
    ):
        return None
    offset = 32 + _SYM_COUNT  # skip inv_sym (not needed for lookups)
    expected_size = (
        offset
        + 2 * _SYM_COUNT * _SYM_TWIST_COUNT  # sym_twist (u16)
        + 4 * _SYM_CLASS_COUNT  # classidx_to_rep (u32, not needed for lookups)
        + 2 * _SYM_CLASS_COUNT  # class_stab_mask (u16)
        + 2 * _SYM_FLIPUDSLICE_COUNT  # flipudslice_classidx (u16)
        + _SYM_FLIPUDSLICE_COUNT  # flipudslice_sym (u8)
    )
    if len(raw) != expected_size:
        return None

    def _u16_list(start: int, count: int) -> list[int]:
        values = array("H")
        values.frombytes(raw[start : start + 2 * count])
        if sys.byteorder != "little":
            values.byteswap()
        return values.tolist()

    sym_twist_flat = _u16_list(offset, _SYM_COUNT * _SYM_TWIST_COUNT)
    sym_twist = [
        sym_twist_flat[s * _SYM_TWIST_COUNT : (s + 1) * _SYM_TWIST_COUNT]
        for s in range(_SYM_COUNT)
    ]
    offset += 2 * _SYM_COUNT * _SYM_TWIST_COUNT
    offset += 4 * _SYM_CLASS_COUNT
    stab_mask = _u16_list(offset, _SYM_CLASS_COUNT)
    offset += 2 * _SYM_CLASS_COUNT
    classidx = _u16_list(offset, _SYM_FLIPUDSLICE_COUNT)
    offset += 2 * _SYM_FLIPUDSLICE_COUNT
    fus_sym = raw[offset : offset + _SYM_FLIPUDSLICE_COUNT]

    if len(dist_raw) != 24 + _SYM_PHASE1_DOMAIN or dist_raw[:8] != _SYM_DIST_MAGIC:
        return None
    domain, depth = struct.unpack_from("<Ii", dist_raw, 8)
    (visited,) = struct.unpack_from("<Q", dist_raw, 16)
    if domain != _SYM_PHASE1_DOMAIN or depth < _SYM_PHASE1_DIAMETER:
        return None
    if visited != _SYM_PHASE1_CANONICAL_COUNT:
        return None
    dist = dist_raw[24:]
    if dist.count(0xFF) != _SYM_PHASE1_DOMAIN - visited:
        return None

    return _SymPhase1Heuristic(
        classidx=classidx,
        fus_sym=fus_sym,
        sym_twist=sym_twist,
        stab_mask=stab_mask,
        dist=dist,
        depth=depth,
        table_bytes=len(raw) + len(dist_raw),
    )


def _phase1_lower_bound_function(
    pruning_tables: tuple[tuple[int, ...], ...],
):
    """Return ``(lower_bound, heuristic_name)`` for phase-1 coordinate triples.

    Prefers the exact symmetry-reduced distance (which dominates every 1-D
    projection of the same space, so no max is needed); falls back to the max
    over the three projection pruning tables when the sym tables are absent.
    """

    heuristic = _sym_phase1_heuristic()
    if heuristic is None:
        def projection_bound(coord: tuple[int, int, int]) -> int:
            return _phase1_lower_bound_from_tables(coord, pruning_tables)

        return projection_bound, "projection_max"

    lookup = heuristic.lookup

    def exact_bound(coord: tuple[int, int, int]) -> int:
        return lookup(coord[0], coord[1], coord[2])

    return exact_bound, "sym_reduced_exact_depth12"


def kociemba_phase1_lower_bound(cube: CubeState) -> int:
    """Return the native coordinate-table lower bound for Kociemba phase 1."""

    _, pruning_tables = _phase1_coordinate_tables()
    coord = (
        CORNER_ORIENTATION_SPEC.encode(cube),
        EDGE_ORIENTATION_SPEC.encode(cube),
        UD_SLICE_SPEC.encode(cube),
    )
    return _phase1_lower_bound_from_tables(coord, pruning_tables)


def kociemba_phase2_projection_lower_bound(cube: CubeState) -> int:
    """Return the native restricted-move lower bound for Kociemba phase 2."""

    _, pruning_tables = _phase2_coordinate_tables()
    coord = tuple(spec.encode(cube) for spec in PHASE2_MOVE_TABLE_SPECS)
    return _phase2_lower_bound_from_tables(coord, pruning_tables)


def solve_kociemba_phase1(
    cube: CubeState,
    *,
    max_depth: int = 8,
    timeout_seconds: float = 5.0,
    node_limit: int = 500_000,
):
    """Solve Kociemba phase 1 in generated coordinate-table space."""

    move_tables, pruning_tables = _phase1_coordinate_tables()
    begin = time.perf_counter()
    goal = (
        CORNER_ORIENTATION_SPEC.solved_coord,
        EDGE_ORIENTATION_SPEC.solved_coord,
        UD_SLICE_SPEC.solved_coord,
    )
    start = (
        CORNER_ORIENTATION_SPEC.encode(cube),
        EDGE_ORIENTATION_SPEC.encode(cube),
        UD_SLICE_SPEC.encode(cube),
    )

    lower_bound, _ = _phase1_lower_bound_function(pruning_tables)

    initial_lower_bound = lower_bound(start)
    if start == goal:
        return IDAStarResult(
            [], 0, 0, max_depth, "exact", 0.0, 0,
            "Coordinate phase-1 goal already satisfied",
        )
    if initial_lower_bound > max_depth:
        return IDAStarResult(
            None, 0, 0, max_depth, "lower_bound", time.perf_counter() - begin,
            initial_lower_bound, "Coordinate phase-1 lower bound exceeds configured max depth",
        )

    expanded = 0
    generated = 0
    path: list[str] = []

    def timed_out() -> bool:
        return (time.perf_counter() - begin) >= timeout_seconds

    def search(
        coord: tuple[int, int, int],
        g: int,
        bound: int,
        previous: str | None,
        seen: dict[tuple[tuple[int, int, int], str], int],
    ) -> int | list[str]:
        nonlocal expanded, generated
        f_score = g + lower_bound(coord)
        if f_score > bound:
            return f_score
        if coord == goal:
            return list(path)
        seen_key = (coord, previous[0] if previous else "")
        previous_depth = seen.get(seen_key)
        if previous_depth is not None and previous_depth <= g:
            return math.inf
        seen[seen_key] = g
        if g >= max_depth:
            return math.inf
        if timed_out() or expanded >= node_limit:
            return math.inf

        expanded += 1
        minimum = math.inf
        children: list[tuple[int, str, tuple[int, int, int]]] = []
        for move_index, move in enumerate(ALL_MOVES):
            if same_face(previous, move):
                continue
            child = (
                move_tables[0][coord[0]][move_index],
                move_tables[1][coord[1]][move_index],
                move_tables[2][coord[2]][move_index],
            )
            generated += 1
            children.append((lower_bound(child), move, child))
        children.sort(key=lambda item: (item[0], item[1]))
        for _, move, child in children:
            path.append(move)
            outcome = search(child, g + 1, bound, move, seen)
            if isinstance(outcome, list):
                return outcome
            if outcome < minimum:
                minimum = outcome
            path.pop()
            if timed_out() or expanded >= node_limit:
                break
        return minimum

    bound = initial_lower_bound
    while bound <= max_depth:
        outcome = search(start, 0, bound, None, {})
        runtime = time.perf_counter() - begin
        if isinstance(outcome, list):
            return IDAStarResult(
                outcome, expanded, generated, max_depth, "exact", runtime,
                initial_lower_bound, "Coordinate phase-1 IDA* completed before timeout",
            )
        if timed_out():
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                initial_lower_bound, "Coordinate phase-1 IDA* timed out",
            )
        if expanded >= node_limit:
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                initial_lower_bound, "Coordinate phase-1 node limit reached",
            )
        if outcome == math.inf:
            break
        bound = int(outcome)

    return IDAStarResult(
        None, expanded, generated, max_depth, "lower_bound", time.perf_counter() - begin,
        initial_lower_bound, "No coordinate phase-1 solution within configured depth",
    )


def collect_kociemba_phase1_candidates(
    cube: CubeState,
    *,
    max_depth: int = 12,
    timeout_seconds: float = 10.0,
    node_limit: int = 2_000_000,
    max_candidates: int = 8,
    soft_timeout_seconds: float | None = None,
) -> IDAStarCandidatesResult:
    """Collect bounded phase-1 handoff candidates in coordinate-table space.

    A Kociemba-style two-phase search should not commit blindly to the first
    phase-1 hit, because different states in the phase-2 subgroup can have very
    different restricted-move distances. This collector keeps the generated
    phase-1 coordinate search small, but returns several independently reached
    full-cube handoff states for phase-2 ranking.

    ``soft_timeout_seconds`` is an early-stop deadline that only applies once
    at least one candidate has been collected: a two-phase caller sharing one
    budget can keep hunting for the FIRST handoff up to the hard timeout (with
    no candidate there is nothing for phase 2 to do), but must stop topping up
    extra candidates early so phase 2 keeps a guaranteed share of the budget.
    """

    max_candidates = max(1, int(max_candidates))
    move_tables, pruning_tables = _phase1_coordinate_tables()
    begin = time.perf_counter()
    goal = (
        CORNER_ORIENTATION_SPEC.solved_coord,
        EDGE_ORIENTATION_SPEC.solved_coord,
        UD_SLICE_SPEC.solved_coord,
    )
    start = (
        CORNER_ORIENTATION_SPEC.encode(cube),
        EDGE_ORIENTATION_SPEC.encode(cube),
        UD_SLICE_SPEC.encode(cube),
    )

    lower_bound, _ = _phase1_lower_bound_function(pruning_tables)

    initial_lower_bound = lower_bound(start)
    if start == goal:
        return IDAStarCandidatesResult(
            [[]], 0, 0, max_depth, "exact", 0.0, 0,
            "Coordinate phase-1 goal already satisfied",
        )
    if initial_lower_bound > max_depth:
        return IDAStarCandidatesResult(
            [], 0, 0, max_depth, "lower_bound", time.perf_counter() - begin,
            initial_lower_bound, "Coordinate phase-1 lower bound exceeds configured max depth",
        )

    expanded = 0
    generated = 0
    path: list[str] = []
    solutions: list[list[str]] = []
    seen_goal_states: set[str] = set()

    soft_deadline = (
        None
        if soft_timeout_seconds is None
        else min(float(timeout_seconds), max(0.0, float(soft_timeout_seconds)))
    )

    def timed_out() -> bool:
        elapsed = time.perf_counter() - begin
        if elapsed >= timeout_seconds:
            return True
        # Soft deadline: once at least one handoff exists, stop collecting so
        # the caller keeps a guaranteed share of its budget for phase 2.
        return bool(solutions) and soft_deadline is not None and elapsed >= soft_deadline

    def search(
        coord: tuple[int, int, int],
        g: int,
        bound: int,
        previous: str | None,
        seen: dict[tuple[tuple[int, int, int], str], int],
    ) -> int:
        nonlocal expanded, generated
        if len(solutions) >= max_candidates or timed_out() or expanded >= node_limit:
            return math.inf
        f_score = g + lower_bound(coord)
        if f_score > bound:
            return f_score
        if coord == goal:
            handoff_state = cube.apply_sequence(path)
            state_key = handoff_state.to_facelets()
            if state_key not in seen_goal_states:
                seen_goal_states.add(state_key)
                solutions.append(list(path))
            return math.inf
        seen_key = (coord, previous[0] if previous else "")
        previous_depth = seen.get(seen_key)
        if previous_depth is not None and previous_depth <= g:
            return math.inf
        seen[seen_key] = g
        if g >= max_depth:
            return math.inf

        expanded += 1
        minimum = math.inf
        children: list[tuple[int, str, tuple[int, int, int]]] = []
        for move_index, move in enumerate(ALL_MOVES):
            if same_face(previous, move):
                continue
            child = (
                move_tables[0][coord[0]][move_index],
                move_tables[1][coord[1]][move_index],
                move_tables[2][coord[2]][move_index],
            )
            generated += 1
            children.append((lower_bound(child), move, child))
        children.sort(key=lambda item: (item[0], item[1]))
        for _, move, child in children:
            path.append(move)
            outcome = search(child, g + 1, bound, move, seen)
            if outcome < minimum:
                minimum = outcome
            path.pop()
            if len(solutions) >= max_candidates or timed_out() or expanded >= node_limit:
                break
        return minimum

    for bound in range(initial_lower_bound, max_depth + 1):
        search(start, 0, bound, None, {})
        if len(solutions) >= max_candidates or timed_out() or expanded >= node_limit:
            break

    runtime = time.perf_counter() - begin
    if solutions:
        note = "Collected coordinate phase-1 handoff candidates"
        if len(solutions) >= max_candidates:
            note += "; candidate limit reached"
        elif timed_out():
            note += "; timeout reached after collecting candidates"
        elif expanded >= node_limit:
            note += "; node limit reached after collecting candidates"
        return IDAStarCandidatesResult(
            solutions, expanded, generated, max_depth, "exact", runtime, initial_lower_bound, note,
        )
    if timed_out():
        return IDAStarCandidatesResult(
            [], expanded, generated, max_depth, "timeout", runtime,
            initial_lower_bound, "Coordinate phase-1 candidate collection timed out",
        )
    if expanded >= node_limit:
        return IDAStarCandidatesResult(
            [], expanded, generated, max_depth, "timeout", runtime,
            initial_lower_bound, "Coordinate phase-1 candidate collection node limit reached",
        )
    return IDAStarCandidatesResult(
        [], expanded, generated, max_depth, "lower_bound", runtime,
        initial_lower_bound, "No coordinate phase-1 handoff candidate within configured depth",
    )


def solve_kociemba_phase2(
    cube: CubeState,
    *,
    max_depth: int = 11,
    timeout_seconds: float = 5.0,
    node_limit: int = 500_000,
):
    """Solve Kociemba phase 2 in generated phase-2 coordinate space."""

    move_tables, pruning_tables = _phase2_coordinate_tables()
    begin = time.perf_counter()
    goal = tuple(spec.solved_coord for spec in PHASE2_MOVE_TABLE_SPECS)
    try:
        start = tuple(spec.encode(cube) for spec in PHASE2_MOVE_TABLE_SPECS)
    except ValueError as exc:
        return IDAStarResult(
            None, 0, 0, max_depth, "failed", time.perf_counter() - begin,
            0, f"Coordinate phase-2 input is outside the phase-2 subgroup: {exc}",
        )

    def lower_bound(coord: tuple[int, ...]) -> int:
        return _phase2_lower_bound_from_tables(coord, pruning_tables)

    initial_lower_bound = lower_bound(start)
    if start == goal:
        return IDAStarResult(
            [], 0, 0, max_depth, "exact", 0.0, 0,
            "Coordinate phase-2 goal already satisfied",
        )
    if initial_lower_bound > max_depth:
        return IDAStarResult(
            None, 0, 0, max_depth, "lower_bound", time.perf_counter() - begin,
            initial_lower_bound, "Coordinate phase-2 lower bound exceeds configured max depth",
        )

    expanded = 0
    generated = 0
    path: list[str] = []

    def timed_out() -> bool:
        return (time.perf_counter() - begin) >= timeout_seconds

    def search(
        coord: tuple[int, ...],
        g: int,
        bound: int,
        previous: str | None,
        seen: dict[tuple[tuple[int, ...], str], int],
    ) -> int | list[str]:
        nonlocal expanded, generated
        f_score = g + lower_bound(coord)
        if f_score > bound:
            return f_score
        if coord == goal:
            return list(path)
        seen_key = (coord, previous[0] if previous else "")
        previous_depth = seen.get(seen_key)
        if previous_depth is not None and previous_depth <= g:
            return math.inf
        seen[seen_key] = g
        if g >= max_depth:
            return math.inf
        if timed_out() or expanded >= node_limit:
            return math.inf

        expanded += 1
        minimum = math.inf
        children: list[tuple[int, str, tuple[int, ...]]] = []
        for move_index, move in enumerate(PHASE2_MOVES):
            if same_face(previous, move):
                continue
            child = tuple(
                move_tables[index][coord[index]][move_index]
                for index in range(len(coord))
            )
            generated += 1
            children.append((lower_bound(child), move, child))
        children.sort(key=lambda item: (item[0], item[1]))
        for _, move, child in children:
            path.append(move)
            outcome = search(child, g + 1, bound, move, seen)
            if isinstance(outcome, list):
                return outcome
            if outcome < minimum:
                minimum = outcome
            path.pop()
            if timed_out() or expanded >= node_limit:
                break
        return minimum

    bound = initial_lower_bound
    while bound <= max_depth:
        outcome = search(start, 0, bound, None, {})
        runtime = time.perf_counter() - begin
        if isinstance(outcome, list):
            return IDAStarResult(
                outcome, expanded, generated, max_depth, "exact", runtime,
                initial_lower_bound, "Coordinate phase-2 IDA* completed before timeout",
            )
        if timed_out():
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                initial_lower_bound, "Coordinate phase-2 IDA* timed out",
            )
        if expanded >= node_limit:
            return IDAStarResult(
                None, expanded, generated, max_depth, "timeout", runtime,
                initial_lower_bound, "Coordinate phase-2 node limit reached",
            )
        if outcome == math.inf:
            break
        bound = int(outcome)

    return IDAStarResult(
        None, expanded, generated, max_depth, "lower_bound", time.perf_counter() - begin,
        initial_lower_bound, "No coordinate phase-2 solution within configured depth",
    )


def solve_kociemba_native_scoped(
    cube: CubeState,
    *,
    phase1_max_depth: int = 12,
    phase2_max_depth: int = 18,
    timeout_seconds: float = 10.0,
    node_limit: int = 2_000_000,
    phase1_candidate_limit: int = 8,
) -> SolverResult:
    # Default depth caps equal the phase diameters (phase 1: 12, phase 2: 18),
    # so no valid state is unreachable by configuration; only the time/node
    # budgets bound the search.
    _phase1_coordinate_tables()
    _phase2_coordinate_tables()
    sym_heuristic = _sym_phase1_heuristic()
    phase1_heuristic_name = (
        "sym_reduced_exact_depth12" if sym_heuristic is not None else "projection_max"
    )
    native_table_bytes = _native_table_bytes() + (
        sym_heuristic.table_bytes if sym_heuristic is not None else 0
    )
    begin = time.perf_counter()
    if cube.is_solved():
        return SolverResult(
            solver_name="kociemba_native_scoped",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=native_table_bytes,
            status="non_exact",
            is_verified=True,
            notes="Solved input; native scoped two-phase path does not claim global optimality",
        )

    # Budget split: candidate collection may use the whole budget while it has
    # found NOTHING (phase 2 has no work without a handoff), but once at least
    # one candidate exists it must stop at the soft deadline so phase 2 keeps a
    # guaranteed share of the budget instead of being starved.
    phase1_candidates = collect_kociemba_phase1_candidates(
        cube,
        max_depth=phase1_max_depth,
        timeout_seconds=timeout_seconds,
        soft_timeout_seconds=0.4 * timeout_seconds,
        node_limit=node_limit,
        max_candidates=phase1_candidate_limit,
    )
    if not phase1_candidates.solutions:
        return SolverResult(
            solver_name="kociemba_native_scoped",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=phase1_candidates.expanded_nodes,
            generated_nodes=phase1_candidates.generated_nodes,
            table_bytes=native_table_bytes,
            status=phase1_candidates.status,
            is_verified=False,
            notes=(
                "Native phase 1 did not reach the orientation/slice subgroup; "
                f"phase1_note={phase1_candidates.notes}; "
                f"phase1_lower_bound={phase1_candidates.lower_bound}; "
                f"phase1_heuristic={phase1_heuristic_name}; "
                f"phase1_candidate_limit={max(1, int(phase1_candidate_limit))}"
            ),
        )

    # Rank candidates by an admissible lower bound on the achievable TOTAL length
    # (phase1 length + admissible phase2 lower bound). This ordering lets us both
    # try the most promising handoff first and prune the rest once a verified
    # total is found, because the list is sorted ascending by that lower bound.
    ranked_candidates: list[tuple[float, float, int, tuple[str, ...], CubeState]] = []
    for candidate in phase1_candidates.solutions:
        phase1_state = cube.apply_sequence(candidate)
        try:
            phase2_lower_bound: float = kociemba_phase2_projection_lower_bound(phase1_state)
        except ValueError:
            phase2_lower_bound = math.inf
        achievable_total_lb = (
            len(candidate) + phase2_lower_bound if phase2_lower_bound != math.inf else math.inf
        )
        ranked_candidates.append((
            achievable_total_lb,
            phase2_lower_bound,
            len(candidate),
            tuple(candidate),
            phase1_state,
        ))
    ranked_candidates.sort(key=lambda item: (item[0], item[2], item[3]))

    expanded = phase1_candidates.expanded_nodes
    generated = phase1_candidates.generated_nodes
    deadline = begin + timeout_seconds
    phase2_attempts = 0

    # Kociemba-style length minimization: instead of returning the first solving
    # handoff, search every ranked candidate and keep the shortest VERIFIED total.
    best_total: int | None = None
    best_solution: list[str] | None = None
    best_phase1_len: int | None = None
    best_phase2_len: int | None = None
    best_selected_lower_bound: int | None = None

    # Diagnostics for the no-solution fallback path.
    best_phase2_for_diag: IDAStarResult | None = None
    best_phase1_for_diag: tuple[str, ...] | None = None
    best_phase2_lower_bound_diag = math.inf

    for achievable_total_lb, phase2_lower_bound, phase1_len, phase1_solution, phase1_state in ranked_candidates:
        # Once a verified total exists, no remaining candidate whose optimistic
        # total lower bound is not strictly smaller can improve it (sorted order).
        if (
            best_total is not None
            and achievable_total_lb != math.inf
            and achievable_total_lb >= best_total
        ):
            break
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            if phase2_attempts > 0:
                break
            # The deadline expired before any phase-2 attempt (collection used
            # the whole budget finding its first handoff).  Phase 2 must run
            # whenever a candidate exists, so grant one small bounded attempt
            # instead of returning a gratuitous failure with handoffs in hand.
            remaining = max(0.25, 0.05 * timeout_seconds)
        # Only look for solutions strictly shorter than the best total so far.
        phase2_cap = phase2_max_depth
        if best_total is not None:
            phase2_cap = min(phase2_cap, best_total - phase1_len - 1)
        if phase2_cap < 0:
            continue
        phase2_attempts += 1
        phase2 = solve_kociemba_phase2(
            phase1_state,
            max_depth=phase2_cap,
            timeout_seconds=remaining,
            node_limit=node_limit,
        )
        expanded += phase2.expanded_nodes
        generated += phase2.generated_nodes
        if best_phase2_for_diag is None or phase2.lower_bound < best_phase2_lower_bound_diag:
            best_phase2_for_diag = phase2
            best_phase1_for_diag = phase1_solution
            best_phase2_lower_bound_diag = phase2.lower_bound
        if phase2.solution is None:
            continue
        candidate_solution = list(phase1_solution) + list(phase2.solution)
        candidate_total = len(candidate_solution)
        if best_total is None or candidate_total < best_total:
            verification = verify_solution(cube, candidate_solution)
            if verification.ok:
                best_total = candidate_total
                best_solution = candidate_solution
                best_phase1_len = len(phase1_solution)
                best_phase2_len = len(phase2.solution)
                best_selected_lower_bound = phase2.lower_bound

    if best_solution is not None:
        return SolverResult(
            solver_name="kociemba_native_scoped",
            input_state=cube.to_facelets(),
            solution_moves=best_solution,
            solution_length=best_total,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=expanded,
            generated_nodes=generated,
            table_bytes=native_table_bytes,
            status="non_exact",
            is_verified=True,
            notes=(
                "Native bounded two-phase result; shortest VERIFIED total over all ranked phase-1 "
                "handoff candidates (Kociemba-style length minimization); no global optimality proof "
                "claimed; "
                f"phase1_length={best_phase1_len}; phase2_length={best_phase2_len}; "
                f"phase1_candidates_collected={len(phase1_candidates.solutions)}; "
                f"phase1_candidates_tried={phase2_attempts}; "
                f"selected_phase2_lower_bound={best_selected_lower_bound}; "
                f"phase1_heuristic={phase1_heuristic_name}; "
                f"phase1_candidate_limit={max(1, int(phase1_candidate_limit))}"
            ),
        )

    if best_phase2_for_diag is not None:
        failure_status = best_phase2_for_diag.status
    elif time.perf_counter() >= deadline:
        # Time, not depth exhaustion, ended the search before any phase-2
        # attempt: report an honest timeout, never a bound-establishing status.
        failure_status = "timeout"
    else:
        failure_status = "lower_bound"

    return SolverResult(
        solver_name="kociemba_native_scoped",
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=expanded,
        generated_nodes=generated,
        table_bytes=native_table_bytes,
        status=failure_status,
        is_verified=False,
        notes=(
            "Native phase 1 reached the subgroup, but bounded phase 2 did not solve any ranked handoff within limits; "
            f"phase1_candidates_collected={len(phase1_candidates.solutions)}; "
            f"phase1_candidates_tried={phase2_attempts}; "
            f"phase1_heuristic={phase1_heuristic_name}; "
            f"best_phase1_length={len(best_phase1_for_diag) if best_phase1_for_diag is not None else None}; "
            f"best_phase2_lower_bound={best_phase2_lower_bound_diag if best_phase2_lower_bound_diag != math.inf else None}; "
            f"phase2_note={best_phase2_for_diag.notes if best_phase2_for_diag is not None else 'none'}"
        ),
    )


def solve_kociemba_adapter(cube: CubeState) -> SolverResult:
    begin = time.perf_counter()
    if cube.is_solved():
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="Solved input; no optimality proof claimed",
        )
    try:
        import kociemba  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on local environment
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=time.perf_counter() - begin,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="not_applicable",
            is_verified=False,
            notes=f"Optional kociemba package unavailable: {exc}",
        )

    try:
        raw = kociemba.solve(cube.to_facelets())
        moves = parse_sequence(raw)
        verification = verify_solution(cube, moves)
        status = "non_exact" if verification.ok else "failed"
        notes = "Two-phase package result verified; no optimality proof claimed"
        if not verification.ok:
            notes = verification.message
    except Exception as exc:
        moves = []
        verification = None
        status = "failed"
        notes = f"kociemba adapter failed: {exc}"

    return SolverResult(
        solver_name="kociemba_two_phase_adapter",
        input_state=cube.to_facelets(),
        solution_moves=moves,
        solution_length=len(moves) if moves else (0 if cube.is_solved() else None),
        metric="HTM",
        runtime_seconds=time.perf_counter() - begin,
        expanded_nodes=None,
        generated_nodes=None,
        table_bytes=None,
        status=status,
        is_verified=bool(verification and verification.ok),
        notes=notes,
    )
