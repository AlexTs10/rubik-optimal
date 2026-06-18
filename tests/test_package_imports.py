import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_raw_checkout_import_shim_exports_oracle_api():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import rubik_optimal; "
                "from rubik_optimal import "
                "CubeState, FastOptimalOracle, FastOptimalOracleConfig, "
                "UniversalOptimalOracle, solve_universal_optimal; "
                "missing = [name for name in rubik_optimal.__all__ "
                "if not hasattr(rubik_optimal, name)]; "
                "assert not missing, missing; "
                "assert CubeState.solved().to_facelets(); "
                "assert FastOptimalOracle.__name__ == 'FastOptimalOracle'; "
                "assert FastOptimalOracleConfig.__name__ == 'FastOptimalOracleConfig'; "
                "assert UniversalOptimalOracle.__name__ == 'UniversalOptimalOracle'; "
                "assert callable(solve_universal_optimal); "
                "print('ok')"
            ),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_raw_checkout_module_cli_help_runs_without_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-m", "rubik_optimal.cli", "--help"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "solve" in completed.stdout
    assert "oracle" in completed.stdout
