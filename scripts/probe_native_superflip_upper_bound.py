#!/usr/bin/env python
"""Probe native own-code upper-bound proof search on the superflip.

The saved length-20 solution is used only as a verified upper bound.  A row is
an own-code optimality proof only when the native Korf/IDA* engine exhausts the
search bound below that upper solution length.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES
from rubik_optimal.solvers.optimal_native import _compile
from rubik_optimal.symmetry import root_symmetry_representative_moves
from rubik_optimal.tables.corner_pdb import default_corner_pdb_path
from rubik_optimal.tables.edge_pdb import default_edge_pdb_paths, default_edge_pdb_paths_7, edge_pdbs_7_available


@dataclass(frozen=True)
class ProbeMode:
    mode_id: str
    compact_transpositions: bool
    tt_entries: int
    description: str


MODES = {
    "legacy_4m": ProbeMode(
        "legacy_4m",
        False,
        4_000_000,
        "std::unordered_map exact transposition table, 4M total entries",
    ),
    "compact_4m": ProbeMode(
        "compact_4m",
        True,
        4_000_000,
        "packed open-addressed exact transposition table, 4M total entries",
    ),
    "compact_32m": ProbeMode(
        "compact_32m",
        True,
        32_000_000,
        "packed open-addressed exact transposition table, 32M total entries",
    ),
}


def superflip_cube() -> CubeState:
    return CubeState(cp=tuple(range(8)), co=(0,) * 8, ep=tuple(range(12)), eo=(1,) * 12)


def _csv(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def _root_move_mask_csv(cube: CubeState) -> str | None:
    representatives = root_symmetry_representative_moves(cube)
    if len(representatives) >= len(ALL_MOVES):
        return None
    return ",".join(representatives)


def _load_saved_upper_solution(path: Path, case_id: str) -> tuple[list[str], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload.get("rows", []):
        if row.get("case_id") != case_id:
            continue
        solution = row.get("solution")
        if not isinstance(solution, str) or not solution.strip():
            raise ValueError(f"{path} row {case_id!r} does not contain a solution string")
        if row.get("status") != "exact" or row.get("verified") is not True:
            raise ValueError(f"{path} row {case_id!r} is not a verified exact certificate")
        return solution.split(), {
            "path": str(path),
            "case_id": case_id,
            "status": row.get("status"),
            "verified": row.get("verified"),
            "solution_length": row.get("solution_length"),
            "runtime_seconds": row.get("runtime_seconds"),
            "solver": row.get("solver"),
        }
    raise ValueError(f"{path} does not contain case_id {case_id!r}")


def _edge_pdbs(root: Path, include_seven_edge: bool = False) -> list[Path]:
    paths = list(default_edge_pdb_paths(root=root))
    if include_seven_edge:
        seven_edge_paths = default_edge_pdb_paths_7(root=root)
        if edge_pdbs_7_available(seven_edge_paths):
            paths.extend(seven_edge_paths)
    return paths


def _command_for_mode(args: argparse.Namespace, mode: ProbeMode, upper_solution: list[str]) -> list[str]:
    cube = superflip_cube()
    binary = _compile(ROOT, args.compiler, with_nissy=False)
    command = [
        str(binary),
        "--corner-pdb",
        str(default_corner_pdb_path(root=ROOT)),
        "--cp",
        _csv(cube.cp),
        "--co",
        _csv(cube.co),
        "--ep",
        _csv(cube.ep),
        "--eo",
        _csv(cube.eo),
        "--max-depth",
        str(args.max_depth),
        "--timeout",
        str(args.timeout),
        "--node-limit",
        "0",
        "--tt-entries",
        str(mode.tt_entries),
        "--threads",
        str(args.threads),
        "--split-depth",
        str(args.split_depth),
        "--child-order",
        args.child_order,
        "--upper-solution",
        " ".join(upper_solution),
        "--upper-bound-proof-strategy",
        "single-bound",
        "--symmetry-transpositions",
        "--full-symmetry-transpositions",
    ]
    if args.root_symmetry_prune:
        mask = _root_move_mask_csv(cube)
        if mask is not None:
            command.extend(["--root-move-mask", mask])
    if mode.compact_transpositions:
        command.append("--compact-transpositions")
    for path in _edge_pdbs(ROOT, include_seven_edge=args.seven_edge_pdbs):
        command.extend(["--edge-pdb", str(path)])
    return command


def row_for_mode(args: argparse.Namespace, mode: ProbeMode, upper_solution: list[str]) -> dict[str, object]:
    command = _command_for_mode(args, mode, upper_solution)
    begin = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - begin
    try:
        payload: dict[str, object] = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "failed",
            "solution_moves": [],
            "solution_length": None,
            "error": completed.stderr.strip() or completed.stdout.strip(),
        }
    row = {
        **asdict(mode),
        **payload,
        "return_code": completed.returncode,
        "wrapper_elapsed_seconds": elapsed,
        "command": command,
    }
    # The native binary reports the conditional status "exact_under_root_mask"
    # whenever --root-move-mask restricts the root branching.  The only mask
    # this script ever passes is derived right here from the full 48-element
    # whole-cube symmetry stabilizer of the superflip
    # (root_symmetry_representative_moves): every excluded first move has a
    # stabilizer image inside the mask, so exhausting the masked root tree
    # below the upper solution length still proves unconditional optimality.
    # Accept the conditional status only for that self-derived mask.
    mask_passed = "--root-move-mask" in command
    row["root_mask_source"] = (
        "root_symmetry_representative_moves (full 48-element whole-cube symmetry stabilizer)"
        if mask_passed
        else None
    )
    status_proves_exact = row.get("status") == "exact" or (
        row.get("status") == "exact_under_root_mask" and mask_passed
    )
    row["native_optimality_proved"] = (
        status_proves_exact
        and row.get("upper_solution_verified") is True
        and row.get("upper_bound_proof_exhaustive") is True
        and row.get("exact_certified_by_upper_bound") is True
    )
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--split-depth", type=int, default=3)
    parser.add_argument("--max-depth", type=int, default=20)
    parser.add_argument("--child-order", default="heuristic-desc")
    parser.add_argument("--compiler", default="c++")
    parser.add_argument("--mode", choices=tuple(MODES), action="append", dest="modes")
    parser.add_argument("--root-symmetry-prune", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--seven-edge-pdbs",
        action="store_true",
        help=(
            "Opt in to the 7-edge PDBs as extra --edge-pdb tables when generated "
            "(off by default so the frozen 6-edge thesis configuration reproduces)"
        ),
    )
    parser.add_argument(
        "--upper-source",
        type=Path,
        default=ROOT / "results" / "processed" / "h48_resident_certification_seed_2026_thesis_h48h7_trusted.json",
    )
    parser.add_argument("--upper-case-id", default="superflip_distance_20")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "processed" / "native_superflip_upper_bound_probe_seed_2026.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    upper_solution, upper_source = _load_saved_upper_solution(args.upper_source, args.upper_case_id)
    selected_modes = args.modes or ["legacy_4m", "compact_4m", "compact_32m"]
    rows = [row_for_mode(args, MODES[mode], upper_solution) for mode in selected_modes]
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "target": "superflip",
        "solver": "korf_native_optimal",
        "uses_runtime_h48_or_nissy": False,
        "upper_solution_source": upper_source,
        "upper_solution_length": len(upper_solution),
        "upper_solution": " ".join(upper_solution),
        "proof_policy": "native row proves optimality only if bound below saved upper solution is exhausted",
        "root_mask_status_policy": (
            "the native binary reports the conditional status exact_under_root_mask whenever "
            "--root-move-mask is active; rows accept it as an optimality proof only because the "
            "mask is derived in this script from the full 48-element whole-cube symmetry "
            "stabilizer (root_symmetry_representative_moves), so masked-tree exhaustion implies "
            "unconditional optimality"
        ),
        "max_depth": args.max_depth,
        "timeout_seconds": args.timeout,
        "threads": args.threads,
        "split_depth": args.split_depth,
        "root_symmetry_prune": args.root_symmetry_prune,
        "seven_edge_pdbs": args.seven_edge_pdbs,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
