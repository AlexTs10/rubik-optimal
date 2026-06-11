import time
import threading
from dataclasses import replace

import rubik_optimal.oracle as oracle_module
from rubik_optimal.cube import CubeState
from rubik_optimal.moves import inverse_sequence, parse_sequence
from rubik_optimal.oracle import (
    FastOptimalOracle,
    FastOptimalOracleConfig,
    PortfolioOptimalOracle,
    PortfolioOptimalOracleConfig,
    RaceOptimalOracle,
    RaceOptimalOracleConfig,
    ResidentRaceOptimalOracle,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
    _RaceCandidate,
)
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.solvers.h48_native import H48LowerBoundResult, _h48_symmetry_rotations
from rubik_optimal.symmetry import CUBE_ROTATIONS


def _exact_result(
    cube: CubeState,
    *,
    solver_name: str,
    solution: list[str] | None = None,
    solution_moves: list[str] | None = None,
) -> SolverResult:
    moves = solution if solution is not None else solution_moves
    if moves is None:
        raise ValueError("test exact result needs solution moves")
    return SolverResult(
        solver_name=solver_name,
        input_state=cube.to_facelets(),
        solution_moves=moves,
        solution_length=len(moves),
        metric="HTM",
        runtime_seconds=0.125,
        expanded_nodes=10,
        generated_nodes=None,
        table_bytes=1234,
        status="exact",
        is_verified=True,
        notes="fake exact backend result",
    )


def _timeout_result(cube: CubeState, *, solver_name: str) -> SolverResult:
    return SolverResult(
        solver_name=solver_name,
        input_state=cube.to_facelets(),
        solution_moves=[],
        solution_length=None,
        metric="HTM",
        runtime_seconds=0.25,
        expanded_nodes=None,
        generated_nodes=None,
        table_bytes=1234,
        status="timeout",
        is_verified=False,
        notes="fake timeout backend result",
    )


class _FakeProcess:
    def __init__(self, return_code: int | None, stdout: str = "", stderr: str = "") -> None:
        self.return_code = return_code
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.return_code

    def communicate(self):
        return self.stdout_text, self.stderr_text

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = -15

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.return_code or 0


def test_race_oracle_returns_first_verified_exact_and_stops_loser(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    winner = _FakeProcess(0)
    loser = _FakeProcess(None)

    def parse_winner(stdout, stderr, return_code, runtime_seconds):
        return _exact_result(cube, solver_name="nissy_optimal_external", solution=["U'", "R'"])

    def parse_loser(stdout, stderr, return_code, runtime_seconds):
        raise AssertionError("loser parser should not run after a verified exact winner")

    def fake_build_candidates(self, cube_arg, *, source_sequence):
        return (
            [
                _RaceCandidate("nissy-optimal", winner, parse_winner, 0.0),
                _RaceCandidate("native-h48", loser, parse_loser, 0.0),
            ],
            ["test_setup=true"],
        )

    monkeypatch.setattr(RaceOptimalOracle, "_build_candidates", fake_build_candidates)

    config = RaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
    )
    result = RaceOptimalOracle(config).solve(cube, source_sequence="R U")

    assert result.solver_name == "race_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert loser.terminated
    assert "selected_backend=nissy-optimal" in result.notes
    assert "killed_backends=native-h48" in result.notes


def test_race_oracle_uses_nissy_core_direct_for_state_input_before_scramble_recovery(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    winner = _FakeProcess(0)

    def parse_winner(stdout, stderr, return_code, runtime_seconds):
        return _exact_result(
            cube,
            solver_name="nissy_core_direct_h48h7",
            solution_moves=["F2", "U'", "R'"],
        )

    def fake_start_direct(self, cube_arg, setup_notes):
        return _RaceCandidate("nissy-core-direct", winner, parse_winner, 0.0)

    def fail_h48(self, cube_arg, setup_notes):
        raise AssertionError("H48 candidate should not be started in this direct-core-only race test")

    monkeypatch.setattr(RaceOptimalOracle, "_start_nissy_core_direct_candidate", fake_start_direct)
    monkeypatch.setattr(RaceOptimalOracle, "_start_h48_candidate", fail_h48)

    config = RaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=False,
        include_nissy=True,
        include_nissy_core_direct=True,
    )
    oracle = RaceOptimalOracle(config)
    result = oracle.solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=nissy-core-direct" in result.notes
    assert "started_backends=nissy-core-direct" in result.notes
    assert "backend_solver=nissy_core_direct_h48h7" in result.notes


def test_resident_race_oracle_h48_winner_stops_nissy(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    loser = _FakeProcess(None)

    def fake_h48_solve(self, cube_arg):
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    def parse_loser(stdout, stderr, return_code, runtime_seconds):
        raise AssertionError("nissy loser parser should not run after resident H48 wins")

    def fake_start_nissy(self, cube_arg, source_sequence, setup_notes):
        return _RaceCandidate("nissy-optimal", loser, parse_loser, 0.0)

    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "_start_nissy_candidate", fake_start_nissy)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube, source_sequence="R U")
    finally:
        oracle.close()

    assert result.solver_name == "resident_race_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert loser.terminated
    assert "selected_backend=resident-h48" in result.notes
    assert "stopped_backends=nissy-optimal" in result.notes
    assert "resident_h48_process=shared_batch_session" in result.notes


def test_resident_race_oracle_nissy_winner_stops_resident_h48(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    winner = _FakeProcess(0)
    closed = {"value": False}

    def fake_h48_solve(self, cube_arg):
        while not closed["value"]:
            time.sleep(0.01)
        return _timeout_result(cube_arg, solver_name="fast_optimal_oracle_h48h7")

    def fake_h48_close(self):
        closed["value"] = True

    def parse_winner(stdout, stderr, return_code, runtime_seconds):
        return _exact_result(
            cube,
            solver_name="nissy_optimal_external",
            solution=inverse_sequence(parse_sequence("R U F2")),
        )

    def fake_start_nissy(self, cube_arg, source_sequence, setup_notes):
        return _RaceCandidate("nissy-optimal", winner, parse_winner, 0.0)

    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)
    monkeypatch.setattr(FastOptimalOracle, "close", fake_h48_close)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "_start_nissy_candidate", fake_start_nissy)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube, source_sequence="R U F2")
    finally:
        oracle.close()

    assert result.solver_name == "resident_race_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert closed["value"] is True
    assert "selected_backend=nissy-optimal" in result.notes
    assert "stopped_backends=resident-h48" in result.notes


def test_resident_race_delay_lets_nissy_win_without_starting_h48(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    winner = _FakeProcess(0)

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("delayed H48 should not start when Nissy wins first")

    def parse_winner(stdout, stderr, return_code, runtime_seconds):
        return _exact_result(
            cube,
            solver_name="nissy_optimal_external",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    def fake_start_nissy(self, cube_arg, source_sequence, setup_notes):
        return _RaceCandidate("nissy-optimal", winner, parse_winner, 0.0)

    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "_start_nissy_candidate", fake_start_nissy)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        h48_start_delay_seconds=0.5,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube, source_sequence="R U")
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.is_verified
    assert "selected_backend=nissy-optimal" in result.notes
    assert "started_backends=nissy-optimal" in result.notes
    assert "stopped_backends=resident-h48-deferred" in result.notes
    assert "h48_start_delay_seconds=0.500000" in result.notes


