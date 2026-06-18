import json
import subprocess
import sys
from pathlib import Path

from rubik_optimal import cli
from rubik_optimal.cube import CubeState
from rubik_optimal.solvers.base import SolverResult
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, highest_available_h48_solver


def test_cli_help_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "scramble" in completed.stdout
    assert "facelets" in completed.stdout
    assert "distance" in completed.stdout
    assert "oracle" in completed.stdout


def test_cli_facelets_generates_valid_state(capsys):
    exit_code = cli.main(["facelets", "--length", "20", "--seed", "2026"])
    captured = capsys.readouterr()
    facelets = captured.out.strip()

    assert exit_code == 0
    assert len(facelets) == 54
    assert {color: facelets.count(color) for color in "URFDLB"} == {
        color: 9 for color in "URFDLB"
    }
    assert CubeState.from_facelets(facelets).to_facelets() == facelets


def test_cli_facelets_json_includes_scramble_metadata(capsys):
    exit_code = cli.main(["facelets", "--length", "3", "--seed", "2026", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["scramble_length"] == 3
    assert len(payload["scramble"]) == 3
    assert payload["metric"] == "HTM"
    assert payload["is_valid"] is True
    assert CubeState.from_sequence(payload["scramble"]).to_facelets() == payload["facelets"]


def test_cli_scramble_rejects_negative_length():
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "scramble", "--length", "-1", "--seed", "2026"],
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "--length must be non-negative" in completed.stderr


def test_cli_random_facelets_alias_matches_facelets(capsys):
    assert cli.main(["facelets", "--length", "5", "--seed", "7"]) == 0
    primary = capsys.readouterr().out

    assert cli.main(["random-facelets", "--length", "5", "--seed", "7"]) == 0
    alias = capsys.readouterr().out

    assert alias == primary


def test_cli_solve_help_exposes_3x3_native_paths():
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "solve", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "native-kociemba" in completed.stdout
    assert "optimal-native" in completed.stdout
    assert "h48-native" in completed.stdout
    assert "h48-oracle" in completed.stdout
    assert "race-optimal" in completed.stdout
    assert "resident-race-optimal" in completed.stdout
    assert "universal-optimal" in completed.stdout
    assert "nissy-core-direct" in completed.stdout
    assert "nissy-optimal" in completed.stdout
    assert "rubikoptimal" in completed.stdout
    assert "--nissy-heuristic" in completed.stdout
    assert "--no-nissy-axis-transforms" in completed.stdout
    assert "--native-child-order" in completed.stdout
    assert "--h48-start-delay" in completed.stdout
    assert "--universal-portfolio-fallback-timeout" in completed.stdout
    assert "--universal-rubikoptimal-race-timeout" in completed.stdout
    assert "--universal-resident-race-prepass-timeout" in completed.stdout
    assert "--universal-rubikoptimal-symmetry-variants" in completed.stdout
    assert "--universal-rubikoptimal-symmetry-timeout" in completed.stdout
    assert "--universal-rubikoptimal-symmetry-max-concurrency" in completed.stdout
    assert "--upper-solution" in completed.stdout
    assert "--upper-bound-proof-strategy" in completed.stdout
    assert "--h48-solver" in completed.stdout
    assert "--h48-oracle" in completed.stdout
    assert "--h48-fastest" in completed.stdout
    assert "--h48-trusted-table" in completed.stdout
    assert "--h48-preload-table" in completed.stdout
    assert "--h48-auto-min-depth" in completed.stdout
    assert "--h48-symmetry-variants" in completed.stdout
    assert "--h48-symmetry-timeout" in completed.stdout
    assert "--nissy-symmetry-variants" in completed.stdout
    assert "--nissy-symmetry-timeout" in completed.stdout
    assert "--nissy-core-direct-symmetry-variants" in completed.stdout
    assert "--nissy-core-direct-symmetry-timeout" in completed.stdout
    assert "--nissy-core-direct-symmetry-max-concurrency" in completed.stdout
    assert "--h48-parallel-symmetry-variants" in completed.stdout
    assert "--h48-parallel-symmetry-timeout" in completed.stdout
    assert "--h48-parallel-symmetry-max-concurrency" in completed.stdout
    assert "--symmetry-order-by-h48-lower-bound" in completed.stdout
    assert "--symmetry-lower-bound-order-timeout" in completed.stdout
    assert "--kociemba-upper-bound-symmetry-variants" in completed.stdout
    assert "--h48-upper-bound-proof-timeout" in completed.stdout
    assert "--h48-upper-bound-proof-max-gap" in completed.stdout
    assert "thistlethwaite" in completed.stdout
    assert "inverse" in completed.stdout


def test_cli_thistlethwaite_uses_scoped_public_solver_name(capsys):
    exit_code = cli.main(["solve", "R2 U2 F2", "--solver", "thistlethwaite", "--timeout", "5"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["solver_name"] == "thistlethwaite_native_scoped"
    assert payload["status"] == "non_exact"
    assert payload["is_verified"] is True
    assert payload["solution_moves"] == ["F2", "U2", "R2"]


def test_cli_distance_reports_invalid_count_valid_facelets(capsys):
    facelets = "DUUUUUUUURRRRRRRRRFFFFFFFFFUDDDDDDDDLLLLLLLLLBBBBBBBBB"
    exit_code = cli.main(["distance", facelets])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["kind"] == "invalid_state"
    assert payload["distance_value"] is None
    assert payload["method"] == "parse"


def test_cli_solve_reports_invalid_count_valid_facelets(capsys):
    facelets = "RUUUUUUUURRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
    exit_code = cli.main(["solve", facelets, "--solver", "korf"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["is_verified"] is False
    assert payload["solution_length"] is None
    assert payload["notes"]


def test_cli_verify_reports_invalid_count_valid_facelets(capsys):
    facelets = "UUUURUUUURRRRURRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
    exit_code = cli.main(["verify", facelets, "R"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["move_count"] == 0
    assert payload["message"]


def test_cli_universal_optimal_defaults_to_oracle_grade_trusted_h48(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_universal(cube, config=None, *, source_sequence=None):
        captured["cube"] = cube
        captured["config"] = config
        captured["source_sequence"] = source_sequence
        return SolverResult(
            solver_name="universal_optimal_oracle",
            input_state=cube.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.001,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=0,
            status="exact",
            is_verified=True,
            notes="test universal oracle",
        )

    monkeypatch.setattr(cli, "solve_universal_optimal", fake_universal)

    assert cli.main(["solve", "R U F2", "--solver", "universal-optimal"]) == 0
    output = json.loads(capsys.readouterr().out)

    config = captured["config"]
    assert config.resident_race.h48.solver == highest_available_h48_solver(profile="thesis")
    assert config.resident_race.h48.trusted_table is True
    assert config.resident_race.h48.auto_min_depth is False
    assert config.resident_h48_symmetry_variants == 0
    assert config.nissy_symmetry_variants == 0
    assert config.nissy_core_direct_symmetry_variants == 0
    assert config.parallel_h48_symmetry_variants == 0
    assert config.rubikoptimal_symmetry_variants == 0
    assert config.rubikoptimal_symmetry_max_concurrency == 0
    assert config.h48_upper_bound_proof_timeout_seconds == 0.0
    assert config.h48_upper_bound_proof_max_gap == 1
    assert config.native_korf_upper_bound_proof_timeout_seconds == 0.0
    assert config.native_korf_upper_bound_proof_max_gap == 1
    assert output["status"] == "exact"


def test_cli_nissy_core_direct_uses_oracle_h48_table(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_nissy_core_direct(cube, **kwargs):
        captured["cube"] = cube
        captured.update(kwargs)
        return SolverResult(
            solver_name="nissy_core_direct_h48h7",
            input_state=cube.to_facelets(),
            solution_moves=["F2", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.001,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=0,
            status="exact",
            is_verified=True,
            notes="input_mode=cube_state; table_symlink=true",
        )

    monkeypatch.setattr(cli, "solve_nissy_core_direct_optimal", fake_nissy_core_direct)

    assert cli.main(["solve", "R U F2", "--solver", "nissy-core-direct", "--threads", "1"]) == 0
    output = json.loads(capsys.readouterr().out)

    assert captured["solver"] == ORACLE_H48_SOLVER
    assert captured["profile"] == "thesis"
    assert captured["threads"] == 1
    assert output["status"] == "exact"


def test_cli_distance_help_exposes_h48_state_oracle():
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "distance", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "--h48-native" in completed.stdout
    assert "--h48-solver" in completed.stdout
    assert "--h48-oracle" in completed.stdout
    assert "--h48-fastest" in completed.stdout
    assert "--h48-trusted-table" in completed.stdout
    assert "--h48-preload-table" in completed.stdout
    assert "--h48-auto-min-depth" in completed.stdout
    assert "--h48-table" in completed.stdout


def test_cli_oracle_batch_solves_line_delimited_states():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "oracle",
            "--h48-solver",
            "h48h0",
            "--timeout",
            "20",
            "--threads",
            "8",
            "--h48-trusted-table",
        ],
        input="R U F2\nR U F2\n",
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["backend"] == "h48_native_batch"
    assert result["all_exact"] is True
    assert result["all_verified"] is True
    assert result["input_count"] == 2
    assert result["h48_trusted_table"] is True
    assert result["batch_wall_seconds"] > 0
    assert [row["distance"] for row in result["rows"]] == [3, 3]
    assert all("table_loaded_once=true" in row["notes"] for row in result["rows"])
    assert all("table_check=skipped" in row["notes"] for row in result["rows"])
    assert all("trusted_table_metadata=valid" in row["notes"] for row in result["rows"])


def test_cli_oracle_help_exposes_fastest_h48_profile():
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "oracle", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "--h48-fastest" in completed.stdout
    assert "--h48-trusted-table" in completed.stdout
    assert "--h48-preload-table" in completed.stdout
    assert "--h48-auto-min-depth" in completed.stdout
    assert "--h48-solver" in completed.stdout
    assert "--learned-certificate-log" in completed.stdout
    assert "--universal-portfolio-fallback-timeout" in completed.stdout
    assert "--universal-resident-race-prepass-timeout" in completed.stdout
    assert "--universal-rubikoptimal-symmetry-max-concurrency" in completed.stdout
    assert "--h48-symmetry-variants" in completed.stdout
    assert "--h48-symmetry-timeout" in completed.stdout
    assert "--nissy-symmetry-variants" in completed.stdout
    assert "--nissy-symmetry-timeout" in completed.stdout
    assert "--nissy-core-direct-symmetry-variants" in completed.stdout
    assert "--nissy-core-direct-symmetry-timeout" in completed.stdout
    assert "--nissy-core-direct-symmetry-max-concurrency" in completed.stdout
    assert "--h48-parallel-symmetry-variants" in completed.stdout
    assert "--h48-parallel-symmetry-timeout" in completed.stdout
    assert "--h48-parallel-symmetry-max-concurrency" in completed.stdout
    assert "--symmetry-order-by-h48-lower-bound" in completed.stdout
    assert "--symmetry-lower-bound-order-timeout" in completed.stdout
    assert "--kociemba-upper-bound-symmetry-variants" in completed.stdout
    assert "--h48-upper-bound-proof-timeout" in completed.stdout
    assert "--h48-upper-bound-proof-max-gap" in completed.stdout
    assert "--no-universal-certificate-cache" in completed.stdout
    assert "--no-universal-upper-lower-certificate" in completed.stdout
    assert "--universal" in completed.stdout
    assert "--stream" in completed.stdout


def test_cli_oracle_universal_uses_resident_h48_batch(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    class FakeUniversalOptimalOracle:
        def __init__(self, config):
            captured["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def solve_many(self, cubes):
            captured["cube_count"] = len(cubes)
            return [
                SolverResult(
                    solver_name="universal_optimal_oracle",
                    input_state=cube.to_facelets(),
                    solution_moves=["F2", "U'", "R'"],
                    solution_length=3,
                    metric="HTM",
                    runtime_seconds=0.001,
                    expanded_nodes=0,
                    generated_nodes=0,
                    table_bytes=0,
                    status="exact",
                    is_verified=True,
                    notes=(
                        "universal exact oracle; selected_backend=resident-h48-batch; "
                        "backend_solver=fast_optimal_oracle_h48h7; resident_native_h48=true; "
                        "table_loaded_once=true; input_mode=cube_state"
                    ),
                )
                for cube in cubes
            ]

    monkeypatch.setattr(cli, "UniversalOptimalOracle", FakeUniversalOptimalOracle)

    learned_log = tmp_path / "learned.jsonl"
    assert (
        cli.main(
            [
                "oracle",
                "--universal",
                "R U F2",
                "R U F2",
                "--threads",
                "1",
                "--h48-symmetry-variants",
                "2",
                "--h48-symmetry-timeout",
                "0.75",
                "--nissy-symmetry-variants",
                "3",
                "--nissy-symmetry-timeout",
                "1.25",
                "--nissy-core-direct-symmetry-variants",
                "4",
                "--nissy-core-direct-symmetry-timeout",
                "1.5",
                "--nissy-core-direct-symmetry-max-concurrency",
                "2",
                "--universal-rubikoptimal-fallback-timeout",
                "8.5",
                "--universal-rubikoptimal-prepass-timeout",
                "6.5",
                "--universal-rubikoptimal-symmetry-variants",
                "5",
                "--universal-rubikoptimal-symmetry-timeout",
                "2.5",
                "--universal-rubikoptimal-symmetry-max-concurrency",
                "2",
                "--universal-resident-race-prepass-timeout",
                "4.5",
                "--kociemba-upper-bound-symmetry-variants",
                "6",
                "--h48-upper-bound-proof-timeout",
                "2.25",
                "--h48-upper-bound-proof-max-gap",
                "3",
                "--native-korf-upper-bound-proof-timeout",
                "4.25",
                "--native-korf-upper-bound-proof-max-gap",
                "5",
                "--h48-auto-min-depth",
                "--learned-certificate-log",
                str(learned_log),
                "--no-universal-certificate-cache",
                "--no-universal-upper-lower-certificate",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    config = captured["config"]

    assert captured["cube_count"] == 2
    assert config.prefer_resident_h48_batch_for_state_input is True
    assert config.learned_certificate_artifact == learned_log
    assert config.resident_h48_symmetry_variants == 2
    assert config.resident_h48_symmetry_timeout_seconds == 0.75
    assert config.nissy_symmetry_variants == 3
    assert config.nissy_symmetry_timeout_seconds == 1.25
    assert config.nissy_core_direct_symmetry_variants == 4
    assert config.nissy_core_direct_symmetry_timeout_seconds == 1.5
    assert config.nissy_core_direct_symmetry_max_concurrency == 2
    assert config.rubikoptimal_fallback_timeout_seconds == 8.5
    assert config.rubikoptimal_prepass_timeout_seconds == 6.5
    assert config.rubikoptimal_symmetry_variants == 5
    assert config.rubikoptimal_symmetry_timeout_seconds == 2.5
    assert config.rubikoptimal_symmetry_max_concurrency == 2
    assert config.rubikoptimal_race_timeout_seconds is None
    assert config.resident_race_prepass_timeout_seconds == 4.5
    assert config.kociemba_upper_bound_symmetry_variants == 6
    assert config.h48_upper_bound_proof_timeout_seconds == 2.25
    assert config.h48_upper_bound_proof_max_gap == 3
    assert config.native_korf_upper_bound_proof_timeout_seconds == 4.25
    assert config.native_korf_upper_bound_proof_max_gap == 5
    assert config.try_certificate_cache is False
    assert config.try_upper_lower_certificate is False
    assert config.resident_race.h48.solver == highest_available_h48_solver(profile="thesis")
    assert config.resident_race.h48.trusted_table is True
    assert config.resident_race.h48.auto_min_depth is True
    assert output["backend"] == "universal_resident_h48_batch"
    assert output["universal_oracle"] is True
    assert output["resident_h48_symmetry_variants"] == 2
    assert output["resident_h48_symmetry_timeout_seconds"] == 0.75
    assert output["nissy_symmetry_variants"] == 3
    assert output["nissy_symmetry_timeout_seconds"] == 1.25
    assert output["nissy_core_direct_symmetry_variants"] == 4
    assert output["nissy_core_direct_symmetry_timeout_seconds"] == 1.5
    assert output["nissy_core_direct_symmetry_max_concurrency"] == 2
    assert output["rubikoptimal_fallback_timeout_seconds"] == 8.5
    assert output["rubikoptimal_prepass_timeout_seconds"] == 6.5
    assert output["rubikoptimal_symmetry_variants"] == 5
    assert output["rubikoptimal_symmetry_timeout_seconds"] == 2.5
    assert output["rubikoptimal_symmetry_max_concurrency"] == 2
    assert output["rubikoptimal_race_timeout_seconds"] is None
    assert output["resident_race_prepass_timeout_seconds"] == 4.5
    assert output["kociemba_upper_bound_symmetry_variants"] == 6
    assert output["h48_upper_bound_proof_timeout_seconds"] == 2.25
    assert output["h48_upper_bound_proof_max_gap"] == 3
    assert output["native_korf_upper_bound_proof_timeout_seconds"] == 4.25
    assert output["native_korf_upper_bound_proof_max_gap"] == 5
    assert output["try_certificate_cache"] is False
    assert output["try_upper_lower_certificate"] is False
    assert output["h48_trusted_table"] is True
    assert output["h48_auto_min_depth"] is True
    assert output["all_exact"] is True
    assert output["all_verified"] is True
    assert [row["selected_backend"] for row in output["rows"]] == [
        "resident-h48-batch",
        "resident-h48-batch",
    ]
    assert all(row["backend_solver"] == "fast_optimal_oracle_h48h7" for row in output["rows"])


def test_cli_oracle_universal_stream_uses_one_universal_oracle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {"solve_calls": 0}

    class FakeUniversalOptimalOracle:
        def __init__(self, config):
            captured["config"] = config

        def __enter__(self):
            captured["entered"] = captured.get("entered", 0) + 1
            return self

        def __exit__(self, exc_type, exc, traceback):
            captured["exited"] = captured.get("exited", 0) + 1
            return None

        def solve(self, cube, *, source_sequence=None):
            captured["solve_calls"] += 1
            captured.setdefault("source_sequences", []).append(source_sequence)
            return SolverResult(
                solver_name="universal_optimal_oracle",
                input_state=cube.to_facelets(),
                solution_moves=["F2", "U'", "R'"],
                solution_length=3,
                metric="HTM",
                runtime_seconds=0.001,
                expanded_nodes=0,
                generated_nodes=0,
                table_bytes=0,
                status="exact",
                is_verified=True,
                notes=(
                    "universal exact oracle; selected_backend=resident-race; "
                    "backend_solver=resident_race_optimal_oracle; "
                    "resident_h48_process=shared_batch_session"
                ),
            )

    monkeypatch.setattr(cli, "UniversalOptimalOracle", FakeUniversalOptimalOracle)

    learned_log = tmp_path / "stream-learned.jsonl"
    assert (
        cli.main(
            [
                "oracle",
                "--stream",
                "--universal",
                "R U F2",
                "R U F2",
                "--threads",
                "1",
                "--h48-symmetry-variants",
                "2",
                "--h48-symmetry-timeout",
                "0.75",
                "--nissy-symmetry-variants",
                "3",
                "--nissy-symmetry-timeout",
                "1.25",
                "--nissy-core-direct-symmetry-variants",
                "4",
                "--nissy-core-direct-symmetry-timeout",
                "1.5",
                "--nissy-core-direct-symmetry-max-concurrency",
                "2",
                "--universal-rubikoptimal-fallback-timeout",
                "8.5",
                "--universal-rubikoptimal-prepass-timeout",
                "6.5",
                "--universal-rubikoptimal-symmetry-variants",
                "5",
                "--universal-rubikoptimal-symmetry-timeout",
                "2.5",
                "--universal-rubikoptimal-symmetry-max-concurrency",
                "3",
                "--universal-rubikoptimal-race-timeout",
                "7.5",
                "--universal-resident-race-prepass-timeout",
                "4.5",
                "--kociemba-upper-bound-symmetry-variants",
                "7",
                "--h48-upper-bound-proof-timeout",
                "3.25",
                "--h48-upper-bound-proof-max-gap",
                "4",
                "--native-korf-upper-bound-proof-timeout",
                "5.25",
                "--native-korf-upper-bound-proof-max-gap",
                "6",
                "--learned-certificate-log",
                str(learned_log),
                "--no-universal-certificate-cache",
                "--no-universal-upper-lower-certificate",
            ]
        )
        == 0
    )
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    config = captured["config"]

    assert captured["entered"] == 1
    assert captured["exited"] == 1
    assert captured["solve_calls"] == 2
    assert captured["source_sequences"] == [["R", "U", "F2"], ["R", "U", "F2"]]
    assert config.learned_certificate_artifact == learned_log
    assert config.prefer_resident_h48_batch_for_state_input is False
    assert config.resident_race.h48.solver == highest_available_h48_solver(profile="thesis")
    assert config.resident_race.h48.trusted_table is True
    assert config.resident_h48_symmetry_variants == 2
    assert config.resident_h48_symmetry_timeout_seconds == 0.75
    assert config.nissy_symmetry_variants == 3
    assert config.nissy_symmetry_timeout_seconds == 1.25
    assert config.nissy_core_direct_symmetry_variants == 4
    assert config.nissy_core_direct_symmetry_timeout_seconds == 1.5
    assert config.nissy_core_direct_symmetry_max_concurrency == 2
    assert config.rubikoptimal_fallback_timeout_seconds == 8.5
    assert config.rubikoptimal_prepass_timeout_seconds == 6.5
    assert config.rubikoptimal_symmetry_variants == 5
    assert config.rubikoptimal_symmetry_timeout_seconds == 2.5
    assert config.rubikoptimal_symmetry_max_concurrency == 3
    assert config.rubikoptimal_race_timeout_seconds == 7.5
    assert config.resident_race_prepass_timeout_seconds == 4.5
    assert config.kociemba_upper_bound_symmetry_variants == 7
    assert config.h48_upper_bound_proof_timeout_seconds == 3.25
    assert config.h48_upper_bound_proof_max_gap == 4
    assert config.native_korf_upper_bound_proof_timeout_seconds == 5.25
    assert config.native_korf_upper_bound_proof_max_gap == 6
    assert config.try_certificate_cache is False
    assert config.try_upper_lower_certificate is False
    assert [row["status"] for row in output] == ["exact", "exact"]
    assert [row["selected_backend"] for row in output] == ["resident-race", "resident-race"]
    assert all(row["backend_solver"] == "resident_race_optimal_oracle" for row in output)


def test_cli_oracle_rubikoptimal_solves_rows_without_h48(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def fake_rubikoptimal_batch(cubes, **kwargs):
        captured["cubes"] = cubes
        captured["kwargs"] = kwargs
        return [
            SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cubes[0].to_facelets(),
                solution_moves=["F2", "U'", "R'"],
                solution_length=3,
                metric="HTM",
                runtime_seconds=0.001,
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

    monkeypatch.setattr(cli, "solve_rubikoptimal_external_batch", fake_rubikoptimal_batch)

    assert (
        cli.main(
            [
                "oracle",
                "--rubikoptimal",
                "R U F2",
                "--timeout",
                "9",
                "--rubikoptimal-table-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)

    assert captured["cubes"] == [CubeState.from_sequence("R U F2")]
    assert captured["kwargs"]["timeout_seconds"] == 9
    assert captured["kwargs"]["table_dir"] == tmp_path
    assert output["backend"] == "rubikoptimal_external"
    assert output["rubikoptimal"] is True
    assert output["all_exact"] is True
    assert output["all_verified"] is True
    assert output["rows"][0]["selected_backend"] == "rubikoptimal_external_batch"
    assert output["rows"][0]["backend_solver"] == "rubikoptimal_external"


def test_cli_oracle_rubikoptimal_stream_reuses_resident_session(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {"solve_calls": 0}

    class FakeRubikOptimalSession:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def __enter__(self):
            captured["entered"] = captured.get("entered", 0) + 1
            return self

        def __exit__(self, exc_type, exc, traceback):
            captured["exited"] = captured.get("exited", 0) + 1
            return None

        def solve(self, cube, *, timeout_seconds):
            captured["solve_calls"] += 1
            captured.setdefault("timeouts", []).append(timeout_seconds)
            return SolverResult(
                solver_name="rubikoptimal_external",
                input_state=cube.to_facelets(),
                solution_moves=["F2", "U'", "R'"],
                solution_length=3,
                metric="HTM",
                runtime_seconds=0.001,
                expanded_nodes=None,
                generated_nodes=None,
                table_bytes=963061264,
                status="exact",
                is_verified=True,
                notes=(
                    "resident RubikOptimal backend; "
                    "selected_backend=rubikoptimal_resident; "
                    "backend_solver=rubikoptimal_external"
                ),
            )

    def forbidden_one_shot(*args, **kwargs):
        raise AssertionError("streaming RubikOptimal oracle should reuse a resident session")

    monkeypatch.setattr(cli, "RubikOptimalOracleSession", FakeRubikOptimalSession)
    monkeypatch.setattr(cli, "solve_rubikoptimal_external", forbidden_one_shot)

    assert (
        cli.main(
            [
                "oracle",
                "--stream",
                "--rubikoptimal",
                "R U F2",
                "R U F2",
                "--timeout",
                "9",
                "--rubikoptimal-table-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert captured["entered"] == 1
    assert captured["exited"] == 1
    assert captured["solve_calls"] == 2
    assert captured["timeouts"] == [9, 9]
    assert captured["init_kwargs"]["table_dir"] == tmp_path
    assert [row["status"] for row in output] == ["exact", "exact"]
    assert [row["selected_backend"] for row in output] == [
        "rubikoptimal_resident",
        "rubikoptimal_resident",
    ]
    assert all(row["backend_solver"] == "rubikoptimal_external" for row in output)


def test_cli_oracle_stream_uses_resident_backend_jsonl():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "oracle",
            "--stream",
            "--h48-solver",
            "h48h0",
            "--timeout",
            "20",
            "--threads",
            "2",
            "--h48-trusted-table",
        ],
        input="R U F2\nR U F2\n",
        check=True,
        text=True,
        capture_output=True,
    )
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert [row["status"] for row in rows] == ["exact", "exact"]
    assert [row["distance"] for row in rows] == [3, 3]
    assert all(row["verified"] is True for row in rows)
    assert all("resident in-repo native H48 backend" in row["notes"] for row in rows)
    assert all("table_loaded_once=true" in row["notes"] for row in rows)
    assert all("trusted_table_metadata=valid" in row["notes"] for row in rows)


def test_cli_inverse_solver_verifies_sequence_input():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "solve",
            "R U F2 D",
            "--solver",
            "inverse",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["solver_name"] == "scramble_inverse_verified"
    assert result["status"] == "non_exact"
    assert result["is_verified"] is True


def test_cli_h48_solver_accepts_facelet_input_without_sequence_context():
    facelets = CubeState.from_sequence("R U F2").to_facelets()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "solve",
            facelets,
            "--solver",
            "h48-native",
            "--timeout",
            "10",
            "--threads",
            "8",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "exact"
    assert result["solution_length"] == 3
    assert result["is_verified"] is True
    assert "input_mode=cube_state" in result["notes"]


def test_cli_distance_can_use_h48_facelet_state_oracle():
    facelets = CubeState.from_sequence("R U F2").to_facelets()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "distance",
            facelets,
            "--bfs-depth",
            "0",
            "--h48-native",
            "--timeout",
            "10",
            "--threads",
            "8",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["kind"] == "exact_distance"
    assert result["distance_value"] == 3
    assert result["method"] == "h48_native_h48h0_depth_20"
    assert "input_mode=cube_state" in result["proof_notes"]


def test_cli_distance_h48_oracle_implies_h48_native():
    facelets = CubeState.from_sequence("R U F2").to_facelets()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rubik_optimal.cli",
            "distance",
            facelets,
            "--bfs-depth",
            "0",
            "--h48-oracle",
            "--timeout",
            "60",
            "--threads",
            "8",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["kind"] == "exact_distance"
    assert result["distance_value"] == 3
    assert result["method"] == "h48_native_h48h7_depth_20"
    assert "input_mode=cube_state" in result["proof_notes"]


def test_quick_benchmark_and_result_verifier(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "benchmark", "--quick", "--seed", "2026", "--root", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    paths = json.loads(completed.stdout)
    assert Path(paths["raw"]).exists()
    assert Path(paths["summary"]).exists()
    assert (tmp_path / "thesis" / "tables" / "benchmark_summary.tex").exists()


def test_benchmark_checkpoint_resume_skips_completed_rows(monkeypatch, tmp_path):
    from rubik_optimal import benchmark
    from rubik_optimal.results import read_jsonl

    monkeypatch.setattr(
        benchmark,
        "_cases",
        lambda seed, profile: [
            {
                "case_id": "tiny",
                "profile": profile,
                "seed": seed,
                "scramble": [],
                "scramble_depth": 0,
                "dataset": "T",
            }
        ],
    )

    def fake_result(name: str) -> SolverResult:
        return SolverResult(
            solver_name=name,
            input_state=CubeState.solved().to_facelets(),
            solution_moves=[],
            solution_length=0,
            metric="HTM",
            runtime_seconds=0.001,
            expanded_nodes=0,
            generated_nodes=0,
            table_bytes=0,
            status="non_exact",
            is_verified=True,
            notes="fake benchmark row",
        )

    korf_calls = 0

    def first_korf(*args, **kwargs):
        nonlocal korf_calls
        korf_calls += 1
        return fake_result("korf_ida_star_scoped")

    def interrupted_kociemba(*args, **kwargs):
        raise RuntimeError("stop after checkpoint")

    monkeypatch.setattr(benchmark, "solve_korf_ida", first_korf)
    monkeypatch.setattr(benchmark, "solve_kociemba_native_scoped", interrupted_kociemba)

    try:
        benchmark.run_benchmarks(seed=2026, profile="quick", root=tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "stop after checkpoint"
    else:
        raise AssertionError("benchmark interruption was not raised")

    raw_path = tmp_path / "results" / "raw" / "benchmarks_seed_2026_quick.jsonl"
    rows = read_jsonl(raw_path)
    assert [(row["case_id"], row["solver"]) for row in rows] == [
        ("tiny", "korf_ida_star_scoped")
    ]
    assert korf_calls == 1

    def skipped_korf(*args, **kwargs):
        raise AssertionError("completed Korf row should be skipped during resume")

    monkeypatch.setattr(benchmark, "solve_korf_ida", skipped_korf)
    monkeypatch.setattr(
        benchmark,
        "solve_kociemba_native_scoped",
        lambda *args, **kwargs: fake_result("kociemba_native_scoped"),
    )
    monkeypatch.setattr(
        benchmark,
        "solve_kociemba_adapter",
        lambda *args, **kwargs: fake_result("kociemba_two_phase_adapter"),
    )
    monkeypatch.setattr(
        benchmark,
        "solve_thistlethwaite_native_scoped",
        lambda *args, **kwargs: fake_result("thistlethwaite_native_scoped"),
    )

    benchmark.run_benchmarks(seed=2026, profile="quick", root=tmp_path, resume=True)
    rows = read_jsonl(raw_path)
    assert [(row["case_id"], row["solver"]) for row in rows] == [
        ("tiny", "korf_ida_star_scoped"),
        ("tiny", "kociemba_native_scoped"),
        ("tiny", "kociemba_two_phase_adapter"),
        ("tiny", "thistlethwaite_native_scoped"),
    ]


def test_generate_figures_uses_saved_benchmark_rows(monkeypatch):
    from scripts import generate_figures

    captured: dict[str, object] = {}

    def fake_generate(*, seed: int, profile: str, root: Path) -> dict[str, Path]:
        captured.update({"seed": seed, "profile": profile, "root": root})
        return {"raw": root / "raw.jsonl", "summary": root / "summary.json", "csv": root / "rows.csv"}

    monkeypatch.setattr(generate_figures, "generate_benchmark_artifacts_from_saved_results", fake_generate)
    assert generate_figures.main(["--profile", "thesis", "--seed", "2026"]) == 0
    assert captured["seed"] == 2026
    assert captured["profile"] == "thesis"
    assert captured["root"] == generate_figures.ROOT
