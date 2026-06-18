import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace

import pytest

import rubik_optimal.tables.h48 as h48_tables
from rubik_optimal.cube import CubeState
from rubik_optimal.oracle import FastOptimalOracle, FastOptimalOracleConfig
from rubik_optimal.runtime import (
    IdleStatus,
    evaluate_idle_status,
    parse_gib,
    parse_thread_setting,
    parse_vm_stat_available_bytes,
    run_process_tree,
    suggest_thread_count,
    wait_for_idle,
)
from rubik_optimal.tables.h48 import (
    estimated_h48_table_size_bytes,
    h48_table_inventory,
    highest_available_h48_solver,
    repository_root,
    resolve_h48_solver,
)
from scripts.inspect_h48_capacity import build_capacity_payload, evaluate_h48_generation_safety
import scripts.inspect_h48_capacity as h48_capacity
from scripts.experimental.cloud_hardtail_preflight import build_preflight_payload
import scripts.experimental.cloud_hardtail_preflight as h48_preflight
import scripts.inspect_h48_proof_volumes as h48_proof_volumes
from scripts.install_h48_table_bundle import install_h48_table_bundle
import scripts.install_h48_table_bundle as h48_bundle_installer
from scripts.create_h48_table_bundle import create_h48_table_bundle
from scripts.run_h48_split_bundle_smoke import run_h48_split_bundle_smoke
import scripts.probe_h48_generation_throughput as h48_generation_probe
from scripts.probe_h48_generation_throughput import parse_progress_lines
import scripts.run_h48_stronger_table_campaign as h48_stronger_campaign
from scripts.run_h48_stronger_table_campaign import build_campaign_decision


def _fake_source_state(_root):
    return {
        "schema_version": 1,
        "state": "test-source",
        "git_available": True,
        "has_commit": True,
        "commit": "test-commit",
        "commit_short": "test-commit",
        "dirty": False,
        "is_reproducible_checkout": True,
        "limitation": "",
        "reproduction_plan": [],
        "status_entry_count": 0,
        "status_sample": [],
    }


def test_runtime_thread_auto_leaves_capacity_on_loaded_machine():
    assert suggest_thread_count(cpu_count=8, load_average=0.25) == 8
    assert suggest_thread_count(cpu_count=8, load_average=4.9) == 3
    assert parse_thread_setting("auto", cpu_count=8, load_average=4.9) == 3
    assert parse_thread_setting("2", cpu_count=8, load_average=4.9) == 2


def test_runtime_idle_status_checks_load_and_memory():
    status = evaluate_idle_status(
        cpu_count=8,
        load_average=(1.2, 1.5, 1.8),
        available_bytes=8 * 1024**3,
        max_load_1m=2.5,
        max_load_5m=3.0,
        min_available_memory_bytes=parse_gib(6),
    )

    assert status.idle is True
    assert status.reasons == ()

    busy = evaluate_idle_status(
        cpu_count=8,
        load_average=(5.6, 6.4, 6.8),
        available_bytes=parse_gib(0.25),
        max_load_1m=2.5,
        max_load_5m=3.0,
        min_available_memory_bytes=parse_gib(6),
    )

    assert busy.idle is False
    assert any("one-minute load" in reason for reason in busy.reasons)
    assert any("five-minute load" in reason for reason in busy.reasons)
    assert any("available memory" in reason for reason in busy.reasons)


def test_runtime_parses_vm_stat_available_memory_conservatively():
    output = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                4118.