def test_resident_race_uses_nissy_core_direct_for_state_input_before_scramble_recovery(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    winner = _FakeProcess(0)

    def parse_winner(stdout, stderr, return_code, runtime_seconds):
        return _exact_result(
            cube,
            solver_name="nissy_core_direct_h48h7",
            solution_moves=["F2", "U'", "R'"],
        )

    def fake_start_direct(self, cube_arg, setup_notes):
        return _RaceCandidate("nissy-core-direct", winner, parse_winner, 0.0)

    def fail_legacy_nissy(self, cube_arg, source_sequence, setup_notes):
        raise AssertionError("representative-scramble Nissy candidate should not run before direct core")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("resident H48 should stay deferred when direct core wins immediately")

    monkeypatch.setattr(ResidentRaceOptimalOracle, "_start_nissy_core_direct_candidate", fake_start_direct)
    monkeypatch.setattr(RaceOptimalOracle, "_start_nissy_candidate", fail_legacy_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=True,
        include_nissy_core_direct=True,
        h48_start_delay_seconds=10.0,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=nissy-core-direct" in result.notes
    assert "started_backends=nissy-core-direct" in result.notes
    assert "stopped_backends=resident-h48-deferred" in result.notes
    assert "backend_solver=nissy_core_direct_h48h7" in result.notes


def test_resident_race_uses_resident_nissy_core_direct_session(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"fake resident direct table")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("delayed H48 should not start when resident direct Nissy wins")

    class FakeNissyCoreDirectSession:
        instances: list["FakeNissyCoreDirectSession"] = []

        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.solve_calls = 0
            self.closed = False
            FakeNissyCoreDirectSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            self.solve_calls += 1
            result = _exact_result(
                cube_arg,
                solver_name="nissy_core_python_resident_h48h7",
                solution_moves=["F2", "U'", "R'"],
            )
            return replace(
                result,
                notes=(
                    "nissy-core Python resident backend; input_mode=cube_state; "
                    "table_loaded_once=true; process_per_batch=true; "
                    "table_data_mode=mmap; solve_buffer_available=True; "
                    f"resident_request_index={self.solve_calls}; "
                    f"resident_process_reused={str(self.solve_calls > 1).lower()}; "
                    f"timeout_seconds={timeout_seconds}"
                ),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)
    monkeypatch.setattr(oracle_module, "_default_nissy_core_module_root", lambda root: tmp_path / "nissy-core")
    monkeypatch.setattr(oracle_module, "_nissy_core_python_module_available", lambda module_root: True)
    monkeypatch.setattr(oracle_module, "_nissy_core_python_enabled_for_table", lambda table_path, module_root: True)
    monkeypatch.setattr(oracle_module, "NissyCoreDirectPythonSession", FakeNissyCoreDirectSession)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=True,
        include_nissy_core_direct=True,
        h48_start_delay_seconds=10.0,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
        second_result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=nissy-core-direct-resident" in result.notes
    assert "started_backends=nissy-core-direct-resident" in result.notes
    assert "stopped_backends=resident-h48-deferred" in result.notes
    assert "backend_solver=nissy_core_python_resident_h48h7" in result.notes
    assert "table_data_mode=mmap" in result.notes
    assert "resident_process_reused=true" in second_result.notes
    assert len(FakeNissyCoreDirectSession.instances) == 1
    assert FakeNissyCoreDirectSession.instances[0].solve_calls == 2
    assert FakeNissyCoreDirectSession.instances[0].closed is True


def test_resident_race_h48_winner_stops_resident_nissy_core_direct(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"fake resident direct table")

    def fake_h48_solve(self, cube_arg):
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    class FakeNissyCoreDirectSession:
        instances: list["FakeNissyCoreDirectSession"] = []

        def __init__(self, **kwargs):
            self.closed = threading.Event()
            self.solve_calls = 0
            FakeNissyCoreDirectSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            self.solve_calls += 1
            self.closed.wait(timeout=5.0)
            return _timeout_result(cube_arg, solver_name="nissy_core_python_resident_h48h7")

        def close(self):
            self.closed.set()

    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)
    monkeypatch.setattr(oracle_module, "_default_nissy_core_module_root", lambda root: tmp_path / "nissy-core")
    monkeypatch.setattr(oracle_module, "_nissy_core_python_module_available", lambda module_root: True)
    monkeypatch.setattr(oracle_module, "_nissy_core_python_enabled_for_table", lambda table_path, module_root: True)
    monkeypatch.setattr(oracle_module, "NissyCoreDirectPythonSession", FakeNissyCoreDirectSession)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=True,
        include_nissy_core_direct=True,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert FakeNissyCoreDirectSession.instances[0].closed.is_set()
    assert "selected_backend=resident-h48" in result.notes
    assert "stopped_backends=nissy-core-direct-resident" in result.notes


def test_resident_race_oracle_rubikoptimal_winner_stops_deferred_h48(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("delayed H48 should not start when RubikOptimal wins first")

    class FakeRubikOptimalSession:
        instances: list["FakeRubikOptimalSession"] = []

        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.solve_calls = 0
            self.closed = False
            FakeRubikOptimalSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            self.solve_calls += 1
            result = _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution_moves=["F2", "U'", "R'"],
            )
            return replace(
                result,
                notes=(
                    "resident RubikOptimal backend; selected_backend=rubikoptimal_resident; "
                    "backend_solver=rubikoptimal_external; "
                    f"resident_request_index={self.solve_calls}; resident_start_count=1; "
                    f"resident_process_reused={str(self.solve_calls > 1).lower()}; "
                    f"timeout_seconds={timeout_seconds}"
                ),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=False,
        include_rubikoptimal=True,
        rubikoptimal_race_timeout_seconds=1.0,
        h48_start_delay_seconds=10.0,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
        second_result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=rubikoptimal-race" in result.notes
    assert "started_backends=rubikoptimal-race" in result.notes
    assert "stopped_backends=resident-h48-deferred" in result.notes
    assert "backend_solver=rubikoptimal_external" in result.notes
    assert "selected_backend=rubikoptimal_resident" in result.notes
    assert second_result.status == "exact"
    assert len(FakeRubikOptimalSession.instances) == 1
    assert FakeRubikOptimalSession.instances[0].solve_calls == 2
    assert "resident_process_reused=true" in second_result.notes


def test_resident_race_oracle_h48_winner_stops_rubikoptimal(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")

    def fake_h48_solve(self, cube_arg):
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    class FakeRubikOptimalSession:
        instances: list["FakeRubikOptimalSession"] = []

        def __init__(self, **kwargs):
            self.closed = threading.Event()
            self.solve_calls = 0
            FakeRubikOptimalSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            self.solve_calls += 1
            self.closed.wait(timeout=5.0)
            return _timeout_result(cube_arg, solver_name="rubikoptimal_external")

        def close(self):
            self.closed.set()

    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=False,
        include_rubikoptimal=True,
        rubikoptimal_race_timeout_seconds=1.0,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert FakeRubikOptimalSession.instances[0].closed.is_set()
    assert "selected_backend=resident-h48" in result.notes
    assert "stopped_backends=rubikoptimal-race" in result.notes


def test_resident_race_rubikoptimal_timeout_allows_h48_fallback(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")

    def fake_h48_solve(self, cube_arg):
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            self.closed = False

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            result = _timeout_result(cube_arg, solver_name="rubikoptimal_external")
            return replace(
                result,
                notes=(
                    "RubikOptimal resident query timed out and the resident process was stopped; "
                    "selected_backend=rubikoptimal_resident; backend_solver=rubikoptimal_external; "
                    f"timeout_seconds={timeout_seconds}"
                ),
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=False,
        include_rubikoptimal=True,
        rubikoptimal_race_timeout_seconds=0.01,
        h48_start_delay_seconds=0.02,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube)
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert "selected_backend=resident-h48" in result.notes
    assert "rubikoptimal-race_timeout_after_seconds=0.010000" in result.notes


def test_portfolio_uses_nissy_exact_result_without_starting_h48(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    captured: dict[str, object] = {}

    def fake_nissy(cube_arg, **kwargs):
        captured.update(kwargs)
        return _exact_result(
            cube_arg,
            solver_name="nissy_optimal_external",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when Nissy proves exact")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube, source_sequence="R U")

    assert result.solver_name == "portfolio_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert captured["source_sequence"] == "R U"
    assert captured["timeout_seconds"] == 0.5
    assert captured["threads"] == 1
    assert "selected_backend=nissy-optimal" in result.notes
    assert "resident_h48_invoked=false" in result.notes


def test_portfolio_falls_back_to_resident_h48_after_nissy_timeout(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_h48_solve(self, cube_arg):
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7",
            solution=inverse_sequence(parse_sequence("R U F2")),
        )

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fake_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube, source_sequence="R U F2")

    assert result.solver_name == "portfolio_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=resident-h48" in result.notes
    assert "nissy_status=timeout" in result.notes
    assert "resident_h48_invoked=true" in result.notes


def test_portfolio_rejects_invalid_cube_before_external_backends(tmp_path):
    invalid = CubeState(co=(1, 0, 0, 0, 0, 0, 0, 0))
    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
    )

    result = PortfolioOptimalOracle(config).solve(invalid)

    assert result.solver_name == "portfolio_optimal_oracle"
    assert result.status == "failed"
    assert not result.is_verified
    assert "invalid physical cube state rejected" in result.notes


def test_portfolio_uses_revalidated_exact_certificate_before_backends(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    artifact = tmp_path / "certificates.json"
    artifact.write_text(
        """{
          "rows": [{
            "case_id": "cached_ruf2",
            "state": "%s",
            "status": "exact",
            "verified": true,
            "solution": "F2 U' R'",
            "solution_length": 3,
            "runtime_seconds": 12.5,
            "solver": "fake_exact_solver"
          }]
        }"""
        % cube.to_facelets(),
        encoding="utf-8",
    )

    def fail_nissy(cube_arg, **kwargs):
        raise AssertionError("Nissy should not run when an exact certificate exists")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when an exact certificate exists")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fail_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        certificate_artifacts=(artifact,),
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=exact-certificate-cache" in result.notes
    assert "certificate_case_id=cached_ruf2" in result.notes


def test_portfolio_reuses_inverse_of_revalidated_exact_certificate(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    inverse_cube = CubeState.from_sequence("F2 U' R'")
    artifact = tmp_path / "certificates.json"
    artifact.write_text(
        """{
          "rows": [{
            "case_id": "cached_ruf2",
            "state": "%s",
            "status": "exact",
            "verified": true,
            "solution": "F2 U' R'",
            "solution_length": 3,
            "runtime_seconds": 12.5,
            "solver": "fake_exact_solver"
          }]
        }"""
        % cube.to_facelets(),
        encoding="utf-8",
    )

    def fail_nissy(cube_arg, **kwargs):
        raise AssertionError("Nissy should not run when an inverse exact certificate exists")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when an inverse exact certificate exists")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fail_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        certificate_artifacts=(artifact,),
    )
    result = PortfolioOptimalOracle(config).solve(inverse_cube)

    assert result.status == "exact"
    assert result.solution_moves == ["R", "U", "F2"]
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=exact-certificate-cache" in result.notes
    assert "certificate_case_id=cached_ruf2#inverse" in result.notes
    assert "certificate_derivation=inverse" in result.notes
    assert "inverse_certificate_closure" in result.notes


def test_portfolio_reuses_rotated_revalidated_exact_certificate(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    rotation = next(rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity)
    rotated_cube = rotation.transform_cube(cube)
    artifact = tmp_path / "certificates.json"
    artifact.write_text(
        """{
          "rows": [{
            "case_id": "cached_ruf2",
            "state": "%s",
            "status": "exact",
            "verified": true,
            "solution": "F2 U' R'",
            "solution_length": 3,
            "runtime_seconds": 12.5,
            "solver": "fake_exact_solver"
          }]
        }"""
        % cube.to_facelets(),
        encoding="utf-8",
    )

    def fail_nissy(cube_arg, **kwargs):
        raise AssertionError("Nissy should not run when a rotated exact certificate exists")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when a rotated exact certificate exists")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fail_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        certificate_artifacts=(artifact,),
    )
    result = PortfolioOptimalOracle(config).solve(rotated_cube)

    assert result.status == "exact"
    assert result.solution_moves == rotation.transform_sequence(["F2", "U'", "R'"])
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=exact-certificate-cache" in result.notes
    assert "certificate_case_id=cached_ruf2#rot" in result.notes
    assert "certificate_derivation=symmetry" in result.notes
    assert "symmetry_certificate_closure" in result.notes


def test_portfolio_certifies_upper_bound_when_h48_lower_bound_matches(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=["U'", "R'"],
            solution_length=2,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake verified upper bound",
        )

    def fake_lower(cube_arg, **kwargs):
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake admissible lower bound",
        )

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 search should not run when bounds certify exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fake_lower)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert "selected_backend=upper-lower-certificate" in result.notes
    assert "admissible_lower_bound_matches_verified_upper_solution=true" in result.notes


def test_portfolio_can_certify_upper_bound_with_rotational_h48_lower_bound(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    captured: dict[str, object] = {}

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=["U'", "R'"],
            solution_length=2,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake verified upper bound",
        )

    def fake_rotational_lower(cube_arg, **kwargs):
        captured.update(kwargs)
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_rotational_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake rotational admissible lower bound; best_rotation=rot02",
        )

    def fail_single_lower(cube_arg, **kwargs):
        raise AssertionError("single-orientation lower bound should not run when rotational bounds are enabled")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 search should not run when bounds certify exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fail_single_lower)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_rotational_lower_bound", fake_rotational_lower)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
        lower_bound_symmetry_variants=23,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert captured["variant_count"] == 23
    assert captured["include_identity"] is True
    assert "selected_backend=upper-lower-certificate" in result.notes
    assert "best_rotation=rot02" in result.notes


def test_portfolio_can_improve_upper_bound_with_kociemba_symmetry(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    solution = ["U'", "R'"]
    selected_rotation = next(rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity)
    rotated_cube = selected_rotation.transform_cube(cube)
    calls: list[str] = []

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        calls.append(cube_arg.to_facelets())
        if cube_arg.to_facelets() == rotated_cube.to_facelets():
            rotated_solution = selected_rotation.transform_sequence(solution)
            return SolverResult(
                solver_name="kociemba_two_phase_adapter",
                input_state=cube_arg.to_facelets(),
                solution_moves=rotated_solution,
                solution_length=len(rotated_solution),
                metric="HTM",
                runtime_seconds=0.02,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=None,
                status="non_exact",
                is_verified=True,
                notes="fake rotated verified upper bound",
            )
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=["F", "F'", *solution],
            solution_length=4,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake longer verified upper bound",
        )

    def fake_lower(cube_arg, **kwargs):
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake admissible lower bound",
        )

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 search should not run when symmetry upper bound certifies exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fake_lower)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
        kociemba_upper_bound_symmetry_variants=23,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_moves == solution
    assert result.solution_length == 2
    assert result.is_verified
    assert len(calls) >= 2
    assert "selected_backend=upper-lower-certificate" in result.notes
    assert "kociemba_symmetry_upper_bound_used=true" in result.notes
    assert "kociemba_symmetry_upper_bound=true" in result.notes
    assert f"selected_rotation={selected_rotation.name}" in result.notes


def test_portfolio_can_certify_upper_bound_with_bounded_h48_proof(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    solution = ["F2", "U'", "R'"]
    captured: dict[str, object] = {}

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=solution,
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake verified upper bound",
        )

    def fake_lower(cube_arg, **kwargs):
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake admissible lower bound",
        )

    def fake_bounded_proof(cube_arg, **kwargs):
        captured.update(kwargs)
        return SolverResult(
            solver_name="h48_native_h48h7",
            input_state=cube_arg.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=0.03,
            expanded_nodes=99,
            generated_nodes=None,
            table_bytes=1234,
            status="lower_bound",
            is_verified=False,
            notes="bounded H48 proof; proved_lower_bound=3",
        )

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 fallback should not run when bounded proof certifies exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fake_lower)
    monkeypatch.setattr("rubik_optimal.oracle.solve_h48_native_optimal", fake_bounded_proof)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
        h48_upper_bound_proof_timeout_seconds=5.0,
        h48_upper_bound_proof_max_gap=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_moves == solution
    assert result.solution_length == 3
    assert result.is_verified
    assert captured["max_depth"] == 2
    assert captured["timeout_seconds"] == 5.0
    assert "selected_backend=h48-upper-bound-proof" in result.notes
    assert "completed bounded H48 search proved no shorter solution" in result.notes
    assert "h48_proved_lower_bound=3" in result.notes


