"""Command-line interface required by the acceptance checks."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from dataclasses import dataclass

from .benchmark import run_benchmarks
from .cube import CubeState
from .distance import DistanceResult, recognize_distance
from .moves import parse_sequence
from .oracle import (
    FastOptimalOracleConfig,
    RaceOptimalOracleConfig,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
    solve_race_optimal,
    solve_resident_race_optimal,
    solve_universal_optimal,
)
from .runtime import default_thread_count
from .scramble import deterministic_scramble
from .search.bfs import bfs_solve
from .solvers.end_to_end import solve_auto_3x3, solve_scramble_inverse
from .solvers.h48_native import H48NativeOracleSession, solve_h48_native_batch, solve_h48_native_optimal
from .solvers.kociemba import solve_kociemba_adapter, solve_kociemba_native_scoped
from .solvers.nissy_external import solve_nissy_core_direct_optimal, solve_nissy_light_optimal, solve_nissy_optimal
from .solvers.rubikoptimal_external import (
    RubikOptimalOracleSession,
    solve_rubikoptimal_external,
    solve_rubikoptimal_external_batch,
)
from .solvers.korf import solve_korf_ida
from .solvers.optimal_native import solve_korf_native_optimal
from .solvers.thistlethwaite import solve_thistlethwaite_native_scoped
from .tables.generation import generate_coordinate_tables
from .tables.h48 import DEFAULT_H48_SOLVER, ORACLE_H48_SOLVER, canonical_h48_solver, highest_available_h48_solver
from .validity import validate_cube
from .verify import verify_solution


@dataclass(frozen=True)
class ParsedInput:
    cube: CubeState
    kind: str
    sequence: list[str] | None = None


def _parse_input(value: str) -> ParsedInput:
    text = value.strip()
    if text == "" or text.lower() == "solved":
        return ParsedInput(CubeState.solved(), "solved", [])
    compact = "".join(text.split())
    if len(compact) == 54 and set(compact) <= set("URFDLB"):
        return ParsedInput(CubeState.from_facelets(compact), "facelets", None)
    sequence = parse_sequence(text)
    return ParsedInput(CubeState.from_sequence(sequence), "sequence", sequence)


def _read_oracle_inputs(args: argparse.Namespace) -> list[str]:
    inputs: list[str] = []
    if args.input_file is not None:
        for line in args.input_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                inputs.append(text)
    if args.states:
        inputs.extend(args.states)
    if args.input_file is None and not args.states:
        for line in sys.stdin:
            text = line.strip()
            if text and not text.startswith("#"):
                inputs.append(text)
    return inputs


def _iter_oracle_inputs(args: argparse.Namespace):
    if args.input_file is not None:
        for line in args.input_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                yield text
    if args.states:
        for text in args.states:
            stripped = text.strip()
            if stripped:
                yield stripped
    if args.input_file is None and not args.states:
        for line in sys.stdin:
            text = line.strip()
            if text and not text.startswith("#"):
                yield text


def _select_h48_solver(args: argparse.Namespace, *, prefer_oracle: bool) -> str:
    """Select H48 strength without weakening high-level exact oracle paths."""

    if args.h48_fastest or prefer_oracle:
        return highest_available_h48_solver(profile=args.h48_profile)
    if args.h48_oracle:
        return ORACLE_H48_SOLVER
    return canonical_h48_solver(args.h48_solver or DEFAULT_H48_SOLVER)


def _use_trusted_h48_table(args: argparse.Namespace, *, prefer_oracle: bool) -> bool:
    """Use trusted generated metadata by default for fast oracle paths."""

    return bool(args.h48_trusted_table or prefer_oracle)


def _note_value(notes: str, key: str) -> str | None:
    prefix = f"{key}="
    for part in notes.split("; "):
        if part.startswith(prefix):
            return part[len(prefix) :].strip()
    return None


def _oracle_row_from_result(index: int, text: str, parsed: ParsedInput, result: object) -> dict[str, object]:
    result_dict = result.to_dict()
    notes = str(result_dict["notes"])
    return {
        "index": index,
        "input": text,
        "input_kind": parsed.kind,
        "status": result_dict["status"],
        "distance": result_dict["solution_length"] if result_dict["status"] == "exact" else None,
        "solution_moves": result_dict["solution_moves"],
        "solution_length": result_dict["solution_length"],
        "metric": result_dict["metric"],
        "verified": result_dict["is_verified"],
        "runtime_seconds": result_dict["runtime_seconds"],
        "expanded_nodes": result_dict["expanded_nodes"],
        "table_bytes": result_dict["table_bytes"],
        "selected_backend": _note_value(notes, "selected_backend"),
        "backend_solver": _note_value(notes, "backend_solver"),
        "notes": notes,
    }


def _oracle_error_row(index: int, text: str, error: str) -> dict[str, object]:
    return {
        "index": index,
        "input": text,
        "input_kind": "invalid",
        "status": "failed",
        "distance": None,
        "solution_moves": [],
        "solution_length": None,
        "metric": "HTM",
        "verified": False,
        "runtime_seconds": 0.0,
        "expanded_nodes": None,
        "table_bytes": 0,
        "selected_backend": None,
        "backend_solver": None,
        "notes": error,
    }


def _solve_parse_error_payload(solver: str, error: str) -> dict[str, object]:
    return {
        "solver_name": solver,
        "solution_moves": [],
        "solution_length": None,
        "metric": "HTM",
        "status": "failed",
        "is_verified": False,
        "expanded_nodes": 0,
        "generated_nodes": 0,
        "notes": error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rubik-optimal")
    sub = parser.add_subparsers(dest="command")

    p_scramble = sub.add_parser("scramble", help="Generate a deterministic scramble")
    p_scramble.add_argument("--length", type=int, default=20)
    p_scramble.add_argument("--seed", type=int, default=2026)

    p_facelets = sub.add_parser(
        "facelets",
        aliases=["random-facelets"],
        help="Generate a deterministic valid facelet state",
    )
    p_facelets.add_argument("--length", type=int, default=20)
    p_facelets.add_argument("--seed", type=int, default=2026)
    p_facelets.add_argument("--offset", type=int, default=0)
    p_facelets.add_argument("--json", action="store_true", help="Include scramble and metadata")

    p_solve = sub.add_parser("solve", help="Solve a cube state or scramble")
    p_solve.add_argument("state", nargs="?", default="solved", help="Facelet string or move sequence from solved")
    p_solve.add_argument(
        "--solver",
        choices=[
            "auto",
            "optimal-native",
            "h48-native",
            "h48-oracle",
            "race-optimal",
            "resident-race-optimal",
            "universal-optimal",
            "native-kociemba",
            "nissy-core-direct",
            "nissy-light",
            "nissy-optimal",
            "rubikoptimal",
            "thistlethwaite",
            "korf",
            "kociemba",
            "adapter",
            "bfs",
            "inverse",
        ],
        default="auto",
    )
    p_solve.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help=(
            "Search depth bound. Only the scoped Python korf solver honors it as given; "
            "the exact native solvers (optimal-native/h48-native/h48-oracle/race/universal/"
            "nissy-core-direct) silently raise it to at least 20, the two-phase solvers "
            "(auto/native-kociemba) derive per-phase caps of at least 12/18 from it, and "
            "thistlethwaite raises its stage 3/4 caps to at least 13/15. Values below those "
            "per-solver minimums are clamped up, not rejected."
        ),
    )
    p_solve.add_argument("--timeout", type=float, default=5.0)
    p_solve.add_argument(
        "--node-limit",
        type=int,
        default=500_000,
        help="Node budget (expanded + generated) for the scoped Python korf IDA* solver",
    )
    p_solve.add_argument("--threads", type=int, default=default_thread_count())
    p_solve.add_argument("--split-depth", type=int, default=3)
    p_solve.add_argument(
        "--native-child-order",
        choices=["heuristic-desc", "heuristic-asc", "move"],
        default="heuristic-desc",
        help="Native IDA* child ordering for exact Korf-style search",
    )
    p_solve.add_argument("--dual-heuristic", action="store_true")
    p_solve.add_argument(
        "--additive-edge-pdbs",
        action="store_true",
        help="Use compatible cost-partitioned edge PDBs in native Korf/IDA* when generated",
    )
    p_solve.add_argument(
        "--seven-edge-pdbs",
        action="store_true",
        help=(
            "Opt in to the 7-edge PDBs in native Korf/IDA* when generated "
            "(off by default so the frozen 6-edge thesis configuration reproduces)"
        ),
    )
    p_solve.add_argument("--nissy-heuristic", action="store_true")
    p_solve.add_argument(
        "--no-nissy-axis-transforms",
        action="store_false",
        dest="nissy_axis_transforms",
        help="Disable axis-transform variants in the native Nissy lower-bound bridge",
    )
    p_solve.add_argument("--nissy-data-dir", type=Path, default=None)
    p_solve.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    p_solve.add_argument("--rubikoptimal-executable", type=Path, default=None)
    p_solve.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    p_solve.add_argument(
        "--h48-start-delay",
        type=float,
        default=0.0,
        help="Delay resident H48 startup in race-based exact solvers so cheaper Nissy attempts can finish first",
    )
    p_solve.add_argument(
        "--universal-portfolio-fallback-timeout",
        type=float,
        default=None,
        help="For universal exact solving, set the late portfolio/Nissy fallback timeout",
    )
    p_solve.add_argument(
        "--universal-fallback-nissy-core-direct-timeout",
        type=float,
        default=10.0,
        help=(
            "For universal exact solving, set the late direct nissy-core cubie-state "
            "fallback timeout after resident H48 misses; negative disables it"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-fallback-timeout",
        type=float,
        default=-1.0,
        help=(
            "For universal exact solving, try table-complete RubikOptimal after the "
            "H48/Nissy portfolio misses; negative disables it"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "For universal exact solving, try table-complete RubikOptimal before the "
            "resident H48 race/batch; negative disables it"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-race-timeout",
        type=float,
        default=-1.0,
        help=(
            "For universal exact solving, race table-complete RubikOptimal concurrently "
            "inside the resident H48/Nissy race; negative disables it"
        ),
    )
    p_solve.add_argument(
        "--universal-resident-race-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "For universal exact solving, run a bounded resident H48/Nissy/RubikOptimal "
            "race before later sequential hard-tail phases; negative disables it"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-symmetry-variants",
        type=int,
        default=0,
        help=(
            "For universal exact solving, try this many non-identity whole-cube "
            "rotations through table-complete RubikOptimal after the direct prepass"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-symmetry-timeout",
        type=float,
        default=None,
        help=(
            "Global RubikOptimal symmetry phase timeout for --universal-rubikoptimal-symmetry-variants; "
            "defaults to --timeout"
        ),
    )
    p_solve.add_argument(
        "--universal-rubikoptimal-symmetry-max-concurrency",
        type=int,
        default=0,
        help=(
            "If positive, race RubikOptimal rotated variants with this many concurrent "
            "processes instead of solving the rotations sequentially in one batch"
        ),
    )
    p_solve.add_argument(
        "--h48-symmetry-variants",
        type=int,
        default=0,
        help="For universal exact solving, try this many non-identity whole-cube rotations through resident H48 first",
    )
    p_solve.add_argument(
        "--h48-symmetry-timeout",
        type=float,
        default=5.0,
        help="Global resident H48 symmetry phase timeout for --h48-symmetry-variants",
    )
    p_solve.add_argument(
        "--nissy-symmetry-variants",
        type=int,
        default=0,
        help="For universal exact solving, try this many non-identity whole-cube rotations through Nissy optimal",
    )
    p_solve.add_argument(
        "--nissy-symmetry-timeout",
        type=float,
        default=None,
        help="Timeout for the Nissy rotational optimal batch; defaults to --timeout",
    )
    p_solve.add_argument(
        "--nissy-core-direct-symmetry-variants",
        type=int,
        default=0,
        help=(
            "For universal exact solving, race this many non-identity whole-cube rotations "
            "through direct nissy-core cubie-state input"
        ),
    )
    p_solve.add_argument(
        "--nissy-core-direct-symmetry-timeout",
        type=float,
        default=None,
        help="Global direct nissy-core symmetry race timeout for --nissy-core-direct-symmetry-variants; defaults to --timeout",
    )
    p_solve.add_argument(
        "--nissy-core-direct-symmetry-max-concurrency",
        type=int,
        default=0,
        help="Maximum direct nissy-core rotation processes to run at once; 0 starts all configured variants",
    )
    p_solve.add_argument(
        "--h48-parallel-symmetry-variants",
        type=int,
        default=0,
        help="For universal exact solving, race this many H48 whole-cube rotations in parallel",
    )
    p_solve.add_argument(
        "--h48-parallel-symmetry-timeout",
        type=float,
        default=5.0,
        help="Global H48 parallel symmetry race timeout for --h48-parallel-symmetry-variants",
    )
    p_solve.add_argument(
        "--h48-parallel-symmetry-max-concurrency",
        type=int,
        default=0,
        help="Maximum H48 rotation processes to run at once; 0 starts all configured variants",
    )
    p_solve.add_argument(
        "--h48-parallel-symmetry-order-by-lower-bound",
        "--symmetry-order-by-h48-lower-bound",
        dest="h48_parallel_symmetry_order_by_lower_bound",
        action="store_true",
        help=(
            "Order whole-cube symmetry candidates by a cheap admissible H48 lower-bound batch "
            "before H48/Nissy/RubikOptimal symmetry search"
        ),
    )
    p_solve.add_argument(
        "--h48-parallel-symmetry-lower-bound-order-timeout",
        "--symmetry-lower-bound-order-timeout",
        dest="h48_parallel_symmetry_lower_bound_order_timeout",
        type=float,
        default=30.0,
        help="Timeout for the H48 lower-bound batch used to order symmetry rotations",
    )
    p_solve.add_argument(
        "--h48-lower-bound-symmetry-variants",
        type=int,
        default=23,
        help=(
            "For universal exact solving, compute H48 lower bounds over this many "
            "non-identity whole-cube rotations before accepting upper/lower certificates"
        ),
    )
    p_solve.add_argument(
        "--kociemba-upper-bound-symmetry-variants",
        type=int,
        default=23,
        help=(
            "For universal exact solving, try this many non-identity whole-cube rotations "
            "through Kociemba as improved upper bounds before accepting upper/lower certificates"
        ),
    )
    p_solve.add_argument(
        "--h48-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "For universal exact solving, spend this many seconds proving no H48 solution "
            "exists below a verified upper bound; 0 disables the bounded proof"
        ),
    )
    p_solve.add_argument(
        "--h48-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help="Only run --h48-upper-bound-proof-timeout when upper minus H48 lower bound is at most this gap",
    )
    p_solve.add_argument(
        "--native-korf-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "For universal exact solving, spend this many seconds in native C++ Korf/IDA* "
            "single-bound proof below a verified upper solution; 0 disables it"
        ),
    )
    p_solve.add_argument(
        "--native-korf-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help=(
            "Only run --native-korf-upper-bound-proof-timeout when upper minus H48 "
            "lower bound is at most this gap"
        ),
    )
    p_solve.add_argument("--upper-solution", default=None, help="Candidate solution used as an upper-bound certificate")
    p_solve.add_argument(
        "--upper-bound-proof-strategy",
        choices=["single-bound", "iterative"],
        default="single-bound",
        help=(
            "For optimal-native with --upper-solution, either prove exactness with one exhaustive "
            "search at upper_length-1 or use classic iterative IDA* bounds"
        ),
    )
    p_solve.add_argument("--h48-solver", default=None)
    p_solve.add_argument("--h48-oracle", action="store_true", help="Use h48h7, nissy-core's oracle-grade optimal H48 profile")
    p_solve.add_argument("--h48-fastest", action="store_true", help="Use the largest generated oracle-grade H48 table for this profile")
    p_solve.add_argument(
        "--h48-trusted-table",
        action="store_true",
        help="Skip the native full-table distribution scan after validating generated H48 metadata",
    )
    p_solve.add_argument(
        "--h48-preload-table",
        action="store_true",
        help="Sequentially touch H48 table pages before solving; useful with --h48-trusted-table on hard states",
    )
    p_solve.add_argument(
        "--h48-auto-min-depth",
        action="store_true",
        help="Start native H48 exact search at its admissible H48 lower bound instead of depth 0",
    )
    p_solve.add_argument("--h48-profile", choices=["quick", "thesis", "stress"], default="thesis")
    p_solve.add_argument("--h48-table", type=Path, default=None)

    p_verify = sub.add_parser("verify", help="Verify a proposed solution")
    p_verify.add_argument("state", help="Facelet string or move sequence from solved")
    p_verify.add_argument("solution", help="Move sequence")

    p_bench = sub.add_parser("benchmark", help="Run benchmark suite")
    p_bench.add_argument("--quick", action="store_true")
    p_bench.add_argument("--profile", choices=["quick", "thesis", "stress"], default=None)
    p_bench.add_argument("--seed", type=int, default=2026)
    p_bench.add_argument("--root", type=Path, default=Path.cwd())

    p_distance = sub.add_parser("distance", help="Recognize exact distance or lower bound")
    p_distance.add_argument("state", nargs="?", default="solved")
    p_distance.add_argument("--bfs-depth", type=int, default=5)
    p_distance.add_argument("--ida-depth", type=int, default=8)
    p_distance.add_argument("--timeout", type=float, default=5.0)
    p_distance.add_argument("--threads", type=int, default=default_thread_count())
    p_distance.add_argument("--optimal-native", action="store_true", help="Use native corner+edge PDB IDA* after BFS")
    p_distance.add_argument("--h48-native", action="store_true", help="Use the in-repo H48 exact backend after BFS")
    p_distance.add_argument("--h48-solver", default="h48h0")
    p_distance.add_argument("--h48-oracle", action="store_true", help="Use h48h7, nissy-core's oracle-grade optimal H48 profile")
    p_distance.add_argument("--h48-fastest", action="store_true", help="Use the largest generated oracle-grade H48 table for this profile")
    p_distance.add_argument(
        "--h48-trusted-table",
        action="store_true",
        help="Skip the native full-table distribution scan after validating generated H48 metadata",
    )
    p_distance.add_argument(
        "--h48-preload-table",
        action="store_true",
        help="Sequentially touch H48 table pages before solving; useful with --h48-trusted-table on hard states",
    )
    p_distance.add_argument(
        "--h48-auto-min-depth",
        action="store_true",
        help="Start native H48 exact search at its admissible H48 lower bound instead of depth 0",
    )
    p_distance.add_argument("--h48-profile", choices=["quick", "thesis", "stress"], default="thesis")
    p_distance.add_argument("--h48-table", type=Path, default=None)

    p_oracle = sub.add_parser("oracle", help="Solve line-delimited states with one shared H48 oracle table load")
    p_oracle.add_argument("states", nargs="*", help="Facelet strings or quoted move sequences; reads stdin if omitted")
    p_oracle.add_argument("--input-file", type=Path, default=None, help="Line-delimited states; blank/comment lines ignored")
    p_oracle.add_argument("--h48-solver", default=ORACLE_H48_SOLVER)
    p_oracle.add_argument("--h48-fastest", action="store_true", help="Use the largest generated oracle-grade H48 table for this profile")
    p_oracle.add_argument(
        "--h48-trusted-table",
        action="store_true",
        help="Skip the native full-table distribution scan after validating generated H48 metadata",
    )
    p_oracle.add_argument(
        "--h48-preload-table",
        action="store_true",
        help="Sequentially touch H48 table pages before solving; useful with --h48-trusted-table on hard states",
    )
    p_oracle.add_argument(
        "--h48-auto-min-depth",
        action="store_true",
        help="Start native H48 exact search at its admissible H48 lower bound instead of depth 0",
    )
    p_oracle.add_argument("--h48-profile", choices=["quick", "thesis", "stress"], default="thesis")
    p_oracle.add_argument("--h48-table", type=Path, default=None)
    p_oracle.add_argument("--timeout", type=float, default=300.0)
    p_oracle.add_argument(
        "--resident-h48-batch-timeout",
        type=float,
        default=30.0,
        help=(
            "Per-state timeout for the universal resident-H48 batch prepass; "
            "negative disables the separate cap"
        ),
    )
    p_oracle.add_argument(
        "--no-universal-portfolio-prepass",
        action="store_true",
        help="Skip the direct-state portfolio prepass before the universal resident-H48 batch",
    )
    p_oracle.add_argument(
        "--universal-portfolio-prepass-timeout",
        type=float,
        default=None,
        help=(
            "Separate timeout for the universal portfolio/Nissy batch prepass; "
            "defaults to --timeout"
        ),
    )
    p_oracle.add_argument(
        "--universal-portfolio-fallback-timeout",
        type=float,
        default=None,
        help=(
            "Separate timeout for the late universal portfolio/Nissy fallback after resident H48; "
            "defaults to the prepass timeout"
        ),
    )
    p_oracle.add_argument(
        "--universal-fallback-nissy-core-direct-timeout",
        type=float,
        default=10.0,
        help=(
            "Separate timeout for the late direct nissy-core cubie-state fallback after "
            "resident H48 misses; negative disables it"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-fallback-timeout",
        type=float,
        default=-1.0,
        help=(
            "With --universal, try table-complete RubikOptimal after resident H48 "
            "and portfolio fallback miss; negative disables it"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "With --universal, try table-complete RubikOptimal before resident H48 "
            "batch/race; negative disables it"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-race-timeout",
        type=float,
        default=-1.0,
        help=(
            "With --universal, race table-complete RubikOptimal concurrently inside "
            "the resident H48/Nissy race; negative disables it"
        ),
    )
    p_oracle.add_argument(
        "--universal-resident-race-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "With --universal, run a bounded resident H48/Nissy/RubikOptimal race "
            "before later sequential hard-tail phases; negative disables it"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-symmetry-variants",
        type=int,
        default=0,
        help=(
            "With --universal, try this many non-identity whole-cube rotations through "
            "table-complete RubikOptimal after the direct RubikOptimal prepass"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-symmetry-timeout",
        type=float,
        default=None,
        help=(
            "Global RubikOptimal symmetry phase timeout for --universal-rubikoptimal-symmetry-variants; "
            "defaults to --timeout"
        ),
    )
    p_oracle.add_argument(
        "--universal-rubikoptimal-symmetry-max-concurrency",
        type=int,
        default=0,
        help=(
            "With --universal, if positive, race RubikOptimal rotated variants with "
            "this many concurrent processes instead of solving them sequentially"
        ),
    )
    p_oracle.add_argument(
        "--h48-symmetry-variants",
        type=int,
        default=0,
        help="With --universal, try this many non-identity whole-cube rotations through resident H48 before the race",
    )
    p_oracle.add_argument(
        "--h48-symmetry-timeout",
        type=float,
        default=5.0,
        help="Global resident H48 symmetry phase timeout for --h48-symmetry-variants",
    )
    p_oracle.add_argument(
        "--nissy-symmetry-variants",
        type=int,
        default=0,
        help="With --universal, try this many non-identity whole-cube rotations through Nissy optimal",
    )
    p_oracle.add_argument(
        "--nissy-symmetry-timeout",
        type=float,
        default=None,
        help="Timeout for the Nissy rotational optimal batch; defaults to --timeout",
    )
    p_oracle.add_argument(
        "--nissy-core-direct-symmetry-variants",
        type=int,
        default=0,
        help=(
            "With --universal, race this many non-identity whole-cube rotations "
            "through direct nissy-core cubie-state input"
        ),
    )
    p_oracle.add_argument(
        "--nissy-core-direct-symmetry-timeout",
        type=float,
        default=None,
        help="Global direct nissy-core symmetry race timeout for --nissy-core-direct-symmetry-variants; defaults to --timeout",
    )
    p_oracle.add_argument(
        "--nissy-core-direct-symmetry-max-concurrency",
        type=int,
        default=0,
        help="Maximum direct nissy-core rotation processes to run at once; 0 starts all configured variants",
    )
    p_oracle.add_argument(
        "--h48-parallel-symmetry-variants",
        type=int,
        default=0,
        help="With --universal, race this many H48 whole-cube rotations in parallel before fallback",
    )
    p_oracle.add_argument(
        "--h48-parallel-symmetry-timeout",
        type=float,
        default=5.0,
        help="Global H48 parallel symmetry race timeout for --h48-parallel-symmetry-variants",
    )
    p_oracle.add_argument(
        "--h48-parallel-symmetry-max-concurrency",
        type=int,
        default=0,
        help="Maximum H48 rotation processes to run at once; 0 starts all configured variants",
    )
    p_oracle.add_argument(
        "--h48-parallel-symmetry-order-by-lower-bound",
        "--symmetry-order-by-h48-lower-bound",
        dest="h48_parallel_symmetry_order_by_lower_bound",
        action="store_true",
        help=(
            "Order whole-cube symmetry candidates by a cheap admissible H48 lower-bound batch "
            "before H48/Nissy/RubikOptimal symmetry search"
        ),
    )
    p_oracle.add_argument(
        "--h48-parallel-symmetry-lower-bound-order-timeout",
        "--symmetry-lower-bound-order-timeout",
        dest="h48_parallel_symmetry_lower_bound_order_timeout",
        type=float,
        default=30.0,
        help="Timeout for the H48 lower-bound batch used to order symmetry rotations",
    )
    p_oracle.add_argument(
        "--h48-lower-bound-symmetry-variants",
        type=int,
        default=23,
        help=(
            "With --universal, compute H48 lower bounds over this many non-identity "
            "whole-cube rotations before accepting upper/lower certificates"
        ),
    )
    p_oracle.add_argument(
        "--kociemba-upper-bound-symmetry-variants",
        type=int,
        default=23,
        help=(
            "With --universal, try this many non-identity whole-cube rotations through "
            "Kociemba as improved upper bounds before accepting upper/lower certificates"
        ),
    )
    p_oracle.add_argument(
        "--h48-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "With --universal, spend this many seconds proving no H48 solution exists "
            "below a verified upper bound; 0 disables the bounded proof"
        ),
    )
    p_oracle.add_argument(
        "--h48-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help="Only run --h48-upper-bound-proof-timeout when upper minus H48 lower bound is at most this gap",
    )
    p_oracle.add_argument(
        "--native-korf-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "With --universal, spend this many seconds in native C++ Korf/IDA* "
            "single-bound proof below a verified upper solution; 0 disables it"
        ),
    )
    p_oracle.add_argument(
        "--native-korf-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help=(
            "Only run --native-korf-upper-bound-proof-timeout when upper minus H48 "
            "lower bound is at most this gap"
        ),
    )
    p_oracle.add_argument(
        "--learned-certificate-log",
        type=Path,
        default=None,
        help="Append newly verified exact universal-oracle rows to this JSONL certificate cache",
    )
    p_oracle.add_argument(
        "--no-universal-certificate-cache",
        action="store_true",
        help="With --universal, skip zero-search exact certificate cache lookup for live-runtime evidence",
    )
    p_oracle.add_argument(
        "--no-universal-upper-lower-certificate",
        action="store_true",
        help="With --universal, skip upper/lower-bound certificate shortcut before live exact backends",
    )
    p_oracle.add_argument(
        "--universal-include-external-label-certificates",
        action="store_true",
        help=(
            "With --universal, allow the exact-certificate cache to also serve rows whose "
            "optimality rests only on a third-party benchmark label; such rows are returned "
            "with status=external_label_exact and an explicit exactness-basis note, never as "
            "plain exact"
        ),
    )
    p_oracle.add_argument("--threads", type=int, default=default_thread_count())
    p_oracle.add_argument("--max-depth", type=int, default=20)
    p_oracle.add_argument(
        "--universal",
        action="store_true",
        help=(
            "Use UniversalOptimalOracle: zero-search certificates first, then one resident H48 batch "
            "for remaining valid state inputs"
        ),
    )
    p_oracle.add_argument(
        "--rubikoptimal",
        action="store_true",
        help="Use the external RubikOptimal exact backend for each valid state input.",
    )
    p_oracle.add_argument("--rubikoptimal-table-dir", type=Path, default=None)
    p_oracle.add_argument("--rubikoptimal-executable", type=Path, default=None)
    p_oracle.add_argument("--rubikoptimal-package-path", type=Path, default=None)
    p_oracle.add_argument("--jsonl", action="store_true", help="Print one JSON result row per input instead of a summary object")
    p_oracle.add_argument(
        "--stream",
        action="store_true",
        help="Keep one resident H48 backend alive and print one JSON row as each input line is solved",
    )

    p_tables = sub.add_parser("tables", help="Generate coordinate move/pruning tables")
    p_tables.add_argument("--quick", action="store_true")
    p_tables.add_argument("--profile", choices=["quick", "thesis", "stress"], default=None)
    p_tables.add_argument("--seed", type=int, default=2026)
    p_tables.add_argument("--root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "scramble":
        if args.length < 0:
            raise SystemExit("--length must be non-negative")
        print(" ".join(deterministic_scramble(args.length, args.seed)))
        return 0

    if args.command in {"facelets", "random-facelets"}:
        if args.length < 0:
            raise SystemExit("--length must be non-negative")
        scramble = deterministic_scramble(args.length, args.seed, offset=args.offset)
        cube = CubeState.from_sequence(scramble)
        facelets = cube.to_facelets()
        if args.json:
            print(
                json.dumps(
                    {
                        "facelets": facelets,
                        "scramble": scramble,
                        "scramble_length": len(scramble),
                        "seed": args.seed,
                        "offset": args.offset,
                        "metric": "HTM",
                        "is_valid": cube.is_valid(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(facelets)
        return 0

    if args.command == "solve":
        try:
            parsed = _parse_input(args.state)
        except ValueError as exc:
            print(json.dumps(_solve_parse_error_payload(args.solver, str(exc)), ensure_ascii=False, indent=2))
            return 1
        cube = parsed.cube
        ok, message = validate_cube(cube)
        if not ok:
            raise SystemExit(message)
        if args.solver == "auto":
            result = solve_auto_3x3(
                cube,
                source_sequence=parsed.sequence,
                # Never derive caps below the phase diameters (12 and 18), or
                # the scoped two-phase leg becomes incomplete by configuration.
                native_phase1_depth=max(args.max_depth, 12),
                native_phase2_depth=max(args.max_depth + 6, 18),
                timeout_seconds=args.timeout,
            )
        elif args.solver == "optimal-native":
            result = solve_korf_native_optimal(
                cube,
                max_depth=max(args.max_depth, 20),
                timeout_seconds=args.timeout,
                threads=args.threads,
                split_depth=args.split_depth,
                child_order=args.native_child_order,
                dual_heuristic=args.dual_heuristic,
                nissy_heuristic=args.nissy_heuristic,
                nissy_axis_transforms=args.nissy_axis_transforms,
                nissy_data_dir=args.nissy_data_dir,
                source_sequence=parsed.sequence,
                upper_solution=parse_sequence(args.upper_solution) if args.upper_solution else None,
                upper_bound_proof_strategy=args.upper_bound_proof_strategy,
                additive_edge_pdbs=args.additive_edge_pdbs,
                use_seven_edge_pdbs=args.seven_edge_pdbs,
            )
        elif args.solver == "native-kociemba":
            result = solve_kociemba_native_scoped(
                cube,
                # Never derive caps below the phase diameters (12 and 18), or
                # the scoped two-phase solver becomes incomplete by configuration.
                phase1_max_depth=max(args.max_depth, 12),
                phase2_max_depth=max(args.max_depth + 6, 18),
                timeout_seconds=args.timeout,
            )
        elif args.solver in {"h48-native", "h48-oracle"}:
            prefer_oracle = args.solver == "h48-oracle"
            h48_solver = _select_h48_solver(args, prefer_oracle=prefer_oracle)
            result = solve_h48_native_optimal(
                cube,
                source_sequence=parsed.sequence,
                solver=h48_solver,
                profile=args.h48_profile,
                table_path=args.h48_table,
                timeout_seconds=args.timeout,
                threads=args.threads,
                max_depth=max(args.max_depth, 20),
                skip_table_check=_use_trusted_h48_table(args, prefer_oracle=prefer_oracle),
                preload_table=args.h48_preload_table,
                auto_min_depth=args.h48_auto_min_depth,
            )
        elif args.solver == "race-optimal":
            h48_solver = _select_h48_solver(args, prefer_oracle=True)
            h48_config = FastOptimalOracleConfig(
                profile=args.h48_profile,
                solver=h48_solver,
                threads=args.threads,
                timeout_seconds=args.timeout,
                max_depth=max(args.max_depth, 20),
                trusted_table=_use_trusted_h48_table(args, prefer_oracle=True),
                preload_table=args.h48_preload_table,
                auto_min_depth=args.h48_auto_min_depth,
                table_path=args.h48_table,
            )
            result = solve_race_optimal(
                cube,
                RaceOptimalOracleConfig(
                    h48=h48_config,
                    timeout_seconds=args.timeout,
                    nissy_threads=min(args.threads, 2),
                    nissy_data_dir=args.nissy_data_dir,
                ),
                source_sequence=parsed.sequence,
            )
        elif args.solver == "resident-race-optimal":
            h48_solver = _select_h48_solver(args, prefer_oracle=True)
            h48_config = FastOptimalOracleConfig(
                profile=args.h48_profile,
                solver=h48_solver,
                threads=args.threads,
                timeout_seconds=args.timeout,
                max_depth=max(args.max_depth, 20),
                trusted_table=_use_trusted_h48_table(args, prefer_oracle=True),
                preload_table=args.h48_preload_table,
                auto_min_depth=args.h48_auto_min_depth,
                table_path=args.h48_table,
            )
            result = solve_resident_race_optimal(
                cube,
                ResidentRaceOptimalOracleConfig(
                    h48=h48_config,
                    timeout_seconds=args.timeout,
                    nissy_threads=min(args.threads, 2),
                    nissy_data_dir=args.nissy_data_dir,
                    h48_start_delay_seconds=args.h48_start_delay,
                ),
                source_sequence=parsed.sequence,
            )
        elif args.solver == "universal-optimal":
            h48_solver = _select_h48_solver(args, prefer_oracle=True)
            h48_config = FastOptimalOracleConfig(
                profile=args.h48_profile,
                solver=h48_solver,
                threads=args.threads,
                timeout_seconds=args.timeout,
                max_depth=max(args.max_depth, 20),
                trusted_table=_use_trusted_h48_table(args, prefer_oracle=True),
                preload_table=args.h48_preload_table,
                auto_min_depth=args.h48_auto_min_depth,
                table_path=args.h48_table,
            )
            result = solve_universal_optimal(
                cube,
                UniversalOptimalOracleConfig(
                    resident_race=ResidentRaceOptimalOracleConfig(
                        h48=h48_config,
                        timeout_seconds=args.timeout,
                        nissy_threads=min(args.threads, 2),
                        nissy_data_dir=args.nissy_data_dir,
                        h48_start_delay_seconds=args.h48_start_delay,
                    ),
                    lower_bound_timeout_seconds=min(args.timeout, 30.0),
                    portfolio_fallback_timeout_seconds=args.universal_portfolio_fallback_timeout,
                    portfolio_fallback_nissy_core_direct_timeout_seconds=(
                        args.universal_fallback_nissy_core_direct_timeout
                    ),
                    rubikoptimal_prepass_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_prepass_timeout < 0
                        else args.universal_rubikoptimal_prepass_timeout
                    ),
                    rubikoptimal_symmetry_variants=max(
                        0,
                        args.universal_rubikoptimal_symmetry_variants,
                    ),
                    rubikoptimal_symmetry_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_symmetry_timeout is None
                        or args.universal_rubikoptimal_symmetry_timeout < 0
                        else args.universal_rubikoptimal_symmetry_timeout
                    ),
                    rubikoptimal_symmetry_max_concurrency=max(
                        0,
                        args.universal_rubikoptimal_symmetry_max_concurrency,
                    ),
                    rubikoptimal_race_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_race_timeout < 0
                        else args.universal_rubikoptimal_race_timeout
                    ),
                    resident_race_prepass_timeout_seconds=(
                        None
                        if args.universal_resident_race_prepass_timeout < 0
                        else args.universal_resident_race_prepass_timeout
                    ),
                    rubikoptimal_fallback_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_fallback_timeout < 0
                        else args.universal_rubikoptimal_fallback_timeout
                    ),
                    rubikoptimal_executable=args.rubikoptimal_executable,
                    rubikoptimal_package_path=args.rubikoptimal_package_path,
                    rubikoptimal_table_dir=args.rubikoptimal_table_dir,
                    resident_h48_symmetry_variants=max(0, args.h48_symmetry_variants),
                    resident_h48_symmetry_timeout_seconds=(
                        None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
                    ),
                    nissy_symmetry_variants=max(0, args.nissy_symmetry_variants),
                    nissy_symmetry_timeout_seconds=args.nissy_symmetry_timeout,
                    nissy_core_direct_symmetry_variants=max(
                        0, args.nissy_core_direct_symmetry_variants
                    ),
                    nissy_core_direct_symmetry_timeout_seconds=(
                        args.nissy_core_direct_symmetry_timeout
                    ),
                    nissy_core_direct_symmetry_max_concurrency=max(
                        0, args.nissy_core_direct_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_variants=max(0, args.h48_parallel_symmetry_variants),
                    parallel_h48_symmetry_timeout_seconds=(
                        None
                        if args.h48_parallel_symmetry_timeout < 0
                        else args.h48_parallel_symmetry_timeout
                    ),
                    parallel_h48_symmetry_max_concurrency=max(
                        0, args.h48_parallel_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_order_by_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    parallel_h48_symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    symmetry_order_by_h48_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    lower_bound_symmetry_variants=max(0, args.h48_lower_bound_symmetry_variants),
                    kociemba_upper_bound_symmetry_variants=max(
                        0,
                        args.kociemba_upper_bound_symmetry_variants,
                    ),
                    h48_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.h48_upper_bound_proof_timeout,
                    ),
                    h48_upper_bound_proof_max_gap=max(
                        1,
                        args.h48_upper_bound_proof_max_gap,
                    ),
                    native_korf_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.native_korf_upper_bound_proof_timeout,
                    ),
                    native_korf_upper_bound_proof_max_gap=max(
                        1,
                        args.native_korf_upper_bound_proof_max_gap,
                    ),
                ),
                source_sequence=parsed.sequence,
            )
        elif args.solver == "nissy-light":
            result = solve_nissy_light_optimal(
                cube,
                source_sequence=parsed.sequence,
                timeout_seconds=args.timeout,
                threads=args.threads,
            )
        elif args.solver == "nissy-core-direct":
            if args.h48_fastest:
                h48_solver = highest_available_h48_solver(profile=args.h48_profile)
            elif args.h48_solver is not None and not args.h48_oracle:
                h48_solver = canonical_h48_solver(args.h48_solver)
            else:
                h48_solver = ORACLE_H48_SOLVER
            result = solve_nissy_core_direct_optimal(
                cube,
                solver=h48_solver,
                profile=args.h48_profile,
                table_path=args.h48_table,
                timeout_seconds=args.timeout,
                threads=args.threads,
                max_depth=max(args.max_depth, 20),
            )
        elif args.solver == "nissy-optimal":
            result = solve_nissy_optimal(
                cube,
                source_sequence=parsed.sequence,
                timeout_seconds=args.timeout,
                threads=args.threads,
            )
        elif args.solver == "rubikoptimal":
            result = solve_rubikoptimal_external(
                cube,
                timeout_seconds=args.timeout,
                executable=args.rubikoptimal_executable,
                package_path=args.rubikoptimal_package_path,
                table_dir=args.rubikoptimal_table_dir,
            )
        elif args.solver == "thistlethwaite":
            result = solve_thistlethwaite_native_scoped(
                cube,
                stage1_max_depth=7,
                stage2_max_depth=8,
                stage3_max_depth=max(args.max_depth, 13),
                stage4_max_depth=max(args.max_depth, 15),
                stage2_candidate_limit=64,
                stage3_candidate_limit=8,
                stage4_candidate_limit=8,
                timeout_seconds=args.timeout,
            )
        elif args.solver == "korf":
            result = solve_korf_ida(
                cube,
                max_depth=args.max_depth,
                timeout_seconds=args.timeout,
                node_limit=args.node_limit,
            )
        elif args.solver == "bfs":
            bfs = bfs_solve(cube, max_depth=args.max_depth)
            solution = bfs.solution or []
            verification = verify_solution(cube, solution) if bfs.solution is not None else None
            result = {
                "solver_name": "bfs_shallow",
                "solution_moves": solution,
                "solution_length": len(solution) if bfs.solution is not None else None,
                "status": bfs.status,
                "is_verified": bool(verification and verification.ok),
                "expanded_nodes": bfs.expanded_nodes,
                "generated_nodes": bfs.generated_nodes,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if bfs.status in {"failed", "timeout"} else 0
        elif args.solver == "inverse":
            if parsed.sequence is None:
                raise SystemExit("--solver inverse is only valid when the input is a move sequence, not facelets")
            result = solve_scramble_inverse(cube, parsed.sequence)
        else:
            result = solve_kociemba_adapter(cube)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        # Mirror the verify/oracle exit-code conventions: a timed-out or failed
        # solve must be detectable from the shell, not only from the JSON payload.
        return 1 if result.status in {"failed", "timeout"} else 0

    if args.command == "verify":
        try:
            cube = _parse_input(args.state).cube
        except ValueError as exc:
            print(
                json.dumps(
                    {"ok": False, "move_count": 0, "message": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        result = verify_solution(cube, args.solution)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    if args.command == "benchmark":
        profile = args.profile or ("quick" if args.quick else "thesis")
        paths = run_benchmarks(seed=args.seed, profile=profile, root=args.root)
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
        return 0

    if args.command == "distance":
        try:
            cube = _parse_input(args.state).cube
        except ValueError as exc:
            result = DistanceResult(None, "invalid_state", "parse", 0.0, 0, str(exc))
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            # Nonzero exit for unparseable input, matching the solve command.
            return 1
        h48_solver = _select_h48_solver(args, prefer_oracle=args.h48_oracle)
        result = recognize_distance(
            cube,
            bfs_depth=args.bfs_depth,
            ida_depth=args.ida_depth,
            timeout_seconds=args.timeout,
            native_optimal=args.optimal_native,
            h48_native=args.h48_native or args.h48_oracle,
            h48_solver=h48_solver,
            h48_profile=args.h48_profile,
            h48_table_path=args.h48_table,
            threads=args.threads,
            h48_skip_table_check=_use_trusted_h48_table(args, prefer_oracle=args.h48_oracle),
            h48_preload_table=args.h48_preload_table,
            h48_auto_min_depth=args.h48_auto_min_depth,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "oracle":
        if args.rubikoptimal and args.universal:
            raise SystemExit("--rubikoptimal cannot be combined with --universal")
        h48_solver = (
            highest_available_h48_solver(profile=args.h48_profile)
            if args.h48_fastest
            else canonical_h48_solver(args.h48_solver)
        )
        # Under the explicit external-label opt-in, certificate-cache rows whose
        # optimality rests on a third-party benchmark label are reported as
        # status=external_label_exact. They count as command success, but the
        # strict all_exact flag below never includes them.
        oracle_accepted_statuses = (
            {"exact", "external_label_exact"}
            if args.universal and args.universal_include_external_label_certificates
            else {"exact"}
        )
        if args.stream:
            all_exact = True
            all_accepted = True
            all_verified = True
            saw_input = False
            if args.rubikoptimal:
                with RubikOptimalOracleSession(
                    executable=args.rubikoptimal_executable,
                    package_path=args.rubikoptimal_package_path,
                    table_dir=args.rubikoptimal_table_dir,
                ) as session:
                    for index, text in enumerate(_iter_oracle_inputs(args)):
                        saw_input = True
                        try:
                            parsed = _parse_input(text)
                            ok, message = validate_cube(parsed.cube)
                            if not ok:
                                row = _oracle_error_row(index, text, message)
                            else:
                                result = session.solve(
                                    parsed.cube,
                                    timeout_seconds=args.timeout,
                                )
                                row = _oracle_row_from_result(index, text, parsed, result)
                        except Exception as exc:
                            row = _oracle_error_row(index, text, str(exc))
                        all_exact = all_exact and row["status"] == "exact"
                        all_accepted = all_accepted and row["status"] in oracle_accepted_statuses
                        all_verified = all_verified and row["verified"] is True
                        print(json.dumps(row, ensure_ascii=False), flush=True)
            elif args.universal:
                h48_config = FastOptimalOracleConfig(
                    profile=args.h48_profile,
                    solver=h48_solver,
                    threads=args.threads,
                    timeout_seconds=args.timeout,
                    max_depth=max(args.max_depth, 20),
                    trusted_table=True,
                    preload_table=args.h48_preload_table,
                    auto_min_depth=args.h48_auto_min_depth,
                    table_path=args.h48_table,
                )
                config = UniversalOptimalOracleConfig(
                    resident_race=ResidentRaceOptimalOracleConfig(
                        h48=h48_config,
                        timeout_seconds=args.timeout,
                        nissy_threads=min(args.threads, 2),
                        include_h48=True,
                        include_nissy=True,
                        h48_start_delay_seconds=0.0,
                    ),
                    prefer_resident_h48_batch_for_state_input=False,
                    resident_h48_batch_timeout_seconds=None,
                    try_portfolio_batch_before_resident_h48_batch=False,
                    portfolio_fallback_timeout_seconds=args.universal_portfolio_fallback_timeout,
                    portfolio_fallback_nissy_core_direct_timeout_seconds=(
                        args.universal_fallback_nissy_core_direct_timeout
                    ),
                    rubikoptimal_prepass_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_prepass_timeout < 0
                        else args.universal_rubikoptimal_prepass_timeout
                    ),
                    rubikoptimal_symmetry_variants=max(
                        0,
                        args.universal_rubikoptimal_symmetry_variants,
                    ),
                    rubikoptimal_symmetry_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_symmetry_timeout is None
                        or args.universal_rubikoptimal_symmetry_timeout < 0
                        else args.universal_rubikoptimal_symmetry_timeout
                    ),
                    rubikoptimal_symmetry_max_concurrency=max(
                        0,
                        args.universal_rubikoptimal_symmetry_max_concurrency,
                    ),
                    rubikoptimal_race_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_race_timeout < 0
                        else args.universal_rubikoptimal_race_timeout
                    ),
                    resident_race_prepass_timeout_seconds=(
                        None
                        if args.universal_resident_race_prepass_timeout < 0
                        else args.universal_resident_race_prepass_timeout
                    ),
                    rubikoptimal_fallback_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_fallback_timeout < 0
                        else args.universal_rubikoptimal_fallback_timeout
                    ),
                    rubikoptimal_executable=args.rubikoptimal_executable,
                    rubikoptimal_package_path=args.rubikoptimal_package_path,
                    rubikoptimal_table_dir=args.rubikoptimal_table_dir,
                    resident_h48_symmetry_variants=max(0, args.h48_symmetry_variants),
                    resident_h48_symmetry_timeout_seconds=(
                        None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
                    ),
                    nissy_symmetry_variants=max(0, args.nissy_symmetry_variants),
                    nissy_symmetry_timeout_seconds=args.nissy_symmetry_timeout,
                    nissy_core_direct_symmetry_variants=max(
                        0, args.nissy_core_direct_symmetry_variants
                    ),
                    nissy_core_direct_symmetry_timeout_seconds=(
                        args.nissy_core_direct_symmetry_timeout
                    ),
                    nissy_core_direct_symmetry_max_concurrency=max(
                        0, args.nissy_core_direct_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_variants=max(0, args.h48_parallel_symmetry_variants),
                    parallel_h48_symmetry_timeout_seconds=(
                        None
                        if args.h48_parallel_symmetry_timeout < 0
                        else args.h48_parallel_symmetry_timeout
                    ),
                    parallel_h48_symmetry_max_concurrency=max(
                        0, args.h48_parallel_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_order_by_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    parallel_h48_symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    symmetry_order_by_h48_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    lower_bound_symmetry_variants=max(0, args.h48_lower_bound_symmetry_variants),
                    kociemba_upper_bound_symmetry_variants=max(
                        0,
                        args.kociemba_upper_bound_symmetry_variants,
                    ),
                    h48_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.h48_upper_bound_proof_timeout,
                    ),
                    h48_upper_bound_proof_max_gap=max(
                        1,
                        args.h48_upper_bound_proof_max_gap,
                    ),
                    native_korf_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.native_korf_upper_bound_proof_timeout,
                    ),
                    native_korf_upper_bound_proof_max_gap=max(
                        1,
                        args.native_korf_upper_bound_proof_max_gap,
                    ),
                    learned_certificate_artifact=args.learned_certificate_log,
                    try_certificate_cache=not args.no_universal_certificate_cache,
                    try_upper_lower_certificate=not args.no_universal_upper_lower_certificate,
                    include_external_label_certificates=(
                        args.universal_include_external_label_certificates
                    ),
                )
                with UniversalOptimalOracle(config) as oracle:
                    for index, text in enumerate(_iter_oracle_inputs(args)):
                        saw_input = True
                        try:
                            parsed = _parse_input(text)
                            ok, message = validate_cube(parsed.cube)
                            if not ok:
                                row = _oracle_error_row(index, text, message)
                            else:
                                result = oracle.solve(parsed.cube, source_sequence=parsed.sequence)
                                row = _oracle_row_from_result(index, text, parsed, result)
                        except Exception as exc:
                            row = _oracle_error_row(index, text, str(exc))
                        all_exact = all_exact and row["status"] == "exact"
                        all_accepted = all_accepted and row["status"] in oracle_accepted_statuses
                        all_verified = all_verified and row["verified"] is True
                        print(json.dumps(row, ensure_ascii=False), flush=True)
            else:
                with H48NativeOracleSession(
                    solver=h48_solver,
                    profile=args.h48_profile,
                    table_path=args.h48_table,
                    threads=args.threads,
                    max_depth=max(args.max_depth, 20),
                    skip_table_check=args.h48_trusted_table,
                    preload_table=args.h48_preload_table,
                    auto_min_depth=args.h48_auto_min_depth,
                    search_timeout_seconds=args.timeout,
                ) as session:
                    for index, text in enumerate(_iter_oracle_inputs(args)):
                        saw_input = True
                        try:
                            parsed = _parse_input(text)
                            ok, message = validate_cube(parsed.cube)
                            if not ok:
                                row = _oracle_error_row(index, text, message)
                            else:
                                result = session.solve(parsed.cube, timeout_seconds=args.timeout)
                                row = _oracle_row_from_result(index, text, parsed, result)
                        except Exception as exc:
                            row = _oracle_error_row(index, text, str(exc))
                        all_exact = all_exact and row["status"] == "exact"
                        all_accepted = all_accepted and row["status"] in oracle_accepted_statuses
                        all_verified = all_verified and row["verified"] is True
                        print(json.dumps(row, ensure_ascii=False), flush=True)
            if not saw_input:
                raise SystemExit("oracle --stream requires at least one state from arguments, --input-file, or stdin")
            return 0 if all_accepted and all_verified else 1

        inputs = _read_oracle_inputs(args)
        if not inputs:
            raise SystemExit("oracle requires at least one state from arguments, --input-file, or stdin")

        rows: list[dict[str, object] | None] = [None] * len(inputs)
        valid_inputs: list[tuple[int, str, ParsedInput]] = []
        for index, text in enumerate(inputs):
            try:
                parsed = _parse_input(text)
                ok, message = validate_cube(parsed.cube)
                if not ok:
                    rows[index] = _oracle_error_row(index, text, message)
                    continue
                valid_inputs.append((index, text, parsed))
            except Exception as exc:
                rows[index] = _oracle_error_row(index, text, str(exc))

        batch_wall_seconds = 0.0
        effective_trusted_h48_table = bool(args.h48_trusted_table or args.universal)
        resident_h48_batch_timeout: float | None = None
        if valid_inputs:
            begin = time.perf_counter()
            if args.universal:
                resident_h48_batch_timeout = (
                    None
                    if args.resident_h48_batch_timeout < 0
                    else min(float(args.timeout), float(args.resident_h48_batch_timeout))
                )
                h48_config = FastOptimalOracleConfig(
                    profile=args.h48_profile,
                    solver=h48_solver,
                    threads=args.threads,
                    timeout_seconds=args.timeout,
                    max_depth=max(args.max_depth, 20),
                    trusted_table=effective_trusted_h48_table,
                    preload_table=args.h48_preload_table,
                    auto_min_depth=args.h48_auto_min_depth,
                    table_path=args.h48_table,
                )
                config = UniversalOptimalOracleConfig(
                    resident_race=ResidentRaceOptimalOracleConfig(
                        h48=h48_config,
                        timeout_seconds=args.timeout,
                        nissy_threads=min(args.threads, 2),
                        include_h48=True,
                        include_nissy=True,
                        h48_start_delay_seconds=0.0,
                    ),
                    prefer_resident_h48_batch_for_state_input=(
                        args.universal_rubikoptimal_race_timeout < 0
                    ),
                    resident_h48_batch_timeout_seconds=resident_h48_batch_timeout,
                    try_portfolio_batch_before_resident_h48_batch=(
                        not args.no_universal_portfolio_prepass
                    ),
                    portfolio_prepass_timeout_seconds=args.universal_portfolio_prepass_timeout,
                    portfolio_fallback_timeout_seconds=args.universal_portfolio_fallback_timeout,
                    portfolio_fallback_nissy_core_direct_timeout_seconds=(
                        args.universal_fallback_nissy_core_direct_timeout
                    ),
                    rubikoptimal_prepass_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_prepass_timeout < 0
                        else args.universal_rubikoptimal_prepass_timeout
                    ),
                    rubikoptimal_symmetry_variants=max(
                        0,
                        args.universal_rubikoptimal_symmetry_variants,
                    ),
                    rubikoptimal_symmetry_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_symmetry_timeout is None
                        or args.universal_rubikoptimal_symmetry_timeout < 0
                        else args.universal_rubikoptimal_symmetry_timeout
                    ),
                    rubikoptimal_symmetry_max_concurrency=max(
                        0,
                        args.universal_rubikoptimal_symmetry_max_concurrency,
                    ),
                    rubikoptimal_race_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_race_timeout < 0
                        else args.universal_rubikoptimal_race_timeout
                    ),
                    resident_race_prepass_timeout_seconds=(
                        None
                        if args.universal_resident_race_prepass_timeout < 0
                        else args.universal_resident_race_prepass_timeout
                    ),
                    rubikoptimal_fallback_timeout_seconds=(
                        None
                        if args.universal_rubikoptimal_fallback_timeout < 0
                        else args.universal_rubikoptimal_fallback_timeout
                    ),
                    rubikoptimal_executable=args.rubikoptimal_executable,
                    rubikoptimal_package_path=args.rubikoptimal_package_path,
                    rubikoptimal_table_dir=args.rubikoptimal_table_dir,
                    resident_h48_symmetry_variants=max(0, args.h48_symmetry_variants),
                    resident_h48_symmetry_timeout_seconds=(
                        None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
                    ),
                    nissy_symmetry_variants=max(0, args.nissy_symmetry_variants),
                    nissy_symmetry_timeout_seconds=args.nissy_symmetry_timeout,
                    nissy_core_direct_symmetry_variants=max(
                        0, args.nissy_core_direct_symmetry_variants
                    ),
                    nissy_core_direct_symmetry_timeout_seconds=(
                        args.nissy_core_direct_symmetry_timeout
                    ),
                    nissy_core_direct_symmetry_max_concurrency=max(
                        0, args.nissy_core_direct_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_variants=max(0, args.h48_parallel_symmetry_variants),
                    parallel_h48_symmetry_timeout_seconds=(
                        None
                        if args.h48_parallel_symmetry_timeout < 0
                        else args.h48_parallel_symmetry_timeout
                    ),
                    parallel_h48_symmetry_max_concurrency=max(
                        0, args.h48_parallel_symmetry_max_concurrency
                    ),
                    parallel_h48_symmetry_order_by_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    parallel_h48_symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    symmetry_order_by_h48_lower_bound=(
                        args.h48_parallel_symmetry_order_by_lower_bound
                    ),
                    symmetry_lower_bound_order_timeout_seconds=max(
                        0.001,
                        args.h48_parallel_symmetry_lower_bound_order_timeout,
                    ),
                    lower_bound_symmetry_variants=max(0, args.h48_lower_bound_symmetry_variants),
                    kociemba_upper_bound_symmetry_variants=max(
                        0,
                        args.kociemba_upper_bound_symmetry_variants,
                    ),
                    h48_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.h48_upper_bound_proof_timeout,
                    ),
                    h48_upper_bound_proof_max_gap=max(
                        1,
                        args.h48_upper_bound_proof_max_gap,
                    ),
                    native_korf_upper_bound_proof_timeout_seconds=max(
                        0.0,
                        args.native_korf_upper_bound_proof_timeout,
                    ),
                    native_korf_upper_bound_proof_max_gap=max(
                        1,
                        args.native_korf_upper_bound_proof_max_gap,
                    ),
                    learned_certificate_artifact=args.learned_certificate_log,
                    try_certificate_cache=not args.no_universal_certificate_cache,
                    try_upper_lower_certificate=not args.no_universal_upper_lower_certificate,
                    include_external_label_certificates=(
                        args.universal_include_external_label_certificates
                    ),
                )
                with UniversalOptimalOracle(config) as oracle:
                    results = oracle.solve_many([parsed.cube for _, _, parsed in valid_inputs])
            elif args.rubikoptimal:
                results = solve_rubikoptimal_external_batch(
                    [parsed.cube for _, _, parsed in valid_inputs],
                    timeout_seconds=args.timeout * max(1, len(valid_inputs)),
                    executable=args.rubikoptimal_executable,
                    package_path=args.rubikoptimal_package_path,
                    table_dir=args.rubikoptimal_table_dir,
                )
            else:
                results = solve_h48_native_batch(
                    [parsed.cube for _, _, parsed in valid_inputs],
                    solver=h48_solver,
                    profile=args.h48_profile,
                    table_path=args.h48_table,
                    timeout_seconds=args.timeout,
                    threads=args.threads,
                    max_depth=max(args.max_depth, 20),
                    skip_table_check=effective_trusted_h48_table,
                    preload_table=args.h48_preload_table,
                    auto_min_depth=args.h48_auto_min_depth,
                )
            batch_wall_seconds = time.perf_counter() - begin
            for (index, text, parsed), result in zip(valid_inputs, results):
                rows[index] = _oracle_row_from_result(index, text, parsed, result)

        final_rows = [row for row in rows if row is not None]
        all_exact = bool(final_rows) and all(row["status"] == "exact" for row in final_rows)
        all_accepted = bool(final_rows) and all(
            row["status"] in oracle_accepted_statuses for row in final_rows
        )
        all_verified = bool(final_rows) and all(row["verified"] is True for row in final_rows)
        external_label_exact_rows = sum(
            1 for row in final_rows if row["status"] == "external_label_exact"
        )
        if args.jsonl:
            for row in final_rows:
                print(json.dumps(row, ensure_ascii=False))
        else:
            payload = {
                "schema_version": 1,
                "command": "oracle",
                "backend": (
                    "rubikoptimal_external"
                    if args.rubikoptimal
                    else "universal_optimal_oracle"
                    if args.universal and args.universal_rubikoptimal_race_timeout >= 0
                    else "universal_resident_h48_batch"
                    if args.universal
                    else "h48_native_batch"
                ),
                "solver": "rubikoptimal_external" if args.rubikoptimal else h48_solver,
                "rubikoptimal": args.rubikoptimal,
                "rubikoptimal_table_dir": (
                    str(args.rubikoptimal_table_dir) if args.rubikoptimal_table_dir is not None else None
                ),
                "rubikoptimal_executable": (
                    str(args.rubikoptimal_executable) if args.rubikoptimal_executable is not None else None
                ),
                "rubikoptimal_package_path": (
                    str(args.rubikoptimal_package_path) if args.rubikoptimal_package_path is not None else None
                ),
                "profile": args.h48_profile,
                "metric": "HTM",
                "max_depth": max(args.max_depth, 20),
                "timeout_seconds": args.timeout,
                "threads": args.threads,
                "universal_oracle": args.universal,
                "prefer_resident_h48_batch_for_state_input": args.universal,
                "resident_h48_batch_timeout_seconds": resident_h48_batch_timeout,
                "resident_h48_symmetry_variants": max(0, args.h48_symmetry_variants) if args.universal else 0,
                "resident_h48_symmetry_timeout_seconds": (
                    None
                    if args.h48_symmetry_timeout < 0
                    else args.h48_symmetry_timeout
                )
                if args.universal
                else None,
                "parallel_h48_symmetry_variants": (
                    max(0, args.h48_parallel_symmetry_variants) if args.universal else 0
                ),
                "parallel_h48_symmetry_timeout_seconds": (
                    None
                    if args.h48_parallel_symmetry_timeout < 0
                    else args.h48_parallel_symmetry_timeout
                )
                if args.universal
                else None,
                "parallel_h48_symmetry_max_concurrency": (
                    max(0, args.h48_parallel_symmetry_max_concurrency) if args.universal else 0
                ),
                "parallel_h48_symmetry_order_by_lower_bound": (
                    args.h48_parallel_symmetry_order_by_lower_bound if args.universal else False
                ),
                "parallel_h48_symmetry_lower_bound_order_timeout_seconds": (
                    max(0.001, args.h48_parallel_symmetry_lower_bound_order_timeout)
                    if args.universal
                    else None
                ),
                "symmetry_order_by_h48_lower_bound": (
                    args.h48_parallel_symmetry_order_by_lower_bound if args.universal else False
                ),
                "symmetry_lower_bound_order_timeout_seconds": (
                    max(0.001, args.h48_parallel_symmetry_lower_bound_order_timeout)
                    if args.universal
                    else None
                ),
                "nissy_symmetry_variants": (
                    max(0, args.nissy_symmetry_variants) if args.universal else 0
                ),
                "nissy_symmetry_timeout_seconds": args.nissy_symmetry_timeout if args.universal else None,
                "nissy_core_direct_symmetry_variants": (
                    max(0, args.nissy_core_direct_symmetry_variants) if args.universal else 0
                ),
                "nissy_core_direct_symmetry_timeout_seconds": (
                    args.nissy_core_direct_symmetry_timeout if args.universal else None
                ),
                "nissy_core_direct_symmetry_max_concurrency": (
                    max(0, args.nissy_core_direct_symmetry_max_concurrency)
                    if args.universal
                    else 0
                ),
                "h48_lower_bound_symmetry_variants": (
                    max(0, args.h48_lower_bound_symmetry_variants) if args.universal else 0
                ),
                "kociemba_upper_bound_symmetry_variants": (
                    max(0, args.kociemba_upper_bound_symmetry_variants)
                    if args.universal
                    else 0
                ),
                "h48_upper_bound_proof_timeout_seconds": (
                    max(0.0, args.h48_upper_bound_proof_timeout) if args.universal else 0.0
                ),
                "h48_upper_bound_proof_max_gap": (
                    max(1, args.h48_upper_bound_proof_max_gap) if args.universal else 1
                ),
                "native_korf_upper_bound_proof_timeout_seconds": (
                    max(0.0, args.native_korf_upper_bound_proof_timeout)
                    if args.universal
                    else 0.0
                ),
                "native_korf_upper_bound_proof_max_gap": (
                    max(1, args.native_korf_upper_bound_proof_max_gap)
                    if args.universal
                    else 1
                ),
                "try_portfolio_batch_before_resident_h48_batch": (
                    bool(args.universal and not args.no_universal_portfolio_prepass)
                ),
                "portfolio_prepass_timeout_seconds": (
                    args.universal_portfolio_prepass_timeout if args.universal else None
                ),
                "portfolio_fallback_timeout_seconds": (
                    args.universal_portfolio_fallback_timeout if args.universal else None
                ),
                "portfolio_fallback_nissy_core_direct_timeout_seconds": (
                    args.universal_fallback_nissy_core_direct_timeout if args.universal else None
                ),
                "rubikoptimal_fallback_timeout_seconds": (
                    args.universal_rubikoptimal_fallback_timeout
                    if args.universal and args.universal_rubikoptimal_fallback_timeout >= 0
                    else None
                ),
                "rubikoptimal_prepass_timeout_seconds": (
                    args.universal_rubikoptimal_prepass_timeout
                    if args.universal and args.universal_rubikoptimal_prepass_timeout >= 0
                    else None
                ),
                "rubikoptimal_symmetry_variants": (
                    max(0, args.universal_rubikoptimal_symmetry_variants) if args.universal else 0
                ),
                "rubikoptimal_symmetry_timeout_seconds": (
                    args.universal_rubikoptimal_symmetry_timeout
                    if args.universal
                    and args.universal_rubikoptimal_symmetry_timeout is not None
                    and args.universal_rubikoptimal_symmetry_timeout >= 0
                    else None
                ),
                "rubikoptimal_symmetry_max_concurrency": (
                    max(0, args.universal_rubikoptimal_symmetry_max_concurrency)
                    if args.universal
                    else 0
                ),
                "rubikoptimal_race_timeout_seconds": (
                    args.universal_rubikoptimal_race_timeout
                    if args.universal and args.universal_rubikoptimal_race_timeout >= 0
                    else None
                ),
                "resident_race_prepass_timeout_seconds": (
                    args.universal_resident_race_prepass_timeout
                    if args.universal and args.universal_resident_race_prepass_timeout >= 0
                    else None
                ),
                "try_certificate_cache": bool(args.universal and not args.no_universal_certificate_cache),
                "try_upper_lower_certificate": bool(
                    args.universal and not args.no_universal_upper_lower_certificate
                ),
                "include_external_label_certificates": bool(
                    args.universal and args.universal_include_external_label_certificates
                ),
                "h48_trusted_table": effective_trusted_h48_table,
                "h48_preload_table": args.h48_preload_table,
                "h48_auto_min_depth": args.h48_auto_min_depth,
                "batch_wall_seconds": batch_wall_seconds,
                "input_count": len(inputs),
                "all_exact": all_exact,
                "all_exact_or_external_label": all_accepted,
                "external_label_exact_rows": external_label_exact_rows,
                "all_verified": all_verified,
                "rows": final_rows,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all_accepted and all_verified else 1

    if args.command == "tables":
        profile = args.profile or ("quick" if args.quick else "thesis")
        paths = generate_coordinate_tables(seed=args.seed, profile=profile, root=args.root)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
