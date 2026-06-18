#!/usr/bin/env python
"""Run a resumable low-load sweep over public known-distance 3x3 rows.

The heavy work is delegated to ``scripts/run_universal_oracle_cli.py`` so the
same public CLI/oracle path is exercised for every row.  This wrapper keeps the
campaign reproducible: one offset per artifact, bounded Nissy prepass, resident
H48 fallback, resume/skip behavior, and an aggregate sweep summary.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.runtime import evaluate_idle_status, parse_gib, wait_for_idle  # noqa: E402
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver  # noqa: E402


@dataclass(frozen=True)
class SweepItem:
    offset: int
    artifact_suffix: str
    artifact_path: Path
    command: list[str]


def _number_label(value: float | int) -> str:
    as_float = float(value)
    if as_float.is_integer():
        return str(int(as_float))
    return str(as_float).replace(".", "p")


def _ordered_symmetry_phase_count(
    *,
    enabled: bool,
    h48_symmetry_variants: int = 0,
    nissy_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_variants: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    rubikoptimal_symmetry_variants: int = 0,
) -> int:
    if not enabled:
        return 0
    return sum(
        1
        for variants in (
            h48_symmetry_variants,
            nissy_symmetry_variants,
            nissy_core_direct_symmetry_variants,
            parallel_h48_symmetry_variants,
            rubikoptimal_symmetry_variants,
        )
        if max(0, int(variants)) > 0
    )


def _single_row_artifact_suffix(
    *,
    distance: int,
    offset: int,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float = 30.0,
    fallback_timeout_seconds: float | None = None,
    fallback_nissy_core_direct_timeout_seconds: float | None = 10.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    h48_symmetry_variants: int = 0,
    h48_symmetry_timeout_seconds: float = 0.0,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    no_portfolio_prepass: bool = False,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    h48_upper_bound_proof_max_gap: int = 1,
    preload_table: bool = True,
    h48_auto_min_depth: bool = False,
    label: str,
) -> str:
    suffix = (
        f"known_distance_{distance}_offset{offset}_trimmed_prepass_"
        f"h48_{_number_label(h48_timeout_seconds)}"
    )
    if h48_symmetry_variants > 0:
        suffix += (
            f"_h48sym{h48_symmetry_variants}_"
            f"{_number_label(h48_symmetry_timeout_seconds)}"
        )
    if nissy_symmetry_variants > 0:
        suffix += (
            f"_nissysym{nissy_symmetry_variants}_"
            f"{_number_label(nissy_symmetry_timeout_seconds)}"
        )
    if nissy_core_direct_symmetry_variants > 0:
        suffix += (
            f"_ncoredsym{nissy_core_direct_symmetry_variants}_"
            f"{_number_label(nissy_core_direct_symmetry_timeout_seconds)}"
        )
        if nissy_core_direct_symmetry_max_concurrency > 0:
            suffix += f"_conc{nissy_core_direct_symmetry_max_concurrency}"
    if parallel_h48_symmetry_variants > 0:
        suffix += (
            f"_parallel_h48sym{parallel_h48_symmetry_variants}_"
            f"{_number_label(parallel_h48_symmetry_timeout_seconds)}"
        )
        if parallel_h48_symmetry_max_concurrency > 0:
            suffix += f"_conc{parallel_h48_symmetry_max_concurrency}"
    if _ordered_symmetry_phase_count(
        enabled=parallel_h48_symmetry_order_by_lower_bound,
        h48_symmetry_variants=h48_symmetry_variants,
        nissy_symmetry_variants=nissy_symmetry_variants,
        nissy_core_direct_symmetry_variants=nissy_core_direct_symmetry_variants,
        parallel_h48_symmetry_variants=parallel_h48_symmetry_variants,
        rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
    ):
        suffix += f"_lborder{_number_label(parallel_h48_symmetry_lower_bound_order_timeout_seconds)}"
    if h48_upper_bound_proof_timeout_seconds > 0:
        suffix += (
            f"_ubproof{_number_label(h48_upper_bound_proof_timeout_seconds)}"
            f"_gap{max(1, int(h48_upper_bound_proof_max_gap))}"
        )
    if fallback_timeout_seconds is not None and not _float_equal(
        fallback_timeout_seconds,
        prepass_timeout_seconds,
    ):
        suffix += f"_nissyfb{_number_label(fallback_timeout_seconds)}"
    if no_portfolio_prepass:
        suffix += "_noprepass"
    if (
        fallback_nissy_core_direct_timeout_seconds is not None
        and fallback_nissy_core_direct_timeout_seconds >= 0.0
    ):
        suffix += f"_ncorefb{_number_label(fallback_nissy_core_direct_timeout_seconds)}"
    if resident_race_prepass_timeout_seconds is not None and resident_race_prepass_timeout_seconds >= 0.0:
        suffix += f"_rrpre{_number_label(resident_race_prepass_timeout_seconds)}"
    if rubikoptimal_prepass_timeout_seconds is not None and rubikoptimal_prepass_timeout_seconds >= 0.0:
        suffix += f"_ropre{_number_label(rubikoptimal_prepass_timeout_seconds)}"
    if rubikoptimal_symmetry_variants > 0:
        symmetry_timeout = (
            h48_timeout_seconds
            if rubikoptimal_symmetry_timeout_seconds is None
            else rubikoptimal_symmetry_timeout_seconds
        )
        suffix += f"_rosym{rubikoptimal_symmetry_variants}_{_number_label(symmetry_timeout)}"
        if rubikoptimal_symmetry_max_concurrency > 0:
            suffix += f"_conc{rubikoptimal_symmetry_max_concurrency}"
    if rubikoptimal_race_timeout_seconds is not None and rubikoptimal_race_timeout_seconds >= 0.0:
        suffix += f"_rorace{_number_label(rubikoptimal_race_timeout_seconds)}"
    if rubikoptimal_fallback_timeout_seconds is not None and rubikoptimal_fallback_timeout_seconds >= 0.0:
        suffix += f"_rofb{_number_label(rubikoptimal_fallback_timeout_seconds)}"
    if not preload_table:
        suffix += "_nopreload"
    if h48_auto_min_depth:
        suffix += "_automin"
    return f"{suffix}_{label}"


def _aggregate_artifact_suffix(
    *,
    distance: int,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float = 30.0,
    fallback_timeout_seconds: float | None = None,
    fallback_nissy_core_direct_timeout_seconds: float | None = 10.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    h48_symmetry_variants: int = 0,
    h48_symmetry_timeout_seconds: float = 0.0,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    no_portfolio_prepass: bool = False,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    h48_upper_bound_proof_max_gap: int = 1,
    preload_table: bool = True,
    h48_auto_min_depth: bool = False,
    label: str,
) -> str:
    suffix = f"known_distance_{distance}_trimmed_prepass_h48_{_number_label(h48_timeout_seconds)}"
    if h48_symmetry_variants > 0:
        suffix += (
            f"_h48sym{h48_symmetry_variants}_"
            f"{_number_label(h48_symmetry_timeout_seconds)}"
        )
    if nissy_symmetry_variants > 0:
        suffix += (
            f"_nissysym{nissy_symmetry_variants}_"
            f"{_number_label(nissy_symmetry_timeout_seconds)}"
        )
    if nissy_core_direct_symmetry_variants > 0:
        suffix += (
            f"_ncoredsym{nissy_core_direct_symmetry_variants}_"
            f"{_number_label(nissy_core_direct_symmetry_timeout_seconds)}"
        )
        if nissy_core_direct_symmetry_max_concurrency > 0:
            suffix += f"_conc{nissy_core_direct_symmetry_max_concurrency}"
    if parallel_h48_symmetry_variants > 0:
        suffix += (
            f"_parallel_h48sym{parallel_h48_symmetry_variants}_"
            f"{_number_label(parallel_h48_symmetry_timeout_seconds)}"
        )
        if parallel_h48_symmetry_max_concurrency > 0:
            suffix += f"_conc{parallel_h48_symmetry_max_concurrency}"
    if _ordered_symmetry_phase_count(
        enabled=parallel_h48_symmetry_order_by_lower_bound,
        h48_symmetry_variants=h48_symmetry_variants,
        nissy_symmetry_variants=nissy_symmetry_variants,
        nissy_core_direct_symmetry_variants=nissy_core_direct_symmetry_variants,
        parallel_h48_symmetry_variants=parallel_h48_symmetry_variants,
        rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
    ):
        suffix += f"_lborder{_number_label(parallel_h48_symmetry_lower_bound_order_timeout_seconds)}"
    if h48_upper_bound_proof_timeout_seconds > 0:
        suffix += (
            f"_ubproof{_number_label(h48_upper_bound_proof_timeout_seconds)}"
            f"_gap{max(1, int(h48_upper_bound_proof_max_gap))}"
        )
    if fallback_timeout_seconds is not None and not _float_equal(
        fallback_timeout_seconds,
        prepass_timeout_seconds,
    ):
        suffix += f"_nissyfb{_number_label(fallback_timeout_seconds)}"
    if no_portfolio_prepass:
        suffix += "_noprepass"
    if (
        fallback_nissy_core_direct_timeout_seconds is not None
        and fallback_nissy_core_direct_timeout_seconds >= 0.0
    ):
        suffix += f"_ncorefb{_number_label(fallback_nissy_core_direct_timeout_seconds)}"
    if resident_race_prepass_timeout_seconds is not None and resident_race_prepass_timeout_seconds >= 0.0:
        suffix += f"_rrpre{_number_label(resident_race_prepass_timeout_seconds)}"
    if rubikoptimal_prepass_timeout_seconds is not None and rubikoptimal_prepass_timeout_seconds >= 0.0:
        suffix += f"_ropre{_number_label(rubikoptimal_prepass_timeout_seconds)}"
    if rubikoptimal_symmetry_variants > 0:
        symmetry_timeout = (
            h48_timeout_seconds
            if rubikoptimal_symmetry_timeout_seconds is None
            else rubikoptimal_symmetry_timeout_seconds
        )
        suffix += f"_rosym{rubikoptimal_symmetry_variants}_{_number_label(symmetry_timeout)}"
        if rubikoptimal_symmetry_max_concurrency > 0:
            suffix += f"_conc{rubikoptimal_symmetry_max_concurrency}"
    if rubikoptimal_race_timeout_seconds is not None and rubikoptimal_race_timeout_seconds >= 0.0:
        suffix += f"_rorace{_number_label(rubikoptimal_race_timeout_seconds)}"
    if rubikoptimal_fallback_timeout_seconds is not None and rubikoptimal_fallback_timeout_seconds >= 0.0:
        suffix += f"_rofb{_number_label(rubikoptimal_fallback_timeout_seconds)}"
    if not preload_table:
        suffix += "_nopreload"
    if h48_auto_min_depth:
        suffix += "_automin"
    return f"{suffix}_sweep_{label}"


def _artifact_path(
    root: Path,
    *,
    seed: int,
    profile: str,
    solver: str,
    artifact_suffix: str,
) -> Path:
    return (
        root
        / "results"
        / "processed"
        / f"universal_oracle_cli_seed_{seed}_{profile}_{solver}_{artifact_suffix}.json"
    )


def _scramble_count(root: Path, distance: int) -> int:
    path = root / ".codex_external" / "nissy-core" / "benchmarks" / "scrambles" / f"scrambles-{distance}.txt"
    if not path.exists():
        raise SystemExit(f"missing nissy-core benchmark scramble file: {path}")
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _float_equal(left: Any, right: float) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return False


def _parallel_h48_wave_count(variant_count: int, max_concurrency: int) -> int:
    if variant_count <= 0:
        return 0
    rotation_count = max(0, int(variant_count)) + 1
    concurrency = rotation_count if max_concurrency <= 0 else max(1, min(rotation_count, int(max_concurrency)))
    return (rotation_count + concurrency - 1) // concurrency


def _estimated_command_timeout_seconds(
    *,
    solver_timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float | None,
    fallback_nissy_core_direct_timeout_seconds: float | None,
    h48_symmetry_variants: int,
    h48_symmetry_timeout_seconds: float,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    no_portfolio_prepass: bool = False,
) -> float:
    solver_timeout = max(0.0, float(solver_timeout_seconds))
    portfolio_budget = 0.0 if no_portfolio_prepass else max(0.0, float(prepass_timeout_seconds))
    fallback_budget = solver_timeout if fallback_timeout_seconds is None else max(0.0, float(fallback_timeout_seconds))
    direct_budget = (
        0.0
        if fallback_nissy_core_direct_timeout_seconds is None
        else max(0.0, float(fallback_nissy_core_direct_timeout_seconds))
    )
    rubikoptimal_prepass_budget = (
        0.0
        if rubikoptimal_prepass_timeout_seconds is None or rubikoptimal_prepass_timeout_seconds < 0.0
        else max(0.0, float(rubikoptimal_prepass_timeout_seconds))
    )
    resident_race_prepass_budget = (
        0.0
        if resident_race_prepass_timeout_seconds is None or resident_race_prepass_timeout_seconds < 0.0
        else max(0.0, float(resident_race_prepass_timeout_seconds))
    )
    rubikoptimal_symmetry_timeout = (
        solver_timeout
        if rubikoptimal_symmetry_timeout_seconds is None
        else max(0.0, float(rubikoptimal_symmetry_timeout_seconds))
    )
    rubikoptimal_symmetry_budget = (
        rubikoptimal_symmetry_timeout if max(0, int(rubikoptimal_symmetry_variants)) > 0 else 0.0
    )
    rubikoptimal_race_budget = (
        0.0
        if rubikoptimal_race_timeout_seconds is None or rubikoptimal_race_timeout_seconds < 0.0
        else max(0.0, float(rubikoptimal_race_timeout_seconds))
    )
    rubikoptimal_fallback_budget = (
        0.0
        if rubikoptimal_fallback_timeout_seconds is None or rubikoptimal_fallback_timeout_seconds < 0.0
        else max(0.0, float(rubikoptimal_fallback_timeout_seconds))
    )
    resident_budget = solver_timeout
    resident_symmetry_budget = (
        max(0.0, float(h48_symmetry_timeout_seconds))
        if max(0, int(h48_symmetry_variants)) > 0
        else 0.0
    )
    nissy_symmetry_budget = (
        max(0.0, float(nissy_symmetry_timeout_seconds)) if nissy_symmetry_variants > 0 else 0.0
    )
    direct_symmetry_budget = (
        max(0.0, float(nissy_core_direct_symmetry_timeout_seconds))
        if nissy_core_direct_symmetry_variants > 0
        else 0.0
    )
    parallel_symmetry_budget = (
        max(0.0, float(parallel_h48_symmetry_timeout_seconds))
        if parallel_h48_symmetry_variants > 0
        else 0.0
    )
    symmetry_order_budget = (
        max(0.0, float(parallel_h48_symmetry_lower_bound_order_timeout_seconds))
        * _ordered_symmetry_phase_count(
            enabled=parallel_h48_symmetry_order_by_lower_bound,
            h48_symmetry_variants=h48_symmetry_variants,
            nissy_symmetry_variants=nissy_symmetry_variants,
            nissy_core_direct_symmetry_variants=nissy_core_direct_symmetry_variants,
            parallel_h48_symmetry_variants=parallel_h48_symmetry_variants,
            rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
        )
    )
    h48_upper_bound_proof_budget = max(0.0, float(h48_upper_bound_proof_timeout_seconds))
    grace_seconds = 60.0
    return max(
        solver_timeout + 45.0,
        portfolio_budget
        + resident_race_prepass_budget
        + rubikoptimal_prepass_budget
        + rubikoptimal_symmetry_budget
        + nissy_symmetry_budget
        + direct_symmetry_budget
        + resident_symmetry_budget
        + symmetry_order_budget
        + parallel_symmetry_budget
        + h48_upper_bound_proof_budget
        + rubikoptimal_race_budget
        + resident_budget
        + direct_budget
        + fallback_budget
        + rubikoptimal_fallback_budget
        + grace_seconds,
    )


def _existing_artifact_success(
    path: Path,
    *,
    distance: int,
    offset: int,
    h48_timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float | None = None,
    fallback_nissy_core_direct_timeout_seconds: float | None = 10.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    h48_symmetry_variants: int = 0,
    h48_symmetry_timeout_seconds: float = 0.0,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    h48_upper_bound_proof_max_gap: int = 1,
    preload_table: bool = True,
    h48_auto_min_depth: bool = False,
    no_portfolio_prepass: bool = False,
) -> bool:
    payload = _load_json(path)
    if not payload:
        return False
    fallback_matches = True
    if fallback_timeout_seconds is not None and not _float_equal(
        fallback_timeout_seconds,
        prepass_timeout_seconds,
    ):
        fallback_matches = _float_equal(
            payload.get("portfolio_fallback_timeout_seconds"),
            fallback_timeout_seconds,
        )
    expected_direct = (
        None
        if fallback_nissy_core_direct_timeout_seconds is None
        or fallback_nissy_core_direct_timeout_seconds < 0.0
        else fallback_nissy_core_direct_timeout_seconds
    )
    actual_direct = payload.get("portfolio_fallback_nissy_core_direct_timeout_seconds")
    direct_fallback_matches = (
        actual_direct is None if expected_direct is None else _float_equal(actual_direct, expected_direct)
    )
    resident_race_prepass_matches = (
        payload.get("resident_race_prepass_timeout_seconds") is None
        if resident_race_prepass_timeout_seconds is None or resident_race_prepass_timeout_seconds < 0.0
        else _float_equal(
            payload.get("resident_race_prepass_timeout_seconds"),
            resident_race_prepass_timeout_seconds,
        )
    )
    rubikoptimal_prepass_matches = (
        payload.get("rubikoptimal_prepass_timeout_seconds") is None
        if rubikoptimal_prepass_timeout_seconds is None or rubikoptimal_prepass_timeout_seconds < 0.0
        else _float_equal(payload.get("rubikoptimal_prepass_timeout_seconds"), rubikoptimal_prepass_timeout_seconds)
    )
    rubikoptimal_symmetry_matches = (
        int(payload.get("rubikoptimal_symmetry_variants") or 0)
        == max(0, int(rubikoptimal_symmetry_variants))
        and int(payload.get("rubikoptimal_symmetry_max_concurrency") or 0)
        == max(0, int(rubikoptimal_symmetry_max_concurrency))
        and (
            rubikoptimal_symmetry_variants <= 0
            or rubikoptimal_symmetry_timeout_seconds is None
            or _float_equal(
                payload.get("rubikoptimal_symmetry_timeout_seconds"),
                rubikoptimal_symmetry_timeout_seconds,
            )
        )
    )
    rubikoptimal_race_matches = (
        payload.get("rubikoptimal_race_timeout_seconds") is None
        if rubikoptimal_race_timeout_seconds is None or rubikoptimal_race_timeout_seconds < 0.0
        else _float_equal(payload.get("rubikoptimal_race_timeout_seconds"), rubikoptimal_race_timeout_seconds)
    )
    rubikoptimal_fallback_matches = (
        payload.get("rubikoptimal_fallback_timeout_seconds") is None
        if rubikoptimal_fallback_timeout_seconds is None or rubikoptimal_fallback_timeout_seconds < 0.0
        else _float_equal(payload.get("rubikoptimal_fallback_timeout_seconds"), rubikoptimal_fallback_timeout_seconds)
    )
    h48_upper_bound_proof_enabled = h48_upper_bound_proof_timeout_seconds > 0.0
    h48_upper_bound_proof_matches = (
        _float_equal(
            payload.get("h48_upper_bound_proof_timeout_seconds", 0.0),
            max(0.0, float(h48_upper_bound_proof_timeout_seconds)),
        )
        and int(payload.get("h48_upper_bound_proof_max_gap", 1) or 1)
        == max(1, int(h48_upper_bound_proof_max_gap))
    )
    return (
        payload.get("passed") is True
        and payload.get("outer_command_timed_out") is False
        and payload.get("all_exact") is True
        and payload.get("all_verified") is True
        and payload.get("all_expected_distances_match") is True
        and payload.get("live_solver_shortcuts_disabled") is (not h48_upper_bound_proof_enabled)
        and payload.get("random_cases_enabled") is False
        and payload.get("benchmark_limit_per_distance") == 1
        and payload.get("benchmark_offset_per_distance") == offset
        and payload.get("nissy_benchmark_distances_present") == [distance]
        and _float_equal(payload.get("timeout_seconds"), h48_timeout_seconds)
        and _float_equal(payload.get("resident_h48_batch_timeout_seconds"), h48_timeout_seconds)
        and bool(payload.get("no_portfolio_prepass", False)) is bool(no_portfolio_prepass)
        and (
            no_portfolio_prepass
            or _float_equal(payload.get("portfolio_prepass_timeout_seconds"), prepass_timeout_seconds)
        )
        and fallback_matches
        and direct_fallback_matches
        and resident_race_prepass_matches
        and rubikoptimal_prepass_matches
        and rubikoptimal_symmetry_matches
        and rubikoptimal_race_matches
        and rubikoptimal_fallback_matches
        and h48_upper_bound_proof_matches
        and int(payload.get("resident_h48_symmetry_variants") or 0) == max(0, int(h48_symmetry_variants))
        and int(payload.get("nissy_symmetry_variants") or 0) == max(0, int(nissy_symmetry_variants))
        and int(payload.get("nissy_core_direct_symmetry_variants") or 0)
        == max(0, int(nissy_core_direct_symmetry_variants))
        and int(payload.get("nissy_core_direct_symmetry_max_concurrency") or 0)
        == max(0, int(nissy_core_direct_symmetry_max_concurrency))
        and int(payload.get("parallel_h48_symmetry_variants") or 0)
        == max(0, int(parallel_h48_symmetry_variants))
        and int(payload.get("parallel_h48_symmetry_max_concurrency") or 0)
        == max(0, int(parallel_h48_symmetry_max_concurrency))
        and bool(payload.get("parallel_h48_symmetry_order_by_lower_bound", False))
        is bool(parallel_h48_symmetry_order_by_lower_bound)
        and (
            not parallel_h48_symmetry_order_by_lower_bound
            or _float_equal(
                payload.get("parallel_h48_symmetry_lower_bound_order_timeout_seconds"),
                parallel_h48_symmetry_lower_bound_order_timeout_seconds,
            )
        )
        and bool(payload.get("preload_table", True)) is bool(preload_table)
        and bool(payload.get("h48_auto_min_depth", False)) is bool(h48_auto_min_depth)
        and (
            h48_symmetry_variants <= 0
            or _float_equal(payload.get("resident_h48_symmetry_timeout_seconds"), h48_symmetry_timeout_seconds)
        )
        and (
            nissy_symmetry_variants <= 0
            or _float_equal(payload.get("nissy_symmetry_timeout_seconds"), nissy_symmetry_timeout_seconds)
        )
        and (
            nissy_core_direct_symmetry_variants <= 0
            or _float_equal(
                payload.get("nissy_core_direct_symmetry_timeout_seconds"),
                nissy_core_direct_symmetry_timeout_seconds,
            )
        )
        and (
            parallel_h48_symmetry_variants <= 0
            or _float_equal(
                payload.get("parallel_h48_symmetry_timeout_seconds"),
                parallel_h48_symmetry_timeout_seconds,
            )
        )
    )


def _summarize_artifact(path: Path) -> dict[str, Any]:
    payload = _load_json(path) or {}
    rows = payload.get("rows", [])
    first_row = rows[0] if isinstance(rows, list) and rows else {}
    return {
        "artifact": str(path),
        "artifact_exists": path.exists(),
        "artifact_passed": payload.get("passed"),
        "case_id": first_row.get("case_id") if isinstance(first_row, dict) else None,
        "selected_backend": first_row.get("selected_backend") if isinstance(first_row, dict) else None,
        "status": first_row.get("status") if isinstance(first_row, dict) else None,
        "verified": first_row.get("verified") if isinstance(first_row, dict) else None,
        "solution_length": first_row.get("solution_length") if isinstance(first_row, dict) else None,
        "runtime_seconds": first_row.get("runtime_seconds") if isinstance(first_row, dict) else None,
        "backend_solve_seconds": first_row.get("backend_solve_seconds") if isinstance(first_row, dict) else None,
        "wrapper_wall_seconds": payload.get("wrapper_wall_seconds"),
        "errors": payload.get("errors", []),
    }


def _idle_guard_config(
    *,
    enabled: bool,
    max_load_1m: float,
    max_load_5m: float,
    min_available_gib: float,
    required_checks: int,
    check_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    min_available_memory_bytes = parse_gib(min_available_gib)
    return {
        "enabled": bool(enabled),
        "max_load_1m": max_load_1m,
        "max_load_5m": max_load_5m,
        "min_available_gib": min_available_gib,
        "min_available_memory_bytes": min_available_memory_bytes,
        "required_consecutive_checks": max(1, int(required_checks)),
        "check_interval_seconds": max(0.0, float(check_interval_seconds)),
        "timeout_seconds": max(0.0, float(timeout_seconds)),
    }


def _build_universal_cli_command(
    *,
    python_executable: str,
    profile: str,
    seed: int,
    solver: str,
    distance: int,
    offset: int,
    timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float | None,
    fallback_nissy_core_direct_timeout_seconds: float | None = 10.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    command_timeout_seconds: float,
    threads: int,
    h48_symmetry_variants: int = 0,
    h48_symmetry_timeout_seconds: float = 0.0,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    h48_upper_bound_proof_max_gap: int = 1,
    preload_table: bool = True,
    h48_auto_min_depth: bool = False,
    no_portfolio_prepass: bool = False,
    artifact_suffix: str,
    nice_level: int | None,
    nice_available: bool,
) -> list[str]:
    command = [
        python_executable,
        "scripts/run_universal_oracle_cli.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--no-random-cases",
        "--benchmark-distance",
        str(distance),
        "--benchmark-limit-per-distance",
        "1",
        "--benchmark-offset-per-distance",
        str(offset),
        "--timeout",
        str(timeout_seconds),
        "--resident-h48-batch-timeout",
        str(timeout_seconds),
        "--command-timeout",
        str(command_timeout_seconds),
        "--threads",
        str(threads),
        "--trusted-table",
        "--no-certificate-cache",
        "--artifact-suffix",
        artifact_suffix,
    ]
    if h48_upper_bound_proof_timeout_seconds <= 0.0:
        command.append("--no-upper-lower-certificate")
    command.extend(
        [
            "--h48-upper-bound-proof-timeout",
            str(max(0.0, float(h48_upper_bound_proof_timeout_seconds))),
            "--h48-upper-bound-proof-max-gap",
            str(max(1, int(h48_upper_bound_proof_max_gap))),
        ]
    )
    if no_portfolio_prepass:
        command.append("--no-portfolio-prepass")
    else:
        command.extend(
            [
                "--universal-portfolio-prepass-timeout",
                str(prepass_timeout_seconds),
            ]
        )
    if fallback_timeout_seconds is not None and not _float_equal(
        fallback_timeout_seconds,
        prepass_timeout_seconds,
    ):
        command.extend(
            [
                "--universal-portfolio-fallback-timeout",
                str(fallback_timeout_seconds),
            ]
        )
    command.extend(
        [
            "--universal-fallback-nissy-core-direct-timeout",
            str(
                -1.0
                if fallback_nissy_core_direct_timeout_seconds is None
                else fallback_nissy_core_direct_timeout_seconds
            ),
        ]
    )
    if rubikoptimal_prepass_timeout_seconds is not None and rubikoptimal_prepass_timeout_seconds >= 0.0:
        command.extend(["--universal-rubikoptimal-prepass-timeout", str(rubikoptimal_prepass_timeout_seconds)])
    if rubikoptimal_symmetry_variants > 0:
        command.extend(
            [
                "--universal-rubikoptimal-symmetry-variants",
                str(rubikoptimal_symmetry_variants),
            ]
        )
        if rubikoptimal_symmetry_timeout_seconds is not None:
            command.extend(
                [
                    "--universal-rubikoptimal-symmetry-timeout",
                    str(rubikoptimal_symmetry_timeout_seconds),
                ]
            )
        if rubikoptimal_symmetry_max_concurrency > 0:
            command.extend(
                [
                    "--universal-rubikoptimal-symmetry-max-concurrency",
                    str(rubikoptimal_symmetry_max_concurrency),
                ]
            )
    if rubikoptimal_race_timeout_seconds is not None and rubikoptimal_race_timeout_seconds >= 0.0:
        command.extend(["--universal-rubikoptimal-race-timeout", str(rubikoptimal_race_timeout_seconds)])
    if resident_race_prepass_timeout_seconds is not None and resident_race_prepass_timeout_seconds >= 0.0:
        command.extend(
            [
                "--universal-resident-race-prepass-timeout",
                str(resident_race_prepass_timeout_seconds),
            ]
        )
    if rubikoptimal_fallback_timeout_seconds is not None and rubikoptimal_fallback_timeout_seconds >= 0.0:
        command.extend(["--universal-rubikoptimal-fallback-timeout", str(rubikoptimal_fallback_timeout_seconds)])
    if preload_table:
        command.append("--preload-table")
    if h48_auto_min_depth:
        command.append("--h48-auto-min-depth")
    if h48_symmetry_variants > 0:
        command.extend(
            [
                "--h48-symmetry-variants",
                str(h48_symmetry_variants),
                "--h48-symmetry-timeout",
                str(h48_symmetry_timeout_seconds),
            ]
        )
    if nissy_symmetry_variants > 0:
        command.extend(["--nissy-symmetry-variants", str(nissy_symmetry_variants)])
        if nissy_symmetry_timeout_seconds > 0:
            command.extend(["--nissy-symmetry-timeout", str(nissy_symmetry_timeout_seconds)])
    if nissy_core_direct_symmetry_variants > 0:
        command.extend(
            [
                "--nissy-core-direct-symmetry-variants",
                str(nissy_core_direct_symmetry_variants),
                "--nissy-core-direct-symmetry-timeout",
                str(nissy_core_direct_symmetry_timeout_seconds),
                "--nissy-core-direct-symmetry-max-concurrency",
                str(nissy_core_direct_symmetry_max_concurrency),
            ]
        )
    if parallel_h48_symmetry_variants > 0:
        command.extend(
            [
                "--h48-parallel-symmetry-variants",
                str(parallel_h48_symmetry_variants),
                "--h48-parallel-symmetry-timeout",
                str(parallel_h48_symmetry_timeout_seconds),
                "--h48-parallel-symmetry-max-concurrency",
                str(parallel_h48_symmetry_max_concurrency),
            ]
        )
    if parallel_h48_symmetry_order_by_lower_bound:
        command.append("--symmetry-order-by-h48-lower-bound")
        command.extend(
            [
                "--symmetry-lower-bound-order-timeout",
                str(parallel_h48_symmetry_lower_bound_order_timeout_seconds),
            ]
        )
    if nice_level is not None and nice_level > 0 and nice_available:
        return ["nice", "-n", str(nice_level), *command]
    return command


def _plan_items(
    root: Path,
    *,
    profile: str,
    seed: int,
    solver: str,
    distance: int,
    offsets: list[int],
    timeout_seconds: float,
    prepass_timeout_seconds: float,
    fallback_timeout_seconds: float | None,
    fallback_nissy_core_direct_timeout_seconds: float | None = 10.0,
    resident_race_prepass_timeout_seconds: float | None = None,
    rubikoptimal_prepass_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_variants: int = 0,
    rubikoptimal_symmetry_timeout_seconds: float | None = None,
    rubikoptimal_symmetry_max_concurrency: int = 0,
    rubikoptimal_race_timeout_seconds: float | None = None,
    rubikoptimal_fallback_timeout_seconds: float | None = None,
    command_timeout_seconds: float,
    threads: int,
    h48_symmetry_variants: int,
    h48_symmetry_timeout_seconds: float,
    nissy_symmetry_variants: int = 0,
    nissy_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_variants: int = 0,
    nissy_core_direct_symmetry_timeout_seconds: float = 0.0,
    nissy_core_direct_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_variants: int = 0,
    parallel_h48_symmetry_timeout_seconds: float = 0.0,
    parallel_h48_symmetry_max_concurrency: int = 0,
    parallel_h48_symmetry_order_by_lower_bound: bool = False,
    parallel_h48_symmetry_lower_bound_order_timeout_seconds: float = 30.0,
    h48_upper_bound_proof_timeout_seconds: float = 0.0,
    h48_upper_bound_proof_max_gap: int = 1,
    preload_table: bool,
    h48_auto_min_depth: bool = False,
    no_portfolio_prepass: bool = False,
    label: str,
    nice_level: int | None,
    python_executable: str,
    nice_available: bool,
) -> list[SweepItem]:
    items: list[SweepItem] = []
    for offset in offsets:
        suffix = _single_row_artifact_suffix(
            distance=distance,
            offset=offset,
            h48_timeout_seconds=timeout_seconds,
            prepass_timeout_seconds=prepass_timeout_seconds,
            fallback_timeout_seconds=fallback_timeout_seconds,
            fallback_nissy_core_direct_timeout_seconds=fallback_nissy_core_direct_timeout_seconds,
            resident_race_prepass_timeout_seconds=resident_race_prepass_timeout_seconds,
            rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout_seconds,
            rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
            rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout_seconds,
            rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
            rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout_seconds,
            rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout_seconds,
            h48_symmetry_variants=h48_symmetry_variants,
            h48_symmetry_timeout_seconds=h48_symmetry_timeout_seconds,
            nissy_symmetry_variants=nissy_symmetry_variants,
            nissy_symmetry_timeout_seconds=nissy_symmetry_timeout_seconds,
            nissy_core_direct_symmetry_variants=nissy_core_direct_symmetry_variants,
            nissy_core_direct_symmetry_timeout_seconds=nissy_core_direct_symmetry_timeout_seconds,
            nissy_core_direct_symmetry_max_concurrency=nissy_core_direct_symmetry_max_concurrency,
            parallel_h48_symmetry_variants=parallel_h48_symmetry_variants,
            parallel_h48_symmetry_timeout_seconds=parallel_h48_symmetry_timeout_seconds,
            parallel_h48_symmetry_max_concurrency=parallel_h48_symmetry_max_concurrency,
            parallel_h48_symmetry_order_by_lower_bound=parallel_h48_symmetry_order_by_lower_bound,
            parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
                parallel_h48_symmetry_lower_bound_order_timeout_seconds
            ),
            h48_upper_bound_proof_timeout_seconds=h48_upper_bound_proof_timeout_seconds,
            h48_upper_bound_proof_max_gap=h48_upper_bound_proof_max_gap,
            preload_table=preload_table,
            h48_auto_min_depth=h48_auto_min_depth,
            no_portfolio_prepass=no_portfolio_prepass,
            label=label,
        )
        artifact = _artifact_path(
            root,
            seed=seed,
            profile=profile,
            solver=solver,
            artifact_suffix=suffix,
        )
        command = _build_universal_cli_command(
            python_executable=python_executable,
            profile=profile,
            seed=seed,
            solver=solver,
            distance=distance,
            offset=offset,
            timeout_seconds=timeout_seconds,
            prepass_timeout_seconds=prepass_timeout_seconds,
            fallback_timeout_seconds=fallback_timeout_seconds,
            fallback_nissy_core_direct_timeout_seconds=fallback_nissy_core_direct_timeout_seconds,
            resident_race_prepass_timeout_seconds=resident_race_prepass_timeout_seconds,
            rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout_seconds,
            rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
            rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout_seconds,
            rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
            rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout_seconds,
            rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout_seconds,
            command_timeout_seconds=command_timeout_seconds,
            threads=threads,
            h48_symmetry_variants=h48_symmetry_variants,
            h48_symmetry_timeout_seconds=h48_symmetry_timeout_seconds,
            nissy_symmetry_variants=nissy_symmetry_variants,
            nissy_symmetry_timeout_seconds=nissy_symmetry_timeout_seconds,
            nissy_core_direct_symmetry_variants=nissy_core_direct_symmetry_variants,
            nissy_core_direct_symmetry_timeout_seconds=nissy_core_direct_symmetry_timeout_seconds,
            nissy_core_direct_symmetry_max_concurrency=nissy_core_direct_symmetry_max_concurrency,
            parallel_h48_symmetry_variants=parallel_h48_symmetry_variants,
            parallel_h48_symmetry_timeout_seconds=parallel_h48_symmetry_timeout_seconds,
            parallel_h48_symmetry_max_concurrency=parallel_h48_symmetry_max_concurrency,
            parallel_h48_symmetry_order_by_lower_bound=parallel_h48_symmetry_order_by_lower_bound,
            parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
                parallel_h48_symmetry_lower_bound_order_timeout_seconds
            ),
            h48_upper_bound_proof_timeout_seconds=h48_upper_bound_proof_timeout_seconds,
            h48_upper_bound_proof_max_gap=h48_upper_bound_proof_max_gap,
            preload_table=preload_table,
            h48_auto_min_depth=h48_auto_min_depth,
            no_portfolio_prepass=no_portfolio_prepass,
            artifact_suffix=suffix,
            nice_level=nice_level,
            nice_available=nice_available,
        )
        items.append(SweepItem(offset=offset, artifact_suffix=suffix, artifact_path=artifact, command=command))
    return items


def _write_table(root: Path, rows: list[dict[str, Any]], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"known_distance20_trimmed_prepass_sweep_{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "{\\small\n",
        "\\begin{tabular}{rllrr}\n",
        "\\hline\n",
        "Offset & Sweep status & Backend & Length & Seconds \\\\\n",
        "\\hline\n",
    ]
    for row in rows:
        body.append(
            f"{row['offset']} & {row['sweep_status']} & "
            f"{str(row.get('selected_backend') or '--').replace('_', '\\_')} & "
            f"{row.get('solution_length') or '--'} & {row.get('runtime_seconds') or '--'} \\\\\n"
        )
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["thesis", "stress"], default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--distance", type=int, default=20, choices=range(16, 21))
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--end-offset", type=int, default=None)
    parser.add_argument("--max-new-runs", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--prepass-timeout", type=float, default=30.0)
    parser.add_argument(
        "--fallback-timeout",
        type=float,
        default=None,
        help="Late universal portfolio/Nissy fallback timeout after resident H48; defaults to the main solver timeout.",
    )
    parser.add_argument(
        "--fallback-nissy-core-direct-timeout",
        type=float,
        default=10.0,
        help="Late direct nissy-core cubie-state fallback timeout after resident H48; negative disables it.",
    )
    parser.add_argument(
        "--resident-race-prepass-timeout",
        type=float,
        default=-1.0,
        help=(
            "Run a bounded universal resident H48/Nissy/RubikOptimal race before "
            "later sequential hard-tail phases; negative disables it."
        ),
    )
    parser.add_argument(
        "--rubikoptimal-prepass-timeout",
        type=float,
        default=-1.0,
        help="Table-complete RubikOptimal prepass timeout before H48/Nissy hard-tail phases; negative disables it.",
    )
    parser.add_argument(
        "--rubikoptimal-symmetry-variants",
        type=int,
        default=0,
        help="Try this many non-identity whole-cube rotations through table-complete RubikOptimal.",
    )
    parser.add_argument(
        "--rubikoptimal-symmetry-timeout",
        type=float,
        default=None,
        help="Global RubikOptimal symmetry phase timeout; defaults to the main timeout.",
    )
    parser.add_argument(
        "--rubikoptimal-symmetry-max-concurrency",
        type=int,
        default=0,
        help=(
            "If positive, race RubikOptimal rotated variants with this many concurrent "
            "processes instead of using the sequential batch helper."
        ),
    )
    parser.add_argument(
        "--rubikoptimal-race-timeout",
        type=float,
        default=-1.0,
        help="Table-complete RubikOptimal resident-race timeout for single-state fallthrough; negative disables it.",
    )
    parser.add_argument(
        "--rubikoptimal-fallback-timeout",
        type=float,
        default=-1.0,
        help="Table-complete RubikOptimal fallback timeout after H48/Nissy hard-tail phases; negative disables it.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=None,
        help="Outer public-CLI timeout; defaults to an adaptive estimate from all enabled exact phases.",
    )
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--h48-symmetry-variants", type=int, default=0)
    parser.add_argument("--h48-symmetry-timeout", type=float, default=0.0)
    parser.add_argument("--nissy-symmetry-variants", type=int, default=0)
    parser.add_argument("--nissy-symmetry-timeout", type=float, default=0.0)
    parser.add_argument("--nissy-core-direct-symmetry-variants", type=int, default=0)
    parser.add_argument("--nissy-core-direct-symmetry-timeout", type=float, default=0.0)
    parser.add_argument("--nissy-core-direct-symmetry-max-concurrency", type=int, default=0)
    parser.add_argument("--h48-parallel-symmetry-variants", type=int, default=0)
    parser.add_argument("--h48-parallel-symmetry-timeout", type=float, default=0.0)
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
    parser.add_argument(
        "--h48-upper-bound-proof-timeout",
        type=float,
        default=0.0,
        help=(
            "Enable the public universal oracle's bounded H48 proof phase for "
            "hard-tail rows; 0 keeps the historical live-solver-only shortcut policy."
        ),
    )
    parser.add_argument(
        "--h48-upper-bound-proof-max-gap",
        type=int,
        default=1,
        help="Only run the bounded H48 proof when upper minus lower bound is at most this gap.",
    )
    parser.add_argument("--h48-auto-min-depth", action="store_true")
    parser.add_argument(
        "--no-portfolio-prepass",
        action="store_true",
        help=(
            "Forward --no-portfolio-prepass to the public CLI so campaigns can isolate "
            "resident H48 without an initial Nissy/RubikOptimal portfolio probe."
        ),
    )
    parser.add_argument(
        "--no-preload-table",
        action="store_true",
        help="Do not pass --h48-preload-table to the public CLI; useful for parallel H48 races on loaded machines.",
    )
    parser.add_argument("--nice-level", type=int, default=20)
    parser.add_argument("--runner-timeout-margin", type=float, default=120.0)
    parser.add_argument(
        "--wait-for-idle",
        action="store_true",
        help="Wait for low CPU load and enough available memory before launching each heavy offset run.",
    )
    parser.add_argument(
        "--max-load1",
        type=float,
        default=2.5,
        help="One-minute load threshold used with --wait-for-idle.",
    )
    parser.add_argument(
        "--max-load5",
        type=float,
        default=3.0,
        help="Five-minute load threshold used with --wait-for-idle.",
    )
    parser.add_argument(
        "--min-available-gib",
        type=float,
        default=6.0,
        help="Conservative available-memory threshold used with --wait-for-idle.",
    )
    parser.add_argument(
        "--idle-checks",
        type=int,
        default=2,
        help="Consecutive passing idle checks required before a heavy offset run starts.",
    )
    parser.add_argument(
        "--idle-check-interval",
        type=float,
        default=60.0,
        help="Seconds between --wait-for-idle checks.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=0.0,
        help="Maximum seconds to wait for idle; 0 performs a single guarded check.",
    )
    parser.add_argument("--label", default="lowload")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root
    solver = canonical_h48_solver(args.solver)
    available = _scramble_count(root, args.distance)
    start_offset = max(0, args.start_offset)
    end_offset = available if args.end_offset is None else min(available, max(start_offset, args.end_offset))
    offsets = list(range(start_offset, end_offset))
    if not offsets:
        raise SystemExit("no offsets selected")

    fallback_direct_timeout = (
        None if args.fallback_nissy_core_direct_timeout < 0 else args.fallback_nissy_core_direct_timeout
    )
    resident_race_prepass_timeout = (
        None if args.resident_race_prepass_timeout < 0 else args.resident_race_prepass_timeout
    )
    rubikoptimal_prepass_timeout = (
        None if args.rubikoptimal_prepass_timeout < 0 else args.rubikoptimal_prepass_timeout
    )
    rubikoptimal_symmetry_variants = max(0, args.rubikoptimal_symmetry_variants)
    rubikoptimal_symmetry_timeout = (
        None
        if args.rubikoptimal_symmetry_timeout is None or args.rubikoptimal_symmetry_timeout < 0
        else args.rubikoptimal_symmetry_timeout
    )
    rubikoptimal_symmetry_max_concurrency = max(0, args.rubikoptimal_symmetry_max_concurrency)
    rubikoptimal_race_timeout = None if args.rubikoptimal_race_timeout < 0 else args.rubikoptimal_race_timeout
    rubikoptimal_fallback_timeout = (
        None if args.rubikoptimal_fallback_timeout < 0 else args.rubikoptimal_fallback_timeout
    )
    command_timeout_seconds = (
        args.command_timeout
        if args.command_timeout is not None and args.command_timeout > 0
        else _estimated_command_timeout_seconds(
            solver_timeout_seconds=args.timeout,
            prepass_timeout_seconds=args.prepass_timeout,
            fallback_timeout_seconds=args.fallback_timeout,
            fallback_nissy_core_direct_timeout_seconds=fallback_direct_timeout,
            resident_race_prepass_timeout_seconds=resident_race_prepass_timeout,
            rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout,
            rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
            rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout,
            rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
            rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout,
            rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout,
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
            parallel_h48_symmetry_max_concurrency=max(0, args.h48_parallel_symmetry_max_concurrency),
            parallel_h48_symmetry_order_by_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
            parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
                args.h48_parallel_symmetry_lower_bound_order_timeout
            ),
            h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
            no_portfolio_prepass=args.no_portfolio_prepass,
        )
    )
    idle_guard = _idle_guard_config(
        enabled=args.wait_for_idle,
        max_load_1m=args.max_load1,
        max_load_5m=args.max_load5,
        min_available_gib=args.min_available_gib,
        required_checks=args.idle_checks,
        check_interval_seconds=args.idle_check_interval,
        timeout_seconds=args.idle_timeout,
    )
    idle_guard["initial_status"] = evaluate_idle_status(
        max_load_1m=idle_guard["max_load_1m"],
        max_load_5m=idle_guard["max_load_5m"],
        min_available_memory_bytes=idle_guard["min_available_memory_bytes"],
    ).to_dict()

    nice_available = shutil.which("nice") is not None
    items = _plan_items(
        root,
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        distance=args.distance,
        offsets=offsets,
        timeout_seconds=args.timeout,
        prepass_timeout_seconds=args.prepass_timeout,
        fallback_timeout_seconds=args.fallback_timeout,
        fallback_nissy_core_direct_timeout_seconds=fallback_direct_timeout,
        resident_race_prepass_timeout_seconds=resident_race_prepass_timeout,
        rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout,
        rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
        rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout,
        rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
        rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout,
        rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout,
        command_timeout_seconds=command_timeout_seconds,
        threads=max(1, args.threads),
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
        parallel_h48_symmetry_max_concurrency=max(0, args.h48_parallel_symmetry_max_concurrency),
        parallel_h48_symmetry_order_by_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
        h48_upper_bound_proof_max_gap=max(1, args.h48_upper_bound_proof_max_gap),
        preload_table=not args.no_preload_table,
        h48_auto_min_depth=args.h48_auto_min_depth,
        no_portfolio_prepass=args.no_portfolio_prepass,
        label=args.label,
        nice_level=args.nice_level,
        python_executable=sys.executable,
        nice_available=nice_available,
    )

    env = os.environ.copy()
    env["RUBIK_OPTIMAL_H48_THREADS"] = str(max(1, args.threads))
    env["RUBIK_OPTIMAL_THREADS"] = str(max(1, args.threads))

    rows: list[dict[str, Any]] = []
    attempted = 0
    failures = 0
    idle_deferred = 0
    runner_timeout = max(command_timeout_seconds + args.runner_timeout_margin, command_timeout_seconds)
    started_at = time.perf_counter()
    for item in items:
        existing_success = (
            not args.no_resume
            and _existing_artifact_success(
                item.artifact_path,
                distance=args.distance,
                offset=item.offset,
                h48_timeout_seconds=args.timeout,
                prepass_timeout_seconds=args.prepass_timeout,
                fallback_timeout_seconds=args.fallback_timeout,
                fallback_nissy_core_direct_timeout_seconds=fallback_direct_timeout,
                resident_race_prepass_timeout_seconds=resident_race_prepass_timeout,
                rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout,
                rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
                rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout,
                rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
                rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout,
                rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout,
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
                parallel_h48_symmetry_max_concurrency=max(0, args.h48_parallel_symmetry_max_concurrency),
                parallel_h48_symmetry_order_by_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
                parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
                    args.h48_parallel_symmetry_lower_bound_order_timeout
                ),
                h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
                h48_upper_bound_proof_max_gap=max(1, args.h48_upper_bound_proof_max_gap),
                preload_table=not args.no_preload_table,
                h48_auto_min_depth=args.h48_auto_min_depth,
                no_portfolio_prepass=args.no_portfolio_prepass,
            )
        )
        base_row: dict[str, Any] = {
            "offset": item.offset,
            "artifact_suffix": item.artifact_suffix,
            "artifact": str(item.artifact_path.relative_to(root)),
            "command": " ".join(item.command),
        }
        if existing_success:
            summary = _summarize_artifact(item.artifact_path)
            rows.append({**summary, **base_row, "sweep_status": "skipped_existing_passed"})
            continue
        if args.dry_run:
            rows.append({**base_row, "sweep_status": "planned"})
            continue
        if args.max_new_runs is not None and attempted >= max(0, args.max_new_runs):
            rows.append({**base_row, "sweep_status": "deferred_by_max_new_runs"})
            continue

        idle_wait_summary: dict[str, Any] | None = None
        if args.wait_for_idle:
            idle_ok, idle_samples = wait_for_idle(
                max_load_1m=idle_guard["max_load_1m"],
                max_load_5m=idle_guard["max_load_5m"],
                min_available_memory_bytes=idle_guard["min_available_memory_bytes"],
                required_consecutive_checks=idle_guard["required_consecutive_checks"],
                check_interval_seconds=idle_guard["check_interval_seconds"],
                timeout_seconds=idle_guard["timeout_seconds"],
            )
            idle_wait_summary = {
                "idle_guard_passed": idle_ok,
                "idle_guard_sample_count": len(idle_samples),
                "idle_guard_first_status": idle_samples[0].to_dict() if idle_samples else None,
                "idle_guard_last_status": idle_samples[-1].to_dict() if idle_samples else None,
            }
            if not idle_ok:
                idle_deferred += 1
                rows.append(
                    {
                        **base_row,
                        "sweep_status": "deferred_by_idle_guard",
                        **idle_wait_summary,
                    }
                )
                if not args.keep_going:
                    break
                continue

        attempted += 1
        run_begin = time.perf_counter()
        try:
            completed = subprocess.run(
                item.command,
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=runner_timeout,
            )
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            runner_timed_out = False
        except subprocess.TimeoutExpired as exc:
            return_code = 124
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            runner_timed_out = True
        runner_wall_seconds = time.perf_counter() - run_begin
        success = _existing_artifact_success(
            item.artifact_path,
            distance=args.distance,
            offset=item.offset,
            h48_timeout_seconds=args.timeout,
            prepass_timeout_seconds=args.prepass_timeout,
            fallback_timeout_seconds=args.fallback_timeout,
            fallback_nissy_core_direct_timeout_seconds=fallback_direct_timeout,
            resident_race_prepass_timeout_seconds=resident_race_prepass_timeout,
            rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout,
            rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
            rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout,
            rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
            rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout,
            rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout,
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
            parallel_h48_symmetry_max_concurrency=max(0, args.h48_parallel_symmetry_max_concurrency),
            parallel_h48_symmetry_order_by_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
            parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
                args.h48_parallel_symmetry_lower_bound_order_timeout
            ),
            h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
            h48_upper_bound_proof_max_gap=max(1, args.h48_upper_bound_proof_max_gap),
            preload_table=not args.no_preload_table,
            h48_auto_min_depth=args.h48_auto_min_depth,
            no_portfolio_prepass=args.no_portfolio_prepass,
        )
        summary = _summarize_artifact(item.artifact_path)
        sweep_status = "ran_passed" if success else "ran_failed"
        if not success:
            failures += 1
        rows.append(
            {
                **summary,
                **base_row,
                "sweep_status": sweep_status,
                "runner_return_code": return_code,
                "runner_timed_out": runner_timed_out,
                "runner_wall_seconds": round(runner_wall_seconds, 6),
                "runner_stdout_truncated": stdout[:2000],
                "runner_stderr_truncated": stderr[:2000],
                **(idle_wait_summary or {}),
            }
        )
        if not success and not args.keep_going:
            break

    aggregate_suffix = _aggregate_artifact_suffix(
        distance=args.distance,
        h48_timeout_seconds=args.timeout,
        prepass_timeout_seconds=args.prepass_timeout,
        fallback_timeout_seconds=args.fallback_timeout,
        fallback_nissy_core_direct_timeout_seconds=fallback_direct_timeout,
        resident_race_prepass_timeout_seconds=resident_race_prepass_timeout,
        rubikoptimal_prepass_timeout_seconds=rubikoptimal_prepass_timeout,
        rubikoptimal_symmetry_variants=rubikoptimal_symmetry_variants,
        rubikoptimal_symmetry_timeout_seconds=rubikoptimal_symmetry_timeout,
        rubikoptimal_symmetry_max_concurrency=rubikoptimal_symmetry_max_concurrency,
        rubikoptimal_race_timeout_seconds=rubikoptimal_race_timeout,
        rubikoptimal_fallback_timeout_seconds=rubikoptimal_fallback_timeout,
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
        parallel_h48_symmetry_max_concurrency=max(0, args.h48_parallel_symmetry_max_concurrency),
        parallel_h48_symmetry_order_by_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound,
        parallel_h48_symmetry_lower_bound_order_timeout_seconds=(
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        h48_upper_bound_proof_timeout_seconds=max(0.0, args.h48_upper_bound_proof_timeout),
        h48_upper_bound_proof_max_gap=max(1, args.h48_upper_bound_proof_max_gap),
        preload_table=not args.no_preload_table,
        h48_auto_min_depth=args.h48_auto_min_depth,
        no_portfolio_prepass=args.no_portfolio_prepass,
        label=args.label,
    )
    completed_count = sum(
        1 for row in rows if row["sweep_status"] in {"skipped_existing_passed", "ran_passed"}
    )
    deferred_count = sum(1 for row in rows if row["sweep_status"] == "deferred_by_max_new_runs")
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "distance": args.distance,
        "available_scramble_rows": available,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "selected_offsets": offsets,
        "timeout_seconds": args.timeout,
        "prepass_timeout_seconds": args.prepass_timeout,
        "fallback_timeout_seconds": args.fallback_timeout,
        "fallback_nissy_core_direct_timeout_seconds": fallback_direct_timeout,
        "resident_race_prepass_timeout_seconds": resident_race_prepass_timeout,
        "rubikoptimal_prepass_timeout_seconds": rubikoptimal_prepass_timeout,
        "rubikoptimal_symmetry_variants": rubikoptimal_symmetry_variants,
        "rubikoptimal_symmetry_timeout_seconds": rubikoptimal_symmetry_timeout,
        "rubikoptimal_symmetry_max_concurrency": rubikoptimal_symmetry_max_concurrency,
        "rubikoptimal_race_timeout_seconds": rubikoptimal_race_timeout,
        "rubikoptimal_fallback_timeout_seconds": rubikoptimal_fallback_timeout,
        "command_timeout_seconds": command_timeout_seconds,
        "command_timeout_source": "explicit" if args.command_timeout is not None and args.command_timeout > 0 else "adaptive",
        "threads": max(1, args.threads),
        "resident_h48_symmetry_variants": max(0, args.h48_symmetry_variants),
        "resident_h48_symmetry_timeout_seconds": args.h48_symmetry_timeout,
        "nissy_symmetry_variants": max(0, args.nissy_symmetry_variants),
        "nissy_symmetry_timeout_seconds": args.nissy_symmetry_timeout,
        "nissy_core_direct_symmetry_variants": max(0, args.nissy_core_direct_symmetry_variants),
        "nissy_core_direct_symmetry_timeout_seconds": args.nissy_core_direct_symmetry_timeout,
        "nissy_core_direct_symmetry_max_concurrency": max(
            0, args.nissy_core_direct_symmetry_max_concurrency
        ),
        "parallel_h48_symmetry_variants": max(0, args.h48_parallel_symmetry_variants),
        "parallel_h48_symmetry_timeout_seconds": args.h48_parallel_symmetry_timeout,
        "parallel_h48_symmetry_max_concurrency": max(0, args.h48_parallel_symmetry_max_concurrency),
        "parallel_h48_symmetry_order_by_lower_bound": args.h48_parallel_symmetry_order_by_lower_bound,
        "parallel_h48_symmetry_lower_bound_order_timeout_seconds": (
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        "symmetry_order_by_h48_lower_bound": args.h48_parallel_symmetry_order_by_lower_bound,
        "symmetry_lower_bound_order_timeout_seconds": (
            args.h48_parallel_symmetry_lower_bound_order_timeout
        ),
        "h48_upper_bound_proof_timeout_seconds": max(0.0, args.h48_upper_bound_proof_timeout),
        "h48_upper_bound_proof_max_gap": max(1, args.h48_upper_bound_proof_max_gap),
        "preload_table": not args.no_preload_table,
        "h48_auto_min_depth": args.h48_auto_min_depth,
        "no_portfolio_prepass": args.no_portfolio_prepass,
        "nice_level": args.nice_level if nice_available else None,
        "idle_guard": idle_guard,
        "resume": not args.no_resume,
        "dry_run": args.dry_run,
        "max_new_runs": args.max_new_runs,
        "attempted_new_runs": attempted,
        "completed_offset_count": completed_count,
        "deferred_offset_count": deferred_count,
        "idle_deferred_offset_count": idle_deferred,
        "failed_offset_count": failures,
        "sweep_complete_for_selected_offsets": completed_count == len(offsets),
        "wrapper_wall_seconds": round(time.perf_counter() - started_at, 6),
        "rows": rows,
        "fast_runtime_proven_for_every_possible_state": False,
        "passed": failures == 0 and idle_deferred == 0,
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    output = (
        root
        / "results"
        / "processed"
        / f"known_distance_sweep_seed_{args.seed}_{args.profile}_{solver}_{aggregate_suffix}.json"
    )
    write_json(output, payload)
    table = _write_table(root, rows, f"{solver}_{aggregate_suffix}")
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