def test_portfolio_can_certify_upper_bound_with_native_korf_proof(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    solution = ["F2", "U'", "R'"]
    captured: dict[str, object] = {}

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=solution,
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake verified upper bound",
        )

    def fake_lower(cube_arg, **kwargs):
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake admissible lower bound",
        )

    def fake_native_korf_proof(cube_arg, **kwargs):
        captured.update(kwargs)
        return SolverResult(
            solver_name="korf_native_optimal",
            input_state=cube_arg.to_facelets(),
            solution_moves=solution,
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.04,
            expanded_nodes=55,
            generated_nodes=144,
            table_bytes=4321,
            status="exact",
            is_verified=True,
            notes=(
                "native C++ IDA* with corner+edge PDB heuristic; "
                "upper_bound_proof_strategy=single-bound; "
                "upper_bound_proof_search_bound=2; "
                "upper_bound_proof_exhaustive=True; "
                "exact_certified_by_upper_bound=True"
            ),
        )

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 fallback should not run when native Korf proof certifies exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fake_lower)
    monkeypatch.setattr("rubik_optimal.oracle.solve_korf_native_optimal", fake_native_korf_proof)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin", threads=2),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
        native_korf_upper_bound_proof_timeout_seconds=5.0,
        native_korf_upper_bound_proof_max_gap=1,
        # Explicit opt-in: exercises the nissy-heuristic flag-propagation plumbing.
        native_korf_upper_bound_proof_nissy_heuristic=True,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_moves == solution
    assert result.solution_length == 3
    assert result.is_verified
    assert captured["max_depth"] == 2
    assert captured["timeout_seconds"] == 5.0
    assert captured["threads"] == 2
    assert captured["upper_solution"] == solution
    assert captured["upper_bound_proof_strategy"] == "single-bound"
    assert captured["nissy_heuristic"] is True
    assert "selected_backend=native-korf-upper-bound-proof" in result.notes
    assert "completed native Korf/IDA* single-bound proof below verified upper bound" in result.notes
    assert "native_korf_proof_max_depth=2" in result.notes


def test_native_korf_proof_nissy_heuristic_defaults_to_false():
    # Licensing stance: the optional GPL-3.0 nissy heuristic must remain strictly
    # opt-in so the requirement-#3 optimal engine stays the student's own work.
    assert PortfolioOptimalOracleConfig().native_korf_upper_bound_proof_nissy_heuristic is False
    assert UniversalOptimalOracleConfig().native_korf_upper_bound_proof_nissy_heuristic is False


def test_portfolio_lower_bound_uses_resolved_auto_h48_solver(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    captured: dict[str, object] = {}

    def fake_nissy(cube_arg, **kwargs):
        return _timeout_result(cube_arg, solver_name="nissy_optimal_external")

    def fake_kociemba(cube_arg):
        return SolverResult(
            solver_name="kociemba_two_phase_adapter",
            input_state=cube_arg.to_facelets(),
            solution_moves=["U'", "R'"],
            solution_length=2,
            metric="HTM",
            runtime_seconds=0.01,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=None,
            status="non_exact",
            is_verified=True,
            notes="fake verified upper bound",
        )

    def fake_lower(cube_arg, **kwargs):
        captured.update(kwargs)
        return H48LowerBoundResult(
            solver_name="h48_native_h48h7_lower_bound",
            input_state=cube_arg.to_facelets(),
            lower_bound=2,
            runtime_seconds=0.02,
            table_bytes=1234,
            status="lower_bound",
            notes="fake admissible lower bound",
        )

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fake_nissy)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fake_lower)
    monkeypatch.setattr("rubik_optimal.tables.h48.h48_table_inventory", lambda **kwargs: [])

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin", solver="auto"),
        try_certificate_cache=False,
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert captured["solver"] == "h48h7"


def test_portfolio_uses_nissy_core_direct_for_state_input_before_scramble_recovery(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_direct(cube_arg, **kwargs):
        captured.update(kwargs)
        return _exact_result(
            cube_arg,
            solver_name="nissy_core_direct_h48h7",
            solution=["F2", "U'", "R'"],
        )

    def fail_nissy(cube_arg, **kwargs):
        raise AssertionError("representative-scramble Nissy wrapper should not run before direct core")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when direct core proves exact")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_core_direct_optimal", fake_direct)
    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal", fail_nissy)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin", solver="h48h7"),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_timeout_seconds=1.0,
        nissy_threads=1,
    )
    result = PortfolioOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 3
    assert captured["solver"] == "h48h7"
    assert captured["table_path"] == tmp_path / "missing.bin"
    assert captured["threads"] == 1
    assert "selected_backend=nissy-core-direct" in result.notes
    assert "nissy_core_direct_invoked=true" in result.notes
    assert "nissy_optimal_invoked=false" in result.notes
    assert "resident_h48_invoked=false" in result.notes


def test_portfolio_solve_many_uses_nissy_core_direct_for_state_input_rows(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    batch_calls: list[list[str]] = []

    def fake_direct_batch(cubes_arg, **kwargs):
        batch_calls.append([cube_arg.to_facelets() for cube_arg in cubes_arg])
        return [
            _exact_result(cubes_arg[0], solver_name="nissy_core_direct_h48h7", solution=["F2", "U'", "R'"]),
            _exact_result(cubes_arg[1], solver_name="nissy_core_direct_h48h7", solution=["U'", "R'"]),
        ]

    def fail_direct(cube_arg, **kwargs):
        raise AssertionError("per-row direct core should not run for solve_many state-input rows")

    def fail_nissy_batch(cubes_arg, **kwargs):
        raise AssertionError("Nissy batch wrapper should not run when direct core proves exact")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when direct core proves exact")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_core_direct_optimal", fail_direct)
    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_core_direct_optimal_batch", fake_direct_batch)
    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal_batch", fail_nissy_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin", solver="h48h7"),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_timeout_seconds=1.0,
        nissy_threads=1,
    )
    results = PortfolioOptimalOracle(config).solve_many(cubes, source_sequences=[None, None])

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert batch_calls == [[cube.to_facelets() for cube in cubes]]
    assert all("selected_backend=nissy-core-direct" in result.notes for result in results)
    assert all("nissy_core_direct_batch_invoked=true" in result.notes for result in results)
    assert all("nissy_core_direct_invoked=true" in result.notes for result in results)
    assert all("nissy_optimal_batch_invoked=false" in result.notes for result in results)


def test_portfolio_solve_many_uses_nissy_batch_before_h48(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_nissy_batch(cubes_arg, **kwargs):
        captured["cube_count"] = len(cubes_arg)
        captured.update(kwargs)
        return [
            _exact_result(cubes_arg[0], solver_name="nissy_optimal_external", solution=["F2", "U'", "R'"]),
            _exact_result(cubes_arg[1], solver_name="nissy_optimal_external", solution=["U'", "R'"]),
        ]

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("H48 fallback should not run when Nissy batch proves exact")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal_batch", fake_nissy_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        nissy_timeout_seconds=1.5,
        nissy_threads=1,
    )
    results = PortfolioOptimalOracle(config).solve_many(cubes, source_sequences=["R U F2", "R U"])

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["cube_count"] == 2
    assert captured["source_sequences"] == ["R U F2", "R U"]
    assert captured["timeout_seconds"] == 1.5
    assert all("selected_backend=nissy-optimal-batch" in result.notes for result in results)


def test_portfolio_solve_many_uses_batch_upper_lower_certificates(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_nissy_batch(cubes_arg, **kwargs):
        return [_timeout_result(cube, solver_name="nissy_optimal_external") for cube in cubes_arg]

    def fake_kociemba(cube_arg):
        return _timeout_result(cube_arg, solver_name="kociemba_two_phase_adapter")

    def fake_lower_batch(cubes_arg, **kwargs):
        captured["cube_count"] = len(cubes_arg)
        captured.update(kwargs)
        return [
            H48LowerBoundResult(
                solver_name="h48_native_h48h7_lower_bound_batch",
                input_state=cubes_arg[0].to_facelets(),
                lower_bound=3,
                runtime_seconds=0.02,
                table_bytes=1234,
                status="lower_bound",
                notes="fake multi-cube lower-bound batch; table_loaded_once=true; batch_input_count=2; batch_row=0",
            ),
            H48LowerBoundResult(
                solver_name="h48_native_h48h7_lower_bound_batch",
                input_state=cubes_arg[1].to_facelets(),
                lower_bound=2,
                runtime_seconds=0.02,
                table_bytes=1234,
                status="lower_bound",
                notes="fake multi-cube lower-bound batch; table_loaded_once=true; batch_input_count=2; batch_row=1",
            ),
        ]

    def fail_single_lower(cube_arg, **kwargs):
        raise AssertionError("single lower-bound subprocess should not run for solve_many fallback")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 fallback should not run when batch bounds certify exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal_batch", fake_nissy_batch)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fail_single_lower)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound_batch", fake_lower_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin", solver="h48h7", threads=1),
        try_certificate_cache=False,
        try_nissy_core_direct_first=False,
        nissy_timeout_seconds=1.5,
        nissy_threads=1,
    )
    results = PortfolioOptimalOracle(config).solve_many(cubes, source_sequences=["R U F2", "R U"])

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["cube_count"] == 2
    assert captured["solver"] == "h48h7"
    assert captured["threads"] == 1
    assert all("selected_backend=upper-lower-certificate" in result.notes for result in results)
    assert all("h48_lower_bound_batch_invoked=true" in result.notes for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)


def test_portfolio_solve_many_batches_bounded_h48_upper_bound_proofs(monkeypatch, tmp_path):
    source_sequences = ["R U F2", "F R U"]
    cubes = [CubeState.from_sequence(sequence) for sequence in source_sequences]
    captured: dict[str, object] = {}

    def fake_nissy_batch(cubes_arg, **kwargs):
        return [_timeout_result(cube, solver_name="nissy_optimal_external") for cube in cubes_arg]

    def fake_kociemba(cube_arg):
        return _timeout_result(cube_arg, solver_name="kociemba_two_phase_adapter")

    def fake_lower_batch(cubes_arg, **kwargs):
        return [
            H48LowerBoundResult(
                solver_name="h48_native_h48h7_lower_bound_batch",
                input_state=cube_arg.to_facelets(),
                lower_bound=2,
                runtime_seconds=0.02,
                table_bytes=1234,
                status="lower_bound",
                notes=f"fake multi-cube lower-bound batch; batch_row={row}",
            )
            for row, cube_arg in enumerate(cubes_arg)
        ]

    def fake_resident_bounded_batch(cubes_arg, **kwargs):
        captured["cube_count"] = len(cubes_arg)
        captured.update(kwargs)
        return [
            SolverResult(
                solver_name="h48_native_h48h7",
                input_state=cube_arg.to_facelets(),
                solution_moves=[],
                solution_length=None,
                metric="HTM",
                runtime_seconds=0.03,
                expanded_nodes=100 + row,
                generated_nodes=None,
                table_bytes=1234,
                status="lower_bound",
                is_verified=False,
                notes=f"bounded H48 batch proof; proved_lower_bound=3; batch_row={row}",
            )
            for row, cube_arg in enumerate(cubes_arg)
        ]

    def fail_single_lower(cube_arg, **kwargs):
        raise AssertionError("single lower-bound subprocess should not run for solve_many fallback")

    def fail_single_proof(cube_arg, **kwargs):
        raise AssertionError("single bounded proof subprocess should not run for solve_many fallback")

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("Full H48 fallback should not run when batch bounded proof certifies exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal_batch", fake_nissy_batch)
    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fail_single_lower)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound_batch", fake_lower_batch)
    monkeypatch.setattr("rubik_optimal.oracle.solve_h48_native_optimal", fail_single_proof)
    monkeypatch.setattr(
        "rubik_optimal.oracle.solve_h48_native_resident_batch",
        fake_resident_bounded_batch,
    )
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(
            root=tmp_path,
            table_path=tmp_path / "missing.bin",
            solver="h48h7",
            threads=1,
        ),
        try_certificate_cache=False,
        try_nissy_core_direct_first=False,
        nissy_timeout_seconds=1.5,
        nissy_threads=1,
        h48_upper_bound_proof_timeout_seconds=5.0,
        h48_upper_bound_proof_max_gap=1,
    )
    results = PortfolioOptimalOracle(config).solve_many(
        cubes,
        source_sequences=source_sequences,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 3]
    assert captured["cube_count"] == 2
    assert captured["solver"] == "h48h7"
    assert captured["threads"] == 1
    assert captured["max_depth"] == 2
    assert captured["timeout_seconds"] == 5.0
    assert all("selected_backend=h48-upper-bound-proof" in result.notes for result in results)
    assert all("h48_upper_bound_proof_batch_invoked=true" in result.notes for result in results)
    assert all("h48_proof_group_size=2" in result.notes for result in results)
    assert all("h48_proved_lower_bound=3" in result.notes for result in results)


def test_universal_uses_revalidated_certificate_before_live_backends(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    artifact = tmp_path / "certificates.json"
    artifact.write_text(
        """{
          "rows": [{
            "case_id": "cached_ruf2",
            "state": "%s",
            "status": "exact",
            "verified": true,
            "solution": "F2 U' R'",
            "solution_length": 3,
            "runtime_seconds": 12.5,
            "solver": "fake_exact_solver"
          }]
        }"""
        % cube.to_facelets(),
        encoding="utf-8",
    )

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run when an exact certificate exists")

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
        ),
        certificate_artifacts=(artifact,),
        try_upper_lower_certificate=False,
    )
    result = UniversalOptimalOracle(config).solve(cube)

    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=exact-certificate-cache" in result.notes
    assert "certificate_case_id=cached_ruf2" in result.notes


