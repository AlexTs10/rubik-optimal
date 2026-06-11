#!/usr/bin/env python
"""Render reproducible cloud runbook scripts for hard-tail campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json  # noqa: E402
from rubik_optimal.tables.h48 import canonical_h48_solver  # noqa: E402


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _script_root_prelude(default_threads: int) -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'ROOT="${RUBIK_OPTIMAL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"\n'
        'cd "$ROOT"\n'
        'if [ "${RUBIK_OPTIMAL_USE_VENV:-1}" != "0" ] && [ -f "$ROOT/.venv/bin/activate" ]; then\n'
        '  # shellcheck disable=SC1091\n'
        '  source "$ROOT/.venv/bin/activate"\n'
        "fi\n"
        "export PYTHONUNBUFFERED=1\n"
        'export RUBIK_OPTIMAL_H48_TABLE_ROOT="${RUBIK_OPTIMAL_H48_TABLE_ROOT:-data/generated/h48}"\n'
        f'export RUBIK_OPTIMAL_H48_THREADS="${{RUBIK_OPTIMAL_H48_THREADS:-{default_threads}}}"\n'
        f'export RUBIK_OPTIMAL_THREADS="${{RUBIK_OPTIMAL_THREADS:-{default_threads}}}"\n'
        "\n"
    )


def _bootstrap_cloud_machine_script(
    *,
    default_threads: int,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
    machine: dict[str, Any] | None,
) -> str:
    preflight_command = _cloud_preflight_command(
        profile=profile,
        seed=seed,
        solver=solver,
        run_suffix=run_suffix,
        default_threads=default_threads,
        machine=machine,
        require_target_table=False,
        role="bootstrap",
    )
    body = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="${{RUBIK_OPTIMAL_ROOT:-$(cd "$(dirname "${{BASH_SOURCE[0]}}")/../.." && pwd)}}"
cd "$ROOT"
BOOTSTRAP_PYTHON="${{RUBIK_OPTIMAL_BOOTSTRAP_PYTHON:-python3}}"
if [ ! -x "$ROOT/.venv/bin/python" ] || [ "${{RUBIK_OPTIMAL_BOOTSTRAP_FORCE:-0}}" = "1" ]; then
  "$BOOTSTRAP_PYTHON" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
export PYTHONUNBUFFERED=1
export RUBIK_OPTIMAL_H48_TABLE_ROOT="${{RUBIK_OPTIMAL_H48_TABLE_ROOT:-data/generated/h48}}"
export RUBIK_OPTIMAL_H48_THREADS="${{RUBIK_OPTIMAL_H48_THREADS:-{default_threads}}}"
export RUBIK_OPTIMAL_THREADS="${{RUBIK_OPTIMAL_THREADS:-{default_threads}}}"
python -m rubik_optimal.cli --help >/dev/null
python -m py_compile \\
  scripts/cloud_hardtail_preflight.py \\
  scripts/create_h48_table_bundle.py \\
  scripts/install_h48_table_bundle.py \\
  scripts/run_cloud_hardtail_campaign.py \\
  scripts/evaluate_cloud_hardtail_campaign.py \\
  scripts/generate_h48_oracle_contract.py \\
  scripts/thesis_audit.py
{shlex.join(preflight_command)} "$@"
"""
    return body


def _campaign_script(
    *,
    plan_relative: str,
    run_suffix: str,
    timeout_scale: float,
    default_threads: int,
    dry_run: bool,
    workload_ids: list[str] | None = None,
    kinds: list[str] | None = None,
    evaluate_after: bool = True,
    pre_commands: list[list[str]] | None = None,
) -> str:
    args = [
        "python",
        "scripts/run_cloud_hardtail_campaign.py",
        "--plan",
        plan_relative,
        "--resume",
        "--stop-on-fail",
        "--use-estimated-timeouts",
        "--timeout-scale",
        str(timeout_scale),
        "--artifact-suffix",
        run_suffix,
        "--evaluation-suffix",
        run_suffix,
    ]
    for workload_id in workload_ids or []:
        args.extend(["--workload-id", workload_id])
    for kind in kinds or []:
        args.extend(["--kind", kind])
    if dry_run:
        args.append("--dry-run")
    if not evaluate_after:
        args.append("--no-evaluate")
    commands = [shlex.join(command) for command in pre_commands or []]
    commands.append(shlex.join(args) + ' "$@"')
    return _script_root_prelude(default_threads) + "\n".join(commands) + "\n"


def _campaign_workload_ids_excluding(
    plan: dict[str, Any],
    excluded_ids: set[str],
) -> list[str]:
    return [
        str(workload.get("id"))
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and workload.get("id") is not None
        and str(workload.get("id")) not in excluded_ids
    ]


def _evaluate_script(*, plan_relative: str, output_suffix: str, default_threads: int) -> str:
    return (
        _script_root_prelude(default_threads)
        + shlex.join(
            [
                "python",
                "scripts/evaluate_cloud_hardtail_campaign.py",
                "--plan",
                plan_relative,
                "--output-suffix",
                output_suffix,
            ]
        )
        + ' "$@"\n'
    )


def _collect_script(*, archive_name: str, default_threads: int, extra_patterns: list[str] | None = None) -> str:
    patterns = [
        "results/processed/cloud_hardtail_*.json",
        "results/processed/cloud_hardtail_campaign_*.json",
        "results/processed/cloud_hardtail_workload_*.json",
        "results/processed/cloud_hardtail_preflight_*.json",
        "results/processed/h48_oracle_contract_seed_*.json",
        "results/processed/h48_metadata_seed_*.json",
        "results/processed/h48_worker_table_validation_*.json",
        "results/processed/thesis_audit.json",
        "results/processed/h48_stronger_table_campaign_*.json",
        "results/processed/rubikoptimal_oracle_corpus_*.json",
        "results/processed/known_distance_sweep_*.json",
        "results/processed/universal_oracle_cli_*.json",
        "thesis/tables/cloud_hardtail_campaign_plan*.tex",
    ]
    patterns.extend(extra_patterns or [])
    embedded = f"""
import tarfile
from pathlib import Path

archive = Path({archive_name!r})
archive.parent.mkdir(parents=True, exist_ok=True)
patterns = {patterns!r}
paths = []
for pattern in patterns:
    paths.extend(path for path in Path('.').glob(pattern) if path.is_file())
paths = sorted(set(paths))
with tarfile.open(archive, 'w:gz') as tar:
    for path in paths:
        tar.add(path, arcname=str(path))
print({{'archive': str(archive), 'file_count': len(paths)}})
"""
    return (
        _script_root_prelude(default_threads)
        + "python - <<'PY'\n"
        + embedded.strip()
        + "\nPY\n"
    )


