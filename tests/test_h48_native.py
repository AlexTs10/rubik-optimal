import json
from types import SimpleNamespace

from rubik_optimal.cube import CubeState
from rubik_optimal.oracle import FastOptimalOracle, FastOptimalOracleConfig
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.h48_native import (
    H48NativeOracleSession,
    _h48_symmetry_rotations,
    compute_h48_native_lower_bound,
    compute_h48_native_lower_bound_batch,
    compute_h48_native_rotational_lower_bound,
    compute_h48_native_rotational_lower_bound_batch,
    cube_to_nissy_string,
    solve_h48_native_batch,
    solve_h48_native_optimal,
    solve_h48_native_resident_batch,
    solve_h48_native_rotational_race,
)
from scripts.run_h48_oracle_certification import certification_cases, superflip_cube
from scripts.validate_h48_worker_table import validate_worker_table
from rubik_optimal.tables.h48 import (
    H48_TABLE_ROOT_ENV,
    H48_FASTEST_SOLVER,
    ORACLE_H48_SOLVER,
    canonical_h48_solver,
    estimated_h48_table_size_bytes,
    generate_h48_table,
    h48_checksum_certificate_path,
    h48_metadata_path,
    h48_solver_h_value,
    h48_table_root,
    h48_table_path,
    highest_available_h48_solver,
    build_h48_backend,
    repository_root,
    validate_trusted_h48_table_checksum,
    validate_trusted_h48_table,
)
from rubik_optimal.tables.metadata import sha256_file
from scripts.run_h48_resident_certification import _default_artifact_suffix, hard_case_ids


def _h48_axis_group(rotation):
    target_up_face = rotation.face_map["U"]
    if target_up_face in {"F", "B"}:
        return "FB"
    if target_up_face in {"R", "L"}:
        return "RL"
    return "UD"


def test_h48_backend_compiles_from_vendored_source():
    binary = build_h48_backend(root=repository_root(), threads=2, arch="PORTABLE")
    assert binary.exists()


def test_h48_native_solved_state_is_exact_without_table():
    result = solve_h48_native_optimal(CubeState.solved(), root=repository_root())
    assert result.status == "exact"
    assert result.solution_moves == []
    assert result.solution_length == 0
    assert result.is_verified


def test_h48_state_conversion_matches_nissy_solved_string():
    assert cube_to_nissy_string(CubeState.solved()) == "ABCDEFGH=ABCDEFGHIJKL=A"


def test_h48_superflip_certification_case_is_valid_distance_20_target():
    cube = superflip_cube()
    assert cube.verify_physical()[0] == 0
    assert cube.cp == CubeState.solved().cp
    assert cube.co == CubeState.solved().co
    assert cube.ep == CubeState.solved().ep
    assert cube.eo == (1,) * 12

    superflip_cases = [case for case in certification_cases(2026) if case.case_id == "superflip_distance_20"]
    assert len(superflip_cases) == 1
    assert superflip_cases[0].expected_distance == 20


def test_h48_oracle_solver_aliases_and_sizes_are_explicit():
    assert h48_solver_h_value("h48h0") == 0
    assert h48_solver_h_value("h48h7") == 7
    assert h48_solver_h_value("optimal") == 7
    assert canonical_h48_solver("optimal") == "h48h7"
    assert estimated_h48_table_size_bytes("h48h0") == 31683944
    assert estimated_h48_table_size_bytes("optimal") == estimated_h48_table_size_bytes("h48h7")
    assert estimated_h48_table_size_bytes("h48h7") == 3793842344


def test_fast_optimal_oracle_config_defaults_to_strongest_trusted_h48():
    # Pin the load probe so the test is deterministic on busy workstations.
    import rubik_optimal.runtime as runtime

    runtime_count = runtime.suggest_thread_count(cpu_count=8, load_average=0.25)
    config = FastOptimalOracleConfig()
    assert config.solver == H48_FASTEST_SOLVER
    assert highest_available_h48_solver(profile="thesis") == ORACLE_H48_SOLVER == "h48h7"
    assert runtime_count == 8
    assert 1 <= config.threads <= 8
    assert config.timeout_seconds is None
    assert config.max_depth == 20
    assert config.trusted_table is True
    assert config.auto_min_depth is False


def test_fast_optimal_oracle_threads_can_be_limited_by_environment(monkeypatch):
    monkeypatch.setenv("RUBIK_OPTIMAL_H48_THREADS", "3")
    config = FastOptimalOracleConfig()
    assert config.threads == 3


def test_fast_optimal_oracle_threads_can_be_auto_sized_by_environment(monkeypatch):
    monkeypatch.setenv("RUBIK_OPTIMAL_H48_THREADS", "auto")
    monkeypatch.setattr("rubik_optimal.runtime.os.cpu_count", lambda: 8)
    monkeypatch.setattr("rubik_optimal.runtime.os.getloadavg", lambda: (4.9, 3.9, 3.8))

    config = FastOptimalOracleConfig()
    assert config.threads == 3


def test_fast_optimal_oracle_solved_state_does_not_start_native_backend(tmp_path):
    config = FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing-h48h7.bin")
    result = FastOptimalOracle(config).solve(CubeState.solved())

    assert result.solver_name == "fast_optimal_oracle_h48h7"
    assert result.status == "exact"
    assert result.solution_moves == []
    assert result.solution_length == 0
    assert result.is_verified
    assert "resident native H48 backend not invoked" in result.notes