def test_universal_solve_many_batches_upper_lower_certificates_before_live_backends(
    monkeypatch,
    tmp_path,
):
    source_sequences = ["R U F2", "R U"]
    cubes = [CubeState.from_sequence(sequence) for sequence in source_sequences]
    captured: dict[str, object] = {}

    def fake_kociemba(cube_arg):
        return _timeout_result(cube_arg, solver_name="kociemba_two_phase_adapter")

    def fake_lower_batch(cubes_arg, **kwargs):
        captured["cube_count"] = len(cubes_arg)
        captured.update(kwargs)
        return [
            H48LowerBoundResult(
                solver_name="h48_native_h48h7_lower_bound_batch",
                input_state=cube_arg.to_facelets(),
                lower_bound=length,
                runtime_seconds=0.02,
                table_bytes=1234,
                status="lower_bound",
                notes=(
                    "fake universal multi-cube lower-bound batch; "
                    "table_loaded_once=true; "
                    f"batch_input_count={len(cubes_arg)}; batch_row={row}"
                ),
            )
            for row, (cube_arg, length) in enumerate(zip(cubes_arg, [3, 2], strict=True))
        ]

    def fail_single_lower(cube_arg, **kwargs):
        raise AssertionError("universal solve_many should batch lower-bound probes")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run when batched bounds certify exactness")

    def fail_h48_solve_many(self, cubes_arg):
        raise AssertionError("resident H48 batch should not run when batched bounds certify exactness")

    monkeypatch.setattr("rubik_optimal.oracle.solve_kociemba_adapter", fake_kociemba)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound", fail_single_lower)
    monkeypatch.setattr("rubik_optimal.oracle.compute_h48_native_lower_bound_batch", fake_lower_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fail_h48_solve_many)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(
                root=tmp_path,
                table_path=tmp_path / "missing.bin",
                solver="h48h7",
                threads=1,
            ),
            timeout_seconds=3.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        lower_bound_symmetry_variants=0,
        prefer_resident_h48_batch_for_state_input=True,
        resident_h48_batch_timeout_seconds=3.0,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=source_sequences)
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["cube_count"] == 2
    assert captured["solver"] == "h48h7"
    assert captured["threads"] == 1
    assert all("selected_backend=upper-lower-certificate" in result.notes for result in results)
    assert all("universal_solve_many_upper_lower_batch=true" in result.notes for result in results)
    assert all("h48_lower_bound_batch_invoked=true" in result.notes for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)


def test_universal_falls_back_to_resident_race(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")

    def fake_resident_race(self, cube_arg, *, source_sequence=None):
        return _exact_result(
            cube_arg,
            solver_name="resident_race_optimal_oracle",
            solution=inverse_sequence(parse_sequence("R U")),
        )

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
    )
    result = UniversalOptimalOracle(config).solve(cube, source_sequence="R U")

    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 2
    assert result.is_verified
    assert "selected_backend=resident-race" in result.notes
    assert "backend_solver=resident_race_optimal_oracle" in result.notes
    assert "fast_runtime_proven_for_every_possible_state=false" in result.notes


def test_universal_marks_rubikoptimal_resident_race_winner(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs

        def solve(self, cube_arg, *, timeout_seconds=300.0):
            result = _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution_moves=["F2", "U'", "R'"],
            )
            return replace(
                result,
                notes=(
                    "resident RubikOptimal backend; selected_backend=rubikoptimal_resident; "
                    "backend_solver=rubikoptimal_external"
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_race_timeout_seconds=1.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    result = UniversalOptimalOracle(config).solve(cube)

    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=rubikoptimal-race" in result.notes
    assert "backend_solver=resident_race_optimal_oracle" in result.notes
    assert "rubikoptimal_race" in result.notes


def test_universal_solve_many_can_use_resident_race_prepass_before_sequential_hardtail(
    monkeypatch,
    tmp_path,
):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_resident_race(self, cube_arg, *, source_sequence=None):
        captured["timeout_seconds"] = self.config.timeout_seconds
        captured["nissy_symmetry_variants"] = self.config.nissy_symmetry_variants
        captured["source_sequence"] = source_sequence
        return _exact_result(
            cube_arg,
            solver_name="resident_race_optimal_oracle",
            solution=["F2", "U'", "R'"],
        )

    def forbidden_later_phase(*args, **kwargs):
        raise AssertionError("resident-race prepass should solve before later hard-tail phases")

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_resident_race)
    monkeypatch.setattr(
        UniversalOptimalOracle,
        "_try_nissy_core_direct_rotational_race",
        forbidden_later_phase,
    )
    monkeypatch.setattr(UniversalOptimalOracle, "_try_nissy_symmetry_batch", forbidden_later_phase)
    monkeypatch.setattr(UniversalOptimalOracle, "_run_resident_h48_symmetry_batch", forbidden_later_phase)
    monkeypatch.setattr(UniversalOptimalOracle, "_run_parallel_h48_symmetry_race", forbidden_later_phase)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_race_prepass_timeout_seconds=1.25,
        nissy_symmetry_variants=2,
    )

    result = UniversalOptimalOracle(config).solve_many([cube], source_sequences=[None])[0]

    assert captured["timeout_seconds"] == 1.25
    assert captured["nissy_symmetry_variants"] == 2
    assert captured["source_sequence"] is None
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_length == 3
    assert "selected_backend=resident-race-prepass" in result.notes
    assert "universal_resident_race_prepass=true" in result.notes


def test_universal_solve_many_records_resident_race_prepass_timeout_before_h48_batch(
    monkeypatch,
    tmp_path,
):
    cube = CubeState.from_sequence("R U F2")

    def fake_resident_race(self, cube_arg, *, source_sequence=None):
        return _timeout_result(cube_arg, solver_name="resident_race_optimal_oracle")

    def fake_h48_solve_many(self, cubes):
        return [
            _exact_result(
                cube_arg,
                solver_name="fast_optimal_oracle_h48h7",
                solution=["F2", "U'", "R'"],
            )
            for cube_arg in cubes
        ]

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_resident_race)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_solve_many)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=3.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        resident_h48_batch_timeout_seconds=3.0,
        resident_race_prepass_timeout_seconds=0.5,
    )

    result = UniversalOptimalOracle(config).solve_many([cube], source_sequences=[None])[0]

    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_length == 3
    assert "selected_backend=resident-h48-batch" in result.notes
    assert "resident_race_prepass_initial_status=timeout" in result.notes
    assert "universal_resident_race_prepass=true" in result.notes


def test_universal_uses_rubikoptimal_after_resident_race_timeout(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_resident_race(self, cube_arg, *, source_sequence=None):
        return _timeout_result(cube_arg, solver_name="resident_race_optimal_oracle")

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def solve(self, cube_arg, *, timeout_seconds):
            captured["cube"] = cube_arg
            captured["timeout_seconds"] = timeout_seconds
            return _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution=["F2", "U'", "R'"],
            )

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_resident_race)
    monkeypatch.setattr("rubik_optimal.oracle.RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_fallback_timeout_seconds=7.5,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    result = UniversalOptimalOracle(config).solve(cube, source_sequence="R U F2")

    assert captured["cube"] == cube
    assert captured["timeout_seconds"] == 7.5
    assert captured["init_kwargs"]["table_dir"] == tmp_path / "rubikoptimal_tables"
    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=rubikoptimal-after-resident-race" in result.notes
    assert "backend_solver=rubikoptimal_external" in result.notes
    assert "universal_rubikoptimal_fallback=true" in result.notes
    assert "prior_universal_status=timeout" in result.notes


def test_universal_uses_rubikoptimal_prepass_before_resident_race(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def solve(self, cube_arg, *, timeout_seconds):
            captured["cube"] = cube_arg
            captured["timeout_seconds"] = timeout_seconds
            return _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution=["F2", "U'", "R'"],
            )

        def close(self):
            captured["closed"] = True

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run when RubikOptimal prepass proves exact")

    def fail_earlier_expensive_prepass(self, *args, **kwargs):
        raise AssertionError("expensive symmetry prepasses should not run before RubikOptimal prepass")

    monkeypatch.setattr("rubik_optimal.oracle.RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)
    monkeypatch.setattr(
        UniversalOptimalOracle,
        "_try_nissy_core_direct_rotational_race",
        fail_earlier_expensive_prepass,
    )
    monkeypatch.setattr(UniversalOptimalOracle, "_try_nissy_symmetry_batch", fail_earlier_expensive_prepass)
    monkeypatch.setattr(UniversalOptimalOracle, "_run_resident_h48_symmetry_batch", fail_earlier_expensive_prepass)
    monkeypatch.setattr(UniversalOptimalOracle, "_run_parallel_h48_symmetry_race", fail_earlier_expensive_prepass)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_core_direct_symmetry_variants=23,
        nissy_symmetry_variants=23,
        resident_h48_symmetry_variants=23,
        parallel_h48_symmetry_variants=23,
        rubikoptimal_prepass_timeout_seconds=7.5,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    result = UniversalOptimalOracle(config).solve(cube, source_sequence="R U F2")

    assert captured["cube"] == cube
    assert captured["timeout_seconds"] == 7.5
    assert captured["init_kwargs"]["table_dir"] == tmp_path / "rubikoptimal_tables"
    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=rubikoptimal-prepass" in result.notes
    assert "backend_solver=rubikoptimal_external" in result.notes


def test_universal_state_input_can_reach_direct_nissy_core_resident_race(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_resident_race(self, cube_arg, *, source_sequence=None):
        captured["source_sequence"] = source_sequence
        return SolverResult(
            solver_name="resident_race_optimal_oracle",
            input_state=cube_arg.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.125,
            expanded_nodes=10,
            generated_nodes=None,
            table_bytes=1234,
            status="exact",
            is_verified=True,
            notes=(
                "resident race exact oracle; selected_backend=nissy-core-direct; "
                "started_backends=nissy-core-direct; stopped_backends=resident-h48-deferred; "
                "backend_solver=nissy_core_direct_h48h7; input_mode=cube_state; table_symlink=true"
            ),
        )

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
            h48_start_delay_seconds=10.0,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
    )
    result = UniversalOptimalOracle(config).solve(cube)

    assert captured["source_sequence"] is None
    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert "selected_backend=resident-race" in result.notes
    assert "selected_backend=nissy-core-direct" in result.notes
    assert "backend_solver=nissy_core_direct_h48h7" in result.notes
    assert "input_mode=cube_state" in result.notes
    assert "table_symlink=true" in result.notes


def test_universal_races_nissy_symmetry_batch_inside_resident_race(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    source = parse_sequence("R U F2")
    captured: dict[str, object] = {}
    winner = _FakeProcess(0)

    def fake_start_symmetry(self, cube_arg, source_sequence, setup_notes):
        captured["variants"] = self.config.nissy_symmetry_variants
        captured["source_sequence"] = list(source_sequence)

        def parse_winner(stdout, stderr, return_code, runtime_seconds):
            return _exact_result(
                cube_arg,
                solver_name="nissy_symmetry_batch_oracle",
                solution=inverse_sequence(source_sequence),
            )

        return _RaceCandidate("nissy-symmetry-batch", winner, parse_winner, 0.0)

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("delayed H48 should not start when symmetry-batched Nissy wins first")

    monkeypatch.setattr(ResidentRaceOptimalOracle, "_start_nissy_symmetry_candidate", fake_start_symmetry)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
            h48_start_delay_seconds=0.5,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_symmetry_variants=1,
    )
    result = UniversalOptimalOracle(config).solve(cube, source_sequence=source)

    assert result.solver_name == "universal_optimal_oracle"
    assert result.status == "exact"
    assert result.solution_moves == inverse_sequence(source)
    assert result.solution_length == 3
    assert result.is_verified
    assert captured["variants"] == 1
    assert captured["source_sequence"] == source
    assert "selected_backend=nissy-symmetry-batch" in result.notes
    assert "backend_solver=nissy_symmetry_batch_oracle" in result.notes
    assert "stopped_backends=resident-h48-deferred" in result.notes
    assert "h48_start_delay_seconds=0.500000" in result.notes
    assert "fast_runtime_proven_for_every_possible_state=false" in result.notes


def test_resident_race_can_start_direct_and_symmetry_nissy_competitors(
    monkeypatch, tmp_path
):
    cube = CubeState.from_sequence("R U F2")
    direct_loser = _FakeProcess(None)
    symmetry_winner = _FakeProcess(0)
    started: list[str] = []

    def fake_start_direct(self, cube_arg, setup_notes):
        started.append("direct")

        def parse_direct(stdout, stderr, return_code, runtime_seconds):
            raise AssertionError("direct loser parser should not run after symmetry wins")

        return _RaceCandidate("nissy-core-direct", direct_loser, parse_direct, 0.0)

    def fake_start_symmetry(self, cube_arg, source_sequence, setup_notes):
        started.append("symmetry")

        def parse_symmetry(stdout, stderr, return_code, runtime_seconds):
            return _exact_result(
                cube_arg,
                solver_name="nissy_symmetry_batch_oracle",
                solution=["F2", "U'", "R'"],
            )

        return _RaceCandidate("nissy-symmetry-batch", symmetry_winner, parse_symmetry, 0.0)

    def fail_h48_solve(self, cube_arg):
        raise AssertionError("delayed H48 should not start when Nissy symmetry wins first")

    monkeypatch.setattr(
        ResidentRaceOptimalOracle,
        "_start_nissy_core_direct_candidate",
        fake_start_direct,
    )
    monkeypatch.setattr(
        ResidentRaceOptimalOracle,
        "_start_nissy_symmetry_candidate",
        fake_start_symmetry,
    )
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48_solve)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=True,
        include_nissy=True,
        include_nissy_core_direct=True,
        h48_start_delay_seconds=0.5,
        nissy_symmetry_variants=1,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        result = oracle.solve(cube, source_sequence=None)
    finally:
        oracle.close()

    assert started == ["direct", "symmetry"]
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert direct_loser.terminated
    assert "selected_backend=nissy-symmetry-batch" in result.notes
    assert "started_backends=nissy-core-direct,nissy-symmetry-batch" in result.notes
    assert "stopped_backends=resident-h48-deferred,nissy-core-direct" in result.notes


def test_resident_race_nissy_symmetry_can_use_h48_lower_bound_ordering(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    identity = next(rotation for rotation in CUBE_ROTATIONS if rotation.is_identity)
    rotations = [identity] + [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity][:2]
    captured: dict[str, object] = {}

    def fake_order(cube_arg, rotations_arg, **kwargs):
        captured["cube"] = cube_arg.to_facelets()
        captured["rotation_names"] = [rotation.name for rotation in rotations_arg]
        captured["kwargs"] = kwargs
        return list(reversed(rotations_arg)), "h48_lower_bound_rotation_order=true; order_status=applied"

    monkeypatch.setattr(oracle_module, "order_h48_rotations_by_lower_bound", fake_order)

    config = ResidentRaceOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
        timeout_seconds=1.0,
        nissy_threads=1,
        include_h48=False,
        include_nissy=True,
        include_nissy_core_direct=False,
        nissy_symmetry_variants=2,
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=0.25,
    )
    oracle = ResidentRaceOptimalOracle(config)
    try:
        ordered, note = oracle._order_nissy_symmetry_rotations_by_h48_lower_bound(cube, rotations)
    finally:
        oracle.close()

    assert [rotation.name for rotation in ordered] == [rotation.name for rotation in reversed(rotations)]
    assert captured["cube"] == cube.to_facelets()
    assert captured["rotation_names"] == [rotation.name for rotation in rotations]
    assert captured["kwargs"]["solver"] == "h48h7"
    assert captured["kwargs"]["table_path"] == table
    assert captured["kwargs"]["timeout_seconds"] == 0.25
    assert note == (
        "resident_race_nissy_symmetry_h48_lower_bound_rotation_order=true; order_status=applied"
    )


def test_universal_resident_race_prepass_forwards_symmetry_ordering(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    source = parse_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_solve(self, cube_arg, *, source_sequence=None):
        captured["symmetry_order_by_h48_lower_bound"] = self.config.symmetry_order_by_h48_lower_bound
        captured["symmetry_lower_bound_order_timeout_seconds"] = (
            self.config.symmetry_lower_bound_order_timeout_seconds
        )
        captured["nissy_symmetry_variants"] = self.config.nissy_symmetry_variants
        captured["source_sequence"] = list(source_sequence)
        return _exact_result(
            cube_arg,
            solver_name="resident_race_optimal_oracle",
            solution=inverse_sequence(source_sequence),
        )

    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fake_solve)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
            h48_start_delay_seconds=0.5,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_race_prepass_timeout_seconds=0.75,
        nissy_symmetry_variants=3,
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=0.2,
    )
    result = UniversalOptimalOracle(config).solve(cube, source_sequence=source)

    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == inverse_sequence(source)
    assert captured == {
        "symmetry_order_by_h48_lower_bound": True,
        "symmetry_lower_bound_order_timeout_seconds": 0.2,
        "nissy_symmetry_variants": 3,
        "source_sequence": source,
    }
    assert "selected_backend=resident-race-prepass" in result.notes