def _unpack_script(*, default_threads: int) -> str:
    body = """
if [ "$#" -eq 0 ]; then
  echo "usage: $0 results/cloud_hardtail_artifacts_*.tar.gz [...]" >&2
  exit 2
fi
for archive in "$@"; do
  tar -xzf "$archive" -C "$ROOT"
done
"""
    return _script_root_prelude(default_threads) + body.lstrip()


def _install_prerequisite_tables_script(
    *,
    default_threads: int,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
) -> str:
    body = f"""
if [ "$#" -ne 1 ]; then
  echo "usage: $0 path/to/cloud_hardtail_prerequisite_tables_*.tar.gz-or-directory" >&2
  exit 2
fi
python scripts/install_h48_table_bundle.py \\
  --profile {shlex.quote(profile)} \\
  --seed {int(seed)} \\
  --solver {shlex.quote(solver)} \\
  --bundle "$1" \\
  --artifact-suffix {shlex.quote(run_suffix + "_worker_install")} \\
  --force
"""
    return _script_root_prelude(default_threads) + body.lstrip()


def _collect_prerequisite_table_parts_script(
    *,
    default_threads: int,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
) -> str:
    parts_dir = f"results/cloud_hardtail_prerequisite_tables_{run_suffix}_parts"
    body = f"""
PARTS_DIR={shlex.quote(parts_dir)}
PART_SIZE_MIB="${{H48_TABLE_BUNDLE_PART_SIZE_MIB:-1024}}"
python scripts/create_h48_table_bundle.py \\
  --profile {shlex.quote(profile)} \\
  --seed {int(seed)} \\
  --solver {shlex.quote(solver)} \\
  --output-dir "$PARTS_DIR" \\
  --part-size-mib "$PART_SIZE_MIB" \\
  --artifact-suffix {shlex.quote(run_suffix + "_prerequisite_parts")} \\
  "$@"
"""
    return _script_root_prelude(default_threads) + body.lstrip()


def _extract_option(args: list[Any], flag: str, default: str | None = None) -> str | None:
    normalized = [str(arg) for arg in args]
    try:
        index = normalized.index(flag)
    except ValueError:
        return default
    if index + 1 >= len(normalized):
        return default
    return normalized[index + 1]


def _stronger_table_generation_options(plan: dict[str, Any], *, solver: str) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for workload in plan.get("workloads", []):
        if not isinstance(workload, dict):
            continue
        if workload.get("kind") != "h48_stronger_table_generation_and_certification":
            continue
        args = list(workload.get("command_args") or [])
        if "--target-solver" in [str(arg) for arg in args]:
            target = _extract_option(args, "--target-solver")
            if target and canonical_h48_solver(target) != canonical_h48_solver(solver):
                continue
        selected = workload
        break
    args = list(selected.get("command_args") or [])
    backend_flags = [
        str(arg).split("=", 1)[1]
        for arg in args
        if isinstance(arg, str) and arg.startswith("--backend-cflag=")
    ]
    return {
        "h48_gendata_workbatch": int(
            _extract_option(args, "--gendata-workbatch", str(plan.get("h48_gendata_workbatch") or 256))
            or 256
        ),
        "mmap_sync_mode": _extract_option(args, "--mmap-sync-mode", "sync") or "sync",
        "backend_extra_cflags": backend_flags,
        "skip_generation_distribution_scan": "--skip-generation-distribution-scan"
        in [str(arg) for arg in args],
    }


def _recover_prerequisite_metadata_script(
    *,
    default_threads: int,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
    h48_gendata_workbatch: int,
    mmap_sync_mode: str,
    backend_extra_cflags: list[str],
    skip_generation_distribution_scan: bool,
) -> str:
    command = [
        "python",
        "scripts/generate_h48_tables.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--threads",
        str(default_threads),
        "--mmap-output",
        "--gendata-workbatch",
        str(h48_gendata_workbatch),
        "--mmap-sync-mode",
        mmap_sync_mode,
        "--adopt-existing-table-metadata",
    ]
    for flag in backend_extra_cflags:
        command.append(f"--backend-cflag={flag}")
    if skip_generation_distribution_scan:
        command.append("--skip-generation-distribution-scan")
    validation_command = _h48_worker_validation_command(
        profile=profile,
        seed=seed,
        solver=solver,
        run_suffix=f"{run_suffix}_recovered",
    )
    body = f"""
H48_TABLE_ROOT="${{RUBIK_OPTIMAL_H48_TABLE_ROOT:-data/generated/h48}}"
TABLE="$H48_TABLE_ROOT"/{shlex.quote(f'{profile}_seed_{seed}/{solver}.bin')}
PARTIAL="$H48_TABLE_ROOT"/{shlex.quote(f'{profile}_seed_{seed}/.{solver}.bin.partial')}
if [ ! -f "$TABLE" ]; then
  echo "canonical H48 table $TABLE is missing; refusing metadata recovery" >&2
  if [ -f "$PARTIAL" ]; then
    echo "staged partial $PARTIAL exists, but mmap partial files can be full-size before completion and are not safe to adopt" >&2
  fi
  exit 2
fi
{shlex.join(command)}
{shlex.join(validation_command)}
"""
    return _script_root_prelude(default_threads) + body.lstrip()


def _h48_worker_validation_command(
    *,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
) -> list[str]:
    return [
        "python",
        "scripts/validate_h48_worker_table.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--artifact-suffix",
        f"{run_suffix}_worker",
        "--persistent-cache",
    ]


def _cloud_preflight_command(
    *,
    profile: str,
    seed: int,
    solver: str,
    run_suffix: str,
    default_threads: int,
    machine: dict[str, Any] | None,
    require_target_table: bool,
    role: str,
) -> list[str]:
    machine = machine or {}
    command = [
        "python",
        "scripts/cloud_hardtail_preflight.py",
        "--profile",
        profile,
        "--seed",
        str(seed),
        "--solver",
        solver,
        "--artifact-suffix",
        f"{run_suffix}_{role}",
        "--threads",
        str(default_threads),
        "--min-cpus",
        str(int(machine.get("cpu_count", default_threads))),
        "--min-memory-gib",
        str(float(machine.get("memory_gib", 64))),
        "--min-storage-gib",
        str(float(machine.get("local_nvme_gib", 250))),
    ]
    if require_target_table:
        command.append("--require-target-table")
    return command