def test_fast_optimal_oracle_solves_direct_cube_with_resident_h48h7():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver=ORACLE_H48_SOLVER)
    assert table.exists()

    config = FastOptimalOracleConfig(root=root, threads=2, timeout_seconds=30.0)
    cube = CubeState.from_sequence("R U F2")
    with FastOptimalOracle(config) as oracle:
        result = oracle.solve(cube)

    assert result.solver_name == "fast_optimal_oracle_h48h7"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "arbitrary_valid_3x3_domain=true" in result.notes
    assert "resident_native_h48=true" in result.notes
    assert "trusted_table=True" in result.notes
    assert "search_timeout_ms=30000" in result.notes


def test_h48_table_paths_canonicalize_optimal_alias():
    root = repository_root()
    assert h48_table_path(root=root, solver="optimal") == h48_table_path(root=root, solver="h48h7")
    assert h48_metadata_path(root=root, solver="optimal") == h48_metadata_path(root=root, solver="h48h7")


def test_h48_table_root_can_be_relocated_by_environment(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    external = tmp_path / "proof-volume" / "h48"
    monkeypatch.setenv(H48_TABLE_ROOT_ENV, str(external))

    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="optimal")

    assert h48_table_root(root=root) == external
    assert table == external / "thesis_seed_2026" / "h48h7.bin"
    assert h48_metadata_path(root=root, profile="thesis", seed=2026, solver="optimal") == (
        root / "results" / "processed" / "h48_metadata_seed_2026_thesis_h48h7.json"
    )