def test_universal_solve_many_uses_nissy_symmetry_batch_before_resident_h48(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_nissy_symmetry(self, cube_arg, *, source_sequence=None):
        captured["cube"] = cube_arg
        captured["source_sequence"] = source_sequence
        captured["variants"] = self.config.nissy_symmetry_variants
        captured["timeout"] = self.config.nissy_symmetry_timeout_seconds
        return _exact_result(
            cube_arg,
            solver_name="nissy_symmetry_batch_oracle",
            solution=["F2", "U'", "R'"],
        )

    def fail_h48_solve_many(self, cubes):
        raise AssertionError("resident H48 batch should not run when Nissy symmetry proves exact first")

    monkeypatch.setattr(UniversalOptimalOracle, "_try_nissy_symmetry_batch", fake_nissy_symmetry)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fail_h48_solve_many)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_symmetry_variants=3,
        nissy_symmetry_timeout_seconds=1.25,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=False,
    )

    result = UniversalOptimalOracle(config).solve_many([cube])[0]

    assert captured["cube"] == cube
    assert captured["source_sequence"] is None
    assert captured["variants"] == 3
    assert captured["timeout"] == 1.25
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_length == 3
    assert "selected_backend=nissy-symmetry-batch" in result.notes
    assert "backend_solver=nissy_symmetry_batch_oracle" in result.notes


def test_universal_can_use_resident_h48_rotational_symmetry_prepass(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_h48_symmetry(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        rotations=None,
        rotation_order_note="h48_symmetry_h48_lower_bound_rotation_order=false",
    ):
        captured["variant_count"] = variant_count
        captured["include_identity"] = include_identity
        captured["timeout_seconds"] = timeout_seconds
        captured["rotations"] = rotations
        captured["rotation_order_note"] = rotation_order_note
        return SolverResult(
            solver_name="fast_optimal_oracle_h48h7_symmetry_batch",
            input_state=cube_arg.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.125,
            expanded_nodes=10,
            generated_nodes=None,
            table_bytes=1234,
            status="exact",
            is_verified=True,
            notes=(
                "resident H48 rotational symmetry batch; "
                "exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                "identity_rotation_included=False; selected_rotation=rot01"
            ),
        )

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after H48 symmetry prepass succeeds")

    monkeypatch.setattr(FastOptimalOracle, "solve_rotated_variants", fake_h48_symmetry)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_h48_symmetry_variants=2,
        resident_h48_symmetry_timeout_seconds=0.75,
    )
    result = UniversalOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert captured == {
        "variant_count": 2,
        "include_identity": False,
        "timeout_seconds": 0.75,
        "rotations": captured["rotations"],
        "rotation_order_note": "resident_h48_symmetry_h48_lower_bound_rotation_order=false",
    }
    assert [rotation.name for rotation in captured["rotations"]] == [
        rotation.name for rotation in _h48_symmetry_rotations(2, include_identity=False)
    ]
    assert "selected_backend=resident-h48-symmetry-batch" in result.notes
    assert "backend_solver=fast_optimal_oracle_h48h7_symmetry_batch" in result.notes
    assert "resident_h48_symmetry_batch" in result.notes
    assert "fast_runtime_proven_for_every_possible_state=false" in result.notes


def test_universal_can_use_parallel_h48_rotational_symmetry_race(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_parallel_h48(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        max_concurrency=None,
        order_by_lower_bound=False,
        lower_bound_order_timeout_seconds=30.0,
    ):
        captured["variant_count"] = variant_count
        captured["include_identity"] = include_identity
        captured["timeout_seconds"] = timeout_seconds
        captured["max_concurrency"] = max_concurrency
        captured["order_by_lower_bound"] = order_by_lower_bound
        captured["lower_bound_order_timeout_seconds"] = lower_bound_order_timeout_seconds
        return SolverResult(
            solver_name="fast_optimal_oracle_h48h7_parallel_symmetry_race",
            input_state=cube_arg.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.125,
            expanded_nodes=10,
            generated_nodes=None,
            table_bytes=1234,
            status="exact",
            is_verified=True,
            notes=(
                "parallel H48 rotational symmetry race; "
                "exactness_policy=first_rotated_exact_solution_mapped_back_and_verified; "
                "identity_rotation_included=True; selected_rotation=rot00"
            ),
        )

    def fail_resident_h48_symmetry(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        rotations=None,
        rotation_order_note="h48_symmetry_h48_lower_bound_rotation_order=false",
    ):
        raise AssertionError("resident H48 symmetry should be skipped when not configured")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after parallel H48 symmetry race succeeds")

    monkeypatch.setattr(FastOptimalOracle, "solve_parallel_rotated_variants", fake_parallel_h48)
    monkeypatch.setattr(FastOptimalOracle, "solve_rotated_variants", fail_resident_h48_symmetry)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        parallel_h48_symmetry_variants=3,
        parallel_h48_symmetry_timeout_seconds=0.75,
        parallel_h48_symmetry_max_concurrency=2,
    )
    result = UniversalOptimalOracle(config).solve(cube)

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert captured == {
        "variant_count": 3,
        "include_identity": True,
        "timeout_seconds": 0.75,
        "max_concurrency": 2,
        "order_by_lower_bound": False,
        "lower_bound_order_timeout_seconds": 30.0,
    }
    assert "selected_backend=parallel-h48-symmetry-race" in result.notes
    assert "backend_solver=fast_optimal_oracle_h48h7_parallel_symmetry_race" in result.notes
    assert "parallel_h48_symmetry_race" in result.notes
    assert "fast_runtime_proven_for_every_possible_state=false" in result.notes


def test_universal_shared_symmetry_ordering_uses_h48_lower_bounds(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    rotations = [rotation for rotation in CUBE_ROTATIONS if not rotation.is_identity][:3]
    captured: dict[str, object] = {}

    def fake_order(cube_arg, rotations_arg, **kwargs):
        captured["cube"] = cube_arg.to_facelets()
        captured["rotation_names"] = [rotation.name for rotation in rotations_arg]
        captured["kwargs"] = kwargs
        return list(reversed(rotations_arg)), "h48_lower_bound_rotation_order=true; order_status=applied"

    monkeypatch.setattr(oracle_module, "order_h48_rotations_by_lower_bound", fake_order)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=0.5,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        ordered, note = oracle._order_symmetry_rotations_by_h48_lower_bound(
            cube,
            rotations,
            context="nissy_symmetry",
        )
    finally:
        oracle.close()

    assert [rotation.name for rotation in ordered] == [rotation.name for rotation in reversed(rotations)]
    assert captured["cube"] == cube.to_facelets()
    assert captured["rotation_names"] == [rotation.name for rotation in rotations]
    assert captured["kwargs"]["solver"] == "h48h7"
    assert captured["kwargs"]["table_path"] == table
    assert captured["kwargs"]["timeout_seconds"] == 0.5
    assert note == "nissy_symmetry_h48_lower_bound_rotation_order=true; order_status=applied"


def test_universal_resident_h48_symmetry_uses_shared_h48_lower_bound_ordering(
    monkeypatch,
    tmp_path,
):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    captured: dict[str, object] = {}

    def fake_order(cube_arg, rotations_arg, **kwargs):
        captured["order_cube"] = cube_arg.to_facelets()
        captured["order_input_names"] = [rotation.name for rotation in rotations_arg]
        captured["order_kwargs"] = kwargs
        return list(reversed(rotations_arg)), (
            "h48_lower_bound_rotation_order=true; order_status=applied"
        )

    def fake_h48_symmetry(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        rotations=None,
        rotation_order_note="h48_symmetry_h48_lower_bound_rotation_order=false",
    ):
        captured["variant_count"] = variant_count
        captured["include_identity"] = include_identity
        captured["timeout_seconds"] = timeout_seconds
        captured["rotation_names"] = [rotation.name for rotation in rotations]
        captured["rotation_order_note"] = rotation_order_note
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7_symmetry_batch",
            solution=["F2", "U'", "R'"],
        )

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after H48 symmetry prepass succeeds")

    monkeypatch.setattr(oracle_module, "order_h48_rotations_by_lower_bound", fake_order)
    monkeypatch.setattr(FastOptimalOracle, "solve_rotated_variants", fake_h48_symmetry)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_h48_symmetry_variants=3,
        resident_h48_symmetry_timeout_seconds=0.75,
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=0.25,
    )
    result = UniversalOptimalOracle(config).solve(cube)

    default_names = [
        rotation.name for rotation in _h48_symmetry_rotations(3, include_identity=False)
    ]
    assert result.status == "exact"
    assert captured["order_cube"] == cube.to_facelets()
    assert captured["order_input_names"] == default_names
    assert captured["order_kwargs"]["solver"] == "h48h7"
    assert captured["order_kwargs"]["table_path"] == table
    assert captured["order_kwargs"]["timeout_seconds"] == 0.25
    assert captured["variant_count"] == 3
    assert captured["include_identity"] is False
    assert captured["timeout_seconds"] == 0.75
    assert captured["rotation_names"] == list(reversed(default_names))
    assert captured["rotation_order_note"] == (
        "resident_h48_symmetry_h48_lower_bound_rotation_order=true; order_status=applied"
    )
    assert "selected_backend=resident-h48-symmetry-batch" in result.notes