def _finalize_script(
    *,
    plan_relative: str,
    run_suffix: str,
    timeout_scale: float,
    default_threads: int,
    profile: str,
    seed: int,
    solver: str,
) -> str:
    commands = [
        [
            "python",
            "scripts/run_cloud_hardtail_campaign.py",
            "--plan",
            plan_relative,
            "--kind",
            "postprocess_and_audit",
            "--resume",
            "--stop-on-fail",
            "--use-estimated-timeouts",
            "--timeout-scale",
            str(timeout_scale),
            "--artifact-suffix",
            f"{run_suffix}_postprocess",
            "--evaluation-suffix",
            f"{run_suffix}_postprocess",
            "--no-evaluate",
        ],
        [
            "python",
            "scripts/evaluate_cloud_hardtail_campaign.py",
            "--plan",
            plan_relative,
            "--output-suffix",
            f"{run_suffix}_precontract",
        ],
        [
            "python",
            "scripts/generate_h48_oracle_contract.py",
            "--profile",
            profile,
            "--seed",
            str(seed),
            "--solver",
            solver,
        ],
        ["python", "scripts/thesis_audit.py"],
        [
            "python",
            "scripts/evaluate_cloud_hardtail_campaign.py",
            "--plan",
            plan_relative,
            "--output-suffix",
            run_suffix,
        ],
        [
            "python",
            "scripts/generate_h48_oracle_contract.py",
            "--profile",
            profile,
            "--seed",
            str(seed),
            "--solver",
            solver,
        ],
        ["python", "scripts/thesis_audit.py"],
    ]
    return _script_root_prelude(default_threads) + "\n".join(shlex.join(command) for command in commands) + "\n"


def _single_machine_end_to_end_script(
    *,
    run_suffix: str,
    default_threads: int,
    requires_table_distribution_before_hardtail: bool,
    canary_reuses_full_prerequisites: bool,
) -> str:
    commands = [
        f"./{step}.sh"
        for step in _single_machine_run_order(
            requires_table_distribution_before_hardtail=requires_table_distribution_before_hardtail,
            canary_reuses_full_prerequisites=canary_reuses_full_prerequisites,
        )
    ]
    body = [
        "# This is a single-machine proof launcher for a capable cloud/idle box.",
        "# It is intentionally not a shortcut: all proof artifacts still must pass.",
        'RUNBOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'cd "$RUNBOOK_DIR"',
        f'echo "Running {run_suffix} end-to-end from $RUNBOOK_DIR"',
        *commands,
        'echo "Collected results archive and regenerated final contract/audit artifacts."',
    ]
    return _script_root_prelude(default_threads) + "\n".join(body) + "\n"


def _single_machine_run_order(
    *,
    requires_table_distribution_before_hardtail: bool,
    canary_reuses_full_prerequisites: bool,
) -> list[str]:
    steps = ["bootstrap_cloud_machine", "preflight_leader"]
    if canary_reuses_full_prerequisites:
        steps.extend(
            [
                "run_full_prerequisites",
                "preflight_worker",
                "validate_prerequisite_tables",
                "run_canary_after_prerequisites",
            ]
        )
    else:
        steps.append("run_canary")
    if requires_table_distribution_before_hardtail:
        for step in [
            "run_full_prerequisites",
            "preflight_worker",
            "validate_prerequisite_tables",
        ]:
            if step not in steps:
                steps.append(step)
    steps.extend(["run_full", "evaluate_full", "collect_results", "finalize_full_after_collect"])
    return steps


