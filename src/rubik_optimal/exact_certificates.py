"""Reusable exact-solution certificate cache for already proved 3x3 states.

Certificate caveat (read before trusting reuse):

    Re-validation performed by this module (``verify_solution`` over the stored
    move sequence, plus the inverse and symmetry closures) proves only solution
    **VALIDITY**: that the recorded sequence of length ``L`` actually solves the
    state. Validity is an UPPER BOUND on the true distance -- it shows the state
    is solvable in ``L`` moves, not that ``L`` is minimal.

    **OPTIMALITY (distance == L) is INHERITED, not re-derived here.** A row is
    only loaded as an exact certificate when the originating solver already
    recorded ``status == "exact"`` and ``verified == True`` (see
    ``_certificate_from_row``). This module does NOT independently re-search the
    state space to confirm minimality; it trusts the source solver's exactness
    flag and merely re-checks that the cached solution is still a valid solution
    of the stated length. If the source flag is wrong, this cache will not
    detect a non-optimal length.

Exactness basis (``exactness_basis``):

    Every certificate carries a machine-readable basis for its optimality
    claim. ``"local_proof"`` means the source row came from a completed local
    exact search; ``"third_party_benchmark_label"`` means the distance is only
    a third-party label (e.g. the nissy-core known-distance benchmark files)
    whose replay was verified locally but whose minimality was never proven
    here. Rows with ``status == "external_label_exact"`` (or an explicit
    non-local ``exactness_basis`` field) are EXCLUDED from the store by
    default; pass ``include_external_label=True`` to opt in. Inverse and
    symmetry closure children inherit the parent's basis.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
from typing import Iterable

from .cube import CubeState
from .moves import inverse_sequence, parse_sequence
from .solvers.base import SolverResult
from .symmetry import CUBE_ROTATIONS
from .verify import verify_solution

LOCAL_PROOF_BASIS = "local_proof"
EXTERNAL_LABEL_BASIS = "third_party_benchmark_label"
EXTERNAL_LABEL_STATUS = "external_label_exact"


class CertificateConflictError(RuntimeError):
    """Two certificates claim different exact lengths for the same state.

    The exact distance of a state is unique, so a length conflict proves that
    at least one source row's exactness flag is wrong. This must surface as an
    error instead of being silently resolved.
    """


@dataclass(frozen=True)
class ExactCertificate:
    state: str
    solution_moves: list[str]
    solution_length: int
    artifact_path: Path
    case_id: str
    source_solver: str
    source_runtime_seconds: float | None
    derivation: str = "direct"
    exactness_basis: str = LOCAL_PROOF_BASIS


def default_certificate_artifacts(root: Path) -> tuple[Path, ...]:
    processed = root / "results" / "processed"
    names = [
        "h48_resident_certification_seed_2026_thesis_h48h7_trusted.json",
        "h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json",
        "h48_oracle_certification_seed_2026_thesis.json",
        "h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json",
        "portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json",
        "portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json",
        "portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json",
        "portfolio_optimal_oracle_seed_2026_thesis_nissy_state_recovery_lowload.json",
        "portfolio_optimal_oracle_seed_2026_thesis_nissy_core_direct_state_lowload.json",
        "race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "resident_race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "resident_race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "universal_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "universal_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_batch_lowload.json",
        "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json",
        "universal_oracle_cli_seed_2026_thesis_h48h7_optimized_lowload.json",
        "universal_oracle_cli_seed_2026_thesis_h48h7_broader_lowload.json",
        "universal_oracle_cli_seed_2026_thesis_h48h7_adaptive_lowload.json",
        "universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json",
        "universal_oracle_cli_seed_2026_thesis_h48h7_superflip_probe_lowload.json",
        "universal_symmetry_oracle_seed_2026_thesis_h48h7_lowload.json",
        "nissy_benchmark_certificates_seed_2026_thesis_distances16_20.json",
        "rubikoptimal_oracle_corpus_seed_2026_thesis_lowload.json",
        "optimal_3x3_seed_2026_stress_h48h7_oracle.json",
        "optimal_3x3_seed_2026_stress_nissy_optimal.json",
        "optimal_3x3_seed_2026_thesis_nissy_optimal.json",
        "optimal_3x3_seed_2026_thesis_nissy_core_direct_lowload.json",
        "fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json",
    ]
    return tuple(processed / name for name in names)


class ExactCertificateStore:
    """Loads saved exact/verified result rows and revalidates before reuse.

    Revalidation here re-checks solution VALIDITY only (the cached sequence
    still solves the state in its recorded length, an upper bound). OPTIMALITY
    is INHERITED from the source row's ``status == "exact"`` flag and is not
    independently re-derived: this store never re-proves that the recorded
    length equals the true distance. See the module docstring for details.

    Rows whose exactness rests only on a third-party label
    (``status == "external_label_exact"`` or a non-local ``exactness_basis``)
    are excluded by default; ``include_external_label=True`` opts in.
    """

    def __init__(
        self,
        root: Path,
        artifact_paths: Iterable[Path] | None = None,
        learned_artifact_path: Path | None = None,
        *,
        include_external_label: bool = False,
    ) -> None:
        self.root = root
        self.learned_artifact_path = learned_artifact_path
        self.include_external_label = include_external_label
        base_artifacts = tuple(artifact_paths) if artifact_paths is not None else default_certificate_artifacts(root)
        if learned_artifact_path is not None:
            learned_artifact = learned_artifact_path if learned_artifact_path.is_absolute() else root / learned_artifact_path
            self.artifact_paths = tuple(path for path in base_artifacts if path != learned_artifact) + (
                learned_artifact,
            )
        else:
            self.artifact_paths = base_artifacts
        self._by_state: dict[str, ExactCertificate] | None = None
        self._lock = threading.Lock()

    def find(self, cube: CubeState) -> ExactCertificate | None:
        if self._by_state is None:
            self._by_state = self._load()
        return self._by_state.get(cube.to_facelets())

    def all_certificates(self) -> tuple[ExactCertificate, ...]:
        if self._by_state is None:
            self._by_state = self._load()
        return tuple(self._by_state.values())

    def remember_result(
        self,
        result: SolverResult,
        *,
        selected_backend: str,
        case_id: str | None = None,
    ) -> bool:
        if self.learned_artifact_path is None:
            return False
        if result.status != "exact" or result.is_verified is not True or result.solution_length is None:
            return False
        try:
            cube = CubeState.from_facelets(result.input_state)
        except Exception:
            return False
        verification = verify_solution(cube, result.solution_moves)
        if not verification.ok or len(result.solution_moves) != result.solution_length:
            return False
        artifact = (
            self.learned_artifact_path
            if self.learned_artifact_path.is_absolute()
            else self.root / self.learned_artifact_path
        )
        digest = hashlib.sha256(cube.to_facelets().encode("ascii")).hexdigest()[:16]
        row = {
            "schema_version": 1,
            "case_id": case_id or f"learned_{digest}",
            "state": cube.to_facelets(),
            "solution": " ".join(result.solution_moves),
            "solution_moves": result.solution_moves,
            "solution_length": result.solution_length,
            "solver": result.solver_name,
            "selected_backend": selected_backend,
            "status": "exact",
            "verified": True,
            "runtime_seconds": result.runtime_seconds,
            "learned_certificate": True,
            "notes": result.notes,
        }
        certificate = self._certificate_from_row(artifact, row)
        if certificate is None:
            return False
        with self._lock:
            if self.find(cube) is not None:
                return False
            artifact.parent.mkdir(parents=True, exist_ok=True)
            with artifact.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            if self._by_state is not None:
                self._add_best(self._by_state, certificate)
                self._add_symmetry_closure(self._by_state, certificate)
                inverse_certificate = self._inverse_certificate(certificate)
                if inverse_certificate is not None:
                    self._add_best(self._by_state, inverse_certificate)
                    self._add_symmetry_closure(self._by_state, inverse_certificate)
        return True

    def _load(self) -> dict[str, ExactCertificate]:
        certificates: dict[str, ExactCertificate] = {}
        for path in self.artifact_paths:
            artifact = path if path.is_absolute() else self.root / path
            if not artifact.exists():
                continue
            try:
                rows = self._rows_from_artifact(artifact)
            except Exception:
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                certificate = self._certificate_from_row(artifact, row)
                if certificate is None:
                    continue
                self._add_best(certificates, certificate)
                self._add_symmetry_closure(certificates, certificate)
                inverse_certificate = self._inverse_certificate(certificate)
                if inverse_certificate is not None:
                    self._add_best(certificates, inverse_certificate)
                    self._add_symmetry_closure(certificates, inverse_certificate)
        return certificates

    @staticmethod
    def _rows_from_artifact(artifact: Path) -> list[object]:
        if artifact.suffix == ".jsonl":
            rows = []
            for line in artifact.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if text:
                    rows.append(json.loads(text))
            return rows
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        rows = payload.get("rows") or payload.get("cases") or []
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _add_best(certificates: dict[str, ExactCertificate], certificate: ExactCertificate) -> None:
        previous = certificates.get(certificate.state)
        if previous is None:
            certificates[certificate.state] = certificate
            return
        if certificate.solution_length == previous.solution_length:
            return
        raise CertificateConflictError(
            "conflicting exact lengths for the same state: "
            f"{previous.solution_length} (case_id={previous.case_id}, "
            f"artifact={previous.artifact_path}) vs "
            f"{certificate.solution_length} (case_id={certificate.case_id}, "
            f"artifact={certificate.artifact_path}); "
            "at least one source exactness flag is wrong"
        )

    def _inverse_certificate(self, certificate: ExactCertificate) -> ExactCertificate | None:
        try:
            inverse_cube = CubeState.from_sequence(certificate.solution_moves)
            inverse_solution = inverse_sequence(certificate.solution_moves)
        except Exception:
            return None
        verification = verify_solution(inverse_cube, inverse_solution)
        if not verification.ok:
            return None
        return ExactCertificate(
            state=inverse_cube.to_facelets(),
            solution_moves=inverse_solution,
            solution_length=len(inverse_solution),
            artifact_path=certificate.artifact_path,
            case_id=f"{certificate.case_id}#inverse",
            source_solver=f"{certificate.source_solver}+inverse_certificate_closure",
            source_runtime_seconds=certificate.source_runtime_seconds,
            derivation="inverse",
            exactness_basis=certificate.exactness_basis,
        )

    def _add_symmetry_closure(
        self,
        certificates: dict[str, ExactCertificate],
        certificate: ExactCertificate,
    ) -> None:
        try:
            cube = CubeState.from_facelets(certificate.state)
        except Exception:
            return
        for rotation in CUBE_ROTATIONS:
            if rotation.is_identity:
                continue
            rotated_cube = rotation.transform_cube(cube)
            rotated_solution = rotation.transform_sequence(certificate.solution_moves)
            verification = verify_solution(rotated_cube, rotated_solution)
            if not verification.ok:
                continue
            derivation = (
                "symmetry" if certificate.derivation == "direct" else f"{certificate.derivation}_symmetry"
            )
            self._add_best(
                certificates,
                ExactCertificate(
                    state=rotated_cube.to_facelets(),
                    solution_moves=rotated_solution,
                    solution_length=len(rotated_solution),
                    artifact_path=certificate.artifact_path,
                    case_id=f"{certificate.case_id}#{rotation.name}",
                    source_solver=f"{certificate.source_solver}+symmetry_certificate_closure",
                    source_runtime_seconds=certificate.source_runtime_seconds,
                    derivation=derivation,
                    exactness_basis=certificate.exactness_basis,
                ),
            )

    def _certificate_from_row(self, artifact: Path, row: dict[str, object]) -> ExactCertificate | None:
        status = row.get("status")
        if status == "exact":
            exactness_basis = str(row.get("exactness_basis") or LOCAL_PROOF_BASIS)
        elif status == EXTERNAL_LABEL_STATUS:
            exactness_basis = str(row.get("exactness_basis") or EXTERNAL_LABEL_BASIS)
        else:
            return None
        if row.get("verified") is not True:
            return None
        if exactness_basis != LOCAL_PROOF_BASIS and not self.include_external_label:
            return None
        raw_state = row.get("state") or row.get("input_state") or row.get("facelets")
        if raw_state is None and row.get("input_kind") == "facelets":
            raw_state = row.get("input")
        raw_solution = row.get("solution")
        if raw_solution is None:
            raw_solution = row.get("solution_moves")
        raw_length = row.get("solution_length")
        if not isinstance(raw_state, str) or raw_solution is None or raw_length is None:
            return None
        try:
            cube = CubeState.from_facelets(raw_state)
            if isinstance(raw_solution, list):
                solution = parse_sequence(" ".join(str(move) for move in raw_solution))
            else:
                solution = parse_sequence(str(raw_solution))
            length = int(raw_length)
        except Exception:
            return None
        if len(solution) != length:
            return None
        verification = verify_solution(cube, solution)
        if not verification.ok:
            return None
        runtime = row.get("runtime_seconds")
        return ExactCertificate(
            state=cube.to_facelets(),
            solution_moves=solution,
            solution_length=length,
            artifact_path=artifact,
            case_id=str(row.get("case_id", "unknown")),
            source_solver=str(
                row.get("solver")
                or row.get("backend_solver")
                or row.get("selected_backend")
                or "saved_exact_artifact"
            ),
            source_runtime_seconds=float(runtime) if isinstance(runtime, (int, float)) else None,
            derivation="direct",
            exactness_basis=exactness_basis,
        )
