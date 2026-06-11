import json
import subprocess
import sys
from pathlib import Path

import scripts.generate_rubikoptimal_tables as generate_rubikoptimal_tables
import scripts.run_rubikoptimal_oracle_corpus as run_rubikoptimal_oracle_corpus
import scripts.run_rubikoptimal_oracle_stream as run_rubikoptimal_oracle_stream
import rubik_optimal.solvers.rubikoptimal_external as rubikoptimal_external
from rubik_optimal.cube import CubeState
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.rubikoptimal_external import (
    RUBIKOPTIMAL_TABLE_SIZES,
    RubikOptimalOracleSession,
    parse_rubikoptimal_batch_process_output,
    parse_rubikoptimal_process_output,
    parse_rubikoptimal_solution,
    rubikoptimal_table_inventory,
    rubikoptimal_tables_ready,
    solve_rubikoptimal_external,
    solve_rubikoptimal_external_batch,
    solve_rubikoptimal_external_rotational_race,
)
from rubik_optimal.symmetry import CUBE_ROTATIONS


def test_rubikoptimal_solution_parser_converts_kociemba_numbered_moves():
    moves, length = parse_rubikoptimal_solution("F2 U3 R3 (3f*)")

    assert moves == ["F2", "U'", "R'"]
    assert length == 3


def test_rubikoptimal_process_parser_ignores_progress_output():
    output = (
        "loading move_twist table...\n"
        "depth 17 done in 1.2 s\n"
        'RUBIKOPTIMAL_RESULT_JSON={"result":"F2 U3 R3 (3f*)"}\n'
    )

    moves, length, raw = parse_rubikoptimal_process_output(output)

    assert moves == ["F2", "U'", "R'"]
    assert length == 3
    assert raw == "F2 U3 R3 (3f*)"


def test_rubikoptimal_batch_process_parser_reads_indexed_rows():
    output = (
        "loading tables...\n"
        'RUBIKOPTIMAL_BATCH_RESULT_JSON={"index":1,"status":"ok","result":"F2 U3 R3 (3f*)",'
        '"runtime_seconds":0.5,"table_load_seconds":1.25}\n'
    )

    rows = parse_rubikoptimal_batch_process_output(output)

    assert rows[1]["moves"] == ["F2", "U'", "R'"]
    assert rows[1]["length"] == 3
    assert rows[1]["raw_solution"] == "F2 U3 R3 (3f*)"
    assert rows[1]["table_load_seconds"] == 1.25


def test_rubikoptimal_batch_process_parser_preserves_timeout_rows():
    output = (
        'RUBIKOPTIMAL_BATCH_RESULT_JSON={"index":2,"status":"timeout",'
        '"error":"resident RubikOptimal query timed out",'
        '"timeout_seconds":0.2,"runtime_seconds":0.21,'
        '"table_load_seconds":1.5}\n'
    )

    rows = parse_rubikoptimal_batch_process_output(output)

    assert rows[2]["status"] == "timeout"
    assert rows[2]["error"] == "resident RubikOptimal query timed out"
    assert rows[2]["timeout_seconds"] == 0.2
    assert rows[2]["child_runtime_seconds"] == 0.21


def test_rubikoptimal_inventory_requires_all_expected_tables(tmp_path):
    (tmp_path / "conj_twist").write_bytes(b"0" * RUBIKOPTIMAL_TABLE_SIZES["conj_twist"])

    rows = rubikoptimal_table_inventory(tmp_path)

    assert any(row["name"] == "conj_twist" and row["size_matches"] is True for row in rows)
    assert rubikoptimal_tables_ready(tmp_path) is False


def test_rubikoptimal_solver_refuses_to_import_when_tables_missing(tmp_path):
    cube = CubeState.from_sequence("R U F2")

    result = solve_rubikoptimal_external(
        cube,
        timeout_seconds=1.0,
        executable=Path("/definitely/missing"),
        package_path="/definitely/missing",
        table_dir=tmp_path,
    )

    assert result.status == "not_applicable"
    assert "tables are not ready" in result.notes
    assert result.solution_length is None