def test_universal_solve_many_can_use_resident_h48_rotational_symmetry_prepass(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_h48_symmetry(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        rotations=None,
        rotation_order_note="h48_symmetry_h48_lower_bound_rotation_order=false",
    ):
        captured["variant_count"] = variant_count
        captured["include_identity"] = include_identity
        captured["timeout_seconds"] = timeout_seconds
        captured["rotations"] = rotations
        captured["rotation_order_note"] = rotation_order_note
        return SolverResult(
            solver_name="fast_optimal_oracle_h48h7_symmetry_batch",
            input_state=cube_arg.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.125,
            expanded_nodes=10,
            generated_nodes=None,
            table_bytes=1234,
            status="exact",
            is_verified=True,
            notes=(
                "resident H48 rotational symmetry batch; "
                "exactness_policy=rotated_exact_solution_mapped_back_and_verified; "
                "identity_rotation_included=False; symmetry_variants=2; selected_rotation=rot02"
            ),
        )

    def fail_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        raise AssertionError("portfolio batch should not run after H48 symmetry solve_many prepass succeeds")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after H48 symmetry solve_many prepass succeeds")

    monkeypatch.setattr(FastOptimalOracle, "solve_rotated_variants", fake_h48_symmetry)
    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fail_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_h48_symmetry_variants=2,
        resident_h48_symmetry_timeout_seconds=0.75,
        prefer_resident_h48_batch_for_state_input=True,
    )

    [result] = UniversalOptimalOracle(config).solve_many([cube], source_sequences=[None])

    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified
    assert captured == {
        "variant_count": 2,
        "include_identity": False,
        "timeout_seconds": 0.75,
        "rotations": captured["rotations"],
        "rotation_order_note": "resident_h48_symmetry_h48_lower_bound_rotation_order=false",
    }
    assert [rotation.name for rotation in captured["rotations"]] == [
        rotation.name for rotation in _h48_symmetry_rotations(2, include_identity=False)
    ]
    assert "selected_backend=resident-h48-symmetry-batch" in result.notes
    assert "backend_solver=fast_optimal_oracle_h48h7_symmetry_batch" in result.notes
    assert "rotated_exact_solution_mapped_back_and_verified" in result.notes
    assert "fast_runtime_proven_for_every_possible_state=false" in result.notes


def test_universal_solve_many_uses_portfolio_batch_for_live_states(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["cube_count"] = len(cubes_arg)
        captured["source_sequences"] = list(source_sequences or [])
        return [
            _exact_result(
                cube_arg,
                solver_name="portfolio_optimal_oracle",
                solution=inverse_sequence(parse_sequence(source)),
            )
            for cube_arg, source in zip(cubes_arg, source_sequences or [], strict=True)
        ]

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("universal solve_many should use the batch portfolio before per-state race")

    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=["R U F2", "R U"])
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["cube_count"] == 2
    assert captured["source_sequences"] == ["R U F2", "R U"]
    assert all("selected_backend=portfolio-batch" in result.notes for result in results)
    assert all("backend_solver=portfolio_optimal_oracle" in result.notes for result in results)


def test_fast_optimal_oracle_solve_many_uses_resident_session_batch(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured["session_kwargs"] = kwargs

        def start(self):
            captured["started"] = True

        def solve_many(self, cubes_arg, *, timeout_seconds=None):
            captured["cube_count"] = len(cubes_arg)
            captured["timeout_seconds"] = timeout_seconds
            return [
                _exact_result(cubes_arg[0], solver_name="h48_native_h48h7", solution=["F2", "U'", "R'"]),
                _exact_result(cubes_arg[1], solver_name="h48_native_h48h7", solution=["U'", "R'"]),
            ]

        def close(self):
            captured["closed"] = True

    def fail_single_solve(self, cube_arg):
        raise AssertionError("FastOptimalOracle.solve_many should use the resident session batch path")

    monkeypatch.setattr(oracle_module, "H48NativeOracleSession", FakeSession)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_single_solve)

    oracle = FastOptimalOracle(
        FastOptimalOracleConfig(
            root=tmp_path,
            table_path=tmp_path / "missing.bin",
            solver="h48h7",
            timeout_seconds=1.5,
            threads=1,
        )
    )
    results = oracle.solve_many(cubes)

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["started"] is True
    assert captured["cube_count"] == 2
    assert captured["timeout_seconds"] == 1.5
    assert captured["session_kwargs"]["search_timeout_seconds"] == 1.5
    assert all("resident_native_h48_batch_api=true" in result.notes for result in results)
    assert all("batch_input_count=2" in result.notes for result in results)


def test_universal_solve_many_can_use_resident_h48_batch_for_state_input(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_h48_batch(self, cubes_arg):
        captured["cube_count"] = len(cubes_arg)
        return [
            _exact_result(cubes_arg[0], solver_name="fast_optimal_oracle_h48h7", solution=["F2", "U'", "R'"]),
            _exact_result(cubes_arg[1], solver_name="fast_optimal_oracle_h48h7", solution=["U'", "R'"]),
        ]

    def fail_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        raise AssertionError("resident H48 batch should be used before portfolio batch in this mode")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident H48 batch should avoid per-state race calls")

    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)
    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fail_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["cube_count"] == 2
    assert all("selected_backend=resident-h48-batch" in result.notes for result in results)
    assert all("backend_solver=fast_optimal_oracle_h48h7" in result.notes for result in results)


def test_universal_solve_many_counts_failed_parallel_h48_prepass_before_batch(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_parallel_h48(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        max_concurrency=None,
        order_by_lower_bound=False,
        lower_bound_order_timeout_seconds=30.0,
    ):
        captured["parallel_variant_count"] = variant_count
        captured["parallel_include_identity"] = include_identity
        captured["parallel_timeout_seconds"] = timeout_seconds
        captured["parallel_max_concurrency"] = max_concurrency
        captured["parallel_order_by_lower_bound"] = order_by_lower_bound
        captured["parallel_lower_bound_order_timeout_seconds"] = lower_bound_order_timeout_seconds
        return SolverResult(
            solver_name="fast_optimal_oracle_h48h7_parallel_symmetry_race",
            input_state=cube_arg.to_facelets(),
            solution_moves=[],
            solution_length=None,
            metric="HTM",
            runtime_seconds=7.0,
            expanded_nodes=None,
            generated_nodes=None,
            table_bytes=1234,
            status="timeout",
            is_verified=False,
            notes="fake parallel H48 symmetry race timeout",
        )

    def fake_h48_batch(self, cubes_arg):
        captured["h48_cube_count"] = len(cubes_arg)
        return [
            _exact_result(cubes_arg[0], solver_name="fast_optimal_oracle_h48h7", solution=["F2", "U'", "R'"]),
        ]

    def fail_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        raise AssertionError("portfolio batch should not run in resident H48 batch mode")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident H48 batch should avoid per-state race calls")

    monkeypatch.setattr(FastOptimalOracle, "solve_parallel_rotated_variants", fake_parallel_h48)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)
    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fail_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        parallel_h48_symmetry_variants=2,
        parallel_h48_symmetry_timeout_seconds=7.0,
        parallel_h48_symmetry_max_concurrency=1,
        prefer_resident_h48_batch_for_state_input=True,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.is_verified
    assert result.runtime_seconds >= 7.0
    assert captured == {
        "parallel_variant_count": 2,
        "parallel_include_identity": True,
        "parallel_timeout_seconds": 7.0,
        "parallel_max_concurrency": 1,
        "parallel_order_by_lower_bound": False,
        "parallel_lower_bound_order_timeout_seconds": 30.0,
        "h48_cube_count": 1,
    }
    assert "selected_backend=resident-h48-batch" in result.notes
    assert "parallel_h48_symmetry_prepass_initial_status=timeout" in result.notes
    assert "parallel_h48_symmetry_prepass_initial_runtime_seconds=7.000000" in result.notes


def test_universal_solve_many_uses_nissy_core_direct_symmetry_before_resident_h48(
    monkeypatch,
    tmp_path,
):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    fake_binary = tmp_path / "nissy-core"
    fake_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakePopen(_FakeProcess):
        def __init__(self, command, *, cwd, text, stdout, stderr):
            super().__init__(0, stdout="F2 U' R'\n")
            captured["command"] = command
            captured["cwd"] = cwd
            captured["text"] = text
            captured["stdout"] = stdout
            captured["stderr"] = stderr

    def fail_h48_batch(self, cubes_arg):
        raise AssertionError("resident H48 batch should not run after a direct nissy-core symmetry exact result")

    monkeypatch.setattr(oracle_module, "_find_nissy_core_shell", lambda root, binary_path=None: fake_binary)
    monkeypatch.setattr(oracle_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fail_h48_batch)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_core_direct_symmetry_variants=2,
        nissy_core_direct_symmetry_timeout_seconds=1.0,
        nissy_core_direct_symmetry_max_concurrency=1,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=False,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_length == 3
    assert "selected_backend=nissy-core-direct-symmetry-race" in result.notes
    assert "backend_solver=nissy_core_direct_symmetry_race" in result.notes
    command = captured["command"]
    assert command[0] == str(fake_binary)
    assert command[command.index("-cube") + 1]
    assert command[command.index("-O") + 1] == "0"
    assert command[command.index("-n") + 1] == "1"
    assert command[command.index("-t") + 1] == "1"