Pages speculative:                         3140.
Pages purgeable:                             10.
Pages active:                            201340.
"""

    assert parse_vm_stat_available_bytes(output) == (4118 + 3140 + 10) * 16384


def test_wait_for_idle_requires_consecutive_passing_checks():
    statuses = iter(
        [
            IdleStatus(False, 8, 5.0, 5.0, parse_gib(8), 2.5, 3.0, parse_gib(6), ("busy",)),
            IdleStatus(True, 8, 1.0, 1.0, parse_gib(8), 2.5, 3.0, parse_gib(6), ()),
            IdleStatus(True, 8, 1.0, 1.0, parse_gib(8), 2.5, 3.0, parse_gib(6), ()),
        ]
    )

    idle, samples = wait_for_idle(
        max_load_1m=2.5,
        max_load_5m=3.0,
        min_available_memory_bytes=parse_gib(6),
        required_consecutive_checks=2,
        check_interval_seconds=0,
        timeout_seconds=10,
        status_provider=lambda: next(statuses),
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    assert idle is True
    assert len(samples) == 3


def test_run_process_tree_timeout_kills_descendant_process(tmp_path):
    marker = tmp_path / "descendant_leaked.txt"
    child_code = (
        "import time; "
        "from pathlib import Path; "
        "time.sleep(0.6); "
        f"Path({str(marker)!r}).write_text('leaked', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(5)"
    )

    result = run_process_tree(
        [sys.executable, "-c", parent_code],
        cwd=tmp_path,
        timeout_seconds=0.1,
        terminate_grace_seconds=0.1,
    )
    time.sleep(0.8)

    assert result.timed_out is True
    assert result.return_code == 124
    assert result.terminated_process_group is True
    assert marker.exists() is False


def test_h48_inventory_selects_strongest_trusted_local_oracle_table():
    root = repository_root()
    rows = h48_table_inventory(root=root, profile="thesis", seed=2026, min_h=7, max_h=11)

    assert estimated_h48_table_size_bytes("h48h11") == 60670567784
    assert any(row["solver"] == "h48h7" and row["trusted_metadata_valid"] is True for row in rows)
    assert highest_available_h48_solver(root=root, profile="thesis", seed=2026) == "h48h7"
    assert resolve_h48_solver("auto", root=root, profile="thesis", seed=2026) == "h48h7"


def test_fast_optimal_oracle_auto_solver_resolves_to_current_strongest_h48():
    root = repository_root()
    config = FastOptimalOracleConfig(
        root=root,
        solver="auto",
        threads=2,
        timeout_seconds=30.0,
    )
    cube = CubeState.from_sequence("R U F2")
    with FastOptimalOracle(config) as oracle:
        result = oracle.solve(cube)

    assert oracle.solver == "h48h7"
    assert result.solver_name == "fast_optimal_oracle_h48h7"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified


def test_h48_capacity_payload_records_missing_larger_tables_without_network():
    payload = build_capacity_payload(
        root=repository_root(),
        profile="thesis",
        seed=2026,
        refresh_public_nissy=False,
    )

    assert payload["strongest_local_oracle_solver"] == "h48h7"
    assert payload["next_missing_oracle_grade_solver"] == "h48h8"
    assert payload["estimated_h48h10_size_bytes"] == 30336314216
    assert payload["estimated_h48h11_size_bytes"] == 60670567784
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["public_nissy_tables"]["contains_h48_entries"] is False
    assert payload["h48_first_stronger_solver"] == "h48h8"
    assert payload["h48_fast_target_solver"] == "h48h10"
    assert payload["h48_first_stronger_generation_safety"]["solver"] == "h48h8"
    assert payload["h48_first_stronger_generation_safety"]["policy"]["generation_storage"] == "mmap_file"
    assert payload["h48_16_thread_upstream_benchmark"]["available"] is True
    assert payload["h48_16_thread_upstream_benchmark"]["target_has_distance20_timing"] is True
    assert payload["h48_16_thread_upstream_benchmark"]["target_has_superflip_timing"] is True
    gate = payload["all_state_fast_oracle_completion_gate"]
    assert gate["target_solver"] == "h48h10"
    assert gate["first_missing_ladder_solver"] == "h48h8"
    assert gate["target_table_expected_size_bytes"] == 30336314216
    assert gate["target_table_trusted"] is False
    assert gate["target_upstream_benchmark_has_distance20_timing"] is True
    assert gate["target_upstream_benchmark_has_superflip_timing"] is True
    assert gate["can_claim_fast_oracle_for_every_possible_state"] is False
    assert payload["h48_stronger_table_build_plan"][0]["solver"] == "h48h8"
    assert "--require-safe" in payload["h48_stronger_table_build_plan"][0]["recommended_command"]

    optimized_payload = build_capacity_payload(
        root=repository_root(),
        profile="thesis",
        seed=2026,
        refresh_public_nissy=False,
        skip_generation_distribution_scan=True,
        mmap_sync_mode="async",
        gendata_workbatch=128,
        backend_extra_cflags=["-march=native"],
    )
    plan_options = optimized_payload["h48_stronger_table_generation_plan_options"]
    assert plan_options["h48_gendata_workbatch"] == 128
    assert plan_options["h48_generation_distribution_mode"] == "expected_constants"
    assert plan_options["h48_generation_distribution_scan_skipped"] is True
    assert plan_options["h48_generation_mmap_sync_mode"] == "async"
    assert plan_options["h48_backend_extra_cflags"] == ["-march=native"]
    optimized_row = optimized_payload["h48_stronger_table_build_plan"][0]
    assert optimized_row["h48_gendata_workbatch"] == 128
    assert optimized_row["h48_generation_distribution_mode"] == "expected_constants"
    assert optimized_row["h48_generation_mmap_sync_mode"] == "async"
    assert optimized_row["h48_backend_extra_cflags"] == ["-march=native"]
    assert "--gendata-workbatch 128" in optimized_row["recommended_command"]
    assert "--skip-generation-distribution-scan" in optimized_row["recommended_command"]
    assert "--mmap-sync-mode async" in optimized_row["recommended_command"]
    assert "--backend-cflag=-march=native" in optimized_row["recommended_command"]


def test_h48_generation_safety_is_machine_checked_for_stronger_table():
    safety = evaluate_h48_generation_safety(
        root=repository_root(),
        solver="h48h8",
        threads=1,
    )

    assert safety["solver"] == "h48h8"
    assert safety["estimated_table_size_bytes"] == estimated_h48_table_size_bytes("h48h8")
    assert isinstance(safety["safe_to_start"], bool)
    assert "memory_fraction_limit" in safety["policy"]
    assert safety["policy"]["generation_storage"] == "mmap_file"


def test_h48_generation_safety_allows_mmap_when_idle_with_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_capacity, "_memory_bytes", lambda: parse_gib(16))
    monkeypatch.setattr(h48_capacity, "_load_average", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(h48_capacity, "available_memory_bytes", lambda: parse_gib(6))
    monkeypatch.setattr(h48_capacity.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        h48_capacity.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=parse_gib(64), used=parse_gib(32), free=parse_gib(32)),
    )

    safety = evaluate_h48_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        mmap_output=True,
    )

    assert safety["safe_to_start"] is True
    assert safety["policy"]["generation_storage"] == "mmap_file"
    assert safety["policy"]["disk_multiplier"] == h48_capacity.H48_MMAP_GENERATION_DISK_MULTIPLIER
    assert safety["policy"]["disk_multiplier_source"] == "storage_default"
    assert not any("35% of total RAM" in reason for reason in safety["reasons"])


def test_h48_capacity_and_preflight_use_configured_table_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    external = tmp_path / "external-proof-volume" / "h48"
    observed_disk_roots: list[Path] = []

    def fake_disk_usage(path):
        observed_disk_roots.append(Path(path))
        return SimpleNamespace(total=parse_gib(128), used=parse_gib(8), free=parse_gib(120))

    monkeypatch.setenv(h48_tables.H48_TABLE_ROOT_ENV, str(external))
    monkeypatch.setattr(h48_capacity, "_memory_bytes", lambda: parse_gib(64))
    monkeypatch.setattr(h48_capacity, "_load_average", lambda: (0.5, 0.5, 0.5))
    monkeypatch.setattr(h48_capacity, "available_memory_bytes", lambda: parse_gib(32))
    monkeypatch.setattr(h48_capacity.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(h48_capacity.shutil, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(h48_preflight.shutil, "disk_usage", fake_disk_usage)

    safety = evaluate_h48_generation_safety(
        root=root,
        solver="h48h8",
        threads=8,
        mmap_output=True,
    )
    payload = build_preflight_payload(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        min_cpus=16,
        min_memory_gib=64.0,
        min_free_disk_gib=1.0,
        min_storage_gib=64.0,
        threads=8,
        require_external_assets=False,
        require_target_table=False,
        assume_cpu_count=16,
        assume_memory_gib=64.0,
        assume_available_memory_gib=32.0,
        assume_free_disk_gib=120.0,
        assume_total_storage_gib=128.0,
    )

    assert observed_disk_roots
    assert all(path == external for path in observed_disk_roots)
    assert safety["machine"]["h48_table_root_env"] == h48_tables.H48_TABLE_ROOT_ENV
    assert safety["machine"]["h48_table_root"] == str(external)
    assert payload["machine"]["h48_table_root_env"] == h48_tables.H48_TABLE_ROOT_ENV
    assert payload["machine"]["h48_table_root"] == str(external)
    assert payload["target_h48_workspace"]["satisfies_workspace"] is True


def test_h48_proof_volume_report_finds_launchable_external_candidate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    slow_volume = tmp_path / "slow-volume"
    fast_volume = tmp_path / "fast-volume"
    slow_volume.mkdir()
    fast_volume.mkdir()
    slow_root = slow_volume / "h48"
    fast_root = fast_volume / "h48"

    def fake_disk_usage(path):
        path = Path(path)
        if path == fast_volume:
            return SimpleNamespace(total=parse_gib(300), used=parse_gib(240), free=parse_gib(60))
        return SimpleNamespace(total=parse_gib(300), used=parse_gib(284), free=parse_gib(16))

    monkeypatch.setattr(h48_proof_volumes, "_memory_bytes", lambda: parse_gib(64))
    monkeypatch.setattr(h48_proof_volumes, "available_memory_bytes", lambda: parse_gib(32))
    monkeypatch.setattr(h48_proof_volumes, "_load_average", lambda: (0.2, 0.2, 0.2))
    monkeypatch.setattr(h48_proof_volumes.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(h48_proof_volumes.os, "access", lambda _path, _mode: True)
    monkeypatch.setattr(h48_proof_volumes.shutil, "disk_usage", fake_disk_usage)

    payload = h48_proof_volumes.build_proof_volume_payload(
        root=repo,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        candidate_roots=[slow_root, fast_root],
        include_configured_root=False,
        include_volume_roots=False,
    )

    assert payload["solver"] == "h48h10"
    assert payload["requirements"]["target_table_size_bytes"] == estimated_h48_table_size_bytes("h48h10")
    assert payload["host_machine_satisfies"] is True
    assert payload["launchable_for_h48_generation"] is True
    assert payload["launchable_candidate_count"] == 1
    assert payload["launchable_candidates"][0]["h48_table_root_absolute"] == str(
        fast_root.resolve(strict=False)
    )
    assert payload["launchable_candidates"][0]["satisfies_workspace"] is True
    assert payload["best_candidate"]["h48_table_root_absolute"] == str(fast_root.resolve(strict=False))
    assert h48_tables.H48_TABLE_ROOT_ENV in payload["best_candidate"]["recommended_preflight_command"]
    assert "--require-safe" in payload["best_candidate"]["recommended_generation_command_after_approval"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_proof_volume_report_keeps_machine_gate_separate_from_disk(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    volume = tmp_path / "large-volume"
    volume.mkdir()

    monkeypatch.setattr(h48_proof_volumes, "_memory_bytes", lambda: parse_gib(16))
    monkeypatch.setattr(h48_proof_volumes, "available_memory_bytes", lambda: parse_gib(8))
    monkeypatch.setattr(h48_proof_volumes, "_load_average", lambda: (0.2, 0.2, 0.2))
    monkeypatch.setattr(h48_proof_volumes.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(h48_proof_volumes.os, "access", lambda _path, _mode: True)
    monkeypatch.setattr(
        h48_proof_volumes.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=parse_gib(512), used=parse_gib(400), free=parse_gib(112)),
    )

    payload = h48_proof_volumes.build_proof_volume_payload(
        root=repo,
        profile="thesis",
        seed=2026,
        solver="h48h10",
        candidate_roots=[volume / "h48"],
        include_configured_root=False,
        include_volume_roots=False,
    )

    assert payload["host_machine_satisfies"] is False
    assert payload["available_memory_satisfies"] is True
    assert payload["threads_satisfy_cpu"] is False
    assert payload["candidates"][0]["satisfies_workspace"] is True
    assert payload["candidates"][0]["satisfies_storage_class"] is True
    assert payload["launchable_for_h48_generation"] is False
    assert any("cpu_count 8" in reason for reason in payload["machine_reasons"])
    assert any("memory_gib 16.000" in reason for reason in payload["machine_reasons"])
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_generation_safety_keeps_heap_full_table_ram_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_capacity, "_memory_bytes", lambda: parse_gib(16))
    monkeypatch.setattr(h48_capacity, "_load_average", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(h48_capacity.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        h48_capacity.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=parse_gib(64), used=parse_gib(32), free=parse_gib(32)),
    )

    safety = evaluate_h48_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        mmap_output=False,
    )

    assert safety["safe_to_start"] is False
    assert safety["policy"]["generation_storage"] == "heap_then_write"
    assert safety["policy"]["disk_multiplier"] == h48_capacity.H48_HEAP_GENERATION_DISK_MULTIPLIER
    assert safety["policy"]["disk_multiplier_source"] == "storage_default"
    assert any("35% of total RAM" in reason for reason in safety["reasons"])


def test_h48_generation_safety_records_explicit_disk_multiplier(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_capacity, "_memory_bytes", lambda: parse_gib(16))
    monkeypatch.setattr(h48_capacity, "_load_average", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(h48_capacity, "available_memory_bytes", lambda: parse_gib(6))
    monkeypatch.setattr(h48_capacity.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        h48_capacity.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=parse_gib(64), used=parse_gib(32), free=parse_gib(32)),
    )

    safety = evaluate_h48_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        mmap_output=True,
        disk_multiplier=1.5,
    )

    assert safety["safe_to_start"] is True
    assert safety["policy"]["disk_multiplier"] == 1.5
    assert safety["policy"]["disk_multiplier_source"] == "explicit"


def test_h48_generation_safety_refuses_mmap_with_low_available_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_capacity, "_memory_bytes", lambda: parse_gib(16))
    monkeypatch.setattr(h48_capacity, "_load_average", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(h48_capacity, "available_memory_bytes", lambda: parse_gib(1))
    monkeypatch.setattr(h48_capacity.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        h48_capacity.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=parse_gib(64), used=parse_gib(32), free=parse_gib(32)),
    )

    safety = evaluate_h48_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        mmap_output=True,
    )

    assert safety["safe_to_start"] is False
    assert any("mmap generation guard" in reason for reason in safety["reasons"])


def test_h48_table_generator_safety_only_does_not_generate_table(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_h48_tables.py",
            "--profile",
            "thesis",
            "--seed",
            "2026",
            "--solver",
            "h48h8",
            "--threads",
            "1",
            "--mmap-output",
            "--safety-only",
            "--root",
            str(tmp_path),
        ],
        cwd=repository_root(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")

    assert payload["status"] in {"safety_passed", "safety_failed"}
    assert payload["would_generate"] == payload["safety"]["safe_to_start"]
    assert table.exists() is False


def test_h48_generation_probe_parses_native_short_cube_progress():
    samples = parse_progress_lines(
        "[H48 gendata] Processing 'short cubes'. This will take a while.\n"
        "[H48 gendata] Processed 1000 / 7437855 cubes\n"
        "[H48 gendata] Scanned 4096 / 10000019 slots; Processed 2500 / 7437855 cubes\n"
    )

    assert samples == [
        {
            "processed_short_cubes": 1000,
            "total_short_cubes": 7437855,
            "scanned_shortcube_slots": None,
            "total_shortcube_slots": None,
        },
        {
            "processed_short_cubes": 2500,
            "total_short_cubes": 7437855,
            "scanned_shortcube_slots": 4096,
            "total_shortcube_slots": 10000019,
        },
    ]


def test_h48_generation_probe_records_explicit_native_workbatch(tmp_path, monkeypatch):
    binary = tmp_path / "h48_backend"
    binary.write_text("fake backend", encoding="utf-8")
    captured_build: dict[str, object] = {}

    def fake_build_h48_backend(**kwargs):
        captured_build.update(kwargs)
        return binary

    class FakePopen:
        pid = 4242

        def __init__(self, command, **_kwargs):
            self.command = command
            self.returncode = 0

        def communicate(self, timeout=None):
            output = self.command[self.command.index("--output") + 1]
            partial = tmp_path / output
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"12345678")
            return (
                json.dumps({"status": "generated"}),
                "[H48 gendata] Scanned 7 / 20 slots; Processed 5 / 10 cubes\n",
            )

    clock = iter([100.0, 110.0])
    monkeypatch.setattr(h48_generation_probe, "build_h48_backend", fake_build_h48_backend)
    monkeypatch.setattr(
        h48_generation_probe,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {"safe_to_start": True, "reasons": []},
    )
    monkeypatch.setattr(h48_generation_probe.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(h48_generation_probe.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(h48_generation_probe, "_load_average", lambda: (0.1, 0.2, 0.3))

    payload = h48_generation_probe.run_probe(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        threads=2,
        timeout_seconds=20.0,
        artifact_suffix="workbatch_test",
        gendata_workbatch=3,
    )

    assert captured_build["gendata_workbatch"] == 3
    assert payload["h48_gendata_workbatch"] == 3
    assert payload["latest_processed_short_cubes"] == 5
    assert payload["total_short_cubes"] == 10
    assert payload["latest_scanned_shortcube_slots"] == 7
    assert payload["total_shortcube_slots"] == 20
    assert payload["partial_cleanup_status"] == "deleted_partial_probe_file"
    assert payload["full_table_generated"] is True
    assert not (tmp_path / payload["partial_path"]).exists()


def test_h48_stronger_table_campaign_refuses_unsafe_generation(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=1,
        allow_unsafe_generation=False,
        dry_run=False,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety={
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test machine is too small"],
        },
    )

    assert decision["status"] == "refused_unsafe_generation"
    assert decision["should_run_generation"] is False
    assert decision["target_trusted_table"] is False
    assert "--require-safe" in decision["generation_command"]
    assert "--min-mmap-available-memory-gib" in decision["generation_command"]
    assert decision["all_state_fast_oracle_goal_satisfied_by_this_decision"] is False


def test_h48_stronger_table_campaign_streams_subprocess_output(tmp_path, capsys):
    result = h48_stronger_campaign._run_command(
        [
            sys.executable,
            "-c",
            "import sys; print('streamed stdout'); print('streamed stderr', file=sys.stderr)",
        ],
        root=tmp_path,
        timeout_seconds=5.0,
        stream_output=True,
    )

    captured = capsys.readouterr()

    assert result["return_code"] == 0
    assert result["timed_out"] is False
    assert result["streamed_output"] is True
    assert "streamed stdout" in captured.out
    assert "streamed stderr" in captured.out
    assert "streamed stdout" in result["stdout_tail"]
    assert "streamed stderr" in result["stdout_tail"]


def test_h48_stronger_table_campaign_plans_safe_dry_run(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=2,
        allow_unsafe_generation=False,
        dry_run=True,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety={
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": True,
            "reasons": [],
        },
    )

    assert decision["status"] == "planned"
    assert decision["should_run_generation"] is False
    assert "--mmap-output" in decision["generation_command"]
    assert "--progress-log" in decision["generation_command"]
    assert "--min-mmap-available-memory-gib" in decision["generation_command"]
    assert "scripts/generate_h48_tables.py" in decision["generation_command_args"]
    assert "hard-case exact certification with h48h8" in decision["remaining_completion_requirements"]


def test_h48_stronger_table_campaign_records_custom_mmap_memory_guard(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=1,
        allow_unsafe_generation=False,
        dry_run=True,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety=None,
        min_mmap_available_memory_bytes=parse_gib(0.25),
    )

    args = decision["generation_command_args"]
    threshold_index = args.index("--min-mmap-available-memory-gib") + 1
    assert args[threshold_index] == "0.25"
    assert decision["safety"]["policy"]["min_mmap_available_memory_bytes"] == parse_gib(0.25)
    assert decision["safety"]["policy"]["generation_storage"] == "mmap_file"


def test_h48_stronger_table_campaign_records_custom_disk_multiplier(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=1,
        allow_unsafe_generation=False,
        dry_run=True,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety=None,
        disk_multiplier=1.25,
    )

    args = decision["generation_command_args"]
    disk_index = args.index("--disk-multiplier") + 1
    assert args[disk_index] == "1.25"
    assert decision["safety"]["policy"]["disk_multiplier"] == 1.25
    assert decision["safety"]["policy"]["disk_multiplier_source"] == "explicit"


def test_h48_stronger_table_campaign_dry_run_marks_unsafe_generation(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h10",
        threads=2,
        allow_unsafe_generation=False,
        dry_run=True,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety={
            "solver": "h48h10",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h10"),
            "safe_to_start": False,
            "reasons": ["test workspace is too small"],
        },
    )

    assert decision["status"] == "dry_run_refused_unsafe_generation"
    assert decision["should_run_generation"] is False
    assert "--mmap-output" in decision["generation_command"]
    assert "test workspace is too small" in decision["safety"]["reasons"]


def test_h48_stronger_table_campaign_wait_for_safe_requires_consecutive_passes(tmp_path, monkeypatch):
    samples = iter(
        [
            {"solver": "h48h8", "safe_to_start": False, "reasons": ["busy"], "policy": {}, "machine": {}},
            {"solver": "h48h8", "safe_to_start": True, "reasons": [], "policy": {}, "machine": {}},
            {"solver": "h48h8", "safe_to_start": True, "reasons": [], "policy": {}, "machine": {}},
        ]
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: next(samples),
    )

    result = h48_stronger_campaign.wait_for_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        timeout_seconds=10,
        check_interval_seconds=0,
        required_consecutive_checks=2,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    assert result["status"] == "safety_wait_passed"
    assert result["sample_count"] == 3
    assert result["completed_consecutive_checks"] == 2
    assert result["safe_to_start"] is True


def test_h48_stronger_table_campaign_wait_reports_safety_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "safe_to_start": True,
            "reasons": [],
            "policy": {},
            "machine": {"available_memory_bytes": parse_gib(8), "load_average": (0.5, 0.5, 0.5)},
        },
    )
    samples: list[dict[str, object]] = []

    result = h48_stronger_campaign.wait_for_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads=1,
        timeout_seconds=10,
        check_interval_seconds=0,
        required_consecutive_checks=1,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
        sample_reporter=samples.append,
    )

    assert result["status"] == "safety_wait_passed"
    assert len(samples) == 1
    assert samples[0]["sample_index"] == 1
    assert samples[0]["safe_to_start"] is True


def test_h48_stronger_table_campaign_wait_recomputes_auto_threads(tmp_path, monkeypatch):
    parsed_threads = iter([2, 1])
    observed_threads: list[int] = []

    monkeypatch.setattr(
        h48_stronger_campaign,
        "parse_thread_setting",
        lambda raw: next(parsed_threads),
    )

    def fake_safety(**kwargs):
        threads = int(kwargs["threads"])
        observed_threads.append(threads)
        return {
            "solver": "h48h8",
            "threads": threads,
            "safe_to_start": threads == 1,
            "reasons": [] if threads == 1 else ["test load still high"],
            "policy": {},
            "machine": {},
        }

    monkeypatch.setattr(h48_stronger_campaign, "evaluate_h48_generation_safety", fake_safety)

    result = h48_stronger_campaign.wait_for_generation_safety(
        root=tmp_path,
        solver="h48h8",
        threads="auto",
        timeout_seconds=10,
        check_interval_seconds=0,
        required_consecutive_checks=1,
        sleeper=lambda _seconds: None,
        monotonic=lambda: 0.0,
    )

    assert result["status"] == "safety_wait_passed"
    assert observed_threads == [2, 1]
    assert [sample["resolved_threads"] for sample in result["samples"]] == [2, 1]
    assert result["final_safety"]["threads"] == 1


def test_h48_stronger_table_campaign_wait_deferred_when_machine_stays_unsafe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test machine remains busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )

    payload = h48_stronger_campaign.run_campaign(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=1,
        allow_unsafe_generation=False,
        dry_run=False,
        generation_timeout_seconds=None,
        certification_timeout_seconds=1.0,
        runtime_target_seconds=1.0,
        artifact_suffix="wait_deferred",
        wait_for_safe=True,
        safety_wait_timeout_seconds=0.0,
        safety_check_interval_seconds=0.0,
        safety_required_consecutive_checks=1,
    )

    assert payload["status"] == "deferred_by_safety_wait"
    assert payload["should_run_generation"] is False
    assert payload["commands"] == []
    assert payload["safety_wait"]["status"] == "safety_wait_timeout"
    assert payload["safety"]["reasons"] == ["test machine remains busy"]


def test_h48_stronger_table_campaign_uses_final_wait_threads_for_generation(tmp_path, monkeypatch):
    parsed_threads = iter([5, 1])
    observed_safety_threads: list[int] = []
    observed_commands: list[list[str]] = []

    monkeypatch.setattr(
        h48_stronger_campaign,
        "parse_thread_setting",
        lambda raw: next(parsed_threads),
    )

    def fake_safety(**kwargs):
        threads = int(kwargs["threads"])
        observed_safety_threads.append(threads)
        return {
            "solver": "h48h8",
            "threads": threads,
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": len(observed_safety_threads) >= 2,
            "reasons": [] if len(observed_safety_threads) >= 2 else ["test machine initially busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        }

    def fake_run(command, **kwargs):
        observed_commands.append([str(part) for part in command])
        return {
            "command": " ".join(str(part) for part in command),
            "return_code": 0,
            "timed_out": False,
            "terminated_process_group": False,
            "runtime_seconds": 0.01,
            "stdout_tail": "",
            "stderr_tail": "",
            "streamed_output": bool(kwargs.get("stream_output")),
        }

    monkeypatch.setattr(h48_stronger_campaign, "evaluate_h48_generation_safety", fake_safety)
    monkeypatch.setattr(h48_stronger_campaign, "_run_command", fake_run)

    payload = h48_stronger_campaign.run_campaign(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=5,
        thread_setting="auto",
        allow_unsafe_generation=False,
        dry_run=False,
        generation_timeout_seconds=None,
        certification_timeout_seconds=1.0,
        runtime_target_seconds=1.0,
        artifact_suffix="dynamic_threads",
        wait_for_safe=True,
        safety_wait_timeout_seconds=10.0,
        safety_check_interval_seconds=0.0,
        safety_required_consecutive_checks=1,
    )

    assert observed_safety_threads == [5, 1]
    assert payload["thread_setting"] == "auto"
    assert payload["dynamic_thread_selection"] is True
    assert payload["generation_threads"] == 1
    assert payload["safety_wait"]["final_safety"]["threads"] == 1
    assert observed_commands[0][observed_commands[0].index("--threads") + 1] == "1"
    assert observed_commands[1][observed_commands[1].index("--threads") + 1] == "1"


def test_h48_stronger_table_campaign_detached_dry_run_records_waitsafe_command(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )

    payload = h48_stronger_campaign.launch_detached_campaign(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads="1",
        allow_unsafe_generation=False,
        generation_timeout_seconds=None,
        certification_timeout_seconds=1.0,
        runtime_target_seconds=1.0,
        artifact_suffix="detached_dryrun",
        wait_for_safe=True,
        safety_wait_timeout_seconds=3600.0,
        safety_check_interval_seconds=60.0,
        safety_required_consecutive_checks=2,
        execute=False,
    )

    assert payload["status"] == "detached_waitsafe_dryrun_planned_not_runtime_evidence"
    assert payload["execute"] is False
    assert payload["pid"] is None
    assert "--wait-for-safe" in payload["child_command"]
    assert "--safety-required-consecutive-checks 2" in payload["child_command"]
    assert "--min-mmap-available-memory-gib" in payload["child_command"]
    assert payload["min_mmap_available_memory_gib"] == 4.0
    assert payload["preflight_safety"]["reasons"] == ["test laptop busy"]
    assert payload["detached_status"]["pid_alive"] is None
    assert payload["h48_gendata_workbatch"] == h48_tables.DEFAULT_H48_GENDATA_WORKBATCH
    assert "--gendata-workbatch" in payload["child_command"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_stronger_table_campaign_detached_start_writes_pid_and_log_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_process_resource_snapshot",
        lambda pids: {"available": True, "matches": [{"pid": pid} for pid in pids]},
    )

    class FakePopen:
        pid = 4242

        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs

    monkeypatch.setattr(h48_stronger_campaign.subprocess, "Popen", FakePopen)

    payload = h48_stronger_campaign.launch_detached_campaign(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads="1",
        allow_unsafe_generation=False,
        generation_timeout_seconds=None,
        certification_timeout_seconds=1.0,
        runtime_target_seconds=1.0,
        artifact_suffix="detached_start",
        wait_for_safe=True,
        safety_wait_timeout_seconds=3600.0,
        safety_check_interval_seconds=60.0,
        safety_required_consecutive_checks=2,
        execute=True,
    )

    assert payload["status"] == "detached_waitsafe_started_not_runtime_evidence"
    assert payload["execute"] is True
    assert payload["pid"] == 4242
    assert (tmp_path / payload["pid_file_path"]).read_text(encoding="utf-8") == "4242"
    assert (tmp_path / payload["log_path"]).exists()
    assert payload["detached_status"]["pid_alive"] is True
    assert payload["detached_status"]["pid_file_exists"] is True
    assert payload["detached_status"]["log_path_exists"] is True
    assert payload["h48_gendata_workbatch"] == h48_tables.DEFAULT_H48_GENDATA_WORKBATCH
    assert "--gendata-workbatch" in payload["child_command_args"]


def test_h48_stronger_table_campaign_detached_status_reports_dryrun_launch_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {"available": True, "matches": []},
    )
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_dryrun",
        "status": "detached_waitsafe_dryrun_planned_not_runtime_evidence",
        "pid": None,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--threads",
            "auto",
            "--gendata-workbatch",
            "256",
            "--mmap-sync-mode",
            "async",
            "--backend-cflag=-march=native",
            "--skip-generation-distribution-scan",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.build_detached_status_payload(
        root=tmp_path,
        detached_payload_path=launch_path,
    )

    assert payload["status"] == "detached_launch_artifact_only_no_running_process"
    assert payload["detached_status"]["pid_alive"] is None
    assert payload["native_h48_backend_running"] is False
    assert payload["target_table"]["exists"] is False
    assert payload["campaign_result_exists"] is False
    assert payload["current_safety"]["reasons"] == ["test laptop busy"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_stronger_table_campaign_status_alias_resolves_canonical_launch(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {"available": True, "matches": []},
    )
    launch_path = h48_stronger_campaign._canonical_detached_status_source_path(
        tmp_path,
        seed=2026,
        profile="thesis",
        solver="h48h8",
        artifact_suffix="detached_alias",
    )
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(
        json.dumps(
            {
                "profile": "thesis",
                "seed": 2026,
                "target_solver": "h48h8",
                "artifact_suffix": "detached_alias",
                "status": "detached_waitsafe_dryrun_planned_not_runtime_evidence",
                "pid": None,
                "pid_file_path": "results/processed/test.pid",
                "log_path": "results/logs/test.log",
                "child_command_args": [
                    sys.executable,
                    "scripts/run_h48_stronger_table_campaign.py",
                    "--threads",
                    "auto",
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_h48_stronger_table_campaign.py",
            "--root",
            str(tmp_path),
            "--profile",
            "thesis",
            "--seed",
            "2026",
            "--target-solver",
            "h48h8",
            "--artifact-suffix",
            "detached_alias",
            "--status",
            "--status-artifact-suffix",
            "detached_alias_current",
        ],
    )

    assert h48_stronger_campaign.main() == 0
    printed = json.loads(capsys.readouterr().out)
    output = tmp_path / "results" / "processed" / (
        "h48_stronger_table_detached_status_seed_2026_thesis_h48h8_detached_alias_current.json"
    )
    table = tmp_path / "thesis" / "tables" / (
        "h48_stronger_table_detached_status_seed_2026_thesis_h48h8_detached_alias_current.tex"
    )

    assert printed["output"] == str(output)
    assert printed["table"] == str(table)
    assert output.exists()
    assert table.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["detached_payload_path"].endswith(
        "h48_stronger_table_detached_seed_2026_thesis_h48h8_detached_alias.json"
    )
    assert payload["status"] == "detached_launch_artifact_only_no_running_process"
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_stronger_table_campaign_parses_generation_progress(tmp_path):
    partial = tmp_path / ".h48h8.bin.partial"
    partial.write_bytes(b"\0" * 8192)

    progress = h48_stronger_campaign._parse_h48_generation_progress(
        "\n".join(
            [
                "[H48 gendata] Computed 7437855 positions",
                "[H48 gendata] Processing 'short cubes'. This will take a while.",
                "[H48 gendata] Processed 1000 / 7437855 cubes",
                "[H48 gendata] Processed 2000 / 7437855 cubes",
            ]
        ),
        partial_path=partial,
    )

    assert progress["available"] is True
    assert progress["saw_processing_phase"] is True
    assert progress["computed_short_positions"] == 7437855
    assert progress["progress_sample_count"] == 2
    assert progress["latest_processed_short_cubes"] == 2000
    assert progress["total_short_cubes"] == 7437855
    assert progress["latest_progress_fraction"] == round(2000 / 7437855, 9)
    assert progress["partial_table_exists"] is True
    assert progress["partial_table_size_bytes"] == 8192
    assert progress["partial_table_allocated_bytes"] is None or progress["partial_table_allocated_bytes"] >= 0


def test_h48_stronger_table_campaign_parses_waitsafe_heartbeats():
    progress = h48_stronger_campaign._parse_wait_safety_progress(
        "\n".join(
            [
                "not json",
                json.dumps(
                    {
                        "event": "h48_generation_safety_sample",
                        "checked_at_utc": "2026-06-02T01:00:00+00:00",
                        "sample_index": 1,
                        "elapsed_seconds": 0.1,
                        "thread_setting": "auto",
                        "resolved_threads": 5,
                        "dynamic_thread_selection": True,
                        "threads": 5,
                        "safe_to_start": False,
                        "reasons": ["available memory 0.25 GiB is below the 4.00 GiB mmap generation guard"],
                        "available_memory_bytes": 268_435_456,
                        "load_average": [2.5, 3.0, 4.0],
                    }
                ),
                json.dumps(
                    {
                        "event": "h48_generation_safety_sample",
                        "checked_at_utc": "2026-06-02T01:01:00+00:00",
                        "sample_index": 2,
                        "elapsed_seconds": 60.1,
                        "thread_setting": "auto",
                        "resolved_threads": 4,
                        "dynamic_thread_selection": True,
                        "threads": 4,
                        "safe_to_start": False,
                        "reasons": ["current one-minute load average is too high"],
                        "available_memory_bytes": 536_870_912,
                        "load_average": [8.0, 4.0, 3.0],
                    }
                ),
            ]
        )
    )

    assert progress["available"] is True
    assert progress["sample_count"] == 2
    assert progress["ever_safe_to_start"] is False
    assert progress["latest_sample_index"] == 2
    assert progress["latest_safe_to_start"] is False
    assert progress["latest_reasons"] == ["current one-minute load average is too high"]
    assert progress["latest_available_memory_bytes"] == 536_870_912
    assert progress["max_available_memory_bytes"] == 536_870_912
    assert progress["consecutive_safe_tail_count"] == 0
    assert progress["latest_resolved_threads"] == 4
    assert len(progress["recent_samples"]) == 2


def test_h48_stronger_table_campaign_detached_status_reports_live_pid_and_log_tail(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": True,
            "reasons": [],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {"available": True, "matches": []},
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)
    log_path = tmp_path / "results" / "logs" / "test.log"
    log_path.parent.mkdir(parents=True)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")
    partial = h48_tables.staged_h48_table_path(table)
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"\0" * 4096)
    log_path.write_text(
        "\n".join(
            [f"line {index}" for index in range(50)]
            + [
                "[H48 gendata] Computed 7437855 positions",
                "[H48 gendata] Processing 'short cubes'. This will take a while.",
                "[H48 gendata] Processed 3000 / 7437855 cubes",
            ]
        ),
        encoding="utf-8",
    )
    pid_file = tmp_path / "results" / "processed" / "test.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("4242", encoding="utf-8")
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_live",
        "status": "detached_waitsafe_started_not_runtime_evidence",
        "pid": 4242,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--threads",
            "1",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.build_detached_status_payload(
        root=tmp_path,
        detached_payload_path=launch_path,
    )

    assert payload["status"] == "detached_python_alive_waiting_or_running_no_trusted_table"
    assert payload["pid"] == 4242
    assert payload["pid_file_pid"] == 4242
    assert payload["effective_pid"] == 4242
    assert payload["pid_alive"] is True
    assert payload["detached_status"]["pid_alive"] is True
    assert payload["detached_status"]["pid_file_pid"] == 4242
    assert "line 49" in payload["detached_status"]["log_tail"]
    assert "line 0" not in payload["detached_status"]["log_tail"]
    assert payload["native_h48_backend_running"] is False
    assert payload["current_safety"]["safe_to_start"] is True
    assert payload["target_partial_table"]["exists"] is True
    assert payload["target_partial_table"]["size_bytes"] == 4096
    assert payload["target_partial_table"]["allocated_bytes"] is None or payload["target_partial_table"]["allocated_bytes"] >= 0
    assert payload["generation_log_progress"]["available"] is True
    assert payload["generation_log_progress"]["latest_processed_short_cubes"] == 3000
    assert payload["generation_log_progress"]["total_short_cubes"] == 7437855


def test_h48_stronger_table_campaign_detached_status_reports_waitsafe_progress(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {"available": True, "matches": []},
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)
    log_path = tmp_path / "results" / "logs" / "test.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "h48_generation_safety_sample",
                        "checked_at_utc": "2026-06-02T01:00:00+00:00",
                        "sample_index": 1,
                        "elapsed_seconds": 0.1,
                        "thread_setting": "auto",
                        "resolved_threads": 5,
                        "dynamic_thread_selection": True,
                        "threads": 5,
                        "safe_to_start": False,
                        "reasons": ["memory guard"],
                        "available_memory_bytes": 268_435_456,
                        "load_average": [2.5, 3.0, 4.0],
                    }
                ),
                json.dumps(
                    {
                        "event": "h48_generation_safety_sample",
                        "checked_at_utc": "2026-06-02T01:01:00+00:00",
                        "sample_index": 2,
                        "elapsed_seconds": 60.1,
                        "thread_setting": "auto",
                        "resolved_threads": 4,
                        "dynamic_thread_selection": True,
                        "threads": 4,
                        "safe_to_start": False,
                        "reasons": ["load guard"],
                        "available_memory_bytes": 536_870_912,
                        "load_average": [8.0, 4.0, 3.0],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    pid_file = tmp_path / "results" / "processed" / "test.pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("4242", encoding="utf-8")
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_waitsafe",
        "status": "detached_waitsafe_started_not_runtime_evidence",
        "pid": 4242,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--threads",
            "auto",
            "--gendata-workbatch",
            "256",
            "--mmap-sync-mode",
            "async",
            "--backend-cflag=-march=native",
            "--skip-generation-distribution-scan",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.build_detached_status_payload(
        root=tmp_path,
        detached_payload_path=launch_path,
    )

    assert payload["status"] == "detached_python_alive_waiting_safety_gate_no_trusted_table"
    assert payload["pid"] == 4242
    assert payload["pid_file_pid"] == 4242
    assert payload["effective_pid"] == 4242
    assert payload["pid_alive"] is True
    assert payload["native_h48_backend_running"] is False
    assert payload["generation_log_progress"]["available"] is False
    assert payload["wait_safe_progress"]["available"] is True
    assert payload["wait_safe_progress"]["sample_count"] == 2
    assert payload["wait_safe_progress"]["latest_sample_index"] == 2
    assert payload["wait_safe_progress"]["latest_reasons"] == ["load guard"]
    assert payload["wait_safe_progress"]["max_available_memory_bytes"] == 536_870_912
    assert payload["h48_gendata_workbatch"] == 256
    assert payload["h48_generation_distribution_mode"] == "expected_constants"
    assert payload["h48_generation_distribution_scan_skipped"] is True
    assert payload["h48_generation_mmap_sync_mode"] == "async"
    assert payload["h48_backend_extra_cflags"] == ["-march=native"]
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_stronger_table_campaign_detached_status_reports_process_resources(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": True,
            "reasons": [],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {
            "available": True,
            "matches": [{"pid": 111, "command": "/tmp/h48_backend", "basename": "h48_backend"}],
        },
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)

    def fake_resources(pids):
        return {
            "available": True,
            "matches": [
                {
                    "pid": pid,
                    "ppid": 1,
                    "pgid": pid,
                    "stat": "R",
                    "elapsed": "00:42",
                    "cpu_percent": 123.4 if pid == 111 else 0.1,
                    "mem_percent": 15.2 if pid == 111 else 0.1,
                    "rss_kib": 2_500_000 if pid == 111 else 10_000,
                    "rss_bytes": (2_500_000 if pid == 111 else 10_000) * 1024,
                    "command": "h48_backend --generate" if pid == 111 else "python scripts/run_h48_stronger_table_campaign.py",
                }
                for pid in pids
            ],
        }

    monkeypatch.setattr(h48_stronger_campaign, "_process_resource_snapshot", fake_resources)
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_live",
        "status": "detached_waitsafe_started_not_runtime_evidence",
        "pid": 4242,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--target-solver",
            "h48h8",
            "--threads",
            "1",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.build_detached_status_payload(
        root=tmp_path,
        detached_payload_path=launch_path,
    )

    assert payload["status"] == "native_generation_or_solver_process_running_not_runtime_evidence"
    assert payload["detached_status"]["process_resources"]["matches"][0]["pid"] == 4242
    native_resources = payload["native_h48_backend_process_resources"]["matches"]
    assert native_resources[0]["pid"] == 111
    assert native_resources[0]["cpu_percent"] == 123.4
    assert native_resources[0]["rss_bytes"] == 2_500_000 * 1024
    assert native_resources[0]["command"] == "h48_backend --generate"


def test_h48_stronger_table_campaign_detached_stop_terminates_waiter_without_native_backend(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": False,
            "reasons": ["test laptop busy"],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {"available": True, "matches": []},
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_process_command_line",
        lambda _pid: {
            "available": True,
            "return_code": 0,
            "command": "python scripts/run_h48_stronger_table_campaign.py --target-solver h48h8 --wait-for-safe",
        },
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_signal_process_group_or_pid",
        lambda pid, sig: signals.append((pid, sig)) or True,
    )
    monkeypatch.setattr(h48_stronger_campaign, "_wait_until_pid_exits", lambda _pid, **_kwargs: True)
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_live",
        "status": "detached_waitsafe_started_not_runtime_evidence",
        "pid": 4242,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--target-solver",
            "h48h8",
            "--threads",
            "auto",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.stop_detached_campaign(
        root=tmp_path,
        detached_payload_path=launch_path,
        terminate_timeout_seconds=0.1,
    )

    assert payload["status"] == "detached_waiter_stopped"
    assert payload["stopped_pid"] == 4242
    assert payload["stop_signal_sent"] == "SIGTERM"
    assert payload["process_command_safe_to_stop"] is True
    assert payload["native_h48_backend_running_before_stop"] is False
    assert payload["stopped_without_native_backend"] is True
    assert payload["refusal_reasons"] == []
    assert signals
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_stronger_table_campaign_detached_stop_refuses_when_native_backend_running(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": True,
            "reasons": [],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_native_processes_by_basename",
        lambda **_kwargs: {
            "available": True,
            "matches": [{"pid": 111, "command": "/tmp/h48_backend", "basename": "h48_backend"}],
        },
    )
    monkeypatch.setattr(h48_stronger_campaign, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_process_command_line",
        lambda _pid: {
            "available": True,
            "return_code": 0,
            "command": "python scripts/run_h48_stronger_table_campaign.py --target-solver h48h8",
        },
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        h48_stronger_campaign,
        "_signal_process_group_or_pid",
        lambda pid, sig: signals.append((pid, sig)) or True,
    )
    launch_payload = {
        "profile": "thesis",
        "seed": 2026,
        "target_solver": "h48h8",
        "artifact_suffix": "detached_live",
        "status": "detached_waitsafe_started_not_runtime_evidence",
        "pid": 4242,
        "pid_file_path": "results/processed/test.pid",
        "log_path": "results/logs/test.log",
        "child_command_args": [
            sys.executable,
            "scripts/run_h48_stronger_table_campaign.py",
            "--target-solver",
            "h48h8",
            "--threads",
            "1",
        ],
    }
    launch_path = tmp_path / "results" / "processed" / "launch.json"
    launch_path.parent.mkdir(parents=True)
    launch_path.write_text(json.dumps(launch_payload), encoding="utf-8")

    payload = h48_stronger_campaign.stop_detached_campaign(
        root=tmp_path,
        detached_payload_path=launch_path,
        terminate_timeout_seconds=0.1,
    )

    assert payload["status"] == "detached_stop_refused"
    assert payload["native_h48_backend_running_before_stop"] is True
    assert payload["stopped_without_native_backend"] is False
    assert "native h48_backend process is running" in payload["refusal_reasons"]
    assert signals == []


def test_h48_stronger_table_campaign_requires_full_checksum_after_campaign(tmp_path, monkeypatch):
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")
    metadata = h48_tables.h48_metadata_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")
    table.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"fake-table")
    metadata.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        h48_stronger_campaign,
        "validate_trusted_h48_table",
        lambda **_kwargs: (True, "metadata ok"),
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "validate_trusted_h48_table_checksum",
        lambda **_kwargs: (
            False,
            "trusted H48 full checksum mismatch",
            {"trusted_metadata_valid": True, "full_checksum_valid": False},
        ),
    )

    payload = h48_stronger_campaign.run_campaign(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=1,
        allow_unsafe_generation=False,
        dry_run=False,
        generation_timeout_seconds=None,
        certification_timeout_seconds=1.0,
        runtime_target_seconds=1.0,
        artifact_suffix="checksum_required",
    )

    assert payload["status"] == "target_table_already_trusted"
    assert payload["post_campaign_target_trusted_table"] is True
    assert payload["post_campaign_full_checksum_valid"] is False
    assert payload["passed"] is False


def test_h48_stronger_table_campaign_forwards_native_workbatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        h48_stronger_campaign,
        "build_capacity_payload",
        lambda **_kwargs: {
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
    )
    monkeypatch.setattr(
        h48_stronger_campaign,
        "evaluate_h48_generation_safety",
        lambda **_kwargs: {
            "solver": "h48h8",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h8"),
            "safe_to_start": True,
            "reasons": [],
            "policy": {"generation_storage": "mmap_file"},
            "machine": {},
        },
    )

    decision = h48_stronger_campaign.build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h8",
        threads=3,
        allow_unsafe_generation=False,
        dry_run=True,
        gendata_workbatch=7,
        skip_generation_distribution_scan=True,
        mmap_sync_mode="async",
        backend_extra_cflags=["-march=native"],
    )

    assert decision["h48_gendata_workbatch"] == 7
    assert decision["h48_generation_distribution_mode"] == "expected_constants"
    assert decision["h48_generation_distribution_scan_skipped"] is True
    assert decision["h48_generation_mmap_sync_mode"] == "async"
    assert decision["h48_backend_extra_cflags"] == ["-march=native"]
    args = decision["generation_command_args"]
    assert args[args.index("--gendata-workbatch") + 1] == "7"
    assert args[args.index("--mmap-sync-mode") + 1] == "async"
    assert "--backend-cflag=-march=native" in args
    assert "--skip-generation-distribution-scan" in args


def test_h48_generation_publishes_only_after_staged_size_check(tmp_path, monkeypatch):
    captured_build: dict[str, object] = {}

    def fake_build_h48_backend(**kwargs):
        captured_build.update(kwargs)
        return tmp_path / "fake_h48_backend"

    monkeypatch.setattr(h48_tables, "build_h48_backend", fake_build_h48_backend)
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(h48_tables, "capture_source_state", _fake_source_state)

    def fake_run(command, **_kwargs):
        output = command[command.index("--output") + 1]
        partial = tmp_path / "data" / "generated" / "h48" / "thesis_seed_2026" / ".h48h0.bin.partial"
        assert output == str(partial)
        partial.write_bytes(b"12345678")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "generated", "runtime_seconds": 0.01, "generation_storage": "mmap_file"}),
            stderr="",
        )

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    metadata = h48_tables.generate_h48_table(root=tmp_path, profile="thesis", seed=2026, solver="h48h0", threads=1)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    partial = h48_tables.staged_h48_table_path(table)

    assert table.read_bytes() == b"12345678"
    assert not partial.exists()
    assert metadata["generation_status"] == "generated"
    assert metadata["staged_generation"] is True
    assert metadata["estimated_size_matches_actual"] is True
    assert metadata["h48_gendata_workbatch"] == h48_tables.DEFAULT_H48_GENDATA_WORKBATCH
    assert metadata["h48_generation_distribution_mode"] == "scanned"
    assert metadata["h48_generation_distribution_scan_skipped"] is False
    assert metadata["h48_generation_mmap_sync_mode"] == "not_applicable"
    assert captured_build["use_expected_distribution"] is False


def test_h48_generation_can_use_expected_distribution_without_final_scan(tmp_path, monkeypatch):
    captured_build: dict[str, object] = {}

    def fake_build_h48_backend(**kwargs):
        captured_build.update(kwargs)
        return tmp_path / "fake_h48_backend"

    monkeypatch.setattr(h48_tables, "build_h48_backend", fake_build_h48_backend)
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(h48_tables, "capture_source_state", _fake_source_state)

    def fake_run(command, **_kwargs):
        output = command[command.index("--output") + 1]
        Path(output).write_bytes(b"12345678")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "generated", "runtime_seconds": 0.01, "generation_storage": "mmap_file"}),
            stderr="",
        )

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    metadata = h48_tables.generate_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
        use_expected_distribution=True,
    )

    assert captured_build["use_expected_distribution"] is True
    assert metadata["h48_generation_distribution_mode"] == "expected_constants"
    assert metadata["h48_generation_distribution_scan_skipped"] is True


def test_h48_generation_can_use_async_mmap_sync_mode(tmp_path, monkeypatch):
    captured_command: list[str] = []

    monkeypatch.setattr(h48_tables, "build_h48_backend", lambda **_kwargs: tmp_path / "fake_h48_backend")
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(h48_tables, "capture_source_state", _fake_source_state)

    def fake_run(command, **_kwargs):
        captured_command.extend(command)
        output = command[command.index("--output") + 1]
        Path(output).write_bytes(b"12345678")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "generated",
                    "runtime_seconds": 0.01,
                    "generation_storage": "mmap_file",
                    "mmap_sync_mode": "async",
                    "mmap_sync_runtime_seconds": 0.123,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    metadata = h48_tables.generate_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
        mmap_output=True,
        mmap_sync_mode="async",
    )

    assert "--generate-mmap" in captured_command
    assert captured_command[captured_command.index("--mmap-sync-mode") + 1] == "async"
    assert metadata["h48_generation_mmap_sync_mode"] == "async"
    assert metadata["h48_generation_mmap_sync_runtime_seconds"] == 0.123


def test_h48_generation_workbatch_is_compiled_and_recorded(tmp_path, monkeypatch):
    vendor = tmp_path / "native" / "h48_backend" / "third_party" / "nissy_core" / "src"
    vendor.mkdir(parents=True)
    (vendor / "nissy.c").write_text("int nissy_test_symbol = 0;\n", encoding="utf-8")
    backend_source = tmp_path / "native" / "h48_backend" / "h48_backend.c"
    backend_source.parent.mkdir(parents=True, exist_ok=True)
    backend_source.write_text("int h48_backend_test_symbol = 0;\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        binary = tmp_path / "native" / "build" / "h48_backend"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("fake-binary", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    binary = h48_tables.build_h48_backend(
        root=tmp_path,
        threads=2,
        arch="PORTABLE",
        gendata_workbatch=5,
        extra_cflags=["-march=native"],
    )

    assert binary.exists()
    assert any(arg == "-DH48_GENDATA_WORKBATCH=5" for arg in commands[0])
    assert any(arg == "-DH48_GENDATA_USE_EXPECTED_DISTRIBUTION=0" for arg in commands[0])
    assert "-march=native" in commands[0]
    build_metadata = json.loads(binary.with_suffix(".build.json").read_text(encoding="utf-8"))
    assert build_metadata["h48_gendata_workbatch"] == 5
    assert build_metadata["h48_gendata_distribution_mode"] == "scanned"
    assert build_metadata["h48_backend_extra_cflags"] == ["-march=native"]


def test_h48_generation_rejects_unsafe_backend_cflag():
    with pytest.raises(ValueError, match="unsupported H48 backend extra compiler flag"):
        h48_tables.normalize_h48_backend_extra_cflags(["-o", "owned"])


def test_h48_generation_expected_distribution_compile_flag(tmp_path, monkeypatch):
    vendor = tmp_path / "native" / "h48_backend" / "third_party" / "nissy_core" / "src"
    vendor.mkdir(parents=True)
    (vendor / "nissy.c").write_text("int nissy_test_symbol = 0;\n", encoding="utf-8")
    backend_source = tmp_path / "native" / "h48_backend" / "h48_backend.c"
    backend_source.parent.mkdir(parents=True, exist_ok=True)
    backend_source.write_text("int h48_backend_test_symbol = 0;\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        binary = tmp_path / "native" / "build" / "h48_backend"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("fake-binary", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    binary = h48_tables.build_h48_backend(
        root=tmp_path,
        threads=2,
        arch="PORTABLE",
        gendata_workbatch=5,
        use_expected_distribution=True,
    )

    assert binary.exists()
    assert any(arg == "-DH48_GENDATA_USE_EXPECTED_DISTRIBUTION=1" for arg in commands[0])
    build_metadata = json.loads(binary.with_suffix(".build.json").read_text(encoding="utf-8"))
    assert build_metadata["h48_gendata_distribution_mode"] == "expected_constants"


def test_h48_generation_workbatch_env_override(monkeypatch):
    monkeypatch.setenv("RUBIK_OPTIMAL_H48_GENDATA_WORKBATCH", "9")

    assert h48_tables.resolve_h48_gendata_workbatch() == 9
    assert h48_tables.resolve_h48_gendata_workbatch("4") == 4

    with pytest.raises(ValueError, match="positive integer"):
        h48_tables.resolve_h48_gendata_workbatch("0")


def test_h48_generation_failure_keeps_existing_table_and_removes_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "build_h48_backend", lambda **_: tmp_path / "fake_h48_backend")
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    table.write_bytes(b"oldtable")

    def fake_run(command, **_kwargs):
        output = command[command.index("--output") + 1]
        partial = h48_tables.staged_h48_table_path(table)
        assert output == str(partial)
        partial.write_bytes(b"badtable")
        return SimpleNamespace(returncode=1, stdout=json.dumps({"status": "failed", "error": "test failure"}), stderr="")

    monkeypatch.setattr(h48_tables.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="H48 generation failed"):
        h48_tables.generate_h48_table(
            root=tmp_path,
            profile="thesis",
            seed=2026,
            solver="h48h0",
            threads=1,
            force=True,
        )

    assert table.read_bytes() == b"oldtable"
    assert not h48_tables.staged_h48_table_path(table).exists()


def test_h48_generation_refuses_to_adopt_existing_table_without_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    table.write_bytes(b"12345678")

    with pytest.raises(RuntimeError, match="without trusted metadata"):
        h48_tables.generate_h48_table(
            root=tmp_path,
            profile="thesis",
            seed=2026,
            solver="h48h0",
            threads=1,
        )

    assert table.read_bytes() == b"12345678"
    assert not h48_tables.h48_metadata_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
    ).exists()


def test_h48_generation_can_explicitly_adopt_exact_size_table_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(h48_tables, "capture_source_state", _fake_source_state)
    monkeypatch.setattr(
        h48_tables,
        "_run_h48_adoption_native_canary",
        lambda **_kwargs: {
            "passed": True,
            "native_payload": {"status": "exact", "table_check": "verified", "solution_length": 3},
        },
    )
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    metadata = h48_tables.h48_metadata_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    table.write_bytes(b"12345678")

    result = h48_tables.generate_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
        adopt_existing_table_metadata=True,
    )
    trusted_ok, trusted_message = h48_tables.validate_trusted_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
    )

    assert metadata.exists()
    assert result["generation_status"] == "adopted_existing_table_metadata"
    assert result["adopted_existing_table_metadata"] is True
    assert result["adoption_requires_explicit_flag"] is True
    assert "Recovered metadata" in result["adoption_trust_boundary"]
    assert "native nissy_checkdata-backed canary" in result["adoption_trust_boundary"]
    assert result["adoption_native_table_check_passed"] is True
    assert result["checksum_sha256"] == h48_tables.sha256_file(table)
    assert result["table_size_bytes"] == 8
    assert result["estimated_size_matches_actual"] is True
    assert trusted_ok is True, trusted_message


def test_h48_generation_refuses_adoption_when_native_canary_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(
        h48_tables,
        "_run_h48_adoption_native_canary",
        lambda **_kwargs: {
            "passed": False,
            "native_payload": {"status": "failed", "error": "table check failed"},
        },
    )
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    metadata = h48_tables.h48_metadata_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    table.write_bytes(b"12345678")

    with pytest.raises(RuntimeError, match="native table-check canary failed"):
        h48_tables.generate_h48_table(
            root=tmp_path,
            profile="thesis",
            seed=2026,
            solver="h48h0",
            threads=1,
            adopt_existing_table_metadata=True,
        )

    assert not metadata.exists()


def test_h48_generation_reuses_only_pretrusted_metadata_without_rewriting(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    metadata = h48_tables.h48_metadata_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    table.write_bytes(b"12345678")
    original_metadata = {
        "schema_version": 1,
        "table_kind": "h48_pruning_table",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h0",
        "h_value": 0,
        "file_path": "data/generated/h48/thesis_seed_2026/h48h0.bin",
        "checksum_sha256": h48_tables.sha256_file(table),
        "backend_source": "vendored_nissy_core_h48",
        "license": "GPL-3.0-or-later",
        "table_size_bytes": 8,
        "estimated_table_size_bytes": 8,
        "estimated_size_matches_actual": True,
        "generation_status": "generated",
        "generated_at_utc": "test-original",
    }
    metadata.write_text(json.dumps(original_metadata), encoding="utf-8")

    result = h48_tables.generate_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
    )

    assert result["generation_status"] == "reused_trusted_table"
    assert result["reused_existing_metadata"] is True
    assert json.loads(metadata.read_text(encoding="utf-8")) == original_metadata


def test_h48_generation_can_re_adopt_existing_trusted_table_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    monkeypatch.setattr(h48_tables, "capture_source_state", _fake_source_state)
    monkeypatch.setattr(
        h48_tables,
        "_run_h48_adoption_native_canary",
        lambda **_kwargs: {
            "passed": True,
            "native_payload": {"status": "exact", "table_check": "verified", "solution_length": 3},
        },
    )
    table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    metadata = h48_tables.h48_metadata_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h0")
    table.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    table.write_bytes(b"12345678")
    original_metadata = {
        "schema_version": 1,
        "table_kind": "h48_pruning_table",
        "profile": "thesis",
        "seed": 2026,
        "solver": "h48h0",
        "h_value": 0,
        "file_path": "data/generated/h48/thesis_seed_2026/h48h0.bin",
        "checksum_sha256": h48_tables.sha256_file(table),
        "backend_source": "vendored_nissy_core_h48",
        "license": "GPL-3.0-or-later",
        "table_size_bytes": 8,
        "estimated_table_size_bytes": 8,
        "estimated_size_matches_actual": True,
        "generation_status": "generated",
        "generated_at_utc": "test-original",
        "source_state": "no_commit+dirty",
        "source_snapshot_reproducible": False,
    }
    metadata.write_text(json.dumps(original_metadata), encoding="utf-8")

    result = h48_tables.generate_h48_table(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
        adopt_existing_table_metadata=True,
    )
    refreshed = json.loads(metadata.read_text(encoding="utf-8"))

    assert result["generation_status"] == "adopted_existing_table_metadata"
    assert result["adopted_existing_table_metadata"] is True
    assert result["adoption_previous_metadata_present"] is True
    assert result["adoption_previous_generation_status"] == "generated"
    assert result["adoption_previous_source_state"] == "no_commit+dirty"
    assert result["adoption_previous_source_snapshot_reproducible"] is False
    assert result["source_state"] == "test-source"
    assert result["source_snapshot_reproducible"] is True
    assert refreshed == result


def test_h48_stronger_table_campaign_forwards_recovery_adoption_flag(tmp_path):
    decision = build_campaign_decision(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        target_solver="h48h10",
        threads=2,
        allow_unsafe_generation=False,
        dry_run=True,
        capacity_payload={
            "strongest_local_oracle_solver": "h48h7",
            "next_missing_oracle_grade_solver": "h48h8",
        },
        safety={
            "solver": "h48h10",
            "estimated_table_size_bytes": estimated_h48_table_size_bytes("h48h10"),
            "safe_to_start": True,
            "reasons": [],
        },
    )

    assert "--adopt-existing-table-metadata" in decision["generation_command_args"]


def test_h48_table_bundle_installer_validates_and_canonicalizes_table(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    source = tmp_path / "bundle_source"
    source.mkdir()
    source_table = source / "h48h8.bin"
    source_table.write_bytes(b"12345678")
    source_metadata = source / "h48_metadata_seed_2026_thesis_h48h8.json"
    source_metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_kind": "h48_pruning_table",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "h_value": 8,
                "file_path": "some/other/path/h48h8.bin",
                "checksum_sha256": h48_tables.sha256_file(source_table),
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
                "table_size_bytes": 8,
                "estimated_table_size_bytes": 8,
                "estimated_size_matches_actual": True,
            }
        ),
        encoding="utf-8",
    )
    bundle = tmp_path / "h48h8_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(source_table, arcname="tables/h48h8.bin")
        archive.add(source_metadata, arcname="metadata/h48_metadata_seed_2026_thesis_h48h8.json")

    payload, output = install_h48_table_bundle(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        bundle=bundle,
        artifact_suffix="test",
    )

    target_table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")
    target_metadata = h48_tables.h48_metadata_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    saved_metadata = json.loads(target_metadata.read_text(encoding="utf-8"))

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "installed_from_bundle"
    assert payload["copied_table"] is True
    assert payload["table_install_method"] == "hardlink_from_extracted_bundle"
    assert payload["table_install_details"]["hardlink_attempted"] is True
    assert payload["table_install_details"]["hardlink_succeeded"] is True
    assert payload["table_install_details"]["fallback_copy_used"] is False
    assert payload["post_install_full_checksum_valid"] is True
    assert target_table.read_bytes() == b"12345678"
    assert saved_metadata["file_path"] == "data/generated/h48/thesis_seed_2026/h48h8.bin"
    assert saved_metadata["import_status"] == "installed_from_bundle"
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_table_bundle_creator_and_installer_support_split_manifest_bundle(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    target_table = h48_tables.h48_table_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_metadata = h48_tables.h48_metadata_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_table.parent.mkdir(parents=True, exist_ok=True)
    target_metadata.parent.mkdir(parents=True, exist_ok=True)
    target_table.write_bytes(b"12345678")
    target_metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_kind": "h48_pruning_table",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "h_value": 8,
                "file_path": str(target_table.relative_to(tmp_path)),
                "checksum_sha256": h48_tables.sha256_file(target_table),
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
                "table_size_bytes": 8,
                "estimated_table_size_bytes": 8,
                "estimated_size_matches_actual": True,
            }
        ),
        encoding="utf-8",
    )

    parts_dir = tmp_path / "results" / "h48h8_parts"
    bundle_payload, bundle_output = create_h48_table_bundle(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        output_dir=parts_dir,
        part_size_bytes=3,
        artifact_suffix="split_test",
    )

    assert bundle_output.exists()
    assert bundle_payload["passed"] is True
    assert bundle_payload["part_count"] == 3
    assert bundle_payload["split_written_part_count"] == 3
    assert (parts_dir / "h48_table_bundle_manifest.json").exists()

    target_table.unlink()
    target_metadata.unlink()
    payload, _output = install_h48_table_bundle(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        bundle=parts_dir,
        artifact_suffix="split_install_test",
    )

    assert payload["passed"] is True
    assert payload["status"] == "installed_from_bundle"
    assert payload["bundle_resolution_details"]["bundle_resolution_kind"] == "split_manifest"
    assert payload["bundle_resolution_details"]["parts_validated"] is True
    assert payload["bundle_resolution_details"]["part_count"] == 3
    assert payload["source_validation_details"]["checksum_source"] == (
        "prevalidated_split_manifest_assembly"
    )
    assert payload["table_install_method"] == "hardlink_from_extracted_bundle"
    assert payload["post_install_full_checksum_valid"] is True
    assert target_table.read_bytes() == b"12345678"
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_split_bundle_smoke_installs_real_split_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    target_table = h48_tables.h48_table_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_metadata = h48_tables.h48_metadata_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_table.parent.mkdir(parents=True, exist_ok=True)
    target_metadata.parent.mkdir(parents=True, exist_ok=True)
    target_table.write_bytes(b"12345678")
    target_metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_kind": "h48_pruning_table",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "h_value": 8,
                "file_path": str(target_table.relative_to(tmp_path)),
                "checksum_sha256": h48_tables.sha256_file(target_table),
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
                "table_size_bytes": 8,
                "estimated_table_size_bytes": 8,
                "estimated_size_matches_actual": True,
            }
        ),
        encoding="utf-8",
    )

    payload, output = run_h48_split_bundle_smoke(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        part_size_bytes=3,
        artifact_suffix="test",
    )

    installed_table = (
        tmp_path
        / "results"
        / "h48_split_bundle_smoke_seed_2026_thesis_h48h8_test_install_root"
        / "data"
        / "generated"
        / "h48"
        / "thesis_seed_2026"
        / "h48h8.bin"
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["bundle_part_count"] == 3
    assert payload["split_manifest_validated"] is True
    assert payload["split_parts_validated"] is True
    assert payload["installed_from_split_manifest"] is True
    assert payload["post_install_full_checksum_valid"] is True
    assert payload["source_checksum_sha256"] == payload["installed_checksum_sha256"]
    assert payload["installed_table_size_bytes"] == 8
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert installed_table.read_bytes() == b"12345678"


def test_h48_table_bundle_installer_skips_source_when_target_full_checksum_trusted(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    target_table = h48_tables.h48_table_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_metadata = h48_tables.h48_metadata_path(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    target_table.parent.mkdir(parents=True, exist_ok=True)
    target_metadata.parent.mkdir(parents=True, exist_ok=True)
    target_table.write_bytes(b"ABCDEFGH")
    target_metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "table_kind": "h48_pruning_table",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "h_value": 8,
                "file_path": str(target_table.relative_to(tmp_path)),
                "checksum_sha256": h48_tables.sha256_file(target_table),
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
                "table_size_bytes": 8,
                "estimated_table_size_bytes": 8,
                "estimated_size_matches_actual": True,
            }
        ),
        encoding="utf-8",
    )

    def fail_resolve(**_kwargs):
        raise AssertionError("source bundle should not be resolved when target is fully trusted")

    monkeypatch.setattr(h48_bundle_installer, "_resolve_bundle_inputs", fail_resolve)

    payload, output = install_h48_table_bundle(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        bundle=tmp_path / "missing_bundle.tar.gz",
        artifact_suffix="already_installed",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["status"] == "target_table_already_trusted"
    assert payload["target_table_already_installed"] is True
    assert payload["source_validation_skipped"] is True
    assert payload["source_validation_passed"] is None
    assert payload["copied_table"] is False
    assert payload["table_install_method"] is None
    assert payload["post_install_full_checksum_valid"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_h48_table_bundle_installer_rejects_checksum_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(h48_tables, "estimated_h48_table_size_bytes", lambda _solver: 8)
    source = tmp_path / "bad_bundle"
    source.mkdir()
    source_table = source / "h48h8.bin"
    source_table.write_bytes(b"12345678")
    source_metadata = source / "h48_metadata_seed_2026_thesis_h48h8.json"
    source_metadata.write_text(
        json.dumps(
            {
                "table_kind": "h48_pruning_table",
                "profile": "thesis",
                "seed": 2026,
                "solver": "h48h8",
                "checksum_sha256": "0" * 64,
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
                "table_size_bytes": 8,
                "estimated_table_size_bytes": 8,
                "estimated_size_matches_actual": True,
            }
        ),
        encoding="utf-8",
    )

    payload, _output = install_h48_table_bundle(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        table_path=source_table,
        metadata_path=source_metadata,
        artifact_suffix="bad",
    )

    target_table = h48_tables.h48_table_path(root=tmp_path, profile="thesis", seed=2026, solver="h48h8")
    assert payload["passed"] is False
    assert payload["status"] == "source_validation_failed"
    assert any("checksum" in reason for reason in payload["source_validation_reasons"])
    assert not target_table.exists()