def test_rubikoptimal_solver_parses_and_verifies_fake_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)

    def fake_run(command, **kwargs):
        assert command[-1] == CubeState.from_sequence("R U F2").to_facelets()
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='RUBIKOPTIMAL_RESULT_JSON={"result":"F2 U3 R3 (3f*)"}\n',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = solve_rubikoptimal_external(
        CubeState.from_sequence("R U F2"),
        timeout_seconds=1.0,
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        table_dir=tmp_path,
    )

    assert result.status == "exact"
    assert result.is_verified is True
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert result.solution_length == 3


def _write_fake_rubikoptimal_package(tmp_path: Path, solver_source: str) -> Path:
    package_dir = tmp_path / "optimal"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "solver.py").write_text(solver_source, encoding="utf-8")
    return tmp_path


def test_rubikoptimal_batch_solver_uses_resident_session_and_verifies(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)
    package_path = _write_fake_rubikoptimal_package(
        tmp_path,
        "def solve(state):\n"
        "    return 'F2 U3 R3 (3f*)'\n",
    )

    results = solve_rubikoptimal_external_batch(
        [CubeState.solved(), CubeState.from_sequence("R U F2")],
        timeout_seconds=9.0,
        executable=Path(sys.executable),
        package_path=package_path,
        table_dir=tmp_path,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert results[0].solution_length == 0
    assert results[1].solution_moves == ["F2", "U'", "R'"]
    assert results[1].solution_length == 3
    assert "selected_backend=rubikoptimal_external_batch" in results[1].notes
    assert "batch_uses_resident_session=true" in results[1].notes
    assert "resident_start_count=1" in results[1].notes


def test_rubikoptimal_batch_solver_keeps_resident_child_after_row_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)
    package_path = _write_fake_rubikoptimal_package(
        tmp_path,
        "import time\n"
        "calls = 0\n"
        "def solve(state):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 2:\n"
        "        time.sleep(5)\n"
        "    return 'F2 U3 R3 (3f*)'\n",
    )

    results = solve_rubikoptimal_external_batch(
        [
            CubeState.from_sequence("R U F2"),
            CubeState.from_sequence("R U F2"),
            CubeState.from_sequence("R U F2"),
        ],
        timeout_seconds=3.0,
        executable=Path(sys.executable),
        package_path=package_path,
        table_dir=tmp_path,
    )

    assert [result.status for result in results] == ["exact", "timeout", "exact"]
    assert all("selected_backend=rubikoptimal_external_batch" in result.notes for result in results)
    assert all("batch_uses_resident_session=true" in result.notes for result in results)
    assert "resident_timeout_without_process_stop=true" in results[1].notes
    assert "resident_process_alive=true" in results[1].notes
    assert "resident_process_reused=true" in results[2].notes
    assert "resident_start_count=1" in results[2].notes