def test_universal_nissy_core_direct_symmetry_uses_global_timeout_before_h48_batch(
    monkeypatch,
    tmp_path,
):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    fake_binary = tmp_path / "nissy-core"
    fake_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    clock = {"now": 0.0}
    started_commands: list[list[str]] = []
    stopped_commands: list[list[str]] = []

    class HangingPopen(_FakeProcess):
        def __init__(self, command, *, cwd, text, stdout, stderr):
            super().__init__(None)
            self.command = command
            self.returncode = None
            started_commands.append(command)

        def terminate(self):
            stopped_commands.append(self.command)
            super().terminate()
            self.returncode = self.return_code

    def fake_perf_counter():
        return clock["now"]

    def fake_sleep(seconds):
        clock["now"] += max(float(seconds), 1.0)

    def fake_h48_batch(self, cubes_arg):
        return [
            _exact_result(
                cube_arg,
                solver_name="fast_optimal_oracle_h48h7",
                solution=["F2", "U'", "R'"],
            )
            for cube_arg in cubes_arg
        ]

    monkeypatch.setattr(oracle_module, "_find_nissy_core_shell", lambda root, binary_path=None: fake_binary)
    monkeypatch.setattr(oracle_module.subprocess, "Popen", HangingPopen)
    monkeypatch.setattr(oracle_module.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(oracle_module.time, "sleep", fake_sleep)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        nissy_core_direct_symmetry_variants=2,
        nissy_core_direct_symmetry_timeout_seconds=1.0,
        nissy_core_direct_symmetry_max_concurrency=1,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=False,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert len(started_commands) == 1
    assert len(stopped_commands) == 1
    assert result.status == "exact"
    assert result.is_verified
    assert "selected_backend=resident-h48-batch" in result.notes
    assert "nissy_core_direct_symmetry_prepass_initial_status=timeout" in result.notes
    assert "global_timeout_seconds=1.0" in result.notes
    assert "global_timeout_expired=True" in result.notes
    assert "pending_rotations_not_started=2" in result.notes


def test_universal_solve_many_falls_back_after_resident_h48_batch_timeout(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_h48_batch(self, cubes_arg):
        captured["h48_cube_count"] = len(cubes_arg)
        return [
            _exact_result(cubes_arg[0], solver_name="fast_optimal_oracle_h48h7", solution=["F2", "U'", "R'"]),
            _timeout_result(cubes_arg[1], solver_name="fast_optimal_oracle_h48h7"),
        ]

    def fake_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["fallback_cube_count"] = len(cubes_arg)
        captured["fallback_sources"] = list(source_sequences or [])
        captured["fallback_timeout_seconds"] = self.config.nissy_timeout_seconds
        return [
            _exact_result(cubes_arg[0], solver_name="portfolio_optimal_oracle", solution=["U'", "R'"]),
        ]

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident H48 batch fallback should avoid per-state race calls")

    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)
    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        portfolio_fallback_timeout_seconds=9.0,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["h48_cube_count"] == 2
    assert captured["fallback_cube_count"] == 1
    assert captured["fallback_sources"] == [None]
    assert captured["fallback_timeout_seconds"] == 9.0
    assert "selected_backend=resident-h48-batch" in results[0].notes
    assert "selected_backend=portfolio-after-resident-h48-fallback" in results[1].notes
    assert "resident_h48_batch_fallback=true" in results[1].notes
    assert "resident_h48_batch_initial_status=timeout" in results[1].notes


def test_universal_solve_many_uses_portfolio_prepass_before_resident_h48_batch(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["prepass_cube_count"] = len(cubes_arg)
        captured["prepass_sources"] = list(source_sequences or [])
        return [
            _exact_result(cubes_arg[0], solver_name="portfolio_optimal_oracle", solution=["F2", "U'", "R'"]),
            _timeout_result(cubes_arg[1], solver_name="portfolio_optimal_oracle"),
        ]

    def fake_h48_batch(self, cubes_arg):
        captured["h48_cube_count"] = len(cubes_arg)
        return [
            _exact_result(cubes_arg[0], solver_name="fast_optimal_oracle_h48h7", solution=["U'", "R'"]),
        ]

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("adaptive solve_many should avoid per-state race calls")

    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_portfolio_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=True,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["prepass_cube_count"] == 2
    assert captured["prepass_sources"] == [None, None]
    assert captured["h48_cube_count"] == 1
    assert "selected_backend=portfolio-before-resident-h48-batch" in results[0].notes
    assert "selected_backend=resident-h48-batch-after-portfolio-prepass" in results[1].notes
    assert "portfolio_prepass_before_resident_h48_batch=true" in results[1].notes
    assert "portfolio_prepass_initial_status=timeout" in results[1].notes


def test_universal_adaptive_batch_prepass_skips_per_row_nissy_core_direct(tmp_path):
    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_portfolio_batch_before_resident_h48_batch=True,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        assert oracle._batch_portfolio.config.try_nissy_first is True
        assert oracle._batch_portfolio.config.try_nissy_core_direct_first is False
        assert oracle._batch_portfolio.config.try_h48_fallback is False
    finally:
        oracle.close()


def test_portfolio_solve_many_can_disable_h48_fallback(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    captured: dict[str, object] = {}

    def fake_nissy_batch(cubes_arg, *, timeout_seconds, **kwargs):
        captured["nissy_timeout_seconds"] = timeout_seconds
        return [_timeout_result(cubes_arg[0], solver_name="nissy_optimal_external")]

    def fail_h48(self, cube_arg):
        raise AssertionError("H48 fallback should be disabled for bounded prepass mode")

    monkeypatch.setattr("rubik_optimal.oracle.solve_nissy_optimal_batch", fake_nissy_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve", fail_h48)

    config = PortfolioOptimalOracleConfig(
        h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
        nissy_timeout_seconds=0.5,
        nissy_threads=1,
        try_nissy_first=True,
        try_nissy_core_direct_first=False,
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        try_h48_fallback=False,
    )
    oracle = PortfolioOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert result.status == "timeout"
    assert result.is_verified is False
    assert captured["nissy_timeout_seconds"] == 0.5
    assert "h48_fallback_disabled=true" in result.notes
    assert "resident_h48_invoked=false" in result.notes


def test_universal_adaptive_batch_prepass_uses_separate_timeout(tmp_path):
    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=300.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_portfolio_batch_before_resident_h48_batch=True,
        portfolio_prepass_timeout_seconds=30.0,
        portfolio_fallback_timeout_seconds=300.0,
        portfolio_fallback_nissy_core_direct_timeout_seconds=45.0,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        assert oracle._batch_portfolio.config.nissy_timeout_seconds == 30.0
        assert oracle._fallback_portfolio.config.nissy_timeout_seconds == 300.0
        assert oracle._fallback_portfolio.config.try_nissy_core_direct_first is True
        assert oracle._fallback_portfolio.config.nissy_core_direct_timeout_seconds == 45.0
        assert oracle._fallback_portfolio.config.try_h48_fallback is False
    finally:
        oracle.close()


def test_universal_resident_h48_batch_miss_uses_late_nissy_core_direct_fallback(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U")
    captured: dict[str, object] = {}

    def fake_h48_batch(self, cubes_arg):
        captured["h48_cube_count"] = len(cubes_arg)
        return [_timeout_result(cubes_arg[0], solver_name="fast_optimal_oracle_h48h7")]

    def fake_fallback_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["fallback_cube_count"] = len(cubes_arg)
        captured["fallback_sources"] = list(source_sequences or [])
        captured["fallback_try_nissy_core_direct_first"] = self.config.try_nissy_core_direct_first
        captured["fallback_nissy_core_direct_timeout_seconds"] = (
            self.config.nissy_core_direct_timeout_seconds
        )
        return [
            SolverResult(
                solver_name="portfolio_optimal_oracle",
                input_state=cubes_arg[0].to_facelets(),
                solution_moves=["U'", "R'"],
                solution_length=2,
                metric="HTM",
                runtime_seconds=0.5,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=1234,
                status="exact",
                is_verified=True,
                notes=(
                    "portfolio exact oracle; selected_backend=nissy-core-direct; "
                    "nissy_core_direct_invoked=true; resident_h48_invoked=false"
                ),
            )
        ]

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("adaptive solve_many should use late fallback portfolio, not per-state race")

    monkeypatch.setattr(FastOptimalOracle, "solve_many", fake_h48_batch)
    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_fallback_portfolio_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=False,
        resident_h48_batch_timeout_seconds=0.01,
        portfolio_fallback_nissy_core_direct_timeout_seconds=12.5,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert result.status == "exact"
    assert captured["h48_cube_count"] == 1
    assert captured["fallback_cube_count"] == 1
    assert captured["fallback_sources"] == [None]
    assert captured["fallback_try_nissy_core_direct_first"] is True
    assert captured["fallback_nissy_core_direct_timeout_seconds"] == 12.5
    assert "selected_backend=portfolio-after-resident-h48-fallback" in result.notes
    assert "selected_backend=nissy-core-direct" in result.notes
    assert "resident_h48_batch_initial_status=timeout" in result.notes


def test_universal_solve_many_reuses_shared_rubikoptimal_resident_after_live_misses(
    monkeypatch, tmp_path
):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {}

    def fake_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["portfolio_cube_count"] = len(cubes_arg)
        return [_timeout_result(cube, solver_name="portfolio_optimal_oracle") for cube in cubes_arg]

    class FakeRubikOptimalSession:
        instances: list["FakeRubikOptimalSession"] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.solve_calls: list[tuple[str, float]] = []
            self.start_count = 0
            self.closed = 0
            FakeRubikOptimalSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            self.solve_calls.append((cube_arg.to_facelets(), timeout_seconds))
            if cube_arg.to_facelets() == cubes[0].to_facelets():
                return _exact_result(
                    cube_arg,
                    solver_name="rubikoptimal_external",
                    solution=["F2", "U'", "R'"],
                )
            return _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution=["U'", "R'"],
            )

        def close(self):
            self.closed += 1

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("solve_many should use batched fallback paths, not per-state race calls")

    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_portfolio_batch)
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=False,
        rubikoptimal_fallback_timeout_seconds=4.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert captured["portfolio_cube_count"] == 2
    assert len(FakeRubikOptimalSession.instances) == 1
    assert FakeRubikOptimalSession.instances[0].solve_calls == [
        (cubes[0].to_facelets(), 4.0),
        (cubes[1].to_facelets(), 4.0),
    ]
    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert all("selected_backend=rubikoptimal-after-universal-fallback" in result.notes for result in results)
    assert all("universal_rubikoptimal_fallback=true" in result.notes for result in results)
    assert all(
        "universal_fallback_uses_shared_rubikoptimal_session=true" in result.notes
        for result in results
    )
    assert all("rubikoptimal_resident_start_count=1" in result.notes for result in results)
    assert all("prior_universal_status=timeout" in result.notes for result in results)


def test_universal_solve_many_reuses_shared_rubikoptimal_resident_when_live_backends_disabled(
    monkeypatch, tmp_path
):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]

    class FakeRubikOptimalSession:
        instances: list["FakeRubikOptimalSession"] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.solve_calls: list[tuple[str, float]] = []
            self.start_count = 0
            self.closed = 0
            FakeRubikOptimalSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            self.solve_calls.append((cube_arg.to_facelets(), timeout_seconds))
            if cube_arg.to_facelets() == cubes[0].to_facelets():
                return _exact_result(
                    cube_arg,
                    solver_name="rubikoptimal_external",
                    solution=["F2", "U'", "R'"],
                )
            return _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution=["U'", "R'"],
            )

        def close(self):
            self.closed += 1

    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_fallback_timeout_seconds=4.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert len(FakeRubikOptimalSession.instances) == 1
    assert FakeRubikOptimalSession.instances[0].solve_calls == [
        (cubes[0].to_facelets(), 4.0),
        (cubes[1].to_facelets(), 4.0),
    ]
    assert [result.status for result in results] == ["exact", "exact"]
    assert all("selected_backend=rubikoptimal-after-universal-fallback" in result.notes for result in results)
    assert all("selected_backend=live-backends-disabled" in result.notes for result in results)
    assert all(
        "universal_fallback_uses_shared_rubikoptimal_session=true" in result.notes
        for result in results
    )


def test_universal_solve_many_uses_rubikoptimal_prepass_before_h48_batch(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]

    class FakeRubikOptimalSession:
        instances: list["FakeRubikOptimalSession"] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.solve_calls: list[tuple[str, float]] = []
            self.start_count = 0
            self.closed = 0
            FakeRubikOptimalSession.instances.append(self)

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            self.solve_calls.append((cube_arg.to_facelets(), timeout_seconds))
            if cube_arg.to_facelets() == cubes[0].to_facelets():
                return _exact_result(
                    cube_arg,
                    solver_name="rubikoptimal_external",
                    solution=["F2", "U'", "R'"],
                )
            return _exact_result(
                cube_arg,
                solver_name="rubikoptimal_external",
                solution=["U'", "R'"],
            )

        def close(self):
            self.closed += 1

    def fail_h48_batch(self, cubes_arg):
        raise AssertionError("resident H48 batch should not run when RubikOptimal prepass proves all rows")

    def fail_rubikoptimal_batch(cubes_arg, **kwargs):
        raise AssertionError("RubikOptimal prepass should reuse the shared resident session")

    monkeypatch.setattr(
        "rubik_optimal.oracle.solve_rubikoptimal_external_batch",
        fail_rubikoptimal_batch,
        raising=False,
    )
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fail_h48_batch)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        prefer_resident_h48_batch_for_state_input=True,
        rubikoptimal_prepass_timeout_seconds=4.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert len(FakeRubikOptimalSession.instances) == 1
    assert FakeRubikOptimalSession.instances[0].solve_calls == [
        (cubes[0].to_facelets(), 4.0),
        (cubes[1].to_facelets(), 4.0),
    ]
    assert [result.status for result in results] == ["exact", "exact"]
    assert all("selected_backend=rubikoptimal-prepass" in result.notes for result in results)
    assert all("universal_rubikoptimal_prepass=true" in result.notes for result in results)
    assert all(
        "universal_prepass_uses_shared_rubikoptimal_session=true" in result.notes
        for result in results
    )
    assert all("rubikoptimal_resident_start_count=1" in result.notes for result in results)


