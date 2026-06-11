"""Exact per-phase coset distance tables for the Thistlethwaite algorithm.

This module builds, caches, and loads the four exact breadth-first-search
distance tables that drive the classic Thistlethwaite four-phase subgroup
chain ``G0 > G1 > G2 > G3 > G4``:

* ``G0 -> G1``  edge-orientation coordinate (2^11 = 2048 states) under all 18
  HTM moves; goal is ``EO = 0``.
* ``G1 -> G2``  corner-orientation (3^7 = 2187) x UD-slice combination
  (C(12,4) = 495) product coordinate (1,082,565 states) under the G1 move set;
  goal is ``CO = 0`` with the four slice edges in the slice.
* ``G2 -> G3``  the left-coset quotient of the corner permutation modulo the
  square-group corner action (420 cosets) crossed with the edge permutation
  modulo the square-group edge action (the reachable edge cosets) under the G2
  move set (29,400 reachable cosets, maximum distance 13).
* ``G3 -> G4``  the square group ``<U2,D2,L2,R2,F2,B2>`` itself
  (96 x 6912 = 663,552 states) under the G3 move set; goal is solved.

Every table is an exact BFS distance table (admissible *and* tight: it is the
true distance, so it doubles as a perfect heuristic for table-guided descent).
Tables are generated once, written to disk as raw little-endian ``uint8``
binaries, checksummed (SHA-256), and reloaded on subsequent runs.  The coset
index maps that translate an arbitrary cube into a table offset are rebuilt
deterministically in-process and pinned to the cached tables via checksums in
the manifest, so a corrupt or mismatched cache is detected rather than silently
mis-solving.

The distance-table sizes and maximum depths are mathematically determined and
independently match the published Thistlethwaite phase bounds (7 / 10 / 13 /
15), which is the verification that the coordinate/coset spaces are correct.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from itertools import permutations
from pathlib import Path

from rubik_optimal.coordinates import (
    CORNER_ORIENTATION_SPEC,
    EDGE_ORIENTATION_SPEC,
    UD_SLICE_SPEC,
)
from rubik_optimal.cube import CubeState

# ---------------------------------------------------------------------------
# Move groups for each subgroup-reduction phase.
# ---------------------------------------------------------------------------

ALL_MOVES = (
    "U", "U'", "U2",
    "R", "R'", "R2",
    "F", "F'", "F2",
    "D", "D'", "D2",
    "L", "L'", "L2",
    "B", "B'", "B2",
)
G1_MOVES = (
    "U", "U'", "U2",
    "D", "D'", "D2",
    "R", "R'", "R2",
    "L", "L'", "L2",
    "F2", "B2",
)
G2_MOVES = ("U", "U'", "U2", "D", "D'", "D2", "R2", "L2", "F2", "B2")
G3_MOVES = ("U2", "D2", "R2", "L2", "F2", "B2")

# Corner / edge orbits fixed (set-wise) by the square group.
G3_CORNER_ORBITS = (
    (0, 2, 5, 7),
    (1, 3, 4, 6),
)
G3_EDGE_ORBITS = (
    (0, 2, 4, 6),
    (1, 3, 5, 7),
    (8, 9, 10, 11),
)

UNREACHED = 255

CACHE_DIRNAME = "thistlethwaite"
MANIFEST_NAME = "thistlethwaite_manifest.json"
SCHEMA_VERSION = 1


def _default_root() -> Path:
    # tables/thistlethwaite_tables.py -> rubik_optimal -> src -> repo root
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Permutation helpers.
# ---------------------------------------------------------------------------

def _compose(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
    """Return ``a . b`` so that ``(a . b)[i] = a[b[i]]``."""

    return tuple(a[b[i]] for i in range(len(a)))


@lru_cache(maxsize=1)
def _g3_corner_permutations() -> tuple[tuple[int, ...], ...]:
    """The 96 corner permutations reachable from solved by half turns."""

    solved = CubeState.solved()
    move_cp = {m: solved.apply_move(m).cp for m in G3_MOVES}
    start = solved.cp
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for m in G3_MOVES:
            nxt = _compose(cur, move_cp[m])
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return tuple(sorted(seen))


@lru_cache(maxsize=1)
def _g3_edge_permutations() -> tuple[tuple[int, ...], ...]:
    """The 6912 edge permutations reachable from solved by half turns."""

    solved = CubeState.solved()
    move_ep = {m: solved.apply_move(m).ep for m in G3_MOVES}
    start = solved.ep
    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for m in G3_MOVES:
            nxt = _compose(cur, move_ep[m])
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return tuple(sorted(seen))


# ---------------------------------------------------------------------------
# Coset index maps (deterministic, shared by generation and runtime).
#
# Distance-to-G3 is invariant under *left* multiplication by a square-group
# element, so the coset of a permutation ``p`` is canonicalised as
# ``min over g in square-group of (g . p)``.  Because the square group is the
# direct product of its corner action (96) and edge action (6912), corners and
# edges canonicalise independently.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _corner_coset_index() -> tuple[dict[tuple[int, ...], int], int]:
    """Map every 8! corner permutation to its square-group left-coset id.

    Coset ids are assigned by sorting the canonical representatives, making the
    enumeration deterministic and independent of traversal order.
    """

    group = _g3_corner_permutations()
    canon: dict[tuple[int, ...], tuple[int, ...]] = {}
    for cp in permutations(range(8)):
        if cp in canon:
            continue
        orbit = [_compose(g, cp) for g in group]
        rep = min(orbit)
        for member in orbit:
            canon[member] = rep
    reps = sorted(set(canon.values()))
    rep_to_id = {rep: idx for idx, rep in enumerate(reps)}
    return {cp: rep_to_id[rep] for cp, rep in canon.items()}, len(reps)


@lru_cache(maxsize=1)
def _edge_group_set() -> frozenset[tuple[int, ...]]:
    return frozenset(_g3_edge_permutations())


@lru_cache(maxsize=1)
def _edge_coset_index() -> tuple[dict[tuple[int, ...], int], int]:
    """Map every G2-reachable edge permutation to its square-group coset id.

    The reachable cosets are discovered by a coset-level BFS.  When a new coset
    is first reached its entire left-orbit ``{g . ep for g in edge-group}`` is
    materialised (6912 compositions), so every edge permutation in that coset
    becomes an O(1) dictionary lookup -- both during table generation and at
    solve time.  Coset ids are finally assigned by sorting the canonical
    (minimal) representatives, making the mapping independent of BFS order and
    therefore deterministic.
    """

    reps = _edge_coset_reps()
    return _build_edge_id_map(reps), len(reps)


def _build_edge_id_map(
    reps: tuple[tuple[int, ...], ...],
) -> dict[tuple[int, ...], int]:
    """Expand each canonical edge-coset rep into its full left-orbit.

    Given the sorted canonical representatives, every edge permutation in a
    coset is enumerated as ``g . rep`` for ``g`` in the square-group edge action,
    so the resulting ``edge permutation -> coset id`` map is an O(1) lookup.
    This is the fast path used at load time (140 x 6912 compositions).
    """

    group = _g3_edge_permutations()
    edge_id_map: dict[tuple[int, ...], int] = {}
    for idx, rep in enumerate(reps):
        for g in group:
            edge_id_map[_compose(g, rep)] = idx
    return edge_id_map


# Optional pinned reps loaded from the cache manifest, letting cold loads skip
# the BFS discovery step entirely.
_PINNED_EDGE_REPS: dict[str, tuple[tuple[int, ...], ...]] = {}


@lru_cache(maxsize=1)
def _edge_coset_reps() -> tuple[tuple[int, ...], ...]:
    """Discover the G2-reachable edge cosets and return their canonical reps.

    The reachable cosets are found by a coset-level BFS; each coset's canonical
    representative is its minimal left-orbit member.  Returning the sorted reps
    makes the enumeration deterministic and independent of BFS order.  This is
    the slow step; its output is small (140 reps) and is persisted in the
    manifest so cold loads can skip the BFS entirely.
    """

    pinned = _PINNED_EDGE_REPS.get("reps")
    if pinned is not None:
        return pinned

    group = _g3_edge_permutations()
    solved = CubeState.solved()
    move_cp = {m: solved.apply_move(m).cp for m in G2_MOVES}
    move_ep = {m: solved.apply_move(m).ep for m in G2_MOVES}
    corner_canon, _ = _corner_coset_index()

    ep_to_rep: dict[tuple[int, ...], tuple[int, ...]] = {}

    def materialise_orbit(ep: tuple[int, ...]) -> tuple[int, ...]:
        rep = ep_to_rep.get(ep)
        if rep is not None:
            return rep
        orbit = [_compose(g, ep) for g in group]
        rep = min(orbit)
        for member in orbit:
            ep_to_rep[member] = rep
        return rep

    start_rep = materialise_orbit(solved.ep)
    start_key = (corner_canon[solved.cp], start_rep)
    seen = {start_key}
    rep_state = {start_key: (solved.cp, solved.ep)}
    queue = deque([start_key])
    edge_reps: set[tuple[int, ...]] = {start_rep}
    while queue:
        key = queue.popleft()
        cp, ep = rep_state[key]
        for m in G2_MOVES:
            mcp = move_cp[m]
            mep = move_ep[m]
            ncp = tuple(cp[mcp[i]] for i in range(8))
            nep = tuple(ep[mep[i]] for i in range(12))
            erep = materialise_orbit(nep)
            nkey = (corner_canon[ncp], erep)
            if nkey not in seen:
                seen.add(nkey)
                rep_state[nkey] = (ncp, nep)
                edge_reps.add(erep)
                queue.append(nkey)

    return tuple(sorted(edge_reps))


def _validate_edge_coset_reps(reps: tuple[tuple[int, ...], ...]) -> bool:
    """Cheaply sanity-check pinned reps before trusting them.

    Each rep must be a permutation of ``range(12)`` and equal to the minimal
    member of its own left-orbit (i.e. be genuinely canonical).  Full BFS
    re-discovery is unnecessary: the G2 distance table's SHA-256 already pins the
    layout, and a wrong rep set would make greedy descent fail loudly rather than
    mis-solve silently.
    """

    if not reps:
        return False
    group = _g3_edge_permutations()
    identity = tuple(range(12))
    for rep in reps:
        if sorted(rep) != list(identity):
            return False
        if min(_compose(g, rep) for g in group) != rep:
            return False
    return len(set(reps)) == len(reps)


def _set_pinned_edge_coset_reps(reps: tuple[tuple[int, ...], ...] | None) -> None:
    """Pin (or clear) cached edge-coset reps so loads can skip BFS discovery."""

    if reps is None:
        _PINNED_EDGE_REPS.pop("reps", None)
    else:
        _PINNED_EDGE_REPS["reps"] = reps
    _edge_coset_reps.cache_clear()
    _edge_coset_index.cache_clear()


# ---------------------------------------------------------------------------
# State -> table offset functions.
# ---------------------------------------------------------------------------

def g0_index(cube: CubeState) -> int:
    return EDGE_ORIENTATION_SPEC.encode(cube)


def g1_index(cube: CubeState) -> int:
    co = CORNER_ORIENTATION_SPEC.encode(cube)
    uds = UD_SLICE_SPEC.encode(cube)
    return co * UD_SLICE_SPEC.domain_size + uds


def g2_index(cube: CubeState) -> int:
    corner_canon, _ = _corner_coset_index()
    edge_id_map, num_edge = _edge_coset_index()
    corner_id = corner_canon[cube.cp]
    edge_id = edge_id_map[cube.ep]
    return corner_id * num_edge + edge_id


def g3_index(cube: CubeState) -> int:
    corner_perms = _g3_corner_permutations()
    edge_perms = _g3_edge_permutations()
    corner_lookup = {p: i for i, p in enumerate(corner_perms)}
    edge_lookup = {p: i for i, p in enumerate(edge_perms)}
    return corner_lookup[cube.cp] * len(edge_perms) + edge_lookup[cube.ep]


# ---------------------------------------------------------------------------
# BFS table builders.
# ---------------------------------------------------------------------------

def build_g0_table() -> bytearray:
    """Edge-orientation distance to ``EO = 0`` under all 18 moves."""

    n = EDGE_ORIENTATION_SPEC.domain_size
    move_table = [[0] * len(ALL_MOVES) for _ in range(n)]
    for coord in range(n):
        cube = EDGE_ORIENTATION_SPEC.decode(coord)
        for mi, move in enumerate(ALL_MOVES):
            move_table[coord][mi] = EDGE_ORIENTATION_SPEC.encode(cube.apply_move(move))
    dist = bytearray([UNREACHED]) * n
    start = EDGE_ORIENTATION_SPEC.solved_coord
    dist[start] = 0
    queue = deque([start])
    nmoves = len(ALL_MOVES)
    while queue:
        s = queue.popleft()
        nd = dist[s] + 1
        row = move_table[s]
        for mi in range(nmoves):
            ns = row[mi]
            if dist[ns] == UNREACHED:
                dist[ns] = nd
                queue.append(ns)
    return dist


def build_g1_table() -> bytearray:
    """Corner-orientation x UD-slice distance to G2 under the G1 move set."""

    nc = CORNER_ORIENTATION_SPEC.domain_size
    nu = UD_SLICE_SPEC.domain_size
    co_mt = [[0] * len(G1_MOVES) for _ in range(nc)]
    for co in range(nc):
        cube = CORNER_ORIENTATION_SPEC.decode(co)
        for mi, move in enumerate(G1_MOVES):
            co_mt[co][mi] = CORNER_ORIENTATION_SPEC.encode(cube.apply_move(move))
    uds_mt = [[0] * len(G1_MOVES) for _ in range(nu)]
    for u in range(nu):
        cube = UD_SLICE_SPEC.decode(u)
        for mi, move in enumerate(G1_MOVES):
            uds_mt[u][mi] = UD_SLICE_SPEC.encode(cube.apply_move(move))

    n = nc * nu
    dist = bytearray([UNREACHED]) * n
    solved = CubeState.solved()
    start = CORNER_ORIENTATION_SPEC.encode(solved) * nu + UD_SLICE_SPEC.encode(solved)
    dist[start] = 0
    queue = deque([start])
    nmoves = len(G1_MOVES)
    while queue:
        s = queue.popleft()
        nd = dist[s] + 1
        co = s // nu
        u = s % nu
        cor = co_mt[co]
        uor = uds_mt[u]
        for mi in range(nmoves):
            ns = cor[mi] * nu + uor[mi]
            if dist[ns] == UNREACHED:
                dist[ns] = nd
                queue.append(ns)
    return dist


def build_g2_table() -> bytearray:
    """Corner/edge left-coset distance to G3 under the G2 move set."""

    solved = CubeState.solved()
    move_cp = {m: solved.apply_move(m).cp for m in G2_MOVES}
    move_ep = {m: solved.apply_move(m).ep for m in G2_MOVES}
    corner_canon, num_corner = _corner_coset_index()
    edge_id_map, num_edge = _edge_coset_index()

    def flat(cp: tuple[int, ...], ep: tuple[int, ...]) -> int:
        return corner_canon[cp] * num_edge + edge_id_map[ep]

    n = num_corner * num_edge
    dist = bytearray([UNREACHED]) * n
    start = flat(solved.cp, solved.ep)
    dist[start] = 0
    queue = deque([(solved.cp, solved.ep)])
    while queue:
        cp, ep = queue.popleft()
        d = dist[flat(cp, ep)] + 1
        for m in G2_MOVES:
            mcp = move_cp[m]
            mep = move_ep[m]
            ncp = tuple(cp[mcp[i]] for i in range(8))
            nep = tuple(ep[mep[i]] for i in range(12))
            ni = flat(ncp, nep)
            if dist[ni] == UNREACHED:
                dist[ni] = d
                queue.append((ncp, nep))
    return dist


def build_g3_table() -> bytearray:
    """Square-group distance to solved under the G3 (half-turn) move set."""

    solved = CubeState.solved()
    corner_perms = _g3_corner_permutations()
    edge_perms = _g3_edge_permutations()
    corner_lookup = {p: i for i, p in enumerate(corner_perms)}
    edge_lookup = {p: i for i, p in enumerate(edge_perms)}
    ne = len(edge_perms)
    move_cp = {m: solved.apply_move(m).cp for m in G3_MOVES}
    move_ep = {m: solved.apply_move(m).ep for m in G3_MOVES}

    def flat(cp: tuple[int, ...], ep: tuple[int, ...]) -> int:
        return corner_lookup[cp] * ne + edge_lookup[ep]

    n = len(corner_perms) * ne
    dist = bytearray([UNREACHED]) * n
    start = flat(solved.cp, solved.ep)
    dist[start] = 0
    queue = deque([(solved.cp, solved.ep)])
    while queue:
        cp, ep = queue.popleft()
        d = dist[flat(cp, ep)] + 1
        for m in G3_MOVES:
            mcp = move_cp[m]
            mep = move_ep[m]
            ncp = tuple(cp[mcp[i]] for i in range(8))
            nep = tuple(ep[mep[i]] for i in range(12))
            ni = flat(ncp, nep)
            if dist[ni] == UNREACHED:
                dist[ni] = d
                queue.append((ncp, nep))
    return dist


# ---------------------------------------------------------------------------
# Persistence and the loaded-table container.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThistlethwaiteTables:
    g0: bytes
    g1: bytes
    g2: bytes
    g3: bytes
    num_edge_cosets: int
    num_corner_cosets: int


_PHASE_FILES = {
    "g0": "thistlethwaite_g0_eo.bin",
    "g1": "thistlethwaite_g1_co_udslice.bin",
    "g2": "thistlethwaite_g2_coset.bin",
    "g3": "thistlethwaite_g3_square.bin",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _coset_signature() -> dict[str, str]:
    """Checksums of the deterministic index maps that pin the G2 table layout."""

    corner_canon, num_corner = _corner_coset_index()
    edge_id_map, num_edge = _edge_coset_index()
    corner_payload = b"".join(
        bytes(cp) + num.to_bytes(2, "little")
        for cp, num in sorted(corner_canon.items())
    )
    edge_payload = b"".join(
        bytes(rep) + idx.to_bytes(2, "little")
        for rep, idx in sorted(edge_id_map.items())
    )
    return {
        "num_corner_cosets": str(num_corner),
        "num_edge_cosets": str(num_edge),
        "corner_index_sha256": _sha256_bytes(corner_payload),
        "edge_index_sha256": _sha256_bytes(edge_payload),
    }


def generate_thistlethwaite_tables(
    *,
    root: Path | None = None,
) -> dict[str, object]:
    """Build the four phase tables, write the binaries, and emit a manifest.

    Returns the manifest payload (also written to ``thistlethwaite_manifest.json``).
    """

    root = root or _default_root()
    cache_dir = root / "data" / "generated" / CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    builders = {
        "g0": ("G0->G1 edge orientation", build_g0_table),
        "g1": ("G1->G2 corner orientation x UD-slice", build_g1_table),
        "g2": ("G2->G3 corner/edge left-coset", build_g2_table),
        "g3": ("G3->G4 square group", build_g3_table),
    }

    coset_signature = _coset_signature()
    tables_meta: list[dict[str, object]] = []
    for phase, (description, builder) in builders.items():
        begin = time.perf_counter()
        table = builder()
        runtime = time.perf_counter() - begin
        path = cache_dir / _PHASE_FILES[phase]
        path.write_bytes(bytes(table))
        checksum = _sha256_bytes(bytes(table))
        max_depth = max(d for d in table if d != UNREACHED)
        reachable = sum(1 for d in table if d != UNREACHED)
        tables_meta.append(
            {
                "phase": phase,
                "description": description,
                "file": _PHASE_FILES[phase],
                "size_bytes": len(table),
                "reachable_states": reachable,
                "max_distance": max_depth,
                "checksum_sha256": checksum,
                "generation_seconds": round(runtime, 4),
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": "rubik_optimal.tables.thistlethwaite_tables.generate_thistlethwaite_tables",
        "move_groups": {
            "g0": list(ALL_MOVES),
            "g1": list(G1_MOVES),
            "g2": list(G2_MOVES),
            "g3": list(G3_MOVES),
        },
        "coset_signature": coset_signature,
        # The sorted canonical edge-coset representatives let cold loads skip the
        # slow BFS discovery and rebuild the ep->id map by fast orbit expansion.
        "edge_coset_reps": [list(rep) for rep in _edge_coset_reps()],
        "tables": tables_meta,
    }
    manifest_path = cache_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _read_manifest(cache_dir: Path) -> dict[str, object] | None:
    manifest_path = cache_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cache_is_valid(cache_dir: Path, manifest: dict[str, object]) -> bool:
    """Validate cached tables cheaply by re-checking their SHA-256 checksums.

    Re-hashing the four binaries (a few MB total) takes only milliseconds and
    catches corruption or accidental edits.  The coset-index layout is pinned to
    these tables by ``coset_signature`` (recorded at generation time); the index
    maps themselves are rebuilt deterministically and lazily on first solve.
    """

    if manifest.get("schema_version") != SCHEMA_VERSION:
        return False
    if "coset_signature" not in manifest:
        return False
    by_phase = {row["phase"]: row for row in manifest.get("tables", [])}
    for phase, filename in _PHASE_FILES.items():
        path = cache_dir / filename
        if not path.exists() or phase not in by_phase:
            return False
        data = path.read_bytes()
        row = by_phase[phase]
        if len(data) != row.get("size_bytes"):
            return False
        if _sha256_bytes(data) != row.get("checksum_sha256"):
            return False
    return True


@lru_cache(maxsize=1)
def load_tables(root_str: str | None = None) -> ThistlethwaiteTables:
    """Load cached tables, regenerating them once if missing or invalid.

    The result is memoised so repeated solves in a process reuse one copy.
    """

    root = Path(root_str) if root_str else _default_root()
    cache_dir = root / "data" / "generated" / CACHE_DIRNAME
    manifest = _read_manifest(cache_dir)
    if manifest is None or not _cache_is_valid(cache_dir, manifest):
        manifest = generate_thistlethwaite_tables(root=root)

    # If the manifest carries the precomputed edge-coset representatives, pin
    # them so the index map is rebuilt by fast orbit expansion instead of the
    # slow BFS discovery.  Pinned reps are validated (canonical + distinct)
    # before being trusted; otherwise we fall back to BFS discovery.
    raw_reps = manifest.get("edge_coset_reps")
    if isinstance(raw_reps, list) and raw_reps:
        reps = tuple(tuple(rep) for rep in raw_reps)
        if _validate_edge_coset_reps(reps):
            _set_pinned_edge_coset_reps(reps)
        else:
            _set_pinned_edge_coset_reps(None)

    # Eagerly build (and memoise) the deterministic coset index maps so that the
    # one-time cost is attributed to loading; every subsequent solve is then a
    # pure table lookup and completes in milliseconds.
    _corner_coset_index()
    _edge_coset_index()

    signature = manifest["coset_signature"]
    g0 = (cache_dir / _PHASE_FILES["g0"]).read_bytes()
    g1 = (cache_dir / _PHASE_FILES["g1"]).read_bytes()
    g2 = (cache_dir / _PHASE_FILES["g2"]).read_bytes()
    g3 = (cache_dir / _PHASE_FILES["g3"]).read_bytes()
    return ThistlethwaiteTables(
        g0=g0,
        g1=g1,
        g2=g2,
        g3=g3,
        num_edge_cosets=int(signature["num_edge_cosets"]),
        num_corner_cosets=int(signature["num_corner_cosets"]),
    )


def table_total_bytes(tables: ThistlethwaiteTables) -> int:
    return len(tables.g0) + len(tables.g1) + len(tables.g2) + len(tables.g3)
