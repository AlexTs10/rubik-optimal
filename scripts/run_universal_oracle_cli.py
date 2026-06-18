#!/usr/bin/env python
"""Generate evidence for the public UniversalOptimalOracle CLI batch path."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.scramble import deterministic_scramble  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver, h48_table_path  # noqa: E402
from scripts.run_h48_oracle_certification import certification_cases  # noqa: E402


@dataclass(frozen=True)
class CliCase:
    case_id: str
    source_depth: int | None
    facelets: str
    case_kind: str = "deterministic_random"
    expected_distance: int | None = None
    source_label: str | None = None


_ALLOWED_UNIVERSAL_SELECTED_BACKENDS = {
    "upper-lower-certificate",
    "h48-upper-bound-proof",
    "h48-upper-bound-proof-found-shorter",
    "exact-certificate-cache",
    "nissy-core-direct-resident",
    "nissy-core-direct-symmetry-race",
    "resident-h48-symmetry-batch",
    "resident-h48-symmetry-batch-after-portfolio-prepass",
    "parallel-h48-symmetry-race",
    "portfolio-before-resident-h48-batch",
    "resident-h48-batch",
    "resident-h48-batch-after-portfolio-prepass",
    "resident-race-prepass",
    "portfolio-after-resident-h48-fallback",
    "portfolio-after-resident-h48-fallback-after-prepass",
    "rubikoptimal-prepass",
    "rubikoptimal-race",
    "rubikoptimal-after-resident-race",
    "rubikoptimal-after-universal-fallback",
    "rubikoptimal-symmetry-batch",
    "rubikoptimal-symmetry-race",
    "solved_fast_path",
}


def _tex(value: object) -> str:
    if value is None:
        return "--"
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_")


def _note_bool(notes: str, key: str) -> bool | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    if not match:
        return None
    value = match.group(1).strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    return None


def _note_float(notes: str, key: str) -> float | None:
    match = re.search(rf"(?:^|; ){re.escape(key)}=([^;]+)", notes)
    if not match:
        return None
    try:
        return float(match.group(1).strip())
    except ValueError:
        return None


def _cases(seed: int, depths: list[int], cases_per_depth: int) -> list[CliCase]:
    rows: list[CliCase] = []
    for depth in depths:
        for index in range(cases_per_depth):
            offset = 7300 + depth * 100 + index
            sequence = deterministic_scramble(depth, seed, offset=offset)
            rows.append(
                CliCase(
                    case_id=f"cli_random_depth_{depth}_{index}",
                    source_depth=depth,
                    facelets=CubeState.from_sequence(sequence).to_facelets(),
                )
            )
    return rows


def _hard_cases(seed: int) -> list[CliCase]:
    rows: list[CliCase] = []
    for case in certification_cases(seed):
        if case.case_id not in {"deterministic_depth_25", "superflip_distance_20"}:
            continue
        rows.append(
            CliCase(
                case_id=f"cli_hard_{case.case_id}",
                source_depth=25 if case.case_id == "deterministic_depth_25" else None,
                facelets=case.cube.to_facelets(),
                case_kind="named_hard_state",
                expected_distance=case.expected_distance if case.expected_distance >= 0 else None,
            )
        )
    return rows


def _nissy_benchmark_cases(
    root: Path,
    *,
    distances: list[int],
    limit_per_distance: int,
    offset_per_distance: int = 0,
) -> list[CliCase]:
    rows: list[CliCase] = []
    scrambles_dir = root / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles"
    offset = max(0, int(offset_per_distance))
    limit = max(1, int(limit_per_distance))
    for distance in distances:
        if distance < 16 or distance > 20:
            raise SystemExit("--benchmark-distance values must be in [16, 20]")
        path = scrambles_dir / f"scrambles-{distance}.txt"
        if not path.exists():
            raise SystemExit(f"missing nissy-core benchmark scramble file: {path}")
        all_rows = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        selected = all_rows[offset : offset + limit]
        if not selected:
            raise SystemExit(
                f"no nissy-core benchmark rows selected for distance {distance}: "
                f"offset {offset} outside {len(all_rows)} available rows"
            )
        for relative_index, sequence in enumerate(selected):
            index = offset + relative_index
            cube = CubeState.from_sequence(sequence)
            rows.append(
                CliCase(
                    case_id=f"nissy_benchmark_distance_{distance}_{index}",
                    source_depth=len(sequence.split()),
                    facelets=cube.to_facelets(),
                    case_kind="nissy_core_benchmark_known_distance",
                    expected_distance=distance,
                    source_label=str(path.relative_to(root)),
                )
            )
    return rows


def _adaptive_command_timeout_seconds(
    *,
    solver_timeout_seconds: float,
    resident_h48_batch_timeout_seconds: float,
    case_count: int,
    portfolio_prepass_enabled: bool,
    portfolio_prepass_timeout_seconds: float | None = None,
    portfolio_fallback_timeout_seconds: float | None = None,
    portfolio_fallback_nissy_core_direct_timeout_seconds: float | None = 0.0,
    h48_symmetry_variants: int,
    h48_symmetry_timeout_seconds: float,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float | None = None,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float | None = None,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float | None = None,
    symmetry_order_by_h48_lower_bound: bool = False,
    symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    native_korf_upper_bound_proof_timeout_seconds: float = 0.0,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    explicit_command_timeout_seconds: float | None = None,
) -> float:
    """Estimate the outer subprocess budget for the adaptive universal CLI.

    The public CLI can spend time in multiple exact phases for the same hard
    state: optional portfolio/Nissy prepass, optional H48 rotations, resident
    H48 batch, then a portfolio fallback.  The outer evidence script should not
    kill that command before those configured exact phases can return their own
    exact or timeout status.
    """

    if explicit_command_timeout_seconds is not None and explicit_command_timeout_seconds > 0:
        return explicit_command_timeout_seconds

    cases = max(1, int(case_count))
    solver_timeout = max(0.0, float(solver_timeout_seconds))
    resident_timeout = (
        solver_timeout
        if resident_h48_batch_timeout_seconds < 0
        else min(solver_timeout, max(0.0, float(resident_h48_batch_timeout_seconds)))
    )
    symmetry_timeout = (
        solver_timeout
        if h48_symmetry_timeout_seconds < 0
        else max(0.0, float(h48_symmetry_timeout_seconds))
    )
    symmetry_budget = (
        symmetry_timeout * cases if max(0, int(h48_symmetry_variants)) > 0 else 0.0
    )
    nissy_symmetry_timeout = (
        solver_timeout
        if nissy_symmetry_timeout_seconds is None
        else max(0.0, float(nissy_symmetry_timeout_seconds))
    )
    nissy_symmetry_budget = (
        nissy_symmetry_timeout * cases if max(0, int(nissy_symmetry_variants)) > 0 else 0.0
    )
    direct_symmetry_timeout = (
        solver_timeout
        if nissy_core_direct_symmetry_timeout_seconds is None
        else max(0.0, float(nissy_core_direct_symmetry_timeout_seconds))
    )
    direct_symmetry_budget = (
        direct_symmetry_timeout * cases
        if nissy_core_direct_symmetry_variants > 0
        else 0.0
    )
    parallel_h48_symmetry_timeout = (
        solver_timeout
        if parallel_h48_symmetry_timeout_seconds is None
        else max(0.0, float(parallel_h48_symmetry_timeout_seconds))
    )
    parallel_h48_symmetry_budget = (
        parallel_h48_symmetry_timeout * cases
        if max(0, int(parallel_h48_symmetry_variants)) > 0
        else 0.0
    )
    ordered_symmetry_phase_count = 0
    if symmetry_order_by_h48_lower_bound:
        ordered_symmetry_phase_count += 1 if max(0, int(h48_symmetry_variants)) > 0 else 0
        ordered_symmetry_phase_count += 1 if max(0, int(nissy_symmetry_variants)) > 0 else 0
        ordered_symmetry_phase_count += (
            1 if max(0, int(nissy_core_direct_symmetry_variants)) > 0 else 0
        )
        ordered_symmetry_phase_count += 1 if max(0, int(parallel_h48_symmetry_variants)) > 0 else 0
        ordered_symmetry_phase_count += 1 if max(0, int(rubikoptimal_symmetry_variants)) > 0 else 0
    symmetry_order_budget = (
        max(0.0, float(symmetry_lower_bound_order_timeout_seconds))
        * cases
        * ordered_symmetry_phase_count
    )
    h48_upper_bound_proof_budget = (
        max(0.0, float(h48_upper_bound_proof_timeout_seconds)) * cases
    )
    native_korf_upper_bound_proof_budget = (
        max(0.0, float(native_korf_upper_bound_proof_timeout_seconds)) * cases
    )
    portfolio_timeout = (
        solver_timeout
        if portfolio_prepass_timeout_seconds is None
        else max(0.0, float(portfolio_prepass_timeout_seconds))
    )
    portfolio_budget = portfolio_timeout if portfolio_prepass_enabled else 0.0
    fallback_budget = (
        solver_timeout
        if portfolio_fallback_timeout_seconds is None
        else max(0.0, float(portfolio_fallback_timeout_seconds))
    )
    fallback_direct_budget = (
        0.0
        if portfolio_fallback_nissy_core_direct_timeout_seconds is None
        else max(0.0, float(portfolio_fallback_nissy_core_direct_timeout_seconds))
    )
    rubikoptimal_prepass_budget = (
        0.0
        if rubikoptimal_prepass_timeout_seconds is None or rubikoptimal_prepass_timeout_seconds < 0
        else max(0.0, float(rubikoptimal_prepass_timeout_seconds)) * cases
    )
    rubikoptimal_symmetry_timeout = (
        solver_timeout
        if rubikoptimal_symmetry_timeout_seconds is None
        else max(0.0, float(rubikoptimal_symmetry_timeout_seconds))
    )
    rubikoptimal_rotation_count = max(0, int(rubikoptimal_symmetry_variants))
    rubikoptimal_symmetry_budget = (
        rubikoptimal_symmetry_timeout * cases if rubikoptimal_rotation_count > 0 else 0.0
    )
    rubikoptimal_race_budget = (
        0.0
        if rubikoptimal_race_timeout_seconds is None or rubikoptimal_race_timeout_seconds < 0
        else max(0.0, float(rubikoptimal_race_timeout_seconds)) * cases
    )
    resident_race_prepass_budget = (
        0.0
        if resident_race_prepass_timeout_seconds is None or resident_race_prepass_timeout_seconds < 0
        else max(0.0, float(resident_race_prepass_timeout_seconds)) * cases
    )
    rubikoptimal_fallback_budget = (
        0.0
        if rubikoptimal_fallback_timeout_seconds is None or rubikoptimal_fallback_timeout_seconds < 0
        else max(0.0, float(rubikoptimal_fallback_timeout_seconds)) * cases
    )
    resident_budget = resident_timeout * cases
    grace_seconds = 60.0
    return max(
        solver_timeout + 45.0,
        portfolio_budget
        + rubikoptimal_prepass_budget
        + rubikoptimal_symmetry_budget
        + symmetry_order_budget
        + symmetry_budget
        + nissy_symmetry_budget
        + direct_symmetry_budget
        + parallel_h48_symmetry_budget
        + h48_upper_bound_proof_budget
        + native_korf_upper_bound_proof_budget
        + rubikoptimal_race_budget
        + resident_race_prepass_budget
        + resident_budget
        + fallback_direct_budget
        + fallback_budget
        + rubikoptimal_fallback_budget
        + grace_seconds,
    )


def _write_table(root: Path, rows: list[dict[str, object]], suffix: str) -> Path:
    filename = f"universal_oracle_cli{suffix}.tex" if suffix else "universal_oracle_cli.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{lrllrr}\n",
        "\\hline\n",
        "Case & Depth & CLI backend & Selected backend & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in rows:
        body.append(
            f"{_tex(row['case_id'])} & {_tex(row['source_depth'])} & "
            f"{_tex(row['cli_backend'])} & {_tex(row['selected_backend'])} & "
            f"{_tex(row['solution_length'])} & {_tex(row['runtime_seconds'])} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def _has_complete_row_set(rows: list[dict[str, object]], expected_count: int) -> bool:
    return expected_count > 0 and len(rows) == expected_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--depth", type=int, action="append", default=None)
    parser.add_argument("--cases-per-depth", type=int, default=1)
    parser.add_argument("--no-random-cases", action="store_true")
    parser.add_argument("--include-hard", action="store_true")
    parser.add_argument(
        "--benchmark-distance",
        type=int,
        action="append",
        default=None,
        help=(
            "Include public nissy-core benchmark scrambles grouped by known HTM optimal distance; "
            "repeatable for 16..20."
        ),
    )
    parser.add_argument("--benchmark-limit-per-distance", type=int, default=1)
    parser.add_argument(
        "--benchmark-offset-per-distance",
        type=int,
        default=0,
        help="Skip this many rows in each public nissy-core known-distance benchmark file.",
    )
    parser.add_argument("--case-id", action="append", default=None, help="Run only the named case; repeatable")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--resident-h48-batch-timeout", type=float, default=30.0)
    parser.add_argument("--no-portfolio-prepass", action="store_true")
    parser.add_argument(
        "--universal-portfolio-prepass-timeout",
        type=float,
        default=None,
        help="Separate timeout for the universal portfolio/Nissy batch prepass.",
    )
    parser.add_argument(
        "--universal-portfolio-fallback-timeout",
        type=float,
        default=None,
        help="Separate timeout for the late universal portfolio/Nissy fallback after resident H48.",
    )
    parser.add_argument(
        "--universal-fallback-nissy-core-direct-timeout",
        type=float,
        default=10.0,
        help=(
            "Timeout for the late direct nissy-core cubie-state fallback after resident H48; "
            "negative disables it."
        ),
    )
    parser.add_argument(
        "--universal-rubikoptimal-prepass-timeout",
        type=float,
        default=-1.0,
        help="Run table-complete RubikOptimal before resident H48/Nissy live phases; negative disables it.",
    )
    parser.add_argument(
        "--universal-rubikoptimal-symmetry-variants",
        type=int,
        default=0,
        help="Try this many non-identity whole-cube rotations through table-complete RubikOptimal.",
    )
    parser.add_argument(
        "--universal-rubikoptimal-symmetry-timeout",
        type=float,
        default=None,
        help="Global RubikOptimal symmetry phase timeout; defaults to --timeout.",
    )
    parser.add_argument(
        "--universal-rubikoptimal-symmetry-max-concurrency",
        type=int,
        default=0,
        help=(
            "If positive, race RubikOptimal rotated variants with this many concurrent "
            "processes instead of using the sequential batch helper."
        ),
    )
    parser.add_argument(
        "--universal-rubikoptimal-race-timeout",
        type=float,
        default=-1.0,
        help="Enable RubikOptimal as a resident-race competitor for single-state universal fallthrough; negative disables it.",
    )
    parser.add_argument(
        "--universal-resident-race-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "Run a bounded resident H48/Nissy/RubikOptimal race before later "
            "sequential hard-tail phases; negative disables it."
        ),
    )
    parser.add_argument(
        "--universal-rubikoptimal-fallback-timeout",
        type=float,
        default=-1.0,
        help="Run table-complete RubikOptimal after live H48/Nissy phases miss; negative disables it.",
    )
    parser.add_argument("--no-certificate-cache", action="store_true")
    parser.add_argument(
        "--include-external-label-certificates",
        action="store_true",
        help=(
            "Pass --universal-include-external-label-certificates to the public CLI so the "
            "exact-certificate cache may also serve rows whose optimality rests only on a "
            "third-party benchmark label; such rows are accepted with "
            "status=external_label_exact and an explicit exactness-basis note, never as plain exact."
        ),
    )
    parser.add_argument("--no-upper-lower-certificate", action="store_true")
    parser.add_argument("--require-resident-h48-batch", action="store_true")
    parser.add_argument(
        "--require-resident-h48-batch-for-all",
        action="store_true",
        help="Fail the evidence artifact unless every row is solved by the resident H48 batch backend.",
    )
    parser.add_argument("--h48-symmetry-variants", type=int, default=0)
    parser.add_argument("--h48-symmetry-timeout", type=float, default=5.0)
    parser.add_argument("--nissy-symmetry-variants", type=int, default=0)
    parser.add_argument("--nissy-symmetry-timeout", type=float, default=None)
    parser.add_argument("--nissy-core-direct-symmetry-variants", type=int, default=0)
    parser.add_argument("--nissy-core-direct-symmetry-timeout", type=float, default=None)
    parser.add_argument("--nissy-core-direct-symmetry-max-concurrency", type=int, default=0)
    parser.add_argument("--h48-parallel-symmetry-variants", type=int, default=0)
    parser.add_argument("--h48-parallel-symmetry-timeout", type=float, default=5.0)
    parser.add_argument("--h48-parallel-symmetry-max-concurrency", type=int, default=0)
    parser.add_argument(
        "--h48-parallel-symmetry-order-by-lower-bound",
        "--symmetry-order-by-h48-lower-bound",
        dest="h48_parallel_symmetry_order_by_lower_bound",
        action="store_true",
    )
    parser.add_argument(
        "--h48-parallel-symmetry-lower-bound-order-timeout",
        "--symmetry-lower-bound-order-timeout",
        dest="h48_parallel_symmetry_lower_bound_order_timeout",
        type=float,
        default=30.0,
    )
    parser.add_argument("--h48-lower-bound-symmetry-variants", type=int, default=23)
    parser.add_argument("--kociemba-upper-bound-symmetry-variants", type=int, default=23)
    parser.add_argument(
        "--h48-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "Spend this many seconds in the public universal oracle proving no H48 "
            "solution exists below a verified upper bound; 0 disables it."
        ),
    )
    parser.add_argument(
        "--h48-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help="Only run the bounded H48 upper-proof when upper minus lower bound is at most this gap.",
    )
    parser.add_argument(
        "--native-korf-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "Spend this many seconds in the public universal oracle's native C++ "
            "Korf/IDA* single-bound upper-proof; 0 disables it."
        ),
    )
    parser.add_argument(
        "--native-korf-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help=(
            "Only run the native Korf upper-proof when upper minus lower bound is "
            "at most this gap."
        ),
    )
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--trusted-table", action="store_true")
    parser.add_argument("--preload-table", action="store_true")
    parser.add_argument("--h48-auto-min-depth", action="store_true")
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=None,
        help="Outer wrapper timeout for the public CLI command; by default it is estimated from adaptive phase timeouts.",
    )
    parser.add_argument("--artifact-suffix", default="optimized_lowload")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    depths = args.depth or [5, 10, 15]
    cases = [] if args.no_random_cases else _cases(args.seed, depths, max(1, args.cases_per_depth))
    if args.include_hard:
        cases.extend(_hard_cases(args.seed))
    if args.benchmark_distance:
        cases.extend(
            _nissy_benchmark_cases(
                root,
                distances=args.benchmark_distance,
                limit_per_distance=args.benchmark_limit_per_distance,
                offset_per_distance=args.benchmark_offset_per_distance,
            )
        )
    if args.case_id is not None:
        selected_ids = set(args.case_id)
        cases = [case for case in cases if case.case_id in selected_ids]
        missing_ids = selected_ids - {case.case_id for case in cases}
        if missing_ids:
            raise SystemExit(f"case-id not found: {', '.join(sorted(missing_ids))}")
    if not cases:
        raise SystemExit("no universal CLI cases selected")
    table_path = h48_table_path(root=root, profile=args.profile, seed=args.seed, solver=solver)
    if not table_path.exists():
        raise SystemExit(f"missing H48 table: {table_path}")

    command = [
        sys.executable,
        "-m",
        "rubik_optimal.cli",
        "oracle",
        "--universal",
        "--h48-solver",
        solver,
        "--h48-profile",
        args.profile,
        "--timeout",
        str(args.timeout),
        "--threads",
        str(args.threads),
        "--resident-h48-batch-timeout",
        str(args.resident_h48_batch_timeout),
    ]
    if args.no_portfolio_prepass:
        command.append("--no-universal-portfolio-prepass")
    if args.universal_portfolio_prepass_timeout is not None:
        command.extend(
            [
                "--universal-portfolio-prepass-timeout",
                str(args.universal_portfolio_prepass_timeout),
            ]
        )
    if args.universal_portfolio_fallback_timeout is not None:
        command.extend(
            [
                "--universal-portfolio-fallback-timeout",
                str(args.universal_portfolio_fallback_timeout),
            ]
        )
    command.extend(
        [
            "--universal-fallback-nissy-core-direct-timeout",
            str(args.universal_fallback_nissy_core_direct_timeout),
        ]
    )
    if args.universal_rubikoptimal_prepass_timeout >= 0:
        command.extend(
            [
                "--universal-rubikoptimal-prepass-timeout",
                str(args.universal_rubikoptimal_prepass_timeout),
            ]
        )
    if args.universal_rubikoptimal_symmetry_variants > 0:
        command.extend(
            [
                "--universal-rubikoptimal-symmetry-variants",
                str(args.universal_rubikoptimal_symmetry_variants),
            ]
        )
        if args.universal_rubikoptimal_symmetry_timeout is not None:
            command.extend(
                [
                    "--universal-rubikoptimal-symmetry-timeout",
                    str(args.universal_rubikoptimal_symmetry_timeout),
                ]
            )
        if args.universal_rubikoptimal_symmetry_max_concurrency > 0:
            command.extend(
                [
                    "--universal-rubikoptimal-symmetry-max-concurrency",
                    str(args.universal_rubikoptimal_symmetry_max_concurrency),
                ]
            )
    if args.universal_rubikoptimal_race_timeout >= 0:
        command.extend(
            [
                "--universal-rubikoptimal-race-timeout",
                str(args.universal_rubikoptimal_race_timeout),
            ]
        )
    if args.universal_resident_race_prepass_timeout >= 0:
        command.extend(
            [
                "--universal-resident-race-prepass-timeout",
                str(args.universal_resident_race_prepass_timeout),
            ]
        )
    if args.universal_rubikoptimal_fallback_timeout >= 0:
        command.extend(
            [
                "--universal-rubikoptimal-fallback-timeout",
                str(args.universal_rubikoptimal_fallback_timeout),
            ]
        )
    if args.no_certificate_cache:
        command.append("--no-universal-certificate-cache")
    if args.include_external_label_certificates:
        command.append("--universal-include-external-label-certificates")
    if args.no_upper_lower_certificate:
        command.append("--no-universal-upper-lower-certificate")
    if args.h48_symmetry_variants > 0:
        command.extend(
            [
                "--h48-symmetry-variants",
                str(args.h48_symmetry_variants),
                "--h48-symmetry-timeout",
                str(args.h48_symmetry_timeout),
            ]
        )
    if args.nissy_symmetry_variants > 0:
        command.extend(["--nissy-symmetry-variants", str(args.nissy_symmetry_variants)])
        if args.nissy_symmetry_timeout is not None:
            command.extend(["--nissy-symmetry-timeout", str(args.nissy_symmetry_timeout)])
    if args.nissy_core_direct_symmetry_variants > 0:
        command.extend(
            [
                "--nissy-core-direct-symmetry-variants",
                str(args.nissy_core_direct_symmetry_variants),
            ]
        )
        if args.nissy_core_direct_symmetry_timeout is not None:
            command.extend(
                [
                    "--nissy-core-direct-symmetry-timeout",
                    str(args.nissy_core_direct_symmetry_timeout),
                ]
            )
        command.extend(
            [
                "--nissy-core-direct-symmetry-max-concurrency",
                str(args.nissy_core_direct_symmetry_max_concurrency),
            ]
        )
    if args.h48_parallel_symmetry_variants > 0:
        command.extend(
            [
                "--h48-parallel-symmetry-variants",
                str(args.h48_parallel_symmetry_variants),
                "--h48-parallel-symmetry-timeout",
                str(args.h48_parallel_symmetry_timeout),
                "--h48-parallel-symmetry-max-concurrency",
                str(args.h48_parallel_symmetry_max_concurrency),
            ]
        )
    if args.h48_parallel_symmetry_order_by_lower_bound:
        command.append("--symmetry-order-by-h48-lower-bound")
        command.extend(
            [
                "--symmetry-lower-bound-order-timeout",
                str(args.h48_parallel_symmetry_lower_bound_order_timeout),
            ]
        )
    command.extend(
        [
            "--h48-lower-bound-symmetry-variants",
            str(max(0, args.h48_lower_bound_symmetry_variants)),
            "--kociemba-upper-bound-symmetry-variants",
            str(max(0, args.kociemba_upper_bound_symmetry_variants)),
            "--h48-upper-bound-proof-timeout",
            str(max(0.0, args.h48_upper_bound_proof_timeout)),
            "--h48-upper-bound-proof-max-gap",
            str(max(1, args.h48_upper_bound_proof_max_gap)),
            "--native-korf-upper-bound-proof-timeout",
            str(max(0.0, args.native_korf_upper_bound_proof_timeout)),
            "--native-korf-upper-bound-proof-max-gap",
            str(max(1, args.native_korf_upper_bound_proof_max_gap)),
        ]
    )
    if args.trusted_table:
        command.append("--h48-trusted-table")
    if args.preload_table:
        command.append("--h48-preload-table")
    if args.h48_auto_min_depth:
        command.append("--h48-auto-min-depth")

    command_timeout_seconds = _adaptive_command_timeout_seconds(
        solver_timeout_seconds=args.timeout,
        resident_h48_batch_timeout_seconds=args.resident_h48_batch_timeout,
        case_count=len(cases),
        portfolio_prepass_enabled=not args.no_portfolio_prepass,
        portfolio_prepass_timeout_seconds=args.universal_portfolio_prepass_timeout,
        portfolio_fallback_timeout_seconds=args.universal_portfolio_fallback_timeout,
        portfolio_fallback_nissy_core_direct_timeout_seconds=(
            None
            if args.universal_fallback_nissy_core_direct_timeout < 0
            else args.universal_fallback_nissy_core_direct_timeout
        ),
        rubikoptimal_prepass_timeout_seconds=(
            None
            if args.universal_rubikoptimal_prepass_timeout < 0
            else args.universal_rubikoptimal_prepass_timeout
        ),
        rubikoptimal_symmetry_variants=max(0, args.universal_rubikoptimal_symmetry_variants),
        rubikoptimal_symmetry_timeout_seconds=args.universal_rubikoptimal_symmetry_timeout,
        rubikoptimal_symmetry_max_concurrency=max(
            0, args.universal_rubikoptimal_symmetry_max_concurrency
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
        h48_symmetry_variants=max(0, args.h48_symmetry_variants),
        h48_symmetry_timeout_seconds=args.h48_symmetry_timeout,
        nissy_symmetry_variants=max(0, args.nissy_symmetry_variants),
        nissy_symmetry_timeout_seconds=args.nissy_symmetry_timeout,
        nissy_core_direct_symmetry_variants=max(0, args.nissy_core_direct_symmetry_variants),
        nissy_core_direct_symmetry_timeout_seconds=args.nissy_core_direct_symmetry_timeout,
        nissy_core_direct_symmetry_max_concurrency=max(
            0, args.nissy_core_direct_symmetry_max_concurrency
        ),
        parallel_h48_symmetry_variants=max(0, args.h48_parallel_symmetry_variants),
        parallel_h48_symmetry_timeout_seconds=args.h48_parallel_symmetry_timeout,
        symmetry_order_by_h48_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
        symmetry_lower_bound_order_timeout_seconds=(
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        h48_upper_bound_proof_timeout_seconds=max(
            0.0, args.h48_upper_bound_proof_timeout
        ),
        native_korf_upper_bound_proof_timeout_seconds=max(
            0.0, args.native_korf_upper_bound_proof_timeout
        ),
        explicit_command_timeout_seconds=args.command_timeout,
    )

    begin = time.perf_counter()
    outer_command_timed_out = False
    completed_return_code = 0
    completed_stdout = ""
    completed_stderr = ""
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input="\n".join(case.facelets for case in cases) + "\n",
            text=True,
            capture_output=True,
            check=False,
            timeout=command_timeout_seconds,
        )
        completed_return_code = completed.returncode
        completed_stdout = completed.stdout
        completed_stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        outer_command_timed_out = True
        completed_return_code = 124
        completed_stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        completed_stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    wrapper_wall_seconds = time.perf_counter() - begin
    try:
        cli_payload = json.loads(completed_stdout) if completed_stdout.strip() else {"rows": []}
    except json.JSONDecodeError as exc:
        cli_payload = {"rows": [], "json_decode_error": str(exc)}

    rows: list[dict[str, object]] = []
    errors: list[str] = []
    if outer_command_timed_out:
        errors.append(f"public universal CLI wrapper timed out after {command_timeout_seconds:.6f}s")
    if "json_decode_error" in cli_payload:
        errors.append(
            f"universal oracle CLI returned non-JSON stdout: {completed_stdout!r}; stderr={completed_stderr!r}"
        )
    cli_rows = cli_payload.get("rows", [])
    for case, row in zip(cases, cli_rows, strict=False):
        notes = str(row.get("notes", ""))
        source_sequence_provided = _note_bool(notes, "source_sequence_provided")
        backend_runtime_seconds = _note_float(notes, "backend_runtime_seconds")
        backend_solve_seconds = _note_float(notes, "backend_solve_seconds")
        raw_solution_moves = row.get("solution_moves")
        solution_moves = raw_solution_moves if isinstance(raw_solution_moves, list) else []
        merged = {
            "case_id": case.case_id,
            "case_kind": case.case_kind,
            "source_label": case.source_label,
            "source_depth": case.source_depth,
            "expected_distance": case.expected_distance,
            "state": case.facelets,
            "input": row.get("input"),
            "input_kind": row.get("input_kind"),
            "cli_backend": cli_payload.get("backend"),
            "selected_backend": row.get("selected_backend"),
            "backend_solver": row.get("backend_solver"),
            "status": row.get("status"),
            "verified": row.get("verified"),
            "solution": " ".join(str(move) for move in solution_moves),
            "solution_moves": solution_moves,
            "solution_length": row.get("solution_length"),
            "distance": row.get("distance"),
            "runtime_seconds": round(float(row.get("runtime_seconds") or 0.0), 6),
            "backend_runtime_seconds": (
                round(backend_runtime_seconds, 6) if backend_runtime_seconds is not None else None
            ),
            "backend_solve_seconds": (
                round(backend_solve_seconds, 6) if backend_solve_seconds is not None else None
            ),
            "source_sequence_provided_to_solver": source_sequence_provided,
            "notes": notes,
        }
        rows.append(merged)
        accepted_statuses = (
            {"exact", "external_label_exact"}
            if args.include_external_label_certificates
            else {"exact"}
        )
        if merged["status"] not in accepted_statuses or merged["verified"] is not True:
            errors.append(f"{case.case_id}: expected exact verified, got {merged['status']}")
        if merged["status"] == "external_label_exact" and (
            merged["selected_backend"] != "exact-certificate-cache"
            or "certificate_exactness_basis=third_party_benchmark_label" not in notes
        ):
            errors.append(
                f"{case.case_id}: external_label_exact row without certificate-cache "
                "provenance or explicit third-party exactness-basis note"
            )
        if case.expected_distance is not None and merged["solution_length"] != case.expected_distance:
            errors.append(
                f"{case.case_id}: expected distance {case.expected_distance}, got {merged['solution_length']}"
            )
        if merged["input_kind"] == "facelets" and merged["input"] != case.facelets:
            errors.append(f"{case.case_id}: public CLI input state did not match generated case")
        if merged["selected_backend"] not in _ALLOWED_UNIVERSAL_SELECTED_BACKENDS:
            errors.append(f"{case.case_id}: unexpected universal path {merged['selected_backend']}")
        if args.no_certificate_cache and merged["selected_backend"] == "exact-certificate-cache":
            errors.append(f"{case.case_id}: certificate cache was disabled but selected")
        if args.no_upper_lower_certificate and merged["selected_backend"] == "upper-lower-certificate":
            errors.append(f"{case.case_id}: upper/lower certificate was disabled but selected")
        if merged["source_sequence_provided_to_solver"] is True:
            errors.append(f"{case.case_id}: source sequence unexpectedly reached solver")

    if completed_return_code != 0:
        errors.append(f"CLI exited {completed_return_code}: {completed_stderr.strip()}")
    if len(cli_rows) != len(cases):
        errors.append(f"expected {len(cases)} CLI rows, got {len(cli_rows)}")
    resident_h48_batch_rows = sum(1 for row in rows if row["selected_backend"] == "resident-h48-batch")
    resident_h48_fallback_rows = sum(
        1 for row in rows if row["selected_backend"] == "portfolio-after-resident-h48-fallback"
    )
    resident_h48_after_prepass_rows = sum(
        1 for row in rows if row["selected_backend"] == "resident-h48-batch-after-portfolio-prepass"
    )
    resident_h48_fallback_after_prepass_rows = sum(
        1 for row in rows if row["selected_backend"] == "portfolio-after-resident-h48-fallback-after-prepass"
    )
    portfolio_prepass_rows = sum(
        1 for row in rows if row["selected_backend"] == "portfolio-before-resident-h48-batch"
    )
    resident_h48_symmetry_rows = sum(
        1 for row in rows if row["selected_backend"] == "resident-h48-symmetry-batch"
    )
    resident_h48_symmetry_after_prepass_rows = sum(
        1 for row in rows if row["selected_backend"] == "resident-h48-symmetry-batch-after-portfolio-prepass"
    )
    parallel_h48_symmetry_rows = sum(
        1 for row in rows if row["selected_backend"] == "parallel-h48-symmetry-race"
    )
    resident_race_prepass_rows = sum(
        1 for row in rows if row["selected_backend"] == "resident-race-prepass"
    )
    nissy_core_direct_symmetry_rows = sum(
        1 for row in rows if row["selected_backend"] == "nissy-core-direct-symmetry-race"
    )
    rubikoptimal_symmetry_rows = sum(
        1
        for row in rows
        if row["selected_backend"] in {"rubikoptimal-symmetry-batch", "rubikoptimal-symmetry-race"}
    )
    rubikoptimal_symmetry_race_rows = sum(
        1 for row in rows if row["selected_backend"] == "rubikoptimal-symmetry-race"
    )
    late_nissy_core_direct_fallback_rows = sum(
        1
        for row in rows
        if str(row.get("selected_backend", "")).startswith("portfolio-after-resident-h48-fallback")
        and "selected_backend=nissy-core-direct" in str(row.get("notes", ""))
    )
    universal_upper_lower_batch_rows = sum(
        1
        for row in rows
        if row["selected_backend"] == "upper-lower-certificate"
        and "universal_solve_many_upper_lower_batch=true" in str(row.get("notes", ""))
    )
    universal_upper_lower_batch_lower_bound_rows = sum(
        1
        for row in rows
        if "h48_lower_bound_batch_invoked=true" in str(row.get("notes", ""))
    )
    row_set_complete = _has_complete_row_set(rows, len(cases))
    if args.require_resident_h48_batch and resident_h48_batch_rows + resident_h48_after_prepass_rows < 1:
        errors.append("expected at least one public CLI row to reach resident-h48-batch")
    resident_h48_batch_all_rows = row_set_complete and all(
        row["selected_backend"] == "resident-h48-batch" for row in rows
    )
    if args.require_resident_h48_batch_for_all and not resident_h48_batch_all_rows:
        errors.append("expected every public CLI row to be solved by resident-h48-batch")

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "public_interface": "rubik-optimal oracle --universal",
        "command": " ".join(command),
        "return_code": completed_return_code,
        "outer_command_timed_out": outer_command_timed_out,
        "stdout_truncated": completed_stdout[:4000],
        "stderr_truncated": completed_stderr[:4000],
        "depths": depths,
        "cases_per_depth": max(1, args.cases_per_depth),
        "random_cases_enabled": not args.no_random_cases,
        "include_hard": args.include_hard,
        "benchmark_distances": args.benchmark_distance or [],
        "benchmark_limit_per_distance": max(1, args.benchmark_limit_per_distance),
        "benchmark_offset_per_distance": max(0, args.benchmark_offset_per_distance),
        "case_ids": args.case_id,
        "case_count": len(cases),
        "hard_case_count": sum(1 for case in cases if case.case_kind == "named_hard_state"),
        "nissy_benchmark_case_count": sum(
            1 for case in cases if case.case_kind == "nissy_core_benchmark_known_distance"
        ),
        "nissy_benchmark_distances_present": sorted(
            {
                int(case.expected_distance)
                for case in cases
                if case.case_kind == "nissy_core_benchmark_known_distance"
                and case.expected_distance is not None
            }
        ),
        "contains_superflip": any(case.case_id == "cli_hard_superflip_distance_20" for case in cases),
        "expected_distance_checked_count": sum(case.expected_distance is not None for case in cases),
        "timeout_seconds": args.timeout,
        "command_timeout_seconds": command_timeout_seconds,
        "command_timeout_explicit": args.command_timeout,
        "resident_h48_batch_timeout_seconds": (
            None if args.resident_h48_batch_timeout < 0 else min(args.timeout, args.resident_h48_batch_timeout)
        ),
        "resident_h48_symmetry_variants": max(0, args.h48_symmetry_variants),
        "resident_h48_symmetry_timeout_seconds": (
            None if args.h48_symmetry_timeout < 0 else args.h48_symmetry_timeout
        ),
        "nissy_symmetry_variants": max(0, args.nissy_symmetry_variants),
        "nissy_symmetry_timeout_seconds": args.nissy_symmetry_timeout,
        "nissy_core_direct_symmetry_variants": max(0, args.nissy_core_direct_symmetry_variants),
        "nissy_core_direct_symmetry_timeout_seconds": args.nissy_core_direct_symmetry_timeout,
        "nissy_core_direct_symmetry_max_concurrency": max(
            0, args.nissy_core_direct_symmetry_max_concurrency
        ),
        "parallel_h48_symmetry_variants": max(0, args.h48_parallel_symmetry_variants),
        "parallel_h48_symmetry_timeout_seconds": (
            None if args.h48_parallel_symmetry_timeout < 0 else args.h48_parallel_symmetry_timeout
        ),
        "parallel_h48_symmetry_max_concurrency": max(0, args.h48_parallel_symmetry_max_concurrency),
        "parallel_h48_symmetry_order_by_lower_bound": args.h48_parallel_symmetry_order_by_lower_bound,
        "parallel_h48_symmetry_lower_bound_order_timeout_seconds": (
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        "symmetry_order_by_h48_lower_bound": args.h48_parallel_symmetry_order_by_lower_bound,
        "symmetry_lower_bound_order_timeout_seconds": (
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        "h48_lower_bound_symmetry_variants": max(0, args.h48_lower_bound_symmetry_variants),
        "kociemba_upper_bound_symmetry_variants": max(
            0,
            args.kociemba_upper_bound_symmetry_variants,
        ),
        "h48_upper_bound_proof_timeout_seconds": max(
            0.0,
            args.h48_upper_bound_proof_timeout,
        ),
        "h48_upper_bound_proof_max_gap": max(
            1,
            args.h48_upper_bound_proof_max_gap,
        ),
        "native_korf_upper_bound_proof_timeout_seconds": max(
            0.0,
            args.native_korf_upper_bound_proof_timeout,
        ),
        "native_korf_upper_bound_proof_max_gap": max(
            1,
            args.native_korf_upper_bound_proof_max_gap,
        ),
        "try_portfolio_batch_before_resident_h48_batch": not args.no_portfolio_prepass,
        "portfolio_prepass_timeout_seconds": args.universal_portfolio_prepass_timeout,
        "portfolio_fallback_timeout_seconds": args.universal_portfolio_fallback_timeout,
        "portfolio_fallback_nissy_core_direct_timeout_seconds": (
            None
            if args.universal_fallback_nissy_core_direct_timeout < 0
            else args.universal_fallback_nissy_core_direct_timeout
        ),
        "rubikoptimal_prepass_timeout_seconds": (
            None
            if args.universal_rubikoptimal_prepass_timeout < 0
            else args.universal_rubikoptimal_prepass_timeout
        ),
        "rubikoptimal_symmetry_variants": max(0, args.universal_rubikoptimal_symmetry_variants),
        "rubikoptimal_symmetry_timeout_seconds": args.universal_rubikoptimal_symmetry_timeout,
        "rubikoptimal_symmetry_max_concurrency": max(
            0, args.universal_rubikoptimal_symmetry_max_concurrency
        ),
        "rubikoptimal_race_timeout_seconds": (
            None
            if args.universal_rubikoptimal_race_timeout < 0
            else args.universal_rubikoptimal_race_timeout
        ),
        "resident_race_prepass_timeout_seconds": (
            None
            if args.universal_resident_race_prepass_timeout < 0
            else args.universal_resident_race_prepass_timeout
        ),
        "rubikoptimal_fallback_timeout_seconds": (
            None
            if args.universal_rubikoptimal_fallback_timeout < 0
            else args.universal_rubikoptimal_fallback_timeout
        ),
        "try_certificate_cache": not args.no_certificate_cache,
        "include_external_label_certificates": args.include_external_label_certificates,
        "try_upper_lower_certificate": not args.no_upper_lower_certificate,
        "live_solver_shortcuts_disabled": args.no_certificate_cache and args.no_upper_lower_certificate,
        "require_resident_h48_batch": args.require_resident_h48_batch,
        "require_resident_h48_batch_for_all": args.require_resident_h48_batch_for_all,
        "resident_h48_batch_all_rows": resident_h48_batch_all_rows,
        "threads": args.threads,
        "trusted_table": bool(args.trusted_table or cli_payload.get("h48_trusted_table")),
        "preload_table": args.preload_table,
        "h48_auto_min_depth": bool(args.h48_auto_min_depth),
        "table_path": str(table_path.relative_to(root)),
        "wrapper_wall_seconds": round(wrapper_wall_seconds, 6),
        "cli_payload": cli_payload,
        "rows": rows,
        "row_set_complete": row_set_complete,
        "all_exact": row_set_complete and all(row["status"] == "exact" for row in rows),
        "all_exact_or_external_label": row_set_complete
        and all(row["status"] in {"exact", "external_label_exact"} for row in rows),
        "external_label_exact_rows": sum(
            1 for row in rows if row["status"] == "external_label_exact"
        ),
        "external_label_exactness_basis": (
            "third_party_benchmark_label"
            if any(row["status"] == "external_label_exact" for row in rows)
            else None
        ),
        "all_verified": row_set_complete and all(row["verified"] is True for row in rows),
        "all_expected_distances_match": row_set_complete and all(
            row["expected_distance"] is None or row["solution_length"] == row["expected_distance"]
            for row in rows
        ),
        "all_universal_resident_h48_batch": resident_h48_batch_all_rows,
        "resident_h48_batch_rows": resident_h48_batch_rows,
        "resident_h48_after_prepass_rows": resident_h48_after_prepass_rows,
        "resident_h48_fallback_rows": resident_h48_fallback_rows,
        "resident_h48_fallback_after_prepass_rows": resident_h48_fallback_after_prepass_rows,
        "resident_h48_symmetry_rows": resident_h48_symmetry_rows,
        "resident_h48_symmetry_after_prepass_rows": resident_h48_symmetry_after_prepass_rows,
        "parallel_h48_symmetry_rows": parallel_h48_symmetry_rows,
        "resident_race_prepass_rows": resident_race_prepass_rows,
        "nissy_core_direct_symmetry_rows": nissy_core_direct_symmetry_rows,
        "rubikoptimal_symmetry_rows": rubikoptimal_symmetry_rows,
        "rubikoptimal_symmetry_race_rows": rubikoptimal_symmetry_race_rows,
        "late_nissy_core_direct_fallback_rows": late_nissy_core_direct_fallback_rows,
        "universal_upper_lower_batch_rows": universal_upper_lower_batch_rows,
        "universal_upper_lower_batch_lower_bound_rows": universal_upper_lower_batch_lower_bound_rows,
        "portfolio_prepass_rows": portfolio_prepass_rows,
        "all_universal_optimized_cli": row_set_complete and all(
            row["selected_backend"] in _ALLOWED_UNIVERSAL_SELECTED_BACKENDS for row in rows
        ),
        "all_state_input_only": row_set_complete and all(
            row["input_kind"] == "facelets" and row["source_sequence_provided_to_solver"] is not True
            for row in rows
        ),
        "selected_backends": sorted({str(row["selected_backend"]) for row in rows if row.get("selected_backend")}),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "max_backend_runtime_seconds": max(
            (float(row["backend_runtime_seconds"]) for row in rows if row["backend_runtime_seconds"] is not None),
            default=None,
        ),
        "max_backend_solve_seconds": max(
            (float(row["backend_solve_seconds"]) for row in rows if row["backend_solve_seconds"] is not None),
            default=None,
        ),
        "fast_runtime_proven_for_every_possible_state": False,
        "errors": errors,
        "passed": not errors,
    }

    output = (
        root
        / "results"
        / "processed"
        / f"universal_oracle_cli_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"_{solver}{suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