def test_rubikoptimal_rotational_race_maps_first_exact_solution(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)

    cube = CubeState.from_sequence("R U F2")
    rotation = next(candidate for candidate in CUBE_ROTATIONS if not candidate.is_identity)
    rotated_cube = rotation.transform_cube(cube)
    rotated_solution = rotation.transform_sequence(["F2", "U'", "R'"])
    sessions: list[object] = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = 0
            self.solve_calls: list[tuple[str, float]] = []
            sessions.append(self)

        def solve(self, cube_arg, *, timeout_seconds):
            self.solve_calls.append((cube_arg.to_facelets(), timeout_seconds))
            if cube_arg.to_facelets() == rotated_cube.to_facelets():
                return SolverResult(
                    solver_name="rubikoptimal_resident",
                    input_state=cube_arg.to_facelets(),
                    solution_moves=rotated_solution,
                    solution_length=len(rotated_solution),
                    metric="HTM",
                    runtime_seconds=0.25,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=1234,
                    status="exact",
                    is_verified=True,
                    notes="fake rotated exact",
                )
            return SolverResult(
                solver_name="rubikoptimal_resident",
                input_state=cube_arg.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.25,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=1234,
                status="timeout",
                is_verified=False,
                notes="fake rotated timeout",
            )

        def close(self):
            self.closed += 1

    monkeypatch.setattr(rubikoptimal_external, "RubikOptimalOracleSession", FakeSession)

    result = solve_rubikoptimal_external_rotational_race(
        cube,
        variant_count=1,
        include_identity=False,
        timeout_seconds=1.5,
        max_concurrency=1,
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        table_dir=tmp_path,
    )

    assert result.status == "exact"
    assert result.is_verified is True
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert result.solution_length == 3
    assert "selected_backend=rubikoptimal_rotational_race" in result.notes
    assert "selected_rotation=" in result.notes
    assert "max_concurrency=1" in result.notes
    assert len(sessions) == 1
    assert len(sessions[0].solve_calls) == 1
    assert sessions[0].solve_calls[0][0] == rotated_cube.to_facelets()
    assert 0.0 < sessions[0].solve_calls[0][1] <= 1.5
    assert sessions[0].closed >= 1


def test_rubikoptimal_rotational_race_reuses_resident_worker_for_rotation_wave(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)

    cube = CubeState.from_sequence("R U F2")
    rotations = [candidate for candidate in CUBE_ROTATIONS if not candidate.is_identity][:2]
    target_rotation = rotations[1]
    target_rotated_cube = target_rotation.transform_cube(cube)
    target_rotated_solution = target_rotation.transform_sequence(["F2", "U'", "R'"])
    sessions: list[object] = []

    class FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = 0
            self.solve_calls: list[tuple[str, float]] = []
            sessions.append(self)

        def solve(self, cube_arg, *, timeout_seconds):
            self.solve_calls.append((cube_arg.to_facelets(), timeout_seconds))
            if cube_arg.to_facelets() == target_rotated_cube.to_facelets():
                return SolverResult(
                    solver_name="rubikoptimal_resident",
                    input_state=cube_arg.to_facelets(),
                    solution_moves=target_rotated_solution,
                    solution_length=len(target_rotated_solution),
                    metric="HTM",
                    runtime_seconds=0.25,
                    expanded_nodes=None,
                    generated_nodes=None,
                    table_bytes=1234,
                    status="exact",
                    is_verified=True,
                    notes="fake second rotated exact",
                )
            return SolverResult(
                solver_name="rubikoptimal_resident",
                input_state=cube_arg.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.25,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=1234,
                status="failed",
                is_verified=False,
                notes="fake first rotated miss",
            )

        def close(self):
            self.closed += 1

    monkeypatch.setattr(rubikoptimal_external, "RubikOptimalOracleSession", FakeSession)

    result = solve_rubikoptimal_external_rotational_race(
        cube,
        variant_count=len(rotations),
        include_identity=False,
        rotations=rotations,
        timeout_seconds=1.5,
        max_concurrency=1,
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        table_dir=tmp_path,
    )

    assert result.status == "exact"
    assert result.is_verified is True
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert len(sessions) == 1
    assert [call[0] for call in sessions[0].solve_calls] == [
        rotations[0].transform_cube(cube).to_facelets(),
        target_rotated_cube.to_facelets(),
    ]
    assert all(0.0 < call[1] <= 1.5 for call in sessions[0].solve_calls)
    assert "resident_worker_pool=true" in result.notes
    assert "resident_worker_count=1" in result.notes
    assert "resident_session_count=1" in result.notes