def test_universal_solve_many_uses_rubikoptimal_symmetry_after_prepass_timeout(monkeypatch, tmp_path):
    cube = CubeState.from_sequence("R U F2")
    rotation = [candidate for candidate in CUBE_ROTATIONS if not candidate.is_identity][0]
    rotated_cube = rotation.transform_cube(cube)
    rotated_solution = rotation.transform_sequence(["F2", "U'", "R'"])
    captured: dict[str, object] = {"calls": [], "resident_calls": [], "resident_timeouts": []}

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.start_count = 0

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            captured["resident_calls"].append(cube_arg.to_facelets())
            captured["resident_timeouts"].append(timeout_seconds)
            if cube_arg.to_facelets() == rotated_cube.to_facelets():
                return _exact_result(
                    cube_arg,
                    solver_name="rubikoptimal_external",
                    solution=rotated_solution,
                )
            return _timeout_result(cube_arg, solver_name="rubikoptimal_external")

        def close(self):
            pass

    def fake_rubikoptimal_batch(cubes_arg, **kwargs):
        raise AssertionError("RubikOptimal symmetry batch should reuse the shared resident session")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after RubikOptimal symmetry proves exact")

    monkeypatch.setattr(
        "rubik_optimal.oracle.solve_rubikoptimal_external_batch",
        fake_rubikoptimal_batch,
        raising=False,
    )
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_prepass_timeout_seconds=2.0,
        rubikoptimal_symmetry_variants=1,
        rubikoptimal_symmetry_timeout_seconds=3.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert captured["calls"] == []
    assert captured["resident_calls"] == [cube.to_facelets(), rotated_cube.to_facelets()]
    assert captured["resident_timeouts"] == [2.0, 3.0]
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert "selected_backend=rubikoptimal-symmetry-batch" in result.notes
    assert "backend_solver=rubikoptimal_symmetry_batch_oracle" in result.notes
    assert "universal_rubikoptimal_symmetry_prepass=true" in result.notes
    assert "universal_symmetry_batch_uses_shared_rubikoptimal_session=true" in result.notes
    assert "selected_rotation=" in result.notes
    assert "rubikoptimal_prepass_initial_status=timeout" in result.notes


def test_universal_solve_many_can_race_rubikoptimal_symmetry_after_prepass_timeout(
    monkeypatch, tmp_path
):
    cube = CubeState.from_sequence("R U F2")
    table = tmp_path / "h48h7.bin"
    table.write_bytes(b"stub")
    captured: dict[str, object] = {"batch_calls": [], "prepass_calls": [], "prepass_timeouts": [], "race_calls": []}

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.start_count = 0

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            captured["prepass_calls"].append(cube_arg.to_facelets())
            captured["prepass_timeouts"].append(timeout_seconds)
            return _timeout_result(cube_arg, solver_name="rubikoptimal_external")

        def close(self):
            pass

    def fake_rubikoptimal_batch(cubes_arg, **kwargs):
        raise AssertionError("RubikOptimal symmetry race should not use the batch helper")

    def fake_rubikoptimal_race(cube_arg, **kwargs):
        captured["race_calls"].append((cube_arg.to_facelets(), kwargs))
        return _exact_result(
            cube_arg,
            solver_name="rubikoptimal_rotational_race",
            solution=["F2", "U'", "R'"],
        )

    def fake_order(cube_arg, rotations_arg, **kwargs):
        captured["order_cube"] = cube_arg.to_facelets()
        captured["order_input"] = [rotation.name for rotation in rotations_arg]
        return (
            list(reversed(rotations_arg)),
            "h48_lower_bound_rotation_order=true; order_status=applied",
        )

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after RubikOptimal symmetry race proves exact")

    monkeypatch.setattr(
        oracle_module,
        "solve_rubikoptimal_external_batch",
        fake_rubikoptimal_batch,
        raising=False,
    )
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(
        oracle_module,
        "solve_rubikoptimal_external_rotational_race",
        fake_rubikoptimal_race,
    )
    monkeypatch.setattr(oracle_module, "order_h48_rotations_by_lower_bound", fake_order)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=table),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_prepass_timeout_seconds=2.0,
        rubikoptimal_symmetry_variants=3,
        rubikoptimal_symmetry_timeout_seconds=3.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
        symmetry_order_by_h48_lower_bound=True,
        symmetry_lower_bound_order_timeout_seconds=0.5,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert captured["batch_calls"] == []
    assert captured["prepass_calls"] == [cube.to_facelets()]
    assert captured["prepass_timeouts"] == [2.0]
    assert len(captured["race_calls"]) == 1
    assert captured["race_calls"][0][0] == cube.to_facelets()
    race_kwargs = captured["race_calls"][0][1]
    assert race_kwargs["variant_count"] == 3
    assert race_kwargs["include_identity"] is False
    assert race_kwargs["timeout_seconds"] == 3.0
    assert race_kwargs["max_concurrency"] == 2
    assert [rotation.name for rotation in race_kwargs["rotations"]] == list(reversed(captured["order_input"]))
    assert (
        race_kwargs["rotation_order_note"]
        == "rubikoptimal_symmetry_race_h48_lower_bound_rotation_order=true; order_status=applied"
    )
    assert captured["order_cube"] == cube.to_facelets()
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert "selected_backend=rubikoptimal-symmetry-race" in result.notes
    assert "universal_rubikoptimal_symmetry_race=true" in result.notes
    assert "rubikoptimal_prepass_initial_status=timeout" in result.notes


def test_universal_rubikoptimal_symmetry_race_includes_identity_when_prepass_disabled(
    monkeypatch, tmp_path
):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    def fake_rubikoptimal_race(cube_arg, **kwargs):
        captured["cube"] = cube_arg.to_facelets()
        captured["kwargs"] = kwargs
        return _exact_result(
            cube_arg,
            solver_name="rubikoptimal_rotational_race",
            solution=["F2", "U'", "R'"],
        )

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after RubikOptimal symmetry race proves exact")

    monkeypatch.setattr(
        oracle_module,
        "solve_rubikoptimal_external_rotational_race",
        fake_rubikoptimal_race,
    )
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_prepass_timeout_seconds=None,
        rubikoptimal_symmetry_variants=2,
        rubikoptimal_symmetry_timeout_seconds=3.0,
        rubikoptimal_symmetry_max_concurrency=2,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        result = oracle.solve(cube, source_sequence=None)
    finally:
        oracle.close()

    assert captured["cube"] == cube.to_facelets()
    race_kwargs = captured["kwargs"]
    assert race_kwargs["include_identity"] is True
    assert race_kwargs["variant_count"] == 3
    assert [rotation.is_identity for rotation in race_kwargs["rotations"]] == [True, False, False]
    assert race_kwargs["timeout_seconds"] == 3.0
    assert race_kwargs["max_concurrency"] == 2
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert "selected_backend=rubikoptimal-symmetry-race" in result.notes


def test_universal_solve_many_rubikoptimal_symmetry_batch_includes_identity_when_prepass_disabled(
    monkeypatch, tmp_path
):
    cube = CubeState.from_sequence("R U F2")
    captured: dict[str, object] = {}

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.start_count = 0
            captured["cubes"] = []
            captured["timeout_seconds"] = []

        def solve(self, cube_arg, *, timeout_seconds):
            self.start_count = 1
            captured["cubes"].append(cube_arg.to_facelets())
            captured["timeout_seconds"].append(timeout_seconds)
            if len(captured["cubes"]) == 1:
                return _exact_result(
                    cube_arg,
                    solver_name="rubikoptimal_external",
                    solution=["F2", "U'", "R'"],
                )
            return _timeout_result(cube_arg, solver_name="rubikoptimal_external")

        def close(self):
            pass

    def fail_rubikoptimal_batch(cubes_arg, **kwargs):
        raise AssertionError("RubikOptimal symmetry batch should reuse the shared resident session")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("resident race should not run after RubikOptimal symmetry batch proves exact")

    monkeypatch.setattr(
        oracle_module,
        "solve_rubikoptimal_external_batch",
        fail_rubikoptimal_batch,
        raising=False,
    )
    monkeypatch.setattr(oracle_module, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=10.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        rubikoptimal_prepass_timeout_seconds=None,
        rubikoptimal_symmetry_variants=2,
        rubikoptimal_symmetry_timeout_seconds=3.0,
        rubikoptimal_table_dir=tmp_path / "rubikoptimal_tables",
    )
    oracle = UniversalOptimalOracle(config)
    try:
        [result] = oracle.solve_many([cube], source_sequences=[None])
    finally:
        oracle.close()

    assert captured["cubes"][0] == cube.to_facelets()
    assert len(captured["cubes"]) == 3
    assert captured["timeout_seconds"] == [1.0, 1.0, 1.0]
    assert result.status == "exact"
    assert result.is_verified
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert "selected_backend=rubikoptimal-symmetry-batch" in result.notes
    assert "identity_rotation_included=True" in result.notes
    assert "universal_symmetry_batch_uses_shared_rubikoptimal_session=true" in result.notes
    assert "selected_rotation=" in result.notes


def test_universal_solve_many_defers_h48_symmetry_until_after_portfolio_prepass(monkeypatch, tmp_path):
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    captured: dict[str, object] = {"h48_symmetry_inputs": []}

    def fake_portfolio_batch(self, cubes_arg, *, source_sequences=None):
        captured["prepass_cube_count"] = len(cubes_arg)
        captured["prepass_sources"] = list(source_sequences or [])
        return [
            _exact_result(cubes_arg[0], solver_name="portfolio_optimal_oracle", solution=["F2", "U'", "R'"]),
            _timeout_result(cubes_arg[1], solver_name="portfolio_optimal_oracle"),
        ]

    def fake_h48_symmetry(
        self,
        cube_arg,
        *,
        variant_count,
        include_identity,
        timeout_seconds,
        rotations=None,
        rotation_order_note="h48_symmetry_h48_lower_bound_rotation_order=false",
    ):
        captured["h48_symmetry_inputs"].append(cube_arg.to_facelets())
        captured["variant_count"] = variant_count
        captured["include_identity"] = include_identity
        captured["timeout_seconds"] = timeout_seconds
        captured["rotations"] = rotations
        captured["rotation_order_note"] = rotation_order_note
        return _exact_result(
            cube_arg,
            solver_name="fast_optimal_oracle_h48h7_symmetry_batch",
            solution=["U'", "R'"],
        )

    def fail_h48_batch(self, cubes_arg):
        raise AssertionError("resident H48 batch should not run when deferred H48 symmetry proves the remaining row")

    def fail_resident_race(self, cube_arg, *, source_sequence=None):
        raise AssertionError("adaptive solve_many should avoid per-state race calls")

    monkeypatch.setattr(PortfolioOptimalOracle, "solve_many", fake_portfolio_batch)
    monkeypatch.setattr(FastOptimalOracle, "solve_rotated_variants", fake_h48_symmetry)
    monkeypatch.setattr(FastOptimalOracle, "solve_many", fail_h48_batch)
    monkeypatch.setattr(ResidentRaceOptimalOracle, "solve", fail_resident_race)

    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, table_path=tmp_path / "missing.bin"),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=True,
            include_nissy=True,
        ),
        try_certificate_cache=False,
        try_upper_lower_certificate=False,
        resident_h48_symmetry_variants=2,
        resident_h48_symmetry_timeout_seconds=0.75,
        prefer_resident_h48_batch_for_state_input=True,
        try_portfolio_batch_before_resident_h48_batch=True,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        results = oracle.solve_many(cubes, source_sequences=[None, None])
    finally:
        oracle.close()

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert captured["prepass_cube_count"] == 2
    assert captured["prepass_sources"] == [None, None]
    assert captured["h48_symmetry_inputs"] == [cubes[1].to_facelets()]
    assert captured["variant_count"] == 2
    assert captured["include_identity"] is False
    assert captured["timeout_seconds"] == 0.75
    assert "selected_backend=portfolio-before-resident-h48-batch" in results[0].notes
    assert "selected_backend=resident-h48-symmetry-batch-after-portfolio-prepass" in results[1].notes
    assert "portfolio_prepass_before_resident_h48_batch=true" in results[1].notes
    assert "portfolio_prepass_initial_status=timeout" in results[1].notes
