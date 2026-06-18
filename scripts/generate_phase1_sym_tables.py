#!/usr/bin/env python
"""Generate the Kociemba/Cube-Explorer phase-1 FlipUDSlice symmetry reduction.

Kociemba's symmetry-reduced phase-1 pruning table reduces the raw
``CO x EO x UD-slice`` projection (2,217,093,120 entries) to 140,908,410
entries by quotienting the *combined* ``FlipUDSlice`` coordinate (EO x UD-slice,
2048 * 495 = 1,013,760 values) by the 16 whole-cube symmetries that fix the UD
axis.  This yields Kociemba's 64,430 equivalence classes; combined with the
corner-orientation (twist) coordinate the table holds 64,430 * 2,187 entries.

``FlipUDSlice`` does **not** factor into independent flip/slice actions: the
symmetry conjugation mixes edge orientation with the edge permutation (verified
empirically).  It *is* a well-defined combined coordinate, though, so this
script does all the (reflection-correct) symmetry math in Python via the
validated whole-cube symmetry layer (``src/rubik_optimal/symmetry.py``) and
emits the reduction tables the native probe needs:

- ``flipudslice_classidx[r]`` : equivalence-class index of raw coordinate ``r``;
- ``flipudslice_sym[r]``      : symmetry ``s`` with ``s . r == representative``;
- ``classidx_to_rep[cls]``    : the (orbit-minimum) representative raw coordinate;
- ``class_stab_mask[cls]``    : 16-bit mask of symmetries fixing the representative
                                FlipUDSlice coordinate (its stabilizer subgroup);
- ``sym_twist[s][twist]``     : corner-orientation coordinate after symmetry ``s``;
- ``inv_sym[s]``              : inverse symmetry index.

When a FlipUDSlice representative has a non-trivial stabilizer, the reduced twist
must be canonicalised as the *minimum over the stabilizer coset* (otherwise a
single orbit splits into several reduced indices and the symmetry-reduced BFS
overestimates distances).  ``class_stab_mask`` carries the stabilizer so the
native lookup can take that minimum.

The reduction is computed by transforming only the ~64,430 representatives (16
symmetries each, ~1M facelet transforms), not all 1,013,760 coordinates.  Twist
is conjugated independently (edges do not affect corner orientation, verified).

Coordinate conventions exactly match
``native/kociemba_phase2_probe/kociemba_phase2_probe.cpp``:

- twist (CO): base-3 over corners 0..6;
- flip (EO):  base-2 over edges 0..10 (edge 0 most significant);
- UD-slice:   lexicographic rank of the 4-subset of occupied positions.

Self-checks gate emission; the native loader adds an end-to-end gate (the
resulting symmetry-reduced distances must match the trusted raw phase-1 BFS).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.symmetry import g1_preserving_symmetries

FLIP_COUNT = 2048
UDSLICE_COUNT = 495
TWIST_COUNT = 2187
SYM_COUNT = 16
FLIPUDSLICE_COUNT = FLIP_COUNT * UDSLICE_COUNT  # 1,013,760
CLASS_COUNT = 64430
MAGIC = b"P1SYMR03"

_COMBOS = list(combinations(range(12), 4))
_COMBO_INDEX = {frozenset(combo): index for index, combo in enumerate(_COMBOS)}
_IDENTITY_MATRIX = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def _encode_twist(co: tuple[int, ...]) -> int:
    coord = 0
    for index in range(7):
        coord = coord * 3 + co[index]
    return coord


def _encode_flip(eo: tuple[int, ...]) -> int:
    coord = 0
    for index in range(11):
        coord = (coord << 1) | eo[index]
    return coord


def _encode_udslice(ep: tuple[int, ...]) -> int:
    occupied = frozenset(position for position in range(12) if 8 <= ep[position] <= 11)
    return _COMBO_INDEX[occupied]


def _permutation_parity(perm: list[int]) -> int:
    seen = [False] * len(perm)
    parity = 0
    for start in range(len(perm)):
        if seen[start]:
            continue
        node = start
        length = 0
        while not seen[node]:
            seen[node] = True
            node = perm[node]
            length += 1
        parity ^= (length - 1) & 1
    return parity


def _twist_cube(twist: int) -> CubeState:
    co = [(twist // (3 ** (6 - index))) % 3 for index in range(7)]
    co.append((-sum(co)) % 3)
    return CubeState(co=tuple(co))


def _flipudslice_cube(flip: int, udslice: int) -> CubeState:
    """A reachable cube with the given (flip, UD-slice) coordinate.

    The choice of which slice edge sits where, and of the non-slice arrangement,
    is arbitrary: FlipUDSlice is a well-defined combined coordinate under the 16
    symmetries (verified), so the conjugate coordinate does not depend on it.
    """
    positions = list(_COMBOS[udslice])
    rest = [position for position in range(12) if position not in positions]
    ep = [0] * 12
    for slot, position in enumerate(positions):
        ep[position] = 8 + slot
    for slot, position in enumerate(rest):
        ep[position] = slot
    eo = [(flip >> (10 - index)) & 1 for index in range(11)]
    eo.append(sum(eo) & 1)
    if _permutation_parity(ep) == 1:
        ep[rest[0]], ep[rest[1]] = ep[rest[1]], ep[rest[0]]
    return CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(ep), eo=tuple(eo))


def _matmul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def _inverse_symmetry_indices(symmetries) -> list[int]:
    inv = []
    for s in symmetries:
        found = None
        for index, candidate in enumerate(symmetries):
            if _matmul(s.matrix, candidate.matrix) == _IDENTITY_MATRIX:
                found = index
                break
        if found is None:
            raise RuntimeError(f"no inverse symmetry for {s.name}")
        inv.append(found)
    return inv


@dataclass
class Reduction:
    symmetries: tuple
    inv_sym: list[int]
    sym_twist: list[list[int]]
    classidx: list[int]
    flipudslice_sym: list[int]
    classidx_to_rep: list[int]
    class_stab_mask: list[int]


def build_reduction() -> Reduction:
    symmetries = g1_preserving_symmetries()
    if len(symmetries) != SYM_COUNT or not symmetries[0].is_identity:
        raise RuntimeError("expected 16 G1-preserving symmetries with the identity first")
    inv_sym = _inverse_symmetry_indices(symmetries)

    # Twist conjugation (independent of edges, verified).
    sym_twist = [
        [_encode_twist(symmetry.transform_cube(_twist_cube(twist)).co) for twist in range(TWIST_COUNT)]
        for symmetry in symmetries
    ]

    classidx = [0xFFFFFFFF] * FLIPUDSLICE_COUNT
    flipudslice_sym = [0] * FLIPUDSLICE_COUNT
    classidx_to_rep: list[int] = []
    class_stab_mask: list[int] = []
    for raw in range(FLIPUDSLICE_COUNT):
        if classidx[raw] != 0xFFFFFFFF:
            continue
        cls = len(classidx_to_rep)
        classidx_to_rep.append(raw)
        flip = raw // UDSLICE_COUNT
        udslice = raw % UDSLICE_COUNT
        cube = _flipudslice_cube(flip, udslice)
        stab_mask = 0
        for s, symmetry in enumerate(symmetries):
            image_cube = symmetry.transform_cube(cube)
            image = _encode_flip(image_cube.eo) * UDSLICE_COUNT + _encode_udslice(image_cube.ep)
            if image == raw:
                stab_mask |= 1 << s  # s fixes the representative FlipUDSlice coord
            if classidx[image] == 0xFFFFFFFF:
                classidx[image] = cls
                # s maps raw(rep) -> image, so inv_sym[s] maps image -> rep.
                flipudslice_sym[image] = inv_sym[s]
        class_stab_mask.append(stab_mask)
    if len(classidx_to_rep) != CLASS_COUNT:
        raise RuntimeError(
            f"FlipUDSlice reduction produced {len(classidx_to_rep)} classes, expected {CLASS_COUNT}"
        )
    return Reduction(
        symmetries=symmetries,
        inv_sym=inv_sym,
        sym_twist=sym_twist,
        classidx=classidx,
        flipudslice_sym=flipudslice_sym,
        classidx_to_rep=classidx_to_rep,
        class_stab_mask=class_stab_mask,
    )


def _validate(reduction: Reduction) -> None:
    symmetries = reduction.symmetries
    sym_twist = reduction.sym_twist
    classidx = reduction.classidx
    flipudslice_sym = reduction.flipudslice_sym
    classidx_to_rep = reduction.classidx_to_rep
    inv_sym = reduction.inv_sym
    class_stab_mask = reduction.class_stab_mask

    # Every stabilizer contains the identity (bit 0); the number of classes with
    # a non-trivial stabilizer is small but non-zero (this is what made the naive
    # reduction overestimate distances).
    nontrivial = 0
    for cls, mask in enumerate(class_stab_mask):
        if not (mask & 1):
            raise RuntimeError(f"class {cls} stabilizer missing identity")
        if mask != 1:
            nontrivial += 1
    if nontrivial == 0:
        raise RuntimeError("expected some classes with non-trivial stabilizers")

    if sym_twist[0] != list(range(TWIST_COUNT)):
        raise RuntimeError("identity symmetry must fix twist")
    for s in range(SYM_COUNT):
        if sorted(sym_twist[s]) != list(range(TWIST_COUNT)):
            raise RuntimeError(f"symmetry {s} twist action is not a bijection")
    # Representatives are orbit minima and self-map under the identity symmetry.
    for cls, rep in enumerate(classidx_to_rep):
        if classidx[rep] != cls or flipudslice_sym[rep] != 0:
            raise RuntimeError(f"representative {rep} of class {cls} is inconsistent")
    # Sampled end-to-end reduction check: applying flipudslice_sym[r] to a cube
    # with coordinate r must land on the class representative coordinate.
    sample = list(range(0, FLIPUDSLICE_COUNT, max(1, FLIPUDSLICE_COUNT // 4000)))
    for raw in sample:
        flip = raw // UDSLICE_COUNT
        udslice = raw % UDSLICE_COUNT
        cube = _flipudslice_cube(flip, udslice)
        s = flipudslice_sym[raw]
        image_cube = symmetries[s].transform_cube(cube)
        image = _encode_flip(image_cube.eo) * UDSLICE_COUNT + _encode_udslice(image_cube.ep)
        rep = classidx_to_rep[classidx[raw]]
        if image != rep:
            raise RuntimeError(f"reduction check failed for raw {raw}: sym {s} -> {image}, rep {rep}")
    # inv_sym consistency on twist.
    for s in range(SYM_COUNT):
        for twist in (0, 1, 1000, 2186):
            if sym_twist[inv_sym[s]][sym_twist[s][twist]] != twist:
                raise RuntimeError(f"inv_sym inconsistent for {s}")


def _pack(reduction: Reduction) -> bytes:
    payload = bytearray()
    payload += MAGIC
    payload += struct.pack(
        "<IIIIII",
        SYM_COUNT,
        FLIP_COUNT,
        UDSLICE_COUNT,
        TWIST_COUNT,
        CLASS_COUNT,
        FLIPUDSLICE_COUNT,
    )
    payload += struct.pack(f"<{SYM_COUNT}B", *reduction.inv_sym)
    for s in range(SYM_COUNT):
        payload += struct.pack(f"<{TWIST_COUNT}H", *reduction.sym_twist[s])
    payload += struct.pack(f"<{CLASS_COUNT}I", *reduction.classidx_to_rep)
    payload += struct.pack(f"<{CLASS_COUNT}H", *reduction.class_stab_mask)
    payload += struct.pack(f"<{FLIPUDSLICE_COUNT}H", *reduction.classidx)
    payload += struct.pack(f"<{FLIPUDSLICE_COUNT}B", *reduction.flipudslice_sym)
    return bytes(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "generated" / "phase1_sym_tables.bin",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    begin = time.perf_counter()
    reduction = build_reduction()
    _validate(reduction)
    blob = _pack(reduction)
    elapsed = time.perf_counter() - begin

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(blob)
    checksum = hashlib.sha256(blob).hexdigest()
    nontrivial_stab = sum(1 for mask in reduction.class_stab_mask if mask != 1)
    metadata = {
        "schema_version": 3,
        "table_name": "phase1_sym_tables",
        "description": "Phase-1 FlipUDSlice 16-symmetry reduction (classidx/sym/rep/stab + twist conjugation)",
        "classes_with_nontrivial_stabilizer": nontrivial_stab,
        "profile": args.profile,
        "seed": args.seed,
        "symmetry_group": "16 G1-preserving whole-cube symmetries (UD-axis stabilizer, incl. reflections)",
        "sym_count": SYM_COUNT,
        "flip_count": FLIP_COUNT,
        "udslice_count": UDSLICE_COUNT,
        "twist_count": TWIST_COUNT,
        "flipudslice_count": FLIPUDSLICE_COUNT,
        "class_count": CLASS_COUNT,
        "byte_size": len(blob),
        "sha256": checksum,
        "generation_seconds": elapsed,
        "path": str(args.out.relative_to(ROOT)),
        "source": "src/rubik_optimal/symmetry.py g1_preserving_symmetries()",
        "validated": "twist bijection, representative consistency, sampled reduction round-trip, inv_sym",
    }
    metadata_path = args.out.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
