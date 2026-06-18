from pathlib import Path

from rubik_optimal.cube import CubeState
import rubik_optimal.solvers.nissy_external as nissy_external
from rubik_optimal.solvers.nissy_external import (
    solve_nissy_core_direct_optimal,
    solve_nissy_core_direct_optimal_batch,
    solve_nissy_light_optimal,
    solve_nissy_light_optimal_batch,
    solve_nissy_optimal,
    solve_nissy_optimal_batch,
)


def test_nissy_external_parser_and_verification_with_fake_binary(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text("#!/bin/sh\nprintf \"F2 U' R' (3)\\n\"\n", encoding="utf-8")
    binary.chmod(0o755)

    cube = CubeState.from_sequence("R U F2")
    result = solve_nissy_light_optimal(
        cube,
        source_sequence=["R", "U", "F2"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert result.status == "exact"
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert result.solution_length == 3
    assert result.is_verified
    assert "input_mode=representative_scramble" in result.notes
    assert "source_sequence_provided=True" in result.notes


def test_nissy_external_solved_state_does_not_require_binary(tmp_path: Path):
    result = solve_nissy_light_optimal(
        CubeState.solved(),
        binary_path=tmp_path / "missing-nissy",
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
    )

    assert result.status == "exact"
    assert result.solution_moves == []
    assert result.solution_length == 0
    assert result.is_verified


def test_nissy_external_optimal_requires_public_table_before_invocation(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    binary.chmod(0o755)

    result = solve_nissy_optimal(
        CubeState.from_sequence("R U F2"),
        source_sequence=["R", "U", "F2"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert result.status == "not_applicable"
    assert result.solution_length is None
    assert "pt_nxopt31_HTM" in result.notes


def test_nissy_external_optimal_parser_with_fake_binary_and_table(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text("#!/bin/sh\nprintf \"F2 U' R' (3)\\n\"\n", encoding="utf-8")
    binary.chmod(0o755)
    table = tmp_path / "nissy_data" / "tables" / "pt_nxopt31_HTM"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"fake public optimal table marker")

    result = solve_nissy_optimal(
        CubeState.from_sequence("R U F2"),
        source_sequence=["R", "U", "F2"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert result.solver_name == "nissy_optimal_external"
    assert result.status == "exact"
    assert result.solution_length == 3
    assert result.is_verified


def test_nissy_optimal_uses_direct_state_bridge_without_source_sequence(
    tmp_path: Path, monkeypatch
):
    bridge = tmp_path / "nissy2-state-bridge"
    args_log = tmp_path / "bridge-args.txt"
    bridge.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" > " + str(args_log) + "\n"
        "printf \"U' R' (2)\\n\"\n",
        encoding="utf-8",
    )
    bridge.chmod(0o755)
    table_dir = tmp_path / "nissy_data" / "tables"
    table_dir.mkdir(parents=True)
    table_dir.joinpath("pt_nxopt31_HTM").write_bytes(b"fake nxopt table")
    table_dir.joinpath("pt_corners_HTM").write_bytes(b"fake corners table")
    monkeypatch.setattr(nissy_external, "build_nissy2_state_bridge", lambda **_: bridge)

    result = solve_nissy_optimal(
        CubeState.from_sequence("R U"),
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert result.solver_name == "nissy2_state_optimal_external"
    assert result.status == "exact"
    assert result.solution_moves == ["U'", "R'"]
    assert result.solution_length == 2
    assert result.is_verified
    assert "input_mode=cube_state" in result.notes
    assert "source_sequence_provided=false" in result.notes
    assert "R U" not in args_log.read_text(encoding="utf-8")


def test_nissy_optimal_single_row_batch_uses_direct_state_bridge(
    tmp_path: Path, monkeypatch
):
    bridge = tmp_path / "nissy2-state-bridge"
    bridge.write_text("#!/bin/sh\nprintf \"U' R' (2)\\n\"\n", encoding="utf-8")
    bridge.chmod(0o755)
    table_dir = tmp_path / "nissy_data" / "tables"
    table_dir.mkdir(parents=True)
    table_dir.joinpath("pt_nxopt31_HTM").write_bytes(b"fake nxopt table")
    table_dir.joinpath("pt_corners_HTM").write_bytes(b"fake corners table")
    monkeypatch.setattr(nissy_external, "build_nissy2_state_bridge", lambda **_: bridge)

    results = solve_nissy_optimal_batch(
        [CubeState.from_sequence("R U")],
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert len(results) == 1
    assert results[0].solver_name == "nissy2_state_optimal_external"
    assert results[0].status == "exact"
    assert results[0].solution_length == 2
    assert results[0].is_verified
    assert "input_mode=cube_state" in results[0].notes


def test_nissy_core_direct_uses_cube_state_and_symlinked_h48_table(tmp_path: Path):
    binary = tmp_path / "nissy-core-run"
    args_log = tmp_path / "args.txt"
    binary.write_text(
        "#!/bin/sh\n"
        "[ -f h48h0 ] || exit 7\n"
        "printf '%s\\n' \"$*\" > " + str(args_log) + "\n"
        "printf 'Reading tables from file h48h0\\n'\n"
        "printf '[H48 solve] Nodes visited: 0\\n'\n"
        "printf \"F2 U' R'\\n\"\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48h0 table")

    result = solve_nissy_core_direct_optimal(
        CubeState.from_sequence("R U F2"),
        solver="h48h0",
        table_path=table,
        binary_path=binary,
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert result.solver_name == "nissy_core_direct_h48h0"
    assert result.status == "exact"
    assert result.solution_moves == ["F2", "U'", "R'"]
    assert result.solution_length == 3
    assert result.is_verified
    assert "input_mode=cube_state" in result.notes
    assert "table_symlink=true" in result.notes
    assert "-cube" in args_log.read_text(encoding="utf-8")


def test_nissy_core_direct_batch_reuses_symlink_and_preserves_order(tmp_path: Path):
    binary = tmp_path / "nissy-core-run"
    args_log = tmp_path / "args.txt"
    binary.write_text(
        "#!/bin/sh\n"
        "[ -f h48h0 ] || exit 7\n"
        "printf '%s\\n' \"$*\" >> " + str(args_log) + "\n"
        "case \"$*\" in\n"
        "  *CEIVLBWH*) printf \"F2 U' R'\\n\" ;;\n"
        "  *) printf \"U' R'\\n\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake h48h0 table")
    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]

    results = solve_nissy_core_direct_optimal_batch(
        cubes,
        solver="h48h0",
        table_path=table,
        binary_path=binary,
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert all(result.is_verified for result in results)
    assert all("table_symlink_reused=true" in result.notes for result in results)
    assert all("process_per_row=true" in result.notes for result in results)
    assert args_log.read_text(encoding="utf-8").count("-cube") == 2


def test_nissy_core_direct_batch_can_use_python_resident_worker(tmp_path: Path, monkeypatch):
    module_dir = tmp_path / ".codex_external" / "nissy-core" / "python"
    module_dir.mkdir(parents=True)
    module_dir.joinpath("nissy.py").write_text(
        "solved_cube = 'ABCDEFGH=ABCDEFGHIJKL=A'\n"
        "nissflag_normal = 0\n"
        "def solve(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    if cube.startswith('CEIVLBWH'):\n"
        "        return [\"F2 U' R'\"]\n"
        "    if cube.startswith('IECVWBLH'):\n"
        "        return [\"U' R'\"]\n"
        "    return []\n",
        encoding="utf-8",
    )
    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake python resident table")
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON", raising=False)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES", raising=False)

    results = solve_nissy_core_direct_optimal_batch(
        [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")],
        solver="h48h0",
        table_path=table,
        binary_path=tmp_path / "missing-shell",
        root=tmp_path,
        timeout_seconds=5,
        threads=1,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert all(result.is_verified for result in results)
    assert all(result.solver_name == "nissy_core_python_resident_h48h0" for result in results)
    assert all("table_loaded_once=true" in result.notes for result in results)
    assert all("process_per_batch=true" in result.notes for result in results)
    assert all("table_data_mode=bytearray" in result.notes for result in results)


def test_nissy_core_direct_batch_python_resident_uses_mmap_solve_buffer(tmp_path: Path, monkeypatch):
    module_dir = tmp_path / ".codex_external" / "nissy-core" / "python"
    module_dir.mkdir(parents=True)
    module_dir.joinpath("nissy.py").write_text(
        "solved_cube = 'ABCDEFGH=ABCDEFGHIJKL=A'\n"
        "nissflag_normal = 0\n"
        "def solve(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    return []\n"
        "def solve_buffer(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    if data.__class__.__name__ != 'mmap':\n"
        "        return []\n"
        "    if cube.startswith('CEIVLBWH'):\n"
        "        return [\"F2 U' R'\"]\n"
        "    return []\n",
        encoding="utf-8",
    )
    table = tmp_path / "h48h0.bin"
    table.write_bytes(b"fake mmap resident table")
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON", raising=False)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES", raising=False)

    results = solve_nissy_core_direct_optimal_batch(
        [CubeState.from_sequence("R U F2")],
        solver="h48h0",
        table_path=table,
        binary_path=tmp_path / "missing-shell",
        root=tmp_path,
        timeout_seconds=5,
        threads=1,
    )

    assert results[0].status == "exact"
    assert results[0].is_verified
    assert "table_data_mode=mmap" in results[0].notes


def test_nissy_core_direct_batch_python_resident_mmap_bypasses_large_table_gate(
    tmp_path: Path, monkeypatch
):
    module_dir = tmp_path / ".codex_external" / "nissy-core" / "python"
    module_dir.mkdir(parents=True)
    module_dir.joinpath("nissy.py").write_text(
        "solved_cube = 'ABCDEFGH=ABCDEFGHIJKL=A'\n"
        "nissflag_normal = 0\n"
        "def solve(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    return []\n"
        "def solve_buffer(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    if data.__class__.__name__ != 'mmap':\n"
        "        return []\n"
        "    if cube.startswith('CEIVLBWH'):\n"
        "        return [\"F2 U' R'\"]\n"
        "    return []\n",
        encoding="utf-8",
    )
    table = tmp_path / "h48h7.bin"
    with table.open("wb") as handle:
        handle.truncate(513 * 1024 * 1024)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON", raising=False)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES", raising=False)

    results = solve_nissy_core_direct_optimal_batch(
        [CubeState.from_sequence("R U F2")],
        solver="h48h7",
        table_path=table,
        binary_path=tmp_path / "missing-shell",
        root=tmp_path,
        timeout_seconds=5,
        threads=1,
    )

    assert results[0].status == "exact"
    assert results[0].is_verified
    assert "table_data_mode=mmap" in results[0].notes
    assert "solve_buffer_available=True" in results[0].notes


def test_nissy_core_direct_batch_python_resident_large_bytearray_table_stays_gated(
    tmp_path: Path, monkeypatch
):
    module_dir = tmp_path / ".codex_external" / "nissy-core" / "python"
    module_dir.mkdir(parents=True)
    module_dir.joinpath("nissy.py").write_text(
        "solved_cube = 'ABCDEFGH=ABCDEFGHIJKL=A'\n"
        "nissflag_normal = 0\n"
        "def solve(cube, solver, nissflag, minmoves, maxmoves, maxsolutions, optimal, threads, data):\n"
        "    return [\"F2 U' R'\"]\n",
        encoding="utf-8",
    )
    table = tmp_path / "h48h7.bin"
    with table.open("wb") as handle:
        handle.truncate(513 * 1024 * 1024)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON", raising=False)
    monkeypatch.delenv("RUBIK_OPTIMAL_NISSY_CORE_PYTHON_MAX_TABLE_BYTES", raising=False)

    results = solve_nissy_core_direct_optimal_batch(
        [CubeState.from_sequence("R U F2")],
        solver="h48h7",
        table_path=table,
        binary_path=tmp_path / "missing-shell",
        root=tmp_path,
        timeout_seconds=5,
        threads=1,
    )

    assert results[0].status == "not_applicable"
    assert "Python resident backend unavailable" in results[0].notes


def test_nissy_external_light_batch_parser_with_fake_binary(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text(
        "#!/bin/sh\n"
        "while IFS= read -r line; do\n"
        "  printf '>>> Line: %s\\n' \"$line\"\n"
        "  case \"$line\" in\n"
        "    \"R U F2\") printf \"F2 U' R' (3)\\n\" ;;\n"
        "    \"R U\") printf \"U' R' (2)\\n\" ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)

    cubes = [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")]
    results = solve_nissy_light_optimal_batch(
        cubes,
        source_sequences=["R U F2", "R U"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert [result.status for result in results] == ["exact", "exact"]
    assert [result.solution_length for result in results] == [3, 2]
    assert all(result.is_verified for result in results)
    assert all("batch backend" in result.notes for result in results)
    assert all("source_sequence_provided=True" in result.notes for result in results)


def test_nissy_external_batch_timeout_preserves_completed_rows(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text(
        "#!/bin/sh\n"
        "while IFS= read -r line; do\n"
        "  case \"$line\" in\n"
        "    \"R U\") printf \"U' R' (2)\\n\" ;;\n"
        "    \"R U F2\") sleep 5 ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)

    results = solve_nissy_light_optimal_batch(
        [CubeState.from_sequence("R U"), CubeState.from_sequence("R U F2")],
        source_sequences=["R U", "R U F2"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert [result.status for result in results] == ["exact", "timeout"]
    assert results[0].solution_moves == ["U'", "R'"]
    assert results[0].is_verified is True
    assert "partial_timeout_recovered=true" in results[0].notes
    assert "partial_completed_count=1" in results[1].notes


def test_nissy_external_batch_orders_shorter_scrambles_before_timeout(tmp_path: Path):
    binary = tmp_path / "nissy"
    input_log = tmp_path / "input.txt"
    binary.write_text(
        "#!/bin/sh\n"
        ": > " + str(input_log) + "\n"
        "while IFS= read -r line; do\n"
        "  printf '%s\\n' \"$line\" >> " + str(input_log) + "\n"
        "  case \"$line\" in\n"
        "    \"R U F2\") sleep 5 ;;\n"
        "    \"R U\") printf \"U' R' (2)\\n\" ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)

    results = solve_nissy_light_optimal_batch(
        [CubeState.from_sequence("R U F2"), CubeState.from_sequence("R U")],
        source_sequences=["R U F2", "R U"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert input_log.read_text(encoding="utf-8").splitlines()[0] == "R U"
    assert [result.status for result in results] == ["timeout", "exact"]
    assert results[1].solution_moves == ["U'", "R'"]
    assert results[1].is_verified is True
    assert "partial_timeout_recovered=true" in results[1].notes
    assert "batch_ordered_by_scramble_length=true" in results[1].notes
    assert "batch_original_index=1" in results[1].notes


def test_nissy_external_optimal_batch_requires_public_table_before_invocation(tmp_path: Path):
    binary = tmp_path / "nissy"
    binary.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    binary.chmod(0o755)

    results = solve_nissy_optimal_batch(
        [CubeState.from_sequence("R U F2")],
        source_sequences=["R U F2"],
        binary_path=binary,
        data_dir=tmp_path / "nissy_data",
        root=tmp_path,
        timeout_seconds=2,
        threads=1,
    )

    assert len(results) == 1
    assert results[0].status == "not_applicable"
    assert "pt_nxopt31_HTM" in results[0].notes