def test_rubikoptimal_rotational_race_uses_global_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)

    cube = CubeState.from_sequence("R U F2")
    rotations = [candidate for candidate in CUBE_ROTATIONS if not candidate.is_identity][:3]
    clock = {"now": 50.0}
    timeouts: list[float] = []

    monkeypatch.setattr(rubikoptimal_external.time, "perf_counter", lambda: clock["now"])

    class FakeSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def solve(self, cube_arg, *, timeout_seconds):
            timeouts.append(timeout_seconds)
            clock["now"] += 2.1
            return SolverResult(
                solver_name="rubikoptimal_resident",
                input_state=cube_arg.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=2.1,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=1234,
                status="timeout",
                is_verified=False,
                notes="fake timeout",
            )

        def close(self):
            pass

    monkeypatch.setattr(rubikoptimal_external, "RubikOptimalOracleSession", FakeSession)

    result = solve_rubikoptimal_external_rotational_race(
        cube,
        variant_count=len(rotations),
        include_identity=False,
        rotations=rotations,
        timeout_seconds=2.0,
        max_concurrency=1,
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        table_dir=tmp_path,
    )

    assert timeouts == [2.0]
    assert result.status == "timeout"
    assert "global_timeout_seconds=2.0" in result.notes
    assert "global_timeout_expired=True" in result.notes
    assert "pending_rotations_not_started=2" in result.notes


def test_rubikoptimal_resident_session_reuses_loaded_tables(monkeypatch, tmp_path):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)
    package_root = tmp_path / "fake_package"
    solver_dir = package_root / "optimal"
    solver_dir.mkdir(parents=True)
    (solver_dir / "__init__.py").write_text("", encoding="utf-8")
    (solver_dir / "solver.py").write_text(
        "def solve(state):\n"
        "    return 'F2 U3 R3 (3f*)'\n",
        encoding="utf-8",
    )

    cube = CubeState.from_sequence("R U F2")
    with RubikOptimalOracleSession(
        executable=Path(sys.executable),
        package_path=package_root,
        table_dir=tmp_path,
    ) as session:
        first = session.solve(cube, timeout_seconds=3.0)
        second = session.solve(cube, timeout_seconds=3.0)

    assert first.status == "exact"
    assert second.status == "exact"
    assert second.solution_moves == ["F2", "U'", "R'"]
    assert session.start_count == 1
    assert "selected_backend=rubikoptimal_resident" in second.notes
    assert "resident_request_index=2" in second.notes
    assert "resident_process_reused=true" in second.notes