def _manual_staged_run_order(
    *,
    requires_table_distribution_before_hardtail: bool,
    canary_reuses_full_prerequisites: bool,
    has_full_plan: bool,
) -> list[str]:
    steps = ["bootstrap_cloud_machine", "preflight_leader", "dry_run_canary"]
    if canary_reuses_full_prerequisites:
        steps.extend(
            [
                "run_full_prerequisites",
                "collect_prerequisite_tables",
                "install_prerequisite_tables",
                "preflight_worker",
                "validate_prerequisite_tables",
                "run_canary_after_prerequisites",
            ]
        )
    else:
        steps.append("run_canary")
        if requires_table_distribution_before_hardtail:
            steps.extend(
                [
                    "run_full_prerequisites",
                    "collect_prerequisite_tables",
                    "install_prerequisite_tables",
                    "preflight_worker",
                    "validate_prerequisite_tables",
                ]
            )
    if has_full_plan:
        steps.extend(["run_full", "evaluate_full", "collect_results"])
    return steps


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _file_fingerprint(root: Path, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    mode = path.stat().st_mode & 0o777
    return {
        "path": _relative(root, path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode_octal": oct(mode),
    }


def _recommended_threads(**plans: dict[str, Any]) -> int:
    values = [
        int(plan.get("worker_threads", 1))
        for plan in plans.values()
        if isinstance(plan.get("worker_threads"), int)
    ]
    return max(values) if values else 16


def _plan_summary(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    workloads = [workload for workload in plan.get("workloads", []) if isinstance(workload, dict)]
    required = [
        workload
        for workload in workloads
        if workload.get("required_for_fast_every_state_claim", True) is True
    ]
    by_kind: dict[str, int] = {}
    for workload in workloads:
        kind = str(workload.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    required_by_kind: dict[str, int] = {}
    for workload in required:
        kind = str(workload.get("kind", "unknown"))
        required_by_kind[kind] = required_by_kind.get(kind, 0) + 1
    return {
        "objective": plan.get("objective"),
        "claim_scope": plan.get("claim_scope"),
        "profile": plan.get("profile"),
        "seed": plan.get("seed"),
        "solver": plan.get("solver"),
        "distance": plan.get("distance"),
        "hardtail_strategy": plan.get("hardtail_strategy"),
        "hardtail_execution_mode": plan.get("hardtail_execution_mode"),
        "hardtail_state_count": plan.get("hardtail_state_count"),
        "worker_threads": plan.get("worker_threads"),
        "h48_gendata_workbatch": plan.get("h48_gendata_workbatch"),
        "workload_count": len(workloads),
        "required_workload_count": len(required),
        "workload_count_by_kind": by_kind,
        "required_workload_count_by_kind": required_by_kind,
        "required_workload_ids": [str(workload.get("id")) for workload in required],
        "hardtail_prerequisite_workload_ids": [
            str(workload_id)
            for workload_id in plan.get("hardtail_prerequisite_workload_ids", [])
        ],
        "requires_table_distribution_before_hardtail": bool(
            plan.get("requires_table_distribution_before_hardtail")
        ),
        "recommended_minimum_machine": plan.get("recommended_minimum_cloud_machine"),
        "fast_runtime_proven_for_every_possible_state": plan.get(
            "fast_runtime_proven_for_every_possible_state"
        ),
    }


def _readme(
    *,
    canary_plan_relative: str,
    full_plan_relative: str | None,
    run_suffix: str,
    default_threads: int,
    timeout_scale: float,
    canary_machine: dict[str, Any] | None,
    full_machine: dict[str, Any] | None,
    parallel_machine_count: int,
    parallel_estimate: dict[str, Any],
    solver: str,
    requires_table_distribution_before_hardtail: bool,
    canary_reuses_full_prerequisites: bool,
) -> str:
    machine = full_machine or canary_machine or {}
    runbook_dir = "./results/cloud_hardtail_runbook_" + run_suffix
    lines = [
        "# Large-machine hard-tail campaign runbook",
        "",
        "This runbook is execution infrastructure, not proof by itself.",
        "The every-state fast-runtime claim is still false until the full-scope campaign passes and the contract flips.",
        "AWS is not required by this runbook. Use the generic SSH/non-AWS wrapper for an approved PC or other non-AWS host; do not use AWS helper scripts unless the correct account is explicitly reauthorized.",
        "",
        "Recommended minimum machine:",
        f"- CPUs: {machine.get('cpu_count', default_threads)}",
        f"- RAM GiB: {machine.get('memory_gib', 64)}",
        f"- Local NVMe GiB: {machine.get('local_nvme_gib', 250)} total storage class, not empty-space requirement",
        "- Free H48 workspace is checked separately by `target_h48_workspace` in the preflight artifact.",
        "",
        "Choose one execution mode:",
        "1. Copy or check out this repository on the approved large machine, including generated tables and `.codex_external` data.",
        f"2. Run `{runbook_dir}/bootstrap_cloud_machine.sh` once to create/use `.venv`, install the repository, check proof scripts, and run the leader preflight.",
        f"3. For a single capable machine, run `{runbook_dir}/run_end_to_end_single_machine.sh`.",
        "4. For staged/manual or parallel execution, do not also run the one-shot launcher; follow the staged order below.",
        "",
        "Manual/staged order:",
        f"1. Run `{runbook_dir}/bootstrap_cloud_machine.sh` and inspect the bootstrap/preflight artifact.",
        f"2. Run `{runbook_dir}/preflight_leader.sh` and inspect the preflight artifact.",
        f"3. Run `{runbook_dir}/dry_run_canary.sh` to verify command construction without spending search time.",
    ]
    if full_plan_relative:
        if requires_table_distribution_before_hardtail:
            if canary_reuses_full_prerequisites:
                lines.extend(
                    [
                        f"4. Run `{runbook_dir}/run_full_prerequisites.sh` first.",
                        f"5. Run `{runbook_dir}/collect_prerequisite_tables.sh` and copy that archive to every hard-tail worker.",
                        f"   For unreliable large transfers, run `{runbook_dir}/collect_prerequisite_table_parts.sh` instead and copy the resulting split-parts directory.",
                        f"6. On each worker, run `{runbook_dir}/install_prerequisite_tables.sh path/to/cloud_hardtail_prerequisite_tables_*.tar.gz`.",
                        "   The installer also accepts the split-parts directory created by `collect_prerequisite_table_parts.sh`.",
                        f"7. Run `{runbook_dir}/preflight_worker.sh` on every hard-tail worker.",
                        f"8. Run `{runbook_dir}/validate_prerequisite_tables.sh` on every hard-tail worker.",
                        f"9. Run `{runbook_dir}/run_canary_after_prerequisites.sh`; this skips the shared stronger-table workload in the canary plan.",
                        "- Do not run `run_canary.sh` after the shared prerequisite path; that would spend the H48 prerequisite under the canary plan instead of reusing the full-plan artifact.",
                        "- The single-machine end-to-end launcher also uses this prerequisite-first path so the expensive H48 table campaign is not run once under the canary artifact name and again under the full-plan artifact name.",
                    ]
                )
                next_step = 10
            else:
                lines.append(f"4. Run `{runbook_dir}/run_canary.sh`.")
                next_step = 5
                lines.extend(
                    [
                        f"{next_step}. Run `{runbook_dir}/run_full_prerequisites.sh` first.",
                        f"{next_step + 1}. Run `{runbook_dir}/collect_prerequisite_tables.sh` and copy that archive to every hard-tail worker.",
                        f"   For unreliable large transfers, run `{runbook_dir}/collect_prerequisite_table_parts.sh` instead and copy the resulting split-parts directory.",
                        f"{next_step + 2}. On each worker, run `{runbook_dir}/install_prerequisite_tables.sh path/to/cloud_hardtail_prerequisite_tables_*.tar.gz`.",
                        "   The installer also accepts the split-parts directory created by `collect_prerequisite_table_parts.sh`.",
                        f"{next_step + 3}. Run `{runbook_dir}/preflight_worker.sh` on every hard-tail worker.",
                        f"{next_step + 4}. Run `{runbook_dir}/validate_prerequisite_tables.sh` on every hard-tail worker.",
                    ]
                )
                next_step += 5
            lines.extend(
                [
                    "   This writes `results/processed/h48_worker_table_validation_*.json` worker-side checksum evidence.",
                    "   The full and per-machine hard-tail scripts also re-run target-table validation before search.",
                    "   If prerequisite generation completed the canonical H48 table file but metadata/finalization was interrupted, run `recover_prerequisite_metadata.sh`; it refuses staged `.partial` files and validates the recovered table checksum.",
                    f"{next_step}. Only after the stronger H48 table and metadata validate on each worker, run the full hard-tail scripts.",
                ]
            )
        else:
            lines.append(f"4. Run `{runbook_dir}/run_canary.sh`.")
        lines.extend(
            [
                f"{(next_step + 1) if requires_table_distribution_before_hardtail else 5}. Run `{runbook_dir}/run_full.sh` for a single-machine full execution, or use the parallel scripts below.",
                f"{(next_step + 2) if requires_table_distribution_before_hardtail else 6}. Run `{runbook_dir}/evaluate_full.sh` if evaluation must be refreshed.",
                f"{(next_step + 3) if requires_table_distribution_before_hardtail else 7}. Run `{runbook_dir}/collect_results.sh` and copy the archive back.",
            ]
        )
        if parallel_estimate.get("steady_state_after_prerequisites_hours_scaled") is not None:
            lines.append(
                f"- If prerequisite tables are already generated and validated, the post-prerequisite budget is about `{parallel_estimate.get('steady_state_after_prerequisites_hours_scaled')}` scaled hours."
            )
        if parallel_machine_count > 1:
            lines.extend(
                [
                    "",
                    "Parallel full-campaign option:",
                    f"- Start `{parallel_machine_count}` approved large machines from the same repo snapshot.",
                    *(
                        [
                            "- If this plan uses a just-generated stronger H48 table, run `run_full_prerequisites.sh` once first and copy `cloud_hardtail_prerequisite_tables_*.tar.gz` to every worker.",
                            "- For a 30 GiB-class H48H10 table, `collect_prerequisite_table_parts.sh` can create a manifest plus checksummed parts for resumable transfer; `install_prerequisite_tables.sh` accepts that directory.",
                            "- Run `install_prerequisite_tables.sh path/to/cloud_hardtail_prerequisite_tables_*.tar.gz` on every worker before preflight.",
                            "- Run `preflight_worker.sh` on every worker after installing the stronger H48 table archive.",
                            "- The generated hard-tail worker scripts run `validate_h48_worker_table.py` before search and write `results/processed/h48_worker_table_validation_*.json`.",
                            "- If a prerequisite run completed the canonical H48 table file but metadata/finalization was interrupted, run `recover_prerequisite_metadata.sh`; it refuses staged `.partial` files and validates the recovered table checksum.",
                        ]
                        if requires_table_distribution_before_hardtail
                        else []
                    ),
                    "- On each worker, run its matching `run_full_machine_XX.sh` script.",
                    "- Run `run_full_nonshard.sh` on one additional/leader machine for remaining non-shard hardcase work, if that script exists.",
                    "- Run `collect_results.sh` on every machine, copy the archives to one central checkout, then use `unpack_results.sh`.",
                    "- Run `finalize_full_after_collect.sh` in the central checkout.",
                    f"- Estimated parallel wall budget with timeout scale: about `{parallel_estimate.get('estimated_wall_hours_scaled')}` hours.",
                ]
            )
    else:
        lines.append("4. No full plan was provided to this runbook.")
    lines.extend(
        [
            "",
            "Key plans:",
            f"- Canary: `{canary_plan_relative}`",
            f"- Full: `{full_plan_relative or 'not provided'}`",
            "",
            "Default runtime settings:",
            f"- `RUBIK_OPTIMAL_H48_THREADS={default_threads}` unless overridden",
            f"- `RUBIK_OPTIMAL_THREADS={default_threads}` unless overridden",
            f"- estimated workload timeout scale: `{timeout_scale}`",
            f"- parallel machine count in generated shard scripts: `{parallel_machine_count}`",
            "",
            "Result interpretation:",
            "- A dry-run or canary pass does not prove the final claim.",
            "- The full plan must pass all required workloads.",
            f"- `results/processed/h48_oracle_contract_seed_2026_thesis_{solver}.json` must record `fast_runtime_proven_for_every_possible_state: true`.",
            "- `scripts/thesis_audit.py` must still pass the implementation, repository, research, and scale gates.",
            "",
        ]
    )
    return "\n".join(lines)


def _workloads_by_kind(plan: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict) and workload.get("kind") == kind
    ]


def _hardtail_workloads(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and workload.get("kind")
        in {
            "public_known_distance_hardtail_sweep",
            "public_known_distance_hardtail_batch",
        }
    ]


def _stronger_table_artifact_patterns(plan: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    for workload in plan.get("workloads", []):
        if not isinstance(workload, dict):
            continue
        if workload.get("kind") != "h48_stronger_table_generation_and_certification":
            continue
        for artifact in workload.get("expected_artifacts", []):
            if not isinstance(artifact, str):
                continue
            if artifact.endswith(".bin") or artifact.endswith(".json"):
                patterns.append(artifact)
    return sorted(set(patterns))


def _stronger_workloads_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(workload.get("id")): workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and workload.get("kind") == "h48_stronger_table_generation_and_certification"
        and workload.get("id") is not None
    }


def _shared_prerequisite_ids(canary_plan: dict[str, Any], full_plan: dict[str, Any]) -> list[str]:
    canary_ids = {
        str(workload_id)
        for workload_id in canary_plan.get("hardtail_prerequisite_workload_ids", [])
    }
    full_ids = {
        str(workload_id)
        for workload_id in full_plan.get("hardtail_prerequisite_workload_ids", [])
    }
    canary_by_id = _stronger_workloads_by_id(canary_plan)
    full_by_id = _stronger_workloads_by_id(full_plan)
    shared: list[str] = []
    for workload_id in sorted(canary_ids.intersection(full_ids)):
        canary = canary_by_id.get(workload_id)
        full = full_by_id.get(workload_id)
        if not canary or not full:
            continue
        if canary.get("command_args") != full.get("command_args"):
            continue
        if canary.get("expected_artifacts") != full.get("expected_artifacts"):
            continue
        shared.append(workload_id)
    return shared


def _balanced_assignments(workloads: list[dict[str, Any]], machine_count: int) -> list[list[dict[str, Any]]]:
    bins: list[list[dict[str, Any]]] = [[] for _ in range(max(1, machine_count))]
    totals = [0.0 for _ in bins]
    for workload in sorted(
        workloads,
        key=lambda item: float(item.get("estimated_wall_seconds") or 0.0),
        reverse=True,
    ):
        index = min(range(len(bins)), key=lambda candidate: totals[candidate])
        bins[index].append(workload)
        totals[index] += float(workload.get("estimated_wall_seconds") or 0.0)
    return bins


def _parallel_estimate(
    *,
    plan: dict[str, Any],
    assignments: list[list[dict[str, Any]]],
    timeout_scale: float,
) -> dict[str, Any]:
    prerequisite_ids = {
        str(workload_id)
        for workload_id in plan.get("hardtail_prerequisite_workload_ids", [])
    }
    prerequisite_seconds = sum(
        float(workload.get("estimated_wall_seconds") or 0.0)
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict) and str(workload.get("id")) in prerequisite_ids
    )
    shard_machine_seconds = [
        sum(float(workload.get("estimated_wall_seconds") or 0.0) for workload in group)
        for group in assignments
    ]
    nonshard_compute = [
        workload
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict)
        and str(workload.get("id")) not in prerequisite_ids
        and workload.get("kind")
        in {
            "h48_stronger_table_generation_and_certification",
            "rubikoptimal_table_complete_hardcase",
        }
    ]
    nonshard_seconds = sum(float(workload.get("estimated_wall_seconds") or 0.0) for workload in nonshard_compute)
    postprocess_seconds = sum(
        float(workload.get("estimated_wall_seconds") or 0.0)
        for workload in plan.get("workloads", [])
        if isinstance(workload, dict) and workload.get("kind") == "postprocess_and_audit"
    )
    hardtail_stage_seconds = max(max(shard_machine_seconds, default=0.0), nonshard_seconds)
    raw_wall = prerequisite_seconds + hardtail_stage_seconds + postprocess_seconds
    steady_state_wall = hardtail_stage_seconds + postprocess_seconds
    return {
        "machine_count": len(assignments),
        "prerequisite_hours_raw": round(prerequisite_seconds / 3600.0, 3),
        "shard_machine_hours_raw": [round(seconds / 3600.0, 3) for seconds in shard_machine_seconds],
        "nonshard_compute_hours_raw": round(nonshard_seconds / 3600.0, 3),
        "postprocess_hours_raw": round(postprocess_seconds / 3600.0, 3),
        "hardtail_stage_hours_raw": round(hardtail_stage_seconds / 3600.0, 3),
        "steady_state_after_prerequisites_hours_raw": round(steady_state_wall / 3600.0, 3),
        "steady_state_after_prerequisites_hours_scaled": round(
            steady_state_wall * timeout_scale / 3600.0,
            3,
        ),
        "estimated_wall_hours_raw": round(raw_wall / 3600.0, 3),
        "estimated_wall_hours_scaled": round(raw_wall * timeout_scale / 3600.0, 3),
    }


def build_cloud_hardtail_runbook(
    *,
    root: Path,
    canary_plan_path: Path,
    full_plan_path: Path | None,
    output_dir: Path,
    run_suffix: str,
    timeout_scale: float = 1.25,
    parallel_machines: int = 1,
) -> tuple[dict[str, Any], Path]:
    canary_plan_path = canary_plan_path if canary_plan_path.is_absolute() else root / canary_plan_path
    full_plan_path = (
        full_plan_path if full_plan_path is None or full_plan_path.is_absolute() else root / full_plan_path
    )
    canary_plan = _load_json(canary_plan_path)
    full_plan = _load_json(full_plan_path) if full_plan_path else None
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_suffix = _safe_id(run_suffix)
    default_threads = _recommended_threads(canary=canary_plan, full=full_plan or {})
    canary_relative = _relative(root, canary_plan_path)
    full_relative = _relative(root, full_plan_path) if full_plan_path else None

    files: dict[str, Path] = {}
    solver = canonical_h48_solver(str((full_plan or canary_plan).get("solver", "h48h7")))
    profile = str((full_plan or canary_plan).get("profile", "thesis"))
    seed = int((full_plan or canary_plan).get("seed", 2026))
    recommended_machine = (full_plan or canary_plan).get("recommended_minimum_cloud_machine")
    leader_preflight = _cloud_preflight_command(
        profile=profile,
        seed=seed,
        solver=solver,
        run_suffix=safe_suffix,
        default_threads=default_threads,
        machine=recommended_machine,
        require_target_table=False,
        role="leader",
    )
    files["bootstrap_cloud_machine"] = output_dir / "bootstrap_cloud_machine.sh"
    _write_executable(
        files["bootstrap_cloud_machine"],
        _bootstrap_cloud_machine_script(
            default_threads=default_threads,
            profile=profile,
            seed=seed,
            solver=solver,
            run_suffix=safe_suffix,
            machine=recommended_machine,
        ),
    )
    files["preflight_leader"] = output_dir / "preflight_leader.sh"
    _write_executable(
        files["preflight_leader"],
        _script_root_prelude(default_threads) + shlex.join(leader_preflight) + ' "$@"\n',
    )
    files["run_canary"] = output_dir / "run_canary.sh"
    _write_executable(
        files["run_canary"],
        _campaign_script(
            plan_relative=canary_relative,
            run_suffix=safe_suffix,
            timeout_scale=timeout_scale,
            default_threads=default_threads,
            dry_run=False,
            pre_commands=[leader_preflight],
        ),
    )
    files["dry_run_canary"] = output_dir / "dry_run_canary.sh"
    _write_executable(
        files["dry_run_canary"],
        _campaign_script(
            plan_relative=canary_relative,
            run_suffix=f"{safe_suffix}_dryrun",
            timeout_scale=timeout_scale,
            default_threads=default_threads,
            dry_run=True,
        ),
    )

    if full_relative:
        full_prerequisite_ids = [
            str(workload_id)
            for workload_id in (full_plan or {}).get("hardtail_prerequisite_workload_ids", [])
        ]
        shared_canary_prerequisite_ids = (
            _shared_prerequisite_ids(canary_plan, full_plan or {}) if full_prerequisite_ids else []
        )
        full_pre_commands = [leader_preflight]
        if full_prerequisite_ids:
            validation_command = _h48_worker_validation_command(
                profile=str((full_plan or {}).get("profile", "thesis")),
                seed=int((full_plan or {}).get("seed", 2026)),
                solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
                run_suffix=safe_suffix,
            )
            worker_preflight_command = _cloud_preflight_command(
                profile=str((full_plan or {}).get("profile", "thesis")),
                seed=int((full_plan or {}).get("seed", 2026)),
                solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
                run_suffix=safe_suffix,
                default_threads=default_threads,
                machine=(full_plan or {}).get("recommended_minimum_cloud_machine"),
                require_target_table=True,
                role="worker",
            )
            files["run_full_prerequisites"] = output_dir / "run_full_prerequisites.sh"
            _write_executable(
                files["run_full_prerequisites"],
                _campaign_script(
                    plan_relative=full_relative,
                    run_suffix=f"{safe_suffix}_prereq",
                    timeout_scale=timeout_scale,
                    default_threads=default_threads,
                    dry_run=False,
                    workload_ids=full_prerequisite_ids,
                    evaluate_after=False,
                    pre_commands=[leader_preflight],
                ),
            )
            files["preflight_worker"] = output_dir / "preflight_worker.sh"
            _write_executable(
                files["preflight_worker"],
                _script_root_prelude(default_threads)
                + shlex.join(worker_preflight_command)
                + ' "$@"\n',
            )
            files["validate_prerequisite_tables"] = output_dir / "validate_prerequisite_tables.sh"
            _write_executable(
                files["validate_prerequisite_tables"],
                _script_root_prelude(default_threads)
                + shlex.join(validation_command)
                + ' "$@"\n',
            )
            full_pre_commands.extend([worker_preflight_command, validation_command])
            files["collect_prerequisite_tables"] = output_dir / "collect_prerequisite_tables.sh"
            _write_executable(
                files["collect_prerequisite_tables"],
                _collect_script(
                    archive_name=f"results/cloud_hardtail_prerequisite_tables_{safe_suffix}.tar.gz",
                    default_threads=default_threads,
                    extra_patterns=_stronger_table_artifact_patterns(full_plan or {}),
                ),
            )
            files["collect_prerequisite_table_parts"] = (
                output_dir / "collect_prerequisite_table_parts.sh"
            )
            _write_executable(
                files["collect_prerequisite_table_parts"],
                _collect_prerequisite_table_parts_script(
                    default_threads=default_threads,
                    profile=str((full_plan or {}).get("profile", "thesis")),
                    seed=int((full_plan or {}).get("seed", 2026)),
                    solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
                    run_suffix=safe_suffix,
                ),
            )
            files["install_prerequisite_tables"] = output_dir / "install_prerequisite_tables.sh"
            _write_executable(
                files["install_prerequisite_tables"],
                _install_prerequisite_tables_script(
                    default_threads=default_threads,
                    profile=str((full_plan or {}).get("profile", "thesis")),
                    seed=int((full_plan or {}).get("seed", 2026)),
                    solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
                    run_suffix=safe_suffix,
                ),
            )
            generation_options = _stronger_table_generation_options(
                full_plan or {},
                solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
            )
            files["recover_prerequisite_metadata"] = output_dir / "recover_prerequisite_metadata.sh"
            _write_executable(
                files["recover_prerequisite_metadata"],
                _recover_prerequisite_metadata_script(
                    default_threads=default_threads,
                    profile=str((full_plan or {}).get("profile", "thesis")),
                    seed=int((full_plan or {}).get("seed", 2026)),
                    solver=canonical_h48_solver(str((full_plan or {}).get("solver", "h48h7"))),
                    run_suffix=safe_suffix,
                    h48_gendata_workbatch=int(generation_options["h48_gendata_workbatch"]),
                    mmap_sync_mode=str(generation_options["mmap_sync_mode"]),
                    backend_extra_cflags=list(generation_options["backend_extra_cflags"]),
                    skip_generation_distribution_scan=bool(
                        generation_options["skip_generation_distribution_scan"]
                    ),
                ),
            )
            if shared_canary_prerequisite_ids:
                canary_after_prereq_ids = _campaign_workload_ids_excluding(
                    canary_plan,
                    set(shared_canary_prerequisite_ids),
                )
                files["run_canary_after_prerequisites"] = output_dir / "run_canary_after_prerequisites.sh"
                _write_executable(
                    files["run_canary_after_prerequisites"],
                    _campaign_script(
                        plan_relative=canary_relative,
                        run_suffix=f"{safe_suffix}_canary_after_prereq",
                        timeout_scale=timeout_scale,
                        default_threads=default_threads,
                        dry_run=False,
                        workload_ids=canary_after_prereq_ids,
                    ),
                )
        files["run_full"] = output_dir / "run_full.sh"
        _write_executable(
            files["run_full"],
            _campaign_script(
                plan_relative=full_relative,
                run_suffix=safe_suffix,
                timeout_scale=timeout_scale,
                default_threads=default_threads,
                dry_run=False,
                pre_commands=full_pre_commands,
            ),
        )
        nonshard_ids = [
            str(workload.get("id"))
            for workload in (full_plan or {}).get("workloads", [])
            if isinstance(workload, dict)
            and str(workload.get("id")) not in set(full_prerequisite_ids)
            and workload.get("kind")
            in {
                "h48_stronger_table_generation_and_certification",
                "rubikoptimal_table_complete_hardcase",
            }
        ]
        if nonshard_ids:
            files["run_full_nonshard"] = output_dir / "run_full_nonshard.sh"
            _write_executable(
                files["run_full_nonshard"],
                _campaign_script(
                    plan_relative=full_relative,
                    run_suffix=f"{safe_suffix}_nonshard",
                    timeout_scale=timeout_scale,
                    default_threads=default_threads,
                    dry_run=False,
                    workload_ids=nonshard_ids,
                    evaluate_after=False,
                ),
            )
        files["evaluate_full"] = output_dir / "evaluate_full.sh"
        _write_executable(
            files["evaluate_full"],
            _evaluate_script(
                plan_relative=full_relative,
                output_suffix=safe_suffix,
                default_threads=default_threads,
            ),
        )
        files["finalize_full_after_collect"] = output_dir / "finalize_full_after_collect.sh"
        _write_executable(
            files["finalize_full_after_collect"],
            _finalize_script(
                plan_relative=full_relative,
                run_suffix=safe_suffix,
                timeout_scale=timeout_scale,
                default_threads=default_threads,
                profile=str(full_plan.get("profile", "thesis")),
                seed=int(full_plan.get("seed", 2026)),
                solver=canonical_h48_solver(str(full_plan.get("solver", "h48h7"))),
            ),
        )

    parallel_assignments: list[list[dict[str, Any]]] = []
    parallel_script_assignments: list[list[dict[str, Any]]] = []
    parallel_estimate: dict[str, Any] = {
        "machine_count": max(1, int(parallel_machines)),
        "estimated_wall_hours_scaled": None,
    }
    if full_relative and full_plan:
        hardtail_workloads = _hardtail_workloads(full_plan)
        parallel_assignments = _balanced_assignments(hardtail_workloads, max(1, int(parallel_machines)))
        parallel_estimate = _parallel_estimate(
            plan=full_plan,
            assignments=parallel_assignments,
            timeout_scale=timeout_scale,
        )
        parallel_script_assignments = [group for group in parallel_assignments if group]
        for index, group in enumerate(parallel_script_assignments):
            key = f"run_full_machine_{index:02d}"
            machine_run_suffix = f"{safe_suffix}_m{index:02d}"
            files[key] = output_dir / f"{key}.sh"
            validation_pre_commands = []
            if full_prerequisite_ids:
                validation_pre_commands.append(
                    _cloud_preflight_command(
                        profile=str(full_plan.get("profile", "thesis")),
                        seed=int(full_plan.get("seed", 2026)),
                        solver=canonical_h48_solver(str(full_plan.get("solver", "h48h7"))),
                        run_suffix=machine_run_suffix,
                        default_threads=default_threads,
                        machine=full_plan.get("recommended_minimum_cloud_machine"),
                        require_target_table=True,
                        role="worker",
                    )
                )
                validation_pre_commands.append(
                    _h48_worker_validation_command(
                        profile=str(full_plan.get("profile", "thesis")),
                        seed=int(full_plan.get("seed", 2026)),
                        solver=canonical_h48_solver(str(full_plan.get("solver", "h48h7"))),
                        run_suffix=machine_run_suffix,
                    )
                )
            _write_executable(
                files[key],
                _campaign_script(
                    plan_relative=full_relative,
                    run_suffix=f"{safe_suffix}_m{index:02d}",
                    timeout_scale=timeout_scale,
                    default_threads=default_threads,
                    dry_run=False,
                    workload_ids=[str(workload.get("id")) for workload in group],
                    evaluate_after=False,
                    pre_commands=validation_pre_commands,
                ),
            )

    files["collect_results"] = output_dir / "collect_results.sh"
    _write_executable(
        files["collect_results"],
        _collect_script(
            archive_name=f"results/cloud_hardtail_artifacts_{safe_suffix}.tar.gz",
            default_threads=default_threads,
        ),
    )
    files["unpack_results"] = output_dir / "unpack_results.sh"
    _write_executable(
        files["unpack_results"],
        _unpack_script(default_threads=default_threads),
    )
    if full_relative:
        files["run_end_to_end_single_machine"] = output_dir / "run_end_to_end_single_machine.sh"
        _write_executable(
            files["run_end_to_end_single_machine"],
            _single_machine_end_to_end_script(
                run_suffix=safe_suffix,
                default_threads=default_threads,
                requires_table_distribution_before_hardtail=bool(full_prerequisite_ids),
                canary_reuses_full_prerequisites=bool(
                    "run_canary_after_prerequisites" in files
                ),
            ),
        )

    files["readme"] = output_dir / "README.md"
    files["readme"].write_text(
        _readme(
            canary_plan_relative=canary_relative,
            full_plan_relative=full_relative,
            run_suffix=safe_suffix,
            default_threads=default_threads,
            timeout_scale=timeout_scale,
            canary_machine=canary_plan.get("recommended_minimum_cloud_machine"),
            full_machine=full_plan.get("recommended_minimum_cloud_machine") if full_plan else None,
            parallel_machine_count=len(parallel_script_assignments) or max(1, int(parallel_machines)),
            parallel_estimate=parallel_estimate,
            solver=solver,
            requires_table_distribution_before_hardtail=bool(
                (full_plan or {}).get("requires_table_distribution_before_hardtail")
            ),
            canary_reuses_full_prerequisites=bool("run_canary_after_prerequisites" in files),
        ),
        encoding="utf-8",
    )

    shared_prerequisite_ids_for_payload = (
        _shared_prerequisite_ids(canary_plan, full_plan)
        if full_plan
        else []
    )
    requires_table_distribution = bool(
        (full_plan or {}).get("requires_table_distribution_before_hardtail")
    )
    single_machine_run_order = (
        _single_machine_run_order(
            requires_table_distribution_before_hardtail=requires_table_distribution,
            canary_reuses_full_prerequisites=bool("run_canary_after_prerequisites" in files),
        )
        if full_relative
        else []
    )
    manual_staged_run_order = _manual_staged_run_order(
        requires_table_distribution_before_hardtail=requires_table_distribution,
        canary_reuses_full_prerequisites=bool("run_canary_after_prerequisites" in files),
        has_full_plan=bool(full_relative),
    )

    payload = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "runbook_generated_not_runtime_evidence",
        "execution_environment": "generic_large_machine_or_approved_cloud",
        "aws_required": False,
        "nonaws_generic_ssh_supported": True,
        "nonaws_entrypoint": "scripts/run_h48_fasttarget_nonaws_proof.py",
        "aws_account_boundary_note": (
            "AWS helper scripts are not required for this runbook. Use the non-AWS generic SSH "
            "entrypoint for an approved PC or other non-AWS host unless the correct AWS account "
            "is explicitly reauthorized."
        ),
        "canary_plan_path": canary_relative,
        "full_plan_path": full_relative,
        "canary_plan_summary": _plan_summary(canary_plan),
        "full_plan_summary": _plan_summary(full_plan),
        "profile": (full_plan or canary_plan).get("profile"),
        "seed": (full_plan or canary_plan).get("seed"),
        "solver": solver,
        "run_suffix": safe_suffix,
        "timeout_scale": timeout_scale,
        "default_threads": default_threads,
        "output_dir": _relative(root, output_dir),
        "generated_files": {key: _relative(root, path) for key, path in files.items()},
        "generated_file_fingerprint_algorithm": "sha256-size-mode-v1",
        "generated_file_fingerprints": {
            key: _file_fingerprint(root, path) for key, path in files.items()
        },
        "parallel_machine_count": len(parallel_script_assignments) or max(1, int(parallel_machines)),
        "parallel_assignments": [
            {
                "machine_index": index,
                "script": _relative(root, output_dir / f"run_full_machine_{index:02d}.sh"),
                "workload_ids": [str(workload.get("id")) for workload in group],
                "estimated_wall_seconds": sum(
                    float(workload.get("estimated_wall_seconds") or 0.0) for workload in group
                ),
            }
            for index, group in enumerate(parallel_script_assignments)
        ],
        "parallel_estimate": parallel_estimate,
        "shared_canary_prerequisite_ids": shared_prerequisite_ids_for_payload,
        "canary_reuses_full_prerequisites": bool("run_canary_after_prerequisites" in files),
        "recommended_minimum_cloud_machine": (full_plan or canary_plan).get(
            "recommended_minimum_cloud_machine"
        ),
        "single_machine_run_order": single_machine_run_order,
        "manual_staged_run_order": manual_staged_run_order,
        "run_order": manual_staged_run_order,
        "completion_gate": (
            "Only a full-scope campaign whose workloads pass and whose regenerated contract records "
            "fast_runtime_proven_for_every_possible_state=true can satisfy the final claim."
        ),
        "fast_runtime_proven_for_every_possible_state": False,
    }
    output = root / "results" / "processed" / f"cloud_hardtail_runbook_{safe_suffix}.json"
    write_json(output, payload)
    return payload, output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canary-plan", type=Path, required=True)
    parser.add_argument("--full-plan", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-suffix", default="cloud_hardtail")
    parser.add_argument("--timeout-scale", type=float, default=1.25)
    parser.add_argument(
        "--parallel-machines",
        type=int,
        default=1,
        help="Render per-machine full-campaign shard scripts for this many cloud workers.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    output_dir = args.output_dir or Path("results") / f"cloud_hardtail_runbook_{_safe_id(args.run_suffix)}"
    payload, output = build_cloud_hardtail_runbook(
        root=args.root,
        canary_plan_path=args.canary_plan,
        full_plan_path=args.full_plan,
        output_dir=output_dir,
        run_suffix=args.run_suffix,
        timeout_scale=args.timeout_scale,
        parallel_machines=args.parallel_machines,
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "output_dir": payload["output_dir"],
                "generated_files": payload["generated_files"],
                "parallel_estimate": payload["parallel_estimate"],
                "fast_runtime_proven_for_every_possible_state": payload[
                    "fast_runtime_proven_for_every_possible_state"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
