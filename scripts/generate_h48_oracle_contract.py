#!/usr/bin/env python
"""Generate the H48 backend evidence summary (saved corpus only).

This artifact summarises machine-checked evidence drawn from the *saved* H48
stress / certification / streaming corpus and the cited external results. It is
NOT a guarantee of fast-optimal coverage over all ~4.3e19 reachable cube states:
the runtime claims are supported empirically only on the recorded corpus, and
the exactness claim is a public-solver-derived contract conditioned on the cited
God's Number result. The payload keys (e.g. ``all_state_exact_contract_supported``)
record those conditional sub-claims and are intentionally unchanged for
backward compatibility; the per-claim ``support`` strings spell out the
saved-corpus scope.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from rubik_optimal.tables.h48 import (
    ORACLE_H48_SOLVER,
    canonical_h48_solver,
    h48_solver_h_value,
    h48_metadata_path,
    h48_table_path,
    validate_trusted_h48_table,
)


SOURCE_PATHS = {
    "h48_oracle_contract_script": "scripts/generate_h48_oracle_contract.py",
    "nissy_solvers_doc": "native/h48_backend/third_party/nissy_core/doc/solvers.md",
    "nissy_h48_doc": "native/h48_backend/third_party/nissy_core/doc/h48.md",
    "nissy_api_header": "native/h48_backend/third_party/nissy_core/src/nissy.h",
    "nissy_dispatch": "native/h48_backend/third_party/nissy_core/src/solvers/dispatch.h",
    "h48_backend": "native/h48_backend/h48_backend.c",
    "h48_gendata_h48": "native/h48_backend/third_party/nissy_core/src/solvers/h48/gendata_h48.h",
    "h48_coordinate": "native/h48_backend/third_party/nissy_core/src/solvers/h48/coordinate.h",
    "h48_gendata_types_macros": (
        "native/h48_backend/third_party/nissy_core/src/solvers/h48/gendata_types_macros.h"
    ),
    "fast_optimal_oracle_api": "src/rubik_optimal/oracle.py",
    "runtime_helpers": "src/rubik_optimal/runtime.py",
    "cli": "src/rubik_optimal/cli.py",
    "cube_symmetry": "src/rubik_optimal/symmetry.py",
    "exact_certificate_cache": "src/rubik_optimal/exact_certificates.py",
    "fast_optimal_oracle_api_script": "scripts/run_fast_optimal_oracle_api.py",
    "portfolio_optimal_oracle_script": "scripts/run_portfolio_optimal_oracle.py",
    "race_optimal_oracle_script": "scripts/run_race_optimal_oracle.py",
    "resident_race_optimal_oracle_script": "scripts/run_resident_race_optimal_oracle.py",
    "universal_optimal_oracle_script": "scripts/run_universal_optimal_oracle.py",
    "universal_batch_oracle_script": "scripts/run_universal_batch_oracle_corpus.py",
    "universal_oracle_cli_script": "scripts/run_universal_oracle_cli.py",
    "known_distance20_trimmed_prepass_sweep_script": "scripts/run_known_distance20_trimmed_prepass_sweep.py",
    "cloud_hardtail_campaign_script": "scripts/experimental/plan_cloud_hardtail_campaign.py",
    "cloud_hardtail_workload_runner_script": "scripts/experimental/run_cloud_hardtail_workload.py",
    "cloud_hardtail_campaign_runner_script": "scripts/experimental/run_cloud_hardtail_campaign.py",
    "cloud_hardtail_campaign_evaluator_script": "scripts/experimental/evaluate_cloud_hardtail_campaign.py",
    "cloud_hardtail_runbook_script": "scripts/experimental/render_cloud_hardtail_runbook.py",
    "cloud_hardtail_preflight_script": "scripts/experimental/cloud_hardtail_preflight.py",
    "h48_fasttarget_aws_security_group_script": "scripts/experimental/prepare_h48_fasttarget_aws_security_group.py",
    "h48_fasttarget_aws_provisioner_script": "scripts/experimental/provision_h48_fasttarget_aws.py",
    "h48_fasttarget_aws_proof_runner_script": "scripts/experimental/run_h48_fasttarget_aws_proof.py",
    "h48_fasttarget_remote_runner_script": "scripts/experimental/run_h48_fasttarget_remote.py",
    "h48_fasttarget_nonaws_runner_script": "scripts/experimental/run_h48_fasttarget_nonaws_proof.py",
    "h48_fasttarget_local_runner_script": "scripts/experimental/run_h48_fasttarget_local_proof.py",
    "h48_fasttarget_proof_package_script": "scripts/experimental/build_h48_fasttarget_proof_package.py",
    "h48_fasttarget_nonaws_launch_script": "scripts/experimental/prepare_h48_fasttarget_nonaws_launch.py",
    "cloud_hardtail_archive_validator_script": "scripts/experimental/validate_cloud_hardtail_archive.py",
    "universal_symmetry_oracle_script": "scripts/run_universal_symmetry_oracle.py",
    "certificate_cache_inverse_script": "scripts/run_certificate_cache_inverse_closure.py",
    "certificate_cache_symmetry_script": "scripts/run_certificate_cache_symmetry_closure.py",
    "learned_certificate_cache_script": "scripts/run_learned_certificate_cache.py",
    "nissy_benchmark_certificate_importer_script": "scripts/import_nissy_benchmark_certificates.py",
    "h48_capacity_script": "scripts/inspect_h48_capacity.py",
    "h48_proof_volume_inspector_script": "scripts/inspect_h48_proof_volumes.py",
    "h48_stronger_table_campaign_script": "scripts/run_h48_stronger_table_campaign.py",
    "h48_worker_table_validation_script": "scripts/validate_h48_worker_table.py",
    "h48_table_bundle_installer_script": "scripts/install_h48_table_bundle.py",
    "h48_table_bundle_creator_script": "scripts/create_h48_table_bundle.py",
    "h48_split_bundle_smoke_script": "scripts/run_h48_split_bundle_smoke.py",
    "h48_table_generator_script": "scripts/generate_h48_tables.py",
    "h48_generation_probe_script": "scripts/probe_h48_generation_throughput.py",
    "h48_native_backend": "native/h48_backend/h48_backend.c",
    "h48_resident_timeout_survival_script": "scripts/benchmark_h48_resident_timeout_survival.py",
    "h48_batch_partial_timeout_recovery_script": "scripts/benchmark_h48_batch_partial_timeout_recovery.py",
    "h48_lower_bound_partial_timeout_recovery_script": (
        "scripts/benchmark_h48_lower_bound_partial_timeout_recovery.py"
    ),
    "external_nissy_solver": "src/rubik_optimal/solvers/nissy_external.py",
    "external_nissy2_state_bridge": "native/nissy2_state_bridge/nissy2_state_bridge.c",
    "external_nissy_core_worker": "src/rubik_optimal/solvers/nissy_core_worker.py",
    "external_nissy_core_resident_mmap_script": "scripts/run_nissy_core_resident_mmap.py",
    "external_rubikoptimal_solver": "src/rubik_optimal/solvers/rubikoptimal_external.py",
    "external_nissy_table_installer": "scripts/install_nissy_public_table.py",
    "external_nissy_table_verifier": "scripts/verify_nissy_public_tables.py",
    "rubikoptimal_resident_oracle_script": "scripts/benchmark_rubikoptimal_resident_oracle.py",
    "rubikoptimal_oracle_stream_script": "scripts/run_rubikoptimal_oracle_stream.py",
    "optimal_3x3_script": "scripts/run_3x3_optimal.py",
    "native_optimal_solver": "native/optimal_solver/optimal_solver.cpp",
    "python_optimal_native_wrapper": "src/rubik_optimal/solvers/optimal_native.py",
    "python_h48_wrapper": "src/rubik_optimal/solvers/h48_native.py",
    "h48_table_helpers": "src/rubik_optimal/tables/h48.py",
    "distance_wrapper": "src/rubik_optimal/distance.py",
}


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _snippet(text: str, pattern: str, *, window: int = 140) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return None
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return " ".join(text[start:end].split())


def _evidence_file(root: Path, relative: str) -> dict[str, Any] | None:
    payload = _load_json(root / relative)
    if payload is None:
        return None
    return {"path": relative, "payload": payload}


def _latest_evidence_file(
    root: Path,
    pattern: str,
    *,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any] | None:
    candidates = sorted((root / "results" / "processed").glob(pattern), key=lambda path: path.stat().st_mtime)
    for path in reversed(candidates):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if predicate is not None and not predicate(payload):
            continue
        return {"path": _relative(root, path), "payload": payload}
    return None


def _latest_h48_stronger_table_detached_status(
    *,
    root: Path,
    profile: str,
    seed: int,
    target_solver: str,
) -> dict[str, Any] | None:
    """Return the newest local no-AWS detached stronger-table status artifact."""

    processed = root / "results" / "processed"
    pattern = (
        f"h48_stronger_table_detached_status_seed_{seed}_{profile}_"
        f"{target_solver}*.json"
    )
    candidates = sorted(processed.glob(pattern), key=lambda path: path.stat().st_mtime)
    for path in reversed(candidates):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get("profile") != profile or payload.get("seed") != seed:
            continue
        if payload.get("target_solver") != target_solver:
            continue
        artifact_suffix = str(payload.get("artifact_suffix") or "")
        detached_payload_path = str(payload.get("detached_payload_path") or "")
        if "noaws" not in artifact_suffix and "noaws" not in detached_payload_path:
            continue
        return {"path": _relative(root, path), "payload": payload}
    return None


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _latest_cloud_hardtail_evaluation(
    *,
    root: Path,
    profile: str,
    seed: int,
    solver: str,
) -> dict[str, Any] | None:
    processed = root / "results" / "processed"
    candidates = sorted(
        processed.glob("cloud_hardtail_campaign_evaluation_*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    matches: list[dict[str, Any]] = []
    for path in reversed(candidates):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        raw_plan_path = payload.get("plan_path")
        if not raw_plan_path:
            continue
        plan_path = Path(str(raw_plan_path))
        if not plan_path.is_absolute():
            plan_path = root / plan_path
        plan = _load_json(plan_path)
        if not isinstance(plan, dict):
            continue
        if plan.get("profile") != profile or plan.get("seed") != seed:
            continue
        try:
            plan_solver = canonical_h48_solver(str(plan.get("solver", "")))
        except ValueError:
            continue
        if plan_solver != solver:
            continue
        matches.append(
            {
                "path": _relative(root, path),
                "payload": payload,
                "plan_path": _relative(root, plan_path),
                "plan": plan,
            }
        )
    if not matches:
        return None
    full_matches = [match for match in matches if match["plan"].get("claim_scope", "full") == "full"]
    return full_matches[0] if full_matches else matches[0]


def _cloud_hardtail_full_coverage(plan: dict[str, Any]) -> bool:
    hardtail_workloads = [
        workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and workload.get("kind")
        in {
            "public_known_distance_hardtail_sweep",
            "public_known_distance_hardtail_batch",
        }
    ]
    selected_start = int(plan.get("selected_offset_start", -1))
    selected_end = int(plan.get("selected_offset_end", -1))
    available_rows = int(plan.get("available_scramble_rows", -2))
    return (
        plan.get("claim_scope", "full") == "full"
        and plan.get("distance") == 20
        and selected_start == 0
        and selected_end == available_rows
        and bool(hardtail_workloads)
        and any(
            workload.get("kind") == "h48_stronger_table_generation_and_certification"
            for workload in plan.get("workloads", [])
            if isinstance(workload, dict)
        )
        and any(
            workload.get("kind") == "rubikoptimal_table_complete_hardcase"
            for workload in plan.get("workloads", [])
            if isinstance(workload, dict)
        )
    )


def _canonical_solver_or_none(value: Any) -> str | None:
    try:
        return canonical_h48_solver(str(value))
    except (TypeError, ValueError):
        return None


def _h48_metadata_is_oracle_grade(metadata: dict[str, Any] | None, *, solver: str) -> bool:
    if not metadata:
        return False
    try:
        metadata_solver = canonical_h48_solver(str(metadata.get("solver", "")))
    except ValueError:
        return False
    return (
        metadata_solver == solver
        and metadata.get("oracle_grade") is True
        and h48_solver_h_value(metadata_solver) >= h48_solver_h_value(ORACLE_H48_SOLVER)
    )


def _cloud_runtime_proof_from_evaluation(
    evaluation: dict[str, Any] | None,
    *,
    solver: str | None = None,
    target_solver: str | None = None,
    target_table_trusted: bool | None = None,
    solver_table_trusted: bool | None = None,
) -> dict[str, Any]:
    if evaluation is None:
        return {
            "evaluation_present": False,
            "passed": False,
            "target_solver": target_solver,
            "contract_solver_matches_h48_fast_target": (
                solver == target_solver if solver is not None and target_solver is not None else None
            ),
            "contract_solver_meets_h48_fast_target": (
                h48_solver_h_value(solver) >= h48_solver_h_value(target_solver)
                if solver is not None and target_solver is not None
                else None
            ),
            "h48_fast_target_table_trusted": target_table_trusted,
            "contract_solver_table_trusted": solver_table_trusted,
            "reason": "no cloud hard-tail campaign evaluation artifact for this profile/seed/solver",
        }
    payload = evaluation["payload"]
    plan = evaluation["plan"]
    missing_or_failed = payload.get("missing_or_failed_workloads", [])
    full_coverage = _cloud_hardtail_full_coverage(plan)
    plan_solver = _canonical_solver_or_none(plan.get("solver"))
    plan_solver_meets_target = target_solver is None or (
        plan_solver is not None and h48_solver_h_value(plan_solver) >= h48_solver_h_value(target_solver)
    )
    contract_solver_meets_target = target_solver is None or (
        solver is not None and h48_solver_h_value(solver) >= h48_solver_h_value(target_solver)
    )
    target_table_requirement_passed = target_solver is None or solver_table_trusted is True
    passed = (
        full_coverage
        and payload.get("all_required_workloads_passed") is True
        and payload.get("all_required_artifact_integrity_passed") is True
        and payload.get("cloud_runtime_evidence_passed") is True
        and payload.get("thesis_audit_acceptance_gates_passed") is True
        and missing_or_failed == []
        and plan_solver_meets_target
        and contract_solver_meets_target
        and target_table_requirement_passed
    )
    return {
        "evaluation_present": True,
        "evaluation_path": evaluation["path"],
        "plan_path": evaluation["plan_path"],
        "claim_scope": plan.get("claim_scope", "full"),
        "plan_solver": plan_solver,
        "target_solver": target_solver,
        "plan_solver_matches_h48_fast_target": plan_solver == target_solver if target_solver else None,
        "contract_solver_matches_h48_fast_target": solver == target_solver if target_solver else None,
        "plan_solver_meets_h48_fast_target": plan_solver_meets_target,
        "contract_solver_meets_h48_fast_target": contract_solver_meets_target,
        "h48_fast_target_table_trusted": target_table_trusted,
        "contract_solver_table_trusted": solver_table_trusted,
        "full_distance20_hardtail_coverage": full_coverage,
        "all_required_workloads_passed": payload.get("all_required_workloads_passed") is True,
        "all_required_artifact_integrity_passed": (
            payload.get("all_required_artifact_integrity_passed") is True
        ),
        "artifact_integrity_required_workload_count": payload.get(
            "artifact_integrity_required_workload_count"
        ),
        "artifact_integrity_passed_workload_count": payload.get(
            "artifact_integrity_passed_workload_count"
        ),
        "cloud_runtime_evidence_passed": payload.get("cloud_runtime_evidence_passed") is True,
        "thesis_audit_acceptance_gates_passed": (
            payload.get("thesis_audit_acceptance_gates_passed") is True
        ),
        "missing_or_failed_workload_count": (
            len(missing_or_failed) if isinstance(missing_or_failed, list) else None
        ),
        "workload_count": payload.get("workload_count"),
        "evaluated_workload_count": payload.get("evaluated_workload_count"),
        "passed": passed,
        "reason": (
            "passed"
            if passed
            else (
                "full-scope cloud runtime evidence is absent, incomplete, failed, not audit-backed, "
                "not produced with the configured H48 fast target, or the target table is not trusted"
            )
        ),
    }


def _rows_all_exact(rows: list[dict[str, Any]], verified_key: str = "verified") -> bool:
    return bool(rows) and all(row.get("status") == "exact" and row.get(verified_key) is True for row in rows)


def build_contract_payload(*, root: Path, profile: str, seed: int, solver: str) -> dict[str, Any]:
    solver = canonical_h48_solver(solver)
    sources = {name: _read(root, relative) for name, relative in SOURCE_PATHS.items()}
    table_path = h48_table_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata_path = h48_metadata_path(root=root, profile=profile, seed=seed, solver=solver)
    metadata = _load_json(metadata_path)
    trusted_ok, trusted_message = validate_trusted_h48_table(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
        table_path=table_path,
    )

    evidence = {
        "stress": _evidence_file(
            root,
            f"results/processed/optimal_3x3_seed_{seed}_stress_h48h7_oracle.json",
        ),
        "single_call_certification": _evidence_file(
            root,
            f"results/processed/h48_oracle_certification_seed_{seed}_{profile}.json",
        ),
        "trusted_no_preload_certification": _evidence_file(
            root,
            f"results/processed/h48_oracle_certification_seed_{seed}_{profile}_trusted_no_preload.json",
        ),
        "resident_certification": _evidence_file(
            root,
            f"results/processed/h48_resident_certification_seed_{seed}_{profile}_{solver}_trusted.json",
        ),
        "streaming_cli": _evidence_file(
            root,
            f"results/processed/h48_oracle_stream_seed_{seed}_{profile}_trusted.json",
        ),
        "resident_speed": _evidence_file(
            root,
            f"results/processed/h48_resident_oracle_seed_{seed}_{profile}_{solver}_trusted.json",
        ),
        "fast_optimal_oracle_api": _evidence_file(
            root,
            f"results/processed/fast_optimal_oracle_api_seed_{seed}_{profile}_{solver}_trusted.json",
        ),
        "nissy_public_table_install": _evidence_file(
            root,
            f"results/processed/nissy_public_table_install_seed_{seed}_{profile}_pt_nxopt31_HTM_installed.json",
        ),
        "nissy_public_tables_complete": _latest_evidence_file(
            root,
            f"nissy_public_tables_complete_seed_{seed}_{profile}_complete_public*.json",
            predicate=lambda payload: (
                payload.get("profile") == profile
                and payload.get("seed") == seed
                and payload.get("archive_table_entry_count") == payload.get("installed_table_count")
            ),
        )
        or _evidence_file(
            root,
            f"results/processed/nissy_public_tables_complete_seed_{seed}_{profile}_complete_public.json",
        ),
        "nissy_optimal_thesis": _evidence_file(
            root,
            f"results/processed/optimal_3x3_seed_{seed}_{profile}_nissy_optimal.json",
        ),
        "nissy_optimal_stress": _evidence_file(
            root,
            f"results/processed/optimal_3x3_seed_{seed}_stress_nissy_optimal.json",
        ),
        "nissy_core_direct_thesis": _evidence_file(
            root,
            f"results/processed/optimal_3x3_seed_{seed}_{profile}_nissy_core_direct_lowload.json",
        ),
        "nissy_core_resident_mmap": _evidence_file(
            root,
            f"results/processed/nissy_core_resident_mmap_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "portfolio_nissy_first": _evidence_file(
            root,
            f"results/processed/portfolio_optimal_oracle_seed_{seed}_{profile}_nissy_first_lowload.json",
        ),
        "portfolio_nissy_state_recovery": _evidence_file(
            root,
            f"results/processed/portfolio_optimal_oracle_seed_{seed}_{profile}_nissy_state_recovery_lowload.json",
        ),
        "portfolio_nissy_core_direct_state": _evidence_file(
            root,
            f"results/processed/portfolio_optimal_oracle_seed_{seed}_{profile}_nissy_core_direct_state_lowload.json",
        ),
        "portfolio_superflip_fallback": _evidence_file(
            root,
            f"results/processed/portfolio_optimal_oracle_seed_{seed}_{profile}_superflip_fallback_lowload.json",
        ),
        "portfolio_superflip_certificate_cache": _evidence_file(
            root,
            f"results/processed/portfolio_optimal_oracle_seed_{seed}_{profile}_superflip_certificate_cache_lowload.json",
        ),
        "race_optimal_oracle": _evidence_file(
            root,
            f"results/processed/race_optimal_oracle_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "race_nissy_core_direct": _evidence_file(
            root,
            f"results/processed/race_optimal_oracle_seed_{seed}_{profile}_{solver}_nissy_core_direct_lowload.json",
        ),
        "resident_race_optimal_oracle": _evidence_file(
            root,
            f"results/processed/resident_race_optimal_oracle_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "resident_race_nissy_core_direct": _evidence_file(
            root,
            f"results/processed/resident_race_optimal_oracle_seed_{seed}_{profile}_{solver}_nissy_core_direct_lowload.json",
        ),
        "universal_optimal_oracle": _evidence_file(
            root,
            f"results/processed/universal_optimal_oracle_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "universal_nissy_core_direct": _evidence_file(
            root,
            f"results/processed/universal_optimal_oracle_seed_{seed}_{profile}_{solver}_nissy_core_direct_lowload.json",
        ),
        "universal_rubikoptimal_race": _evidence_file(
            root,
            f"results/processed/universal_optimal_oracle_seed_{seed}_{profile}_{solver}_rubikoptimal_race_lowload.json",
        ),
        "rubikoptimal_resident_oracle": _evidence_file(
            root,
            f"results/processed/rubikoptimal_resident_oracle_seed_{seed}_{profile}_lowload.json",
        ),
        "rubikoptimal_oracle_stream": _evidence_file(
            root,
            f"results/processed/rubikoptimal_oracle_stream_seed_{seed}_{profile}_lowload.json",
        ),
        "universal_h48_symmetry": _evidence_file(
            root,
            f"results/processed/universal_optimal_oracle_seed_{seed}_{profile}_{solver}_h48_symmetry_lowload.json",
        ),
        "universal_batch_oracle_corpus": _evidence_file(
            root,
            f"results/processed/universal_batch_oracle_corpus_seed_{seed}_{profile}_{solver}_batch_lowload.json",
        ),
        "universal_resident_h48_batch": _evidence_file(
            root,
            f"results/processed/universal_batch_oracle_corpus_seed_{seed}_{profile}_{solver}_resident_h48_batch_lowload.json",
        ),
        "universal_oracle_cli": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_optimized_lowload.json",
        ),
        "universal_oracle_cli_broader": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_broader_lowload.json",
        ),
        "universal_oracle_cli_adaptive": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_adaptive_lowload.json",
        ),
        "universal_oracle_cli_expanded_adaptive": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_expanded_adaptive_lowload.json",
        ),
        "universal_oracle_cli_h48_symmetry": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_h48_symmetry_lowload.json",
        ),
        "universal_oracle_cli_h48_parallel_symmetry": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_h48_parallel_symmetry_lowload.json",
        ),
        "universal_oracle_cli_rotational_lower_bound_certificate": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_rotational_lower_bound_certificate_direct_lowload.json",
        ),
        "universal_oracle_cli_upper_lower_batch": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_upper_lower_batch_no_cache_lowload.json",
        ),
        "universal_oracle_cli_late_nissy_core_direct_fallback": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_late_nissy_core_direct_fallback_lowload.json",
        ),
        "universal_oracle_cli_live_no_shortcuts": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_live_no_shortcuts_lowload.json",
        ),
        "universal_oracle_cli_live_no_shortcuts_broader": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_live_no_shortcuts_broader_lowload.json",
        ),
        "universal_oracle_cli_known_distance_17": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_17_no_shortcuts_lowload.json",
        ),
        "universal_oracle_cli_known_distance_adaptive": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_17_18_adaptive_symmetry_lowload.json",
        ),
        "universal_oracle_cli_known_distance_19": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_19_adaptive_symmetry_lowload.json",
        ),
        "universal_oracle_cli_known_distance_20": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_20_adaptive_symmetry_lowload.json",
        ),
        "universal_oracle_cli_known_distance_20_offset1": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_20_offset1_adaptive_symmetry_lowload.json",
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.json",
        ),
        "nissy_benchmark_certificates": _evidence_file(
            root,
            f"results/processed/nissy_benchmark_certificates_seed_{seed}_{profile}_distances16_20.json",
        ),
        "universal_oracle_cli_known_distance_certificate_cache": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_16_20_certificate_cache_lowload.json",
        ),
        "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live": _evidence_file(
            root,
            f"results/processed/universal_oracle_cli_seed_{seed}_{profile}_{solver}_known_distance_20_offset2_trimmed_prepass_h48_180_ropre300_rorace120_rofb300_nopreload_rubikoptimal_live_lowload.json",
        ),
        "known_distance_20_offset2_rubikoptimal_live_sweep": _evidence_file(
            root,
            f"results/processed/known_distance_sweep_seed_{seed}_{profile}_{solver}_known_distance_20_trimmed_prepass_h48_180_ropre300_rorace120_rofb300_nopreload_sweep_rubikoptimal_live_lowload.json",
        ),
        "universal_symmetry_oracle": _evidence_file(
            root,
            f"results/processed/universal_symmetry_oracle_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "certificate_cache_inverse_closure": _evidence_file(
            root,
            f"results/processed/certificate_cache_inverse_closure_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "certificate_cache_symmetry_closure": _evidence_file(
            root,
            f"results/processed/certificate_cache_symmetry_closure_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "certificate_cache_expanded_symmetry_closure": _evidence_file(
            root,
            f"results/processed/certificate_cache_symmetry_closure_seed_{seed}_{profile}_{solver}_expanded_default_lowload.json",
        ),
        "learned_certificate_cache": _evidence_file(
            root,
            f"results/processed/learned_certificate_cache_seed_{seed}_{profile}_{solver}_lowload.json",
        ),
        "h48_capacity": _evidence_file(
            root,
            f"results/processed/h48_capacity_seed_{seed}_{profile}_lowload.json",
        ),
        "h48_proof_volume_candidates": _evidence_file(
            root,
            f"results/processed/h48_proof_volume_candidates_seed_{seed}_{profile}_"
            "h48h10_local_noaws_current.json",
        ),
        "h48_generation_probe": _evidence_file(
            root,
            f"results/processed/h48_generation_probe_seed_{seed}_{profile}_h48h8_lowload_15s.json",
        ),
        "h48_stronger_table_detached_status": _latest_h48_stronger_table_detached_status(
            root=root,
            profile=profile,
            seed=seed,
            target_solver="h48h8",
        ),
        "h48_fasttarget_stronger_table_detached_status": _latest_h48_stronger_table_detached_status(
            root=root,
            profile=profile,
            seed=seed,
            target_solver="h48h10",
        ),
        "h48_fasttarget_runbook": _evidence_file(
            root,
            "results/processed/cloud_hardtail_runbook_cloud_20260601_h48h10_fasttarget_batch10.json",
        ),
        "h48_fasttarget_assumed_nonaws_preflight": _evidence_file(
            root,
            f"results/processed/cloud_hardtail_preflight_seed_{seed}_{profile}_"
            "h48h10_assumed_nonaws_16c64g250g.json",
        ),
        "h48_fasttarget_aws_provision_dryrun": _evidence_file(
            root,
            "results/processed/"
            "aws_h48_fasttarget_provision_cloud_20260601_h48h10_fasttarget_batch10_"
            "aws_dryrun.json",
        ),
        "h48_fasttarget_aws_security_group_dryrun": _evidence_file(
            root,
            "results/processed/aws_h48_fasttarget_security_group_aws_sg_dryrun.json",
        ),
        "h48_fasttarget_aws_proof_run_dryrun": _evidence_file(
            root,
            "results/processed/"
            "aws_h48_fasttarget_proof_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "aws_proof_dryrun.json",
        ),
        "h48_fasttarget_remote_preflight_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_preflight_dryrun.json",
        ),
        "h48_fasttarget_remote_start_prerequisites_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_start_prerequisites_dryrun.json",
        ),
        "h48_fasttarget_remote_status_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_status_dryrun.json",
        ),
        "h48_fasttarget_remote_wait_prerequisites_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_wait_prerequisites_dryrun.json",
        ),
        "h48_fasttarget_remote_recover_prerequisite_metadata_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_recover_prerequisite_metadata_dryrun.json",
        ),
        "h48_fasttarget_remote_wait_prerequisites_install_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_wait_prerequisites_install_dryrun.json",
        ),
        "h48_fasttarget_remote_resume_install_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_resume_install_dryrun.json",
        ),
        "h48_fasttarget_remote_staged_proof_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_staged_proof_dryrun.json",
        ),
        "h48_fasttarget_remote_detached_staged_proof_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_detached_staged_proof_dryrun.json",
        ),
        "h48_fasttarget_remote_start_full_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_start_full_dryrun.json",
        ),
        "h48_fasttarget_remote_wait_full_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_remote_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_wait_full_dryrun.json",
        ),
        "h48_fasttarget_nonaws_detached_staged_proof_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_nonaws_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_detached_staged_dryrun_noaws_workbatch_validated.json",
        ),
        "h48_fasttarget_nonaws_detached_staged_proof_split_dryrun": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_nonaws_run_cloud_20260601_h48h10_fasttarget_batch10_"
            "h48h10_detached_staged_dryrun_noaws_splitbundle_validated.json",
        ),
        "h48_fasttarget_nonaws_proof_package": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_nonaws_proof_package_seed_2026_thesis_h48h10_"
            "nonaws_splitbundle_validated.json",
        ),
        "h48_fasttarget_nonaws_launch_preparation": _evidence_file(
            root,
            "results/processed/"
            "h48_fasttarget_nonaws_launch_preparation_seed_2026_thesis_h48h10_"
            "current_laptop_launchcheck_20260603.json",
        ),
        "h48_split_bundle_smoke": _evidence_file(
            root,
            f"results/processed/h48_split_bundle_smoke_seed_{seed}_{profile}_h48h0_local.json",
        ),
        "h48_split_bundle_oracle_grade_smoke": _evidence_file(
            root,
            "results/processed/"
            f"h48_split_bundle_smoke_seed_{seed}_{profile}_h48h7_oracle_grade_local.json",
        ),
    }
    cloud_hardtail_evaluation = _latest_cloud_hardtail_evaluation(
        root=root,
        profile=profile,
        seed=seed,
        solver=solver,
    )
    evidence["cloud_hardtail_campaign_evaluation"] = cloud_hardtail_evaluation
    h48_capacity_payload = evidence["h48_capacity"]["payload"] if evidence["h48_capacity"] else {}
    h48_stronger_table_status_payload = (
        evidence["h48_stronger_table_detached_status"]["payload"]
        if evidence["h48_stronger_table_detached_status"]
        else {}
    )
    h48_stronger_table_wait_safe = (
        h48_stronger_table_status_payload.get("wait_safe_progress") or {}
        if h48_stronger_table_status_payload
        else {}
    )
    h48_stronger_table_generation_progress = (
        h48_stronger_table_status_payload.get("generation_log_progress") or {}
        if h48_stronger_table_status_payload
        else {}
    )
    h48_fasttarget_stronger_table_status_payload = (
        evidence["h48_fasttarget_stronger_table_detached_status"]["payload"]
        if evidence["h48_fasttarget_stronger_table_detached_status"]
        else {}
    )
    h48_fasttarget_stronger_table_wait_safe = (
        h48_fasttarget_stronger_table_status_payload.get("wait_safe_progress") or {}
        if h48_fasttarget_stronger_table_status_payload
        else {}
    )
    h48_fasttarget_stronger_table_generation_progress = (
        h48_fasttarget_stronger_table_status_payload.get("generation_log_progress") or {}
        if h48_fasttarget_stronger_table_status_payload
        else {}
    )
    h48_capacity_plan = (
        h48_capacity_payload.get("h48_stronger_table_build_plan", []) if h48_capacity_payload else []
    )
    h48_capacity_gate = (
        h48_capacity_payload.get("all_state_fast_oracle_completion_gate", {})
        if h48_capacity_payload
        else {}
    )
    h48_capacity_fast_target_solver = _canonical_solver_or_none(
        h48_capacity_gate.get("target_solver") or h48_capacity_payload.get("h48_fast_target_solver")
    )
    h48_capacity_fast_target_table_trusted = h48_capacity_gate.get("target_table_trusted") is True
    h48_capacity_options = h48_capacity_payload.get("h48_stronger_table_generation_plan_options") or {}
    h48_capacity_plan_solvers = [row.get("solver") for row in h48_capacity_plan]
    h48_capacity_plan_recommends_optimized_generation = bool(h48_capacity_plan) and all(
        "--require-safe" in str(row.get("recommended_command", ""))
        and "--gendata-workbatch 256" in str(row.get("recommended_command", ""))
        and "--skip-generation-distribution-scan" in str(row.get("recommended_command", ""))
        and "--mmap-sync-mode async" in str(row.get("recommended_command", ""))
        and "--backend-cflag=-march=native" in str(row.get("recommended_command", ""))
        and row.get("h48_gendata_workbatch") == 256
        and row.get("h48_generation_distribution_mode") == "expected_constants"
        and row.get("h48_generation_mmap_sync_mode") == "async"
        and row.get("h48_backend_extra_cflags") == ["-march=native"]
        for row in h48_capacity_plan
    )
    h48_capacity_fast_target_proof_plan_valid = (
        bool(h48_capacity_payload)
        and h48_capacity_payload.get("profile") == profile
        and h48_capacity_payload.get("seed") == seed
        and h48_capacity_payload.get("next_missing_oracle_grade_solver") == "h48h8"
        and h48_capacity_payload.get("h48_first_stronger_solver") == "h48h8"
        and h48_capacity_payload.get("h48_fast_target_solver") == "h48h10"
        and h48_capacity_plan_solvers == ["h48h8", "h48h9", "h48h10", "h48h11"]
        and h48_capacity_options.get("h48_gendata_workbatch") == 256
        and h48_capacity_options.get("h48_generation_distribution_mode") == "expected_constants"
        and h48_capacity_options.get("h48_generation_mmap_sync_mode") == "async"
        and h48_capacity_options.get("h48_backend_extra_cflags") == ["-march=native"]
        and h48_capacity_plan_recommends_optimized_generation
        and h48_capacity_gate.get("target_solver") == "h48h10"
        and h48_capacity_gate.get("first_missing_ladder_solver") == "h48h8"
        and h48_capacity_gate.get("target_table_expected_size_bytes") == 30_336_314_216
        and h48_capacity_gate.get("target_upstream_benchmark_has_distance20_timing") is True
        and h48_capacity_gate.get("target_upstream_benchmark_has_superflip_timing") is True
        and h48_capacity_gate.get("can_claim_fast_oracle_for_every_possible_state") is False
    )
    contract_solver_matches_fast_target = solver == h48_capacity_fast_target_solver
    contract_solver_meets_fast_target = (
        h48_capacity_fast_target_solver is not None
        and h48_solver_h_value(solver) >= h48_solver_h_value(h48_capacity_fast_target_solver)
    )
    cloud_runtime_proof = _cloud_runtime_proof_from_evaluation(
        cloud_hardtail_evaluation,
        solver=solver,
        target_solver=h48_capacity_fast_target_solver,
        target_table_trusted=h48_capacity_fast_target_table_trusted,
        solver_table_trusted=trusted_ok,
    )

    stress_rows = evidence["stress"]["payload"].get("rows", []) if evidence["stress"] else []
    resident_cert_rows = (
        evidence["resident_certification"]["payload"].get("rows", [])
        if evidence["resident_certification"]
        else []
    )
    streaming_rows = evidence["streaming_cli"]["payload"].get("rows", []) if evidence["streaming_cli"] else []
    resident_speed_payload = evidence["resident_speed"]["payload"] if evidence["resident_speed"] else {}
    api_payload = evidence["fast_optimal_oracle_api"]["payload"] if evidence["fast_optimal_oracle_api"] else {}
    api_rows = api_payload.get("rows", []) if api_payload else []
    nissy_install_payload = (
        evidence["nissy_public_table_install"]["payload"]
        if evidence["nissy_public_table_install"]
        else {}
    )
    nissy_install_target = root / str(nissy_install_payload.get("target_path", ""))
    nissy_complete_payload = (
        evidence["nissy_public_tables_complete"]["payload"]
        if evidence["nissy_public_tables_complete"]
        else {}
    )
    nissy_optimal_thesis_payload = (
        evidence["nissy_optimal_thesis"]["payload"] if evidence["nissy_optimal_thesis"] else {}
    )
    nissy_optimal_thesis_rows = (
        nissy_optimal_thesis_payload.get("rows", []) if nissy_optimal_thesis_payload else []
    )
    nissy_optimal_stress_payload = (
        evidence["nissy_optimal_stress"]["payload"] if evidence["nissy_optimal_stress"] else {}
    )
    nissy_optimal_stress_rows = (
        nissy_optimal_stress_payload.get("rows", []) if nissy_optimal_stress_payload else []
    )
    nissy_core_direct_payload = (
        evidence["nissy_core_direct_thesis"]["payload"]
        if evidence["nissy_core_direct_thesis"]
        else {}
    )
    nissy_core_direct_rows = nissy_core_direct_payload.get("rows", []) if nissy_core_direct_payload else []
    nissy_core_resident_mmap_payload = (
        evidence["nissy_core_resident_mmap"]["payload"]
        if evidence["nissy_core_resident_mmap"]
        else {}
    )
    nissy_core_resident_mmap_rows = (
        nissy_core_resident_mmap_payload.get("rows", [])
        if nissy_core_resident_mmap_payload
        else []
    )
    trusted_no_preload_payload = (
        evidence["trusted_no_preload_certification"]["payload"]
        if evidence["trusted_no_preload_certification"]
        else {}
    )
    portfolio_nissy_payload = (
        evidence["portfolio_nissy_first"]["payload"] if evidence["portfolio_nissy_first"] else {}
    )
    portfolio_nissy_rows = portfolio_nissy_payload.get("rows", []) if portfolio_nissy_payload else []
    portfolio_state_recovery_payload = (
        evidence["portfolio_nissy_state_recovery"]["payload"]
        if evidence["portfolio_nissy_state_recovery"]
        else {}
    )
    portfolio_state_recovery_rows = (
        portfolio_state_recovery_payload.get("rows", []) if portfolio_state_recovery_payload else []
    )
    portfolio_nissy_core_direct_state_payload = (
        evidence["portfolio_nissy_core_direct_state"]["payload"]
        if evidence["portfolio_nissy_core_direct_state"]
        else {}
    )
    portfolio_nissy_core_direct_state_rows = (
        portfolio_nissy_core_direct_state_payload.get("rows", [])
        if portfolio_nissy_core_direct_state_payload
        else []
    )
    portfolio_superflip_payload = (
        evidence["portfolio_superflip_fallback"]["payload"]
        if evidence["portfolio_superflip_fallback"]
        else {}
    )
    portfolio_superflip_rows = (
        portfolio_superflip_payload.get("rows", []) if portfolio_superflip_payload else []
    )
    portfolio_cache_payload = (
        evidence["portfolio_superflip_certificate_cache"]["payload"]
        if evidence["portfolio_superflip_certificate_cache"]
        else {}
    )
    portfolio_cache_rows = portfolio_cache_payload.get("rows", []) if portfolio_cache_payload else []
    race_payload = evidence["race_optimal_oracle"]["payload"] if evidence["race_optimal_oracle"] else {}
    race_rows = race_payload.get("rows", []) if race_payload else []
    race_nissy_core_payload = (
        evidence["race_nissy_core_direct"]["payload"]
        if evidence["race_nissy_core_direct"]
        else {}
    )
    race_nissy_core_rows = race_nissy_core_payload.get("rows", []) if race_nissy_core_payload else []
    resident_race_payload = (
        evidence["resident_race_optimal_oracle"]["payload"]
        if evidence["resident_race_optimal_oracle"]
        else {}
    )
    resident_race_rows = resident_race_payload.get("rows", []) if resident_race_payload else []
    resident_race_nissy_core_payload = (
        evidence["resident_race_nissy_core_direct"]["payload"]
        if evidence["resident_race_nissy_core_direct"]
        else {}
    )
    resident_race_nissy_core_rows = (
        resident_race_nissy_core_payload.get("rows", []) if resident_race_nissy_core_payload else []
    )
    universal_payload = (
        evidence["universal_optimal_oracle"]["payload"]
        if evidence["universal_optimal_oracle"]
        else {}
    )
    universal_rows = universal_payload.get("rows", []) if universal_payload else []
    universal_nissy_core_payload = (
        evidence["universal_nissy_core_direct"]["payload"]
        if evidence["universal_nissy_core_direct"]
        else {}
    )
    universal_nissy_core_rows = (
        universal_nissy_core_payload.get("rows", []) if universal_nissy_core_payload else []
    )
    universal_rubikoptimal_race_payload = (
        evidence["universal_rubikoptimal_race"]["payload"]
        if evidence["universal_rubikoptimal_race"]
        else {}
    )
    universal_rubikoptimal_race_rows = (
        universal_rubikoptimal_race_payload.get("rows", [])
        if universal_rubikoptimal_race_payload
        else []
    )
    rubikoptimal_resident_payload = (
        evidence["rubikoptimal_resident_oracle"]["payload"]
        if evidence["rubikoptimal_resident_oracle"]
        else {}
    )
    rubikoptimal_resident_rows = (
        rubikoptimal_resident_payload.get("rows", []) if rubikoptimal_resident_payload else []
    )
    rubikoptimal_stream_payload = (
        evidence["rubikoptimal_oracle_stream"]["payload"]
        if evidence["rubikoptimal_oracle_stream"]
        else {}
    )
    rubikoptimal_stream_rows = (
        rubikoptimal_stream_payload.get("rows", []) if rubikoptimal_stream_payload else []
    )
    universal_h48_symmetry_payload = (
        evidence["universal_h48_symmetry"]["payload"]
        if evidence["universal_h48_symmetry"]
        else {}
    )
    universal_h48_symmetry_rows = (
        universal_h48_symmetry_payload.get("rows", []) if universal_h48_symmetry_payload else []
    )
    universal_batch_payload = (
        evidence["universal_batch_oracle_corpus"]["payload"]
        if evidence["universal_batch_oracle_corpus"]
        else {}
    )
    universal_batch_rows = universal_batch_payload.get("rows", []) if universal_batch_payload else []
    universal_resident_h48_batch_payload = (
        evidence["universal_resident_h48_batch"]["payload"]
        if evidence["universal_resident_h48_batch"]
        else {}
    )
    universal_resident_h48_batch_rows = (
        universal_resident_h48_batch_payload.get("rows", [])
        if universal_resident_h48_batch_payload
        else []
    )
    universal_oracle_cli_payload = (
        evidence["universal_oracle_cli"]["payload"]
        if evidence["universal_oracle_cli"]
        else {}
    )
    universal_oracle_cli_rows = (
        universal_oracle_cli_payload.get("rows", []) if universal_oracle_cli_payload else []
    )
    universal_oracle_cli_broader_payload = (
        evidence["universal_oracle_cli_broader"]["payload"]
        if evidence["universal_oracle_cli_broader"]
        else {}
    )
    universal_oracle_cli_broader_rows = (
        universal_oracle_cli_broader_payload.get("rows", [])
        if universal_oracle_cli_broader_payload
        else []
    )
    universal_oracle_cli_adaptive_payload = (
        evidence["universal_oracle_cli_adaptive"]["payload"]
        if evidence["universal_oracle_cli_adaptive"]
        else {}
    )
    universal_oracle_cli_adaptive_rows = (
        universal_oracle_cli_adaptive_payload.get("rows", [])
        if universal_oracle_cli_adaptive_payload
        else []
    )
    universal_oracle_cli_expanded_payload = (
        evidence["universal_oracle_cli_expanded_adaptive"]["payload"]
        if evidence["universal_oracle_cli_expanded_adaptive"]
        else {}
    )
    universal_oracle_cli_expanded_rows = (
        universal_oracle_cli_expanded_payload.get("rows", [])
        if universal_oracle_cli_expanded_payload
        else []
    )
    universal_oracle_cli_h48_symmetry_payload = (
        evidence["universal_oracle_cli_h48_symmetry"]["payload"]
        if evidence["universal_oracle_cli_h48_symmetry"]
        else {}
    )
    universal_oracle_cli_h48_symmetry_rows = (
        universal_oracle_cli_h48_symmetry_payload.get("rows", [])
        if universal_oracle_cli_h48_symmetry_payload
        else []
    )
    universal_oracle_cli_h48_parallel_symmetry_payload = (
        evidence["universal_oracle_cli_h48_parallel_symmetry"]["payload"]
        if evidence["universal_oracle_cli_h48_parallel_symmetry"]
        else {}
    )
    universal_oracle_cli_h48_parallel_symmetry_rows = (
        universal_oracle_cli_h48_parallel_symmetry_payload.get("rows", [])
        if universal_oracle_cli_h48_parallel_symmetry_payload
        else []
    )
    universal_oracle_cli_rotational_lower_bound_payload = (
        evidence["universal_oracle_cli_rotational_lower_bound_certificate"]["payload"]
        if evidence["universal_oracle_cli_rotational_lower_bound_certificate"]
        else {}
    )
    universal_oracle_cli_rotational_lower_bound_rows = (
        universal_oracle_cli_rotational_lower_bound_payload.get("rows", [])
        if universal_oracle_cli_rotational_lower_bound_payload
        else []
    )
    universal_oracle_cli_upper_lower_batch_payload = (
        evidence["universal_oracle_cli_upper_lower_batch"]["payload"]
        if evidence["universal_oracle_cli_upper_lower_batch"]
        else {}
    )
    universal_oracle_cli_upper_lower_batch_rows = (
        universal_oracle_cli_upper_lower_batch_payload.get("rows", [])
        if universal_oracle_cli_upper_lower_batch_payload
        else []
    )
    universal_oracle_cli_late_nissy_core_payload = (
        evidence["universal_oracle_cli_late_nissy_core_direct_fallback"]["payload"]
        if evidence["universal_oracle_cli_late_nissy_core_direct_fallback"]
        else {}
    )
    universal_oracle_cli_late_nissy_core_rows = (
        universal_oracle_cli_late_nissy_core_payload.get("rows", [])
        if universal_oracle_cli_late_nissy_core_payload
        else []
    )
    universal_oracle_cli_live_payload = (
        evidence["universal_oracle_cli_live_no_shortcuts"]["payload"]
        if evidence["universal_oracle_cli_live_no_shortcuts"]
        else {}
    )
    universal_oracle_cli_live_rows = (
        universal_oracle_cli_live_payload.get("rows", [])
        if universal_oracle_cli_live_payload
        else []
    )
    universal_oracle_cli_live_broader_payload = (
        evidence["universal_oracle_cli_live_no_shortcuts_broader"]["payload"]
        if evidence["universal_oracle_cli_live_no_shortcuts_broader"]
        else {}
    )
    universal_oracle_cli_live_broader_rows = (
        universal_oracle_cli_live_broader_payload.get("rows", [])
        if universal_oracle_cli_live_broader_payload
        else []
    )
    universal_oracle_cli_known_distance_payload = (
        evidence["universal_oracle_cli_known_distance_17"]["payload"]
        if evidence["universal_oracle_cli_known_distance_17"]
        else {}
    )
    universal_oracle_cli_known_distance_rows = (
        universal_oracle_cli_known_distance_payload.get("rows", [])
        if universal_oracle_cli_known_distance_payload
        else []
    )
    universal_oracle_cli_known_distance_adaptive_payload = (
        evidence["universal_oracle_cli_known_distance_adaptive"]["payload"]
        if evidence["universal_oracle_cli_known_distance_adaptive"]
        else {}
    )
    universal_oracle_cli_known_distance_adaptive_rows = (
        universal_oracle_cli_known_distance_adaptive_payload.get("rows", [])
        if universal_oracle_cli_known_distance_adaptive_payload
        else []
    )
    universal_oracle_cli_known_distance_19_payload = (
        evidence["universal_oracle_cli_known_distance_19"]["payload"]
        if evidence["universal_oracle_cli_known_distance_19"]
        else {}
    )
    universal_oracle_cli_known_distance_19_rows = (
        universal_oracle_cli_known_distance_19_payload.get("rows", [])
        if universal_oracle_cli_known_distance_19_payload
        else []
    )
    universal_oracle_cli_known_distance_20_payload = (
        evidence["universal_oracle_cli_known_distance_20"]["payload"]
        if evidence["universal_oracle_cli_known_distance_20"]
        else {}
    )
    universal_oracle_cli_known_distance_20_rows = (
        universal_oracle_cli_known_distance_20_payload.get("rows", [])
        if universal_oracle_cli_known_distance_20_payload
        else []
    )
    universal_oracle_cli_known_distance_20_offset1_payload = (
        evidence["universal_oracle_cli_known_distance_20_offset1"]["payload"]
        if evidence["universal_oracle_cli_known_distance_20_offset1"]
        else {}
    )
    universal_oracle_cli_known_distance_20_offset1_rows = (
        universal_oracle_cli_known_distance_20_offset1_payload.get("rows", [])
        if universal_oracle_cli_known_distance_20_offset1_payload
        else []
    )
    universal_oracle_cli_known_distance_20_offset1_trimmed_payload = (
        evidence["universal_oracle_cli_known_distance_20_offset1_trimmed_prepass"]["payload"]
        if evidence["universal_oracle_cli_known_distance_20_offset1_trimmed_prepass"]
        else {}
    )
    universal_oracle_cli_known_distance_20_offset1_trimmed_rows = (
        universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("rows", [])
        if universal_oracle_cli_known_distance_20_offset1_trimmed_payload
        else []
    )
    nissy_benchmark_certificates_payload = (
        evidence["nissy_benchmark_certificates"]["payload"]
        if evidence["nissy_benchmark_certificates"]
        else {}
    )
    nissy_benchmark_certificate_rows = (
        nissy_benchmark_certificates_payload.get("rows", []) if nissy_benchmark_certificates_payload else []
    )
    universal_oracle_cli_known_distance_certificate_payload = (
        evidence["universal_oracle_cli_known_distance_certificate_cache"]["payload"]
        if evidence["universal_oracle_cli_known_distance_certificate_cache"]
        else {}
    )
    universal_oracle_cli_known_distance_certificate_rows = (
        universal_oracle_cli_known_distance_certificate_payload.get("rows", [])
        if universal_oracle_cli_known_distance_certificate_payload
        else []
    )
    known_distance_20_offset2_rubikoptimal_live_payload = (
        evidence["universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live"]["payload"]
        if evidence["universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live"]
        else {}
    )
    known_distance_20_offset2_rubikoptimal_live_rows = (
        known_distance_20_offset2_rubikoptimal_live_payload.get("rows", [])
        if known_distance_20_offset2_rubikoptimal_live_payload
        else []
    )
    known_distance_20_offset2_rubikoptimal_live_sweep_payload = (
        evidence["known_distance_20_offset2_rubikoptimal_live_sweep"]["payload"]
        if evidence["known_distance_20_offset2_rubikoptimal_live_sweep"]
        else {}
    )
    known_distance_20_offset2_rubikoptimal_live_sweep_rows = (
        known_distance_20_offset2_rubikoptimal_live_sweep_payload.get("rows", [])
        if known_distance_20_offset2_rubikoptimal_live_sweep_payload
        else []
    )
    universal_symmetry_payload = (
        evidence["universal_symmetry_oracle"]["payload"]
        if evidence["universal_symmetry_oracle"]
        else {}
    )
    universal_symmetry_rows = universal_symmetry_payload.get("rows", []) if universal_symmetry_payload else []
    inverse_cache_payload = (
        evidence["certificate_cache_inverse_closure"]["payload"]
        if evidence["certificate_cache_inverse_closure"]
        else {}
    )
    inverse_cache_rows = inverse_cache_payload.get("rows", []) if inverse_cache_payload else []
    symmetry_cache_payload = (
        evidence["certificate_cache_symmetry_closure"]["payload"]
        if evidence["certificate_cache_symmetry_closure"]
        else {}
    )
    symmetry_cache_rows = symmetry_cache_payload.get("rows", []) if symmetry_cache_payload else []
    expanded_symmetry_cache_payload = (
        evidence["certificate_cache_expanded_symmetry_closure"]["payload"]
        if evidence["certificate_cache_expanded_symmetry_closure"]
        else {}
    )
    expanded_symmetry_cache_rows = (
        expanded_symmetry_cache_payload.get("rows", []) if expanded_symmetry_cache_payload else []
    )
    learned_certificate_cache_payload = (
        evidence["learned_certificate_cache"]["payload"]
        if evidence["learned_certificate_cache"]
        else {}
    )
    learned_certificate_cache_rows = (
        learned_certificate_cache_payload.get("rows", []) if learned_certificate_cache_payload else []
    )
    h48_generation_probe_payload = (
        evidence["h48_generation_probe"]["payload"] if evidence["h48_generation_probe"] else {}
    )
    h48_proof_volume_candidates_payload = (
        evidence["h48_proof_volume_candidates"]["payload"]
        if evidence["h48_proof_volume_candidates"]
        else {}
    )
    h48_fasttarget_remote_preflight_payload = (
        evidence["h48_fasttarget_remote_preflight_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_preflight_dryrun"]
        else {}
    )
    h48_fasttarget_remote_start_prerequisites_payload = (
        evidence["h48_fasttarget_remote_start_prerequisites_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_start_prerequisites_dryrun"]
        else {}
    )
    h48_fasttarget_remote_status_payload = (
        evidence["h48_fasttarget_remote_status_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_status_dryrun"]
        else {}
    )
    h48_fasttarget_remote_wait_prerequisites_payload = (
        evidence["h48_fasttarget_remote_wait_prerequisites_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_wait_prerequisites_dryrun"]
        else {}
    )
    h48_fasttarget_remote_recover_prerequisite_metadata_payload = (
        evidence["h48_fasttarget_remote_recover_prerequisite_metadata_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_recover_prerequisite_metadata_dryrun"]
        else {}
    )
    h48_fasttarget_remote_wait_prerequisites_install_payload = (
        evidence["h48_fasttarget_remote_wait_prerequisites_install_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_wait_prerequisites_install_dryrun"]
        else {}
    )
    h48_fasttarget_remote_resume_install_payload = (
        evidence["h48_fasttarget_remote_resume_install_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_resume_install_dryrun"]
        else {}
    )
    h48_fasttarget_remote_staged_proof_payload = (
        evidence["h48_fasttarget_remote_staged_proof_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_staged_proof_dryrun"]
        else {}
    )
    h48_fasttarget_remote_detached_staged_proof_payload = (
        evidence["h48_fasttarget_remote_detached_staged_proof_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_detached_staged_proof_dryrun"]
        else {}
    )
    h48_fasttarget_remote_start_full_payload = (
        evidence["h48_fasttarget_remote_start_full_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_start_full_dryrun"]
        else {}
    )
    h48_fasttarget_remote_wait_full_payload = (
        evidence["h48_fasttarget_remote_wait_full_dryrun"]["payload"]
        if evidence["h48_fasttarget_remote_wait_full_dryrun"]
        else {}
    )
    h48_fasttarget_nonaws_detached_staged_proof_payload = (
        evidence["h48_fasttarget_nonaws_detached_staged_proof_dryrun"]["payload"]
        if evidence["h48_fasttarget_nonaws_detached_staged_proof_dryrun"]
        else {}
    )
    h48_fasttarget_nonaws_detached_staged_proof_split_payload = (
        evidence["h48_fasttarget_nonaws_detached_staged_proof_split_dryrun"]["payload"]
        if evidence["h48_fasttarget_nonaws_detached_staged_proof_split_dryrun"]
        else {}
    )
    h48_fasttarget_nonaws_proof_package_payload = (
        evidence["h48_fasttarget_nonaws_proof_package"]["payload"]
        if evidence["h48_fasttarget_nonaws_proof_package"]
        else {}
    )
    h48_fasttarget_nonaws_launch_preparation_payload = (
        evidence["h48_fasttarget_nonaws_launch_preparation"]["payload"]
        if evidence["h48_fasttarget_nonaws_launch_preparation"]
        else {}
    )
    h48_split_bundle_smoke_payload = (
        evidence["h48_split_bundle_smoke"]["payload"]
        if evidence["h48_split_bundle_smoke"]
        else {}
    )
    h48_split_bundle_oracle_grade_smoke_payload = (
        evidence["h48_split_bundle_oracle_grade_smoke"]["payload"]
        if evidence["h48_split_bundle_oracle_grade_smoke"]
        else {}
    )
    h48_fasttarget_runbook_payload = (
        evidence["h48_fasttarget_runbook"]["payload"]
        if evidence["h48_fasttarget_runbook"]
        else {}
    )
    h48_fasttarget_assumed_preflight_payload = (
        evidence["h48_fasttarget_assumed_nonaws_preflight"]["payload"]
        if evidence["h48_fasttarget_assumed_nonaws_preflight"]
        else {}
    )
    h48_fasttarget_aws_provision_payload = (
        evidence["h48_fasttarget_aws_provision_dryrun"]["payload"]
        if evidence["h48_fasttarget_aws_provision_dryrun"]
        else {}
    )
    h48_fasttarget_aws_security_group_payload = (
        evidence["h48_fasttarget_aws_security_group_dryrun"]["payload"]
        if evidence["h48_fasttarget_aws_security_group_dryrun"]
        else {}
    )
    h48_fasttarget_aws_proof_run_payload = (
        evidence["h48_fasttarget_aws_proof_run_dryrun"]["payload"]
        if evidence["h48_fasttarget_aws_proof_run_dryrun"]
        else {}
    )

    source_checks = {
        "nissy_docs_h48_htm_optimal": "An HTM-optimal solver" in sources["nissy_solvers_doc"],
        "nissy_docs_h48_requisites_none": "* Requisites: none." in sources["nissy_solvers_doc"],
        "nissy_docs_h48_moveset_htm": "* Moveset: HTM" in sources["nissy_solvers_doc"],
        "nissy_docs_optimal_alias_h48h7": "alias for `h48h7`" in sources["nissy_solvers_doc"]
        and '{ "optimal", "h48h7" }' in sources["nissy_dispatch"],
        "nissy_api_optimal_parameter_documented": "optimal          - The maximum number of moves above the optimal solution"
        in sources["nissy_api_header"],
        "nissy_api_lower_bound_admissible": "Compute an admissible lower bound" in sources["nissy_api_header"],
        "backend_calls_nissy_solve": "result = nissy_solve(" in sources["h48_backend"],
        "backend_exposes_lower_bound_mode": "--lower-bound" in sources["h48_backend"]
        and "nissy_lowerbound(" in sources["h48_backend"],
        "backend_exposes_lower_bound_batch_mode": "--lower-bound-batch" in sources["h48_backend"]
        and "run_lower_bound_batch" in sources["h48_backend"],
        "backend_uses_normal_htm_flag": "NISSY_NISSFLAG_NORMAL" in sources["h48_backend"],
        "backend_sets_optimal_zero": re.search(
            r"nissy_solve\([^;]+?,\s*1,\s*0,\s*options->threads",
            sources["h48_backend"],
            flags=re.DOTALL,
        )
        is not None,
        "backend_caps_max_depth_at_20": 'if (options->max_depth > 20)' in sources["h48_backend"],
        "backend_has_native_search_deadline_poll": "--search-timeout-ms" in sources["h48_backend"]
        and "poll_deadline_status" in sources["h48_backend"]
        and "NISSY_STATUS_STOP" in sources["h48_backend"],
        "backend_reports_native_search_timeout": "timed_out_by_poll" in sources["h48_backend"]
        and "search_deadline_expired" in sources["h48_backend"],
        "backend_reports_completed_negative_search_as_lower_bound": (
            "completed_negative_search" in sources["h48_backend"]
            and "proved_lower_bound" in sources["h48_backend"]
            and '\\"status\\":\\"lower_bound\\"' in sources["h48_backend"]
        ),
        "python_validates_physical_cube_before_conversion": "cube.verify_physical()" in sources["python_h48_wrapper"],
        "python_converts_direct_cubie_state": "cube_to_nissy_string(cube)" in sources["python_h48_wrapper"],
        "python_independently_verifies_solution": "verify_solution(cube, solution)" in sources["python_h48_wrapper"],
        "python_h48_lower_bound_wrapper_exists": "def compute_h48_native_lower_bound" in sources["python_h48_wrapper"],
        "python_h48_rotational_lower_bound_wrapper_exists": "def compute_h48_native_rotational_lower_bound"
        in sources["python_h48_wrapper"]
        and "--lower-bound-batch" in sources["python_h48_wrapper"]
        and "max(valid_bounds" in sources["python_h48_wrapper"],
        "python_h48_wrapper_passes_native_search_timeout": "search_timeout_seconds" in sources["python_h48_wrapper"]
        and '"--search-timeout-ms"' in sources["python_h48_wrapper"],
        "python_h48_wrapper_preserves_bounded_search_lower_bound": (
            '"lower_bound"' in sources["python_h48_wrapper"]
            and "proved_lower_bound=" in sources["python_h48_wrapper"]
            and '{"exact", "timeout", "lower_bound"}' in sources["python_h48_wrapper"]
        ),
        "python_h48_resident_timeout_keeps_loaded_process": (
            "def _resident_stdout_wait_timeout" in sources["python_h48_wrapper"]
            and "native_search_timeout_seconds" in sources["python_h48_wrapper"]
            and "stdout_wait_timeout_seconds" in sources["python_h48_wrapper"]
            and "return max(request_timeout_seconds, search_timeout_with_grace)"
            in sources["python_h48_wrapper"]
        ),
        "python_h48_batch_recovers_partial_timeout_rows": (
            "def _parse_h48_batch_payload_lines" in sources["python_h48_wrapper"]
            and "partial_timeout_recovered=true" in sources["python_h48_wrapper"]
            and "partial_completed_count" in sources["python_h48_wrapper"]
            and "_subprocess_text(exc.stdout)" in sources["python_h48_wrapper"]
        ),
        "python_h48_resident_batch_recovers_partial_timeout_rows": (
            "def solve_many(self, cubes: Iterable[CubeState]" in sources["python_h48_wrapper"]
            and "completed_result_indexes" in sources["python_h48_wrapper"]
            and "resident_partial_timeout_recovered=true" in sources["python_h48_wrapper"]
            and "partial_completed_count" in sources["python_h48_wrapper"]
            and "replace(" in sources["python_h48_wrapper"]
        ),
        "python_h48_lower_bound_recovers_partial_timeout_rows": (
            "def _parse_h48_lower_bound_rows" in sources["python_h48_wrapper"]
            and '"partial_timeout_recovered" if timed_out else "applied"' in sources["python_h48_wrapper"]
            and "partial_timeout_recovered={'true' if timed_out else 'false'}"
            in sources["python_h48_wrapper"]
            and "_subprocess_text(exc.stdout)" in sources["python_h48_wrapper"]
        ),
        "h48_resident_timeout_survival_evidence_script_uses_session": (
            "H48NativeOracleSession(" in sources["h48_resident_timeout_survival_script"]
            and "process_reused_after_timeout" in sources["h48_resident_timeout_survival_script"]
            and "timed_out_by_poll=True" in sources["h48_resident_timeout_survival_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources[
                "h48_resident_timeout_survival_script"
            ]
        ),
        "h48_batch_partial_timeout_recovery_evidence_script_exists": (
            "solve_h48_native_batch(" in sources["h48_batch_partial_timeout_recovery_script"]
            and "partial_rows_preserved" in sources["h48_batch_partial_timeout_recovery_script"]
            and "TimeoutExpired" in sources["h48_batch_partial_timeout_recovery_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources[
                "h48_batch_partial_timeout_recovery_script"
            ]
        ),
        "h48_lower_bound_partial_timeout_recovery_evidence_script_exists": (
            "compute_h48_native_rotational_lower_bound(" in sources[
                "h48_lower_bound_partial_timeout_recovery_script"
            ]
            and "partial_lower_bound_preserved" in sources[
                "h48_lower_bound_partial_timeout_recovery_script"
            ]
            and "partial_ordering_preserved" in sources[
                "h48_lower_bound_partial_timeout_recovery_script"
            ]
            and "fast_runtime_proven_for_every_possible_state" in sources[
                "h48_lower_bound_partial_timeout_recovery_script"
            ]
        ),
        "python_exact_certificate_cache_revalidates": "verify_solution(cube, solution)"
        in sources["exact_certificate_cache"],
        "python_exact_certificate_cache_accepts_cli_facelet_input": 'row.get("input_kind") == "facelets"'
        in sources["exact_certificate_cache"]
        and 'row.get("input")' in sources["exact_certificate_cache"],
        "python_exact_certificate_cache_accepts_solution_moves_rows": 'row.get("solution_moves")'
        in sources["exact_certificate_cache"]
        and "isinstance(raw_solution, list)" in sources["exact_certificate_cache"],
        "python_exact_certificate_cache_loads_expanded_cli_default": (
            "universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json"
            in sources["exact_certificate_cache"]
            and "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json"
            in sources["exact_certificate_cache"]
        ),
        "python_exact_certificate_cache_loads_nissy_benchmark_certificates": (
            "nissy_benchmark_certificates_seed_2026_thesis_distances16_20.json"
            in sources["exact_certificate_cache"]
        ),
        "nissy_benchmark_certificate_importer_verifies_rows": (
            "verify_solution(cube, solution)" in sources["nissy_benchmark_certificate_importer_script"]
            and "does not match known-distance label" in sources["nissy_benchmark_certificate_importer_script"]
            and "source_sequence_provided_to_solver" in sources["nissy_benchmark_certificate_importer_script"]
        ),
        "python_exact_certificate_cache_derives_inverse_closure": "def _inverse_certificate"
        in sources["exact_certificate_cache"]
        and "inverse_sequence(certificate.solution_moves)" in sources["exact_certificate_cache"]
        and 'derivation="inverse"' in sources["exact_certificate_cache"],
        "python_cube_symmetry_has_24_rotations": "CUBE_ROTATIONS" in sources["cube_symmetry"]
        and "len(CUBE_ROTATIONS) != 24" in sources["cube_symmetry"]
        and "transform_sequence" in sources["cube_symmetry"],
        "python_exact_certificate_cache_derives_symmetry_closure": "def _add_symmetry_closure"
        in sources["exact_certificate_cache"]
        and "CUBE_ROTATIONS" in sources["exact_certificate_cache"]
        and "symmetry_certificate_closure" in sources["exact_certificate_cache"],
        "python_exact_certificate_cache_supports_learned_jsonl": "def remember_result"
        in sources["exact_certificate_cache"]
        and "learned_artifact_path" in sources["exact_certificate_cache"]
        and 'artifact.suffix == ".jsonl"' in sources["exact_certificate_cache"]
        and "json.dumps(row" in sources["exact_certificate_cache"],
        "fast_oracle_api_exists": "class FastOptimalOracle" in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_defaults_to_strongest_trusted_h48": (
            "solver: str = H48_FASTEST_SOLVER" in sources["fast_optimal_oracle_api"]
            and "resolve_h48_solver(" in sources["fast_optimal_oracle_api"]
            and "highest_available_h48_solver(" in sources["h48_table_helpers"]
            and "fallback: str = ORACLE_H48_SOLVER" in sources["h48_table_helpers"]
        ),
        "fast_oracle_api_uses_resident_backend": "H48NativeOracleSession" in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_uses_trusted_table_by_default": "trusted_table: bool = True"
        in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_depth_20_default": "max_depth: int = 20" in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_validates_physical_cube": "validate_cube(cube)" in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_has_solved_state_fast_path": "resident native H48 backend not invoked"
        in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_defaults_to_unbounded_native_search": "timeout_seconds: float | None = None"
        in sources["fast_optimal_oracle_api"]
        and "downgraded to ``timeout`` unless the caller explicitly" in sources["fast_optimal_oracle_api"],
        "fast_oracle_api_passes_timeout_to_resident_h48": "search_timeout_seconds=self.config.timeout_seconds"
        in sources["fast_optimal_oracle_api"],
        "python_h48_resident_solve_many_pipelines_batch": (
            "def solve_many(self, cubes: Iterable[CubeState]" in sources["python_h48_wrapper"]
            and "resident_batch_pipelined=true" in sources["python_h48_wrapper"]
            and '"\\n".join(nissy_cube for _, _, nissy_cube in pending)' in sources["python_h48_wrapper"]
            and "partial_completed_count" in sources["python_h48_wrapper"]
        ),
        "fast_oracle_api_solve_many_uses_resident_batch": (
            "def solve_many(self, cubes: Iterable[CubeState])" in sources["fast_optimal_oracle_api"]
            and "self._session.solve_many" in sources["fast_optimal_oracle_api"]
            and "resident_native_h48_batch_api=true" in sources["fast_optimal_oracle_api"]
        ),
        "fast_oracle_api_threads_are_runtime_configurable": "RUBIK_OPTIMAL_H48_THREADS"
        in sources["runtime_helpers"],
        "fast_oracle_api_threads_support_load_aware_auto": "suggest_thread_count" in sources["runtime_helpers"]
        and '"auto"' in sources["runtime_helpers"],
        "fast_oracle_api_supports_auto_strongest_h48": "resolve_h48_solver" in sources["fast_optimal_oracle_api"]
        and "highest_available_h48_solver" in sources["runtime_helpers"] + sources.get("h48_table_helpers", ""),
        "runtime_helper_terminates_process_group_on_timeout": (
            "def run_process_tree" in sources["runtime_helpers"]
            and "start_new_session=os.name == \"posix\"" in sources["runtime_helpers"]
            and "os.killpg" in sources["runtime_helpers"]
            and "return_code = 124" in sources["runtime_helpers"]
        ),
        "portfolio_oracle_api_exists": "class PortfolioOptimalOracle" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_tries_nissy_before_h48": "solve_nissy_optimal(" in sources["fast_optimal_oracle_api"]
        and "self._h48.solve(cube)" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_has_bounded_nissy_timeout": "nissy_timeout_seconds" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_uses_exact_certificate_cache": "ExactCertificateStore"
        in sources["fast_optimal_oracle_api"]
        and "selected_backend=exact-certificate-cache" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_has_upper_lower_certificate": "selected_backend=upper-lower-certificate"
        in sources["fast_optimal_oracle_api"]
        and "compute_h48_native_lower_bound" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_can_use_rotational_lower_bound_certificate": "compute_h48_native_rotational_lower_bound"
        in sources["fast_optimal_oracle_api"]
        and "lower_bound_symmetry_variants" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_batches_upper_lower_certificates": (
            "def _try_upper_lower_certificates_batch" in sources["fast_optimal_oracle_api"]
            and "compute_h48_native_lower_bound_batch" in sources["fast_optimal_oracle_api"]
            and "compute_h48_native_rotational_lower_bound_batch" in sources["fast_optimal_oracle_api"]
            and "h48_lower_bound_batch_invoked=" in sources["fast_optimal_oracle_api"]
        ),
        "portfolio_oracle_can_use_kociemba_symmetry_upper_bound_certificate": (
            "kociemba_upper_bound_symmetry_variants" in sources["fast_optimal_oracle_api"]
            and "def _shortest_kociemba_symmetry_upper_bound" in sources["fast_optimal_oracle_api"]
            and "kociemba_symmetry_upper_bound=true" in sources["fast_optimal_oracle_api"]
            and "admissible_lower_bound_matches_verified_upper_solution=true"
            in sources["fast_optimal_oracle_api"]
        ),
        "portfolio_oracle_can_use_h48_upper_bound_proof": (
            "h48_upper_bound_proof_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "def _try_h48_upper_bound_proof" in sources["fast_optimal_oracle_api"]
            and "selected_backend=h48-upper-bound-proof" in sources["fast_optimal_oracle_api"]
            and "completed bounded H48 search proved no shorter solution"
            in sources["fast_optimal_oracle_api"]
        ),
        "portfolio_oracle_batches_h48_upper_bound_proofs": (
            "def _try_h48_upper_bound_proofs_batch" in sources["fast_optimal_oracle_api"]
            and "solve_h48_native_resident_batch" in sources["fast_optimal_oracle_api"]
            and "h48_upper_bound_proof_batch_invoked=" in sources["fast_optimal_oracle_api"]
            and "h48_proof_group_size=" in sources["fast_optimal_oracle_api"]
        ),
        "native_korf_upper_bound_proof_supports_single_bound_exhaustive": (
            "UpperBoundProofStrategy::SingleBound" in sources["native_optimal_solver"]
            and "--upper-bound-proof-strategy" in sources["native_optimal_solver"]
            and "solver.upper_bound_proof_exhaustive = true" in sources["native_optimal_solver"]
            and "record_solution(solver" in sources["native_optimal_solver"]
            and "upper_bound_shorter_solution_found" in sources["native_optimal_solver"]
            and "upper_bound_proof_strategy" in sources["python_optimal_native_wrapper"]
            and "--native-upper-bound-proof-strategy" in sources["optimal_3x3_script"]
            and "--upper-bound-proof-strategy" in sources["cli"]
        ),
        "portfolio_oracle_can_use_native_korf_upper_bound_proof": (
            "native_korf_upper_bound_proof_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "def _try_native_korf_upper_bound_proof" in sources["fast_optimal_oracle_api"]
            and "solve_korf_native_optimal" in sources["fast_optimal_oracle_api"]
            and "selected_backend=\"native-korf-upper-bound-proof\"" in sources["fast_optimal_oracle_api"]
            and "completed native Korf/IDA* single-bound proof below verified upper bound"
            in sources["fast_optimal_oracle_api"]
            and "--native-korf-upper-bound-proof-timeout" in sources["cli"]
        ),
        "portfolio_oracle_tries_nissy_core_direct_for_state_input": "try_nissy_core_direct_first"
        in sources["fast_optimal_oracle_api"]
        and "source_sequence is None" in sources["fast_optimal_oracle_api"]
        and "solve_nissy_core_direct_optimal" in sources["fast_optimal_oracle_api"]
        and 'selected_backend="nissy-core-direct"' in sources["fast_optimal_oracle_api"]
        and "nissy_core_direct_invoked=true" in sources["fast_optimal_oracle_api"]
        and "nissy_optimal_batch_invoked=false" in sources["fast_optimal_oracle_api"],
        "portfolio_oracle_batches_nissy_core_direct_for_state_input": (
            "solve_nissy_core_direct_optimal_batch" in sources["fast_optimal_oracle_api"]
            and "def _try_nissy_core_direct_batch" in sources["fast_optimal_oracle_api"]
            and "direct_pending" in sources["fast_optimal_oracle_api"]
            and "nissy_core_direct_batch_invoked=true" in sources["fast_optimal_oracle_api"]
            and "source is None" in sources["fast_optimal_oracle_api"]
        ),
        "portfolio_oracle_persists_learned_certificates": "learned_certificate_artifact"
        in sources["fast_optimal_oracle_api"]
        and "self._certificates.remember_result" in sources["fast_optimal_oracle_api"]
        and "self.remember_result(wrapped" in sources["fast_optimal_oracle_api"],
        "portfolio_evidence_script_uses_package_api": "PortfolioOptimalOracle(config)"
        in sources["portfolio_optimal_oracle_script"],
        "race_oracle_api_exists": "class RaceOptimalOracle" in sources["fast_optimal_oracle_api"],
        "race_oracle_uses_exact_first_verified_policy": "first_verified_exact_solution_wins"
        in sources["fast_optimal_oracle_api"],
        "race_oracle_terminates_slower_backend": "_stop_process" in sources["fast_optimal_oracle_api"]
        and "killed_backends" in sources["fast_optimal_oracle_api"],
        "race_oracle_starts_h48_and_nissy": "_start_h48_candidate" in sources["fast_optimal_oracle_api"]
        and "_start_nissy_candidate" in sources["fast_optimal_oracle_api"],
        "race_oracle_uses_nissy_core_direct_state_candidate": "include_nissy_core_direct"
        in sources["fast_optimal_oracle_api"]
        and "_start_nissy_core_direct_candidate" in sources["fast_optimal_oracle_api"]
        and "_find_nissy_core_shell" in sources["fast_optimal_oracle_api"]
        and "_parse_plain_nissy_core_solution" in sources["fast_optimal_oracle_api"]
        and "race backend=nissy-core-direct" in sources["fast_optimal_oracle_api"]
        and "input_mode=cube_state" in sources["fast_optimal_oracle_api"],
        "race_oracle_cli_exposed": '"race-optimal"' in sources["cli"]
        and "solve_race_optimal(" in sources["cli"],
        "race_evidence_script_uses_package_api": "RaceOptimalOracle(config)"
        in sources["race_optimal_oracle_script"],
        "resident_race_oracle_api_exists": "class ResidentRaceOptimalOracle" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_uses_resident_h48": "FastOptimalOracle(self.config.h48)"
        in sources["fast_optimal_oracle_api"]
        and "resident_h48_process=shared_batch_session" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_uses_threaded_h48": "ThreadPoolExecutor"
        in sources["fast_optimal_oracle_api"]
        and "self._executor.submit(self._h48.solve, cube)" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_stops_losing_backends": "self._h48.close()"
        in sources["fast_optimal_oracle_api"]
        and "stopped_backends" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_cli_exposed": '"resident-race-optimal"' in sources["cli"]
        and "solve_resident_race_optimal(" in sources["cli"],
        "resident_race_evidence_script_uses_package_api": "ResidentRaceOptimalOracle("
        in sources["resident_race_optimal_oracle_script"],
        "resident_race_oracle_can_delay_h48_start": "h48_start_delay_seconds"
        in sources["fast_optimal_oracle_api"]
        and "resident-h48-deferred" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_uses_nissy_core_direct_state_candidate": "include_nissy_core_direct"
        in sources["fast_optimal_oracle_api"]
        and "_start_nissy_core_direct_candidate" in sources["fast_optimal_oracle_api"]
        and "_find_nissy_core_shell" in sources["fast_optimal_oracle_api"]
        and "_parse_plain_nissy_core_solution" in sources["fast_optimal_oracle_api"]
        and "resident race backend=nissy-core-direct" in sources["fast_optimal_oracle_api"]
        and "input_mode=cube_state" in sources["fast_optimal_oracle_api"],
        "resident_race_oracle_uses_resident_nissy_core_direct_state_candidate": (
            "include_nissy_core_python_resident" in sources["fast_optimal_oracle_api"]
            and "NissyCoreDirectPythonSession" in sources["fast_optimal_oracle_api"]
            and "_nissy_core_direct_resident_session().solve" in sources["fast_optimal_oracle_api"]
            and "nissy-core-direct-resident" in sources["fast_optimal_oracle_api"]
            and "table_loaded_once=true" in sources["fast_optimal_oracle_api"]
            and "source_sequence_provided=false" in sources["fast_optimal_oracle_api"]
            and "ThreadPoolExecutor(max_workers=3" in sources["fast_optimal_oracle_api"]
        ),
        "resident_race_oracle_uses_rubikoptimal_candidate": "include_rubikoptimal"
        in sources["fast_optimal_oracle_api"]
        and "rubikoptimal_race_timeout_seconds" in sources["fast_optimal_oracle_api"]
        and "RubikOptimalOracleSession" in sources["fast_optimal_oracle_api"]
        and "_rubikoptimal_resident_session().solve" in sources["fast_optimal_oracle_api"]
        and "rubikoptimal_future" in sources["fast_optimal_oracle_api"]
        and 'selected_backend="rubikoptimal-race"' in sources["fast_optimal_oracle_api"]
        and "resident race backend=rubikoptimal-race" in sources["fast_optimal_oracle_api"]
        and "selected_backend=rubikoptimal_resident" in sources["external_rubikoptimal_solver"]
        and "verify_solution(cube, solution)" in sources["external_rubikoptimal_solver"],
        "rubikoptimal_resident_session_exists": "class RubikOptimalOracleSession"
        in sources["external_rubikoptimal_solver"]
        and "_READY_MARKER" in sources["external_rubikoptimal_solver"]
        and "_readline_with_timeout" in sources["external_rubikoptimal_solver"]
        and "selected_backend=rubikoptimal_resident" in sources["external_rubikoptimal_solver"]
        and "resident_process_reused=" in sources["external_rubikoptimal_solver"],
        "public_oracle_cli_rubikoptimal_stream_uses_resident_session": "--rubikoptimal"
        in sources["cli"]
        and "with RubikOptimalOracleSession(" in sources["cli"]
        and "result = session.solve(" in sources["cli"]
        and "selected_backend=rubikoptimal_resident" in sources["external_rubikoptimal_solver"],
        "universal_oracle_api_exists": "class UniversalOptimalOracle" in sources["fast_optimal_oracle_api"],
        "universal_oracle_uses_resident_rubikoptimal_session": "RubikOptimalOracleSession"
        in sources["fast_optimal_oracle_api"]
        and "_rubikoptimal_resident_session().solve" in sources["fast_optimal_oracle_api"]
        and "self._rubikoptimal_session.close()" in sources["fast_optimal_oracle_api"],
        "universal_oracle_rubikoptimal_prepass_uses_shared_resident_session": (
            "def _solve_rubikoptimal_resident_batch" in sources["fast_optimal_oracle_api"]
            and "self._solve_rubikoptimal_resident_batch(" in sources["fast_optimal_oracle_api"]
            and "shared_session = self._rubikoptimal_resident_session()"
            in sources["fast_optimal_oracle_api"]
            and 'note_flag="universal_prepass_uses_shared_rubikoptimal_session"'
            in sources["fast_optimal_oracle_api"]
            and 'budget_note_prefix="prepass"' in sources["fast_optimal_oracle_api"]
            and "{budget_note_prefix}_row_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "{budget_note_prefix}_global_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and 'selected_backend="rubikoptimal-prepass"' in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_rubikoptimal_fallback_uses_shared_resident_session": (
            "shared_session = self._rubikoptimal_resident_session()"
            in sources["fast_optimal_oracle_api"]
            and "universal_fallback_uses_shared_rubikoptimal_session=true"
            in sources["fast_optimal_oracle_api"]
            and "fallback_row_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "rubikoptimal_resident_start_count" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_uses_certificate_before_live_race": "_solve_from_certificate_cache"
        in sources["fast_optimal_oracle_api"]
        and "selected_backend=\"exact-certificate-cache\"" in sources["fast_optimal_oracle_api"],
        "universal_oracle_uses_upper_lower_before_live_race": "_try_upper_lower_certificate"
        in sources["fast_optimal_oracle_api"]
        and "selected_backend=\"upper-lower-certificate\"" in sources["fast_optimal_oracle_api"],
        "universal_oracle_solve_many_batches_upper_lower_certificates": (
            "universal_solve_many_upper_lower_batch=true" in sources["fast_optimal_oracle_api"]
            and "upper_lower_results = self._certifying_portfolio._try_upper_lower_certificates_batch"
            in sources["fast_optimal_oracle_api"]
            and "universal_upper_lower_batch_wall_seconds=" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_falls_back_to_resident_race": "ResidentRaceOptimalOracle"
        in sources["fast_optimal_oracle_api"]
        and 'selected_backend = "resident-race"' in sources["fast_optimal_oracle_api"]
        and "_resident_race.solve" in sources["fast_optimal_oracle_api"],
        "universal_oracle_batches_live_corpus": "_batch_portfolio.solve_many"
        in sources["fast_optimal_oracle_api"]
        and "selected_backend=\"portfolio-batch\"" in sources["fast_optimal_oracle_api"],
        "universal_oracle_batches_state_input_through_resident_h48": (
            "prefer_resident_h48_batch_for_state_input" in sources["fast_optimal_oracle_api"]
            and 'selected_backend = "resident-h48-batch"' in sources["fast_optimal_oracle_api"]
            and "h48_batch_oracle.solve_many" in sources["fast_optimal_oracle_api"]
            and "resident_h48_batch_timeout_seconds" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_uses_portfolio_prepass_before_resident_h48_batch": (
            "try_portfolio_batch_before_resident_h48_batch" in sources["fast_optimal_oracle_api"]
            and "portfolio_prepass_before_resident_h48_batch=true" in sources["fast_optimal_oracle_api"]
            and "portfolio-before-resident-h48-batch" in sources["fast_optimal_oracle_api"]
            and "resident-h48-batch-after-portfolio-prepass" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_has_bounded_nissy_only_portfolio_prepass": (
            "portfolio_prepass_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "try_h48_fallback=False" in sources["fast_optimal_oracle_api"]
            and "h48_fallback_disabled=true" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_falls_back_after_resident_h48_batch_timeout": (
            "fallback_pending" in sources["fast_optimal_oracle_api"]
            and "portfolio-after-resident-h48-fallback" in sources["fast_optimal_oracle_api"]
            and "resident_h48_batch_initial_status" in sources["fast_optimal_oracle_api"]
            and "resident_h48_batch_fallback=true" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_late_fallback_uses_nissy_core_direct_state_input": (
            "portfolio_fallback_nissy_core_direct_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "try_nissy_core_direct_first=(" in sources["fast_optimal_oracle_api"]
            and "nissy_core_direct_late_fallback" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_exposes_rubikoptimal_race": (
            "rubikoptimal_race_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "include_rubikoptimal=True" in sources["fast_optimal_oracle_api"]
            and 'selected_backend = "rubikoptimal-race"' in sources["fast_optimal_oracle_api"]
            and "rubikoptimal_race" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_uses_resident_race_prepass": (
            "resident_race_prepass_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "_try_resident_race_prepass" in sources["fast_optimal_oracle_api"]
            and "universal_resident_race_prepass=true" in sources["fast_optimal_oracle_api"]
            and 'selected_backend="resident-race-prepass"' in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_uses_rubikoptimal_symmetry_batch": (
            "rubikoptimal_symmetry_variants" in sources["fast_optimal_oracle_api"]
            and "_try_rubikoptimal_symmetry_batch" in sources["fast_optimal_oracle_api"]
            and "_solve_rubikoptimal_resident_batch" in sources["fast_optimal_oracle_api"]
            and "rotation.inverse_transform_sequence" in sources["fast_optimal_oracle_api"]
            and "rubikoptimal-symmetry-batch" in sources["fast_optimal_oracle_api"]
            and "rotated_exact_solution_mapped_back_and_verified" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_rubikoptimal_symmetry_batch_uses_shared_resident_session": (
            "def _solve_rubikoptimal_resident_batch" in sources["fast_optimal_oracle_api"]
            and 'note_flag="universal_symmetry_batch_uses_shared_rubikoptimal_session"'
            in sources["fast_optimal_oracle_api"]
            and 'budget_note_prefix="symmetry"' in sources["fast_optimal_oracle_api"]
            and "{budget_note_prefix}_row_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and "{budget_note_prefix}_global_timeout_seconds" in sources["fast_optimal_oracle_api"]
            and 'selected_backend="rubikoptimal-symmetry-batch"'
            in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_rubikoptimal_symmetry_includes_identity_without_prepass": (
            "def _rubikoptimal_symmetry_include_identity" in sources["fast_optimal_oracle_api"]
            and "return not self._rubikoptimal_prepass_enabled()" in sources["fast_optimal_oracle_api"]
            and "include_identity = self._rubikoptimal_symmetry_include_identity()"
            in sources["fast_optimal_oracle_api"]
            and "identity_rotation_included={include_identity}" in sources["fast_optimal_oracle_api"]
        ),
        "rubikoptimal_external_supports_rotational_race": (
            "def solve_rubikoptimal_external_rotational_race" in sources["external_rubikoptimal_solver"]
            and "ThreadPoolExecutor" in sources["external_rubikoptimal_solver"]
            and "max_concurrency" in sources["external_rubikoptimal_solver"]
            and "first_rotated_exact_solution_mapped_back_and_verified"
            in sources["external_rubikoptimal_solver"]
        ),
        "rubikoptimal_rotational_race_uses_resident_worker_pool": (
            "resident_worker_pool=true" in sources["external_rubikoptimal_solver"]
            and "claim_next_rotation" in sources["external_rubikoptimal_solver"]
            and "resident_worker_count" in sources["external_rubikoptimal_solver"]
            and "resident_session_count" in sources["external_rubikoptimal_solver"]
            and "close_losing_sessions" in sources["external_rubikoptimal_solver"]
        ),
        "rubikoptimal_rotational_race_uses_global_wall_timeout": (
            "global_timeout_seconds = max(0.0, float(timeout_seconds))"
            in sources["external_rubikoptimal_solver"]
            and "deadline = begin + global_timeout_seconds" in sources["external_rubikoptimal_solver"]
            and "pending_rotations_not_started" in sources["external_rubikoptimal_solver"]
            and "row_timeouts" in sources["external_rubikoptimal_solver"]
        ),
        "rubikoptimal_resident_timeout_keeps_loaded_process": (
            "signal.setitimer" in sources["external_rubikoptimal_solver"]
            and "resident_timeout_without_process_stop=true" in sources["external_rubikoptimal_solver"]
            and "resident_process_alive=" in sources["external_rubikoptimal_solver"]
            and "_resident_child_timeout_seconds" in sources["external_rubikoptimal_solver"]
        ),
        "rubikoptimal_batch_uses_resident_session": (
            "batch_uses_resident_session=true" in sources["external_rubikoptimal_solver"]
            and "with RubikOptimalOracleSession(" in sources["external_rubikoptimal_solver"]
            and "batch_row_timeout_seconds" in sources["external_rubikoptimal_solver"]
            and "global resident batch budget" in sources["external_rubikoptimal_solver"]
        ),
        "universal_oracle_uses_rubikoptimal_symmetry_race": (
            "rubikoptimal_symmetry_max_concurrency" in sources["fast_optimal_oracle_api"]
            and "solve_rubikoptimal_external_rotational_race" in sources["fast_optimal_oracle_api"]
            and "rubikoptimal-symmetry-race" in sources["fast_optimal_oracle_api"]
            and "universal_rubikoptimal_symmetry_race=true" in sources["fast_optimal_oracle_api"]
        ),
        "universal_rubikoptimal_symmetry_uses_global_wall_timeout": (
            "def _rubikoptimal_symmetry_global_timeout" in sources["fast_optimal_oracle_api"]
            and "timeout_seconds=self._rubikoptimal_symmetry_global_timeout()"
            in sources["fast_optimal_oracle_api"]
            and "total_timeout_seconds=self._rubikoptimal_symmetry_global_timeout()"
            in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_uses_live_nissy_symmetry_batch": "nissy_symmetry_variants"
        in sources["fast_optimal_oracle_api"]
        and "CUBE_ROTATIONS" in sources["fast_optimal_oracle_api"]
        and "inverse_transform_sequence" in sources["fast_optimal_oracle_api"]
        and "_start_nissy_symmetry_candidate" in sources["fast_optimal_oracle_api"]
        and "h48_competes_concurrently=true" in sources["fast_optimal_oracle_api"],
        "resident_race_nissy_symmetry_orders_by_h48_lower_bound": (
            "symmetry_order_by_h48_lower_bound" in sources["fast_optimal_oracle_api"]
            and "_order_nissy_symmetry_rotations_by_h48_lower_bound"
            in sources["fast_optimal_oracle_api"]
            and "resident_race_nissy_symmetry_h48_lower_bound_rotation_order"
            in sources["fast_optimal_oracle_api"]
            and "order_h48_rotations_by_lower_bound(" in sources["fast_optimal_oracle_api"]
        ),
        "public_oracle_cli_exposes_shared_symmetry_ordering_alias": (
            "--symmetry-order-by-h48-lower-bound" in sources["cli"]
            and "--symmetry-lower-bound-order-timeout" in sources["cli"]
            and "symmetry_order_by_h48_lower_bound=" in sources["cli"]
        ),
        "public_oracle_cli_exposes_kociemba_symmetry_upper_bound": (
            "--kociemba-upper-bound-symmetry-variants" in sources["cli"]
            and "kociemba_upper_bound_symmetry_variants=" in sources["cli"]
        ),
        "public_oracle_cli_exposes_h48_upper_bound_proof": (
            "--h48-upper-bound-proof-timeout" in sources["cli"]
            and "--h48-upper-bound-proof-max-gap" in sources["cli"]
            and "h48_upper_bound_proof_timeout_seconds=" in sources["cli"]
        ),
        "public_oracle_cli_exposes_native_korf_upper_bound_proof": (
            "--native-korf-upper-bound-proof-timeout" in sources["cli"]
            and "--native-korf-upper-bound-proof-max-gap" in sources["cli"]
            and "native_korf_upper_bound_proof_timeout_seconds=" in sources["cli"]
        ),
        "h48_native_supports_rotated_direct_state_variants": "def solve_rotated_variants"
        in sources["python_h48_wrapper"]
        and "rotated_exact_solution_mapped_back_and_verified" in sources["python_h48_wrapper"]
        and "rotation.transform_cube(cube)" in sources["python_h48_wrapper"]
        and "rotation.inverse_transform_sequence" in sources["python_h48_wrapper"],
        "python_h48_resident_symmetry_accepts_explicit_rotation_order": (
            "rotations: Iterable[CubeRotation] | None = None" in sources["python_h48_wrapper"]
            and "rotation_order_note:" in sources["python_h48_wrapper"]
            and "rotation_order={[candidate.name for candidate in rotations]}" in sources["python_h48_wrapper"]
        ),
        "h48_native_symmetry_rotations_cover_cube_axes": "_H48_SYMMETRY_AXIS_GROUP_ORDER"
        in sources["python_h48_wrapper"]
        and "def _h48_symmetry_axis_key" in sources["python_h48_wrapper"]
        and 'rotation.face_map["U"]' in sources["python_h48_wrapper"]
        and '"FB", "RL", "UD"' in sources["python_h48_wrapper"],
        "universal_oracle_uses_resident_h48_symmetry_batch": "resident_h48_symmetry_variants"
        in sources["fast_optimal_oracle_api"]
        and "_try_resident_h48_symmetry_batch" in sources["fast_optimal_oracle_api"]
        and "solve_rotated_variants" in sources["fast_optimal_oracle_api"]
        and 'selected_backend="resident-h48-symmetry-batch"' in sources["fast_optimal_oracle_api"],
        "universal_resident_h48_symmetry_orders_by_h48_lower_bound": (
            "_order_symmetry_rotations_by_h48_lower_bound" in sources["fast_optimal_oracle_api"]
            and 'context="resident_h48_symmetry"' in sources["fast_optimal_oracle_api"]
            and "rotations=rotations" in sources["fast_optimal_oracle_api"]
            and "rotation_order_note=rotation_order_note" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_solve_many_uses_resident_h48_symmetry_batch": "def solve_many"
        in sources["fast_optimal_oracle_api"]
        and "h48_symmetry_result = self._try_resident_h48_symmetry_batch(cube)"
        in sources["fast_optimal_oracle_api"]
        and 'selected_backend="resident-h48-symmetry-batch"'
        in sources["fast_optimal_oracle_api"],
        "universal_oracle_cli_exposed": '"universal-optimal"' in sources["cli"]
        and "solve_universal_optimal(" in sources["cli"],
        "cli_high_level_exact_solvers_prefer_oracle_h48": "def _select_h48_solver"
        in sources["cli"]
        and "prefer_oracle" in sources["cli"]
        and "return ORACLE_H48_SOLVER" in sources["cli"]
        and 'args.solver == "universal-optimal"' in sources["cli"],
        "cli_high_level_exact_solvers_use_trusted_h48_by_default": "def _use_trusted_h48_table"
        in sources["cli"]
        and "args.h48_trusted_table or prefer_oracle" in sources["cli"]
        and "trusted_table=_use_trusted_h48_table(args, prefer_oracle=True)" in sources["cli"],
        "universal_evidence_script_uses_package_api": "UniversalOptimalOracle(config)"
        in sources["universal_optimal_oracle_script"],
        "universal_evidence_script_supports_state_input_only": "--state-input-only"
        in sources["universal_optimal_oracle_script"]
        and "source_sequence = None if args.state_input_only" in sources["universal_optimal_oracle_script"]
        and "direct_nissy_core_used" in sources["universal_optimal_oracle_script"],
        "universal_evidence_script_supports_h48_symmetry_prepass": "--h48-symmetry-variants"
        in sources["universal_optimal_oracle_script"]
        and "resident_h48_symmetry_variants" in sources["universal_optimal_oracle_script"]
        and "resident_h48_symmetry_used" in sources["universal_optimal_oracle_script"],
        "universal_evidence_script_supports_rubikoptimal_race": "--rubikoptimal-race-timeout"
        in sources["universal_optimal_oracle_script"]
        and "rubikoptimal_race_timeout_seconds" in sources["universal_optimal_oracle_script"]
        and "rubikoptimal-race" in sources["universal_optimal_oracle_script"],
        "rubikoptimal_resident_evidence_script_uses_session": "RubikOptimalOracleSession"
        in sources["rubikoptimal_resident_oracle_script"]
        and "resident_start_count" in sources["rubikoptimal_resident_oracle_script"]
        and "resident_process_reused_rows" in sources["rubikoptimal_resident_oracle_script"],
        "rubikoptimal_stream_evidence_script_uses_public_cli": "rubik-optimal oracle --stream --rubikoptimal"
        in sources["rubikoptimal_oracle_stream_script"]
        and '"rubik_optimal.cli"' in sources["rubikoptimal_oracle_stream_script"]
        and '"--stream"' in sources["rubikoptimal_oracle_stream_script"]
        and '"--rubikoptimal"' in sources["rubikoptimal_oracle_stream_script"]
        and "source_sequence_provided_to_solver" in sources["rubikoptimal_oracle_stream_script"]
        and "resident_process_reused" in sources["rubikoptimal_oracle_stream_script"],
        "universal_oracle_cli_evidence_supports_h48_symmetry_prepass": "--h48-symmetry-variants"
        in sources["universal_oracle_cli_script"]
        and "resident_h48_symmetry_rows" in sources["universal_oracle_cli_script"]
        and "resident-h48-symmetry-batch" in sources["universal_oracle_cli_script"],
        "h48_native_supports_parallel_rotational_race": "def solve_h48_native_rotational_race"
        in sources["python_h48_wrapper"]
        and "first_rotated_exact_solution_mapped_back_and_verified" in sources["python_h48_wrapper"]
        and "_stop_h48_process" in sources["python_h48_wrapper"],
        "h48_parallel_rotational_race_uses_global_wall_timeout": (
            "global_timeout_seconds" in sources["python_h48_wrapper"]
            and "can_start_more()" in sources["python_h48_wrapper"]
            and "total_timeout_seconds = None if timeout_seconds is None or timeout_seconds <= 0 else timeout_seconds"
            in sources["python_h48_wrapper"]
        ),
        "h48_parallel_rotational_race_clips_native_search_timeout_to_remaining_budget": (
            "native_search_timeout_clipped_to_remaining_global_budget=true"
            in sources["python_h48_wrapper"]
            and "per_candidate_native_search_timeout_ms" in sources["python_h48_wrapper"]
            and "remaining_global_seconds = max(0.001, deadline - time.perf_counter())"
            in sources["python_h48_wrapper"]
            and "min(native_timeout_seconds, remaining_global_seconds)"
            in sources["python_h48_wrapper"]
        ),
        "h48_resident_rotational_batch_uses_global_wall_timeout": (
            "def solve_rotated_variants" in sources["python_h48_wrapper"]
            and "global_timeout_seconds = configured_timeout_seconds" in sources["python_h48_wrapper"]
            and "pending_rotations_not_started" in sources["python_h48_wrapper"]
            and "row_timeouts" in sources["python_h48_wrapper"]
        ),
        "universal_oracle_cli_evidence_supports_parallel_h48_symmetry_race": (
            "--h48-parallel-symmetry-variants" in sources["universal_oracle_cli_script"]
            and "parallel_h48_symmetry_rows" in sources["universal_oracle_cli_script"]
            and "parallel-h48-symmetry-race" in sources["universal_oracle_cli_script"]
        ),
        "universal_nissy_core_direct_symmetry_uses_global_wall_timeout": (
            "def _try_nissy_core_direct_rotational_race" in sources["fast_optimal_oracle_api"]
            and "global_timeout_seconds = per_rotation_timeout" in sources["fast_optimal_oracle_api"]
            and "global_timeout_expired" in sources["fast_optimal_oracle_api"]
            and "pending_rotations_not_started" in sources["fast_optimal_oracle_api"]
        ),
        "universal_oracle_cli_budgets_symmetry_races_as_global_phases": (
            "direct_symmetry_budget = (" in sources["universal_oracle_cli_script"]
            and "direct_symmetry_timeout * cases" in sources["universal_oracle_cli_script"]
            and "nissy_symmetry_budget = (" in sources["universal_oracle_cli_script"]
            and "nissy_symmetry_timeout * cases" in sources["universal_oracle_cli_script"]
            and "parallel_h48_symmetry_budget = (" in sources["universal_oracle_cli_script"]
            and "parallel_h48_symmetry_timeout * cases" in sources["universal_oracle_cli_script"]
            and "symmetry_timeout * cases if max(0, int(h48_symmetry_variants)) > 0 else 0.0"
            in sources["universal_oracle_cli_script"]
            and "rubikoptimal_symmetry_timeout * cases if rubikoptimal_rotation_count > 0 else 0.0"
            in sources["universal_oracle_cli_script"]
        ),
        "universal_oracle_cli_budgets_shared_symmetry_ordering": (
            "ordered_symmetry_phase_count = 0" in sources["universal_oracle_cli_script"]
            and "symmetry_order_budget = (" in sources["universal_oracle_cli_script"]
            and "symmetry_order_by_h48_lower_bound" in sources["universal_oracle_cli_script"]
            and "symmetry_lower_bound_order_timeout_seconds" in sources["universal_oracle_cli_script"]
            and "symmetry_order_by_h48_lower_bound=args.h48_parallel_symmetry_order_by_lower_bound"
            in sources["universal_oracle_cli_script"]
        ),
        "known_distance_sweep_budgets_shared_symmetry_ordering": (
            "def _ordered_symmetry_phase_count" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "symmetry_order_budget = (" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "parallel_h48_symmetry_lower_bound_order_timeout_seconds"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "_lborder" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "nissy_symmetry_variants=nissy_symmetry_variants"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
        ),
        "universal_oracle_cli_evidence_supports_rubikoptimal_symmetry_batch": (
            "--universal-rubikoptimal-symmetry-variants" in sources["universal_oracle_cli_script"]
            and "rubikoptimal_symmetry_rows" in sources["universal_oracle_cli_script"]
            and "rubikoptimal-symmetry-batch" in sources["universal_oracle_cli_script"]
            and "rubikoptimal_symmetry_budget" in sources["universal_oracle_cli_script"]
        ),
        "universal_oracle_cli_evidence_supports_rubikoptimal_symmetry_race": (
            "--universal-rubikoptimal-symmetry-max-concurrency"
            in sources["universal_oracle_cli_script"]
            and "rubikoptimal_symmetry_race_rows" in sources["universal_oracle_cli_script"]
            and "rubikoptimal-symmetry-race" in sources["universal_oracle_cli_script"]
            and "rubikoptimal_symmetry_timeout * cases if rubikoptimal_rotation_count > 0 else 0.0"
            in sources["universal_oracle_cli_script"]
        ),
        "universal_oracle_cli_evidence_supports_resident_race_prepass": (
            "--universal-resident-race-prepass-timeout" in sources["universal_oracle_cli_script"]
            and "resident_race_prepass_budget" in sources["universal_oracle_cli_script"]
            and "resident_race_prepass_rows" in sources["universal_oracle_cli_script"]
            and "resident-race-prepass" in sources["universal_oracle_cli_script"]
        ),
        "universal_oracle_cli_evidence_exposes_shared_symmetry_ordering_alias": (
            "--symmetry-order-by-h48-lower-bound" in sources["universal_oracle_cli_script"]
            and "--symmetry-lower-bound-order-timeout" in sources["universal_oracle_cli_script"]
            and "symmetry_order_by_h48_lower_bound" in sources["universal_oracle_cli_script"]
        ),
        "universal_batch_evidence_script_uses_solve_many": "UniversalOptimalOracle(config)"
        in sources["universal_batch_oracle_script"]
        and "oracle.solve_many" in sources["universal_batch_oracle_script"],
        "universal_batch_evidence_script_supports_resident_h48_batch": "--resident-h48-batch"
        in sources["universal_batch_oracle_script"]
        and "prefer_resident_h48_batch_for_state_input=args.resident_h48_batch"
        in sources["universal_batch_oracle_script"]
        and "all_universal_resident_h48_batch" in sources["universal_batch_oracle_script"],
        "public_oracle_cli_exposes_universal_resident_batch": "--universal"
        in sources["cli"]
        and "UniversalOptimalOracle(config)" in sources["cli"]
        and "prefer_resident_h48_batch_for_state_input=(" in sources["cli"]
        and "args.universal_rubikoptimal_race_timeout < 0" in sources["cli"]
        and "resident_h48_batch_timeout_seconds=resident_h48_batch_timeout" in sources["cli"]
        and "try_portfolio_batch_before_resident_h48_batch=" in sources["cli"]
        and "universal_resident_h48_batch" in sources["cli"],
        "public_oracle_cli_exposes_rubikoptimal_race": "--universal-rubikoptimal-race-timeout"
        in sources["cli"]
        and "rubikoptimal_race_timeout_seconds=" in sources["cli"]
        and '"universal_optimal_oracle"' in sources["cli"],
        "public_oracle_cli_exposes_resident_race_prepass": (
            "--universal-resident-race-prepass-timeout" in sources["cli"]
            and "resident_race_prepass_timeout_seconds=" in sources["cli"]
            and "resident_race_prepass_timeout_seconds" in sources["cli"]
        ),
        "public_oracle_cli_exposes_rubikoptimal_symmetry_batch": (
            "--universal-rubikoptimal-symmetry-variants" in sources["cli"]
            and "--universal-rubikoptimal-symmetry-timeout" in sources["cli"]
            and "rubikoptimal_symmetry_variants=" in sources["cli"]
            and "rubikoptimal_symmetry_timeout_seconds=" in sources["cli"]
        ),
        "public_oracle_cli_exposes_rubikoptimal_symmetry_race": (
            "--universal-rubikoptimal-symmetry-max-concurrency" in sources["cli"]
            and "rubikoptimal_symmetry_max_concurrency=" in sources["cli"]
        ),
        "public_oracle_cli_exposes_h48_symmetry_prepass": "--h48-symmetry-variants"
        in sources["cli"]
        and "--h48-symmetry-timeout" in sources["cli"]
        and "resident_h48_symmetry_variants=max(0, args.h48_symmetry_variants)" in sources["cli"],
        "public_oracle_cli_exposes_parallel_h48_symmetry_race": (
            "--h48-parallel-symmetry-variants" in sources["cli"]
            and "--h48-parallel-symmetry-timeout" in sources["cli"]
            and "parallel_h48_symmetry_variants=max(0, args.h48_parallel_symmetry_variants)" in sources["cli"]
        ),
        "public_oracle_cli_exposes_bounded_portfolio_prepass": (
            "--universal-portfolio-prepass-timeout" in sources["cli"]
            and "portfolio_prepass_timeout_seconds=args.universal_portfolio_prepass_timeout"
            in sources["cli"]
        ),
        "public_oracle_cli_can_disable_universal_shortcuts": "--no-universal-certificate-cache"
        in sources["cli"]
        and "--no-universal-upper-lower-certificate" in sources["cli"]
        and "try_certificate_cache=not args.no_universal_certificate_cache" in sources["cli"]
        and "try_upper_lower_certificate=not args.no_universal_upper_lower_certificate" in sources["cli"],
        "public_oracle_cli_exposes_learned_certificate_log": "--learned-certificate-log"
        in sources["cli"]
        and "learned_certificate_artifact=args.learned_certificate_log" in sources["cli"],
        "universal_oracle_cli_evidence_script_uses_public_cli": "--universal"
        in sources["universal_oracle_cli_script"]
        and '"rubik_optimal.cli"' in sources["universal_oracle_cli_script"]
        and "all_universal_optimized_cli" in sources["universal_oracle_cli_script"]
        and "resident_h48_batch_rows" in sources["universal_oracle_cli_script"]
        and "resident_h48_fallback_rows" in sources["universal_oracle_cli_script"]
        and "portfolio_prepass_rows" in sources["universal_oracle_cli_script"]
        and "--include-hard" in sources["universal_oracle_cli_script"]
        and "all_expected_distances_match" in sources["universal_oracle_cli_script"],
        "universal_oracle_cli_evidence_can_disable_shortcuts": "--no-certificate-cache"
        in sources["universal_oracle_cli_script"]
        and "--no-upper-lower-certificate" in sources["universal_oracle_cli_script"]
        and "--no-universal-certificate-cache" in sources["universal_oracle_cli_script"]
        and "live_solver_shortcuts_disabled" in sources["universal_oracle_cli_script"],
        "universal_oracle_cli_evidence_supports_known_distance_benchmark_corpus": "--benchmark-distance"
        in sources["universal_oracle_cli_script"]
        and "_nissy_benchmark_cases" in sources["universal_oracle_cli_script"]
        and "nissy_core_benchmark_known_distance" in sources["universal_oracle_cli_script"]
        and "all_expected_distances_match" in sources["universal_oracle_cli_script"],
        "universal_oracle_cli_evidence_budgets_adaptive_hard_phases": "_adaptive_command_timeout_seconds"
        in sources["universal_oracle_cli_script"]
        and "portfolio_budget" in sources["universal_oracle_cli_script"]
        and "symmetry_budget" in sources["universal_oracle_cli_script"]
        and "resident_budget" in sources["universal_oracle_cli_script"]
        and "outer_command_timed_out" in sources["universal_oracle_cli_script"],
        "universal_oracle_cli_exposes_rotational_lower_bound_certificate": "--h48-lower-bound-symmetry-variants"
        in sources["cli"]
        and "--h48-lower-bound-symmetry-variants" in sources["universal_oracle_cli_script"],
        "universal_oracle_cli_exposes_late_nissy_core_direct_fallback": (
            "--universal-fallback-nissy-core-direct-timeout" in sources["cli"]
            and "--universal-fallback-nissy-core-direct-timeout"
            in sources["universal_oracle_cli_script"]
            and "late_nissy_core_direct_fallback_rows" in sources["universal_oracle_cli_script"]
        ),
        "known_distance_sweep_exposes_rubikoptimal_phases": (
            "--rubikoptimal-prepass-timeout" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--rubikoptimal-symmetry-variants" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--rubikoptimal-symmetry-timeout" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--rubikoptimal-symmetry-max-concurrency"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--rubikoptimal-race-timeout" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--rubikoptimal-fallback-timeout" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-rubikoptimal-prepass-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-rubikoptimal-symmetry-variants"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-rubikoptimal-symmetry-max-concurrency"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-rubikoptimal-race-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-rubikoptimal-fallback-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "rubikoptimal_prepass_timeout_seconds" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "rubikoptimal_symmetry_variants" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "rubikoptimal_symmetry_max_concurrency"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "rubikoptimal_fallback_timeout_seconds" in sources["known_distance20_trimmed_prepass_sweep_script"]
        ),
        "known_distance_sweep_exposes_resident_race_prepass": (
            "--resident-race-prepass-timeout" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--universal-resident-race-prepass-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "resident_race_prepass_timeout_seconds"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "resident_race_prepass_budget" in sources["known_distance20_trimmed_prepass_sweep_script"]
        ),
        "known_distance_sweep_exposes_shared_symmetry_ordering_alias": (
            "--symmetry-order-by-h48-lower-bound"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--symmetry-lower-bound-order-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "parallel_h48_symmetry_order_by_lower_bound"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
        ),
        "known_distance_sweep_exposes_h48_upper_bound_proof": (
            "--h48-upper-bound-proof-timeout"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "--h48-upper-bound-proof-max-gap"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "h48_upper_bound_proof_budget" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "h48_upper_bound_proof_timeout_seconds="
            in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "h48_upper_bound_proof_max_gap=" in sources["known_distance20_trimmed_prepass_sweep_script"]
            and "command.append(\"--no-upper-lower-certificate\")"
            in sources["known_distance20_trimmed_prepass_sweep_script"]
        ),
        "cloud_hardtail_campaign_plans_fast_every_state_workloads": (
            "build_cloud_hardtail_plan" in sources["cloud_hardtail_campaign_script"]
            and "public_known_distance_hardtail_sweep" in sources["cloud_hardtail_campaign_script"]
            and "public_known_distance_hardtail_batch" in sources["cloud_hardtail_campaign_script"]
            and "--h48-upper-bound-proof-timeout" in sources["cloud_hardtail_campaign_script"]
            and "scripts/run_h48_stronger_table_campaign.py" in sources["cloud_hardtail_campaign_script"]
            and "rubikoptimal_superflip_hardcase" in sources["cloud_hardtail_campaign_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources["cloud_hardtail_campaign_script"]
        ),
        "cloud_hardtail_campaign_has_workload_runner_and_evaluator": (
            "def run_workload" in sources["cloud_hardtail_workload_runner_script"]
            and "cloud_hardtail_workload_" in sources["cloud_hardtail_workload_runner_script"]
            and "expected_artifacts_found" in sources["cloud_hardtail_workload_runner_script"]
            and "validate_trusted_h48_table_checksum" in sources["cloud_hardtail_workload_runner_script"]
            and "full_checksum_valid" in sources["cloud_hardtail_workload_runner_script"]
            and "blocked_by_untrusted_h48_dependencies" in sources["cloud_hardtail_workload_runner_script"]
            and "run_process_tree(" in sources["cloud_hardtail_workload_runner_script"]
            and "terminated_process_group" in sources["cloud_hardtail_workload_runner_script"]
            and "def run_campaign" in sources["cloud_hardtail_campaign_runner_script"]
            and "run_workload(" in sources["cloud_hardtail_campaign_runner_script"]
            and "evaluate_campaign(" in sources["cloud_hardtail_campaign_runner_script"]
            and "cloud_hardtail_campaign_run_" in sources["cloud_hardtail_campaign_runner_script"]
            and "def evaluate_campaign" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "all_required_workloads_passed" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "cloud_runtime_evidence_passed" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["cloud_hardtail_campaign_evaluator_script"]
        ),
        "cloud_hardtail_campaign_rejects_stale_workload_results": (
            "def fingerprint_json" in sources["cloud_hardtail_workload_runner_script"]
            and "sha256-canonical-json-v1" in sources["cloud_hardtail_workload_runner_script"]
            and "plan_fingerprint" in sources["cloud_hardtail_workload_runner_script"]
            and "workload_fingerprint" in sources["cloud_hardtail_workload_runner_script"]
            and "validate_workload_result_fingerprints" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "workload result does not match the current plan/workload fingerprint"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "ignored_resume_fingerprint_validation"
            in sources["cloud_hardtail_campaign_runner_script"]
        ),
        "cloud_hardtail_campaign_reuses_valid_passed_workload_evidence": (
            "def select_reusable_workload_result"
            in sources["cloud_hardtail_workload_runner_script"]
            and "workload_result_candidates"
            in sources["cloud_hardtail_workload_runner_script"]
            and "rejection_reason"
            in sources["cloud_hardtail_workload_runner_script"]
            and "ignored_newer_results"
            in sources["cloud_hardtail_campaign_runner_script"]
            and "ignored_newer_results"
            in sources["cloud_hardtail_campaign_evaluator_script"]
        ),
        "cloud_hardtail_workload_artifacts_are_content_fingerprinted": (
            "ARTIFACT_INTEGRITY_ALGORITHM = \"sha256-size-v1\""
            in sources["cloud_hardtail_workload_runner_script"]
            and "def validate_workload_artifact_integrity"
            in sources["cloud_hardtail_workload_runner_script"]
            and "\"sha256\"" in sources["cloud_hardtail_workload_runner_script"]
            and "\"size_bytes\"" in sources["cloud_hardtail_workload_runner_script"]
            and "artifact_integrity_algorithm" in sources["cloud_hardtail_workload_runner_script"]
            and "validate_workload_artifact_integrity"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "workload artifact content no longer matches recorded fingerprint"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "artifact_integrity_mismatch"
            in sources["cloud_hardtail_workload_runner_script"]
        ),
        "cloud_hardtail_final_runtime_proof_requires_artifact_integrity": (
            "all_required_artifact_integrity_passed"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "artifact_integrity_required_workload_count"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "artifact_integrity_passed_workload_count"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "payload.get(\"all_required_artifact_integrity_passed\") is True"
            in sources["h48_oracle_contract_script"]
        ),
        "cloud_hardtail_evaluator_requires_h48_dependency_validation": (
            "def _h48_dependency_validation" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "h48_trusted_dependency_checks" in sources["cloud_hardtail_campaign_evaluator_script"]
            and "workload did not prove trusted H48 dependency validation before search"
            in sources["cloud_hardtail_campaign_evaluator_script"]
            and "full checksum check for" in sources["cloud_hardtail_campaign_evaluator_script"]
        ),
        "cloud_hardtail_fasttarget_can_require_native_h48_only": (
            "--hardtail-strategy" in sources["cloud_hardtail_campaign_script"]
            and "native-h48-only" in sources["cloud_hardtail_campaign_script"]
            and "--require-resident-h48-batch-for-all"
            in sources["cloud_hardtail_campaign_script"]
            and "require_resident_h48_batch_for_all"
            in sources["universal_oracle_cli_script"]
            and "resident_h48_batch_all_rows" in sources["universal_oracle_cli_script"]
            and 'plan.get("hardtail_strategy") == "native-h48-only"'
            in sources["cloud_hardtail_campaign_evaluator_script"]
        ),
        "h48_stronger_table_campaign_uses_process_tree_timeout": (
            "run_process_tree(" in sources["h48_stronger_table_campaign_script"]
            and "terminated_process_group" in sources["h48_stronger_table_campaign_script"]
            and "generation_failed_or_timed_out" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_streams_generation_progress": (
            "def _run_streaming_command" in sources["h48_stronger_table_campaign_script"]
            and "stderr=subprocess.STDOUT" in sources["h48_stronger_table_campaign_script"]
            and "stream_output=True" in sources["h48_stronger_table_campaign_script"]
            and "streamed_output" in sources["h48_stronger_table_campaign_script"]
            and "terminated_group = _terminate_process_group(process)"
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_requires_full_checksum": (
            "validate_trusted_h48_table_checksum" in sources["h48_stronger_table_campaign_script"]
            and "post_campaign_full_checksum_valid" in sources["h48_stronger_table_campaign_script"]
            and "post_campaign_checksum_details" in sources["h48_stronger_table_campaign_script"]
            and 'and checksum_ok' in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_table_generator_can_recover_exact_size_table_metadata": (
            "--adopt-existing-table-metadata" in sources["h48_table_generator_script"]
            and "adopt_existing_table_metadata" in sources["h48_table_helpers"]
            and "adopted_existing_table_metadata" in sources["h48_table_helpers"]
            and "adoption_trust_boundary" in sources["h48_table_helpers"]
            and "_run_h48_adoption_native_canary" in sources["h48_table_helpers"]
            and "adoption_native_table_check_passed" in sources["h48_table_helpers"]
            and "nissy_checkdata" in sources["h48_table_helpers"]
            and "--adopt-existing-table-metadata" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_can_wait_for_safe_generation": (
            "def wait_for_generation_safety" in sources["h48_stronger_table_campaign_script"]
            and "--wait-for-safe" in sources["h48_stronger_table_campaign_script"]
            and "deferred_by_safety_wait" in sources["h48_stronger_table_campaign_script"]
            and "safety_wait_timeout" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_logs_wait_safe_heartbeats": (
            "def _report_wait_sample" in sources["h48_stronger_table_campaign_script"]
            and "h48_generation_safety_sample" in sources["h48_stronger_table_campaign_script"]
            and "sample_reporter=_report_wait_sample" in sources["h48_stronger_table_campaign_script"]
            and "flush=True" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_recomputes_auto_threads_during_wait": (
            "def _resolve_thread_setting" in sources["h48_stronger_table_campaign_script"]
            and "resolved_threads = _resolve_thread_setting(threads)"
            in sources["h48_stronger_table_campaign_script"]
            and '"resolved_threads": resolved_threads'
            in sources["h48_stronger_table_campaign_script"]
            and "thread_setting=args.threads" in sources["h48_stronger_table_campaign_script"]
            and "final_threads = int(safety_wait[\"final_safety\"].get(\"threads\")"
            in sources["h48_stronger_table_campaign_script"]
            and '"dynamic_thread_selection": dynamic_thread_selection'
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_can_plan_detached_local_generation": (
            "def launch_detached_campaign" in sources["h48_stronger_table_campaign_script"]
            and "--detach" in sources["h48_stronger_table_campaign_script"]
            and "--detach-dry-run" in sources["h48_stronger_table_campaign_script"]
            and "detached_waitsafe_dryrun_planned_not_runtime_evidence"
            in sources["h48_stronger_table_campaign_script"]
            and "pid_file_path" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_can_probe_detached_local_status": (
            "def build_detached_status_payload" in sources["h48_stronger_table_campaign_script"]
            and "--detached-status-from" in sources["h48_stronger_table_campaign_script"]
            and "native_h48_backend_running" in sources["h48_stronger_table_campaign_script"]
            and "campaign_result_path" in sources["h48_stronger_table_campaign_script"]
            and "full_checksum_requested" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_exposes_status_alias": (
            "def _canonical_detached_status_source_path" in sources["h48_stronger_table_campaign_script"]
            and "--status" in sources["h48_stronger_table_campaign_script"]
            and "--status-artifact-suffix" in sources["h48_stronger_table_campaign_script"]
            and "detached_status_from = _canonical_detached_status_source_path"
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_status_exposes_top_level_pid_liveness": (
            '"pid": detached_status.get("pid")' in sources["h48_stronger_table_campaign_script"]
            and '"pid_file_pid": detached_status.get("pid_file_pid")'
            in sources["h48_stronger_table_campaign_script"]
            and '"effective_pid": detached_status.get("effective_pid")'
            in sources["h48_stronger_table_campaign_script"]
            and '"pid_alive": detached_status.get("pid_alive")'
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_oracle_contract_records_stronger_table_detached_status": (
            "def _latest_h48_stronger_table_detached_status"
            in sources["h48_oracle_contract_script"]
            and '"h48_stronger_table_detached_status"'
            in sources["h48_oracle_contract_script"]
            and "h48_stronger_table_detached_status_target_solver"
            in sources["h48_oracle_contract_script"]
            and "h48_stronger_table_detached_status_waitsafe_sample_count"
            in sources["h48_oracle_contract_script"]
        ),
        "h48_oracle_contract_records_fasttarget_stronger_table_status": (
            '"h48_fasttarget_stronger_table_detached_status"'
            in sources["h48_oracle_contract_script"]
            and "h48_fasttarget_stronger_table_status_payload"
            in sources["h48_oracle_contract_script"]
            and "h48_fasttarget_stronger_table_detached_status_target_solver"
            in sources["h48_oracle_contract_script"]
            and "h48_fasttarget_stronger_table_detached_status_target_trusted_table"
            in sources["h48_oracle_contract_script"]
        ),
        "h48_stronger_table_campaign_status_parses_generation_progress": (
            "H48_GENDATA_PROGRESS_RE" in sources["h48_stronger_table_campaign_script"]
            and "def _parse_h48_generation_progress" in sources["h48_stronger_table_campaign_script"]
            and '"generation_log_progress": generation_progress'
            in sources["h48_stronger_table_campaign_script"]
            and '"allocated_bytes": _disk_allocated_bytes(partial)'
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_status_parses_waitsafe_heartbeats": (
            "def _parse_wait_safety_progress" in sources["h48_stronger_table_campaign_script"]
            and '"event": "h48_generation_safety_sample"' in sources["h48_stronger_table_campaign_script"]
            and '"wait_safe_progress": wait_safe_progress'
            in sources["h48_stronger_table_campaign_script"]
            and "detached_python_alive_waiting_safety_gate_no_trusted_table"
            in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_status_reports_optimized_generation_options": (
            '"child_command_args": child_args' in sources["h48_stronger_table_campaign_script"]
            and '"h48_gendata_workbatch"' in sources["h48_stronger_table_campaign_script"]
            and '"h48_generation_distribution_mode"' in sources["h48_stronger_table_campaign_script"]
            and '"h48_generation_mmap_sync_mode"' in sources["h48_stronger_table_campaign_script"]
            and '"h48_backend_extra_cflags"' in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_exposes_mmap_memory_guard": (
            "--min-mmap-available-memory-gib" in sources["h48_stronger_table_campaign_script"]
            and "--min-mmap-available-memory-gib" in sources["h48_table_generator_script"]
            and "min_mmap_available_memory_bytes" in sources["h48_stronger_table_campaign_script"]
            and "min_mmap_available_memory_bytes" in sources["h48_table_generator_script"]
            and "min_mmap_available_memory_gib" in sources["h48_stronger_table_campaign_script"]
            and "--safety-only" in sources["h48_table_generator_script"]
        ),
        "h48_generation_safety_uses_storage_aware_disk_multiplier": (
            "H48_MMAP_GENERATION_DISK_MULTIPLIER = 1.15" in sources["h48_capacity_script"]
            and "H48_HEAP_GENERATION_DISK_MULTIPLIER = 2.0" in sources["h48_capacity_script"]
            and "disk_multiplier_source" in sources["h48_capacity_script"]
            and "--disk-multiplier" in sources["h48_table_generator_script"]
            and "--disk-multiplier" in sources["h48_stronger_table_campaign_script"]
            and "--disk-multiplier" in sources["cloud_hardtail_preflight_script"]
        ),
        "h48_table_storage_root_is_relocatable": (
            "H48_TABLE_ROOT_ENV = \"RUBIK_OPTIMAL_H48_TABLE_ROOT\""
            in sources["h48_table_helpers"]
            and "def h48_table_root" in sources["h48_table_helpers"]
            and "os.environ.get(H48_TABLE_ROOT_ENV)" in sources["h48_table_helpers"]
            and "return h48_table_root(root=root)" in sources["h48_table_helpers"]
            and "\"file_path\": _relative_or_absolute(root, table_path)"
            in sources["h48_table_helpers"]
            and "recorded_table_path = _relative_or_absolute(root, selected_table_path)"
            in sources["h48_table_helpers"]
        ),
        "h48_capacity_and_preflight_use_configured_table_root": (
            "h48_table_root(root=root)" in sources["h48_capacity_script"]
            and "h48_table_root(root=root)" in sources["cloud_hardtail_preflight_script"]
            and "\"h48_table_root_env\"" in sources["h48_capacity_script"]
            and "\"h48_table_root_env\"" in sources["cloud_hardtail_preflight_script"]
        ),
        "h48_proof_volume_inspector_records_local_nonaws_launch_gate": (
            "def build_proof_volume_payload" in sources["h48_proof_volume_inspector_script"]
            and "launchable_for_h48_generation" in sources["h48_proof_volume_inspector_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources[
                "h48_proof_volume_inspector_script"
            ]
            and "machine_source" in sources["h48_proof_volume_inspector_script"]
        ),
        "h48_proof_volume_inspector_uses_configured_h48_table_root": (
            "H48_TABLE_ROOT_ENV" in sources["h48_proof_volume_inspector_script"]
            and "h48_table_root(root=root)" in sources["h48_proof_volume_inspector_script"]
            and "--candidate-root" in sources["h48_proof_volume_inspector_script"]
            and "recommended_preflight_command" in sources["h48_proof_volume_inspector_script"]
        ),
        "h48_stronger_table_campaign_can_stop_stale_detached_waiter": (
            "def stop_detached_campaign" in sources["h48_stronger_table_campaign_script"]
            and "--detached-stop-from" in sources["h48_stronger_table_campaign_script"]
            and "detached_waiter_stopped" in sources["h48_stronger_table_campaign_script"]
            and "detached_stop_refused" in sources["h48_stronger_table_campaign_script"]
            and "native_h48_backend_running_before_stop"
            in sources["h48_stronger_table_campaign_script"]
            and "process_command_safe_to_stop" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_stronger_table_campaign_status_reports_process_resources": (
            "def _process_resource_snapshot" in sources["h48_stronger_table_campaign_script"]
            and '"process_resources": _process_resource_snapshot'
            in sources["h48_stronger_table_campaign_script"]
            and "native_h48_backend_process_resources"
            in sources["h48_stronger_table_campaign_script"]
            and "cpu_percent" in sources["h48_stronger_table_campaign_script"]
            and "rss_bytes" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_native_generation_workbatch_is_configurable": (
            "#ifndef H48_GENDATA_WORKBATCH" in sources["h48_gendata_h48"]
            and "H48_GENDATA_WORKBATCH 256" in sources["h48_gendata_h48"]
            and 'Processed %" PRIu64 " / %" PRIu64' in sources["h48_gendata_h48"]
            and "(done / 1000)" not in sources["h48_gendata_h48"]
            and "resolve_h48_gendata_workbatch" in sources["h48_table_helpers"]
            and "RUBIK_OPTIMAL_H48_GENDATA_WORKBATCH" in sources["h48_table_helpers"]
            and "h48_gendata_workbatch" in sources["h48_table_helpers"]
            and "--gendata-workbatch" in sources["h48_table_generator_script"]
            and "--gendata-workbatch" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_generation_can_skip_distribution_scan_with_expected_constants": (
            "H48_GENDATA_USE_EXPECTED_DISTRIBUTION" in sources["h48_gendata_h48"]
            and "gendata_h48_set_expected_distribution" in sources["h48_gendata_h48"]
            and "skipping full generated-table distribution scan" in sources["h48_gendata_h48"]
            and "-DH48_GENDATA_USE_EXPECTED_DISTRIBUTION="
            in sources["h48_table_helpers"]
            and "h48_generation_distribution_mode" in sources["h48_table_helpers"]
            and "--skip-generation-distribution-scan" in sources["h48_table_generator_script"]
            and "--skip-generation-distribution-scan"
            in sources["h48_stronger_table_campaign_script"]
            and "--skip-h48-generation-distribution-scan"
            in sources["cloud_hardtail_campaign_script"]
        ),
        "h48_generation_exposes_mmap_sync_mode": (
            "--mmap-sync-mode" in sources["h48_native_backend"]
            and "mmap_sync_runtime_seconds" in sources["h48_native_backend"]
            and "normalize_h48_mmap_sync_mode" in sources["h48_table_helpers"]
            and "h48_generation_mmap_sync_mode" in sources["h48_table_helpers"]
            and "--mmap-sync-mode" in sources["h48_table_generator_script"]
            and "--mmap-sync-mode" in sources["h48_stronger_table_campaign_script"]
            and "--h48-generation-mmap-sync-mode" in sources["cloud_hardtail_campaign_script"]
        ),
        "cloud_hardtail_campaign_forwards_h48_gendata_workbatch": (
            "resolve_h48_gendata_workbatch" in sources["cloud_hardtail_campaign_script"]
            and "--h48-gendata-workbatch" in sources["cloud_hardtail_campaign_script"]
            and "--gendata-workbatch" in sources["cloud_hardtail_campaign_script"]
            and '"h48_gendata_workbatch"' in sources["cloud_hardtail_campaign_script"]
            and "--gendata-workbatch" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_capacity_recommends_h48_gendata_workbatch": (
            "resolve_h48_gendata_workbatch" in sources["h48_capacity_script"]
            and "--gendata-workbatch" in sources["h48_capacity_script"]
            and '"h48_gendata_workbatch"' in sources["h48_capacity_script"]
        ),
        "h48_backend_exposes_audited_native_compile_flags": (
            "normalize_h48_backend_extra_cflags" in sources["h48_table_helpers"]
            and "h48_backend_extra_cflags" in sources["h48_table_helpers"]
            and "--backend-cflag" in sources["h48_table_generator_script"]
            and "--backend-cflag" in sources["h48_stronger_table_campaign_script"]
            and "--h48-backend-cflag" in sources["cloud_hardtail_campaign_script"]
            and "-march=" in sources["h48_table_helpers"]
        ),
        "h48_native_generation_uses_atomic_table_updates": (
            "set_h48_pval_atomic_min" in sources["h48_gendata_h48"]
            and "set_h48_pvalmin_atomic" in sources["h48_gendata_h48"]
            and "atomic_compare_exchange_weak_explicit" in sources["h48_gendata_h48"]
            and "memory_order_relaxed" in sources["h48_gendata_h48"]
            and ".table_atomic = table_atomic" in sources["h48_gendata_h48"]
            and ".table_atomic = arg->table_atomic" in sources["h48_gendata_h48"]
            and "wrapthread_mutex_lock(arg->table_mutex" not in sources["h48_gendata_h48"]
            and "wrapthread_mutex_lock(dfsarg->table_mutex" not in sources["h48_gendata_h48"]
            and "wrapthread_atomic unsigned char *table_atomic"
            in sources["h48_gendata_types_macros"]
        ),
        "h48_native_generation_uses_atomic_work_scheduling": (
            "h48_atomic_fetch_add_u64" in sources["h48_gendata_h48"]
            and "h48_atomic_load_u64" in sources["h48_gendata_h48"]
            and "atomic_fetch_add_explicit" in sources["h48_gendata_h48"]
            and "wrapthread_atomic uint64_t next;" in sources["h48_gendata_h48"]
            and ".next = &next" in sources["h48_gendata_h48"]
            and "dfsarg->next, H48_GENDATA_WORKBATCH" in sources["h48_gendata_h48"]
            and "h48_atomic_fetch_add_u64(dfsarg->scanned, local_scanned)"
            in sources["h48_gendata_h48"]
            and "h48_atomic_fetch_add_u64(dfsarg->count, local_count)"
            in sources["h48_gendata_h48"]
            and "h48_atomic_load_u64(dfsarg[0].scanned)" in sources["h48_gendata_h48"]
            and "shortcubes_mutex" not in sources["h48_gendata_h48"]
            and "shortcubes_mutex" not in sources["h48_gendata_types_macros"]
            and "wrapthread_atomic uint64_t *next" in sources["h48_gendata_types_macros"]
        ),
        "h48_native_generation_uses_edge_only_symmetry_marking": (
            "coord_h48_edges_rep" in sources["h48_coordinate"]
            and "return coord_h48_edges_rep(d, coclass, h)" in sources["h48_coordinate"]
            and "edge_rep = transform_edges(arg->cube, ttrep)" in sources["h48_gendata_h48"]
            and "edge_sym = transform_edges(edge_rep, t)" in sources["h48_gendata_h48"]
            and "coord = coord_h48_edges_rep(edge_sym, coclass, arg->h)"
            in sources["h48_gendata_h48"]
            and "FOREACH_H48SIM(arg->cube, arg->cocsepdata, arg->selfsim"
            not in sources["h48_gendata_h48"]
        ),
        "h48_native_short_generation_uses_edge_only_symmetry_expansion": (
            "coord_h48_edges_rep" in sources["h48_coordinate"]
            and "edge_rep = transform_edges(d, ttrep)" in sources["h48_gendata_h48"]
            and "edge_sym = transform_edges(edge_rep, t)" in sources["h48_gendata_h48"]
            and "coord = coord_h48_edges_rep(edge_sym, coclass, 11)"
            in sources["h48_gendata_h48"]
            and "FOREACH_H48SIM" not in sources["h48_gendata_h48"]
            and "FOREACH_H48SIM" not in sources["h48_gendata_types_macros"]
            and "similar h48 coordinates can be improved"
            not in sources["h48_gendata_types_macros"]
        ),
        "h48_contract_accepts_stronger_oracle_grade_solvers": (
            "def _h48_metadata_is_oracle_grade" in sources["h48_oracle_contract_script"]
            and "h48_solver_h_value(metadata_solver) >= h48_solver_h_value(ORACLE_H48_SOLVER)"
            in sources["h48_oracle_contract_script"]
            and '"h48_solver_is_oracle_grade": _h48_metadata_is_oracle_grade'
            in sources["h48_oracle_contract_script"]
        ),
        "cloud_hardtail_runbook_renders_cloud_execution_scripts": (
            "def build_cloud_hardtail_runbook" in sources["cloud_hardtail_runbook_script"]
            and "cloud_hardtail_preflight.py" in sources["cloud_hardtail_runbook_script"]
            and "preflight_leader" in sources["cloud_hardtail_runbook_script"]
            and "preflight_worker" in sources["cloud_hardtail_runbook_script"]
            and "run_cloud_hardtail_campaign.py" in sources["cloud_hardtail_runbook_script"]
            and "evaluate_cloud_hardtail_campaign.py" in sources["cloud_hardtail_runbook_script"]
            and "validate_h48_worker_table.py" in sources["cloud_hardtail_runbook_script"]
            and "validate_prerequisite_tables" in sources["cloud_hardtail_runbook_script"]
            and "collect_results.sh" in sources["cloud_hardtail_runbook_script"]
            and "run_full_machine_" in sources["cloud_hardtail_runbook_script"]
            and "finalize_full_after_collect.sh" in sources["cloud_hardtail_runbook_script"]
            and "parallel_assignments" in sources["cloud_hardtail_runbook_script"]
            and "run_canary.sh" in sources["cloud_hardtail_runbook_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_enforces_leader_preflight_before_real_runs": (
            sources["cloud_hardtail_runbook_script"].count("pre_commands=[leader_preflight]")
            >= 2
            and "pre_commands=full_pre_commands" in sources["cloud_hardtail_runbook_script"]
            and "run_full_prerequisites" in sources["cloud_hardtail_runbook_script"]
            and "run_canary" in sources["cloud_hardtail_runbook_script"]
            and "run_full" in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_validates_target_table_before_full": (
            "full_pre_commands.extend([worker_preflight_command, validation_command])"
            in sources["cloud_hardtail_runbook_script"]
            and "--require-target-table" in sources["cloud_hardtail_runbook_script"]
            and "scripts/validate_h48_worker_table.py" in sources["cloud_hardtail_runbook_script"]
            and "run_full_machine_" in sources["cloud_hardtail_runbook_script"]
            and "machine_run_suffix = f\"{safe_suffix}_m{index:02d}\""
            in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_reuses_shared_h48_prerequisite_for_canary": (
            "--h48-prerequisite-artifact-suffix" in sources["cloud_hardtail_campaign_script"]
            and "h48_prerequisite_artifact_suffix" in sources["cloud_hardtail_campaign_script"]
            and "def _shared_prerequisite_ids" in sources["cloud_hardtail_runbook_script"]
            and "run_canary_after_prerequisites" in sources["cloud_hardtail_runbook_script"]
            and "shared_canary_prerequisite_ids" in sources["cloud_hardtail_runbook_script"]
            and "canary_reuses_full_prerequisites" in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_separates_single_machine_and_staged_order": (
            "def _single_machine_run_order" in sources["cloud_hardtail_runbook_script"]
            and "def _manual_staged_run_order" in sources["cloud_hardtail_runbook_script"]
            and '"single_machine_run_order"' in sources["cloud_hardtail_runbook_script"]
            and '"manual_staged_run_order"' in sources["cloud_hardtail_runbook_script"]
            and '"run_order": manual_staged_run_order'
            in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_bootstraps_python_environment": (
            "def _bootstrap_cloud_machine_script" in sources["cloud_hardtail_runbook_script"]
            and "bootstrap_cloud_machine.sh" in sources["cloud_hardtail_runbook_script"]
            and "-m venv" in sources["cloud_hardtail_runbook_script"]
            and 'python -m pip install -e ".[dev]"' in sources["cloud_hardtail_runbook_script"]
            and ".venv/bin/activate" in sources["cloud_hardtail_runbook_script"]
            and "python -m rubik_optimal.cli --help" in sources["cloud_hardtail_runbook_script"]
            and "role=\"bootstrap\"" in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_records_nonaws_execution_summary": (
            '"aws_required": False' in sources["cloud_hardtail_runbook_script"]
            and '"nonaws_generic_ssh_supported": True'
            in sources["cloud_hardtail_runbook_script"]
            and '"nonaws_entrypoint": "scripts/run_h48_fasttarget_nonaws_proof.py"'
            in sources["cloud_hardtail_runbook_script"]
            and "def _plan_summary" in sources["cloud_hardtail_runbook_script"]
            and '"full_plan_summary": _plan_summary(full_plan)'
            in sources["cloud_hardtail_runbook_script"]
            and '"required_workload_ids"' in sources["cloud_hardtail_runbook_script"]
            and '"h48_gendata_workbatch"' in sources["cloud_hardtail_runbook_script"]
            and "AWS is not required by this runbook"
            in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_fingerprints_generated_files": (
            "def _file_fingerprint" in sources["cloud_hardtail_runbook_script"]
            and "hashlib.sha256" in sources["cloud_hardtail_runbook_script"]
            and '"generated_file_fingerprint_algorithm": "sha256-size-mode-v1"'
            in sources["cloud_hardtail_runbook_script"]
            and '"generated_file_fingerprints"' in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_can_recover_prerequisite_metadata": (
            "def _recover_prerequisite_metadata_script"
            in sources["cloud_hardtail_runbook_script"]
            and "recover_prerequisite_metadata.sh" in sources["cloud_hardtail_runbook_script"]
            and "recover_prerequisite_metadata" in sources["cloud_hardtail_runbook_script"]
            and "scripts/generate_h48_tables.py" in sources["cloud_hardtail_runbook_script"]
            and "--adopt-existing-table-metadata" in sources["cloud_hardtail_runbook_script"]
            and "staged partial" in sources["cloud_hardtail_runbook_script"]
            and "scripts/validate_h48_worker_table.py" in sources["cloud_hardtail_runbook_script"]
            and "--persistent-cache" in sources["cloud_hardtail_runbook_script"]
        ),
        "cloud_hardtail_runbook_exports_split_prerequisite_table_bundle": (
            "def _collect_prerequisite_table_parts_script"
            in sources["cloud_hardtail_runbook_script"]
            and "collect_prerequisite_table_parts.sh"
            in sources["cloud_hardtail_runbook_script"]
            and "scripts/create_h48_table_bundle.py"
            in sources["cloud_hardtail_runbook_script"]
            and "H48_TABLE_BUNDLE_PART_SIZE_MIB"
            in sources["cloud_hardtail_runbook_script"]
            and "split-parts directory" in sources["cloud_hardtail_runbook_script"]
        ),
        "h48_worker_table_validation_script_full_checksums": (
            "validate_trusted_h48_table_checksum" in sources["h48_worker_table_validation_script"]
            and "h48_worker_table_validation_" in sources["h48_worker_table_validation_script"]
            and "full_checksum_valid" in sources["h48_worker_table_validation_script"]
        ),
        "h48_table_bundle_creator_writes_split_manifest": (
            "h48_split_table_bundle" in sources["h48_table_bundle_creator_script"]
            and "h48_table_bundle_manifest.json"
            in sources["h48_table_bundle_creator_script"]
            and "split_reused_part_count" in sources["h48_table_bundle_creator_script"]
            and "validate_trusted_h48_table_checksum"
            in sources["h48_table_bundle_creator_script"]
            and "persistent_cache=True" in sources["h48_table_bundle_creator_script"]
        ),
        "h48_table_bundle_installer_skips_existing_full_checksum_target": (
            "source_validation_skipped" in sources["h48_table_bundle_installer_script"]
            and "target_table_already_installed" in sources["h48_table_bundle_installer_script"]
            and "validate_trusted_h48_table_checksum"
            in sources["h48_table_bundle_installer_script"]
            and "persistent_cache=True" in sources["h48_table_bundle_installer_script"]
            and "Skipped source bundle resolution"
            in sources["h48_table_bundle_installer_script"]
        ),
        "h48_table_bundle_installer_supports_split_manifest_bundle": (
            "def _assemble_split_manifest_bundle"
            in sources["h48_table_bundle_installer_script"]
            and "h48_split_table_bundle" in sources["h48_table_bundle_installer_script"]
            and "assembled_checksum_sha256" in sources["h48_table_bundle_installer_script"]
            and "prevalidated_split_manifest_assembly"
            in sources["h48_table_bundle_installer_script"]
            and "parts_validated" in sources["h48_table_bundle_installer_script"]
        ),
        "h48_table_bundle_installer_hardlinks_extracted_bundle": (
            "hardlink_from_extracted_bundle" in sources["h48_table_bundle_installer_script"]
            and "os.link" in sources["h48_table_bundle_installer_script"]
            and "fallback_copy_used" in sources["h48_table_bundle_installer_script"]
            and "table_install_method" in sources["h48_table_bundle_installer_script"]
            and "private temporary directory" in sources["h48_table_bundle_installer_script"]
        ),
        "h48_split_bundle_smoke_script_records_isolated_install": (
            "def run_h48_split_bundle_smoke" in sources["h48_split_bundle_smoke_script"]
            and "create_h48_table_bundle" in sources["h48_split_bundle_smoke_script"]
            and "install_h48_table_bundle" in sources["h48_split_bundle_smoke_script"]
            and "split_parts_validated" in sources["h48_split_bundle_smoke_script"]
            and "isolated_install_root_preserved" in sources["h48_split_bundle_smoke_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources[
                "h48_split_bundle_smoke_script"
            ]
        ),
        "h48_proof_workflow_uses_persistent_checksum_certificate": (
            "h48_checksum_certificate_path" in sources["h48_table_helpers"]
            and "_load_matching_h48_checksum_certificate" in sources["h48_table_helpers"]
            and "checksum_persistent_cache_hit" in sources["h48_worker_table_validation_script"]
            and "--persistent-cache" in sources["cloud_hardtail_runbook_script"]
            and "persistent_cache=True" in sources["cloud_hardtail_workload_runner_script"]
            and "persistent_cache=True" in sources["h48_fasttarget_remote_runner_script"]
            and "persistent_cache=True" in sources["h48_stronger_table_campaign_script"]
            and "persistent_cache=True" in sources["cloud_hardtail_preflight_script"]
        ),
        "cloud_hardtail_preflight_records_machine_gate": (
            "evaluate_h48_generation_safety" in sources["cloud_hardtail_preflight_script"]
            and "min_memory_gib" in sources["cloud_hardtail_preflight_script"]
            and "min_free_disk_gib" in sources["cloud_hardtail_preflight_script"]
            and "min_storage_gib" in sources["cloud_hardtail_preflight_script"]
            and "data_generated_h48_total_gib" in sources["cloud_hardtail_preflight_script"]
            and "require_target_table" in sources["cloud_hardtail_preflight_script"]
            and "cloud_hardtail_preflight_" in sources["cloud_hardtail_preflight_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources["cloud_hardtail_preflight_script"]
        ),
        "cloud_hardtail_preflight_records_target_h48_workspace": (
            "estimated_h48_table_size_bytes" in sources["cloud_hardtail_preflight_script"]
            and "target_h48_workspace" in sources["cloud_hardtail_preflight_script"]
            and "required_workspace_bytes" in sources["cloud_hardtail_preflight_script"]
            and "workspace_headroom_bytes" in sources["cloud_hardtail_preflight_script"]
            and "required H48 workspace" in sources["cloud_hardtail_preflight_script"]
        ),
        "cloud_hardtail_preflight_supports_assumed_nonaws_machine_spec": (
            "--assume-cpu-count" in sources["cloud_hardtail_preflight_script"]
            and "--assume-memory-gib" in sources["cloud_hardtail_preflight_script"]
            and "--assume-free-disk-gib" in sources["cloud_hardtail_preflight_script"]
            and "--assume-total-storage-gib" in sources["cloud_hardtail_preflight_script"]
            and "machine_source" in sources["cloud_hardtail_preflight_script"]
            and "assumed_machine_not_runtime_evidence" in sources["cloud_hardtail_preflight_script"]
        ),
        "h48_fasttarget_aws_provisioner_can_dryrun_target_ec2": (
            "def provision_plan" in sources["h48_fasttarget_aws_provisioner_script"]
            and "m6id.4xlarge" in sources["h48_fasttarget_aws_provisioner_script"]
            and "DryRunOperation" in sources["h48_fasttarget_aws_provisioner_script"]
            and "AWS CLI call blocked by default"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "nvme-Amazon_EC2_NVMe_Instance_Storage"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "instance_satisfies_runbook_requirements"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "refusing paid EC2 launch without exact --paid-ec2-ack"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "authorize-security-group-ingress"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "--ssh-cidr" in sources["h48_fasttarget_aws_provisioner_script"]
            and "proof_host_launch_dry_run_authorized"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "detached-staged-proof" in sources["h48_fasttarget_aws_provisioner_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_aws_provisioner_script"]
        ),
        "h48_fasttarget_aws_helpers_block_cli_by_default": (
            "AWS_API_UNLOCK_ENV" in sources["h48_fasttarget_aws_provisioner_script"]
            and "AWS CLI call blocked by default"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "ARCHIVED_AWS_EXECUTION_ENV"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "AWS_ARCHIVED_EXECUTION_MESSAGE"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "AWS_API_UNLOCK_ENV"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "AWS CLI call blocked by default"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "ARCHIVED_AWS_EXECUTION_ENV"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "AWS_ARCHIVED_EXECUTION_MESSAGE"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "AWS_API_UNLOCK_ENV" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "AWS CLI call blocked by default"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "ARCHIVED_AWS_EXECUTION_ENV" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "AWS_ARCHIVED_EXECUTION_MESSAGE"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_helpers_are_archived_for_current_route": (
            "The AWS H48 fast-target helper is archived for the current project route"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "scripts/run_h48_fasttarget_nonaws_proof.py"
            in sources["h48_fasttarget_aws_provisioner_script"]
            and "ARCHIVED_AWS_EXECUTION_ACK"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "ARCHIVED_AWS_EXECUTION_ACK"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_security_group_can_prepare_dedicated_ssh_access": (
            "def prepare_security_group_plan"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "create-security-group" in sources["h48_fasttarget_aws_security_group_script"]
            and "_authorize_ssh_ingress_command"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "authorize_ssh_ingress_command_template"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "revoke-security-group-ingress"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "delete-security-group" in sources["h48_fasttarget_aws_security_group_script"]
            and "SECURITY_GROUP_ACK" in sources["h48_fasttarget_aws_security_group_script"]
            and "dedicated_security_group_planned"
            in sources["h48_fasttarget_aws_security_group_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_aws_security_group_script"]
        ),
        "h48_fasttarget_aws_proof_runner_can_launch_wait_and_start_detached_proof": (
            "def run_aws_proof_plan"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "instance-status-ok" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "describe-instances" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "detached-staged-proof" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "stop-instances" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "terminate-instances" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "PAID_EC2_ACK" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "SSH_CIDR" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_can_create_dedicated_sg_before_launch": (
            "prepare_security_group_plan"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "create_dedicated_security_group"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "SECURITY_GROUP_ACK" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "created_security_group_id" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "effective_security_group_id"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "prepare_h48_fasttarget_aws_security_group.py"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "dedicated_security_group_cleanup_commands"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_can_cleanup_after_detached_proof": (
            "_run_instance_cleanup"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "_run_dedicated_security_group_cleanup"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--terminate-instance-on-success"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--cleanup-dedicated-security-group-on-success"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--terminate-instance-on-failure"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "instance-terminated"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "cleanup_passed" in sources["h48_fasttarget_aws_proof_runner_script"]
            and "execution_error" in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_checkpoints_before_remote_wait": (
            "checkpoint_payload"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "pre_remote_detached_proof"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "aws_h48_fasttarget_instance_ready_pre_remote_checkpoint_not_runtime_evidence"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "write_json(output, checkpoint_payload)"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "checkpoint_written_before_remote_start"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "pre_remote_checkpoint_path"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_passes_detached_wait_windows": (
            "DEFAULT_PREREQUISITE_WAIT_TIMEOUT_SECONDS"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "DEFAULT_FULL_WAIT_TIMEOUT_SECONDS"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "def _add_remote_wait_args"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--prerequisite-wait-timeout"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--full-wait-timeout"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "prerequisite_wait_timeout_seconds"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "full_wait_timeout_seconds"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_can_resume_from_checkpoint": (
            "def run_aws_checkpoint_resume_plan"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "def build_remote_resume_command"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "--resume-from-checkpoint"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "resume_from_checkpoint"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "aws_h48_fasttarget_checkpoint_resume_dryrun_planned_not_runtime_evidence"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "_instance_cleanup_action_from_checkpoint"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "_checkpoint_dedicated_security_group_cleanup_enabled"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_aws_proof_runner_writes_actionable_resume_command": (
            "def build_checkpoint_resume_command"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "aws_checkpoint_resume_command"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "aws_checkpoint_resume_command_template"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "resume_h48_fasttarget_aws_proof_from_checkpoint.sh"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "checkpoint_resume_script_path"
            in sources["h48_fasttarget_aws_proof_runner_script"]
            and "CHECKPOINT_PATH"
            in sources["h48_fasttarget_aws_proof_runner_script"]
        ),
        "h48_fasttarget_remote_runner_syncs_runs_fetches_and_finalizes": (
            "def run_remote_fasttarget_proof" in sources["h48_fasttarget_remote_runner_script"]
            and "run_end_to_end_single_machine" in sources["h48_fasttarget_remote_runner_script"]
            and "rsync" in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_results_archive" in sources["h48_fasttarget_remote_runner_script"]
            and "finalize_full_after_collect" in sources["h48_fasttarget_remote_runner_script"]
            and "fast_runtime_proven_for_every_possible_state" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_runs_cloud_bootstrap": (
            "remote_bootstrap_cloud_machine" in sources["h48_fasttarget_remote_runner_script"]
            and "bootstrap_cloud_machine" in sources["h48_fasttarget_remote_runner_script"]
            and "not in {\"end-to-end\", \"status\", \"wait-prerequisites\", \"wait-full\"}"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_fetches_diagnostics_on_fail": (
            "fetch_diagnostics_on_fail" in sources["h48_fasttarget_remote_runner_script"]
            and "diagnostic_fetch_command" in sources["h48_fasttarget_remote_runner_script"]
            and "triggered_by_failed_step" in sources["h48_fasttarget_remote_runner_script"]
            and "results/processed/" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_run_prerequisite_stage_separately": (
            "remote_action" in sources["h48_fasttarget_remote_runner_script"]
            and "run_full_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "collect_prerequisite_tables" in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_prerequisite_tables_archive" in sources["h48_fasttarget_remote_runner_script"]
            and "cloud_hardtail_prerequisite_tables_" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_supports_split_prerequisite_bundles": (
            "PREREQUISITE_BUNDLE_MODE_CHOICES"
            in sources["h48_fasttarget_remote_runner_script"]
            and "collect_prerequisite_table_parts"
            in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_prerequisite_table_parts"
            in sources["h48_fasttarget_remote_runner_script"]
            and "prerequisite_tables_parts_dir"
            in sources["h48_fasttarget_remote_runner_script"]
            and "prerequisite_bundle_mode"
            in sources["h48_fasttarget_remote_runner_script"]
            and "_prerequisite_scripts_for_mode"
            in sources["h48_fasttarget_remote_runner_script"]
            and "--prerequisite-bundle-mode"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_run_canary_after_prerequisites": (
            '"canary-after-prerequisites"' in sources["h48_fasttarget_remote_runner_script"]
            and "remote_run_canary_after_prerequisites"
            in sources["h48_fasttarget_remote_runner_script"]
            and "run_canary_after_prerequisites"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_run_preflight_only": (
            '"preflight"' in sources["h48_fasttarget_remote_runner_script"]
            and "remote_preflight_leader" in sources["h48_fasttarget_remote_runner_script"]
            and "preflight_leader" in sources["h48_fasttarget_remote_runner_script"]
            and "sync and run only the remote leader preflight before generation"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_start_prerequisites_detached": (
            '"start-prerequisites"' in sources["h48_fasttarget_remote_runner_script"]
            and "remote_start_prerequisites_detached"
            in sources["h48_fasttarget_remote_runner_script"]
            and "nohup bash -lc" in sources["h48_fasttarget_remote_runner_script"]
            and "h48_fasttarget_" in sources["h48_fasttarget_remote_runner_script"]
            and "start-prerequisites to launch the long H48 table prerequisite detached"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_probe_remote_status": (
            "remote_status" in sources["h48_fasttarget_remote_runner_script"]
            and "_remote_status_command" in sources["h48_fasttarget_remote_runner_script"]
            and "target_table_size_matches_expected" in sources["h48_fasttarget_remote_runner_script"]
            and "target_table_full_checksum_valid" in sources["h48_fasttarget_remote_runner_script"]
            and "validate_trusted_h48_table_checksum" in sources["h48_fasttarget_remote_runner_script"]
            and "contract_fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_remote_runner_script"]
            and "processed_workload_artifact_count" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_status_reports_detached_prerequisites": (
            "def detached_prerequisite_status" in sources["h48_fasttarget_remote_runner_script"]
            and "start_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "os.kill(pid, 0)" in sources["h48_fasttarget_remote_runner_script"]
            and "tail_max_lines" in sources["h48_fasttarget_remote_runner_script"]
            and "prerequisite_tables_archive_present"
            in sources["h48_fasttarget_remote_runner_script"]
            and "'detached_prerequisite': detached_prerequisite_status()"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_status_reports_detached_full_proof": (
            "def detached_full_proof_status" in sources["h48_fasttarget_remote_runner_script"]
            and "start_full" in sources["h48_fasttarget_remote_runner_script"]
            and "results_archive_present" in sources["h48_fasttarget_remote_runner_script"]
            and "'detached_full_proof': detached_full_proof_status()"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_wait_for_detached_prerequisites": (
            '"wait-prerequisites"' in sources["h48_fasttarget_remote_runner_script"]
            and "def _remote_wait_prerequisites_command"
            in sources["h48_fasttarget_remote_runner_script"]
            and "remote_wait_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "prerequisite_wait_timeout_seconds"
            in sources["h48_fasttarget_remote_runner_script"]
            and "prerequisite_poll_interval_seconds"
            in sources["h48_fasttarget_remote_runner_script"]
            and "ready_for_resume" in sources["h48_fasttarget_remote_runner_script"]
            and "validate_trusted_h48_table_checksum"
            in sources["h48_fasttarget_remote_runner_script"]
            and "target_table_full_checksum_valid"
            in sources["h48_fasttarget_remote_runner_script"]
            and "metadata_trusted_table"
            in sources["h48_fasttarget_remote_runner_script"]
            and "persistent_cache=True"
            in sources["h48_fasttarget_remote_runner_script"]
            and "stopped_without_ready_artifacts"
            in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_prerequisite_tables_archive"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_recover_prerequisite_metadata": (
            '"recover-prerequisite-metadata"'
            in sources["h48_fasttarget_remote_runner_script"]
            and '"recover_prerequisite_metadata"'
            in sources["h48_fasttarget_remote_runner_script"]
            and "remote_recover_prerequisite_metadata"
            in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_processed_artifacts"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_install_fetched_prerequisites": (
            "--install-fetched-prerequisites"
            in sources["h48_fasttarget_remote_runner_script"]
            and "install_fetched_prerequisite_tables"
            in sources["h48_fasttarget_remote_runner_script"]
            and "install_prerequisite_tables"
            in sources["h48_fasttarget_remote_runner_script"]
            and "cloud_hardtail_prerequisite_tables_"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_preserves_install_on_resume_finalize": (
            "def _preserve_requested_prerequisite_install_step"
            in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_prerequisite_tables_archive"
            in sources["h48_fasttarget_remote_runner_script"]
            and "install_fetched_prerequisite_tables"
            in sources["h48_fasttarget_remote_runner_script"]
            and "not _preserve_requested_prerequisite_install_step"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_start_full_detached": (
            '"start-full"' in sources["h48_fasttarget_remote_runner_script"]
            and "remote_start_full_detached" in sources["h48_fasttarget_remote_runner_script"]
            and "start_full" in sources["h48_fasttarget_remote_runner_script"]
            and "run_canary_after_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "run_full" in sources["h48_fasttarget_remote_runner_script"]
            and "evaluate_full" in sources["h48_fasttarget_remote_runner_script"]
            and "collect_results" in sources["h48_fasttarget_remote_runner_script"]
            and "nohup bash -lc" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_wait_for_detached_full": (
            '"wait-full"' in sources["h48_fasttarget_remote_runner_script"]
            and "def _remote_wait_full_command" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_wait_full" in sources["h48_fasttarget_remote_runner_script"]
            and "ready_for_finalize" in sources["h48_fasttarget_remote_runner_script"]
            and "full_wait_timeout_seconds" in sources["h48_fasttarget_remote_runner_script"]
            and "full_poll_interval_seconds" in sources["h48_fasttarget_remote_runner_script"]
            and "fetch_results_archive" in sources["h48_fasttarget_remote_runner_script"]
            and "finalize_full_after_collect" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_run_staged_detached_proof": (
            '"staged-proof"' in sources["h48_fasttarget_remote_runner_script"]
            and "def _staged_decision_from_remote_status"
            in sources["h48_fasttarget_remote_runner_script"]
            and "start_prerequisites_then_full" in sources["h48_fasttarget_remote_runner_script"]
            and "wait_prerequisites_then_full" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_start_prerequisites_detached"
            in sources["h48_fasttarget_remote_runner_script"]
            and "remote_wait_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_run_canary_after_prerequisites"
            in sources["h48_fasttarget_remote_runner_script"]
            and "remote_run_full" in sources["h48_fasttarget_remote_runner_script"]
            and "finalize_full_after_collect" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_can_run_detached_staged_proof": (
            '"detached-staged-proof"' in sources["h48_fasttarget_remote_runner_script"]
            and "def _detached_staged_decision_from_remote_status"
            in sources["h48_fasttarget_remote_runner_script"]
            and "start_prerequisites_then_start_full"
            in sources["h48_fasttarget_remote_runner_script"]
            and "wait_prerequisites_then_start_full"
            in sources["h48_fasttarget_remote_runner_script"]
            and "start_full_then_wait" in sources["h48_fasttarget_remote_runner_script"]
            and "wait_full" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_start_prerequisites_detached"
            in sources["h48_fasttarget_remote_runner_script"]
            and "remote_wait_prerequisites" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_start_full_detached" in sources["h48_fasttarget_remote_runner_script"]
            and "remote_wait_full" in sources["h48_fasttarget_remote_runner_script"]
            and "finalize_full_after_collect" in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_validates_results_archive_before_finalize": (
            "validate_cloud_hardtail_archive.py"
            in sources["h48_fasttarget_remote_runner_script"]
            and "validate_results_archive"
            in sources["h48_fasttarget_remote_runner_script"]
            and '"unpack_results_archive"'
            in sources["h48_fasttarget_remote_runner_script"]
            and "full_plan_path" in sources["cloud_hardtail_archive_validator_script"]
            and "cloud_hardtail_campaign_evaluation_"
            in sources["cloud_hardtail_archive_validator_script"]
            and "cloud_hardtail_workload_"
            in sources["cloud_hardtail_archive_validator_script"]
            and "plan_fingerprint" in sources["cloud_hardtail_archive_validator_script"]
            and "workload_fingerprint" in sources["cloud_hardtail_archive_validator_script"]
            and "all_required_workloads_passed"
            in sources["cloud_hardtail_archive_validator_script"]
            and "all_required_artifact_integrity_passed"
            in sources["cloud_hardtail_archive_validator_script"]
            and "cloud_runtime_evidence_passed"
            in sources["cloud_hardtail_archive_validator_script"]
        ),
        "h48_fasttarget_remote_runner_can_resume_from_status": (
            '"resume"' in sources["h48_fasttarget_remote_runner_script"]
            and "def _resume_decision_from_remote_status" in sources[
                "h48_fasttarget_remote_runner_script"
            ]
            and "fetch_finalize" in sources["h48_fasttarget_remote_runner_script"]
            and "resume_remote_full_skipped" in sources["h48_fasttarget_remote_runner_script"]
            and "metadata_trusted_table" in sources["h48_fasttarget_remote_runner_script"]
            and "target_table_full_checksum_valid" in sources["h48_fasttarget_remote_runner_script"]
            and "full checksum validates -> full" in sources["h48_fasttarget_remote_runner_script"]
            and "fast_runtime_proven_for_every_possible_state=true -> fetch_finalize"
            in sources["h48_fasttarget_remote_runner_script"]
            and "skipped_by_resume_decision" in sources["h48_fasttarget_remote_runner_script"]
            and "remote target H48 table, metadata, size, and full checksum are already trusted"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_remote_runner_requires_final_contract_proof": (
            "def _final_contract_summary" in sources["h48_fasttarget_remote_runner_script"]
            and "final_contract_required_for_pass"
            in sources["h48_fasttarget_remote_runner_script"]
            and "final_contract_proof_passed" in sources["h48_fasttarget_remote_runner_script"]
            and "cloud_runtime_proof_passed"
            in sources["h48_fasttarget_remote_runner_script"]
            and "all_required_artifact_integrity_passed"
            in sources["h48_fasttarget_remote_runner_script"]
            and "artifact_integrity_count_matches"
            in sources["h48_fasttarget_remote_runner_script"]
            and "missing_or_failed_workload_count"
            in sources["h48_fasttarget_remote_runner_script"]
            and "fast_runtime_proven_for_every_possible_state=true"
            in sources["h48_fasttarget_remote_runner_script"]
        ),
        "h48_fasttarget_nonaws_runner_forbids_aws_usage": (
            "def run_nonaws_fasttarget_proof"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "execution_provider"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "generic_ssh_non_aws"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "AWS_UNLOCK_ENV = \"RUBIK_OPTIMAL_ENABLE_AWS\""
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "scan_planned_steps_for_aws"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "refused_nonaws_guard"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "run_remote_fasttarget_proof"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_nonaws_runner_script"]
        ),
        "h48_fasttarget_nonaws_runner_validates_h48h10_runbook_before_execute": (
            "def _validate_nonaws_runbook_manifest"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "runbook_validation" in sources["h48_fasttarget_nonaws_runner_script"]
            and "runbook manifest/plan validation failed"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "generated_file_fingerprint_sha256_mismatch"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "generated_file_fingerprint_size_mismatch"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "runbook_missing_generated_file_fingerprints"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "stronger_table_missing_optimized_command_flag"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "h48_gendata_workbatch" in sources["h48_fasttarget_nonaws_runner_script"]
            and "--gendata-workbatch" in sources["h48_fasttarget_nonaws_runner_script"]
            and "--mmap-sync-mode" in sources["h48_fasttarget_nonaws_runner_script"]
            and "--backend-cflag=-march=native" in sources["h48_fasttarget_nonaws_runner_script"]
            and "--skip-generation-distribution-scan"
            in sources["h48_fasttarget_nonaws_runner_script"]
        ),
        "h48_fasttarget_nonaws_runner_passes_split_prerequisite_bundle_mode": (
            "PREREQUISITE_BUNDLE_MODE_CHOICES"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "collect_prerequisite_table_parts"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "prerequisite_bundle_mode=prerequisite_bundle_mode"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "--prerequisite-bundle-mode"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "prerequisite_bundle_mode"
            in sources["h48_fasttarget_nonaws_runner_script"]
        ),
        "h48_fasttarget_nonaws_runner_requires_launchable_package_for_execute": (
            "DEFAULT_PROOF_PACKAGE" in sources["h48_fasttarget_nonaws_runner_script"]
            and "LAUNCHABLE_PACKAGE_REQUIRED_ACTIONS"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "launchable_proof_package_required"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "proof_package_validation" in sources["h48_fasttarget_nonaws_runner_script"]
            and "readiness_classification_launchable"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "live_preflight_required" in sources["h48_fasttarget_nonaws_runner_script"]
            and "launchable_for_execution" in sources["h48_fasttarget_nonaws_runner_script"]
            and "preflight_is_live_runtime_evidence"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "preflight_requirement_satisfied"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "proof_volume_report_required"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "proof_volume_report_launchable"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "proof_volume_requirement_satisfied"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "package_sha256_matches_components"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "component_fingerprints_revalidated"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "component_fingerprint_sha256_mismatch"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "nonaws_h48_fasttarget_pre_remote_checkpoint_not_runtime_evidence"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "checkpoint_written_before_remote_start"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "checkpoint_resume_command"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "checkpoint_status_command"
            in sources["h48_fasttarget_nonaws_runner_script"]
            and "remote_host_matches" in sources["h48_fasttarget_nonaws_runner_script"]
            and "remote_root_matches" in sources["h48_fasttarget_nonaws_runner_script"]
            and "remote_host_placeholder" in sources["h48_fasttarget_nonaws_runner_script"]
            and "remote_root_placeholder" in sources["h48_fasttarget_nonaws_runner_script"]
            and "launchable H48H10 proof package validation failed"
            in sources["h48_fasttarget_nonaws_runner_script"]
        ),
        "h48_fasttarget_nonaws_proof_package_builds_byte_bound_manifest": (
            "def build_proof_package" in sources["h48_fasttarget_proof_package_script"]
            and "PACKAGE_KIND = \"h48_fasttarget_nonaws_proof_package\""
            in sources["h48_fasttarget_proof_package_script"]
            and "_validate_nonaws_runbook_manifest"
            in sources["h48_fasttarget_proof_package_script"]
            and "scan_planned_steps_for_aws" in sources["h48_fasttarget_proof_package_script"]
            and "build_remote_proof_steps" in sources["h48_fasttarget_proof_package_script"]
            and "prerequisite_bundle_mode=\"split\""
            in sources["h48_fasttarget_proof_package_script"]
            and "package_sha256" in sources["h48_fasttarget_proof_package_script"]
            and "component_fingerprints" in sources["h48_fasttarget_proof_package_script"]
            and "required_completion_gates" in sources["h48_fasttarget_proof_package_script"]
            and "generic_ssh_detached_staged_split_proof"
            in sources["h48_fasttarget_proof_package_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_proof_package_script"]
            and "--require-live-preflight"
            in sources["h48_fasttarget_proof_package_script"]
            and "launchable_for_execution"
            in sources["h48_fasttarget_proof_package_script"]
            and "preflight_is_live_runtime_evidence"
            in sources["h48_fasttarget_proof_package_script"]
            and "proof_volume_report_required"
            in sources["h48_fasttarget_proof_package_script"]
            and "proof_volume_requirement_satisfied"
            in sources["h48_fasttarget_proof_package_script"]
            and "proof_volume_report_launchable"
            in sources["h48_fasttarget_proof_package_script"]
            and "--require-proof-volume-report"
            in sources["h48_fasttarget_proof_package_script"]
            and "--proof-package"
            in sources["h48_fasttarget_proof_package_script"]
        ),
        "h48_fasttarget_nonaws_launch_preparation_gathers_live_launch_evidence": (
            "ARTIFACT_KIND = \"h48_fasttarget_nonaws_launch_preparation\""
            in sources["h48_fasttarget_nonaws_launch_script"]
            and "def prepare_launch_package" in sources["h48_fasttarget_nonaws_launch_script"]
            and "write_preflight(" in sources["h48_fasttarget_nonaws_launch_script"]
            and "write_proof_volume_report(" in sources["h48_fasttarget_nonaws_launch_script"]
            and "build_proof_package(" in sources["h48_fasttarget_nonaws_launch_script"]
            and "require_live_preflight=True" in sources["h48_fasttarget_nonaws_launch_script"]
            and "require_proof_volume_report=True"
            in sources["h48_fasttarget_nonaws_launch_script"]
            and "heavy_generation_started" in sources["h48_fasttarget_nonaws_launch_script"]
            and "proof_workloads_started" in sources["h48_fasttarget_nonaws_launch_script"]
            and "next_execute_command_after_approval"
            in sources["h48_fasttarget_nonaws_launch_script"]
            and "--proof-package" in sources["h48_fasttarget_nonaws_launch_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_nonaws_launch_script"]
        ),
        "h48_oracle_contract_requires_nonaws_runbook_fingerprint_validation": (
            "h48_fasttarget_nonaws_fingerprint_validation_passed"
            in sources["h48_oracle_contract_script"]
            and '"generated_file_fingerprint_algorithm"'
            in sources["h48_oracle_contract_script"]
            and '"generated_file_fingerprint_count"'
            in sources["h48_oracle_contract_script"]
            and '"missing_generated_file_fingerprint_keys"'
            in sources["h48_oracle_contract_script"]
            and '"actual_sha256"' in sources["h48_oracle_contract_script"]
            and '"expected_sha256"' in sources["h48_oracle_contract_script"]
            and '"actual_size_bytes"' in sources["h48_oracle_contract_script"]
            and '"expected_size_bytes"' in sources["h48_oracle_contract_script"]
            and '"actual_mode_octal"' in sources["h48_oracle_contract_script"]
            and '"expected_mode_octal"' in sources["h48_oracle_contract_script"]
        ),
        "h48_fasttarget_local_runner_runs_generated_nonaws_runbook": (
            "def run_local_fasttarget_proof" in sources["h48_fasttarget_local_runner_script"]
            and "EXECUTION_PROVIDER = \"local_non_aws\""
            in sources["h48_fasttarget_local_runner_script"]
            and "ACTION_TO_RUNBOOK_FILE" in sources["h48_fasttarget_local_runner_script"]
            and "scan_planned_steps_for_aws" in sources["h48_fasttarget_local_runner_script"]
            and "aws_usage_allowed" in sources["h48_fasttarget_local_runner_script"]
            and "final_contract_proof_passed" in sources["h48_fasttarget_local_runner_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["h48_fasttarget_local_runner_script"]
        ),
        "h48_fasttarget_local_runner_validates_h48h10_runbook_before_execute": (
            "_validate_nonaws_runbook_manifest"
            in sources["h48_fasttarget_local_runner_script"]
            and "runbook_validation" in sources["h48_fasttarget_local_runner_script"]
            and "runbook manifest/plan validation failed"
            in sources["h48_fasttarget_local_runner_script"]
            and "refused_local_nonaws_guard"
            in sources["h48_fasttarget_local_runner_script"]
        ),
        "h48_fasttarget_local_runner_requires_launchable_package_for_staged_execute": (
            "DEFAULT_PROOF_PACKAGE" in sources["h48_fasttarget_local_runner_script"]
            and "launchable_proof_package_required"
            in sources["h48_fasttarget_local_runner_script"]
            and "proof_package_validation" in sources["h48_fasttarget_local_runner_script"]
            and "readiness_classification_launchable"
            in sources["h48_fasttarget_local_runner_script"]
            and "live_preflight_required" in sources["h48_fasttarget_local_runner_script"]
            and "launchable_for_execution" in sources["h48_fasttarget_local_runner_script"]
            and "preflight_is_live_runtime_evidence"
            in sources["h48_fasttarget_local_runner_script"]
            and "preflight_requirement_satisfied"
            in sources["h48_fasttarget_local_runner_script"]
            and "proof_volume_report_required"
            in sources["h48_fasttarget_local_runner_script"]
            and "proof_volume_report_launchable"
            in sources["h48_fasttarget_local_runner_script"]
            and "proof_volume_requirement_satisfied"
            in sources["h48_fasttarget_local_runner_script"]
            and "launchable H48H10 proof package validation failed"
            in sources["h48_fasttarget_local_runner_script"]
        ),
        "h48_fasttarget_local_runner_executes_staged_single_machine_order": (
            "SEQUENCE_ACTION_TO_RUNBOOK_ORDER"
            in sources["h48_fasttarget_local_runner_script"]
            and '"staged-proof": "single_machine_run_order"'
            in sources["h48_fasttarget_local_runner_script"]
            and "planned_steps" in sources["h48_fasttarget_local_runner_script"]
            and "step_results" in sources["h48_fasttarget_local_runner_script"]
            and "sequence_summary" in sources["h48_fasttarget_local_runner_script"]
            and "finalize_full_after_collect"
            in sources["h48_fasttarget_local_runner_script"]
            and "local_nonaws_staged_proof_failed_final_contract"
            in sources["h48_fasttarget_local_runner_script"]
        ),
        "universal_symmetry_evidence_script_uses_package_api": "UniversalOptimalOracle(config)"
        in sources["universal_symmetry_oracle_script"]
        and "nissy_symmetry_variants" in sources["universal_symmetry_oracle_script"]
        and "nissy-symmetry-batch" in sources["universal_symmetry_oracle_script"],
        "certificate_inverse_evidence_script_uses_universal_api": "ExactCertificateStore(ROOT)"
        in sources["certificate_cache_inverse_script"]
        and "UniversalOptimalOracle(config)" in sources["certificate_cache_inverse_script"]
        and "certificate_derivation" in sources["certificate_cache_inverse_script"],
        "certificate_symmetry_evidence_script_uses_universal_api": "ExactCertificateStore(ROOT)"
        in sources["certificate_cache_symmetry_script"]
        and "UniversalOptimalOracle(config)" in sources["certificate_cache_symmetry_script"]
        and "SYMMETRY_DERIVATIONS" in sources["certificate_cache_symmetry_script"],
        "learned_certificate_cache_evidence_script_uses_universal_api": "learned_certificate_artifact=learned_log"
        in sources["learned_certificate_cache_script"]
        and "certificate_artifacts=()" in sources["learned_certificate_cache_script"]
        and "replay_live_backends_enabled" in sources["learned_certificate_cache_script"]
        and "UniversalOptimalOracle(" in sources["learned_certificate_cache_script"],
        "h48_capacity_script_records_stronger_table_build_plan": "h48_stronger_table_build_plan"
        in sources["h48_capacity_script"]
        and "all_state_fast_oracle_completion_gate" in sources["h48_capacity_script"]
        and "H48_FAST_TARGET_SOLVER" in sources["h48_capacity_script"]
        and "h48_16_thread_upstream_benchmark" in sources["h48_capacity_script"]
        and "h48_stronger_table_generation_plan_options" in sources["h48_capacity_script"]
        and '"h48_gendata_workbatch"' in sources["h48_capacity_script"]
        and "--skip-generation-distribution-scan" in sources["h48_capacity_script"]
        and "--mmap-sync-mode" in sources["h48_capacity_script"]
        and "--backend-cflag" in sources["h48_capacity_script"],
        "h48_contract_separates_fast_target_plan_from_local_table": (
            "h48_capacity_fast_target_proof_plan_valid" in sources["h48_oracle_contract_script"]
            and "h48_capacity_plan_recommends_optimized_generation"
            in sources["h48_oracle_contract_script"]
            and "can_claim_fast_oracle_for_every_possible_state" in sources["h48_oracle_contract_script"]
        ),
        "h48_table_generator_has_generation_safety_guard": "--require-safe"
        in sources["h48_table_generator_script"]
        and "evaluate_h48_generation_safety" in sources["h48_table_generator_script"],
        "h48_table_generator_refuses_untrusted_existing_table": (
            "refusing to reuse existing H48 table without trusted metadata"
            in sources["h48_table_helpers"]
            and "reused_trusted_table" in sources["h48_table_helpers"]
            and "reuse_trusted_metadata_valid" in sources["h48_table_helpers"]
        ),
        "h48_generation_probe_uses_native_mmap_progress": "--generate-mmap"
        in sources["h48_generation_probe_script"]
        and "--progress-log" in sources["h48_generation_probe_script"]
        and "build_h48_backend(root=root, threads=threads, gendata_workbatch=resolved_workbatch)"
        in sources["h48_generation_probe_script"],
        "h48_generation_probe_records_native_workbatch": "--gendata-workbatch"
        in sources["h48_generation_probe_script"]
        and "resolve_h48_gendata_workbatch" in sources["h48_generation_probe_script"]
        and '"h48_gendata_workbatch": resolved_workbatch'
        in sources["h48_generation_probe_script"]
        and "gendata_workbatch=args.gendata_workbatch"
        in sources["h48_generation_probe_script"],
        "h48_generation_uses_upstream_workbatch_default": "DEFAULT_H48_GENDATA_WORKBATCH = 256"
        in sources["h48_table_helpers"]
        and "#define H48_GENDATA_WORKBATCH 256" in sources["h48_gendata_h48"],
        "h48_generation_logs_scan_progress": (
            "Scanned %\" PRIu64 \" / %\" PRIu64" in sources["h48_gendata_h48"]
            and "scanned_shortcube_slots" in sources["h48_generation_probe_script"]
            and "scanned_shortcube_slots" in sources["h48_stronger_table_campaign_script"]
        ),
        "h48_generation_probe_is_bounded_and_cleans_partial": "communicate(timeout=timeout_seconds)"
        in sources["h48_generation_probe_script"]
        and "--keep-partial" in sources["h48_generation_probe_script"]
        and "partial_path.unlink()" in sources["h48_generation_probe_script"],
        "h48_generation_probe_parses_native_progress": "def parse_progress_lines"
        in sources["h48_generation_probe_script"]
        and "PROGRESS_RE" in sources["h48_generation_probe_script"]
        and "Processed\\s+" in sources["h48_generation_probe_script"],
        "fast_oracle_api_evidence_script_uses_package_api": "FastOptimalOracle(config)"
        in sources["fast_optimal_oracle_api_script"],
        "fast_oracle_api_evidence_script_records_all_state_contract": "fast_optimal_oracle_implemented_for_every_valid_3x3_state"
        in sources["fast_optimal_oracle_api_script"],
        "external_nissy_optimal_backend_exists": "def solve_nissy_optimal" in sources["external_nissy_solver"],
        "external_nissy_optimal_requires_public_table": "pt_nxopt31_HTM" in sources["external_nissy_solver"]
        and "required_table" in sources["external_nissy_solver"],
        "external_nissy_optimal_independently_verifies_solution": "verify_solution(cube, solution)"
        in sources["external_nissy_solver"],
        "external_nissy_optimal_uses_direct_state_bridge": (
            "def solve_nissy2_state_optimal" in sources["external_nissy_solver"]
            and "build_nissy2_state_bridge" in sources["external_nissy_solver"]
            and "nissy2_state_optimal_external" in sources["external_nissy_solver"]
            and "input_mode=cube_state" in sources["external_nissy_solver"]
            and "len(cubes) == 1" in sources["external_nissy_solver"]
            and "solve_nissy2_state_optimal(" in sources["external_nissy_solver"]
            and "cube_from_local_arrays" in sources["external_nissy2_state_bridge"]
            and "corner_cofb_from_coud" in sources["external_nissy2_state_bridge"]
            and "corner_corl_from_coud" in sources["external_nissy2_state_bridge"]
            and "solve(cube, &optimal_HTM, &opts)" in sources["external_nissy2_state_bridge"]
        ),
        "external_nissy_batch_recovers_partial_timeout_rows": "_parse_partial_batch_solutions"
        in sources["external_nissy_solver"]
        and "partial_timeout_recovered=true" in sources["external_nissy_solver"]
        and "partial_completed_count" in sources["external_nissy_solver"],
        "external_nissy_batch_orders_shorter_scrambles_first": (
            "ordered_pending = sorted(pending" in sources["external_nissy_solver"]
            and "batch_ordered_by_scramble_length=true" in sources["external_nissy_solver"]
            and "batch_original_index" in sources["external_nissy_solver"]
        ),
        "external_nissy_core_direct_backend_exists": "def solve_nissy_core_direct_optimal"
        in sources["external_nissy_solver"]
        and "cube_to_nissy_string(cube)" in sources["external_nissy_solver"]
        and "input_mode=cube_state" in sources["external_nissy_solver"],
        "external_nissy_core_direct_backend_uses_h48_table_symlink": "TemporaryDirectory"
        in sources["external_nissy_solver"]
        and "symlink_to" in sources["external_nissy_solver"]
        and "table_symlink=true" in sources["external_nissy_solver"],
        "external_nissy_core_direct_backend_enforces_optimal_zero": '"-O"'
        in sources["external_nissy_solver"]
        and '"0"' in sources["external_nissy_solver"]
        and "nissy-core direct H48 shell backend" in sources["external_nissy_solver"],
        "external_nissy_core_direct_batch_backend_reuses_h48_table_symlink": (
            "def solve_nissy_core_direct_optimal_batch" in sources["external_nissy_solver"]
            and "rubik-nissy-core-batch-" in sources["external_nissy_solver"]
            and "table_symlink_reused=true" in sources["external_nissy_solver"]
            and "process_per_row=true" in sources["external_nissy_solver"]
            and "verify_solution(cube, solution)" in sources["external_nissy_solver"]
        ),
        "external_nissy_core_python_resident_backend_exists": (
            "class NissyCoreDirectPythonSession" in sources["external_nissy_solver"]
            and "nissy_core_worker" in sources["external_nissy_solver"]
            and "table_loaded_once=true" in sources["external_nissy_solver"]
            and "process_per_batch=true" in sources["external_nissy_solver"]
            and "verify_solution(cube, solution)" in sources["external_nissy_solver"]
            and "def main(" in sources["external_nissy_core_worker"]
            and "table_mmap = mmap.mmap(" in sources["external_nissy_core_worker"]
            and "solve_fn =" in sources["external_nissy_core_worker"]
            and "solve_fn(" in sources["external_nissy_core_worker"]
        ),
        "external_nissy_core_python_resident_has_safe_table_size_gate": (
            "RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES" in sources["external_nissy_solver"]
            and "_DEFAULT_NISSY_CORE_PYTHON_MAX_TABLE_BYTES" in sources["external_nissy_solver"]
            and "_nissy_core_python_enabled_for_table" in sources["external_nissy_solver"]
            and "RUBIK_OPTIMAL_NISSY_CORE_PYTHON" in sources["external_nissy_solver"]
        ),
        "external_nissy_core_python_resident_uses_mmap_buffer_when_available": (
            "import mmap" in sources["external_nissy_core_worker"]
            and "mmap.mmap(" in sources["external_nissy_core_worker"]
            and "hasattr(nissy, \"solve_buffer\")" in sources["external_nissy_core_worker"]
            and "table_data_mode" in sources["external_nissy_core_worker"]
            and "table_data_mode={self.table_data_mode}" in sources["external_nissy_solver"]
        ),
        "external_nissy_core_python_resident_auto_allows_large_mmap_tables": (
            "def _nissy_core_python_supports_solve_buffer" in sources["external_nissy_solver"]
            and "_nissy_core_python_enabled_for_table(" in sources["external_nissy_solver"]
            and "selected_table, module_root" in sources["external_nissy_solver"]
            and "if _nissy_core_python_supports_solve_buffer(module_root):" in sources[
                "external_nissy_solver"
            ]
            and '"solve_buffer_available"' in sources["external_nissy_core_worker"]
            and "solve_buffer_available={self.solve_buffer_available}" in sources[
                "external_nissy_solver"
            ]
        ),
        "external_nissy_core_python_resident_mmap_evidence_script_exists": (
            "solve_nissy_core_direct_optimal_batch"
            in sources["external_nissy_core_resident_mmap_script"]
            and "shell_fallback_disabled_by_missing_binary"
            in sources["external_nissy_core_resident_mmap_script"]
            and "all_used_resident_mmap"
            in sources["external_nissy_core_resident_mmap_script"]
            and "table_data_mode" in sources["external_nissy_core_resident_mmap_script"]
            and "solve_buffer_available" in sources["external_nissy_core_resident_mmap_script"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["external_nissy_core_resident_mmap_script"]
        ),
        "cli_exposes_nissy_core_direct_backend": '"nissy-core-direct"' in sources["cli"]
        and "solve_nissy_core_direct_optimal" in sources["cli"],
        "external_nissy_table_installer_fetches_single_range": "downloads only the selected entry" in sources[
            "external_nissy_table_installer"
        ]
        and "Range" in sources["external_nissy_table_installer"],
        "external_nissy_table_verifier_checks_complete_public_install": (
            "build_public_table_completeness_payload"
            in sources["external_nissy_table_verifier"]
            and "all_archive_tables_installed"
            in sources["external_nissy_table_verifier"]
            and "all_archive_table_sizes_match"
            in sources["external_nissy_table_verifier"]
            and "Some pruning tables are missing or unreadable"
            in sources["external_nissy_table_verifier"]
            and "fast_runtime_proven_for_every_possible_state"
            in sources["external_nissy_table_verifier"]
        ),
        "optimal_3x3_script_exposes_nissy_optimal_backend": '"nissy-optimal"'
        in sources["optimal_3x3_script"],
        "optimal_3x3_script_exposes_nissy_core_direct_backend": '"nissy-core-direct"'
        in sources["optimal_3x3_script"]
        and "solve_nissy_core_direct_optimal" in sources["optimal_3x3_script"],
        "distance_uses_h48_depth_20": "max_depth=20" in sources["distance_wrapper"]
        and "h48_native" in sources["distance_wrapper"],
    }

    h48_fasttarget_runbook_generated_files = (
        h48_fasttarget_runbook_payload.get("generated_files") or {}
    )
    h48_fasttarget_nonaws_runbook_validation = (
        h48_fasttarget_nonaws_detached_staged_proof_payload.get("runbook_validation") or {}
    )
    h48_fasttarget_nonaws_fingerprint_checks = (
        h48_fasttarget_nonaws_runbook_validation.get("generated_file_fingerprint_checks")
        or []
    )
    h48_fasttarget_nonaws_fingerprint_validation_passed = (
        h48_fasttarget_nonaws_runbook_validation.get(
            "generated_file_fingerprint_algorithm"
        )
        == "sha256-size-mode-v1"
        and h48_fasttarget_nonaws_runbook_validation.get(
            "generated_file_fingerprint_count"
        )
        == len(h48_fasttarget_runbook_generated_files)
        and h48_fasttarget_nonaws_runbook_validation.get(
            "missing_generated_file_fingerprint_keys"
        )
        == []
        and len(h48_fasttarget_nonaws_fingerprint_checks)
        == len(h48_fasttarget_runbook_generated_files)
        and all(
            check.get("passed") is True
            and check.get("actual_sha256") == check.get("expected_sha256")
            and check.get("actual_size_bytes") == check.get("expected_size_bytes")
            and check.get("actual_mode_octal") == check.get("expected_mode_octal")
            for check in h48_fasttarget_nonaws_fingerprint_checks
        )
    )

    artifact_checks = {
        "h48_table_present": table_path.exists(),
        "h48_metadata_present": metadata is not None,
        "h48_trusted_metadata_valid": trusted_ok,
        "h48_table_size_matches_metadata": bool(metadata)
        and table_path.exists()
        and int(metadata.get("table_size_bytes", -1)) == table_path.stat().st_size,
        "h48_solver_is_oracle_grade": _h48_metadata_is_oracle_grade(metadata, solver=solver),
        "h48_solver_is_oracle_grade_h48h7": _h48_metadata_is_oracle_grade(metadata, solver=solver),
        "nissy_public_optimal_table_installed": bool(nissy_install_payload)
        and nissy_install_payload.get("passed") is True
        and nissy_install_payload.get("installed") is True
        and nissy_install_payload.get("target_size_matches_archive") is True
        and nissy_install_target.exists()
        and nissy_install_target.stat().st_size == int(nissy_install_payload.get("target_size_bytes", -1) or -1),
        "nissy_public_tables_complete": bool(nissy_complete_payload)
        and nissy_complete_payload.get("passed") is True
        and nissy_complete_payload.get("archive_table_entry_count") == 18
        and nissy_complete_payload.get("installed_table_count") == 18
        and nissy_complete_payload.get("all_archive_tables_installed") is True
        and nissy_complete_payload.get("all_archive_table_sizes_match") is True
        and (nissy_complete_payload.get("nissy_ptable") or {}).get("reports_missing_tables") is False
        and nissy_complete_payload.get("fast_runtime_proven_for_every_possible_state") is False,
        "h48_capacity_stronger_table_plan_valid": bool(h48_capacity_payload)
        and h48_capacity_payload.get("profile") == profile
        and h48_capacity_payload.get("seed") == seed
        and h48_capacity_payload.get("strongest_local_oracle_solver") == solver
        and h48_capacity_payload.get("next_missing_oracle_grade_solver") == "h48h8"
        and h48_capacity_payload.get("h48_first_stronger_solver") == "h48h8"
        and h48_capacity_payload.get("h48_fast_target_solver") == "h48h10"
        and h48_capacity_fast_target_proof_plan_valid
        and h48_capacity_gate.get("target_solver") == "h48h10"
        and h48_capacity_gate.get("first_missing_ladder_solver") == "h48h8"
        and h48_capacity_gate.get("target_table_expected_size_bytes") == 30_336_314_216
        and h48_capacity_gate.get("target_upstream_benchmark_has_distance20_timing") is True
        and h48_capacity_gate.get("target_upstream_benchmark_has_superflip_timing") is True,
        "h48_capacity_fast_target_proof_plan_valid": h48_capacity_fast_target_proof_plan_valid,
        "h48_proof_volume_candidates_current_local_machine_recorded": bool(
            h48_proof_volume_candidates_payload
        )
        and h48_proof_volume_candidates_payload.get("artifact_kind")
        == "h48_proof_volume_candidates"
        and h48_proof_volume_candidates_payload.get("profile") == profile
        and h48_proof_volume_candidates_payload.get("seed") == seed
        and h48_proof_volume_candidates_payload.get("solver") == "h48h10"
        and h48_proof_volume_candidates_payload.get("machine_source") == "local"
        and h48_proof_volume_candidates_payload.get("h48_table_root_env")
        == "RUBIK_OPTIMAL_H48_TABLE_ROOT"
        and int(h48_proof_volume_candidates_payload.get("candidate_count", 0) or 0) >= 1
        and (h48_proof_volume_candidates_payload.get("requirements") or {}).get(
            "target_table_size_bytes"
        )
        == 30_336_314_216
        and (h48_proof_volume_candidates_payload.get("requirements") or {}).get(
            "workspace_multiplier"
        )
        == 1.15
        and h48_proof_volume_candidates_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_generation_probe_records_h48h8_lowload_bottleneck": bool(h48_generation_probe_payload)
        and h48_generation_probe_payload.get("profile") == profile
        and h48_generation_probe_payload.get("seed") == seed
        and h48_generation_probe_payload.get("solver") == "h48h8"
        and h48_generation_probe_payload.get("status") == "timed_out"
        and h48_generation_probe_payload.get("probe_completed") is True
        and h48_generation_probe_payload.get("full_table_generated") is False
        and h48_generation_probe_payload.get("partial_cleanup_status") == "deleted_partial_probe_file"
        and h48_generation_probe_payload.get("expected_table_size_bytes") == 7_585_624_040
        and (h48_generation_probe_payload.get("safety") or {}).get("safe_to_start") is False,
        "h48_split_bundle_smoke_installed_isolated_trusted_table": bool(
            h48_split_bundle_smoke_payload
        )
        and h48_split_bundle_smoke_payload.get("artifact_kind") == "h48_split_bundle_smoke"
        and h48_split_bundle_smoke_payload.get("profile") == profile
        and h48_split_bundle_smoke_payload.get("seed") == seed
        and h48_split_bundle_smoke_payload.get("solver") == "h48h0"
        and h48_split_bundle_smoke_payload.get("passed") is True
        and h48_split_bundle_smoke_payload.get("bundle_part_count", 0) > 1
        and h48_split_bundle_smoke_payload.get("source_full_checksum_valid") is True
        and h48_split_bundle_smoke_payload.get("split_manifest_validated") is True
        and h48_split_bundle_smoke_payload.get("split_parts_validated") is True
        and h48_split_bundle_smoke_payload.get("installed_from_split_manifest") is True
        and h48_split_bundle_smoke_payload.get("post_install_full_checksum_valid") is True
        and h48_split_bundle_smoke_payload.get("installed_table_size_bytes") == 31_683_944
        and h48_split_bundle_smoke_payload.get("expected_table_size_bytes") == 31_683_944
        and h48_split_bundle_smoke_payload.get("source_checksum_sha256")
        == h48_split_bundle_smoke_payload.get("installed_checksum_sha256")
        and h48_split_bundle_smoke_payload.get("isolated_install_root_preserved") is True
        and h48_split_bundle_smoke_payload.get("fast_runtime_proven_for_every_possible_state")
        is False,
        "h48_split_bundle_oracle_grade_smoke_installed_isolated_trusted_table": bool(
            h48_split_bundle_oracle_grade_smoke_payload
        )
        and h48_split_bundle_oracle_grade_smoke_payload.get("artifact_kind")
        == "h48_split_bundle_smoke"
        and h48_split_bundle_oracle_grade_smoke_payload.get("profile") == profile
        and h48_split_bundle_oracle_grade_smoke_payload.get("seed") == seed
        and h48_split_bundle_oracle_grade_smoke_payload.get("solver") == "h48h7"
        and h48_split_bundle_oracle_grade_smoke_payload.get("h_value") == 7
        and h48_split_bundle_oracle_grade_smoke_payload.get("oracle_grade") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("passed") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("bundle_part_count", 0) > 1
        and h48_split_bundle_oracle_grade_smoke_payload.get("source_full_checksum_valid") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("split_manifest_validated") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("split_parts_validated") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("installed_from_split_manifest") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("post_install_full_checksum_valid") is True
        and h48_split_bundle_oracle_grade_smoke_payload.get("source_table_size_bytes")
        == 3_793_842_344
        and h48_split_bundle_oracle_grade_smoke_payload.get("installed_table_size_bytes")
        == 3_793_842_344
        and h48_split_bundle_oracle_grade_smoke_payload.get("expected_table_size_bytes")
        == 3_793_842_344
        and h48_split_bundle_oracle_grade_smoke_payload.get("source_checksum_sha256")
        == h48_split_bundle_oracle_grade_smoke_payload.get("installed_checksum_sha256")
        and h48_split_bundle_oracle_grade_smoke_payload.get("isolated_install_root_preserved")
        is True
        and h48_split_bundle_oracle_grade_smoke_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_runbook_bootstrap_planned": bool(h48_fasttarget_runbook_payload)
        and h48_fasttarget_runbook_payload.get("status") == "runbook_generated_not_runtime_evidence"
        and h48_fasttarget_runbook_payload.get("profile") == profile
        and h48_fasttarget_runbook_payload.get("seed") == seed
        and h48_fasttarget_runbook_payload.get("solver") == "h48h10"
        and h48_fasttarget_runbook_payload.get("fast_runtime_proven_for_every_possible_state")
        is False
        and "bootstrap_cloud_machine"
        in (h48_fasttarget_runbook_payload.get("generated_files") or {})
        and "recover_prerequisite_metadata"
        in (h48_fasttarget_runbook_payload.get("generated_files") or {})
        and "collect_prerequisite_table_parts"
        in (h48_fasttarget_runbook_payload.get("generated_files") or {})
        and h48_fasttarget_runbook_payload.get("generated_file_fingerprint_algorithm")
        == "sha256-size-mode-v1"
        and set((h48_fasttarget_runbook_payload.get("generated_file_fingerprints") or {}).keys())
        == set((h48_fasttarget_runbook_payload.get("generated_files") or {}).keys())
        and all(
            isinstance(fingerprint, dict)
            and fingerprint.get("path")
            == (h48_fasttarget_runbook_payload.get("generated_files") or {}).get(key)
            and isinstance(fingerprint.get("size_bytes"), int)
            and isinstance(fingerprint.get("sha256"), str)
            and len(fingerprint.get("sha256", "")) == 64
            and isinstance(fingerprint.get("mode_octal"), str)
            for key, fingerprint in (
                h48_fasttarget_runbook_payload.get("generated_file_fingerprints") or {}
            ).items()
        )
        and str(
            (h48_fasttarget_runbook_payload.get("generated_files") or {}).get(
                "bootstrap_cloud_machine", ""
            )
        ).endswith("bootstrap_cloud_machine.sh")
        and str(
            (h48_fasttarget_runbook_payload.get("generated_files") or {}).get(
                "recover_prerequisite_metadata", ""
            )
        ).endswith("recover_prerequisite_metadata.sh")
        and str(
            (h48_fasttarget_runbook_payload.get("generated_files") or {}).get(
                "collect_prerequisite_table_parts", ""
            )
        ).endswith("collect_prerequisite_table_parts.sh")
        and h48_fasttarget_runbook_payload.get("aws_required") is False
        and h48_fasttarget_runbook_payload.get("nonaws_generic_ssh_supported") is True
        and h48_fasttarget_runbook_payload.get("nonaws_entrypoint")
        == "scripts/run_h48_fasttarget_nonaws_proof.py"
        and (h48_fasttarget_runbook_payload.get("full_plan_summary") or {}).get(
            "claim_scope"
        )
        == "full"
        and (h48_fasttarget_runbook_payload.get("full_plan_summary") or {}).get(
            "required_workload_count"
        )
        == 8
        and (h48_fasttarget_runbook_payload.get("full_plan_summary") or {}).get(
            "hardtail_strategy"
        )
        == "native-h48-only"
        and "stronger_table_h48h10"
        in (
            (h48_fasttarget_runbook_payload.get("full_plan_summary") or {}).get(
                "required_workload_ids"
            )
            or []
        )
        and (
            (
                h48_fasttarget_runbook_payload.get("full_plan_summary") or {}
            ).get("recommended_minimum_machine")
            or {}
        ).get("cpu_count")
        == 16
        and (h48_fasttarget_runbook_payload.get("single_machine_run_order") or [None])[0]
        == "bootstrap_cloud_machine"
        and (h48_fasttarget_runbook_payload.get("manual_staged_run_order") or [None])[0]
        == "bootstrap_cloud_machine",
        "h48_fasttarget_assumed_nonaws_machine_preflight_passed": bool(
            h48_fasttarget_assumed_preflight_payload
        )
        and h48_fasttarget_assumed_preflight_payload.get("profile") == profile
        and h48_fasttarget_assumed_preflight_payload.get("seed") == seed
        and h48_fasttarget_assumed_preflight_payload.get("solver") == "h48h10"
        and h48_fasttarget_assumed_preflight_payload.get("passed") is True
        and h48_fasttarget_assumed_preflight_payload.get("machine_source") == "assumed"
        and h48_fasttarget_assumed_preflight_payload.get("assumed_machine_not_runtime_evidence")
        is True
        and h48_fasttarget_assumed_preflight_payload.get("require_target_table") is False
        and h48_fasttarget_assumed_preflight_payload.get("fast_runtime_proven_for_every_possible_state")
        is False
        and h48_fasttarget_assumed_preflight_payload.get("min_cpus") == 16
        and h48_fasttarget_assumed_preflight_payload.get("min_memory_gib") == 64.0
        and h48_fasttarget_assumed_preflight_payload.get("min_storage_gib") == 250.0
        and (h48_fasttarget_assumed_preflight_payload.get("machine") or {}).get("cpu_count") == 16
        and (h48_fasttarget_assumed_preflight_payload.get("machine") or {}).get("memory_gib")
        == 64.0
        and (h48_fasttarget_assumed_preflight_payload.get("machine") or {}).get(
            "data_generated_h48_total_gib"
        )
        == 250.0
        and (
            h48_fasttarget_assumed_preflight_payload.get("target_h48_workspace") or {}
        ).get("satisfies_workspace")
        is True
        and (h48_fasttarget_assumed_preflight_payload.get("generation_safety") or {}).get(
            "assumed_machine"
        )
        is True,
        "h48_fasttarget_aws_provision_dryrun_authorized": bool(
            h48_fasttarget_aws_provision_payload
        )
        and h48_fasttarget_aws_provision_payload.get("status")
        == "ec2_and_ssh_dryrun_authorized_not_runtime_evidence"
        and h48_fasttarget_aws_provision_payload.get("profile") == profile
        and h48_fasttarget_aws_provision_payload.get("seed") == seed
        and h48_fasttarget_aws_provision_payload.get("solver") == "h48h10"
        and h48_fasttarget_aws_provision_payload.get("execute") is False
        and h48_fasttarget_aws_provision_payload.get("passed") is True
        and h48_fasttarget_aws_provision_payload.get("security_group_explicit") is True
        and h48_fasttarget_aws_provision_payload.get("cloud_init_has_ssh_key") is True
        and h48_fasttarget_aws_provision_payload.get("remote_access_dry_run_authorized")
        is True
        and h48_fasttarget_aws_provision_payload.get(
            "proof_host_launch_dry_run_authorized"
        )
        is True
        and h48_fasttarget_aws_provision_payload.get(
            "instance_satisfies_runbook_requirements"
        )
        is True
        and (h48_fasttarget_aws_provision_payload.get("aws_dry_run") or {}).get(
            "authorized"
        )
        is True
        and (
            h48_fasttarget_aws_provision_payload.get("ssh_ingress_dry_run") or {}
        ).get("authorized")
        is True
        and h48_fasttarget_aws_provision_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False
        and (
            h48_fasttarget_aws_provision_payload.get("runbook_requirements") or {}
        ).get("h48_target_solver")
        == "h48h10"
        and (
            h48_fasttarget_aws_provision_payload.get("instance_summary") or {}
        ).get("instance_type")
        == "m6id.4xlarge",
        "h48_fasttarget_aws_security_group_dryrun_authorized": bool(
            h48_fasttarget_aws_security_group_payload
        )
        and h48_fasttarget_aws_security_group_payload.get("status")
        == "dedicated_security_group_dryrun_authorized_not_runtime_evidence"
        and h48_fasttarget_aws_security_group_payload.get("execute") is False
        and h48_fasttarget_aws_security_group_payload.get("passed") is True
        and h48_fasttarget_aws_security_group_payload.get("region") == "eu-west-1"
        and h48_fasttarget_aws_security_group_payload.get("group_name")
        == "sgarbas-h48-fasttarget-proof"
        and h48_fasttarget_aws_security_group_payload.get("dedicated_security_group_planned")
        is True
        and (
            h48_fasttarget_aws_security_group_payload.get("create_security_group_dry_run")
            or {}
        ).get("authorized")
        is True
        and "authorize-security-group-ingress"
        in (
            h48_fasttarget_aws_security_group_payload.get(
                "authorize_ssh_ingress_command_template"
            )
            or []
        )
        and "revoke-security-group-ingress"
        in (
            (
                h48_fasttarget_aws_security_group_payload.get("cleanup_commands")
                or {}
            ).get("revoke_ssh_ingress")
            or []
        )
        and "delete-security-group"
        in (
            (
                h48_fasttarget_aws_security_group_payload.get("cleanup_commands")
                or {}
            ).get("delete_security_group")
            or []
        )
        and h48_fasttarget_aws_security_group_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_aws_proof_run_dryrun_planned": bool(
            h48_fasttarget_aws_proof_run_payload
        )
        and h48_fasttarget_aws_proof_run_payload.get("status")
        == "aws_h48_fasttarget_proof_dryrun_planned_not_runtime_evidence"
        and h48_fasttarget_aws_proof_run_payload.get("profile") == profile
        and h48_fasttarget_aws_proof_run_payload.get("seed") == seed
        and h48_fasttarget_aws_proof_run_payload.get("solver") == "h48h10"
        and h48_fasttarget_aws_proof_run_payload.get("execute") is False
        and h48_fasttarget_aws_proof_run_payload.get("passed") is True
        and h48_fasttarget_aws_proof_run_payload.get("provision_status")
        == "ec2_and_ssh_dryrun_authorized_not_runtime_evidence"
        and h48_fasttarget_aws_proof_run_payload.get("proof_host_launch_dry_run_authorized")
        is True
        and "instance-status-ok"
        in (h48_fasttarget_aws_proof_run_payload.get("aws_wait_instance_status_command") or [])
        and "describe-instances"
        in (h48_fasttarget_aws_proof_run_payload.get("aws_describe_instance_command") or [])
        and "detached-staged-proof"
        in (h48_fasttarget_aws_proof_run_payload.get("remote_start_command") or [])
        and "--prerequisite-wait-timeout"
        in (h48_fasttarget_aws_proof_run_payload.get("remote_start_command") or [])
        and "--full-wait-timeout"
        in (h48_fasttarget_aws_proof_run_payload.get("remote_start_command") or [])
        and "--resume-from-checkpoint"
        in (
            h48_fasttarget_aws_proof_run_payload.get(
                "aws_checkpoint_resume_command_template"
            )
            or []
        )
        and "${CHECKPOINT_PATH}"
        in (
            h48_fasttarget_aws_proof_run_payload.get(
                "aws_checkpoint_resume_command_template"
            )
            or []
        )
        and "--execute"
        in (
            h48_fasttarget_aws_proof_run_payload.get(
                "aws_checkpoint_resume_command_template"
            )
            or []
        )
        and str(
            h48_fasttarget_aws_proof_run_payload.get(
                "checkpoint_resume_script_path"
            )
            or ""
        ).endswith("resume_h48_fasttarget_aws_proof_from_checkpoint.sh")
        and h48_fasttarget_aws_proof_run_payload.get(
            "prerequisite_wait_timeout_seconds"
        )
        == 43_200.0
        and h48_fasttarget_aws_proof_run_payload.get("full_wait_timeout_seconds")
        == 28_800.0
        and "stop-instances"
        in (h48_fasttarget_aws_proof_run_payload.get("aws_stop_instance_command") or [])
        and "terminate-instances"
        in (h48_fasttarget_aws_proof_run_payload.get("aws_terminate_instance_command") or [])
        and "instance-terminated"
        in (
            h48_fasttarget_aws_proof_run_payload.get("aws_wait_instance_terminated_command")
            or []
        )
        and h48_fasttarget_aws_proof_run_payload.get("terminate_instance_on_success")
        is True
        and h48_fasttarget_aws_proof_run_payload.get(
            "cleanup_dedicated_security_group_on_success"
        )
        is True
        and h48_fasttarget_aws_proof_run_payload.get("cleanup_attempted") is False
        and h48_fasttarget_aws_proof_run_payload.get("pre_remote_checkpoint_written")
        is False
        and h48_fasttarget_aws_proof_run_payload.get("checkpoint_written_before_remote_start")
        is False
        and h48_fasttarget_aws_proof_run_payload.get(
            "create_dedicated_security_group_for_execute"
        )
        is True
        and h48_fasttarget_aws_proof_run_payload.get(
            "execute_script_uses_dedicated_security_group"
        )
        is True
        and h48_fasttarget_aws_proof_run_payload.get("dedicated_security_group_status")
        == "dedicated_security_group_dryrun_authorized_not_runtime_evidence"
        and h48_fasttarget_aws_proof_run_payload.get("dedicated_security_group_passed")
        is True
        and str(
            h48_fasttarget_aws_proof_run_payload.get(
                "dedicated_security_group_artifact_path"
            )
            or ""
        ).endswith("aws_h48_fasttarget_security_group_aws_proof_dryrun_sg.json")
        and h48_fasttarget_aws_proof_run_payload.get(
            "security_group_ack_required_for_dedicated_security_group_execute"
        )
        == "I understand this creates or changes an AWS security group"
        and h48_fasttarget_aws_proof_run_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_preflight_dryrun_planned": bool(
            h48_fasttarget_remote_preflight_payload
        )
        and h48_fasttarget_remote_preflight_payload.get("remote_action") == "preflight"
        and h48_fasttarget_remote_preflight_payload.get("execute") is False
        and h48_fasttarget_remote_preflight_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_preflight_payload.get("profile") == profile
        and h48_fasttarget_remote_preflight_payload.get("seed") == seed
        and h48_fasttarget_remote_preflight_payload.get("step_count") == 5
        and [
            row.get("id")
            for row in h48_fasttarget_remote_preflight_payload.get("rows", [])
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "fetch_processed_artifacts",
        ]
        and h48_fasttarget_remote_preflight_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_status_dryrun_planned": bool(
            h48_fasttarget_remote_status_payload
        )
        and h48_fasttarget_remote_status_payload.get("remote_action") == "status"
        and h48_fasttarget_remote_status_payload.get("execute") is False
        and h48_fasttarget_remote_status_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_status_payload.get("profile") == profile
        and h48_fasttarget_remote_status_payload.get("seed") == seed
        and h48_fasttarget_remote_status_payload.get("step_count") == 1
        and [
            row.get("id")
            for row in h48_fasttarget_remote_status_payload.get("rows", [])
        ]
        == ["remote_status"]
        and all(
            token in str(h48_fasttarget_remote_status_payload["rows"][0].get("shell_command", ""))
            for token in [
                "detached_prerequisite",
                "start_prerequisites",
                "os.kill(pid, 0)",
                "tail_max_lines",
                "prerequisite_tables_archive_present",
            ]
        )
        and h48_fasttarget_remote_status_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_wait_prerequisites_dryrun_planned": bool(
            h48_fasttarget_remote_wait_prerequisites_payload
        )
        and h48_fasttarget_remote_wait_prerequisites_payload.get("remote_action")
        == "wait-prerequisites"
        and h48_fasttarget_remote_wait_prerequisites_payload.get("execute") is False
        and h48_fasttarget_remote_wait_prerequisites_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_wait_prerequisites_payload.get("profile") == profile
        and h48_fasttarget_remote_wait_prerequisites_payload.get("seed") == seed
        and h48_fasttarget_remote_wait_prerequisites_payload.get("step_count") == 3
        and [
            row.get("id")
            for row in h48_fasttarget_remote_wait_prerequisites_payload.get("rows", [])
        ]
        == [
            "remote_wait_prerequisites",
            "fetch_prerequisite_tables_archive",
            "fetch_processed_artifacts",
        ]
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "prerequisite_wait_timeout_seconds",
                    "prerequisite_poll_interval_seconds",
                    "ready_for_resume",
                    "start_prerequisites",
                    "os.kill(pid, 0)",
                    "validate_trusted_h48_table_checksum",
                    "target_table_full_checksum_valid",
                    "metadata_trusted_table",
                ]
            )
            for row in h48_fasttarget_remote_wait_prerequisites_payload.get("rows", [])
            if row.get("id") == "remote_wait_prerequisites"
        )
        and h48_fasttarget_remote_wait_prerequisites_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_recover_prerequisite_metadata_dryrun_planned": bool(
            h48_fasttarget_remote_recover_prerequisite_metadata_payload
        )
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("remote_action")
        == "recover-prerequisite-metadata"
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("execute")
        is False
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("solver")
        == "h48h10"
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("profile")
        == profile
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("seed")
        == seed
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get("step_count")
        == 5
        and [
            row.get("id")
            for row in h48_fasttarget_remote_recover_prerequisite_metadata_payload.get(
                "rows", []
            )
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_bootstrap_cloud_machine",
            "remote_recover_prerequisite_metadata",
            "fetch_processed_artifacts",
        ]
        and any(
            "recover_prerequisite_metadata.sh" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_recover_prerequisite_metadata_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_recover_prerequisite_metadata"
        )
        and h48_fasttarget_remote_recover_prerequisite_metadata_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_wait_prerequisites_install_dryrun_planned": bool(
            h48_fasttarget_remote_wait_prerequisites_install_payload
        )
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("remote_action")
        == "wait-prerequisites"
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("execute") is False
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("profile") == profile
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("seed") == seed
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get("step_count") == 4
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get(
            "install_fetched_prerequisites"
        )
        is True
        and [
            row.get("id")
            for row in h48_fasttarget_remote_wait_prerequisites_install_payload.get(
                "rows", []
            )
        ]
        == [
            "remote_wait_prerequisites",
            "fetch_prerequisite_tables_archive",
            "install_fetched_prerequisite_tables",
            "fetch_processed_artifacts",
        ]
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "ready_for_resume",
                    "validate_trusted_h48_table_checksum",
                    "target_table_full_checksum_valid",
                    "metadata_trusted_table",
                ]
            )
            for row in h48_fasttarget_remote_wait_prerequisites_install_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_wait_prerequisites"
        )
        and any(
            "install_prerequisite_tables.sh" in str(row.get("shell_command", ""))
            and "cloud_hardtail_prerequisite_tables_" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_wait_prerequisites_install_payload.get(
                "rows", []
            )
            if row.get("id") == "install_fetched_prerequisite_tables"
        )
        and h48_fasttarget_remote_wait_prerequisites_install_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_resume_install_dryrun_planned": bool(
            h48_fasttarget_remote_resume_install_payload
        )
        and h48_fasttarget_remote_resume_install_payload.get("remote_action") == "resume"
        and h48_fasttarget_remote_resume_install_payload.get("execute") is False
        and h48_fasttarget_remote_resume_install_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_resume_install_payload.get("profile") == profile
        and h48_fasttarget_remote_resume_install_payload.get("seed") == seed
        and h48_fasttarget_remote_resume_install_payload.get("step_count") == 18
        and h48_fasttarget_remote_resume_install_payload.get(
            "install_fetched_prerequisites"
        )
        is True
        and [
            row.get("id")
            for row in h48_fasttarget_remote_resume_install_payload.get("rows", [])
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_status",
            "remote_bootstrap_cloud_machine",
            "remote_run_prerequisites",
            "remote_collect_prerequisite_tables",
            "remote_preflight_worker",
            "remote_validate_prerequisite_tables",
            "remote_run_full",
            "remote_evaluate_full",
            "remote_collect_results",
            "fetch_prerequisite_tables_archive",
            "install_fetched_prerequisite_tables",
            "fetch_processed_artifacts",
            "fetch_results_archive",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and any(
            "install_prerequisite_tables.sh" in str(row.get("shell_command", ""))
            and "cloud_hardtail_prerequisite_tables_" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_resume_install_payload.get("rows", [])
            if row.get("id") == "install_fetched_prerequisite_tables"
        )
        and h48_fasttarget_remote_resume_install_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_start_prerequisites_dryrun_planned": bool(
            h48_fasttarget_remote_start_prerequisites_payload
        )
        and h48_fasttarget_remote_start_prerequisites_payload.get("remote_action")
        == "start-prerequisites"
        and h48_fasttarget_remote_start_prerequisites_payload.get("execute") is False
        and h48_fasttarget_remote_start_prerequisites_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_start_prerequisites_payload.get("profile") == profile
        and h48_fasttarget_remote_start_prerequisites_payload.get("seed") == seed
        and h48_fasttarget_remote_start_prerequisites_payload.get("step_count") == 6
        and [
            row.get("id")
            for row in h48_fasttarget_remote_start_prerequisites_payload.get("rows", [])
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "remote_start_prerequisites_detached",
            "fetch_processed_artifacts",
        ]
        and any(
            row.get("detached") is True
            for row in h48_fasttarget_remote_start_prerequisites_payload.get("rows", [])
        )
        and h48_fasttarget_remote_start_prerequisites_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_staged_proof_dryrun_planned": bool(
            h48_fasttarget_remote_staged_proof_payload
        )
        and h48_fasttarget_remote_staged_proof_payload.get("remote_action")
        == "staged-proof"
        and h48_fasttarget_remote_staged_proof_payload.get("execute") is False
        and h48_fasttarget_remote_staged_proof_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_staged_proof_payload.get("profile") == profile
        and h48_fasttarget_remote_staged_proof_payload.get("seed") == seed
        and h48_fasttarget_remote_staged_proof_payload.get("step_count") == 19
        and [
            row.get("id")
            for row in h48_fasttarget_remote_staged_proof_payload.get("rows", [])
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_status",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "remote_start_prerequisites_detached",
            "remote_wait_prerequisites",
            "remote_preflight_worker",
            "remote_validate_prerequisite_tables",
            "remote_run_canary_after_prerequisites",
            "remote_run_full",
            "remote_evaluate_full",
            "remote_collect_results",
            "fetch_results_archive",
            "fetch_prerequisite_tables_archive",
            "fetch_processed_artifacts",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and any(
            row.get("detached") is True
            for row in h48_fasttarget_remote_staged_proof_payload.get("rows", [])
        )
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "ready_for_resume",
                    "prerequisite_wait_timeout_seconds",
                    "start_prerequisites",
                ]
            )
            for row in h48_fasttarget_remote_staged_proof_payload.get("rows", [])
            if row.get("id") == "remote_wait_prerequisites"
        )
        and h48_fasttarget_remote_staged_proof_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_detached_staged_proof_dryrun_planned": bool(
            h48_fasttarget_remote_detached_staged_proof_payload
        )
        and h48_fasttarget_remote_detached_staged_proof_payload.get("remote_action")
        == "detached-staged-proof"
        and h48_fasttarget_remote_detached_staged_proof_payload.get("execute") is False
        and h48_fasttarget_remote_detached_staged_proof_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_detached_staged_proof_payload.get("profile") == profile
        and h48_fasttarget_remote_detached_staged_proof_payload.get("seed") == seed
        and h48_fasttarget_remote_detached_staged_proof_payload.get("step_count") == 15
        and [
            row.get("id")
            for row in h48_fasttarget_remote_detached_staged_proof_payload.get(
                "rows", []
            )
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_status",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "remote_start_prerequisites_detached",
            "remote_wait_prerequisites",
            "remote_start_full_detached",
            "remote_wait_full",
            "fetch_results_archive",
            "fetch_prerequisite_tables_archive",
            "fetch_processed_artifacts",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and any(
            row.get("detached") is True
            and "start_prerequisites" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_detached_staged_proof_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_start_prerequisites_detached"
        )
        and any(
            row.get("detached") is True
            and "start_full" in str(row.get("shell_command", ""))
            and "run_canary_after_prerequisites" in str(row.get("shell_command", ""))
            and "collect_results" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_detached_staged_proof_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_start_full_detached"
        )
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "ready_for_resume",
                    "prerequisite_wait_timeout_seconds",
                    "start_prerequisites",
                ]
            )
            for row in h48_fasttarget_remote_detached_staged_proof_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_wait_prerequisites"
        )
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "ready_for_finalize",
                    "full_wait_timeout_seconds",
                    "start_full",
                    "cloud_hardtail_artifacts_",
                ]
            )
            for row in h48_fasttarget_remote_detached_staged_proof_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_wait_full"
        )
        and h48_fasttarget_remote_detached_staged_proof_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_nonaws_detached_staged_proof_validates_runbook": bool(
            h48_fasttarget_nonaws_detached_staged_proof_payload
        )
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("execution_provider")
        == "generic_ssh_non_aws"
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("aws_usage_allowed")
        is False
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("remote_action")
        == "detached-staged-proof"
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("execute") is False
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("solver") == "h48h10"
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("profile") == profile
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get("seed") == seed
        and (
            h48_fasttarget_nonaws_detached_staged_proof_payload.get("aws_command_scan")
            or {}
        ).get("passed")
        is True
        and (
            h48_fasttarget_nonaws_detached_staged_proof_payload.get("runbook_validation")
            or {}
        ).get("passed")
        is True
        and h48_fasttarget_nonaws_fingerprint_validation_passed
        and (
            h48_fasttarget_nonaws_detached_staged_proof_payload.get("runbook_validation")
            or {}
        ).get("h48_gendata_workbatch")
        == 256
        and len(
            (
                h48_fasttarget_nonaws_detached_staged_proof_payload.get(
                    "runbook_validation"
                )
                or {}
            ).get("plan_checks")
            or []
        )
        == 2
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get(
            "underlying_remote_artifact", ""
        ).startswith("results/processed/h48_fasttarget_remote_run_")
        and h48_fasttarget_nonaws_detached_staged_proof_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_nonaws_detached_staged_proof_split_bundle_planned": bool(
            h48_fasttarget_nonaws_detached_staged_proof_split_payload
        )
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
            "execution_provider"
        )
        == "generic_ssh_non_aws"
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
            "aws_usage_allowed"
        )
        is False
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
            "remote_action"
        )
        == "detached-staged-proof"
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
            "prerequisite_bundle_mode"
        )
        == "split"
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get("execute")
        is False
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get("solver")
        == "h48h10"
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get("profile")
        == profile
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get("seed")
        == seed
        and (
            h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
                "aws_command_scan"
            )
            or {}
        ).get("passed")
        is True
        and (
            h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
                "runbook_validation"
            )
            or {}
        ).get("passed")
        is True
        and [
            row.get("id")
            for row in h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
                "rows", []
            )
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_status",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "remote_start_prerequisites_detached",
            "remote_wait_prerequisites",
            "remote_start_full_detached",
            "remote_wait_full",
            "fetch_results_archive",
            "fetch_prerequisite_table_parts",
            "fetch_processed_artifacts",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and any(
            "collect_prerequisite_table_parts.sh" in str(row.get("shell_command", ""))
            and "collect_prerequisite_tables.sh"
            not in str(row.get("shell_command", ""))
            for row in h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
                "rows", []
            )
            if row.get("id") == "remote_start_prerequisites_detached"
        )
        and any(
            "cloud_hardtail_prerequisite_tables_"
            in str(row.get("shell_command", ""))
            and "_parts/" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
                "rows", []
            )
            if row.get("id") == "fetch_prerequisite_table_parts"
        )
        and h48_fasttarget_nonaws_detached_staged_proof_split_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_nonaws_proof_package_validated": bool(
            h48_fasttarget_nonaws_proof_package_payload
        )
        and h48_fasttarget_nonaws_proof_package_payload.get("artifact_kind")
        == "h48_fasttarget_nonaws_proof_package"
        and h48_fasttarget_nonaws_proof_package_payload.get("execution_provider")
        == "generic_ssh_non_aws"
        and h48_fasttarget_nonaws_proof_package_payload.get("aws_usage_allowed")
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get("profile") == profile
        and h48_fasttarget_nonaws_proof_package_payload.get("seed") == seed
        and h48_fasttarget_nonaws_proof_package_payload.get("solver") == "h48h10"
        and h48_fasttarget_nonaws_proof_package_payload.get("prerequisite_bundle_mode")
        == "split"
        and h48_fasttarget_nonaws_proof_package_payload.get("package_mode") == "planning"
        and h48_fasttarget_nonaws_proof_package_payload.get("live_preflight_required")
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_required")
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get(
            "preflight_is_live_runtime_evidence"
        )
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get(
            "proof_volume_report_launchable"
        )
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get("launchable_for_execution")
        is False
        and h48_fasttarget_nonaws_proof_package_payload.get("readiness_classification")
        == "planning_nonaws_proof_package"
        and h48_fasttarget_nonaws_proof_package_payload.get("passed") is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("aws_command_scan") or {}
        ).get("passed")
        is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("runbook_validation") or {}
        ).get("passed")
        is True
        and all(
            value is True
            for value in (h48_fasttarget_nonaws_proof_package_payload.get("checks") or {}).values()
        )
        and h48_fasttarget_nonaws_proof_package_payload.get("planned_step_ids")
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_status",
            "remote_bootstrap_cloud_machine",
            "remote_preflight_leader",
            "remote_start_prerequisites_detached",
            "remote_wait_prerequisites",
            "remote_start_full_detached",
            "remote_wait_full",
            "fetch_results_archive",
            "fetch_prerequisite_table_parts",
            "fetch_processed_artifacts",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("full_plan_summary") or {}
        ).get("required_workload_count")
        == 8
        and "stronger_table_h48h10"
        in (
            (
                h48_fasttarget_nonaws_proof_package_payload.get("full_plan_summary")
                or {}
            ).get("required_workload_ids")
            or []
        )
        and bool(h48_fasttarget_nonaws_proof_package_payload.get("package_sha256"))
        and len(h48_fasttarget_nonaws_proof_package_payload.get("component_fingerprints") or [])
        > 10
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("assumed_preflight_summary")
            or {}
        ).get("assumed_machine_not_runtime_evidence")
        is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("assumed_preflight_summary")
            or {}
        ).get("live_runtime_evidence")
        is False
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("assumed_preflight_summary")
            or {}
        ).get("preflight_requirement_satisfied")
        is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_summary")
            or {}
        ).get("present")
        is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_summary")
            or {}
        ).get("proof_volume_report_required")
        is False
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_summary")
            or {}
        ).get("proof_volume_requirement_satisfied")
        is True
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_summary")
            or {}
        ).get("launchable_for_h48_generation")
        is False
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("proof_volume_report_summary")
            or {}
        ).get("launchable_candidate_count")
        == 0
        and (
            h48_fasttarget_nonaws_proof_package_payload.get("contract_gap_summary") or {}
        ).get("fast_runtime_proven_for_every_possible_state")
        is False
        and "--execute"
        in (
            (
                h48_fasttarget_nonaws_proof_package_payload.get("operator_commands")
                or {}
            ).get("generic_ssh_detached_staged_split_proof")
            or ""
        )
        and h48_fasttarget_nonaws_proof_package_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_start_full_dryrun_planned": bool(
            h48_fasttarget_remote_start_full_payload
        )
        and h48_fasttarget_remote_start_full_payload.get("remote_action") == "start-full"
        and h48_fasttarget_remote_start_full_payload.get("execute") is False
        and h48_fasttarget_remote_start_full_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_start_full_payload.get("profile") == profile
        and h48_fasttarget_remote_start_full_payload.get("seed") == seed
        and h48_fasttarget_remote_start_full_payload.get("step_count") == 5
        and [
            row.get("id")
            for row in h48_fasttarget_remote_start_full_payload.get("rows", [])
        ]
        == [
            "remote_prepare",
            "sync_repo_to_remote",
            "remote_bootstrap_cloud_machine",
            "remote_start_full_detached",
            "fetch_processed_artifacts",
        ]
        and any(
            row.get("detached") is True
            and "start_full" in str(row.get("shell_command", ""))
            and "run_canary_after_prerequisites" in str(row.get("shell_command", ""))
            and "collect_results" in str(row.get("shell_command", ""))
            for row in h48_fasttarget_remote_start_full_payload.get("rows", [])
            if row.get("id") == "remote_start_full_detached"
        )
        and h48_fasttarget_remote_start_full_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
        "h48_fasttarget_remote_wait_full_dryrun_planned": bool(
            h48_fasttarget_remote_wait_full_payload
        )
        and h48_fasttarget_remote_wait_full_payload.get("remote_action") == "wait-full"
        and h48_fasttarget_remote_wait_full_payload.get("execute") is False
        and h48_fasttarget_remote_wait_full_payload.get("solver") == "h48h10"
        and h48_fasttarget_remote_wait_full_payload.get("profile") == profile
        and h48_fasttarget_remote_wait_full_payload.get("seed") == seed
        and h48_fasttarget_remote_wait_full_payload.get("step_count") == 6
        and [
            row.get("id")
            for row in h48_fasttarget_remote_wait_full_payload.get("rows", [])
        ]
        == [
            "remote_wait_full",
            "fetch_results_archive",
            "fetch_processed_artifacts",
            "validate_results_archive",
            "unpack_results_archive",
            "finalize_after_collect",
        ]
        and any(
            all(
                token in str(row.get("shell_command", ""))
                for token in [
                    "full_wait_timeout_seconds",
                    "full_poll_interval_seconds",
                    "ready_for_finalize",
                    "start_full",
                    "cloud_hardtail_artifacts_",
                ]
            )
            for row in h48_fasttarget_remote_wait_full_payload.get("rows", [])
            if row.get("id") == "remote_wait_full"
        )
        and h48_fasttarget_remote_wait_full_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False,
    }

    empirical_checks = {
        "stress_all_exact": bool(evidence["stress"])
        and evidence["stress"]["payload"].get("all_exact") is True
        and len(stress_rows) >= 15
        and _rows_all_exact(stress_rows),
        "resident_certification_all_exact": bool(evidence["resident_certification"])
        and evidence["resident_certification"]["payload"].get("all_exact") is True
        and evidence["resident_certification"]["payload"].get("all_hard_cases_exact") is True
        and _rows_all_exact(resident_cert_rows),
        "streaming_cli_all_exact": bool(evidence["streaming_cli"])
        and evidence["streaming_cli"]["payload"].get("all_exact") is True
        and evidence["streaming_cli"]["payload"].get("all_verified") is True
        and _rows_all_exact(streaming_rows),
        "resident_speedup_at_least_10x": bool(resident_speed_payload)
        and float(resident_speed_payload.get("resident_speedup", 0.0) or 0.0) >= 10.0,
        "trusted_no_preload_hard_certification_all_exact": bool(trusted_no_preload_payload)
        and trusted_no_preload_payload.get("all_exact") is True
        and trusted_no_preload_payload.get("within_runtime_target") is True,
        "fast_optimal_oracle_api_all_exact": bool(api_payload)
        and api_payload.get("api_class") == "FastOptimalOracle"
        and api_payload.get("solver") == solver
        and api_payload.get("trusted_table") is True
        and api_payload.get("passed") is True
        and api_payload.get("all_exact") is True
        and api_payload.get("all_verified") is True
        and api_payload.get("all_under_runtime_target") is True
        and api_payload.get("fast_optimal_oracle_implemented_for_every_valid_3x3_state") is True
        and len(api_rows) >= 4
        and _rows_all_exact(api_rows),
        "external_nissy_optimal_thesis_all_exact": bool(nissy_optimal_thesis_payload)
        and nissy_optimal_thesis_payload.get("backend") == "nissy-optimal"
        and nissy_optimal_thesis_payload.get("all_exact") is True
        and len(nissy_optimal_thesis_rows) >= 4
        and _rows_all_exact(nissy_optimal_thesis_rows),
        "external_nissy_core_direct_thesis_all_exact": bool(nissy_core_direct_payload)
        and nissy_core_direct_payload.get("backend") == "nissy-core-direct"
        and nissy_core_direct_payload.get("h48_solver") == solver
        and nissy_core_direct_payload.get("all_exact") is True
        and len(nissy_core_direct_rows) >= 4
        and all("input_mode=cube_state" in str(row.get("notes", "")) for row in nissy_core_direct_rows)
        and _rows_all_exact(nissy_core_direct_rows),
        "external_nissy_core_resident_mmap_h48_table_all_exact": bool(
            nissy_core_resident_mmap_payload
        )
        and nissy_core_resident_mmap_payload.get("profile") == profile
        and nissy_core_resident_mmap_payload.get("solver") == solver
        and nissy_core_resident_mmap_payload.get("passed") is True
        and nissy_core_resident_mmap_payload.get("all_exact") is True
        and nissy_core_resident_mmap_payload.get("all_verified") is True
        and nissy_core_resident_mmap_payload.get("all_expected_distances_match") is True
        and nissy_core_resident_mmap_payload.get("all_used_resident_mmap") is True
        and nissy_core_resident_mmap_payload.get("shell_fallback_disabled_by_missing_binary") is True
        and nissy_core_resident_mmap_payload.get("source_sequences_provided_to_solver") is False
        and nissy_core_resident_mmap_payload.get("table_data_modes") == ["mmap"]
        and nissy_core_resident_mmap_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and len(nissy_core_resident_mmap_rows) >= 2
        and all(
            row.get("solver") == f"nissy_core_python_resident_{solver}"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("table_data_mode") == "mmap"
            and row.get("solve_buffer_available") == "True"
            and row.get("used_resident_mmap") is True
            and row.get("source_sequence_provided_to_solver") is False
            for row in nissy_core_resident_mmap_rows
        ),
        "external_nissy_optimal_stress_depth20_exact": bool(nissy_optimal_stress_payload)
        and nissy_optimal_stress_payload.get("backend") == "nissy-optimal"
        and nissy_optimal_stress_payload.get("all_exact") is True
        and len(nissy_optimal_stress_rows) >= 5
        and any(
            row.get("case_id") == "random_3_20"
            and row.get("status") == "exact"
            and row.get("solution_length") == 17
            and row.get("verified") is True
            for row in nissy_optimal_stress_rows
        )
        and _rows_all_exact(nissy_optimal_stress_rows),
        "portfolio_nissy_first_corpus_all_exact": bool(portfolio_nissy_payload)
        and portfolio_nissy_payload.get("passed") is True
        and portfolio_nissy_payload.get("all_exact") is True
        and any(str(backend).startswith("nissy-optimal") for backend in portfolio_nissy_payload.get("selected_backends", []))
        and len(portfolio_nissy_rows) >= 5
        and any(
            row.get("case_id") == "random_3_20"
            and str(row.get("selected_backend", "")).startswith("nissy-optimal")
            and row.get("status") == "exact"
            and row.get("solution_length") == 17
            and row.get("verified") is True
            for row in portfolio_nissy_rows
        )
        and _rows_all_exact(portfolio_nissy_rows),
        "portfolio_nissy_state_recovery_all_exact": bool(portfolio_state_recovery_payload)
        and portfolio_state_recovery_payload.get("passed") is True
        and portfolio_state_recovery_payload.get("state_input_only") is True
        and portfolio_state_recovery_payload.get("certificate_cache_enabled") is False
        and portfolio_state_recovery_payload.get("upper_lower_certificate_enabled") is False
        and portfolio_state_recovery_payload.get("all_exact") is True
        and any(
            str(backend).startswith("nissy-optimal")
            for backend in portfolio_state_recovery_payload.get("selected_backends", [])
        )
        and len(portfolio_state_recovery_rows) >= 5
        and any(
            row.get("case_id") == "random_3_20"
            and str(row.get("selected_backend", "")).startswith("nissy-optimal")
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("status") == "exact"
            and row.get("solution_length") == 17
            and row.get("verified") is True
            and "scramble_source=inverse_verified_kociemba_solution" in str(row.get("notes", ""))
            for row in portfolio_state_recovery_rows
        )
        and _rows_all_exact(portfolio_state_recovery_rows),
        "portfolio_nissy_core_direct_state_all_exact": bool(portfolio_nissy_core_direct_state_payload)
        and portfolio_nissy_core_direct_state_payload.get("passed") is True
        and portfolio_nissy_core_direct_state_payload.get("state_input_only") is True
        and portfolio_nissy_core_direct_state_payload.get("certificate_cache_enabled") is False
        and portfolio_nissy_core_direct_state_payload.get("upper_lower_certificate_enabled") is False
        and portfolio_nissy_core_direct_state_payload.get("nissy_core_direct_first") is True
        and portfolio_nissy_core_direct_state_payload.get("all_exact") is True
        and "nissy-core-direct" in set(portfolio_nissy_core_direct_state_payload.get("selected_backends", []))
        and len(portfolio_nissy_core_direct_state_rows) >= 2
        and all(
            row.get("selected_backend") == "nissy-core-direct"
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "input_mode=cube_state" in str(row.get("notes", ""))
            and "table_symlink=true" in str(row.get("notes", ""))
            and "nissy_core_direct_invoked=true" in str(row.get("notes", ""))
            and "nissy_optimal_batch_invoked=false" in str(row.get("notes", ""))
            for row in portfolio_nissy_core_direct_state_rows
        )
        and _rows_all_exact(portfolio_nissy_core_direct_state_rows),
        "portfolio_superflip_h48_fallback_exact": bool(portfolio_superflip_payload)
        and portfolio_superflip_payload.get("passed") is True
        and portfolio_superflip_payload.get("all_exact") is True
        and portfolio_superflip_payload.get("case_ids") == ["superflip_distance_20"]
        and "resident-h48" in set(portfolio_superflip_payload.get("selected_backends", []))
        and any(
            row.get("case_id") == "superflip_distance_20"
            and row.get("selected_backend") == "resident-h48"
            and row.get("status") == "exact"
            and row.get("solution_length") == 20
            and row.get("verified") is True
            for row in portfolio_superflip_rows
        )
        and _rows_all_exact(portfolio_superflip_rows),
        "portfolio_superflip_certificate_cache_exact": bool(portfolio_cache_payload)
        and portfolio_cache_payload.get("passed") is True
        and portfolio_cache_payload.get("all_exact") is True
        and portfolio_cache_payload.get("case_ids") == ["superflip_distance_20"]
        and "exact-certificate-cache" in set(portfolio_cache_payload.get("selected_backends", []))
        and any(
            row.get("case_id") == "superflip_distance_20"
            and row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "exact"
            and row.get("solution_length") == 20
            and row.get("verified") is True
            for row in portfolio_cache_rows
        )
        and _rows_all_exact(portfolio_cache_rows),
        "race_optimal_oracle_lowload_exact": bool(race_payload)
        and race_payload.get("profile") == profile
        and race_payload.get("solver") == solver
        and race_payload.get("passed") is True
        and race_payload.get("all_exact") is True
        and race_payload.get("all_verified") is True
        and len(race_rows) >= 1
        and any(
            row.get("case_id") == "shallow_r_u_f2"
            and row.get("selected_backend") == "nissy-optimal"
            and row.get("started_backends") == "native-h48,nissy-optimal"
            and row.get("killed_backends") == "native-h48"
            and row.get("status") == "exact"
            and row.get("solution_length") == 3
            and row.get("verified") is True
            for row in race_rows
        )
        and _rows_all_exact(race_rows),
        "race_nissy_core_direct_lowload_exact": bool(race_nissy_core_payload)
        and race_nissy_core_payload.get("profile") == profile
        and race_nissy_core_payload.get("solver") == solver
        and race_nissy_core_payload.get("trusted_table") is True
        and race_nissy_core_payload.get("h48_enabled") is False
        and race_nissy_core_payload.get("nissy_core_direct_enabled") is True
        and race_nissy_core_payload.get("passed") is True
        and race_nissy_core_payload.get("all_exact") is True
        and race_nissy_core_payload.get("all_verified") is True
        and any(
            row.get("selected_backend") == "nissy-core-direct"
            and row.get("started_backends") == "nissy-core-direct"
            and row.get("killed_backends") == "none"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "input_mode=cube_state" in str(row.get("notes", ""))
            and "table_symlink=true" in str(row.get("notes", ""))
            for row in race_nissy_core_rows
        )
        and _rows_all_exact(race_nissy_core_rows),
        "resident_race_optimal_oracle_lowload_exact": bool(resident_race_payload)
        and resident_race_payload.get("profile") == profile
        and resident_race_payload.get("solver") == solver
        and resident_race_payload.get("trusted_table") is True
        and resident_race_payload.get("passed") is True
        and resident_race_payload.get("all_exact") is True
        and resident_race_payload.get("all_verified") is True
        and len(resident_race_rows) >= 3
        and any(
            row.get("mode") == "resident_race"
            and row.get("case_id") == "shallow_r_u_f2"
            and row.get("started_backends") == "resident-h48,nissy-optimal"
            and row.get("selected_backend") in {"nissy-optimal", "resident-h48"}
            and row.get("status") == "exact"
            and row.get("solution_length") == 3
            and row.get("verified") is True
            for row in resident_race_rows
        )
        and sum(
            1
            for row in resident_race_rows
            if row.get("mode") == "resident_h48_reuse"
            and row.get("selected_backend") == "resident-h48"
            and row.get("started_backends") == "resident-h48"
            and row.get("status") == "exact"
            and row.get("solution_length") == 3
            and row.get("verified") is True
        )
        >= 2
        and _rows_all_exact(resident_race_rows),
        "resident_race_nissy_core_direct_lowload_exact": bool(resident_race_nissy_core_payload)
        and resident_race_nissy_core_payload.get("profile") == profile
        and resident_race_nissy_core_payload.get("solver") == solver
        and resident_race_nissy_core_payload.get("trusted_table") is True
        and resident_race_nissy_core_payload.get("nissy_core_direct_enabled") is True
        and float(resident_race_nissy_core_payload.get("h48_start_delay_seconds", 0.0) or 0.0) > 0.0
        and resident_race_nissy_core_payload.get("passed") is True
        and resident_race_nissy_core_payload.get("all_exact") is True
        and resident_race_nissy_core_payload.get("all_verified") is True
        and any(
            row.get("mode") == "resident_race"
            and row.get("selected_backend") in {"nissy-core-direct", "nissy-core-direct-resident"}
            and row.get("started_backends") in {"nissy-core-direct", "nissy-core-direct-resident"}
            and row.get("stopped_backends") == "resident-h48-deferred"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "input_mode=cube_state" in str(row.get("notes", ""))
            and (
                "table_symlink=true" in str(row.get("notes", ""))
                or (
                    "nissy-core-direct-resident" in str(row.get("notes", ""))
                    and "table_loaded_once=true" in str(row.get("notes", ""))
                )
            )
            for row in resident_race_nissy_core_rows
        )
        and _rows_all_exact(resident_race_nissy_core_rows),
        "universal_optimal_oracle_lowload_exact": bool(universal_payload)
        and universal_payload.get("profile") == profile
        and universal_payload.get("solver") == solver
        and universal_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_payload.get("trusted_table") is True
        and universal_payload.get("passed") is True
        and universal_payload.get("all_exact") is True
        and universal_payload.get("all_verified") is True
        and universal_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and len(universal_rows) >= 3
        and {"solved_fast_path", "exact-certificate-cache", "resident-race"}.issubset(
            set(universal_payload.get("selected_backends", []))
        )
        and any(
            row.get("case_id") == "solved"
            and row.get("selected_backend") == "solved_fast_path"
            and row.get("status") == "exact"
            and row.get("solution_length") == 0
            and row.get("verified") is True
            for row in universal_rows
        )
        and any(
            row.get("case_id") == "superflip_distance_20"
            and row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "exact"
            and row.get("solution_length") == 20
            and row.get("verified") is True
            for row in universal_rows
        )
        and any(
            row.get("case_id") == "shallow_r_u_f2"
            and row.get("selected_backend") == "resident-race"
            and row.get("status") == "exact"
            and row.get("solution_length") == 3
            and row.get("verified") is True
            for row in universal_rows
        )
        and _rows_all_exact(universal_rows),
        "universal_nissy_core_direct_lowload_exact": bool(universal_nissy_core_payload)
        and universal_nissy_core_payload.get("profile") == profile
        and universal_nissy_core_payload.get("solver") == solver
        and universal_nissy_core_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_nissy_core_payload.get("trusted_table") is True
        and universal_nissy_core_payload.get("state_input_only") is True
        and universal_nissy_core_payload.get("passed") is True
        and universal_nissy_core_payload.get("all_exact") is True
        and universal_nissy_core_payload.get("all_verified") is True
        and universal_nissy_core_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and universal_nissy_core_payload.get("direct_nissy_core_rows") == len(universal_nissy_core_rows)
        and len(universal_nissy_core_rows) >= 1
        and "resident-race" in set(universal_nissy_core_payload.get("selected_backends", []))
        and "nissy-core-direct" in set(universal_nissy_core_payload.get("nested_selected_backends", []))
        and all(
            row.get("selected_backend") == "resident-race"
            and row.get("direct_nissy_core_used") is True
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("started_backends") == "nissy-core-direct"
            and row.get("stopped_backends") == "resident-h48-deferred"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "input_mode=cube_state" in str(row.get("notes", ""))
            and "table_symlink=true" in str(row.get("notes", ""))
            for row in universal_nissy_core_rows
        )
        and _rows_all_exact(universal_nissy_core_rows),
        "universal_rubikoptimal_race_lowload_exact": bool(universal_rubikoptimal_race_payload)
        and universal_rubikoptimal_race_payload.get("profile") == profile
        and universal_rubikoptimal_race_payload.get("solver") == solver
        and universal_rubikoptimal_race_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_rubikoptimal_race_payload.get("trusted_table") is True
        and universal_rubikoptimal_race_payload.get("state_input_only") is True
        and universal_rubikoptimal_race_payload.get("include_h48") is False
        and universal_rubikoptimal_race_payload.get("include_nissy") is False
        and universal_rubikoptimal_race_payload.get("rubikoptimal_race_timeout_seconds") is not None
        and universal_rubikoptimal_race_payload.get("passed") is True
        and universal_rubikoptimal_race_payload.get("all_exact") is True
        and universal_rubikoptimal_race_payload.get("all_verified") is True
        and universal_rubikoptimal_race_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and len(universal_rubikoptimal_race_rows) >= 1
        and "rubikoptimal-race" in set(universal_rubikoptimal_race_payload.get("selected_backends", []))
        and all(
            row.get("selected_backend") == "rubikoptimal-race"
            and row.get("backend_solver") == "resident_race_optimal_oracle"
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("started_backends") == "rubikoptimal-race"
            and row.get("stopped_backends") == "none"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "rubikoptimal_external" in set(row.get("nested_backend_solvers", []))
            and "resident race backend=rubikoptimal-race" in str(row.get("notes", ""))
            and "selected_backend=rubikoptimal_resident" in str(row.get("notes", ""))
            and "backend_solver=rubikoptimal_external" in str(row.get("notes", ""))
            for row in universal_rubikoptimal_race_rows
        )
        and _rows_all_exact(universal_rubikoptimal_race_rows),
        "rubikoptimal_resident_oracle_lowload_exact": bool(rubikoptimal_resident_payload)
        and rubikoptimal_resident_payload.get("profile") == profile
        and rubikoptimal_resident_payload.get("seed") == seed
        and rubikoptimal_resident_payload.get("api")
        == "rubik_optimal.solvers.rubikoptimal_external.RubikOptimalOracleSession.solve"
        and rubikoptimal_resident_payload.get("passed") is True
        and rubikoptimal_resident_payload.get("all_exact") is True
        and rubikoptimal_resident_payload.get("all_verified") is True
        and rubikoptimal_resident_payload.get("all_resident_backend") is True
        and rubikoptimal_resident_payload.get("rubikoptimal_table_complete") is True
        and rubikoptimal_resident_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and rubikoptimal_resident_payload.get("resident_start_count") == 1
        and rubikoptimal_resident_payload.get("resident_process_reused_rows", 0) >= 1
        and len(rubikoptimal_resident_rows) >= 2
        and all(
            row.get("selected_backend") == "rubikoptimal_resident"
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "selected_backend=rubikoptimal_resident" in str(row.get("notes", ""))
            for row in rubikoptimal_resident_rows
        )
        and _rows_all_exact(rubikoptimal_resident_rows),
        "rubikoptimal_oracle_stream_lowload_exact": bool(rubikoptimal_stream_payload)
        and rubikoptimal_stream_payload.get("profile") == profile
        and rubikoptimal_stream_payload.get("seed") == seed
        and rubikoptimal_stream_payload.get("public_interface")
        == "rubik-optimal oracle --stream --rubikoptimal"
        and rubikoptimal_stream_payload.get("passed") is True
        and rubikoptimal_stream_payload.get("all_exact") is True
        and rubikoptimal_stream_payload.get("all_verified") is True
        and rubikoptimal_stream_payload.get("all_state_input_only") is True
        and rubikoptimal_stream_payload.get("all_rubikoptimal_resident") is True
        and rubikoptimal_stream_payload.get("rubikoptimal_table_complete") is True
        and rubikoptimal_stream_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and rubikoptimal_stream_payload.get("resident_reused_rows", 0) >= 1
        and len(rubikoptimal_stream_rows) >= 3
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend") == "rubikoptimal_resident"
            and row.get("backend_solver") == "rubikoptimal_external"
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("expected_distance_matches") is True
            and "selected_backend=rubikoptimal_resident" in str(row.get("notes", ""))
            for row in rubikoptimal_stream_rows
        )
        and _rows_all_exact(rubikoptimal_stream_rows),
        "universal_h48_symmetry_lowload_exact": bool(universal_h48_symmetry_payload)
        and universal_h48_symmetry_payload.get("profile") == profile
        and universal_h48_symmetry_payload.get("solver") == solver
        and universal_h48_symmetry_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_h48_symmetry_payload.get("trusted_table") is True
        and universal_h48_symmetry_payload.get("state_input_only") is True
        and universal_h48_symmetry_payload.get("passed") is True
        and universal_h48_symmetry_payload.get("all_exact") is True
        and universal_h48_symmetry_payload.get("all_verified") is True
        and universal_h48_symmetry_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and universal_h48_symmetry_payload.get("resident_h48_symmetry_variants") == 2
        and "resident-h48-symmetry-batch" in set(universal_h48_symmetry_payload.get("selected_backends", []))
        and len(universal_h48_symmetry_rows) >= 1
        and all(
            row.get("selected_backend") == "resident-h48-symmetry-batch"
            and row.get("backend_solver") == f"fast_optimal_oracle_{solver}_symmetry_batch"
            and row.get("resident_h48_symmetry_used") is True
            and row.get("selected_rotation")
            and row.get("source_sequence_provided_to_solver") is False
            and row.get("status") == "exact"
            and row.get("verified") is True
            and "rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
            for row in universal_h48_symmetry_rows
        )
        and _rows_all_exact(universal_h48_symmetry_rows),
        "universal_batch_oracle_corpus_lowload_exact": bool(universal_batch_payload)
        and universal_batch_payload.get("profile") == profile
        and universal_batch_payload.get("solver") == solver
        and universal_batch_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_batch_payload.get("trusted_table") is True
        and universal_batch_payload.get("state_input_only") is True
        and universal_batch_payload.get("passed") is True
        and universal_batch_payload.get("all_exact") is True
        and universal_batch_payload.get("all_verified") is True
        and universal_batch_payload.get("all_universal_portfolio_batch") is True
        and len(universal_batch_rows) >= 3
        and all(
            row.get("selected_backend") == "portfolio-batch"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is False
            for row in universal_batch_rows
        ),
        "universal_resident_h48_batch_lowload_exact": bool(universal_resident_h48_batch_payload)
        and universal_resident_h48_batch_payload.get("profile") == profile
        and universal_resident_h48_batch_payload.get("solver") == solver
        and universal_resident_h48_batch_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_resident_h48_batch_payload.get("trusted_table") is True
        and universal_resident_h48_batch_payload.get("state_input_only") is True
        and universal_resident_h48_batch_payload.get("resident_h48_batch") is True
        and universal_resident_h48_batch_payload.get("passed") is True
        and universal_resident_h48_batch_payload.get("all_exact") is True
        and universal_resident_h48_batch_payload.get("all_verified") is True
        and universal_resident_h48_batch_payload.get("all_universal_resident_h48_batch") is True
        and len(universal_resident_h48_batch_rows) >= 3
        and all(
            row.get("selected_backend") == "resident-h48-batch"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is False
            and "resident_native_h48=true" in str(row.get("notes", ""))
            and "table_loaded_once=true" in str(row.get("notes", ""))
            and "input_mode=cube_state" in str(row.get("notes", ""))
            for row in universal_resident_h48_batch_rows
        ),
        "universal_oracle_cli_optimized_lowload_exact": bool(universal_oracle_cli_payload)
        and universal_oracle_cli_payload.get("profile") == profile
        and universal_oracle_cli_payload.get("solver") == solver
        and universal_oracle_cli_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_payload.get("trusted_table") is True
        and universal_oracle_cli_payload.get("passed") is True
        and universal_oracle_cli_payload.get("all_exact") is True
        and universal_oracle_cli_payload.get("all_verified") is True
        and universal_oracle_cli_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_payload.get("all_state_input_only") is True
        and int(universal_oracle_cli_payload.get("resident_h48_batch_rows", 0)) >= 1
        and len(universal_oracle_cli_rows) >= 3
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend")
            in {
                "upper-lower-certificate",
                "exact-certificate-cache",
                "resident-h48-batch",
                "portfolio-after-resident-h48-fallback",
                "solved_fast_path",
            }
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_rows
        ),
        "universal_oracle_cli_broader_lowload_exact": bool(universal_oracle_cli_broader_payload)
        and universal_oracle_cli_broader_payload.get("profile") == profile
        and universal_oracle_cli_broader_payload.get("solver") == solver
        and universal_oracle_cli_broader_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_broader_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_broader_payload.get("trusted_table") is True
        and universal_oracle_cli_broader_payload.get("passed") is True
        and universal_oracle_cli_broader_payload.get("all_exact") is True
        and universal_oracle_cli_broader_payload.get("all_verified") is True
        and universal_oracle_cli_broader_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_broader_payload.get("all_state_input_only") is True
        and int(universal_oracle_cli_broader_payload.get("resident_h48_batch_rows", 0)) >= 1
        and int(universal_oracle_cli_broader_payload.get("resident_h48_fallback_rows", 0)) >= 1
        and len(universal_oracle_cli_broader_rows) >= 5
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend")
            in {
                "upper-lower-certificate",
                "exact-certificate-cache",
                "resident-h48-batch",
                "portfolio-after-resident-h48-fallback",
                "solved_fast_path",
            }
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_broader_rows
        ),
        "universal_oracle_cli_adaptive_lowload_exact": bool(universal_oracle_cli_adaptive_payload)
        and universal_oracle_cli_adaptive_payload.get("profile") == profile
        and universal_oracle_cli_adaptive_payload.get("solver") == solver
        and universal_oracle_cli_adaptive_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_adaptive_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_adaptive_payload.get("trusted_table") is True
        and universal_oracle_cli_adaptive_payload.get("passed") is True
        and universal_oracle_cli_adaptive_payload.get("all_exact") is True
        and universal_oracle_cli_adaptive_payload.get("all_verified") is True
        and universal_oracle_cli_adaptive_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_adaptive_payload.get("all_state_input_only") is True
        and universal_oracle_cli_adaptive_payload.get("try_portfolio_batch_before_resident_h48_batch") is True
        and int(universal_oracle_cli_adaptive_payload.get("portfolio_prepass_rows", 0)) >= 1
        and len(universal_oracle_cli_adaptive_rows) >= 5
        and (
            not universal_oracle_cli_broader_payload
            or float(universal_oracle_cli_adaptive_payload.get("max_runtime_seconds", 10**9))
            < float(universal_oracle_cli_broader_payload.get("max_runtime_seconds", 0))
        )
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend")
            in {
                "upper-lower-certificate",
                "exact-certificate-cache",
                "portfolio-before-resident-h48-batch",
                "resident-h48-batch",
                "resident-h48-batch-after-portfolio-prepass",
                "portfolio-after-resident-h48-fallback",
                "portfolio-after-resident-h48-fallback-after-prepass",
                "solved_fast_path",
            }
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_adaptive_rows
        ),
        "universal_oracle_cli_expanded_adaptive_lowload_exact": bool(universal_oracle_cli_expanded_payload)
        and universal_oracle_cli_expanded_payload.get("profile") == profile
        and universal_oracle_cli_expanded_payload.get("solver") == solver
        and universal_oracle_cli_expanded_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_expanded_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_expanded_payload.get("trusted_table") is True
        and universal_oracle_cli_expanded_payload.get("passed") is True
        and universal_oracle_cli_expanded_payload.get("all_exact") is True
        and universal_oracle_cli_expanded_payload.get("all_verified") is True
        and universal_oracle_cli_expanded_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_expanded_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_expanded_payload.get("all_state_input_only") is True
        and universal_oracle_cli_expanded_payload.get("try_portfolio_batch_before_resident_h48_batch") is True
        and universal_oracle_cli_expanded_payload.get("include_hard") is True
        and universal_oracle_cli_expanded_payload.get("contains_superflip") is True
        and int(universal_oracle_cli_expanded_payload.get("hard_case_count", 0)) >= 2
        and int(universal_oracle_cli_expanded_payload.get("expected_distance_checked_count", 0)) >= 1
        and int(universal_oracle_cli_expanded_payload.get("portfolio_prepass_rows", 0)) >= 1
        and len(universal_oracle_cli_expanded_rows) >= 12
        and any(
            row.get("case_id") == "cli_hard_superflip_distance_20"
            and row.get("expected_distance") == 20
            and row.get("solution_length") == 20
            and row.get("selected_backend") == "exact-certificate-cache"
            for row in universal_oracle_cli_expanded_rows
        )
        and all(
            row.get("input_kind") == "facelets"
            and isinstance(row.get("state"), str)
            and row.get("solution") is not None
            and row.get("selected_backend")
            in {
                "upper-lower-certificate",
                "exact-certificate-cache",
                "portfolio-before-resident-h48-batch",
                "resident-h48-batch",
                "resident-h48-batch-after-portfolio-prepass",
                "portfolio-after-resident-h48-fallback",
                "portfolio-after-resident-h48-fallback-after-prepass",
                "solved_fast_path",
            }
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_expanded_rows
        ),
        "universal_oracle_cli_h48_symmetry_lowload_exact": bool(universal_oracle_cli_h48_symmetry_payload)
        and universal_oracle_cli_h48_symmetry_payload.get("profile") == profile
        and universal_oracle_cli_h48_symmetry_payload.get("solver") == solver
        and universal_oracle_cli_h48_symmetry_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_h48_symmetry_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_h48_symmetry_payload.get("trusted_table") is True
        and universal_oracle_cli_h48_symmetry_payload.get("passed") is True
        and universal_oracle_cli_h48_symmetry_payload.get("all_exact") is True
        and universal_oracle_cli_h48_symmetry_payload.get("all_verified") is True
        and universal_oracle_cli_h48_symmetry_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_h48_symmetry_payload.get("all_state_input_only") is True
        and universal_oracle_cli_h48_symmetry_payload.get("resident_h48_symmetry_variants") == 2
        and int(universal_oracle_cli_h48_symmetry_payload.get("resident_h48_symmetry_rows", 0)) >= 1
        and len(universal_oracle_cli_h48_symmetry_rows) >= 1
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend") == "resident-h48-symmetry-batch"
            and row.get("backend_solver") == f"fast_optimal_oracle_{solver}_symmetry_batch"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
            for row in universal_oracle_cli_h48_symmetry_rows
        ),
        "universal_oracle_cli_h48_parallel_symmetry_lowload_exact": bool(
            universal_oracle_cli_h48_parallel_symmetry_payload
        )
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("profile") == profile
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("solver") == solver
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("trusted_table") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("passed") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("all_exact") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("all_verified") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("all_state_input_only") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_h48_parallel_symmetry_payload.get("parallel_h48_symmetry_variants") == 2
        and int(universal_oracle_cli_h48_parallel_symmetry_payload.get("parallel_h48_symmetry_rows", 0))
        >= 1
        and len(universal_oracle_cli_h48_parallel_symmetry_rows) >= 1
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend") == "parallel-h48-symmetry-race"
            and row.get("backend_solver") == f"fast_optimal_oracle_{solver}_parallel_symmetry_race"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "first_rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
            for row in universal_oracle_cli_h48_parallel_symmetry_rows
        ),
        "universal_oracle_cli_rotational_lower_bound_certificate_exact": bool(
            universal_oracle_cli_rotational_lower_bound_payload
        )
        and universal_oracle_cli_rotational_lower_bound_payload.get("solver") == solver
        and universal_oracle_cli_rotational_lower_bound_payload.get("universal_oracle") is True
        and universal_oracle_cli_rotational_lower_bound_payload.get("all_exact") is True
        and universal_oracle_cli_rotational_lower_bound_payload.get("all_verified") is True
        and universal_oracle_cli_rotational_lower_bound_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_rotational_lower_bound_payload.get("try_upper_lower_certificate") is True
        and universal_oracle_cli_rotational_lower_bound_payload.get("h48_lower_bound_symmetry_variants") == 23
        and len(universal_oracle_cli_rotational_lower_bound_rows) >= 1
        and any(
            row.get("selected_backend") == "upper-lower-certificate"
            and row.get("status") == "exact"
            and row.get("solution_length") == 3
            and row.get("verified") is True
            and "rotational admissible lower-bound batch" in str(row.get("notes", ""))
            and "rotation_count=24" in str(row.get("notes", ""))
            for row in universal_oracle_cli_rotational_lower_bound_rows
        )
        and _rows_all_exact(universal_oracle_cli_rotational_lower_bound_rows),
        "universal_oracle_cli_upper_lower_batch_lowload_exact": bool(
            universal_oracle_cli_upper_lower_batch_payload
        )
        and universal_oracle_cli_upper_lower_batch_payload.get("profile") == profile
        and universal_oracle_cli_upper_lower_batch_payload.get("solver") == solver
        and universal_oracle_cli_upper_lower_batch_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_upper_lower_batch_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_upper_lower_batch_payload.get("trusted_table") is True
        and universal_oracle_cli_upper_lower_batch_payload.get("passed") is True
        and universal_oracle_cli_upper_lower_batch_payload.get("all_exact") is True
        and universal_oracle_cli_upper_lower_batch_payload.get("all_verified") is True
        and universal_oracle_cli_upper_lower_batch_payload.get("all_state_input_only") is True
        and universal_oracle_cli_upper_lower_batch_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_upper_lower_batch_payload.get("try_upper_lower_certificate") is True
        and int(universal_oracle_cli_upper_lower_batch_payload.get("universal_upper_lower_batch_rows", 0))
        >= 1
        and int(
            universal_oracle_cli_upper_lower_batch_payload.get(
                "universal_upper_lower_batch_lower_bound_rows", 0
            )
        )
        >= 1
        and len(universal_oracle_cli_upper_lower_batch_rows) >= 1
        and any(
            row.get("selected_backend") == "upper-lower-certificate"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("input_kind") == "facelets"
            and row.get("source_sequence_provided_to_solver") is not True
            and "universal_solve_many_upper_lower_batch=true" in str(row.get("notes", ""))
            and "h48_lower_bound_batch_invoked=true" in str(row.get("notes", ""))
            for row in universal_oracle_cli_upper_lower_batch_rows
        )
        and _rows_all_exact(universal_oracle_cli_upper_lower_batch_rows),
        "universal_oracle_cli_late_nissy_core_direct_fallback_exact": bool(
            universal_oracle_cli_late_nissy_core_payload
        )
        and universal_oracle_cli_late_nissy_core_payload.get("profile") == profile
        and universal_oracle_cli_late_nissy_core_payload.get("solver") == solver
        and universal_oracle_cli_late_nissy_core_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_late_nissy_core_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_late_nissy_core_payload.get("trusted_table") is True
        and universal_oracle_cli_late_nissy_core_payload.get("passed") is True
        and universal_oracle_cli_late_nissy_core_payload.get("all_exact") is True
        and universal_oracle_cli_late_nissy_core_payload.get("all_verified") is True
        and universal_oracle_cli_late_nissy_core_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_late_nissy_core_payload.get("all_state_input_only") is True
        and universal_oracle_cli_late_nissy_core_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_late_nissy_core_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_late_nissy_core_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_late_nissy_core_payload.get("portfolio_fallback_nissy_core_direct_timeout_seconds")
        == 30.0
        and int(universal_oracle_cli_late_nissy_core_payload.get("late_nissy_core_direct_fallback_rows", 0))
        >= 1
        and len(universal_oracle_cli_late_nissy_core_rows) >= 1
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend") == "portfolio-after-resident-h48-fallback"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "resident_h48_batch_initial_status=timeout" in str(row.get("notes", ""))
            and "selected_backend=nissy-core-direct" in str(row.get("notes", ""))
            and "nissy-core direct H48 shell backend" in str(row.get("notes", ""))
            for row in universal_oracle_cli_late_nissy_core_rows
        ),
        "universal_oracle_cli_live_no_shortcuts_lowload_exact": bool(universal_oracle_cli_live_payload)
        and universal_oracle_cli_live_payload.get("profile") == profile
        and universal_oracle_cli_live_payload.get("solver") == solver
        and universal_oracle_cli_live_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_live_payload.get("public_interface") == "rubik-optimal oracle --universal"
        and universal_oracle_cli_live_payload.get("trusted_table") is True
        and universal_oracle_cli_live_payload.get("passed") is True
        and universal_oracle_cli_live_payload.get("all_exact") is True
        and universal_oracle_cli_live_payload.get("all_verified") is True
        and universal_oracle_cli_live_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_live_payload.get("all_state_input_only") is True
        and universal_oracle_cli_live_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_live_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_live_payload.get("live_solver_shortcuts_disabled") is True
        and len(universal_oracle_cli_live_rows) >= 1
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend")
            not in {"exact-certificate-cache", "upper-lower-certificate", "solved_fast_path"}
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_live_rows
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_lowload_exact": bool(
            universal_oracle_cli_live_broader_payload
        )
        and universal_oracle_cli_live_broader_payload.get("profile") == profile
        and universal_oracle_cli_live_broader_payload.get("solver") == solver
        and universal_oracle_cli_live_broader_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_live_broader_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_live_broader_payload.get("trusted_table") is True
        and universal_oracle_cli_live_broader_payload.get("passed") is True
        and universal_oracle_cli_live_broader_payload.get("all_exact") is True
        and universal_oracle_cli_live_broader_payload.get("all_verified") is True
        and universal_oracle_cli_live_broader_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_live_broader_payload.get("all_state_input_only") is True
        and universal_oracle_cli_live_broader_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_live_broader_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_live_broader_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_live_broader_payload.get("preload_table") is True
        and universal_oracle_cli_live_broader_payload.get("try_portfolio_batch_before_resident_h48_batch")
        is False
        and int(universal_oracle_cli_live_broader_payload.get("resident_h48_batch_rows") or 0) >= 5
        and list(universal_oracle_cli_live_broader_payload.get("selected_backends", [])) == ["resident-h48-batch"]
        and list(universal_oracle_cli_live_broader_payload.get("depths", [])) == [5, 10, 15, 20, 25]
        and len(universal_oracle_cli_live_broader_rows) >= 5
        and float(universal_oracle_cli_live_broader_payload.get("max_runtime_seconds", 10**9)) <= 20.0
        and float(universal_oracle_cli_live_broader_payload.get("wrapper_wall_seconds", 10**9)) <= 20.0
        and all(
            row.get("input_kind") == "facelets"
            and row.get("selected_backend")
            not in {"exact-certificate-cache", "upper-lower-certificate", "solved_fast_path"}
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            for row in universal_oracle_cli_live_broader_rows
        ),
        "universal_oracle_cli_known_distance_17_no_shortcuts_lowload_exact": bool(
            universal_oracle_cli_known_distance_payload
        )
        and universal_oracle_cli_known_distance_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_payload.get("passed") is True
        and universal_oracle_cli_known_distance_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_known_distance_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_known_distance_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_payload.get("nissy_benchmark_distances_present") == [17]
        and int(universal_oracle_cli_known_distance_payload.get("resident_h48_batch_rows") or 0) >= 1
        and list(universal_oracle_cli_known_distance_payload.get("selected_backends", [])) == ["resident-h48-batch"]
        and len(universal_oracle_cli_known_distance_rows) >= 1
        and float(universal_oracle_cli_known_distance_payload.get("max_backend_solve_seconds", 10**9))
        <= 120.0
        and all(
            row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") == 17
            and row.get("solution_length") == 17
            and row.get("selected_backend") == "resident-h48-batch"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and float(row.get("backend_solve_seconds") or 10**9) <= 120.0
            for row in universal_oracle_cli_known_distance_rows
        ),
        "universal_oracle_cli_known_distance_17_18_adaptive_lowload_exact": bool(
            universal_oracle_cli_known_distance_adaptive_payload
        )
        and universal_oracle_cli_known_distance_adaptive_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_adaptive_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_adaptive_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_adaptive_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_adaptive_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("passed") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("outer_command_timed_out") is False
        and universal_oracle_cli_known_distance_adaptive_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_known_distance_adaptive_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_adaptive_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_known_distance_adaptive_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_adaptive_payload.get("nissy_benchmark_distances_present")
        == [17, 18]
        and int(universal_oracle_cli_known_distance_adaptive_payload.get("portfolio_prepass_rows") or 0) >= 2
        and list(universal_oracle_cli_known_distance_adaptive_payload.get("selected_backends", []))
        == ["portfolio-before-resident-h48-batch"]
        and float(universal_oracle_cli_known_distance_adaptive_payload.get("max_runtime_seconds", 10**9))
        <= 90.0
        and float(universal_oracle_cli_known_distance_adaptive_payload.get("wrapper_wall_seconds", 10**9))
        <= 90.0
        and float(universal_oracle_cli_known_distance_adaptive_payload.get("command_timeout_seconds", 0))
        >= 600.0
        and len(universal_oracle_cli_known_distance_adaptive_rows) >= 2
        and all(
            row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") in {17, 18}
            and row.get("solution_length") == row.get("expected_distance")
            and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
            and row.get("backend_solver") == "portfolio_optimal_oracle"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
            and "scramble_source=inverse_verified_kociemba_solution" in str(row.get("notes", ""))
            for row in universal_oracle_cli_known_distance_adaptive_rows
        ),
        "universal_oracle_cli_known_distance_19_adaptive_lowload_exact": bool(
            universal_oracle_cli_known_distance_19_payload
        )
        and universal_oracle_cli_known_distance_19_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_19_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_19_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_19_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_19_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_19_payload.get("passed") is True
        and universal_oracle_cli_known_distance_19_payload.get("outer_command_timed_out") is False
        and universal_oracle_cli_known_distance_19_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_19_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_19_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_19_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_19_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_19_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_known_distance_19_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_19_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_known_distance_19_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_19_payload.get("nissy_benchmark_distances_present") == [19]
        and int(universal_oracle_cli_known_distance_19_payload.get("portfolio_prepass_rows") or 0) >= 1
        and list(universal_oracle_cli_known_distance_19_payload.get("selected_backends", []))
        == ["portfolio-before-resident-h48-batch"]
        and float(universal_oracle_cli_known_distance_19_payload.get("max_runtime_seconds", 10**9))
        <= 240.0
        and float(universal_oracle_cli_known_distance_19_payload.get("wrapper_wall_seconds", 10**9))
        <= 240.0
        and float(universal_oracle_cli_known_distance_19_payload.get("max_backend_solve_seconds", 10**9))
        <= 60.0
        and float(universal_oracle_cli_known_distance_19_payload.get("command_timeout_seconds", 0))
        >= 690.0
        and len(universal_oracle_cli_known_distance_19_rows) >= 1
        and all(
            row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") == 19
            and row.get("solution_length") == 19
            and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
            and row.get("backend_solver") == "portfolio_optimal_oracle"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
            and "nissy_status=timeout" in str(row.get("notes", ""))
            and "resident_h48_invoked=true" in str(row.get("notes", ""))
            and float(row.get("backend_solve_seconds") or 10**9) <= 60.0
            for row in universal_oracle_cli_known_distance_19_rows
        ),
        "universal_oracle_cli_known_distance_20_adaptive_lowload_exact": bool(
            universal_oracle_cli_known_distance_20_payload
        )
        and universal_oracle_cli_known_distance_20_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_20_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_20_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_20_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_20_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_20_payload.get("passed") is True
        and universal_oracle_cli_known_distance_20_payload.get("outer_command_timed_out") is False
        and universal_oracle_cli_known_distance_20_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_20_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_20_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_20_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_20_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_20_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_known_distance_20_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_20_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_known_distance_20_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_20_payload.get("nissy_benchmark_distances_present") == [20]
        and int(universal_oracle_cli_known_distance_20_payload.get("portfolio_prepass_rows") or 0) >= 1
        and list(universal_oracle_cli_known_distance_20_payload.get("selected_backends", []))
        == ["portfolio-before-resident-h48-batch"]
        and float(universal_oracle_cli_known_distance_20_payload.get("max_runtime_seconds", 10**9))
        <= 540.0
        and float(universal_oracle_cli_known_distance_20_payload.get("wrapper_wall_seconds", 10**9))
        <= 540.0
        and float(universal_oracle_cli_known_distance_20_payload.get("max_backend_solve_seconds", 10**9))
        <= 240.0
        and float(universal_oracle_cli_known_distance_20_payload.get("command_timeout_seconds", 0))
        >= 1080.0
        and len(universal_oracle_cli_known_distance_20_rows) >= 1
        and all(
            row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") == 20
            and row.get("solution_length") == 20
            and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
            and row.get("backend_solver") == "portfolio_optimal_oracle"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
            and "nissy_status=timeout" in str(row.get("notes", ""))
            and "resident_h48_invoked=true" in str(row.get("notes", ""))
            and float(row.get("backend_solve_seconds") or 10**9) <= 240.0
            for row in universal_oracle_cli_known_distance_20_rows
        ),
        "universal_oracle_cli_known_distance_20_offset1_adaptive_lowload_exact": bool(
            universal_oracle_cli_known_distance_20_offset1_payload
        )
        and universal_oracle_cli_known_distance_20_offset1_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_20_offset1_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_20_offset1_payload.get("api_class")
        == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_20_offset1_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_20_offset1_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("passed") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("outer_command_timed_out") is False
        and universal_oracle_cli_known_distance_20_offset1_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("try_certificate_cache") is False
        and universal_oracle_cli_known_distance_20_offset1_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_20_offset1_payload.get("live_solver_shortcuts_disabled") is True
        and universal_oracle_cli_known_distance_20_offset1_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_20_offset1_payload.get("benchmark_offset_per_distance") == 1
        and universal_oracle_cli_known_distance_20_offset1_payload.get("nissy_benchmark_distances_present")
        == [20]
        and int(universal_oracle_cli_known_distance_20_offset1_payload.get("portfolio_prepass_rows") or 0)
        >= 1
        and list(universal_oracle_cli_known_distance_20_offset1_payload.get("selected_backends", []))
        == ["portfolio-before-resident-h48-batch"]
        and float(universal_oracle_cli_known_distance_20_offset1_payload.get("max_runtime_seconds", 10**9))
        <= 540.0
        and float(universal_oracle_cli_known_distance_20_offset1_payload.get("wrapper_wall_seconds", 10**9))
        <= 540.0
        and float(
            universal_oracle_cli_known_distance_20_offset1_payload.get("max_backend_solve_seconds", 10**9)
        )
        <= 240.0
        and float(universal_oracle_cli_known_distance_20_offset1_payload.get("command_timeout_seconds", 0))
        >= 1080.0
        and len(universal_oracle_cli_known_distance_20_offset1_rows) >= 1
        and all(
            row.get("case_id") == "nissy_benchmark_distance_20_1"
            and row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") == 20
            and row.get("solution_length") == 20
            and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
            and row.get("backend_solver") == "portfolio_optimal_oracle"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
            and "nissy_status=timeout" in str(row.get("notes", ""))
            and "resident_h48_invoked=true" in str(row.get("notes", ""))
            and float(row.get("backend_solve_seconds") or 10**9) <= 240.0
            for row in universal_oracle_cli_known_distance_20_offset1_rows
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_lowload_exact": bool(
            universal_oracle_cli_known_distance_20_offset1_trimmed_payload
        )
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("api_class")
        == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("passed") is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("outer_command_timed_out")
        is False
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("all_exact") is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "all_expected_distances_match"
        )
        is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "all_universal_optimized_cli"
        )
        is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("all_state_input_only")
        is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("try_certificate_cache")
        is False
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "try_upper_lower_certificate"
        )
        is False
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "live_solver_shortcuts_disabled"
        )
        is True
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("random_cases_enabled")
        is False
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "benchmark_offset_per_distance"
        )
        == 1
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "portfolio_prepass_timeout_seconds"
        )
        == 30.0
        and universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
            "nissy_benchmark_distances_present"
        )
        == [20]
        and list(universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get("selected_backends", []))
        == ["resident-h48-batch-after-portfolio-prepass"]
        and float(
            universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                "max_runtime_seconds",
                10**9,
            )
        )
        <= 240.0
        and float(
            universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                "wrapper_wall_seconds",
                10**9,
            )
        )
        <= 240.0
        and float(
            universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                "max_backend_solve_seconds",
                10**9,
            )
        )
        <= 180.0
        and float(
            universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                "command_timeout_seconds",
                0,
            )
        )
        >= 540.0
        and len(universal_oracle_cli_known_distance_20_offset1_trimmed_rows) >= 1
        and all(
            row.get("case_id") == "nissy_benchmark_distance_20_1"
            and row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("expected_distance") == 20
            and row.get("solution_length") == 20
            and row.get("selected_backend") == "resident-h48-batch-after-portfolio-prepass"
            and row.get("backend_solver") == "fast_optimal_oracle_h48h7"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("source_sequence_provided_to_solver") is not True
            and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
            and "nissy_status=timeout" in str(row.get("notes", ""))
            and "timed out after 30.0s" in str(row.get("notes", ""))
            and "h48_fallback_disabled=true" in str(row.get("notes", ""))
            and float(row.get("backend_solve_seconds") or 10**9) <= 180.0
            for row in universal_oracle_cli_known_distance_20_offset1_trimmed_rows
        ),
        "nissy_benchmark_certificates_imported_all_external_label_exact": bool(
            nissy_benchmark_certificates_payload
        )
        and nissy_benchmark_certificates_payload.get("profile") == profile
        and nissy_benchmark_certificates_payload.get("seed") == seed
        and nissy_benchmark_certificates_payload.get("passed") is True
        and nissy_benchmark_certificates_payload.get("distances") == [16, 17, 18, 19, 20]
        and int(nissy_benchmark_certificates_payload.get("row_count", 0) or 0) >= 125
        and len(nissy_benchmark_certificate_rows) >= 125
        and all(
            row.get("status") == "external_label_exact"
            and row.get("exactness_basis") == "third_party_benchmark_label"
            and row.get("verified") is True
            and row.get("selected_backend") == "known-distance-benchmark-certificate"
            and row.get("solution_length") == row.get("expected_distance")
            and row.get("source_sequence_provided_to_solver") is False
            for row in nissy_benchmark_certificate_rows
        ),
        # Honest replay semantics: the 125 known-distance benchmark rows are
        # served from the certificate cache under the explicit external-label
        # opt-in, so they must report status=external_label_exact (optimality
        # rests on the third-party benchmark label, never proven locally) and
        # the strict all_exact flag must stay False.
        "universal_oracle_cli_known_distance_16_20_certificate_cache_external_label_exact": bool(
            universal_oracle_cli_known_distance_certificate_payload
        )
        and universal_oracle_cli_known_distance_certificate_payload.get("profile") == profile
        and universal_oracle_cli_known_distance_certificate_payload.get("solver") == solver
        and universal_oracle_cli_known_distance_certificate_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_oracle_cli_known_distance_certificate_payload.get("public_interface")
        == "rubik-optimal oracle --universal"
        and universal_oracle_cli_known_distance_certificate_payload.get("trusted_table") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("passed") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("outer_command_timed_out") is False
        and universal_oracle_cli_known_distance_certificate_payload.get("all_exact") is False
        and universal_oracle_cli_known_distance_certificate_payload.get("all_exact_or_external_label") is True
        and universal_oracle_cli_known_distance_certificate_payload.get(
            "include_external_label_certificates"
        )
        is True
        and int(
            universal_oracle_cli_known_distance_certificate_payload.get("external_label_exact_rows", 0) or 0
        )
        >= 125
        and universal_oracle_cli_known_distance_certificate_payload.get("all_verified") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("all_expected_distances_match") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("all_universal_optimized_cli") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("all_state_input_only") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("try_certificate_cache") is True
        and universal_oracle_cli_known_distance_certificate_payload.get("try_upper_lower_certificate") is False
        and universal_oracle_cli_known_distance_certificate_payload.get("random_cases_enabled") is False
        and universal_oracle_cli_known_distance_certificate_payload.get("nissy_benchmark_distances_present")
        == [16, 17, 18, 19, 20]
        and int(universal_oracle_cli_known_distance_certificate_payload.get("case_count", 0) or 0) >= 125
        and int(
            universal_oracle_cli_known_distance_certificate_payload.get(
                "expected_distance_checked_count",
                0,
            )
            or 0
        )
        >= 125
        and list(universal_oracle_cli_known_distance_certificate_payload.get("selected_backends", []))
        == ["exact-certificate-cache"]
        and float(
            universal_oracle_cli_known_distance_certificate_payload.get(
                "max_runtime_seconds",
                10**9,
            )
        )
        <= 5.0
        and float(
            universal_oracle_cli_known_distance_certificate_payload.get(
                "wrapper_wall_seconds",
                10**9,
            )
        )
        <= 10.0
        and universal_oracle_cli_known_distance_certificate_payload.get(
            "fast_runtime_proven_for_every_possible_state"
        )
        is False
        and len(universal_oracle_cli_known_distance_certificate_rows) >= 125
        and all(
            row.get("case_kind") == "nissy_core_benchmark_known_distance"
            and row.get("input_kind") == "facelets"
            and row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "external_label_exact"
            and row.get("verified") is True
            and row.get("solution_length") == row.get("expected_distance")
            and row.get("source_sequence_provided_to_solver") is not True
            and "certificate_exactness_basis=third_party_benchmark_label" in str(row.get("notes", ""))
            and "certificate_artifact=results/processed/nissy_benchmark_certificates_seed_2026_thesis_distances16_20.json"
            in str(row.get("notes", ""))
            for row in universal_oracle_cli_known_distance_certificate_rows
        ),
        "universal_symmetry_oracle_lowload_exact": bool(universal_symmetry_payload)
        and universal_symmetry_payload.get("profile") == profile
        and universal_symmetry_payload.get("solver") == solver
        and universal_symmetry_payload.get("api_class") == "UniversalOptimalOracle"
        and universal_symmetry_payload.get("trusted_table") is True
        and universal_symmetry_payload.get("passed") is True
        and universal_symmetry_payload.get("all_exact") is True
        and universal_symmetry_payload.get("all_verified") is True
        and universal_symmetry_payload.get("all_nissy_symmetry_batch") is True
        and universal_symmetry_payload.get("fast_runtime_proven_for_every_possible_state") is False
        and len(universal_symmetry_rows) >= 1
        and all(
            row.get("selected_backend") == "nissy-symmetry-batch"
            and row.get("backend_solver") == "nissy_symmetry_batch_oracle"
            and row.get("selected_rotation")
            and row.get("status") == "exact"
            and row.get("verified") is True
            for row in universal_symmetry_rows
        ),
        "certificate_cache_inverse_closure_lowload_exact": bool(inverse_cache_payload)
        and inverse_cache_payload.get("profile") == profile
        and inverse_cache_payload.get("solver") == solver
        and inverse_cache_payload.get("api_class") == "UniversalOptimalOracle"
        and inverse_cache_payload.get("certificate_store") == "ExactCertificateStore"
        and inverse_cache_payload.get("certificate_cache_derivation") == "inverse"
        and inverse_cache_payload.get("passed") is True
        and inverse_cache_payload.get("all_exact") is True
        and inverse_cache_payload.get("all_verified") is True
        and inverse_cache_payload.get("all_inverse_certificate_cache") is True
        and len(inverse_cache_rows) >= 10
        and all(
            row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("certificate_derivation") == "inverse"
            for row in inverse_cache_rows
        ),
        "certificate_cache_symmetry_closure_lowload_exact": bool(symmetry_cache_payload)
        and symmetry_cache_payload.get("profile") == profile
        and symmetry_cache_payload.get("solver") == solver
        and symmetry_cache_payload.get("api_class") == "UniversalOptimalOracle"
        and symmetry_cache_payload.get("certificate_store") == "ExactCertificateStore"
        and symmetry_cache_payload.get("passed") is True
        and symmetry_cache_payload.get("all_exact") is True
        and symmetry_cache_payload.get("all_verified") is True
        and symmetry_cache_payload.get("all_symmetry_certificate_cache") is True
        and symmetry_cache_payload.get("symmetry_closure_proven_for_saved_certificates") is True
        and len(symmetry_cache_rows) >= 700
        and all(
            row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("certificate_derivation") in {"symmetry", "inverse_symmetry"}
            for row in symmetry_cache_rows
        ),
        "certificate_cache_expanded_symmetry_closure_lowload_exact": bool(expanded_symmetry_cache_payload)
        and expanded_symmetry_cache_payload.get("profile") == profile
        and expanded_symmetry_cache_payload.get("solver") == solver
        and expanded_symmetry_cache_payload.get("api_class") == "UniversalOptimalOracle"
        and expanded_symmetry_cache_payload.get("certificate_store") == "ExactCertificateStore"
        and expanded_symmetry_cache_payload.get("passed") is True
        and expanded_symmetry_cache_payload.get("all_exact") is True
        and expanded_symmetry_cache_payload.get("all_verified") is True
        and expanded_symmetry_cache_payload.get("all_symmetry_certificate_cache") is True
        and expanded_symmetry_cache_payload.get("symmetry_closure_proven_for_saved_certificates") is True
        and len(expanded_symmetry_cache_rows) > len(symmetry_cache_rows)
        and all(
            row.get("selected_backend") == "exact-certificate-cache"
            and row.get("status") == "exact"
            and row.get("verified") is True
            and row.get("certificate_derivation") in {"symmetry", "inverse_symmetry"}
            for row in expanded_symmetry_cache_rows
        ),
        "learned_certificate_cache_lowload_exact": bool(learned_certificate_cache_payload)
        and learned_certificate_cache_payload.get("profile") == profile
        and learned_certificate_cache_payload.get("solver") == solver
        and learned_certificate_cache_payload.get("api_class") == "UniversalOptimalOracle"
        and learned_certificate_cache_payload.get("certificate_store") == "ExactCertificateStore"
        and learned_certificate_cache_payload.get("passed") is True
        and learned_certificate_cache_payload.get("learned_jsonl_all_exact") is True
        and learned_certificate_cache_payload.get("first_pass_all_exact") is True
        and learned_certificate_cache_payload.get("first_pass_all_verified") is True
        and learned_certificate_cache_payload.get("first_pass_all_cache_miss") is True
        and learned_certificate_cache_payload.get("replay_live_backends_enabled") is False
        and learned_certificate_cache_payload.get("replay_all_exact") is True
        and learned_certificate_cache_payload.get("replay_all_verified") is True
        and learned_certificate_cache_payload.get("replay_all_certificate_cache") is True
        and len(learned_certificate_cache_rows) >= 2
        and int(learned_certificate_cache_payload.get("learned_jsonl_row_count", 0) or 0)
        >= len(learned_certificate_cache_rows)
        and all(
            row.get("first_selected_backend") != "exact-certificate-cache"
            and row.get("replay_selected_backend") == "exact-certificate-cache"
            and row.get("first_status") == "exact"
            and row.get("first_verified") is True
            and row.get("replay_status") == "exact"
            and row.get("replay_verified") is True
            and row.get("solution_length") == row.get("replay_solution_length")
            for row in learned_certificate_cache_rows
        ),
    }

    all_state_exact_contract_supported = all(source_checks.values()) and all(artifact_checks.values())
    fast_optimal_oracle_implemented_for_every_valid_3x3_state = all_state_exact_contract_supported
    empirical_fast_corpus_supported = all(empirical_checks.values())
    fast_runtime_proven_for_every_possible_state = (
        all_state_exact_contract_supported
        and fast_optimal_oracle_implemented_for_every_valid_3x3_state
        and empirical_fast_corpus_supported
        and contract_solver_meets_fast_target
        and trusted_ok
        and cloud_runtime_proof["passed"] is True
    )
    resident_cert_max = (
        evidence["resident_certification"]["payload"].get("max_runtime_seconds")
        if evidence["resident_certification"]
        else None
    )
    resident_cert_wall = (
        evidence["resident_certification"]["payload"].get("resident_wall_seconds")
        if evidence["resident_certification"]
        else None
    )

    source_snippets = {
        "nissy_h48_solver": _snippet(sources["nissy_solvers_doc"], r"## The H48 optimal solver.*?\* From"),
        "nissy_solve_api": _snippet(sources["nissy_api_header"], r"optimal\s+- The maximum number of moves above the optimal solution"),
        "backend_nissy_solve_call": _snippet(sources["h48_backend"], r"result = nissy_solve\(.*?\);"),
        "backend_native_search_timeout": _snippet(sources["h48_backend"], r"--search-timeout-ms.*?timed_out_by_poll"),
        "python_verification": _snippet(sources["python_h48_wrapper"], r"verification = verify_solution\(cube, solution\)"),
    }

    return {
        "schema_version": 1,
        "profile": profile,
        "seed": seed,
        "solver": solver,
        "table_path": str(table_path.relative_to(root)),
        "metadata_path": str(metadata_path.relative_to(root)),
        "trusted_metadata_message": trusted_message,
        "source_paths": SOURCE_PATHS,
        "source_checks": source_checks,
        "artifact_checks": artifact_checks,
        "empirical_checks": empirical_checks,
        "source_snippets": source_snippets,
        "measured_evidence": {
            "stress_case_count": len(stress_rows),
            "resident_certification_case_count": len(resident_cert_rows),
            "resident_certification_max_runtime_seconds": resident_cert_max,
            "resident_certification_resident_wall_seconds": resident_cert_wall,
            "resident_speedup": resident_speed_payload.get("resident_speedup"),
            "fast_optimal_oracle_api_case_count": len(api_rows),
            "fast_optimal_oracle_api_max_runtime_seconds": api_payload.get("max_runtime_seconds"),
            "fast_optimal_oracle_api_p95_runtime_seconds": api_payload.get("p95_runtime_seconds"),
            "streaming_wrapper_wall_seconds": (
                evidence["streaming_cli"]["payload"].get("wrapper_wall_seconds")
                if evidence["streaming_cli"]
                else None
            ),
            "trusted_no_preload_max_runtime_seconds": trusted_no_preload_payload.get("max_runtime_seconds"),
            "nissy_public_optimal_table_size_bytes": nissy_install_payload.get("target_size_bytes"),
            "nissy_public_optimal_table_install_runtime_seconds": (
                nissy_install_payload.get("install_result", {}) or {}
            ).get("runtime_seconds"),
            "nissy_public_archive_table_entry_count": nissy_complete_payload.get("archive_table_entry_count"),
            "nissy_public_installed_table_count": nissy_complete_payload.get("installed_table_count"),
            "nissy_public_tables_total_bytes": nissy_complete_payload.get("installed_total_bytes"),
            "nissy_public_ptable_reports_missing_tables": (
                nissy_complete_payload.get("nissy_ptable") or {}
            ).get("reports_missing_tables"),
            "nissy_public_tables_complete_path": (
                evidence["nissy_public_tables_complete"]["path"]
                if evidence["nissy_public_tables_complete"]
                else None
            ),
            "nissy_public_tables_complete_checked_at_utc": nissy_complete_payload.get("checked_at_utc"),
            "nissy_optimal_thesis_max_runtime_seconds": max(
                [float(row.get("runtime_seconds", 0.0) or 0.0) for row in nissy_optimal_thesis_rows],
                default=None,
            ),
            "nissy_optimal_stress_max_runtime_seconds": max(
                [float(row.get("runtime_seconds", 0.0) or 0.0) for row in nissy_optimal_stress_rows],
                default=None,
            ),
            "nissy_optimal_stress_depth20_runtime_seconds": next(
                (
                    row.get("runtime_seconds")
                    for row in nissy_optimal_stress_rows
                    if row.get("case_id") == "random_3_20"
                ),
                None,
            ),
            "nissy_core_direct_thesis_case_count": len(nissy_core_direct_rows),
            "nissy_core_direct_thesis_max_runtime_seconds": max(
                [float(row.get("runtime_seconds", 0.0) or 0.0) for row in nissy_core_direct_rows],
                default=None,
            ),
            "nissy_core_direct_thesis_table_bytes": nissy_core_direct_rows[1].get("table_size_bytes")
            if len(nissy_core_direct_rows) > 1
            else None,
            "nissy_core_resident_mmap_case_count": len(nissy_core_resident_mmap_rows),
            "nissy_core_resident_mmap_max_runtime_seconds": (
                nissy_core_resident_mmap_payload.get("max_runtime_seconds")
            ),
            "nissy_core_resident_mmap_wrapper_wall_seconds": (
                nissy_core_resident_mmap_payload.get("wrapper_wall_seconds")
            ),
            "nissy_core_resident_mmap_table_bytes": (
                nissy_core_resident_mmap_payload.get("table_size_bytes")
            ),
            "nissy_core_resident_mmap_table_data_modes": (
                nissy_core_resident_mmap_payload.get("table_data_modes")
            ),
            "portfolio_nissy_first_max_runtime_seconds": portfolio_nissy_payload.get("max_runtime_seconds"),
            "portfolio_nissy_state_recovery_max_runtime_seconds": portfolio_state_recovery_payload.get(
                "max_runtime_seconds"
            ),
            "portfolio_nissy_core_direct_state_case_count": len(portfolio_nissy_core_direct_state_rows),
            "portfolio_nissy_core_direct_state_max_runtime_seconds": (
                portfolio_nissy_core_direct_state_payload.get("max_runtime_seconds")
            ),
            "portfolio_superflip_fallback_runtime_seconds": next(
                (
                    row.get("runtime_seconds")
                    for row in portfolio_superflip_rows
                    if row.get("case_id") == "superflip_distance_20"
                ),
                None,
            ),
            "portfolio_superflip_certificate_cache_runtime_seconds": next(
                (
                    row.get("runtime_seconds")
                    for row in portfolio_cache_rows
                    if row.get("case_id") == "superflip_distance_20"
                ),
                None,
            ),
            "race_optimal_oracle_max_runtime_seconds": race_payload.get("max_runtime_seconds"),
            "race_optimal_oracle_selected_backends": sorted(
                {str(row.get("selected_backend")) for row in race_rows if row.get("selected_backend")}
            ),
            "race_optimal_oracle_killed_backends": sorted(
                {str(row.get("killed_backends")) for row in race_rows if row.get("killed_backends")}
            ),
            "race_nissy_core_direct_max_runtime_seconds": race_nissy_core_payload.get("max_runtime_seconds"),
            "race_nissy_core_direct_selected_backends": sorted(
                {
                    str(row.get("selected_backend"))
                    for row in race_nissy_core_rows
                    if row.get("selected_backend")
                }
            ),
            "resident_race_optimal_oracle_max_runtime_seconds": resident_race_payload.get(
                "max_runtime_seconds"
            ),
            "resident_race_optimal_oracle_h48_reuse_wall_seconds": resident_race_payload.get(
                "h48_reuse_wall_seconds"
            ),
            "resident_race_optimal_oracle_selected_backends": sorted(
                {
                    str(row.get("selected_backend"))
                    for row in resident_race_rows
                    if row.get("selected_backend")
                }
            ),
            "resident_race_nissy_core_direct_max_runtime_seconds": resident_race_nissy_core_payload.get(
                "max_runtime_seconds"
            ),
            "resident_race_nissy_core_direct_selected_backends": sorted(
                {
                    str(row.get("selected_backend"))
                    for row in resident_race_nissy_core_rows
                    if row.get("selected_backend")
                }
            ),
            "universal_optimal_oracle_max_runtime_seconds": universal_payload.get("max_runtime_seconds"),
            "universal_optimal_oracle_selected_backends": sorted(
                {
                    str(row.get("selected_backend"))
                    for row in universal_rows
                    if row.get("selected_backend")
                }
            ),
            "universal_nissy_core_direct_case_count": len(universal_nissy_core_rows),
            "universal_nissy_core_direct_max_runtime_seconds": universal_nissy_core_payload.get(
                "max_runtime_seconds"
            ),
            "universal_nissy_core_direct_nested_backends": universal_nissy_core_payload.get(
                "nested_selected_backends"
            ),
            "universal_rubikoptimal_race_case_count": len(universal_rubikoptimal_race_rows),
            "universal_rubikoptimal_race_max_runtime_seconds": universal_rubikoptimal_race_payload.get(
                "max_runtime_seconds"
            ),
            "universal_rubikoptimal_race_selected_backends": universal_rubikoptimal_race_payload.get(
                "selected_backends"
            ),
            "rubikoptimal_resident_oracle_case_count": len(rubikoptimal_resident_rows),
            "rubikoptimal_resident_oracle_max_runtime_seconds": rubikoptimal_resident_payload.get(
                "max_runtime_seconds"
            ),
            "rubikoptimal_resident_oracle_start_count": rubikoptimal_resident_payload.get(
                "resident_start_count"
            ),
            "rubikoptimal_resident_oracle_reused_rows": rubikoptimal_resident_payload.get(
                "resident_process_reused_rows"
            ),
            "rubikoptimal_oracle_stream_case_count": len(rubikoptimal_stream_rows),
            "rubikoptimal_oracle_stream_max_runtime_seconds": rubikoptimal_stream_payload.get(
                "max_runtime_seconds"
            ),
            "rubikoptimal_oracle_stream_reused_rows": rubikoptimal_stream_payload.get(
                "resident_reused_rows"
            ),
            "universal_h48_symmetry_case_count": len(universal_h48_symmetry_rows),
            "universal_h48_symmetry_max_runtime_seconds": universal_h48_symmetry_payload.get(
                "max_runtime_seconds"
            ),
            "universal_h48_symmetry_selected_rotations": sorted(
                {
                    str(row.get("selected_rotation"))
                    for row in universal_h48_symmetry_rows
                    if row.get("selected_rotation")
                }
            ),
            "universal_batch_oracle_corpus_case_count": len(universal_batch_rows),
            "universal_batch_oracle_corpus_max_runtime_seconds": universal_batch_payload.get(
                "max_runtime_seconds"
            ),
            "universal_batch_oracle_corpus_nested_backends": universal_batch_payload.get(
                "nested_selected_backends"
            ),
            "universal_resident_h48_batch_case_count": len(universal_resident_h48_batch_rows),
            "universal_resident_h48_batch_max_runtime_seconds": (
                universal_resident_h48_batch_payload.get("max_runtime_seconds")
            ),
            "universal_resident_h48_batch_nested_backends": (
                universal_resident_h48_batch_payload.get("nested_selected_backends")
            ),
            "universal_resident_h48_batch_depths": universal_resident_h48_batch_payload.get("depths"),
            "universal_oracle_cli_case_count": len(universal_oracle_cli_rows),
            "universal_oracle_cli_max_runtime_seconds": universal_oracle_cli_payload.get(
                "max_runtime_seconds"
            ),
            "universal_oracle_cli_resident_h48_batch_rows": universal_oracle_cli_payload.get(
                "resident_h48_batch_rows"
            ),
            "universal_oracle_cli_selected_backends": universal_oracle_cli_payload.get(
                "selected_backends"
            ),
            "universal_oracle_cli_broader_case_count": len(universal_oracle_cli_broader_rows),
            "universal_oracle_cli_broader_max_runtime_seconds": (
                universal_oracle_cli_broader_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_broader_wrapper_wall_seconds": (
                universal_oracle_cli_broader_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_broader_resident_h48_batch_rows": (
                universal_oracle_cli_broader_payload.get("resident_h48_batch_rows")
            ),
            "universal_oracle_cli_broader_resident_h48_fallback_rows": (
                universal_oracle_cli_broader_payload.get("resident_h48_fallback_rows")
            ),
            "universal_oracle_cli_broader_selected_backends": (
                universal_oracle_cli_broader_payload.get("selected_backends")
            ),
            "universal_oracle_cli_adaptive_case_count": len(universal_oracle_cli_adaptive_rows),
            "universal_oracle_cli_adaptive_max_runtime_seconds": (
                universal_oracle_cli_adaptive_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_adaptive_wrapper_wall_seconds": (
                universal_oracle_cli_adaptive_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_adaptive_portfolio_prepass_rows": (
                universal_oracle_cli_adaptive_payload.get("portfolio_prepass_rows")
            ),
            "universal_oracle_cli_adaptive_selected_backends": (
                universal_oracle_cli_adaptive_payload.get("selected_backends")
            ),
            "universal_oracle_cli_expanded_adaptive_case_count": len(universal_oracle_cli_expanded_rows),
            "universal_oracle_cli_expanded_adaptive_hard_case_count": (
                universal_oracle_cli_expanded_payload.get("hard_case_count")
            ),
            "universal_oracle_cli_expanded_adaptive_max_runtime_seconds": (
                universal_oracle_cli_expanded_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_expanded_adaptive_wrapper_wall_seconds": (
                universal_oracle_cli_expanded_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_expanded_adaptive_portfolio_prepass_rows": (
                universal_oracle_cli_expanded_payload.get("portfolio_prepass_rows")
            ),
            "universal_oracle_cli_expanded_adaptive_selected_backends": (
                universal_oracle_cli_expanded_payload.get("selected_backends")
            ),
            "universal_oracle_cli_expanded_adaptive_contains_superflip": (
                universal_oracle_cli_expanded_payload.get("contains_superflip")
            ),
            "universal_oracle_cli_h48_symmetry_case_count": len(universal_oracle_cli_h48_symmetry_rows),
            "universal_oracle_cli_h48_symmetry_max_runtime_seconds": (
                universal_oracle_cli_h48_symmetry_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_h48_symmetry_wrapper_wall_seconds": (
                universal_oracle_cli_h48_symmetry_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_h48_symmetry_rows": (
                universal_oracle_cli_h48_symmetry_payload.get("resident_h48_symmetry_rows")
            ),
            "universal_oracle_cli_h48_symmetry_selected_backends": (
                universal_oracle_cli_h48_symmetry_payload.get("selected_backends")
            ),
            "universal_oracle_cli_h48_parallel_symmetry_case_count": len(
                universal_oracle_cli_h48_parallel_symmetry_rows
            ),
            "universal_oracle_cli_h48_parallel_symmetry_max_runtime_seconds": (
                universal_oracle_cli_h48_parallel_symmetry_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_h48_parallel_symmetry_wrapper_wall_seconds": (
                universal_oracle_cli_h48_parallel_symmetry_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_h48_parallel_symmetry_rows": (
                universal_oracle_cli_h48_parallel_symmetry_payload.get("parallel_h48_symmetry_rows")
            ),
            "universal_oracle_cli_h48_parallel_symmetry_selected_backends": (
                universal_oracle_cli_h48_parallel_symmetry_payload.get("selected_backends")
            ),
            "universal_oracle_cli_rotational_lower_bound_case_count": len(
                universal_oracle_cli_rotational_lower_bound_rows
            ),
            "universal_oracle_cli_rotational_lower_bound_batch_wall_seconds": (
                universal_oracle_cli_rotational_lower_bound_payload.get("batch_wall_seconds")
            ),
            "universal_oracle_cli_rotational_lower_bound_symmetry_variants": (
                universal_oracle_cli_rotational_lower_bound_payload.get("h48_lower_bound_symmetry_variants")
            ),
            "universal_oracle_cli_rotational_lower_bound_selected_backends": sorted(
                {
                    row.get("selected_backend")
                    for row in universal_oracle_cli_rotational_lower_bound_rows
                    if row.get("selected_backend")
                }
            ),
            "universal_oracle_cli_upper_lower_batch_case_count": len(
                universal_oracle_cli_upper_lower_batch_rows
            ),
            "universal_oracle_cli_upper_lower_batch_rows": (
                universal_oracle_cli_upper_lower_batch_payload.get("universal_upper_lower_batch_rows")
            ),
            "universal_oracle_cli_upper_lower_batch_lower_bound_rows": (
                universal_oracle_cli_upper_lower_batch_payload.get(
                    "universal_upper_lower_batch_lower_bound_rows"
                )
            ),
            "universal_oracle_cli_upper_lower_batch_selected_backends": (
                universal_oracle_cli_upper_lower_batch_payload.get("selected_backends")
            ),
            "universal_oracle_cli_late_nissy_core_direct_case_count": len(
                universal_oracle_cli_late_nissy_core_rows
            ),
            "universal_oracle_cli_late_nissy_core_direct_rows": (
                universal_oracle_cli_late_nissy_core_payload.get("late_nissy_core_direct_fallback_rows")
            ),
            "universal_oracle_cli_late_nissy_core_direct_selected_backends": (
                universal_oracle_cli_late_nissy_core_payload.get("selected_backends")
            ),
            "universal_oracle_cli_late_nissy_core_direct_max_runtime_seconds": (
                universal_oracle_cli_late_nissy_core_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_live_no_shortcuts_case_count": len(universal_oracle_cli_live_rows),
            "universal_oracle_cli_live_no_shortcuts_max_runtime_seconds": (
                universal_oracle_cli_live_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_live_no_shortcuts_wrapper_wall_seconds": (
                universal_oracle_cli_live_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_live_no_shortcuts_selected_backends": (
                universal_oracle_cli_live_payload.get("selected_backends")
            ),
            "universal_oracle_cli_live_no_shortcuts_broader_case_count": len(
                universal_oracle_cli_live_broader_rows
            ),
            "universal_oracle_cli_live_no_shortcuts_broader_depths": (
                universal_oracle_cli_live_broader_payload.get("depths")
            ),
            "universal_oracle_cli_live_no_shortcuts_broader_max_runtime_seconds": (
                universal_oracle_cli_live_broader_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_live_no_shortcuts_broader_wrapper_wall_seconds": (
                universal_oracle_cli_live_broader_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_live_no_shortcuts_broader_selected_backends": (
                universal_oracle_cli_live_broader_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_17_case_count": len(
                universal_oracle_cli_known_distance_rows
            ),
            "universal_oracle_cli_known_distance_17_max_runtime_seconds": (
                universal_oracle_cli_known_distance_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_17_max_backend_solve_seconds": (
                universal_oracle_cli_known_distance_payload.get("max_backend_solve_seconds")
            ),
            "universal_oracle_cli_known_distance_17_distances": (
                universal_oracle_cli_known_distance_payload.get("nissy_benchmark_distances_present")
            ),
            "universal_oracle_cli_known_distance_adaptive_case_count": len(
                universal_oracle_cli_known_distance_adaptive_rows
            ),
            "universal_oracle_cli_known_distance_adaptive_distances": (
                universal_oracle_cli_known_distance_adaptive_payload.get("nissy_benchmark_distances_present")
            ),
            "universal_oracle_cli_known_distance_adaptive_max_runtime_seconds": (
                universal_oracle_cli_known_distance_adaptive_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_adaptive_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_adaptive_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_known_distance_adaptive_selected_backends": (
                universal_oracle_cli_known_distance_adaptive_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_19_case_count": len(
                universal_oracle_cli_known_distance_19_rows
            ),
            "universal_oracle_cli_known_distance_19_distances": (
                universal_oracle_cli_known_distance_19_payload.get("nissy_benchmark_distances_present")
            ),
            "universal_oracle_cli_known_distance_19_max_runtime_seconds": (
                universal_oracle_cli_known_distance_19_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_19_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_19_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_known_distance_19_max_backend_solve_seconds": (
                universal_oracle_cli_known_distance_19_payload.get("max_backend_solve_seconds")
            ),
            "universal_oracle_cli_known_distance_19_selected_backends": (
                universal_oracle_cli_known_distance_19_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_20_case_count": len(
                universal_oracle_cli_known_distance_20_rows
            ),
            "universal_oracle_cli_known_distance_20_distances": (
                universal_oracle_cli_known_distance_20_payload.get("nissy_benchmark_distances_present")
            ),
            "universal_oracle_cli_known_distance_20_max_runtime_seconds": (
                universal_oracle_cli_known_distance_20_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_20_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_20_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_known_distance_20_max_backend_solve_seconds": (
                universal_oracle_cli_known_distance_20_payload.get("max_backend_solve_seconds")
            ),
            "universal_oracle_cli_known_distance_20_selected_backends": (
                universal_oracle_cli_known_distance_20_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_20_offset1_case_count": len(
                universal_oracle_cli_known_distance_20_offset1_rows
            ),
            "universal_oracle_cli_known_distance_20_offset1_distances": (
                universal_oracle_cli_known_distance_20_offset1_payload.get(
                    "nissy_benchmark_distances_present"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_max_runtime_seconds": (
                universal_oracle_cli_known_distance_20_offset1_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_20_offset1_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_20_offset1_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_known_distance_20_offset1_max_backend_solve_seconds": (
                universal_oracle_cli_known_distance_20_offset1_payload.get("max_backend_solve_seconds")
            ),
            "universal_oracle_cli_known_distance_20_offset1_selected_backends": (
                universal_oracle_cli_known_distance_20_offset1_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_20_offset1_benchmark_offset_per_distance": (
                universal_oracle_cli_known_distance_20_offset1_payload.get("benchmark_offset_per_distance")
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_case_count": len(
                universal_oracle_cli_known_distance_20_offset1_trimmed_rows
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_distances": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "nissy_benchmark_distances_present"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_runtime_seconds": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "max_runtime_seconds"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "wrapper_wall_seconds"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_backend_solve_seconds": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "max_backend_solve_seconds"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_selected_backends": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "selected_backends"
                )
            ),
            "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_timeout_seconds": (
                universal_oracle_cli_known_distance_20_offset1_trimmed_payload.get(
                    "portfolio_prepass_timeout_seconds"
                )
            ),
            "nissy_benchmark_certificate_imported_case_count": len(nissy_benchmark_certificate_rows),
            "nissy_benchmark_certificate_imported_distances": (
                nissy_benchmark_certificates_payload.get("distances")
            ),
            "universal_oracle_cli_known_distance_certificate_cache_case_count": len(
                universal_oracle_cli_known_distance_certificate_rows
            ),
            "universal_oracle_cli_known_distance_certificate_cache_distances": (
                universal_oracle_cli_known_distance_certificate_payload.get(
                    "nissy_benchmark_distances_present"
                )
            ),
            "universal_oracle_cli_known_distance_certificate_cache_max_runtime_seconds": (
                universal_oracle_cli_known_distance_certificate_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_certificate_cache_wrapper_wall_seconds": (
                universal_oracle_cli_known_distance_certificate_payload.get("wrapper_wall_seconds")
            ),
            "universal_oracle_cli_known_distance_certificate_cache_selected_backends": (
                universal_oracle_cli_known_distance_certificate_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_statuses": sorted(
                {
                    str(row.get("status"))
                    for row in known_distance_20_offset2_rubikoptimal_live_rows
                    if row.get("status")
                }
            ),
            "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_selected_backends": (
                known_distance_20_offset2_rubikoptimal_live_payload.get("selected_backends")
            ),
            "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_max_runtime_seconds": (
                known_distance_20_offset2_rubikoptimal_live_payload.get("max_runtime_seconds")
            ),
            "universal_oracle_cli_known_distance_20_offset2_rubikoptimal_live_max_backend_runtime_seconds": (
                known_distance_20_offset2_rubikoptimal_live_payload.get("max_backend_runtime_seconds")
            ),
            "known_distance_20_offset2_rubikoptimal_live_sweep_failed_offset_count": (
                known_distance_20_offset2_rubikoptimal_live_sweep_payload.get("failed_offset_count")
            ),
            "known_distance_20_offset2_rubikoptimal_live_sweep_wrapper_wall_seconds": (
                known_distance_20_offset2_rubikoptimal_live_sweep_payload.get("wrapper_wall_seconds")
            ),
            "known_distance_20_offset2_rubikoptimal_live_sweep_row_statuses": sorted(
                {
                    str(row.get("status"))
                    for row in known_distance_20_offset2_rubikoptimal_live_sweep_rows
                    if row.get("status")
                }
            ),
            "universal_symmetry_oracle_case_count": len(universal_symmetry_rows),
            "universal_symmetry_oracle_max_runtime_seconds": universal_symmetry_payload.get(
                "max_runtime_seconds"
            ),
            "universal_symmetry_oracle_selected_rotations": sorted(
                {
                    str(row.get("selected_rotation"))
                    for row in universal_symmetry_rows
                    if row.get("selected_rotation")
                }
            ),
            "certificate_cache_inverse_closure_case_count": len(inverse_cache_rows),
            "certificate_cache_inverse_closure_max_runtime_seconds": inverse_cache_payload.get(
                "max_runtime_seconds"
            ),
            "certificate_cache_symmetry_closure_case_count": len(symmetry_cache_rows),
            "certificate_cache_symmetry_closure_max_runtime_seconds": symmetry_cache_payload.get(
                "max_runtime_seconds"
            ),
            "certificate_cache_symmetry_closure_derivation_counts": symmetry_cache_payload.get(
                "derivation_counts"
            ),
            "certificate_cache_expanded_symmetry_closure_case_count": len(expanded_symmetry_cache_rows),
            "certificate_cache_expanded_symmetry_closure_max_runtime_seconds": (
                expanded_symmetry_cache_payload.get("max_runtime_seconds")
            ),
            "certificate_cache_expanded_symmetry_closure_derivation_counts": (
                expanded_symmetry_cache_payload.get("derivation_counts")
            ),
            "learned_certificate_cache_case_count": len(learned_certificate_cache_rows),
            "learned_certificate_cache_jsonl_row_count": learned_certificate_cache_payload.get(
                "learned_jsonl_row_count"
            ),
            "learned_certificate_cache_max_first_runtime_seconds": (
                learned_certificate_cache_payload.get("max_first_runtime_seconds")
            ),
            "learned_certificate_cache_max_replay_runtime_seconds": (
                learned_certificate_cache_payload.get("max_replay_runtime_seconds")
            ),
            "learned_certificate_cache_first_selected_backends": sorted(
                {
                    str(row.get("first_selected_backend"))
                    for row in learned_certificate_cache_rows
                    if row.get("first_selected_backend")
                }
            ),
            "learned_certificate_cache_replay_selected_backends": sorted(
                {
                    str(row.get("replay_selected_backend"))
                    for row in learned_certificate_cache_rows
                    if row.get("replay_selected_backend")
                }
            ),
            "h48_capacity_stronger_table_plan_solvers": h48_capacity_plan_solvers,
            "h48_capacity_fast_target_proof_plan_valid": h48_capacity_fast_target_proof_plan_valid,
            "h48_capacity_plan_recommends_optimized_generation": (
                h48_capacity_plan_recommends_optimized_generation
            ),
            "h48_capacity_safe_to_start_h48h8_generation_now": h48_capacity_payload.get(
                "safe_to_start_h48h8_generation_now"
            )
            if h48_capacity_payload
            else None,
            "h48_capacity_can_claim_every_state_fast": h48_capacity_gate.get(
                "can_claim_fast_oracle_for_every_possible_state"
            )
            if h48_capacity_gate
            else None,
            "h48_capacity_fast_target_solver": h48_capacity_payload.get("h48_fast_target_solver")
            if h48_capacity_payload
            else None,
            "h48_capacity_fast_target_expected_size_bytes": h48_capacity_gate.get(
                "target_table_expected_size_bytes"
            )
            if h48_capacity_gate
            else None,
            "h48_capacity_fast_target_table_trusted": h48_capacity_fast_target_table_trusted,
            "h48_capacity_fast_target_safe_to_generate_now": (
                h48_capacity_payload.get("h48_fast_target_generation_safety") or {}
            ).get("safe_to_start")
            if h48_capacity_payload
            else None,
            "h48_capacity_fast_target_has_upstream_distance20_timing": h48_capacity_gate.get(
                "target_upstream_benchmark_has_distance20_timing"
            )
            if h48_capacity_gate
            else None,
            "h48_capacity_fast_target_has_upstream_superflip_timing": h48_capacity_gate.get(
                "target_upstream_benchmark_has_superflip_timing"
            )
            if h48_capacity_gate
            else None,
            "h48_fasttarget_assumed_nonaws_preflight_passed": (
                h48_fasttarget_assumed_preflight_payload.get("passed")
            ),
            "h48_fasttarget_assumed_nonaws_preflight_machine_source": (
                h48_fasttarget_assumed_preflight_payload.get("machine_source")
            ),
            "h48_fasttarget_assumed_nonaws_preflight_workspace_satisfies": (
                h48_fasttarget_assumed_preflight_payload.get("target_h48_workspace") or {}
            ).get("satisfies_workspace"),
            "h48_fasttarget_assumed_nonaws_preflight_runtime_proven": (
                h48_fasttarget_assumed_preflight_payload.get(
                    "fast_runtime_proven_for_every_possible_state"
                )
            ),
            "h48_proof_volume_candidate_count": h48_proof_volume_candidates_payload.get(
                "candidate_count"
            ),
            "h48_proof_volume_launchable_candidate_count": (
                h48_proof_volume_candidates_payload.get("launchable_candidate_count")
            ),
            "h48_proof_volume_launchable_for_generation": (
                h48_proof_volume_candidates_payload.get("launchable_for_h48_generation")
            ),
            "h48_proof_volume_host_machine_satisfies": (
                h48_proof_volume_candidates_payload.get("host_machine_satisfies")
            ),
            "h48_proof_volume_required_workspace_bytes": (
                h48_proof_volume_candidates_payload.get("requirements") or {}
            ).get("required_workspace_bytes"),
            "h48_proof_volume_best_candidate_free_gib": (
                h48_proof_volume_candidates_payload.get("best_candidate") or {}
            ).get("disk_free_gib"),
            "h48_generation_probe_status": h48_generation_probe_payload.get("status"),
            "h48_generation_probe_runtime_seconds": h48_generation_probe_payload.get("runtime_seconds"),
            "h48_generation_probe_expected_table_size_bytes": h48_generation_probe_payload.get(
                "expected_table_size_bytes"
            ),
            "h48_generation_probe_partial_allocated_size_bytes": h48_generation_probe_payload.get(
                "partial_allocated_size_bytes_before_cleanup"
            ),
            "h48_generation_probe_latest_processed_short_cubes": h48_generation_probe_payload.get(
                "latest_processed_short_cubes"
            ),
            "h48_generation_probe_safe_to_start": (
                h48_generation_probe_payload.get("safety") or {}
            ).get("safe_to_start"),
            "h48_stronger_table_detached_status_path": (
                evidence["h48_stronger_table_detached_status"]["path"]
                if evidence["h48_stronger_table_detached_status"]
                else None
            ),
            "h48_stronger_table_detached_status_status": (
                h48_stronger_table_status_payload.get("status")
            ),
            "h48_stronger_table_detached_status_target_solver": (
                h48_stronger_table_status_payload.get("target_solver")
            ),
            "h48_stronger_table_detached_status_pid": (
                h48_stronger_table_status_payload.get("pid")
            ),
            "h48_stronger_table_detached_status_pid_alive": (
                h48_stronger_table_status_payload.get("pid_alive")
            ),
            "h48_stronger_table_detached_status_native_running": (
                h48_stronger_table_status_payload.get("native_h48_backend_running")
            ),
            "h48_stronger_table_detached_status_target_trusted_table": (
                h48_stronger_table_status_payload.get("target_trusted_table")
            ),
            "h48_stronger_table_detached_status_waitsafe_sample_count": (
                h48_stronger_table_wait_safe.get("sample_count")
            ),
            "h48_stronger_table_detached_status_waitsafe_ever_safe_to_start": (
                h48_stronger_table_wait_safe.get("ever_safe_to_start")
            ),
            "h48_stronger_table_detached_status_waitsafe_latest_safe_to_start": (
                h48_stronger_table_wait_safe.get("latest_safe_to_start")
            ),
            "h48_stronger_table_detached_status_waitsafe_latest_available_memory_bytes": (
                h48_stronger_table_wait_safe.get("latest_available_memory_bytes")
            ),
            "h48_stronger_table_detached_status_waitsafe_latest_reasons": (
                h48_stronger_table_wait_safe.get("latest_reasons")
            ),
            "h48_stronger_table_detached_status_generation_progress_available": (
                h48_stronger_table_generation_progress.get("available")
            ),
            "h48_stronger_table_detached_status_partial_table_exists": (
                h48_stronger_table_generation_progress.get("partial_table_exists")
            ),
            "h48_stronger_table_detached_status_gendata_workbatch": (
                h48_stronger_table_status_payload.get("h48_gendata_workbatch")
            ),
            "h48_stronger_table_detached_status_generation_distribution_mode": (
                h48_stronger_table_status_payload.get("h48_generation_distribution_mode")
            ),
            "h48_stronger_table_detached_status_generation_mmap_sync_mode": (
                h48_stronger_table_status_payload.get("h48_generation_mmap_sync_mode")
            ),
            "h48_stronger_table_detached_status_backend_extra_cflags": (
                h48_stronger_table_status_payload.get("h48_backend_extra_cflags")
            ),
            "h48_stronger_table_detached_status_fast_runtime_proven": (
                h48_stronger_table_status_payload.get("fast_runtime_proven_for_every_possible_state")
            ),
            "h48_fasttarget_stronger_table_detached_status_path": (
                evidence["h48_fasttarget_stronger_table_detached_status"]["path"]
                if evidence["h48_fasttarget_stronger_table_detached_status"]
                else None
            ),
            "h48_fasttarget_stronger_table_detached_status_status": (
                h48_fasttarget_stronger_table_status_payload.get("status")
            ),
            "h48_fasttarget_stronger_table_detached_status_target_solver": (
                h48_fasttarget_stronger_table_status_payload.get("target_solver")
            ),
            "h48_fasttarget_stronger_table_detached_status_pid": (
                h48_fasttarget_stronger_table_status_payload.get("pid")
            ),
            "h48_fasttarget_stronger_table_detached_status_pid_alive": (
                h48_fasttarget_stronger_table_status_payload.get("pid_alive")
            ),
            "h48_fasttarget_stronger_table_detached_status_native_running": (
                h48_fasttarget_stronger_table_status_payload.get("native_h48_backend_running")
            ),
            "h48_fasttarget_stronger_table_detached_status_target_trusted_table": (
                h48_fasttarget_stronger_table_status_payload.get("target_trusted_table")
            ),
            "h48_fasttarget_stronger_table_detached_status_waitsafe_sample_count": (
                h48_fasttarget_stronger_table_wait_safe.get("sample_count")
            ),
            "h48_fasttarget_stronger_table_detached_status_waitsafe_latest_safe_to_start": (
                h48_fasttarget_stronger_table_wait_safe.get("latest_safe_to_start")
            ),
            "h48_fasttarget_stronger_table_detached_status_waitsafe_latest_available_memory_bytes": (
                h48_fasttarget_stronger_table_wait_safe.get("latest_available_memory_bytes")
            ),
            "h48_fasttarget_stronger_table_detached_status_waitsafe_latest_reasons": (
                h48_fasttarget_stronger_table_wait_safe.get("latest_reasons")
            ),
            "h48_fasttarget_stronger_table_detached_status_current_safe_to_start": (
                (h48_fasttarget_stronger_table_status_payload.get("current_safety") or {}).get(
                    "safe_to_start"
                )
            ),
            "h48_fasttarget_stronger_table_detached_status_current_reasons": (
                (h48_fasttarget_stronger_table_status_payload.get("current_safety") or {}).get(
                    "reasons"
                )
            ),
            "h48_fasttarget_stronger_table_detached_status_current_available_memory_bytes": (
                (
                    (h48_fasttarget_stronger_table_status_payload.get("current_safety") or {}).get(
                        "machine"
                    )
                    or {}
                ).get("available_memory_bytes")
            ),
            "h48_fasttarget_stronger_table_detached_status_current_h48_free_bytes": (
                (
                    (h48_fasttarget_stronger_table_status_payload.get("current_safety") or {}).get(
                        "machine"
                    )
                    or {}
                ).get("data_generated_h48_free_bytes")
            ),
            "h48_fasttarget_stronger_table_detached_status_generation_progress_available": (
                h48_fasttarget_stronger_table_generation_progress.get("available")
            ),
            "h48_fasttarget_stronger_table_detached_status_partial_table_exists": (
                h48_fasttarget_stronger_table_generation_progress.get("partial_table_exists")
            ),
            "h48_fasttarget_stronger_table_detached_status_gendata_workbatch": (
                h48_fasttarget_stronger_table_status_payload.get("h48_gendata_workbatch")
            ),
            "h48_fasttarget_stronger_table_detached_status_generation_distribution_mode": (
                h48_fasttarget_stronger_table_status_payload.get("h48_generation_distribution_mode")
            ),
            "h48_fasttarget_stronger_table_detached_status_generation_mmap_sync_mode": (
                h48_fasttarget_stronger_table_status_payload.get("h48_generation_mmap_sync_mode")
            ),
            "h48_fasttarget_stronger_table_detached_status_backend_extra_cflags": (
                h48_fasttarget_stronger_table_status_payload.get("h48_backend_extra_cflags")
            ),
            "h48_fasttarget_stronger_table_detached_status_fast_runtime_proven": (
                h48_fasttarget_stronger_table_status_payload.get(
                    "fast_runtime_proven_for_every_possible_state"
                )
            ),
            "h48_split_bundle_smoke_passed": h48_split_bundle_smoke_payload.get("passed"),
            "h48_split_bundle_smoke_solver": h48_split_bundle_smoke_payload.get("solver"),
            "h48_split_bundle_smoke_part_count": h48_split_bundle_smoke_payload.get(
                "bundle_part_count"
            ),
            "h48_split_bundle_smoke_runtime_seconds": h48_split_bundle_smoke_payload.get(
                "runtime_seconds"
            ),
            "h48_split_bundle_smoke_installed_table_size_bytes": (
                h48_split_bundle_smoke_payload.get("installed_table_size_bytes")
            ),
            "h48_split_bundle_smoke_post_install_checksum": (
                h48_split_bundle_smoke_payload.get("post_install_full_checksum_valid")
            ),
            "h48_split_bundle_oracle_grade_smoke_passed": (
                h48_split_bundle_oracle_grade_smoke_payload.get("passed")
            ),
            "h48_split_bundle_oracle_grade_smoke_solver": (
                h48_split_bundle_oracle_grade_smoke_payload.get("solver")
            ),
            "h48_split_bundle_oracle_grade_smoke_part_count": (
                h48_split_bundle_oracle_grade_smoke_payload.get("bundle_part_count")
            ),
            "h48_split_bundle_oracle_grade_smoke_runtime_seconds": (
                h48_split_bundle_oracle_grade_smoke_payload.get("runtime_seconds")
            ),
            "h48_split_bundle_oracle_grade_smoke_installed_table_size_bytes": (
                h48_split_bundle_oracle_grade_smoke_payload.get("installed_table_size_bytes")
            ),
            "h48_split_bundle_oracle_grade_smoke_post_install_checksum": (
                h48_split_bundle_oracle_grade_smoke_payload.get(
                    "post_install_full_checksum_valid"
                )
            ),
            "h48_fasttarget_nonaws_proof_package_passed": (
                h48_fasttarget_nonaws_proof_package_payload.get("passed")
            ),
            "h48_fasttarget_nonaws_proof_package_sha256": (
                h48_fasttarget_nonaws_proof_package_payload.get("package_sha256")
            ),
            "h48_fasttarget_nonaws_proof_package_step_count": (
                h48_fasttarget_nonaws_proof_package_payload.get("planned_step_count")
            ),
            "h48_fasttarget_nonaws_proof_package_mode": (
                h48_fasttarget_nonaws_proof_package_payload.get("package_mode")
            ),
            "h48_fasttarget_nonaws_proof_package_launchable": (
                h48_fasttarget_nonaws_proof_package_payload.get("launchable_for_execution")
            ),
            "h48_fasttarget_nonaws_proof_package_preflight_is_live": (
                h48_fasttarget_nonaws_proof_package_payload.get(
                    "preflight_is_live_runtime_evidence"
                )
            ),
            "h48_fasttarget_nonaws_proof_package_proof_volume_required": (
                h48_fasttarget_nonaws_proof_package_payload.get(
                    "proof_volume_report_required"
                )
            ),
            "h48_fasttarget_nonaws_proof_package_proof_volume_launchable": (
                h48_fasttarget_nonaws_proof_package_payload.get(
                    "proof_volume_report_launchable"
                )
            ),
            "h48_fasttarget_nonaws_proof_package_proof_volume_requirement": (
                (
                    h48_fasttarget_nonaws_proof_package_payload.get(
                        "proof_volume_report_summary"
                    )
                    or {}
                ).get("proof_volume_requirement_satisfied")
            ),
            "h48_fasttarget_nonaws_proof_package_proof_volume_candidate_count": (
                (
                    h48_fasttarget_nonaws_proof_package_payload.get(
                        "proof_volume_report_summary"
                    )
                    or {}
                ).get("candidate_count")
            ),
            "h48_fasttarget_nonaws_proof_package_launchable_volume_count": (
                (
                    h48_fasttarget_nonaws_proof_package_payload.get(
                        "proof_volume_report_summary"
                    )
                    or {}
                ).get("launchable_candidate_count")
            ),
            "h48_fasttarget_nonaws_proof_package_full_required_workload_count": (
                (
                    h48_fasttarget_nonaws_proof_package_payload.get("full_plan_summary")
                    or {}
                ).get("required_workload_count")
            ),
            "h48_fasttarget_nonaws_proof_package_contract_still_requires_runtime": (
                (
                    h48_fasttarget_nonaws_proof_package_payload.get("checks")
                    or {}
                ).get("contract_still_requires_runtime_proof")
            ),
            "h48_fasttarget_nonaws_proof_package_fast_runtime_proven": (
                h48_fasttarget_nonaws_proof_package_payload.get(
                    "fast_runtime_proven_for_every_possible_state"
                )
            ),
            "h48_fasttarget_nonaws_launch_preparation_status": (
                h48_fasttarget_nonaws_launch_preparation_payload.get("status")
            ),
            "h48_fasttarget_nonaws_launch_preparation_launchable": (
                h48_fasttarget_nonaws_launch_preparation_payload.get(
                    "launchable_for_execution"
                )
            ),
            "h48_fasttarget_nonaws_launch_preparation_heavy_generation_started": (
                h48_fasttarget_nonaws_launch_preparation_payload.get(
                    "heavy_generation_started"
                )
            ),
            "h48_fasttarget_nonaws_launch_preparation_proof_workloads_started": (
                h48_fasttarget_nonaws_launch_preparation_payload.get(
                    "proof_workloads_started"
                )
            ),
            "h48_fasttarget_nonaws_launch_preparation_preflight_path": (
                h48_fasttarget_nonaws_launch_preparation_payload.get("preflight_path")
            ),
            "h48_fasttarget_nonaws_launch_preparation_proof_volume_path": (
                h48_fasttarget_nonaws_launch_preparation_payload.get(
                    "proof_volume_report_path"
                )
            ),
            "h48_fasttarget_nonaws_launch_preparation_proof_package_path": (
                h48_fasttarget_nonaws_launch_preparation_payload.get("proof_package_path")
            ),
            "h48_fasttarget_nonaws_launch_preparation_fast_runtime_proven": (
                h48_fasttarget_nonaws_launch_preparation_payload.get(
                    "fast_runtime_proven_for_every_possible_state"
                )
            ),
            "cloud_hardtail_evaluation_path": cloud_runtime_proof.get("evaluation_path"),
            "cloud_hardtail_claim_scope": cloud_runtime_proof.get("claim_scope"),
            "cloud_hardtail_full_distance20_coverage": cloud_runtime_proof.get(
                "full_distance20_hardtail_coverage"
            ),
            "cloud_hardtail_workload_count": cloud_runtime_proof.get("workload_count"),
            "cloud_hardtail_missing_or_failed_workload_count": cloud_runtime_proof.get(
                "missing_or_failed_workload_count"
            ),
            "cloud_hardtail_plan_solver_matches_fast_target": cloud_runtime_proof.get(
                "plan_solver_matches_h48_fast_target"
            ),
            "cloud_hardtail_contract_solver_matches_fast_target": cloud_runtime_proof.get(
                "contract_solver_matches_h48_fast_target"
            ),
            "cloud_hardtail_plan_solver_meets_fast_target": cloud_runtime_proof.get(
                "plan_solver_meets_h48_fast_target"
            ),
            "cloud_hardtail_contract_solver_meets_fast_target": cloud_runtime_proof.get(
                "contract_solver_meets_h48_fast_target"
            ),
            "cloud_hardtail_contract_solver_table_trusted": cloud_runtime_proof.get(
                "contract_solver_table_trusted"
            ),
            "cloud_hardtail_runtime_proof_passed": cloud_runtime_proof.get("passed"),
        },
        "referenced_evidence_files": {
            name: value["path"] if value else None for name, value in evidence.items()
        },
        "all_state_exact_contract_supported": all_state_exact_contract_supported,
        "fast_optimal_oracle_implemented_for_every_valid_3x3_state": (
            fast_optimal_oracle_implemented_for_every_valid_3x3_state
        ),
        "empirical_fast_corpus_supported": empirical_fast_corpus_supported,
        "cloud_runtime_proof": cloud_runtime_proof,
        "fast_runtime_proven_for_every_possible_state": fast_runtime_proven_for_every_possible_state,
        "claim_boundary": {
            "software_capability": (
                "The package now exposes a first-class FastOptimalOracle API backed by a resident "
                "native h48h7 H48 process, generated trusted metadata, max_depth 20, and independent "
                "solution verification for every returned solution. The package API default leaves native "
                "H48 search unbounded, so a valid direct-state query is not reported as a timeout unless "
                "the caller explicitly configures a benchmark/interactive deadline; it also exposes a portfolio oracle "
                "that reuses revalidated exact certificates, tries Nissy optimal under a bounded timeout, "
                "certifies matching upper/lower bounds, and then falls back to the resident H48 path. "
                "A separate nissy-core direct shell backend is exposed for direct cube-state input: it "
                "converts the cubie state to nissy-core format, symlinks the generated H48 table under "
                "the solver data id, invokes `solve -O 0 -cube`, and revalidates the returned solution "
                "without representative-scramble recovery. "
                "The RaceOptimalOracle latency layer can start native H48 and external Nissy optimal "
                "simultaneously, accept the first independently verified exact result, and terminate "
                "the slower subprocess.  The ResidentRaceOptimalOracle keeps the H48 side behind a "
                "resident FastOptimalOracle session while still racing the independent Nissy exact "
                "process, so repeated calls avoid unnecessary H48 process/table setup when H48 stays "
                "active. The UniversalOptimalOracle is the top-level optimized exact path: it tries "
                "solved-state and revalidated exact certificate answers, then matching upper/lower "
                "certificates, then the resident exact-backend race, where raw cube-state inputs can "
                "select the direct nissy-core H48 shell backend before representative-scramble recovery. "
                "For raw state-input corpora it can also route live states through one resident H48 "
                "batch so a native process and H48 table mapping are reused across rows. "
                "The public universal CLI can disable both zero-search certificate replay and "
                "upper/lower certificate shortcuts when collecting live-runtime evidence. "
                "The certificate cache now also "
                "derives and revalidates inverse-state certificates from saved exact rows, giving "
                "zero-search exact answers for those inverse states; it also derives whole-cube "
                "rotational symmetry certificates, giving zero-search exact answers for rotationally "
                "equivalent saved evidence states. Newly solved and independently verified exact rows "
                "can also be appended to a learned JSONL certificate log and replayed later through "
                "the same revalidated zero-search certificate path. "
                "Dedicated API evidence artifacts execute these public package-level entrypoints. "
                "The H48 capacity artifact records the h48h8-h48h11 stronger-table build ladder "
                "and the generator can refuse unsafe h48h8 generation on this loaded local machine. "
                "A bounded native h48h8 generation probe records the real mmap/table-allocation "
                "bottleneck and deletes its partial artifact. The split H48 bundle smoke creates "
                "checksummed table parts from a trusted h48h0 table and installs them into an "
                "isolated generated root with full checksum validation, proving the local "
                "split-transfer/install mechanics before applying the same path to a future "
                "stronger table."
            ),
            "all_state_exactness": (
                "Supported as a public-solver-derived contract if the thesis accepts nissy-core H48 "
                "plus the cited God's Number result: every valid state is in the H48 domain, "
                "max_depth is 20, and returned solutions are independently verified."
            ),
            "fast_runtime": (
                "Supported by the full cloud hard-tail runtime campaign recorded in cloud_runtime_proof."
                if fast_runtime_proven_for_every_possible_state
                else (
                    "Supported empirically for the saved H48 stress/certification/streaming corpus and "
                    "the external Nissy optimal plus portfolio stress/fallback corpora only; "
                    "no completed full-scope cloud/runtime proof over every possible 3x3 state is present."
                )
            ),
        },
        "passed": all_state_exact_contract_supported and empirical_fast_corpus_supported,
    }


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_\\allowbreak{}")


def write_table(root: Path, payload: dict[str, Any], suffix: str) -> Path:
    filename = f"h48_oracle_contract{suffix}.tex" if suffix else "h48_oracle_contract.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("Fast optimal oracle API", payload["fast_optimal_oracle_implemented_for_every_valid_3x3_state"]),
        ("All-state exact contract", payload["all_state_exact_contract_supported"]),
        ("Empirical fast corpus", payload["empirical_fast_corpus_supported"]),
        ("Every-state fast runtime proof", payload["fast_runtime_proven_for_every_possible_state"]),
        ("Fast API max seconds", payload["measured_evidence"]["fast_optimal_oracle_api_max_runtime_seconds"]),
        ("Resident hard max seconds", payload["measured_evidence"]["resident_certification_max_runtime_seconds"]),
        ("Resident speedup", payload["measured_evidence"]["resident_speedup"]),
        ("Nissy optimal stress max seconds", payload["measured_evidence"]["nissy_optimal_stress_max_runtime_seconds"]),
        (
            "Nissy-core direct max seconds",
            payload["measured_evidence"]["nissy_core_direct_thesis_max_runtime_seconds"],
        ),
        ("Portfolio Nissy-first max seconds", payload["measured_evidence"]["portfolio_nissy_first_max_runtime_seconds"]),
        (
            "Portfolio state recovery max seconds",
            payload["measured_evidence"]["portfolio_nissy_state_recovery_max_runtime_seconds"],
        ),
        (
            "Portfolio direct state max seconds",
            payload["measured_evidence"]["portfolio_nissy_core_direct_state_max_runtime_seconds"],
        ),
        ("Race oracle max seconds", payload["measured_evidence"]["race_optimal_oracle_max_runtime_seconds"]),
        (
            "Race direct state seconds",
            payload["measured_evidence"]["race_nissy_core_direct_max_runtime_seconds"],
        ),
        (
            "Resident race max seconds",
            payload["measured_evidence"]["resident_race_optimal_oracle_max_runtime_seconds"],
        ),
        (
            "Resident race direct seconds",
            payload["measured_evidence"]["resident_race_nissy_core_direct_max_runtime_seconds"],
        ),
        (
            "Universal direct state seconds",
            payload["measured_evidence"]["universal_nissy_core_direct_max_runtime_seconds"],
        ),
        (
            "Universal H48 symmetry seconds",
            payload["measured_evidence"]["universal_h48_symmetry_max_runtime_seconds"],
        ),
        (
            "Universal H48 batch seconds",
            payload["measured_evidence"]["universal_resident_h48_batch_max_runtime_seconds"],
        ),
        (
            "Universal CLI max seconds",
            payload["measured_evidence"]["universal_oracle_cli_max_runtime_seconds"],
        ),
        (
            "Universal CLI broader seconds",
            payload["measured_evidence"]["universal_oracle_cli_broader_max_runtime_seconds"],
        ),
        (
            "Universal CLI adaptive seconds",
            payload["measured_evidence"]["universal_oracle_cli_adaptive_max_runtime_seconds"],
        ),
        (
            "Universal CLI expanded seconds",
            payload["measured_evidence"]["universal_oracle_cli_expanded_adaptive_max_runtime_seconds"],
        ),
        (
            "Universal CLI live no-shortcuts seconds",
            payload["measured_evidence"]["universal_oracle_cli_live_no_shortcuts_max_runtime_seconds"],
        ),
        (
            "Universal CLI live no-shortcuts broader seconds",
            payload["measured_evidence"][
                "universal_oracle_cli_live_no_shortcuts_broader_max_runtime_seconds"
            ],
        ),
        (
            "Universal CLI known-distance 19 seconds",
            payload["measured_evidence"]["universal_oracle_cli_known_distance_19_max_runtime_seconds"],
        ),
        (
            "Universal CLI known-distance 20 seconds",
            payload["measured_evidence"]["universal_oracle_cli_known_distance_20_max_runtime_seconds"],
        ),
        (
            "Portfolio superflip fallback seconds",
            payload["measured_evidence"]["portfolio_superflip_fallback_runtime_seconds"],
        ),
        (
            "Portfolio superflip cache seconds",
            payload["measured_evidence"]["portfolio_superflip_certificate_cache_runtime_seconds"],
        ),
        (
            "Certificate symmetry cases",
            payload["measured_evidence"]["certificate_cache_symmetry_closure_case_count"],
        ),
        (
            "Expanded certificate symmetry cases",
            payload["measured_evidence"]["certificate_cache_expanded_symmetry_closure_case_count"],
        ),
        (
            "Learned certificate replay seconds",
            payload["measured_evidence"]["learned_certificate_cache_max_replay_runtime_seconds"],
        ),
        (
            "Live symmetry batch max seconds",
            payload["measured_evidence"]["universal_symmetry_oracle_max_runtime_seconds"],
        ),
        ("Nissy optimal table bytes", payload["measured_evidence"]["nissy_public_optimal_table_size_bytes"]),
        ("h48h8 probe status", payload["measured_evidence"]["h48_generation_probe_status"]),
        ("h48h8 probe allocated bytes", payload["measured_evidence"]["h48_generation_probe_partial_allocated_size_bytes"]),
        (
            "h48h8 detached status",
            payload["measured_evidence"]["h48_stronger_table_detached_status_status"],
        ),
        (
            "h48h8 detached waits",
            payload["measured_evidence"]["h48_stronger_table_detached_status_waitsafe_sample_count"],
        ),
    ]
    body = [
        "{\\small\n",
        "\\begin{tabular}{@{}p{0.54\\linewidth}p{0.34\\linewidth}@{}}\n",
        "\\hline\n",
        "Check & Value \\\\\n",
        "\\hline\n",
    ]
    for name, value in rows:
        body.append(f"{_tex(name)} & {_tex(value)} \\\\\n")
    body.extend(["\\hline\n", "\\end{tabular}\n", "}\n"])
    table_path.write_text("".join(body), encoding="utf-8")
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "H48 backend evidence summary (saved corpus only). Summarises "
            "machine-checked evidence from the saved H48 corpus plus cited "
            "external results; does NOT certify fast-optimal coverage of all "
            "~4.3e19 reachable cube states."
        ),
    )
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--artifact-suffix", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    solver = canonical_h48_solver(args.solver)
    artifact_suffix = args.artifact_suffix
    if artifact_suffix is None:
        artifact_suffix = solver
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    payload = build_contract_payload(root=args.root, profile=args.profile, seed=args.seed, solver=solver)
    output = (
        args.root
        / "results"
        / "processed"
        / f"h48_oracle_contract_seed_{args.seed}_{args.profile}{suffix}.json"
    )
    write_json(output, payload)
    table = write_table(args.root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
