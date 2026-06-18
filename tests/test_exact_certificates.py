import json
from pathlib import Path

from rubik_optimal.cube import CubeState
from rubik_optimal.exact_certificates import ExactCertificateStore, default_certificate_artifacts
from rubik_optimal.oracle import (
    FastOptimalOracleConfig,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
)
from rubik_optimal.solvers.base import SolverResult


def test_certificate_store_accepts_public_cli_facelet_solution_moves(tmp_path: Path):
    cube = CubeState.from_sequence("R U")
    artifact = tmp_path / "results" / "processed" / "cli.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "case_id": "cli_state",
                        "input": cube.to_facelets(),
                        "input_kind": "facelets",
                        "solution_moves": ["U'", "R'"],
                        "solution_length": 2,
                        "status": "exact",
                        "verified": True,
                        "selected_backend": "upper-lower-certificate",
                        "runtime_seconds": 0.01,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    certificate = ExactCertificateStore(tmp_path, artifact_paths=[artifact]).find(cube)

    assert certificate is not None
    assert certificate.solution_moves == ["U'", "R'"]
    assert certificate.solution_length == 2
    assert certificate.source_solver == "upper-lower-certificate"


def test_default_certificate_artifacts_include_public_universal_cli_corpora():
    names = {path.name for path in default_certificate_artifacts(Path("/repo"))}

    assert "universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json" in names
    assert "nissy_benchmark_certificates_seed_2026_thesis_distances16_20.json" in names
    assert "rubikoptimal_oracle_corpus_seed_2026_thesis_lowload.json" in names
    assert "universal_oracle_cli_seed_2026_thesis_h48h7_superflip_probe_lowload.json" in names
    assert "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json" in names


def test_certificate_store_remembers_verified_exact_results_to_jsonl(tmp_path: Path):
    cube = CubeState.from_sequence("R U F")
    log_path = tmp_path / "results" / "processed" / "learned.jsonl"
    store = ExactCertificateStore(tmp_path, artifact_paths=[], learned_artifact_path=log_path)
    result = SolverResult(
        solver_name="test_exact_backend",
        input_state=cube.to_facelets(),
        solution_moves=["F'", "U'", "R'"],
        solution_length=3,
        metric="HTM",
        runtime_seconds=0.25,
        expanded_nodes=10,
        generated_nodes=None,
        table_bytes=1234,
        status="exact",
        is_verified=True,
        notes="selected_backend=test-backend",
    )

    assert store.remember_result(result, selected_backend="test-backend") is True
    assert store.find(cube) is not None

    reloaded = ExactCertificateStore(tmp_path, artifact_paths=[log_path]).find(cube)

    assert reloaded is not None
    assert reloaded.solution_moves == ["F'", "U'", "R'"]
    assert reloaded.source_solver == "test_exact_backend"


def test_universal_oracle_remembers_verified_exact_results_to_learned_cache(tmp_path: Path):
    cube = CubeState.from_sequence("R U F")
    log_path = tmp_path / "results" / "processed" / "learned.jsonl"
    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=FastOptimalOracleConfig(root=tmp_path, timeout_seconds=1.0, threads=1),
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
            include_nissy_core_direct=False,
        ),
        certificate_artifacts=(),
        learned_certificate_artifact=log_path,
        try_upper_lower_certificate=False,
    )
    oracle = UniversalOptimalOracle(config)
    try:
        exact = SolverResult(
            solver_name="test_exact_backend",
            input_state=cube.to_facelets(),
            solution_moves=["F'", "U'", "R'"],
            solution_length=3,
            metric="HTM",
            runtime_seconds=0.25,
            expanded_nodes=10,
            generated_nodes=None,
            table_bytes=1234,
            status="exact",
            is_verified=True,
            notes="selected_backend=test-backend",
        )

        wrapped = oracle._wrap_result(
            exact,
            selected_backend="test-backend",
            total_runtime_seconds=0.3,
        )
    finally:
        oracle.close()

    assert wrapped.status == "exact"
    assert log_path.exists()

    reloaded = ExactCertificateStore(tmp_path, artifact_paths=[log_path]).find(cube)

    assert reloaded is not None
    assert reloaded.solution_moves == ["F'", "U'", "R'"]