def test_h48_external_table_root_metadata_validates(tmp_path, monkeypatch):
    import rubik_optimal.tables.h48 as h48_tables

    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "proof-volume" / "h48"
    monkeypatch.setenv(H48_TABLE_ROOT_ENV, str(external))

    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"external-h48-table")
    monkeypatch.setattr(
        h48_tables,
        "estimated_h48_table_size_bytes",
        lambda _solver: table.stat().st_size,
    )
    monkeypatch.setattr(
        h48_tables,
        "_run_h48_adoption_native_canary",
        lambda **_kwargs: {"passed": True, "native_payload": {"status": "exact", "table_check": "verified"}},
    )

    row = generate_h48_table(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        adopt_existing_table_metadata=True,
    )
    metadata = json.loads(
        h48_metadata_path(root=root, profile="thesis", seed=2026, solver="h48h8").read_text(
            encoding="utf-8"
        )
    )
    metadata_ok, metadata_message = validate_trusted_h48_table(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    checksum_ok, checksum_message, checksum_details = validate_trusted_h48_table_checksum(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        use_cache=False,
    )

    assert row["file_path"] == str(table)
    assert row["h48_table_root_env"] == H48_TABLE_ROOT_ENV
    assert row["h48_table_root"] == str(external)
    assert row["adoption_native_table_check_passed"] is True
    assert metadata["file_path"] == str(table)
    assert metadata_ok, metadata_message
    assert checksum_ok, checksum_message
    assert checksum_details["table_path"] == str(table)
    inventory = h48_tables.h48_table_inventory(root=root, profile="thesis", seed=2026, min_h=8, max_h=8)
    assert inventory[0]["table_path"] == str(table)
    assert inventory[0]["trusted_metadata_valid"] is True


def test_h48_trusted_table_requires_generated_metadata_contract():
    root = repository_root()
    ok, message = validate_trusted_h48_table(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert ok, message
    assert "without per-call checksum scan" in message

    ok, message = validate_trusted_h48_table(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        table_path=root / "data" / "generated" / "h48" / "thesis_seed_2026" / "not-canonical.bin",
    )
    assert not ok
    assert "canonical generated table path" in message


def test_h48_full_checksum_validation_rejects_same_size_corrupt_table(tmp_path, monkeypatch):
    import rubik_optimal.tables.h48 as h48_tables

    root = tmp_path
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    metadata = h48_metadata_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    table.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"same-size-corrupt-test")
    monkeypatch.setattr(
        h48_tables,
        "estimated_h48_table_size_bytes",
        lambda _solver: table.stat().st_size,
    )
    metadata.write_text(
        json.dumps(
            {
                "table_kind": "h48_pruning_table",
                "backend_source": "vendored_nissy_core_h48",
                "solver": "h48h8",
                "file_path": str(table.relative_to(root)),
                "table_size_bytes": table.stat().st_size,
                "estimated_table_size_bytes": table.stat().st_size,
                "estimated_size_matches_actual": True,
                "checksum_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    metadata_ok, metadata_message = validate_trusted_h48_table(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
    )
    full_ok, full_message, details = validate_trusted_h48_table_checksum(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        use_cache=False,
    )

    assert metadata_ok, metadata_message
    assert full_ok is False
    assert "full checksum mismatch" in full_message
    assert details["trusted_metadata_valid"] is True
    assert details["full_checksum_valid"] is False
    assert details["actual_checksum_sha256"] == sha256_file(table)


def test_h48_worker_table_validation_writes_auditable_checksum_artifact(tmp_path, monkeypatch):
    import rubik_optimal.tables.h48 as h48_tables

    root = tmp_path
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    metadata = h48_metadata_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    table.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"valid-worker-table-test")
    monkeypatch.setattr(
        h48_tables,
        "estimated_h48_table_size_bytes",
        lambda _solver: table.stat().st_size,
    )
    metadata.write_text(
        json.dumps(
            {
                "table_kind": "h48_pruning_table",
                "backend_source": "vendored_nissy_core_h48",
                "solver": "h48h8",
                "file_path": str(table.relative_to(root)),
                "table_size_bytes": table.stat().st_size,
                "estimated_table_size_bytes": table.stat().st_size,
                "estimated_size_matches_actual": True,
                "checksum_sha256": sha256_file(table),
            }
        ),
        encoding="utf-8",
    )

    payload, output = validate_worker_table(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        artifact_suffix="worker_test",
        use_cache=False,
    )

    assert output.exists()
    assert output.name == "h48_worker_table_validation_seed_2026_thesis_h48h8_worker_test.json"
    assert payload["passed"] is True
    assert payload["trusted_metadata_valid"] is True
    assert payload["full_checksum_valid"] is True
    assert payload["table_path"] == "data/generated/h48/thesis_seed_2026/h48h8.bin"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["details"]["actual_checksum_sha256"] == sha256_file(table)


def test_h48_full_checksum_persistent_certificate_reuses_verified_table(tmp_path, monkeypatch):
    import os
    import rubik_optimal.tables.h48 as h48_tables
    from rubik_optimal.tables.metadata import sha256_file as real_sha256_file

    root = tmp_path
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    metadata = h48_metadata_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    certificate = h48_checksum_certificate_path(root=root, profile="thesis", seed=2026, solver="h48h8")
    table.parent.mkdir(parents=True, exist_ok=True)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"valid-persistent-cache-table")
    monkeypatch.setattr(
        h48_tables,
        "estimated_h48_table_size_bytes",
        lambda _solver: table.stat().st_size,
    )
    metadata.write_text(
        json.dumps(
            {
                "table_kind": "h48_pruning_table",
                "backend_source": "vendored_nissy_core_h48",
                "solver": "h48h8",
                "file_path": str(table.relative_to(root)),
                "table_size_bytes": table.stat().st_size,
                "estimated_table_size_bytes": table.stat().st_size,
                "estimated_size_matches_actual": True,
                "checksum_sha256": real_sha256_file(table),
            }
        ),
        encoding="utf-8",
    )

    first_ok, first_message, first_details = validate_trusted_h48_table_checksum(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        use_cache=False,
        persistent_cache=True,
    )

    assert first_ok, first_message
    assert certificate.exists()
    assert first_details["checksum_certificate_written"] is True

    def fail_sha256(_path):
        raise AssertionError("persistent certificate should avoid a second full checksum read")

    monkeypatch.setattr(h48_tables, "sha256_file", fail_sha256)
    second_ok, second_message, second_details = validate_trusted_h48_table_checksum(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        use_cache=False,
        persistent_cache=True,
    )

    assert second_ok, second_message
    assert "certificate reused" in second_message
    assert second_details["checksum_persistent_cache_hit"] is True
    assert second_details["checksum_certificate_path"] == str(certificate.relative_to(root))

    replacement = b"corrupt-persist-cache-table".ljust(table.stat().st_size, b"!")
    assert len(replacement) == table.stat().st_size
    table.write_bytes(replacement)
    stat = table.stat()
    os.utime(table, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    monkeypatch.setattr(h48_tables, "sha256_file", real_sha256_file)

    stale_ok, stale_message, stale_details = validate_trusted_h48_table_checksum(
        root=root,
        profile="thesis",
        seed=2026,
        solver="h48h8",
        use_cache=False,
        persistent_cache=True,
    )

    assert stale_ok is False
    assert "full checksum mismatch" in stale_message
    assert stale_details["checksum_persistent_cache_hit"] is False
    assert stale_details["checksum_certificate_present"] is True
    assert stale_details["checksum_certificate_message"] == "checksum certificate identity mismatch"


def test_h48_native_solves_non_solved_cube_without_source_sequence():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    result = solve_h48_native_optimal(
        cube,
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=8,
        root=root,
    )

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "input_mode=cube_state" in result.notes
    assert "search_timeout_ms=10000" in result.notes
    assert "timed_out_by_poll=False" in result.notes


def test_h48_native_reports_completed_bounded_negative_search_as_lower_bound():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    result = solve_h48_native_optimal(
        cube,
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=2,
        max_depth=2,
        root=root,
    )

    assert result.status == "lower_bound"
    assert result.solution_length is None
    assert not result.is_verified
    assert "proved_lower_bound=3" in result.notes
    assert "search_deadline_expired=False" in result.notes


def test_h48_native_lower_bound_probe_returns_admissible_value():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    result = compute_h48_native_lower_bound(
        cube,
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=2,
        skip_table_check=True,
        root=root,
    )

    assert result.status == "lower_bound"
    assert result.lower_bound is not None
    assert 0 <= result.lower_bound <= 3
    assert "admissible lower-bound probe" in result.notes


def test_h48_native_rotational_lower_bound_batches_one_table_load():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    result = compute_h48_native_rotational_lower_bound(
        cube,
        variant_count=2,
        include_identity=True,
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=2,
        skip_table_check=True,
        root=root,
    )

    assert result.status == "lower_bound"
    assert result.lower_bound is not None
    assert 0 <= result.lower_bound <= 3
    assert "rotational admissible lower-bound batch" in result.notes
    assert "rotation_count=3" in result.notes


def test_h48_native_lower_bound_batch_loads_table_once():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    results = compute_h48_native_lower_bound_batch(
        [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")],
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=2,
        skip_table_check=True,
        root=root,
    )

    assert [result.status for result in results] == ["lower_bound", "lower_bound"]
    assert all(result.lower_bound is not None for result in results)
    assert all("multi-cube lower-bound batch" in result.notes for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)
    assert all("batch_input_count=2" in result.notes for result in results)


def test_h48_native_rotational_lower_bound_batch_flattens_rotations_once(monkeypatch, tmp_path):
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48 table")
    captured: dict[str, object] = {}

    def fake_run(*_args, **kwargs):
        captured["input_line_count"] = len([line for line in kwargs["input"].splitlines() if line.strip()])
        stdout = "\n".join(
            [
                '{"status":"lower_bound","lower_bound":1,"runtime_seconds":0.01}',
                '{"status":"lower_bound","lower_bound":2,"runtime_seconds":0.01}',
                '{"status":"lower_bound","lower_bound":3,"runtime_seconds":0.01}',
                '{"status":"lower_bound","lower_bound":4,"runtime_seconds":0.01}',
            ]
        ) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr(h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")
    monkeypatch.setattr(h48_native.subprocess, "run", fake_run)

    results = compute_h48_native_rotational_lower_bound_batch(
        [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")],
        variant_count=1,
        include_identity=True,
        solver="h48h0",
        profile="thesis",
        seed=2026,
        table_path=table,
        timeout_seconds=1.0,
        threads=1,
        root=tmp_path,
    )

    assert captured["input_line_count"] == 4
    assert [result.status for result in results] == ["lower_bound", "lower_bound"]
    assert [result.lower_bound for result in results] == [2, 4]
    assert all("rotational admissible multi-cube lower-bound batch" in result.notes for result in results)
    assert all("source_batch_size=2" in result.notes for result in results)
    assert all("rotation_count=2" in result.notes for result in results)
    assert all("flattened_rotation_count=4" in result.notes for result in results)


def test_h48_rotational_lower_bound_timeout_preserves_completed_rows(monkeypatch, tmp_path):
    import subprocess
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48 table")

    def fake_run(*_args, **_kwargs):
        stdout = "\n".join(
            [
                '{"status":"lower_bound","lower_bound":1,"runtime_seconds":0.01}',
                '{"status":"lower_bound","lower_bound":9,"runtime_seconds":0.02}',
            ]
        ) + "\n"
        raise subprocess.TimeoutExpired(cmd=["h48"], timeout=1.0, output=stdout)

    monkeypatch.setattr(h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")
    monkeypatch.setattr(h48_native.subprocess, "run", fake_run)

    result = compute_h48_native_rotational_lower_bound(
        CubeState.from_sequence("R U F2"),
        variant_count=2,
        include_identity=True,
        solver="h48h0",
        profile="thesis",
        seed=2026,
        table_path=table,
        timeout_seconds=1.0,
        threads=1,
        root=tmp_path,
    )

    assert result.status == "lower_bound"
    assert result.lower_bound == 9
    assert "partial_timeout_recovered=true" in result.notes
    assert "partial_completed_count=2" in result.notes
    assert "rotation_count=3" in result.notes


def test_h48_native_batch_solves_multiple_states_after_one_table_load():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    results = solve_h48_native_batch(
        [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U F2")],
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=8,
        root=root,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 3]
    assert all(result.is_verified for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)
    assert all("search_timeout_ms=10000" in result.notes for result in results)


def test_h48_resident_oracle_reuses_one_native_process_for_multiple_states():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    results = solve_h48_native_resident_batch(
        [cube, cube],
        solver="h48h0",
        profile="thesis",
        timeout_seconds=10,
        threads=2,
        skip_table_check=True,
        root=root,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 3]
    assert all(result.is_verified for result in results)
    assert all("resident in-repo native H48 backend" in result.notes for result in results)
    assert all("resident_batch_pipelined=true" in result.notes for result in results)
    assert all("batch_input_count=2" in result.notes for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)
    assert all("search_timeout_ms=10000" in result.notes for result in results)


def test_h48_symmetry_rotation_selection_covers_non_ud_axes_first():
    rotations = _h48_symmetry_rotations(2, include_identity=False)

    assert len(rotations) == 2
    assert {rotation.is_identity for rotation in rotations} == {False}
    assert [_h48_axis_group(rotation) for rotation in rotations] == ["FB", "RL"]


def test_h48_symmetry_rotation_selection_keeps_identity_then_axis_representatives():
    rotations = _h48_symmetry_rotations(2, include_identity=True)

    assert len(rotations) == 3
    assert rotations[0].is_identity
    assert [_h48_axis_group(rotation) for rotation in rotations] == ["UD", "FB", "RL"]


def test_h48_resident_oracle_solves_rotated_direct_state_variant():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    with H48NativeOracleSession(
        solver="h48h0",
        profile="thesis",
        search_timeout_seconds=10,
        threads=1,
        skip_table_check=True,
        root=root,
    ) as session:
        result = session.solve_rotated_variants(
            cube,
            variant_count=1,
            include_identity=False,
            timeout_seconds=10,
        )

    assert result.solver_name == "h48_native_h48h0_symmetry_batch"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "rotated_exact_solution_mapped_back_and_verified" in result.notes
    assert "identity_rotation_included=False" in result.notes
    assert "selected_rotation=" in result.notes


def test_h48_resident_rotated_variants_uses_global_timeout(monkeypatch, tmp_path):
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake h48 table")
    clock = {"now": 100.0}
    timeouts: list[float | None] = []

    monkeypatch.setattr(h48_native.time, "perf_counter", lambda: clock["now"])

    def fake_solve(self, cube_arg, *, timeout_seconds=None):
        timeouts.append(timeout_seconds)
        clock["now"] += 3.1
        return SolverResult(
            solver_name=f"h48_native_{self.solver}",
            input_state=cube_arg.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=3.1,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=table.stat().st_size,
            status="timeout",
            is_verified=False,
            notes="fake resident timeout",
        )

    monkeypatch.setattr(H48NativeOracleSession, "solve", fake_solve)

    session = H48NativeOracleSession(
        solver="h48h0",
        table_path=table,
        threads=1,
        root=tmp_path,
    )
    result = session.solve_rotated_variants(
        CubeState.from_sequence("R U F2"),
        variant_count=3,
        include_identity=True,
        timeout_seconds=3.0,
    )

    assert timeouts == [3.0]
    assert result.status == "timeout"
    assert "global_timeout_seconds=3.0" in result.notes
    assert "global_timeout_expired=True" in result.notes
    assert "pending_rotations_not_started=3" in result.notes


def test_h48_resident_rotated_variants_honors_explicit_rotation_order(monkeypatch, tmp_path):
    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake h48 table")
    rotations = _h48_symmetry_rotations(3, include_identity=True)
    ordered_rotations = [rotations[2], rotations[0], rotations[1]]
    solved_rotation = ordered_rotations[1]
    attempted: list[str] = []

    def fake_solve(self, cube_arg, *, timeout_seconds=None):
        del timeout_seconds
        for rotation in ordered_rotations:
            if rotation.transform_cube(CubeState.from_sequence("R U F2")) == cube_arg:
                attempted.append(rotation.name)
                status = "exact" if rotation.name == solved_rotation.name else "timeout"
                return SolverResult(
                    solver_name=f"h48_native_{self.solver}",
                    input_state=cube_arg.to_facelets(),
                    solution_moves=["F2", "U'", "R'"] if status == "exact" else [],
                    solution_length=3 if status == "exact" else None,
                    metric="HTM",
                    runtime_seconds=0.01,
                    expanded_nodes=1,
                    generated_nodes=None,
                    table_bytes=table.stat().st_size,
                    status=status,
                    is_verified=status == "exact",
                    notes=f"fake resident {status}",
                )
        raise AssertionError("unexpected rotated cube")

    monkeypatch.setattr(H48NativeOracleSession, "solve", fake_solve)

    session = H48NativeOracleSession(
        solver="h48h0",
        table_path=table,
        threads=1,
        root=tmp_path,
    )
    result = session.solve_rotated_variants(
        CubeState.from_sequence("R U F2"),
        variant_count=3,
        include_identity=True,
        timeout_seconds=10.0,
        rotations=ordered_rotations,
        rotation_order_note="resident_h48_symmetry_h48_lower_bound_rotation_order=true; order_status=applied",
    )

    assert result.status == "exact"
    assert result.is_verified
    assert attempted == [ordered_rotations[0].name, ordered_rotations[1].name]
    assert f"selected_rotation={solved_rotation.name}" in result.notes
    assert f"rotation_order={[rotation.name for rotation in ordered_rotations]}" in result.notes
    assert "resident_h48_symmetry_h48_lower_bound_rotation_order=true" in result.notes


def test_h48_resident_native_timeout_row_keeps_loaded_process(monkeypatch, tmp_path):
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48 table")
    fake_processes = []
    select_timeouts = []

    class FakeStdin:
        def __init__(self) -> None:
            self.closed = False
            self.writes = []

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            return None

        def close(self):
            self.closed = True

    class FakeStdout:
        def __init__(self) -> None:
            self.lines = [
                (
                    b'{"status":"timeout","solution":"","solution_length":null,'
                    b'"proved_lower_bound":0,"runtime_seconds":10.0,'
                    b'"expanded_nodes":0,"table_lookups":0,"table_fallbacks":0,'
                    b'"table_size_bytes":14,"table_check":"verified",'
                    b'"table_storage":"mmap","table_preload":"disabled",'
                    b'"auto_min_depth":"disabled","lower_bound":0,'
                    b'"min_depth":0,"max_depth":20,"search_timeout_ms":10000,'
                    b'"timed_out_by_poll":true,"search_deadline_expired":true}\n'
                ),
                (
                    b'{"status":"exact","solution":"R\\u0027","solution_length":1,'
                    b'"proved_lower_bound":0,"runtime_seconds":0.01,'
                    b'"expanded_nodes":1,"table_lookups":1,"table_fallbacks":0,'
                    b'"table_size_bytes":14,"table_check":"verified",'
                    b'"table_storage":"mmap","table_preload":"disabled",'
                    b'"auto_min_depth":"disabled","lower_bound":0,'
                    b'"min_depth":0,"max_depth":20,"search_timeout_ms":10000,'
                    b'"timed_out_by_poll":false,"search_deadline_expired":false}\n'
                ),
            ]

        def readline(self):
            return self.lines.pop(0)

    class FakeStderr:
        def read(self):
            return b""

    class FakeProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.stderr = FakeStderr()
            self.terminated = False
            self.killed = False
            fake_processes.append(self)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    def fake_select(reads, writes, errors, timeout=None):
        select_timeouts.append(timeout)
        return reads, writes, errors

    monkeypatch.setattr(h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")
    monkeypatch.setattr(h48_native.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(h48_native.select, "select", fake_select)

    with H48NativeOracleSession(
        solver="h48h0",
        profile="thesis",
        seed=2026,
        table_path=table,
        search_timeout_seconds=10,
        threads=1,
        root=tmp_path,
    ) as session:
        timeout_result = session.solve(CubeState.from_sequence("R U F2"), timeout_seconds=10)
        exact_result = session.solve(CubeState.from_sequence("R"), timeout_seconds=10)

    assert timeout_result.status == "timeout"
    assert "timed_out_by_poll=True" in timeout_result.notes
    assert "stdout_wait_timeout_seconds=12.0" in timeout_result.notes
    assert exact_result.status == "exact"
    assert exact_result.solution_length == 1
    assert exact_result.is_verified
    assert len(fake_processes) == 1
    assert fake_processes[0].terminated is False
    assert fake_processes[0].killed is False
    assert len(fake_processes[0].stdin.writes) == 2
    assert select_timeouts[:2] == [12.0, 12.0]


def test_h48_resident_timeout_survival_probe_writes_artifact(monkeypatch, tmp_path):
    import scripts.benchmark_h48_resident_timeout_survival as probe

    table = tmp_path / "h48h0.bin"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"fake h48 table")
    calls = []

    class FakeSession:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append(("closed", None))

        def solve(self, cube, *, timeout_seconds=None):
            calls.append(("solve", timeout_seconds))
            if len([call for call in calls if call[0] == "solve"]) == 1:
                return SimpleNamespace(
                    solver_name="h48_native_h48h0",
                    status="timeout",
                    solution_length=None,
                    is_verified=False,
                    runtime_seconds=0.01,
                    expanded_nodes=0,
                    table_bytes=table.stat().st_size,
                    notes=(
                        "resident in-repo native H48 backend; table_loaded_once=true; "
                        "timed_out_by_poll=True; stdout_wait_timeout_seconds=12.0"
                    ),
                )
            return SimpleNamespace(
                solver_name="h48_native_h48h0",
                status="exact",
                solution_length=1,
                is_verified=True,
                runtime_seconds=0.01,
                expanded_nodes=1,
                table_bytes=table.stat().st_size,
                notes="resident in-repo native H48 backend; table_loaded_once=true",
            )

    monkeypatch.setattr(probe, "h48_table_path", lambda **_kwargs: table)
    monkeypatch.setattr(probe, "H48NativeOracleSession", FakeSession)

    payload, output = probe.run_probe(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        threads=1,
        timeout_seconds=10.0,
        artifact_suffix="unit",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["process_reused_after_timeout"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert [row["case_id"] for row in payload["rows"]] == [
        "superflip_tiny_timeout",
        "post_timeout_simple_exact",
    ]


def test_h48_resident_solve_many_timeout_annotates_completed_rows(monkeypatch, tmp_path):
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48 table")
    select_calls = []
    fake_processes = []

    class FakeStdin:
        def __init__(self) -> None:
            self.writes = []
            self.closed = False

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            return None

        def close(self):
            self.closed = True
            return None

    class FakeStdout:
        def __init__(self) -> None:
            self.lines = [
                (
                    b'{"status":"exact","solution":"R\\u0027","solution_length":1,'
                    b'"proved_lower_bound":0,"runtime_seconds":0.01,'
                    b'"expanded_nodes":1,"table_lookups":1,"table_fallbacks":0,'
                    b'"table_size_bytes":14,"table_check":"verified",'
                    b'"table_storage":"mmap","table_preload":"disabled",'
                    b'"auto_min_depth":"disabled","lower_bound":0,'
                    b'"min_depth":0,"max_depth":20,"search_timeout_ms":1000,'
                    b'"timed_out_by_poll":false,"search_deadline_expired":false}\n'
                )
            ]

        def readline(self):
            return self.lines.pop(0)

    class FakeStderr:
        def read(self):
            return b""

    class FakeProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.stderr = FakeStderr()
            self.terminated = False
            self.killed = False
            fake_processes.append(self)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    def fake_select(reads, writes, errors, timeout=None):
        select_calls.append(timeout)
        if len(select_calls) == 1:
            return reads, writes, errors
        return [], writes, errors

    monkeypatch.setattr(h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")
    monkeypatch.setattr(h48_native.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(h48_native.select, "select", fake_select)

    with H48NativeOracleSession(
        solver="h48h0",
        profile="thesis",
        seed=2026,
        table_path=table,
        search_timeout_seconds=1.0,
        threads=1,
        root=tmp_path,
    ) as session:
        results = session.solve_many(
            [CubeState.from_sequence("R"), CubeState.from_sequence("R U F2")],
            timeout_seconds=1.0,
        )

    assert [result.status for result in results] == ["exact", "timeout"]
    assert results[0].solution_length == 1
    assert results[0].is_verified is True
    assert "resident_partial_timeout_recovered=true" in results[0].notes
    assert "partial_timeout_recovered=true" in results[0].notes
    assert "partial_completed_count=1" in results[0].notes
    assert "timeout_batch_row=1" in results[0].notes
    assert "resident_partial_timeout_recovered=true" in results[1].notes
    assert "partial_completed_count=1" in results[1].notes
    assert fake_processes[0].stdin.closed is True
    assert fake_processes[0].terminated is False
    assert fake_processes[0].killed is False
    assert len(fake_processes[0].stdin.writes) == 1
    assert select_calls == [3.0, 3.0]


def test_h48_native_batch_timeout_preserves_completed_rows(monkeypatch, tmp_path):
    import subprocess
    import rubik_optimal.solvers.h48_native as h48_native

    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48 table")

    def fake_run(*_args, **_kwargs):
        stdout = (
            '{"status":"exact","solution":"R\\u0027","solution_length":1,'
            '"proved_lower_bound":0,"runtime_seconds":0.01,'
            '"expanded_nodes":1,"table_lookups":1,"table_fallbacks":0,'
            '"table_size_bytes":14,"table_check":"verified",'
            '"table_storage":"mmap","table_preload":"disabled",'
            '"auto_min_depth":"disabled","lower_bound":0,'
            '"min_depth":0,"max_depth":20,"search_timeout_ms":1000,'
            '"timed_out_by_poll":false,"search_deadline_expired":false}\n'
        )
        raise subprocess.TimeoutExpired(cmd=["h48"], timeout=2.0, output=stdout)

    monkeypatch.setattr(h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")
    monkeypatch.setattr(h48_native.subprocess, "run", fake_run)

    results = solve_h48_native_batch(
        [CubeState.from_sequence("R"), CubeState.from_sequence("R U F2")],
        solver="h48h0",
        profile="thesis",
        seed=2026,
        table_path=table,
        timeout_seconds=1.0,
        threads=1,
        root=tmp_path,
    )

    assert [result.status for result in results] == ["exact", "timeout"]
    assert results[0].solution_length == 1
    assert results[0].is_verified
    assert "partial_timeout_recovered=true" in results[0].notes
    assert "partial_completed_count=1" in results[0].notes
    assert results[1].solution_length is None
    assert results[1].is_verified is False
    assert "partial_timeout_recovered=true" in results[1].notes
    assert "partial_completed_count=1" in results[1].notes


def test_h48_batch_partial_timeout_recovery_probe_writes_artifact(monkeypatch, tmp_path):
    import scripts.benchmark_h48_batch_partial_timeout_recovery as probe

    table = tmp_path / "h48h0.bin"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"fake h48 table")
    monkeypatch.setattr(probe, "h48_table_path", lambda **_kwargs: table)
    monkeypatch.setattr(probe.h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")

    payload, output = probe.run_probe(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        timeout_seconds=1.0,
        artifact_suffix="unit",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["partial_rows_preserved"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert [row["status"] for row in payload["rows"]] == ["exact", "timeout"]
    assert payload["rows"][0]["verified"] is True


def test_h48_parallel_rotational_race_solves_direct_state_variant():
    root = repository_root()
    table = h48_table_path(root=root, profile="thesis", seed=2026, solver="h48h0")
    assert table.exists()

    cube = CubeState.from_sequence("R U F2")
    result = solve_h48_native_rotational_race(
        cube,
        solver="h48h0",
        profile="thesis",
        variant_count=2,
        include_identity=True,
        max_concurrency=1,
        timeout_seconds=10,
        threads=1,
        skip_table_check=True,
        root=root,
    )

    assert result.solver_name == "h48_native_h48h0_parallel_symmetry_race"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "parallel H48 rotational symmetry race" in result.notes
    assert "exactness_policy=first_rotated_exact_solution_mapped_back_and_verified" in result.notes
    assert "selected_rotation=" in result.notes
    assert "max_concurrency=1" in result.notes


def test_h48_parallel_rotational_race_pools_later_rotation_waves(monkeypatch, tmp_path):
    started_commands: list[list[str]] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            started_commands.append(command)

        def poll(self):
            return 0

        def communicate(self):
            return (
                '{"status":"failed","solution":"","solution_length":null,'
                '"expanded_nodes":null,"table_lookups":0,"table_fallbacks":0}',
                "",
            )

    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.build_h48_backend", lambda **kwargs: tmp_path / "fake_h48")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.Popen", FakeProcess)

    result = solve_h48_native_rotational_race(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        profile="thesis",
        variant_count=3,
        include_identity=True,
        max_concurrency=1,
        table_path=table,
        timeout_seconds=5,
        threads=1,
        auto_min_depth=True,
        skip_table_check=False,
        root=tmp_path,
    )

    assert len(started_commands) == 4
    assert all("--auto-min-depth" in command for command in started_commands)
    assert result.status == "timeout"
    assert "max_concurrency=1" in result.notes
    assert "parallel_wave_count=4" in result.notes
    assert "effective_total_timeout_seconds=5" in result.notes
    assert "global_timeout_seconds=5" in result.notes
    assert "pending_rotations_not_started=0" in result.notes


def test_h48_parallel_rotational_race_can_order_by_lower_bound(monkeypatch, tmp_path):
    started_commands: list[list[str]] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            started_commands.append(command)

        def poll(self):
            return 0

        def communicate(self):
            return (
                '{"status":"failed","solution":"","solution_length":null,'
                '"expanded_nodes":null,"table_lookups":0,"table_fallbacks":0}',
                "",
            )

    class FakeCompleted:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    rotations = _h48_symmetry_rotations(2, include_identity=True)
    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake")

    def fake_run(command, **kwargs):
        assert "--lower-bound-batch" in command
        return FakeCompleted(
            "\n".join(
                [
                    '{"status":"lower_bound","lower_bound":1,"runtime_seconds":0.01}',
                    '{"status":"lower_bound","lower_bound":9,"runtime_seconds":0.01}',
                    '{"status":"lower_bound","lower_bound":5,"runtime_seconds":0.01}',
                ]
            )
        )

    monkeypatch.setattr("rubik_optimal.solvers.h48_native.build_h48_backend", lambda **kwargs: tmp_path / "fake_h48")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.run", fake_run)
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.Popen", FakeProcess)

    result = solve_h48_native_rotational_race(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        profile="thesis",
        variant_count=2,
        include_identity=True,
        max_concurrency=1,
        table_path=table,
        timeout_seconds=5,
        threads=1,
        skip_table_check=False,
        order_by_lower_bound=True,
        lower_bound_order_timeout_seconds=2,
        root=tmp_path,
    )

    assert len(started_commands) == 3
    assert result.status == "timeout"
    assert "h48_lower_bound_rotation_order=true" in result.notes
    assert "order_status=applied" in result.notes
    assert f"started_rotations=['{rotations[1].name}', '{rotations[2].name}', '{rotations[0].name}']" in result.notes


def test_h48_parallel_rotational_race_uses_partial_lower_bound_order_on_timeout(monkeypatch, tmp_path):
    import subprocess

    started_commands: list[list[str]] = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            started_commands.append(command)

        def poll(self):
            return 0

        def communicate(self):
            return (
                '{"status":"failed","solution":"","solution_length":null,'
                '"expanded_nodes":null,"table_lookups":0,"table_fallbacks":0}',
                "",
            )

    rotations = _h48_symmetry_rotations(2, include_identity=True)
    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake")

    def fake_run(command, **kwargs):
        assert "--lower-bound-batch" in command
        stdout = "\n".join(
            [
                '{"status":"lower_bound","lower_bound":1,"runtime_seconds":0.01}',
                '{"status":"lower_bound","lower_bound":9,"runtime_seconds":0.01}',
            ]
        ) + "\n"
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"], output=stdout)

    monkeypatch.setattr("rubik_optimal.solvers.h48_native.build_h48_backend", lambda **kwargs: tmp_path / "fake_h48")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.run", fake_run)
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.Popen", FakeProcess)

    result = solve_h48_native_rotational_race(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        profile="thesis",
        variant_count=2,
        include_identity=True,
        max_concurrency=1,
        table_path=table,
        timeout_seconds=5,
        threads=1,
        skip_table_check=False,
        order_by_lower_bound=True,
        lower_bound_order_timeout_seconds=2,
        root=tmp_path,
    )

    assert len(started_commands) == 3
    assert result.status == "timeout"
    assert "h48_lower_bound_rotation_order=true" in result.notes
    assert "order_status=partial_timeout_recovered" in result.notes
    assert "partial_completed_count=2" in result.notes
    assert f"started_rotations=['{rotations[1].name}', '{rotations[0].name}', '{rotations[2].name}']" in result.notes


def test_h48_parallel_rotational_race_enforces_per_candidate_wall_timeout(monkeypatch, tmp_path):
    started_commands: list[list[str]] = []
    stopped_commands: list[list[str]] = []
    clock = {"now": 0.0}

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None
            started_commands.append(command)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15
            stopped_commands.append(self.command)

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def communicate(self):
            return ("", "")

    def fake_perf_counter():
        return clock["now"]

    def fake_sleep(seconds):
        clock["now"] += max(seconds, 0.05)

    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.build_h48_backend", lambda **kwargs: tmp_path / "fake_h48")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.time.perf_counter", fake_perf_counter)
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.time.sleep", fake_sleep)

    result = solve_h48_native_rotational_race(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        profile="thesis",
        variant_count=1,
        include_identity=True,
        max_concurrency=1,
        table_path=table,
        timeout_seconds=1.0,
        threads=1,
        skip_table_check=False,
        root=tmp_path,
    )

    assert len(started_commands) == 1
    assert len(stopped_commands) == 1
    assert result.status == "timeout"
    assert "per_candidate_timeouts=" in result.notes
    assert "global_timeout_seconds=1.0" in result.notes
    assert "completed_rotations=" in result.notes
    assert "pending_rotations_not_started=1" in result.notes


def test_h48_parallel_rotational_race_clips_native_timeout_for_later_waves(monkeypatch, tmp_path):
    started_commands: list[list[str]] = []
    clock = {"now": 0.0}
    communicate_calls = {"count": 0}

    class FakeProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = 0
            started_commands.append(command)

        def poll(self):
            return self.returncode

        def communicate(self):
            communicate_calls["count"] += 1
            if communicate_calls["count"] == 1:
                clock["now"] = 0.6
            return (
                '{"status":"failed","solution":"","solution_length":null,'
                '"expanded_nodes":null,"table_lookups":0,"table_fallbacks":0}',
                "",
            )

    def fake_perf_counter():
        return clock["now"]

    def search_timeout_ms(command: list[str]) -> int:
        index = command.index("--search-timeout-ms")
        return int(command[index + 1])

    table = tmp_path / "h48.bin"
    table.write_bytes(b"fake")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.build_h48_backend", lambda **kwargs: tmp_path / "fake_h48")
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.subprocess.Popen", FakeProcess)
    monkeypatch.setattr("rubik_optimal.solvers.h48_native.time.perf_counter", fake_perf_counter)

    result = solve_h48_native_rotational_race(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        profile="thesis",
        variant_count=1,
        include_identity=True,
        max_concurrency=1,
        table_path=table,
        timeout_seconds=1.0,
        threads=1,
        skip_table_check=False,
        root=tmp_path,
    )

    assert len(started_commands) == 2
    assert search_timeout_ms(started_commands[0]) == 1000
    assert search_timeout_ms(started_commands[1]) == 400
    assert result.status == "timeout"
    assert "native_search_timeout_clipped_to_remaining_global_budget=true" in result.notes
    assert "per_candidate_native_search_timeout_ms=" in result.notes


def test_h48_lower_bound_partial_timeout_recovery_probe_writes_artifact(monkeypatch, tmp_path):
    import scripts.benchmark_h48_lower_bound_partial_timeout_recovery as probe

    table = tmp_path / "h48h0.bin"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_bytes(b"fake h48 table")
    monkeypatch.setattr(probe, "h48_table_path", lambda **_kwargs: table)
    monkeypatch.setattr(probe.h48_native, "build_h48_backend", lambda **_kwargs: tmp_path / "h48_backend")

    payload, output = probe.run_probe(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        solver="h48h0",
        timeout_seconds=1.0,
        artifact_suffix="unit",
    )

    assert output.exists()
    assert payload["passed"] is True
    assert payload["partial_lower_bound_preserved"] is True
    assert payload["partial_ordering_preserved"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert [row["case_id"] for row in payload["rows"]] == [
        "rotational_lower_bound_partial_timeout",
        "parallel_order_partial_timeout",
    ]


def test_h48_resident_oracle_solved_state_does_not_invoke_backend():
    session = H48NativeOracleSession(solver="h48h0", root=repository_root(), threads=1)
    result = session.solve(CubeState.solved(), timeout_seconds=1)

    assert result.status == "exact"
    assert result.solution_length == 0
    assert result.is_verified
    assert "resident H48 backend not invoked" in result.notes


def test_h48_resident_certification_names_hard_targets_and_artifact_suffix():
    assert hard_case_ids() == {"deterministic_depth_25", "superflip_distance_20"}
    assert _default_artifact_suffix("h48h7", trusted_table=True, preload_table=False) == "h48h7_trusted"
    assert _default_artifact_suffix("h48h7", trusted_table=True, preload_table=True) == "h48h7_trusted_preload"