def test_rubikoptimal_resident_session_timeout_keeps_loaded_child_for_next_query(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(rubikoptimal_external, "rubikoptimal_table_bytes", lambda _table_dir: 1234)
    package_root = tmp_path / "fake_package"
    solver_dir = package_root / "optimal"
    solver_dir.mkdir(parents=True)
    (solver_dir / "__init__.py").write_text("", encoding="utf-8")
    (solver_dir / "solver.py").write_text(
        "import time\n"
        "calls = 0\n"
        "def solve(state):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 1:\n"
        "        time.sleep(5)\n"
        "    return 'F2 U3 R3 (3f*)'\n",
        encoding="utf-8",
    )

    cube = CubeState.from_sequence("R U F2")
    with RubikOptimalOracleSession(
        executable=Path(sys.executable),
        package_path=package_root,
        table_dir=tmp_path,
    ) as session:
        timed_out = session.solve(cube, timeout_seconds=0.25)
        second = session.solve(cube, timeout_seconds=3.0)

        assert timed_out.status == "timeout"
        assert session._process is not None
        assert session._process.poll() is None
        assert "resident_timeout_without_process_stop=true" in timed_out.notes
        assert "resident_process_alive=true" in timed_out.notes
        assert second.status == "exact"
        assert second.solution_moves == ["F2", "U'", "R'"]
        assert session.start_count == 1
        assert "resident_request_index=2" in second.notes
        assert "resident_process_reused=true" in second.notes


def test_rubikoptimal_generation_safety_refuses_loaded_machine(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_rubikoptimal_tables, "_load_average", lambda: (10.0, 9.0, 8.0))
    monkeypatch.setattr(generate_rubikoptimal_tables.os, "cpu_count", lambda: 8)

    safety = generate_rubikoptimal_tables.evaluate_rubikoptimal_generation_safety(
        root=tmp_path,
        table_dir=tmp_path / "rubikoptimal_tables",
    )

    assert safety["safe_to_start"] is False
    assert any("load average" in reason for reason in safety["reasons"])


def test_rubikoptimal_full_generation_require_safe_refuses_without_subprocess(monkeypatch, tmp_path):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("unsafe full table generation should not start")

    monkeypatch.setattr(generate_rubikoptimal_tables.subprocess, "run", fail_run)
    monkeypatch.setattr(
        generate_rubikoptimal_tables,
        "evaluate_rubikoptimal_generation_safety",
        lambda **_kwargs: {
            "safe_to_start": False,
            "reasons": ["test machine busy"],
            "expected_total_size_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
            "current_table_bytes": 0,
            "remaining_table_bytes": sum(RUBIKOPTIMAL_TABLE_SIZES.values()),
            "policy": {},
            "machine": {},
            "table_dir": "rubikoptimal_tables",
        },
    )

    payload = generate_rubikoptimal_tables.build_payload(
        root=tmp_path,
        table_dir=tmp_path / "rubikoptimal_tables",
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        timeout_seconds=1.0,
        dry_run=False,
        require_safe=True,
    )

    assert payload["status"] == "refused_unsafe_generation"
    assert payload["operation_succeeded"] is False
    assert payload["command"] is None


def test_rubikoptimal_cornerprun_only_can_make_small_progress(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        assert "optimal.solver" not in command[-1]
        assert "optimal.moves" in command[-1]
        assert kwargs["cwd"] == tmp_path
        (tmp_path / "cornerprun").write_bytes(b"0" * RUBIKOPTIMAL_TABLE_SIZES["cornerprun"])
        return subprocess.CompletedProcess(command, 0, stdout="cornerprun ready\n", stderr="")

    monkeypatch.setattr(generate_rubikoptimal_tables.subprocess, "run", fake_run)

    payload = generate_rubikoptimal_tables.build_payload(
        root=tmp_path,
        table_dir=tmp_path,
        executable=Path("/bin/echo"),
        package_path="/tmp/package",
        timeout_seconds=1.0,
        dry_run=False,
        cornerprun_only=True,
    )

    assert payload["status"] == "cornerprun_only"
    assert payload["operation_succeeded"] is True
    assert payload["passed"] is False
    assert "cornerprun" not in payload["missing_or_wrong_tables"]
    assert "phase1x24_prun" in payload["missing_or_wrong_tables"]


def test_rubikoptimal_oracle_corpus_records_state_only_exact_rows(monkeypatch, tmp_path):
    table_dir = tmp_path / "rubikoptimal_tables"
    table_dir.mkdir()
    monkeypatch.setattr(run_rubikoptimal_oracle_corpus, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(run_rubikoptimal_oracle_corpus, "rubikoptimal_table_bytes", lambda _table_dir: 963061264)
    monkeypatch.setattr(run_rubikoptimal_oracle_corpus, "rubikoptimal_table_inventory", lambda _table_dir: [])

    def fake_batch_solver(cubes, **kwargs):
        assert kwargs["table_dir"] == table_dir
        return [
            SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cubes[0].to_facelets(),
                solution_moves=["F2", "U'", "R'"],
                solution_length=3,
                metric="HTM",
                runtime_seconds=0.01,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=963061264,
                status="exact",
                is_verified=True,
                notes=(
                    "external RubikOptimal batch backend; "
                    "selected_backend=rubikoptimal_external_batch; "
                    "backend_solver=rubikoptimal_external"
                ),
            )
        ]

    payload, output, table = run_rubikoptimal_oracle_corpus.run_corpus(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        cases=[
            run_rubikoptimal_oracle_corpus.RubikOptimalCase(
                "shallow_r_u_f2",
                CubeState.from_sequence("R U F2"),
                ["R", "U", "F2"],
                3,
                "known shallow three-move state",
            )
        ],
        timeout_seconds=9.0,
        executable=None,
        package_path=None,
        table_dir=table_dir,
        artifact_suffix="test",
        batch_solver_func=fake_batch_solver,
    )

    assert payload["passed"] is True
    assert payload["rubikoptimal_table_complete"] is True
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert payload["rows"][0]["source_sequence_provided_to_solver"] is False
    assert payload["rows"][0]["solution_length"] == 3
    assert output.exists()
    assert table.exists()


def test_rubikoptimal_oracle_stream_uses_public_cli_and_facelets(monkeypatch, tmp_path):
    table_dir = tmp_path / "rubikoptimal_tables"
    table_dir.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr(run_rubikoptimal_oracle_stream, "rubikoptimal_tables_ready", lambda _table_dir: True)
    monkeypatch.setattr(run_rubikoptimal_oracle_stream, "rubikoptimal_table_bytes", lambda _table_dir: 963061264)
    monkeypatch.setattr(run_rubikoptimal_oracle_stream, "rubikoptimal_table_inventory", lambda _table_dir: [])

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        rows = [
            {
                "index": 0,
                "input": CubeState.solved().to_facelets(),
                "input_kind": "facelets",
                "status": "exact",
                "distance": 0,
                "solution_moves": [],
                "solution_length": 0,
                "metric": "HTM",
                "verified": True,
                "runtime_seconds": 0.001,
                "expanded_nodes": None,
                "table_bytes": 963061264,
                "selected_backend": "rubikoptimal_resident",
                "backend_solver": "rubikoptimal_external",
                "notes": (
                    "resident RubikOptimal backend not invoked for solved state; "
                    "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external"
                ),
            },
            {
                "index": 1,
                "input": CubeState.from_sequence("R U").to_facelets(),
                "input_kind": "facelets",
                "status": "exact",
                "distance": 2,
                "solution_moves": ["U'", "R'"],
                "solution_length": 2,
                "metric": "HTM",
                "verified": True,
                "runtime_seconds": 0.01,
                "expanded_nodes": None,
                "table_bytes": 963061264,
                "selected_backend": "rubikoptimal_resident",
                "backend_solver": "rubikoptimal_external",
                "notes": (
                    "resident RubikOptimal backend; selected_backend=rubikoptimal_resident; "
                    "backend_solver=rubikoptimal_external; resident_process_reused=true"
                ),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(row) for row in rows) + "\n",
            stderr="",
        )

    monkeypatch.setattr(run_rubikoptimal_oracle_stream.subprocess, "run", fake_run)

    payload, output, table = run_rubikoptimal_oracle_stream.run_stream(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        cases=[
            run_rubikoptimal_oracle_stream.RubikOptimalStreamCase(
                "stream_facelets_solved",
                CubeState.solved(),
                0,
                "solved state supplied as facelets",
            ),
            run_rubikoptimal_oracle_stream.RubikOptimalStreamCase(
                "stream_facelets_depth_2",
                CubeState.from_sequence("R U"),
                2,
                "known two-move state supplied as facelets",
            ),
        ],
        timeout_seconds=9.0,
        executable=None,
        package_path=None,
        table_dir=table_dir,
        artifact_suffix="test",
    )

    command = captured["command"]
    assert command[:4] == [sys.executable, "-m", "rubik_optimal.cli", "oracle"]
    assert "--stream" in command
    assert "--rubikoptimal" in command
    assert "--rubikoptimal-table-dir" in command
    assert captured["kwargs"]["cwd"] == tmp_path
    assert "R U" not in captured["kwargs"]["input"]
    assert CubeState.from_sequence("R U").to_facelets() in captured["kwargs"]["input"]
    assert payload["passed"] is True
    assert payload["public_interface"] == "rubik-optimal oracle --stream --rubikoptimal"
    assert payload["all_state_input_only"] is True
    assert payload["all_rubikoptimal_resident"] is True
    assert payload["resident_reused_rows"] == 1
    assert payload["fast_runtime_proven_for_every_possible_state"] is False
    assert output.exists()
    assert table.exists()
