#!/usr/bin/env python
"""Audit thesis scale, generated artifacts, and claim-risk markers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.source_state import capture_source_state

THESIS = ROOT / "thesis"
TARGET_MIN_PAGES = 90
TARGET_MIN_WORDS = 22_000
TARGET_MIN_FIGURES_TABLES = 20

REQUIRED_REPOSITORY_PATHS = [
    "pyproject.toml",
    "README.md",
    "REPRODUCIBILITY.md",
    "AGENTS.md",
    "docs",
    "docs/THIRD_PARTY_NOTICES.md",
    "specs/topic_brief.pdf",
    "src/rubik_optimal",
    "tests",
    "scripts",
    "data/generated",
    "results/raw",
    "results/processed",
    "thesis/main.tex",
    "thesis/references.bib",
    "thesis/chapters",
    "thesis/figures",
    "thesis/tables",
]

REQUIRED_IMPLEMENTATION_PATHS = [
    "src/rubik_optimal/cube.py",
    "src/rubik_optimal/moves.py",
    "src/rubik_optimal/scramble.py",
    "src/rubik_optimal/validity.py",
    "src/rubik_optimal/verify.py",
    "src/rubik_optimal/distance.py",
    "src/rubik_optimal/coordinates/corner_orientation.py",
    "src/rubik_optimal/coordinates/edge_orientation.py",
    "src/rubik_optimal/coordinates/corner_permutation.py",
    "src/rubik_optimal/coordinates/edge_permutation.py",
    "src/rubik_optimal/coordinates/ud_slice.py",
    "src/rubik_optimal/coordinates/phase2.py",
    "src/rubik_optimal/tables/generation.py",
    "src/rubik_optimal/tables/corner_pdb.py",
    "src/rubik_optimal/tables/edge_pdb.py",
    "src/rubik_optimal/tables/h48.py",
    "src/rubik_optimal/tables/move_tables.py",
    "src/rubik_optimal/tables/pruning_tables.py",
    "src/rubik_optimal/search/bfs.py",
    "src/rubik_optimal/search/ida_star.py",
    "src/rubik_optimal/search/heuristics.py",
    "src/rubik_optimal/solvers/kociemba.py",
    "src/rubik_optimal/solvers/thistlethwaite.py",
    "src/rubik_optimal/solvers/korf.py",
    "src/rubik_optimal/solvers/optimal_native.py",
    "src/rubik_optimal/solvers/h48_native.py",
    "src/rubik_optimal/symmetry.py",
    "src/rubik_optimal/oracle.py",
    "src/rubik_optimal/solvers/nissy_external.py",
    "src/rubik_optimal/solvers/rubikoptimal_external.py",
    "src/rubik_optimal/solvers/end_to_end.py",
    "src/rubik_optimal/pocket/cube.py",
    "src/rubik_optimal/pocket/optimal.py",
    "src/rubik_optimal/cli.py",
    "scripts/run_3x3_end_to_end.py",
    "scripts/run_3x3_optimal.py",
    "scripts/generate_corner_pdb.py",
    "scripts/generate_edge_pdb.py",
    "scripts/benchmark_edge_pdb_coverage.py",
    "scripts/generate_h48_tables.py",
    "scripts/install_h48_table_bundle.py",
    "scripts/run_h48_stronger_table_campaign.py",
    "scripts/experimental/plan_cloud_hardtail_campaign.py",
    "scripts/experimental/run_cloud_hardtail_workload.py",
    "scripts/experimental/run_cloud_hardtail_campaign.py",
    "scripts/experimental/evaluate_cloud_hardtail_campaign.py",
    "scripts/experimental/render_cloud_hardtail_runbook.py",
    "scripts/experimental/run_h48_fasttarget_remote.py",
    "scripts/generate_rubikoptimal_tables.py",
    "scripts/run_rubikoptimal_oracle_corpus.py",
    "scripts/probe_h48_generation_throughput.py",
    "scripts/run_h48_oracle_certification.py",
    "scripts/benchmark_h48_batch_overhead.py",
    "scripts/benchmark_h48_solver_levels.py",
    "scripts/benchmark_h48_trusted_table.py",
    "scripts/run_h48_oracle_cli.py",
    "scripts/run_h48_oracle_stream.py",
    "scripts/benchmark_h48_resident_oracle.py",
    "scripts/run_h48_resident_certification.py",
    "scripts/run_fast_optimal_oracle_api.py",
    "scripts/run_nissy_core_resident_mmap.py",
    "scripts/generate_h48_oracle_contract.py",
    "scripts/install_nissy_public_table.py",
    "scripts/verify_nissy_public_tables.py",
    "scripts/run_portfolio_optimal_oracle.py",
    "scripts/run_race_optimal_oracle.py",
    "scripts/run_resident_race_optimal_oracle.py",
    "scripts/run_universal_optimal_oracle.py",
    "scripts/run_universal_batch_oracle_corpus.py",
    "scripts/run_universal_oracle_cli.py",
    "scripts/run_universal_symmetry_oracle.py",
    "scripts/run_certificate_cache_inverse_closure.py",
    "scripts/run_certificate_cache_symmetry_closure.py",
    "scripts/run_learned_certificate_cache.py",
    "native/corner_pdb/corner_pdb.cpp",
    "native/edge_pdb/edge_pdb.cpp",
    "native/optimal_solver/optimal_solver.cpp",
    "native/h48_backend/h48_backend.c",
    "native/h48_backend/third_party/nissy_core/src/nissy.c",
]

REQUIRED_CLI_COMMANDS = ["scramble", "solve", "verify", "benchmark", "distance", "oracle", "tables"]
REQUIRED_STATUS_LABELS = ["exact", "non_exact", "lower_bound", "timeout", "not_applicable", "failed"]
REQUIRED_THESIS_SOLVERS = [
    "korf_ida_star_scoped",
    "kociemba_native_scoped",
    "kociemba_two_phase_adapter",
    "thistlethwaite_native_scoped",
]

REQUIRED_HANDOFF_DOCUMENTS = {
    "docs/final_metadata_packet.md": [
        "\\thesisStudentName",
        "\\thesisRegistrationNumber",
        "final_metadata_values.template.json",
        "scripts/apply_final_metadata.py",
        "final_supervisor_approval.md",
        "front_matter_placeholders: []",
        "final_submission_ready: true",
    ],
    "docs/supervisor_handoff_request.md": [
        "Student name in Greek",
        "Second committee member",
        "scripts/apply_final_metadata.py",
        "final_supervisor_approval.md",
        "latexmk -xelatex",
        "final_submission_ready: true",
    ],
    "docs/completion_audit_matrix.md": [
        "Remaining Missing or Externally Blocked Requirements",
        "Student identity metadata",
        "scripts/apply_final_metadata.py",
        "final_supervisor_approval.md",
        "front_matter_placeholders: []",
        "final_submission_ready: true",
    ],
}

SUPERVISOR_APPROVAL_RECORD = "docs/final_supervisor_approval.md"
REQUIRED_SUPERVISOR_APPROVAL_TERMS = [
    "approval_status: approved",
    "approval_source:",
    "approval_date:",
    "front-matter style approved",
    "bibliography style approved",
    "scoped solver claims approved",
]
SUPERVISOR_APPROVAL_PLACEHOLDER_PATTERN = re.compile(
    r"\b(TODO|TBD|PENDING|UNCONFIRMED|NEEDS_CONFIRMATION)\b|ΣΥΜΠΛΗΡΩΣ|ΕΚΚΡΕΜ",
    re.IGNORECASE,
)

FRONT_MATTER_PLACEHOLDER_PATTERNS = {
    "student_name": re.compile(r"ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ|STUDENT NAME, SURNAME"),
    "student_full_name": re.compile(r"ΟΝΟΜΑ ΕΠΩΝΥΜΟ ΤΟΥ ΠΑΤΡΩΝΥΜΟ"),
    "registration_number": re.compile(r"ΧΧΧΧΧΧΧ"),
    "supervisor_division": re.compile(r"ΤΟΜΕΑΣ ΕΠΙΒΛΕΠΟΝΤΟΣ"),
    "supervisor_laboratory": re.compile(r"ΕΡΓΑΣΤΗΡΙΟ ΕΠΙΒΛΕΠΟΝΤΟΣ"),
    "copyright_year": re.compile(r"20XX"),
    "place_date": re.compile(r"ΠΑΤΡΑ - ΜΗΝΑΣ (?:2026|ΕΤΟΣ)"),
    "exam_date": re.compile(r"……\.\.\./……\.\./(?:2026|………)"),
    "committee_member": re.compile(r"Όνομα Επώνυμο"),
    "division_director": re.compile(r"Ονοματεπώνυμο"),
    "rank_placeholder": re.compile(r"\bΒαθμίδα\b"),
}

SUPERVISOR_REQUIRED_FIELD_LABELS = {
    "student_name": "student display name",
    "student_full_name": "student full name with patronymic",
    "registration_number": "student registration number",
    "supervisor_division": "supervisor division",
    "supervisor_laboratory": "supervisor laboratory",
    "place_date": "place/month/year cover line",
    "exam_date": "public examination date",
    "copyright_year": "copyright year",
    "committee_member": "committee member name/title/department",
    "division_director": "division director name/title/signature details",
    "rank_placeholder": "academic rank/title",
}


def _run_text(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout


def _pdf_pages(pdf: Path) -> int | None:
    if not pdf.exists():
        return None
    output = _run_text(["pdfinfo", str(pdf)])
    if output is None:
        return None
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    return None


def _pdf_word_count(pdf: Path) -> int | None:
    if not pdf.exists():
        return None
    output = _run_text(["pdftotext", str(pdf), "-"])
    if output is None:
        return None
    return len(re.findall(r"[\wΆ-ώ]+", output, flags=re.UNICODE))


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_deliverable_audit(
    root_pdf: Path | None = None,
    thesis_pdf: Path | None = None,
    root: Path = ROOT,
) -> dict[str, object]:
    root_pdf = root_pdf or root / "main.pdf"
    thesis_pdf = thesis_pdf or root / "thesis" / "main.pdf"
    root_exists = root_pdf.exists()
    thesis_exists = thesis_pdf.exists()
    root_sha256 = _sha256(root_pdf)
    thesis_sha256 = _sha256(thesis_pdf)
    hashes_match = root_sha256 == thesis_sha256 if root_exists and thesis_exists else None
    passed = thesis_exists and (not root_exists or hashes_match is True)
    notes = []
    if root_exists and thesis_exists and hashes_match is False:
        notes.append("root main.pdf differs from thesis/main.pdf; copy the latest build output before auditing")
    elif not thesis_exists:
        notes.append("thesis/main.pdf is missing")
    elif not root_exists:
        notes.append("root main.pdf is absent; no duplicate build output to compare")
    else:
        notes.append("root main.pdf and thesis/main.pdf are byte-identical")

    return {
        "canonical_pdf": str(thesis_pdf.relative_to(root)) if thesis_pdf.is_relative_to(root) else str(thesis_pdf),
        "root_pdf": str(root_pdf.relative_to(root)) if root_pdf.is_relative_to(root) else str(root_pdf),
        "root_exists": root_exists,
        "thesis_exists": thesis_exists,
        "root_size_bytes": root_pdf.stat().st_size if root_exists else None,
        "thesis_size_bytes": thesis_pdf.stat().st_size if thesis_exists else None,
        "root_sha256": root_sha256,
        "thesis_sha256": thesis_sha256,
        "hashes_match": hashes_match,
        "passed": passed,
        "notes": notes,
    }


def _tex_files() -> list[Path]:
    return [THESIS / "main.tex"] + sorted((THESIS / "chapters").glob("*.tex"))


def _source_text() -> str:
    chunks = []
    for path in _tex_files():
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _source_word_count(text: str) -> int:
    stripped = re.sub(r"\\[a-zA-Z]+(\[[^\]]*\])?(\{[^}]*\})?", " ", text)
    stripped = re.sub(r"[{}$&_%#]", " ", stripped)
    return len(re.findall(r"[A-Za-zΑ-Ωα-ωΆ-ώ0-9]+", stripped, flags=re.UNICODE))


def _line_findings(pattern: re.Pattern[str], paths: list[Path], limit: int = 40) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                findings.append({
                    "path": str(path.relative_to(ROOT)),
                    "line": line_no,
                    "text": line.strip()[:220],
                })
                if len(findings) >= limit:
                    return findings
    return findings


def _repository_audit(root: Path = ROOT) -> dict[str, object]:
    missing = [relative for relative in REQUIRED_REPOSITORY_PATHS if not (root / relative).exists()]
    return {
        "required_count": len(REQUIRED_REPOSITORY_PATHS),
        "missing": missing,
        "passed": not missing,
    }


def _implementation_artifact_audit(root: Path = ROOT) -> dict[str, object]:
    missing = [relative for relative in REQUIRED_IMPLEMENTATION_PATHS if not (root / relative).exists()]
    source_chunks = []
    for relative in REQUIRED_IMPLEMENTATION_PATHS:
        path = root / relative
        if path.exists() and path.suffix == ".py":
            source_chunks.append(path.read_text(encoding="utf-8"))
    source_text = "\n".join(source_chunks)
    missing_status_labels = [label for label in REQUIRED_STATUS_LABELS if label not in source_text]
    checks = {
        "required_source_paths_present": not missing,
        "required_status_labels_present": not missing_status_labels,
    }
    return {
        "required_source_count": len(REQUIRED_IMPLEMENTATION_PATHS),
        "missing_source_paths": missing,
        "required_status_labels": REQUIRED_STATUS_LABELS,
        "missing_status_labels": missing_status_labels,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _cli_audit(help_text: str | None = None) -> dict[str, object]:
    output = help_text
    return_code: int | None = None
    if output is None:
        completed = subprocess.run(
            [sys.executable, "-m", "rubik_optimal.cli", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        return_code = completed.returncode
    missing = [command for command in REQUIRED_CLI_COMMANDS if command not in output]
    return {
        "required_commands": REQUIRED_CLI_COMMANDS,
        "missing_commands": missing,
        "return_code": return_code,
        "passed": not missing and (return_code in (None, 0)),
    }


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _git_provenance_audit(root: Path = ROOT) -> dict[str, object]:
    def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)

    inside = run_git(["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0:
        return {
            "inside_work_tree": False,
            "head_sha": None,
            "dirty_path_count": None,
            "dirty_paths_sample": [],
            "passed": False,
            "error": inside.stderr.strip() or inside.stdout.strip(),
        }
    head = run_git(["rev-parse", "HEAD"])
    status = run_git(["status", "--porcelain"])
    dirty_paths = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "inside_work_tree": True,
        "head_sha": head.stdout.strip() if head.returncode == 0 else None,
        "head_error": head.stderr.strip() if head.returncode != 0 else None,
        "dirty_path_count": len(dirty_paths),
        "dirty_paths_sample": dirty_paths[:40],
        "passed": head.returncode == 0 and status.returncode == 0 and not dirty_paths,
    }


def _source_state_label_is_reproducible(state: str) -> bool:
    return bool(state) and state != "git_unavailable" and not state.startswith("no_commit") and "+dirty" not in state


def _source_state_entries_from_payload(
    value: object,
    *,
    artifact: str,
    json_path: str = "$",
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if isinstance(value, dict):
        if "source_state" in value:
            state = str(value.get("source_state") or "")
            details = value.get("source_state_details")
            reproducible = value.get("source_snapshot_reproducible")
            limitation = str(value.get("source_snapshot_limitation") or "")
            if isinstance(details, dict):
                reproducible = details.get("is_reproducible_checkout", reproducible)
                limitation = str(details.get("limitation") or limitation)
            if reproducible is None:
                reproducible = _source_state_label_is_reproducible(state)
            entries.append({
                "artifact": artifact,
                "json_path": json_path,
                "source_state": state,
                "source_snapshot_reproducible": bool(reproducible),
                "source_snapshot_limitation": limitation,
            })
        for key, child in value.items():
            entries.extend(
                _source_state_entries_from_payload(child, artifact=artifact, json_path=f"{json_path}.{key}")
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            entries.extend(
                _source_state_entries_from_payload(child, artifact=artifact, json_path=f"{json_path}[{index}]")
            )
    return entries


def _source_state_audit(
    root: Path = ROOT,
    artifact_paths: list[Path] | None = None,
) -> dict[str, object]:
    """Check that generated metadata and the current tree are final-reproducible."""

    excluded_names = {"thesis_audit.json", "source_state_report.json"}
    paths = artifact_paths or [
        path
        for path in sorted((root / "results" / "processed").glob("*.json"))
        if path.name not in excluded_names
    ]
    current_source_state = capture_source_state(root)
    entries: list[dict[str, object]] = []
    unreadable: list[dict[str, object]] = []
    for path in paths:
        if not path.exists() or path.suffix != ".json":
            continue
        artifact = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unreadable.append({"artifact": artifact, "error": str(exc)})
            continue
        entries.extend(_source_state_entries_from_payload(payload, artifact=artifact))

    non_reproducible_entries = [
        entry for entry in entries if entry["source_snapshot_reproducible"] is not True
    ]
    current_reproducible = current_source_state["is_reproducible_checkout"] is True
    return {
        "current_source_state": current_source_state,
        "artifact_count_scanned": len(paths),
        "source_state_entry_count": len(entries),
        "non_reproducible_entry_count": len(non_reproducible_entries),
        "unique_non_reproducible_states": sorted({str(entry["source_state"]) for entry in non_reproducible_entries}),
        "non_reproducible_examples": non_reproducible_entries[:20],
        "unreadable_json": unreadable,
        "requires_clean_commit_or_archive_for_final_submission": True,
        "warning": (
            "Generated artifact metadata contains source states that cannot be reproduced by clean checkout."
            if non_reproducible_entries
            else (
                "Current checkout is not a reproducible clean source baseline."
                if not current_reproducible
                else ""
            )
        ),
        "regeneration_plan": [
            "Create an intentional commit or approved immutable source archive for the thesis baseline.",
            "Regenerate final metadata/result artifacts from that baseline.",
            "Rerun python scripts/source_state_report.py and python scripts/thesis_audit.py.",
        ],
        "passed": current_reproducible and not non_reproducible_entries and not unreadable,
    }


def _third_party_notice_audit(root: Path = ROOT) -> dict[str, object]:
    notice_path = root / "docs" / "THIRD_PARTY_NOTICES.md"
    vendored_license = root / "native" / "h48_backend" / "third_party" / "nissy_core" / "LICENSE"
    notice_text = notice_path.read_text(encoding="utf-8") if notice_path.exists() else ""
    required_terms = [
        "nissy-core",
        "GPL-3.0-or-later",
        "native/h48_backend/third_party/nissy_core/LICENSE",
        "public-solver-derived",
        "not original thesis algorithmic work",
    ]
    missing_terms = [term for term in required_terms if term not in notice_text]
    return {
        "path": "docs/THIRD_PARTY_NOTICES.md",
        "exists": notice_path.exists(),
        "vendored_license_exists": vendored_license.exists(),
        "missing_terms": missing_terms,
        "passed": notice_path.exists() and vendored_license.exists() and not missing_terms,
    }


def _topic_brief_artifact_audit(root: Path = ROOT) -> dict[str, object]:
    distance_path = root / "results" / "processed" / "distance_recognition_corpus_seed_2026_thesis_topic_brief_bullet2.json"
    heuristic_path = root / "results" / "processed" / "heuristic_comparison_seed_2026_thesis.json"
    heuristic_csv = root / "results" / "processed" / "heuristic_comparison_seed_2026_thesis.csv"
    heuristic_table = root / "thesis" / "tables" / "heuristic_comparison.tex"
    distance = _load_json(distance_path)
    heuristic = _load_json(heuristic_path)
    checks = {
        "distance_artifact_present": distance is not None,
        "distance_profile_is_thesis": bool(distance) and distance.get("profile") == "thesis",
        "distance_seed_is_2026": bool(distance) and distance.get("seed") == 2026,
        "distance_contains_exact": bool(distance) and distance.get("contains_live_exact") is True,
        "distance_contains_lower_bound": bool(distance) and distance.get("contains_lower_bound") is True,
        "distance_contains_invalid_state": bool(distance) and distance.get("contains_invalid_state") is True,
        "distance_keeps_hard_reference_saved": bool(distance)
        and distance.get("contains_saved_hard_reference") is True
        and distance.get("hard_search_started") is False,
        "heuristic_json_present": heuristic is not None,
        "heuristic_csv_present": heuristic_csv.exists() and heuristic_csv.stat().st_size > 0,
        "heuristic_table_present": heuristic_table.exists() and heuristic_table.stat().st_size > 0,
        "heuristic_profile_is_thesis": bool(heuristic) and heuristic.get("profile") == "thesis",
        "heuristic_seed_is_2026": bool(heuristic) and heuristic.get("seed") == 2026,
        "heuristic_a_star_variant_is_ida": bool(heuristic) and heuristic.get("a_star_variant") == "IDA*",
        "heuristic_admissibility_checked": bool(heuristic)
        and heuristic.get("all_exact_rows_admissible") is True
        and heuristic.get("all_combined_not_weaker_than_components") is True,
        "heuristic_uses_current_edge_pdb_bytes": bool(heuristic)
        and heuristic.get("edge_pdb_bytes") == (
            (_load_json(root / "results" / "processed" / "edge_pdb_metadata_seed_2026_thesis.json") or {}).get(
                "total_size_bytes"
            )
        ),
    }
    return {
        "distance_artifact": str(distance_path.relative_to(root)),
        "heuristic_artifact": str(heuristic_path.relative_to(root)),
        "heuristic_csv": str(heuristic_csv.relative_to(root)),
        "heuristic_table": str(heuristic_table.relative_to(root)),
        "distance_row_count": distance.get("row_count") if distance else None,
        "heuristic_case_count": heuristic.get("case_count") if heuristic else None,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _cloud_scope_drift_audit(root: Path = ROOT) -> dict[str, object]:
    """Classify cloud/H48H10-era artifacts without treating them as thesis-core gates."""

    processed_dir = root / "results" / "processed"
    runbook_dirs = sorted((root / "results").glob("cloud_hardtail_runbook*"))
    table_dir = root / "thesis" / "tables"
    docs_to_check = [
        root / "docs" / "scope_and_hardware_reality.md",
        root / "docs" / "limitations.md",
        root / "docs" / "final_audit.md",
        root / "docs" / "completion_audit_matrix.md",
    ]
    scope_terms = (
        "cloud_hardtail",
        "h48_fasttarget",
        "fasttarget",
        "h48h10",
        "h48h11",
        "noaws",
    )
    core_h48_terms = (
        "h48h0",
        "h48h7",
        "h48_oracle",
        "h48_capacity",
        "h48_generation_probe",
        "h48_resident",
        "h48_batch",
        "h48_trusted",
    )

    def has_scope_term(path: Path) -> bool:
        lowered = path.name.lower()
        return any(term in lowered for term in scope_terms)

    def has_core_term(path: Path) -> bool:
        lowered = path.name.lower()
        return any(term in lowered for term in core_h48_terms)

    processed_artifacts = [path for path in sorted(processed_dir.glob("*.json")) if has_scope_term(path)]
    thesis_tables = [path for path in sorted(table_dir.glob("*.tex")) if has_scope_term(path)]
    core_h48_tables = [path for path in sorted(table_dir.glob("*.tex")) if has_core_term(path) and not has_scope_term(path)]
    implementation_paths = [
        path
        for path in REQUIRED_IMPLEMENTATION_PATHS
        if any(term in path.lower() for term in ("cloud_hardtail", "h48_fasttarget"))
    ]
    required_generated = _generated_artifacts()["required_count"]
    required_generated_scope_paths = [
        relative
        for relative in (
            "results/processed/h48_capacity_seed_2026_thesis_lowload.json",
            "results/processed/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.json",
            "thesis/tables/h48_capacity_seed_2026_thesis_lowload.tex",
            "thesis/tables/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.tex",
        )
        if (root / relative).exists()
    ]
    docs_text = "\n".join(
        path.read_text(encoding="utf-8") for path in docs_to_check if path.exists()
    ).lower()
    documentation_checks = {
        "scope_note_exists": (root / "docs" / "scope_and_hardware_reality.md").exists(),
        "completion_gate_false_documented": "not a completion requirement" in docs_text
        or "never the completion gate" in docs_text,
        "h48h10_local_not_allowed_documented": "do not generate h48h10" in docs_text,
        "stretch_or_archive_documented": (
            "optional stretch" in docs_text
            or "archived stretch" in docs_text
            or "archived/stretch" in docs_text
        ),
    }
    return {
        "classification": "archived_stretch_or_negative_evidence",
        "completion_gate": False,
        "core_thesis_requirement": False,
        "destructive_cleanup_allowed": False,
        "artifact_deletion_recommended": False,
        "processed_artifact_count": len(processed_artifacts),
        "processed_artifact_examples": [
            str(path.relative_to(root)) for path in processed_artifacts[:20]
        ],
        "runbook_directory_count": len(runbook_dirs),
        "runbook_directory_examples": [
            str(path.relative_to(root)) for path in runbook_dirs[:10]
        ],
        "thesis_table_count": len(thesis_tables),
        "thesis_table_examples": [
            str(path.relative_to(root)) for path in thesis_tables[:20]
        ],
        "core_h48_table_count": len(core_h48_tables),
        "implementation_path_count": len(implementation_paths),
        "implementation_path_classification": "stretch/reproducibility harness, not topic-brief core solver",
        "implementation_path_examples": implementation_paths,
        "required_generated_artifact_count": required_generated,
        "required_generated_scope_paths": required_generated_scope_paths,
        "required_generated_scope_classification": (
            "capacity/probe guardrails only; not H48H10/H48H11 proof tables or completion gates"
        ),
        "documentation_checks": documentation_checks,
        "passed": all(documentation_checks.values()),
    }


def _backend_identity_audit(root: Path = ROOT) -> dict[str, object]:
    h48_h0 = _load_json(root / "results" / "processed" / "h48_metadata_seed_2026_thesis_h48h0.json")
    h48_h7 = _load_json(root / "results" / "processed" / "h48_metadata_seed_2026_thesis_h48h7.json")
    backend_source = root / "native" / "h48_backend" / "h48_backend.c"
    thesis_text = _source_text() if root == ROOT else ""
    metadata_checks = []
    for name, payload in (("h48h0", h48_h0), ("h48h7", h48_h7)):
        metadata_checks.append({
            "solver": name,
            "present": payload is not None,
            "backend_source": payload.get("backend_source") if payload else None,
            "license": payload.get("license") if payload else None,
            "passed": bool(payload)
            and payload.get("backend_source") == "vendored_nissy_core_h48"
            and payload.get("license") == "GPL-3.0-or-later",
        })
    source_text = backend_source.read_text(encoding="utf-8") if backend_source.exists() else ""
    checks = {
        "metadata_identifies_vendored_backend": all(row["passed"] for row in metadata_checks),
        "backend_wrapper_mentions_vendored_nissy": "vendored" in source_text and "nissy-core" in source_text,
        "thesis_mentions_vendored_h48_boundary": root != ROOT
        or ("vendored" in thesis_text and "H48" in thesis_text and "GPL" in thesis_text),
    }
    return {
        "metadata": metadata_checks,
        "backend_wrapper": "native/h48_backend/h48_backend.c",
        "checks": checks,
        "passed": all(checks.values()),
    }


def _solver_evidence_audit(
    summary_path: Path | None = None,
    pocket_path: Path | None = None,
    table_metadata_path: Path | None = None,
    corner_pdb_metadata_path: Path | None = None,
    edge_pdb_metadata_path: Path | None = None,
    h48_metadata_path: Path | None = None,
    h48_oracle_metadata_path: Path | None = None,
    e2e_path: Path | None = None,
    optimal_path: Path | None = None,
    stress_optimal_path: Path | None = None,
    h48_stress_path: Path | None = None,
    h48_oracle_stress_path: Path | None = None,
    h48_oracle_certification_path: Path | None = None,
    h48_batch_overhead_path: Path | None = None,
    h48_trusted_speedup_path: Path | None = None,
    h48_trusted_batch_overhead_path: Path | None = None,
    h48_oracle_cli_trusted_path: Path | None = None,
    h48_oracle_stream_trusted_path: Path | None = None,
    h48_resident_oracle_path: Path | None = None,
    h48_resident_certification_path: Path | None = None,
    fast_optimal_oracle_api_path: Path | None = None,
    nissy_core_direct_path: Path | None = None,
    portfolio_nissy_first_path: Path | None = None,
    portfolio_nissy_state_recovery_path: Path | None = None,
    portfolio_superflip_fallback_path: Path | None = None,
    portfolio_superflip_certificate_cache_path: Path | None = None,
    race_optimal_oracle_path: Path | None = None,
    resident_race_optimal_oracle_path: Path | None = None,
    universal_optimal_oracle_path: Path | None = None,
    universal_nissy_core_direct_path: Path | None = None,
    universal_h48_symmetry_path: Path | None = None,
    universal_batch_oracle_corpus_path: Path | None = None,
    universal_resident_h48_batch_path: Path | None = None,
    universal_oracle_cli_path: Path | None = None,
    universal_oracle_cli_broader_path: Path | None = None,
    universal_oracle_cli_adaptive_path: Path | None = None,
    universal_oracle_cli_expanded_path: Path | None = None,
    universal_oracle_cli_h48_symmetry_path: Path | None = None,
    universal_oracle_cli_h48_parallel_symmetry_path: Path | None = None,
    universal_oracle_cli_live_no_shortcuts_path: Path | None = None,
    universal_oracle_cli_live_no_shortcuts_broader_path: Path | None = None,
    universal_oracle_cli_known_distance_17_path: Path | None = None,
    universal_oracle_cli_known_distance_adaptive_path: Path | None = None,
    universal_oracle_cli_known_distance_19_path: Path | None = None,
    universal_oracle_cli_known_distance_20_path: Path | None = None,
    universal_oracle_cli_known_distance_20_offset1_path: Path | None = None,
    universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_path: Path | None = None,
    universal_symmetry_oracle_path: Path | None = None,
    certificate_cache_inverse_closure_path: Path | None = None,
    certificate_cache_symmetry_closure_path: Path | None = None,
    certificate_cache_expanded_symmetry_closure_path: Path | None = None,
    learned_certificate_cache_path: Path | None = None,
    h48_oracle_contract_path: Path | None = None,
    h48_capacity_path: Path | None = None,
    h48_generation_probe_path: Path | None = None,
    h48_oracle_certification_trusted_preload_path: Path | None = None,
) -> dict[str, object]:
    summary = _load_json(summary_path or ROOT / "results" / "processed" / "summary_seed_2026_thesis.json")
    pocket = _load_json(pocket_path or ROOT / "results" / "processed" / "pocket_cube_summary_seed_2026_thesis.json")
    table_metadata = _load_json(
        table_metadata_path or ROOT / "results" / "processed" / "table_metadata_thesis_seed_2026.json"
    )
    corner_pdb = _load_json(
        corner_pdb_metadata_path or ROOT / "results" / "processed" / "corner_pdb_metadata_seed_2026_thesis.json"
    )
    edge_pdb = _load_json(
        edge_pdb_metadata_path or ROOT / "results" / "processed" / "edge_pdb_metadata_seed_2026_thesis.json"
    )
    edge_cpdb = _load_json(ROOT / "results" / "processed" / "edge_cpdb_metadata_seed_2026_thesis.json")
    edge_cpdb_coverage = _load_json(
        ROOT / "results" / "processed" / "edge_pdb_coverage_seed_2026_thesis_cpdb_additive.json"
    )
    h48_metadata = _load_json(
        h48_metadata_path or ROOT / "results" / "processed" / "h48_metadata_seed_2026_thesis_h48h0.json"
    )
    h48_oracle_metadata = _load_json(
        h48_oracle_metadata_path or ROOT / "results" / "processed" / "h48_metadata_seed_2026_thesis_h48h7.json"
    )
    e2e = _load_json(e2e_path or ROOT / "results" / "processed" / "e2e_3x3_seed_2026_thesis.json")
    optimal = _load_json(
        optimal_path or ROOT / "results" / "processed" / "optimal_3x3_seed_2026_thesis.json"
    )
    stress_optimal = _load_json(
        stress_optimal_path or ROOT / "results" / "processed" / "optimal_3x3_seed_2026_stress.json"
    )
    h48_stress = _load_json(
        h48_stress_path or ROOT / "results" / "processed" / "optimal_3x3_seed_2026_stress_h48h0.json"
    )
    h48_oracle_stress = _load_json(
        h48_oracle_stress_path
        or ROOT / "results" / "processed" / "optimal_3x3_seed_2026_stress_h48h7_oracle.json"
    )
    h48_oracle_certification = _load_json(
        h48_oracle_certification_path
        or ROOT / "results" / "processed" / "h48_oracle_certification_seed_2026_thesis.json"
    )
    h48_batch_overhead = _load_json(
        h48_batch_overhead_path or ROOT / "results" / "processed" / "h48_batch_overhead_seed_2026_thesis.json"
    )
    h48_trusted_speedup = _load_json(
        h48_trusted_speedup_path
        or ROOT / "results" / "processed" / "h48_trusted_table_speedup_seed_2026_thesis_h48h7.json"
    )
    h48_trusted_batch_overhead = _load_json(
        h48_trusted_batch_overhead_path
        or ROOT / "results" / "processed" / "h48_batch_overhead_seed_2026_thesis_trusted.json"
    )
    h48_oracle_cli_trusted = _load_json(
        h48_oracle_cli_trusted_path
        or ROOT / "results" / "processed" / "h48_oracle_cli_seed_2026_thesis_trusted.json"
    )
    h48_oracle_stream_trusted = _load_json(
        h48_oracle_stream_trusted_path
        or ROOT / "results" / "processed" / "h48_oracle_stream_seed_2026_thesis_trusted.json"
    )
    h48_resident_oracle = _load_json(
        h48_resident_oracle_path
        or ROOT / "results" / "processed" / "h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json"
    )
    h48_resident_certification = _load_json(
        h48_resident_certification_path
        or ROOT
        / "results"
        / "processed"
        / "h48_resident_certification_seed_2026_thesis_h48h7_trusted.json"
    )
    h48_oracle_contract = _load_json(
        h48_oracle_contract_path
        or ROOT / "results" / "processed" / "h48_oracle_contract_seed_2026_thesis_h48h7.json"
    )
    h48_capacity = _load_json(
        h48_capacity_path
        or ROOT / "results" / "processed" / "h48_capacity_seed_2026_thesis_lowload.json"
    )
    h48_generation_probe = _load_json(
        h48_generation_probe_path
        or ROOT / "results" / "processed" / "h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.json"
    )
    fast_optimal_oracle_api = _load_json(
        fast_optimal_oracle_api_path
        or ROOT / "results" / "processed" / "fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json"
    )
    nissy_core_direct = _load_json(
        nissy_core_direct_path
        or ROOT / "results" / "processed" / "optimal_3x3_seed_2026_thesis_nissy_core_direct_lowload.json"
    )
    portfolio_nissy_first = _load_json(
        portfolio_nissy_first_path
        or ROOT / "results" / "processed" / "portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json"
    )
    portfolio_nissy_state_recovery = _load_json(
        portfolio_nissy_state_recovery_path
        or ROOT
        / "results"
        / "processed"
        / "portfolio_optimal_oracle_seed_2026_thesis_nissy_state_recovery_lowload.json"
    )
    portfolio_nissy_core_direct_state = _load_json(
        ROOT
        / "results"
        / "processed"
        / "portfolio_optimal_oracle_seed_2026_thesis_nissy_core_direct_state_lowload.json"
    )
    portfolio_superflip_fallback = _load_json(
        portfolio_superflip_fallback_path
        or ROOT
        / "results"
        / "processed"
        / "portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json"
    )
    portfolio_superflip_certificate_cache = _load_json(
        portfolio_superflip_certificate_cache_path
        or ROOT
        / "results"
        / "processed"
        / "portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json"
    )
    race_optimal_oracle = _load_json(
        race_optimal_oracle_path
        or ROOT / "results" / "processed" / "race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json"
    )
    race_nissy_core_direct = _load_json(
        ROOT
        / "results"
        / "processed"
        / "race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json"
    )
    resident_race_optimal_oracle = _load_json(
        resident_race_optimal_oracle_path
        or ROOT
        / "results"
        / "processed"
        / "resident_race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json"
    )
    resident_race_nissy_core_direct = _load_json(
        ROOT
        / "results"
        / "processed"
        / "resident_race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json"
    )
    universal_optimal_oracle = _load_json(
        universal_optimal_oracle_path
        or ROOT
        / "results"
        / "processed"
        / "universal_optimal_oracle_seed_2026_thesis_h48h7_lowload.json"
    )
    universal_nissy_core_direct = _load_json(
        universal_nissy_core_direct_path
        or ROOT
        / "results"
        / "processed"
        / "universal_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json"
    )
    universal_h48_symmetry = _load_json(
        universal_h48_symmetry_path
        or ROOT
        / "results"
        / "processed"
        / "universal_optimal_oracle_seed_2026_thesis_h48h7_h48_symmetry_lowload.json"
    )
    universal_batch_oracle_corpus = _load_json(
        universal_batch_oracle_corpus_path
        or ROOT
        / "results"
        / "processed"
        / "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_batch_lowload.json"
    )
    universal_resident_h48_batch = _load_json(
        universal_resident_h48_batch_path
        or ROOT
        / "results"
        / "processed"
        / "universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json"
    )
    universal_oracle_cli = _load_json(
        universal_oracle_cli_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_optimized_lowload.json"
    )
    universal_oracle_cli_broader = _load_json(
        universal_oracle_cli_broader_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_broader_lowload.json"
    )
    universal_oracle_cli_adaptive = _load_json(
        universal_oracle_cli_adaptive_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_adaptive_lowload.json"
    )
    universal_oracle_cli_expanded = _load_json(
        universal_oracle_cli_expanded_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json"
    )
    universal_oracle_cli_h48_symmetry = _load_json(
        universal_oracle_cli_h48_symmetry_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_h48_symmetry_lowload.json"
    )
    universal_oracle_cli_h48_parallel_symmetry = _load_json(
        universal_oracle_cli_h48_parallel_symmetry_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_h48_parallel_symmetry_lowload.json"
    )
    universal_oracle_cli_live_no_shortcuts = _load_json(
        universal_oracle_cli_live_no_shortcuts_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_lowload.json"
    )
    universal_oracle_cli_live_no_shortcuts_broader = _load_json(
        universal_oracle_cli_live_no_shortcuts_broader_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_broader_lowload.json"
    )
    universal_oracle_cli_known_distance_17 = _load_json(
        universal_oracle_cli_known_distance_17_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_no_shortcuts_lowload.json"
    )
    universal_oracle_cli_known_distance_adaptive = _load_json(
        universal_oracle_cli_known_distance_adaptive_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_18_adaptive_symmetry_lowload.json"
    )
    universal_oracle_cli_known_distance_19 = _load_json(
        universal_oracle_cli_known_distance_19_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_19_adaptive_symmetry_lowload.json"
    )
    universal_oracle_cli_known_distance_20 = _load_json(
        universal_oracle_cli_known_distance_20_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_adaptive_symmetry_lowload.json"
    )
    universal_oracle_cli_known_distance_20_offset1 = _load_json(
        universal_oracle_cli_known_distance_20_offset1_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_adaptive_symmetry_lowload.json"
    )
    universal_oracle_cli_known_distance_20_offset1_trimmed_prepass = _load_json(
        universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_path
        or ROOT
        / "results"
        / "processed"
        / "universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.json"
    )
    universal_symmetry_oracle = _load_json(
        universal_symmetry_oracle_path
        or ROOT
        / "results"
        / "processed"
        / "universal_symmetry_oracle_seed_2026_thesis_h48h7_lowload.json"
    )
    certificate_cache_inverse_closure = _load_json(
        certificate_cache_inverse_closure_path
        or ROOT
        / "results"
        / "processed"
        / "certificate_cache_inverse_closure_seed_2026_thesis_h48h7_lowload.json"
    )
    certificate_cache_symmetry_closure = _load_json(
        certificate_cache_symmetry_closure_path
        or ROOT
        / "results"
        / "processed"
        / "certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_lowload.json"
    )
    certificate_cache_expanded_symmetry_closure = _load_json(
        certificate_cache_expanded_symmetry_closure_path
        or ROOT
        / "results"
        / "processed"
        / "certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_expanded_default_lowload.json"
    )
    learned_certificate_cache = _load_json(
        learned_certificate_cache_path
        or ROOT
        / "results"
        / "processed"
        / "learned_certificate_cache_seed_2026_thesis_h48h7_lowload.json"
    )
    h48_oracle_certification_trusted_preload = _load_json(
        h48_oracle_certification_trusted_preload_path
        or ROOT
        / "results"
        / "processed"
        / "h48_oracle_certification_seed_2026_thesis_trusted_preload.json"
    )

    solvers = summary.get("solvers", {}) if summary else {}
    missing_solvers = [solver for solver in REQUIRED_THESIS_SOLVERS if solver not in solvers]
    non_applicable_primary = [
        solver for solver in ("kociemba_native_scoped", "thistlethwaite_native_scoped")
        if solver in solvers and solvers[solver].get("statuses") == ["not_applicable"]
    ]

    native_kociemba_verified = int(solvers.get("kociemba_native_scoped", {}).get("verified_solutions", 0) or 0)
    native_thistle_verified = int(solvers.get("thistlethwaite_native_scoped", {}).get("verified_solutions", 0) or 0)
    korf_statuses = set(solvers.get("korf_ida_star_scoped", {}).get("statuses", []))
    table_rows = table_metadata.get("tables", []) if table_metadata else []
    corner_pdb_path = ROOT / str(corner_pdb.get("file_path", "")) if corner_pdb else None
    edge_pdb_subsets = edge_pdb.get("subsets", []) if edge_pdb else []
    edge_pdb_paths = [ROOT / str(subset.get("file_path", "")) for subset in edge_pdb_subsets]
    edge_pdb_binary_size = (
        sum(path.stat().st_size for path in edge_pdb_paths if path.exists()) if edge_pdb_paths else None
    )
    edge_cpdb_subsets = edge_cpdb.get("subsets", []) if edge_cpdb else []
    edge_cpdb_paths = [ROOT / str(subset.get("file_path", "")) for subset in edge_cpdb_subsets]
    h48_path = ROOT / str(h48_metadata.get("file_path", "")) if h48_metadata else None
    h48_oracle_path = ROOT / str(h48_oracle_metadata.get("file_path", "")) if h48_oracle_metadata else None
    pocket_distribution = pocket.get("distribution", {}) if pocket else {}
    pocket_representatives = pocket.get("representative_solutions", []) if pocket else []
    e2e_rows = e2e.get("rows", []) if e2e else []
    optimal_rows = optimal.get("rows", []) if optimal else []
    optimal_native_solver_rows = [
        row
        for row in optimal_rows
        if not str(row.get("solver", "")).startswith(("h48_", "nissy_"))
    ]
    stress_optimal_rows = stress_optimal.get("rows", []) if stress_optimal else []
    h48_stress_rows = h48_stress.get("rows", []) if h48_stress else []
    h48_oracle_stress_rows = h48_oracle_stress.get("rows", []) if h48_oracle_stress else []
    h48_oracle_certification_rows = h48_oracle_certification.get("rows", []) if h48_oracle_certification else []
    h48_batch_rows = h48_batch_overhead.get("batch_rows", []) if h48_batch_overhead else []
    h48_trusted_batch_rows = (
        h48_trusted_batch_overhead.get("batch_rows", []) if h48_trusted_batch_overhead else []
    )
    h48_oracle_cli_trusted_rows = h48_oracle_cli_trusted.get("rows", []) if h48_oracle_cli_trusted else []
    h48_oracle_stream_trusted_rows = (
        h48_oracle_stream_trusted.get("rows", []) if h48_oracle_stream_trusted else []
    )
    h48_resident_rows = h48_resident_oracle.get("resident_rows", []) if h48_resident_oracle else []
    h48_resident_certification_rows = (
        h48_resident_certification.get("rows", []) if h48_resident_certification else []
    )
    fast_optimal_oracle_api_rows = fast_optimal_oracle_api.get("rows", []) if fast_optimal_oracle_api else []
    nissy_core_direct_rows = nissy_core_direct.get("rows", []) if nissy_core_direct else []
    portfolio_nissy_first_rows = portfolio_nissy_first.get("rows", []) if portfolio_nissy_first else []
    portfolio_nissy_state_recovery_rows = (
        portfolio_nissy_state_recovery.get("rows", []) if portfolio_nissy_state_recovery else []
    )
    portfolio_nissy_core_direct_state_rows = (
        portfolio_nissy_core_direct_state.get("rows", []) if portfolio_nissy_core_direct_state else []
    )
    portfolio_superflip_fallback_rows = (
        portfolio_superflip_fallback.get("rows", []) if portfolio_superflip_fallback else []
    )
    portfolio_superflip_certificate_cache_rows = (
        portfolio_superflip_certificate_cache.get("rows", []) if portfolio_superflip_certificate_cache else []
    )
    race_optimal_oracle_rows = race_optimal_oracle.get("rows", []) if race_optimal_oracle else []
    race_nissy_core_direct_rows = (
        race_nissy_core_direct.get("rows", []) if race_nissy_core_direct else []
    )
    resident_race_optimal_oracle_rows = (
        resident_race_optimal_oracle.get("rows", []) if resident_race_optimal_oracle else []
    )
    resident_race_nissy_core_direct_rows = (
        resident_race_nissy_core_direct.get("rows", []) if resident_race_nissy_core_direct else []
    )
    universal_optimal_oracle_rows = (
        universal_optimal_oracle.get("rows", []) if universal_optimal_oracle else []
    )
    universal_nissy_core_direct_rows = (
        universal_nissy_core_direct.get("rows", []) if universal_nissy_core_direct else []
    )
    universal_h48_symmetry_rows = (
        universal_h48_symmetry.get("rows", []) if universal_h48_symmetry else []
    )
    universal_batch_oracle_corpus_rows = (
        universal_batch_oracle_corpus.get("rows", []) if universal_batch_oracle_corpus else []
    )
    universal_resident_h48_batch_rows = (
        universal_resident_h48_batch.get("rows", []) if universal_resident_h48_batch else []
    )
    universal_oracle_cli_rows = universal_oracle_cli.get("rows", []) if universal_oracle_cli else []
    universal_oracle_cli_broader_rows = (
        universal_oracle_cli_broader.get("rows", []) if universal_oracle_cli_broader else []
    )
    universal_oracle_cli_adaptive_rows = (
        universal_oracle_cli_adaptive.get("rows", []) if universal_oracle_cli_adaptive else []
    )
    universal_oracle_cli_expanded_rows = (
        universal_oracle_cli_expanded.get("rows", []) if universal_oracle_cli_expanded else []
    )
    universal_oracle_cli_h48_symmetry_rows = (
        universal_oracle_cli_h48_symmetry.get("rows", []) if universal_oracle_cli_h48_symmetry else []
    )
    universal_oracle_cli_h48_parallel_symmetry_rows = (
        universal_oracle_cli_h48_parallel_symmetry.get("rows", [])
        if universal_oracle_cli_h48_parallel_symmetry
        else []
    )
    universal_oracle_cli_live_no_shortcuts_rows = (
        universal_oracle_cli_live_no_shortcuts.get("rows", [])
        if universal_oracle_cli_live_no_shortcuts
        else []
    )
    universal_oracle_cli_live_no_shortcuts_broader_rows = (
        universal_oracle_cli_live_no_shortcuts_broader.get("rows", [])
        if universal_oracle_cli_live_no_shortcuts_broader
        else []
    )
    universal_oracle_cli_known_distance_17_rows = (
        universal_oracle_cli_known_distance_17.get("rows", [])
        if universal_oracle_cli_known_distance_17
        else []
    )
    universal_oracle_cli_known_distance_adaptive_rows = (
        universal_oracle_cli_known_distance_adaptive.get("rows", [])
        if universal_oracle_cli_known_distance_adaptive
        else []
    )
    universal_oracle_cli_known_distance_19_rows = (
        universal_oracle_cli_known_distance_19.get("rows", [])
        if universal_oracle_cli_known_distance_19
        else []
    )
    universal_oracle_cli_known_distance_20_rows = (
        universal_oracle_cli_known_distance_20.get("rows", [])
        if universal_oracle_cli_known_distance_20
        else []
    )
    universal_oracle_cli_known_distance_20_offset1_rows = (
        universal_oracle_cli_known_distance_20_offset1.get("rows", [])
        if universal_oracle_cli_known_distance_20_offset1
        else []
    )
    universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_rows = (
        universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("rows", [])
        if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
        else []
    )
    universal_symmetry_oracle_rows = (
        universal_symmetry_oracle.get("rows", []) if universal_symmetry_oracle else []
    )
    certificate_cache_inverse_closure_rows = (
        certificate_cache_inverse_closure.get("rows", []) if certificate_cache_inverse_closure else []
    )
    certificate_cache_symmetry_closure_rows = (
        certificate_cache_symmetry_closure.get("rows", []) if certificate_cache_symmetry_closure else []
    )
    certificate_cache_expanded_symmetry_closure_rows = (
        certificate_cache_expanded_symmetry_closure.get("rows", [])
        if certificate_cache_expanded_symmetry_closure
        else []
    )
    learned_certificate_cache_rows = (
        learned_certificate_cache.get("rows", []) if learned_certificate_cache else []
    )
    h48_oracle_certification_trusted_preload_rows = (
        h48_oracle_certification_trusted_preload.get("rows", [])
        if h48_oracle_certification_trusted_preload
        else []
    )
    h48_capacity_build_plan = h48_capacity.get("h48_stronger_table_build_plan", []) if h48_capacity else []
    h48_capacity_gate = h48_capacity.get("all_state_fast_oracle_completion_gate", {}) if h48_capacity else {}
    h48_contract_cloud_runtime_proof = (
        h48_oracle_contract.get("cloud_runtime_proof", {}) if h48_oracle_contract else {}
    )
    h48_contract_fast_runtime_flag_valid = (
        not h48_oracle_contract
        or h48_oracle_contract.get("fast_runtime_proven_for_every_possible_state") is False
        or h48_contract_cloud_runtime_proof.get("passed") is True
    )

    checks = {
        "summary_profile_is_thesis": bool(summary) and summary.get("profile") == "thesis",
        "summary_seed_is_2026": bool(summary) and summary.get("seed") == 2026,
        "required_solvers_present": not missing_solvers,
        "primary_native_solvers_not_not_applicable": not non_applicable_primary,
        "native_kociemba_has_verified_solution": native_kociemba_verified > 0,
        "native_thistlethwaite_has_verified_solution": native_thistle_verified > 0,
        "korf_has_exact_evidence": "exact" in korf_statuses,
        "table_metadata_profile_is_thesis": bool(table_metadata) and table_metadata.get("profile") == "thesis",
        "generated_table_count_met": len(table_rows) >= 12,
        "corner_pdb_profile_is_thesis": bool(corner_pdb) and corner_pdb.get("profile") == "thesis",
        "corner_pdb_complete_state_count_met": (
            bool(corner_pdb)
            and corner_pdb.get("complete") is True
            and corner_pdb.get("state_count") == corner_pdb.get("visited_states") == 88_179_840
        ),
        "corner_pdb_binary_present": bool(corner_pdb_path) and corner_pdb_path.exists(),
        "corner_pdb_binary_size_met": bool(corner_pdb_path) and corner_pdb_path.exists()
        and corner_pdb_path.stat().st_size == int(corner_pdb.get("size_bytes", -1)),
        "edge_pdb_profile_is_thesis": bool(edge_pdb) and edge_pdb.get("profile") == "thesis",
        "edge_pdb_complete_state_count_met": (
            bool(edge_pdb)
            and edge_pdb.get("complete") is True
            and len(edge_pdb_subsets) >= 8
            and edge_pdb.get("total_state_count") == 42_577_920 * len(edge_pdb_subsets)
            and all(subset.get("visited_states") == 42_577_920 for subset in edge_pdb_subsets)
        ),
        "edge_pdb_binaries_present": bool(edge_pdb_paths) and all(path.exists() for path in edge_pdb_paths),
        "edge_pdb_binary_size_met": bool(edge_pdb_paths) and all(path.exists() for path in edge_pdb_paths)
        and sum(path.stat().st_size for path in edge_pdb_paths) == int(edge_pdb.get("total_size_bytes", -1)),
        "edge_cpdb_profile_is_thesis": bool(edge_cpdb) and edge_cpdb.get("profile") == "thesis",
        "edge_cpdb_complete_state_count_met": (
            bool(edge_cpdb)
            and edge_cpdb.get("complete") is True
            and edge_cpdb.get("cost_partitioned") is True
            and edge_cpdb.get("total_state_count") == 42_577_920 * len(edge_cpdb_subsets)
            and all(subset.get("visited_states") == 42_577_920 for subset in edge_cpdb_subsets)
        ),
        "edge_cpdb_binaries_present": bool(edge_cpdb_paths) and all(path.exists() for path in edge_cpdb_paths),
        "edge_cpdb_binary_size_met": bool(edge_cpdb_paths) and all(path.exists() for path in edge_cpdb_paths)
        and sum(path.stat().st_size for path in edge_cpdb_paths) == int(edge_cpdb.get("total_size_bytes", -1)),
        "edge_cpdb_coverage_valid_if_present": (
            edge_cpdb_coverage is None
            or (
                edge_cpdb_coverage.get("passed") is True
                and edge_cpdb_coverage.get("all_combined_not_weaker") is True
                and edge_cpdb_coverage.get("additive_cost_partition_count") == len(edge_cpdb_subsets)
            )
        ),
        "h48_backend_metadata_present": bool(h48_metadata),
        "h48_backend_is_in_repo_vendored": bool(h48_metadata)
        and h48_metadata.get("backend_source") == "vendored_nissy_core_h48"
        and h48_metadata.get("license") == "GPL-3.0-or-later",
        "h48_backend_table_present": bool(h48_path) and h48_path.exists(),
        "h48_backend_table_size_recorded": bool(h48_metadata)
        and bool(h48_path)
        and h48_path.exists()
        and h48_path.stat().st_size == int(h48_metadata.get("table_size_bytes", -1)),
        "h48_oracle_metadata_valid_if_present": not h48_oracle_metadata
        or (
            h48_oracle_metadata.get("solver") == "h48h7"
            and h48_oracle_metadata.get("h_value") == 7
            and h48_oracle_metadata.get("oracle_grade") is True
            and bool(h48_oracle_path)
            and h48_oracle_path.exists()
            and h48_oracle_path.stat().st_size == int(h48_oracle_metadata.get("table_size_bytes", -1))
            and h48_oracle_metadata.get("estimated_size_matches_actual") is True
        ),
        "e2e_3x3_profile_is_thesis": bool(e2e) and e2e.get("profile") == "thesis",
        "e2e_3x3_passed": bool(e2e) and e2e.get("passed") is True,
        "e2e_3x3_has_sequence_and_facelet_inputs": bool(e2e_rows)
        and {"sequence", "facelets"}.issubset({str(row.get("input_kind")) for row in e2e_rows}),
        "optimal_3x3_profile_is_thesis": bool(optimal) and optimal.get("profile") == "thesis",
        "optimal_3x3_backend_is_native": bool(optimal) and optimal.get("backend") == "native",
        "optimal_3x3_rows_are_native": bool(optimal_rows) and len(optimal_native_solver_rows) == len(optimal_rows),
        "optimal_3x3_all_recorded_rows_exact": bool(optimal) and optimal.get("all_exact") is True,
        "optimal_3x3_has_random_15_exact": bool(optimal_rows)
        and any(row.get("case_id") == "random_2_15" and row.get("status") == "exact" for row in optimal_rows),
        "external_or_certified_optimal_stress_valid_if_present": not stress_optimal
        or (
            stress_optimal.get("profile") == "stress"
            and stress_optimal.get("all_exact") is True
            and (
                stress_optimal.get("backend") == "nissy-light"
                or (
                    stress_optimal.get("backend") == "native"
                    and stress_optimal.get("nissy_heuristic") is True
                    and stress_optimal.get("nissy_certificate") is True
                )
            )
            and any(
                row.get("case_id") == "random_3_20"
                and row.get("status") == "exact"
                and row.get("solution_length") == 17
                and row.get("verified") is True
                and (
                    stress_optimal.get("backend") == "nissy-light"
                    or "exact_certified_by_upper_bound=True" in str(row.get("notes", ""))
                )
                for row in stress_optimal_rows
            )
        ),
        "h48_native_stress_valid": bool(h48_stress)
        and h48_stress.get("profile") == "stress"
        and h48_stress.get("backend") == "h48-native"
        and h48_stress.get("h48_solver") == "h48h0"
        and h48_stress.get("all_exact") is True
        and any(
            row.get("case_id") == "random_3_20"
            and row.get("status") == "exact"
            and row.get("solution_length") == 17
            and row.get("verified") is True
            for row in h48_stress_rows
        ),
        "h48_oracle_stress_valid_if_present": not h48_oracle_stress
        or (
            h48_oracle_stress.get("profile") == "stress"
            and h48_oracle_stress.get("backend") == "h48-native"
            and h48_oracle_stress.get("h48_solver") == "h48h7"
            and h48_oracle_stress.get("all_exact") is True
            and len(h48_oracle_stress_rows) >= 15
            and any(
                row.get("case_id") == "random_3_20"
                and row.get("status") == "exact"
                and row.get("solution_length") == 17
                and row.get("verified") is True
                for row in h48_oracle_stress_rows
            )
            and all(row.get("status") == "exact" and row.get("verified") is True for row in h48_oracle_stress_rows)
        ),
        "h48_oracle_certification_valid_if_present": not h48_oracle_certification
        or (
            h48_oracle_certification.get("profile") == "thesis"
            and h48_oracle_certification.get("solver") == "h48h7"
            and h48_oracle_certification.get("all_exact") is True
            and h48_oracle_certification.get("all_expected_distances_match") is True
            and h48_oracle_certification.get("within_runtime_target") is True
            and len(h48_oracle_certification_rows) >= 4
            and any(
                row.get("case_id") == "superflip_distance_20"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                and row.get("expected_distance_matches") is True
                for row in h48_oracle_certification_rows
            )
            and all(row.get("status") == "exact" and row.get("verified") is True for row in h48_oracle_certification_rows)
        ),
        "h48_batch_overhead_valid_if_present": not h48_batch_overhead
        or (
            h48_batch_overhead.get("profile") == "thesis"
            and h48_batch_overhead.get("solver") == "h48h7"
            and h48_batch_overhead.get("passed") is True
            and int(h48_batch_overhead.get("repetitions", 0) or 0) >= 12
            and float(h48_batch_overhead.get("throughput_speedup", 0.0) or 0.0) >= 10.0
            and h48_batch_overhead.get("sequential_exact_count") == h48_batch_overhead.get("repetitions")
            and h48_batch_overhead.get("batch_exact_count") == h48_batch_overhead.get("repetitions")
            and all(row.get("status") == "exact" and row.get("is_verified") is True for row in h48_batch_rows)
        ),
        "h48_trusted_speedup_valid_if_present": not h48_trusted_speedup
        or (
            h48_trusted_speedup.get("profile") == "thesis"
            and h48_trusted_speedup.get("solver") == "h48h7"
            and h48_trusted_speedup.get("passed") is True
            and int(h48_trusted_speedup.get("repetitions", 0) or 0) >= 4
            and h48_trusted_speedup.get("checked_exact_count") == h48_trusted_speedup.get("repetitions")
            and h48_trusted_speedup.get("trusted_exact_count") == h48_trusted_speedup.get("repetitions")
            and float(h48_trusted_speedup.get("trusted_speedup", 0.0) or 0.0) >= 10.0
        ),
        "h48_trusted_batch_overhead_valid_if_present": not h48_trusted_batch_overhead
        or (
            h48_trusted_batch_overhead.get("profile") == "thesis"
            and h48_trusted_batch_overhead.get("solver") == "h48h7"
            and h48_trusted_batch_overhead.get("trusted_table") is True
            and h48_trusted_batch_overhead.get("passed") is True
            and int(h48_trusted_batch_overhead.get("repetitions", 0) or 0) >= 12
            and float(h48_trusted_batch_overhead.get("throughput_speedup", 0.0) or 0.0) >= 10.0
            and h48_trusted_batch_overhead.get("sequential_exact_count")
            == h48_trusted_batch_overhead.get("repetitions")
            and h48_trusted_batch_overhead.get("batch_exact_count")
            == h48_trusted_batch_overhead.get("repetitions")
            and all(row.get("status") == "exact" and row.get("is_verified") is True for row in h48_trusted_batch_rows)
        ),
        "h48_oracle_cli_trusted_valid_if_present": not h48_oracle_cli_trusted
        or (
            h48_oracle_cli_trusted.get("profile") == "thesis"
            and h48_oracle_cli_trusted.get("solver") == "h48h7"
            and h48_oracle_cli_trusted.get("trusted_table") is True
            and h48_oracle_cli_trusted.get("passed") is True
            and h48_oracle_cli_trusted.get("all_exact") is True
            and h48_oracle_cli_trusted.get("all_verified") is True
            and int(h48_oracle_cli_trusted.get("input_count", 0) or 0) >= 4
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in h48_oracle_cli_trusted_rows
            )
        ),
        "h48_oracle_stream_trusted_valid_if_present": not h48_oracle_stream_trusted
        or (
            h48_oracle_stream_trusted.get("profile") == "thesis"
            and h48_oracle_stream_trusted.get("solver") == "h48h7"
            and h48_oracle_stream_trusted.get("trusted_table") is True
            and h48_oracle_stream_trusted.get("passed") is True
            and h48_oracle_stream_trusted.get("all_exact") is True
            and h48_oracle_stream_trusted.get("all_verified") is True
            and int(h48_oracle_stream_trusted.get("input_count", 0) or 0) >= 4
            and int(h48_oracle_stream_trusted.get("row_count", 0) or 0)
            == int(h48_oracle_stream_trusted.get("input_count", -1) or -1)
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in h48_oracle_stream_trusted_rows
            )
            and any(
                "resident in-repo native H48 backend" in str(row.get("notes", ""))
                for row in h48_oracle_stream_trusted_rows
                if row.get("distance") != 0
            )
        ),
        "h48_resident_oracle_valid_if_present": not h48_resident_oracle
        or (
            h48_resident_oracle.get("profile") == "thesis"
            and h48_resident_oracle.get("solver") == "h48h7"
            and h48_resident_oracle.get("trusted_table") is True
            and h48_resident_oracle.get("passed") is True
            and int(h48_resident_oracle.get("resident_exact_count", 0) or 0)
            == int(h48_resident_oracle.get("repetitions", -1) or -1)
            and float(h48_resident_oracle.get("resident_speedup", 0.0) or 0.0) >= 10.0
            and all(row.get("status") == "exact" and row.get("is_verified") is True for row in h48_resident_rows)
        ),
        "h48_resident_certification_valid_if_present": not h48_resident_certification
        or (
            h48_resident_certification.get("profile") == "thesis"
            and h48_resident_certification.get("solver") == "h48h7"
            and h48_resident_certification.get("trusted_table") is True
            and h48_resident_certification.get("passed") is True
            and h48_resident_certification.get("all_exact") is True
            and h48_resident_certification.get("all_hard_cases_exact") is True
            and h48_resident_certification.get("all_expected_distances_match") is True
            and h48_resident_certification.get("within_runtime_target") is True
            and len(h48_resident_certification_rows) >= 4
            and any(
                row.get("case_id") == "superflip_distance_20"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                for row in h48_resident_certification_rows
            )
            and any(
                row.get("case_id") == "deterministic_depth_25"
                and row.get("status") == "exact"
                and row.get("verified") is True
                for row in h48_resident_certification_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in h48_resident_certification_rows
            )
            and any(
                "resident in-repo native H48 backend" in str(row.get("notes", ""))
                for row in h48_resident_certification_rows
                if row.get("solution_length") != 0
            )
        ),
        "fast_optimal_oracle_api_valid_if_present": not fast_optimal_oracle_api
        or (
            fast_optimal_oracle_api.get("profile") == "thesis"
            and fast_optimal_oracle_api.get("api_class") == "FastOptimalOracle"
            and fast_optimal_oracle_api.get("solver") == "h48h7"
            and fast_optimal_oracle_api.get("trusted_table") is True
            and fast_optimal_oracle_api.get("passed") is True
            and fast_optimal_oracle_api.get("all_exact") is True
            and fast_optimal_oracle_api.get("all_verified") is True
            and fast_optimal_oracle_api.get("all_under_runtime_target") is True
            and fast_optimal_oracle_api.get("fast_optimal_oracle_implemented_for_every_valid_3x3_state") is True
            and fast_optimal_oracle_api.get("fast_runtime_proven_for_every_possible_state") is False
            and len(fast_optimal_oracle_api_rows) >= 4
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in fast_optimal_oracle_api_rows
            )
        ),
        "nissy_core_direct_valid_if_present": not nissy_core_direct
        or (
            nissy_core_direct.get("profile") == "thesis"
            and nissy_core_direct.get("backend") == "nissy-core-direct"
            and nissy_core_direct.get("h48_solver") == "h48h7"
            and nissy_core_direct.get("all_exact") is True
            and len(nissy_core_direct_rows) >= 4
            and all(
                row.get("status") == "exact"
                and row.get("verified") is True
                and "input_mode=cube_state" in str(row.get("notes", ""))
                for row in nissy_core_direct_rows
            )
        ),
        "portfolio_nissy_first_valid_if_present": not portfolio_nissy_first
        or (
            portfolio_nissy_first.get("profile") == "thesis"
            and portfolio_nissy_first.get("case_set") == "thesis"
            and portfolio_nissy_first.get("passed") is True
            and portfolio_nissy_first.get("all_exact") is True
            and any(
                str(backend).startswith("nissy-optimal")
                for backend in portfolio_nissy_first.get("selected_backends", [])
            )
            and len(portfolio_nissy_first_rows) >= 5
            and any(
                row.get("case_id") == "random_3_20"
                and str(row.get("selected_backend", "")).startswith("nissy-optimal")
                and row.get("status") == "exact"
                and row.get("solution_length") == 17
                and row.get("verified") is True
                for row in portfolio_nissy_first_rows
            )
            and all(row.get("status") == "exact" and row.get("verified") is True for row in portfolio_nissy_first_rows)
        ),
        "portfolio_nissy_state_recovery_valid_if_present": not portfolio_nissy_state_recovery
        or (
            portfolio_nissy_state_recovery.get("profile") == "thesis"
            and portfolio_nissy_state_recovery.get("case_set") == "thesis"
            and portfolio_nissy_state_recovery.get("state_input_only") is True
            and portfolio_nissy_state_recovery.get("certificate_cache_enabled") is False
            and portfolio_nissy_state_recovery.get("upper_lower_certificate_enabled") is False
            and portfolio_nissy_state_recovery.get("passed") is True
            and portfolio_nissy_state_recovery.get("all_exact") is True
            and any(
                str(backend).startswith("nissy-optimal")
                for backend in portfolio_nissy_state_recovery.get("selected_backends", [])
            )
            and len(portfolio_nissy_state_recovery_rows) >= 5
            and any(
                row.get("case_id") == "random_3_20"
                and str(row.get("selected_backend", "")).startswith("nissy-optimal")
                and row.get("source_sequence_provided_to_solver") is False
                and row.get("status") == "exact"
                and row.get("solution_length") == 17
                and row.get("verified") is True
                and "scramble_source=inverse_verified_kociemba_solution" in str(row.get("notes", ""))
                for row in portfolio_nissy_state_recovery_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in portfolio_nissy_state_recovery_rows
            )
        ),
        "portfolio_nissy_core_direct_state_valid_if_present": not portfolio_nissy_core_direct_state
        or (
            portfolio_nissy_core_direct_state.get("profile") == "thesis"
            and portfolio_nissy_core_direct_state.get("state_input_only") is True
            and portfolio_nissy_core_direct_state.get("certificate_cache_enabled") is False
            and portfolio_nissy_core_direct_state.get("upper_lower_certificate_enabled") is False
            and portfolio_nissy_core_direct_state.get("nissy_core_direct_first") is True
            and portfolio_nissy_core_direct_state.get("passed") is True
            and portfolio_nissy_core_direct_state.get("all_exact") is True
            and "nissy-core-direct" in set(portfolio_nissy_core_direct_state.get("selected_backends", []))
            and len(portfolio_nissy_core_direct_state_rows) >= 2
            and all(
                row.get("selected_backend") == "nissy-core-direct"
                and row.get("source_sequence_provided_to_solver") is False
                and row.get("status") == "exact"
                and row.get("verified") is True
                and "input_mode=cube_state" in str(row.get("notes", ""))
                and "table_symlink=true" in str(row.get("notes", ""))
                and "nissy_core_direct_invoked=true" in str(row.get("notes", ""))
                and "nissy_optimal_batch_invoked=false" in str(row.get("notes", ""))
                for row in portfolio_nissy_core_direct_state_rows
            )
        ),
        "portfolio_superflip_fallback_valid_if_present": not portfolio_superflip_fallback
        or (
            portfolio_superflip_fallback.get("profile") == "thesis"
            and portfolio_superflip_fallback.get("case_set") == "hard"
            and portfolio_superflip_fallback.get("case_ids") == ["superflip_distance_20"]
            and portfolio_superflip_fallback.get("passed") is True
            and portfolio_superflip_fallback.get("all_exact") is True
            and "resident-h48" in set(portfolio_superflip_fallback.get("selected_backends", []))
            and len(portfolio_superflip_fallback_rows) == 1
            and all(
                row.get("case_id") == "superflip_distance_20"
                and row.get("selected_backend") == "resident-h48"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                for row in portfolio_superflip_fallback_rows
            )
        ),
        "portfolio_superflip_certificate_cache_valid_if_present": not portfolio_superflip_certificate_cache
        or (
            portfolio_superflip_certificate_cache.get("profile") == "thesis"
            and portfolio_superflip_certificate_cache.get("case_set") == "hard"
            and portfolio_superflip_certificate_cache.get("case_ids") == ["superflip_distance_20"]
            and portfolio_superflip_certificate_cache.get("passed") is True
            and portfolio_superflip_certificate_cache.get("all_exact") is True
            and "exact-certificate-cache" in set(portfolio_superflip_certificate_cache.get("selected_backends", []))
            and len(portfolio_superflip_certificate_cache_rows) == 1
            and all(
                row.get("case_id") == "superflip_distance_20"
                and row.get("selected_backend") == "exact-certificate-cache"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                and row.get("expected_distance_matches") is True
                for row in portfolio_superflip_certificate_cache_rows
            )
        ),
        "race_optimal_oracle_valid_if_present": not race_optimal_oracle
        or (
            race_optimal_oracle.get("profile") == "thesis"
            and race_optimal_oracle.get("solver") == "h48h7"
            and race_optimal_oracle.get("trusted_table") is True
            and race_optimal_oracle.get("passed") is True
            and race_optimal_oracle.get("all_exact") is True
            and race_optimal_oracle.get("all_verified") is True
            and len(race_optimal_oracle_rows) >= 1
            and any(
                row.get("case_id") == "shallow_r_u_f2"
                and row.get("selected_backend") == "nissy-optimal"
                and row.get("started_backends") == "native-h48,nissy-optimal"
                and row.get("killed_backends") == "native-h48"
                and row.get("status") == "exact"
                and row.get("solution_length") == 3
                and row.get("verified") is True
                for row in race_optimal_oracle_rows
            )
            and all(row.get("status") == "exact" and row.get("verified") is True for row in race_optimal_oracle_rows)
        ),
        "race_nissy_core_direct_valid_if_present": not race_nissy_core_direct
        or (
            race_nissy_core_direct.get("profile") == "thesis"
            and race_nissy_core_direct.get("solver") == "h48h7"
            and race_nissy_core_direct.get("trusted_table") is True
            and race_nissy_core_direct.get("h48_enabled") is False
            and race_nissy_core_direct.get("nissy_core_direct_enabled") is True
            and race_nissy_core_direct.get("passed") is True
            and race_nissy_core_direct.get("all_exact") is True
            and race_nissy_core_direct.get("all_verified") is True
            and any(
                row.get("selected_backend") == "nissy-core-direct"
                and row.get("started_backends") == "nissy-core-direct"
                and row.get("killed_backends") == "none"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and "input_mode=cube_state" in str(row.get("notes", ""))
                and "table_symlink=true" in str(row.get("notes", ""))
                for row in race_nissy_core_direct_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in race_nissy_core_direct_rows
            )
        ),
        "resident_race_optimal_oracle_valid_if_present": not resident_race_optimal_oracle
        or (
            resident_race_optimal_oracle.get("profile") == "thesis"
            and resident_race_optimal_oracle.get("solver") == "h48h7"
            and resident_race_optimal_oracle.get("trusted_table") is True
            and resident_race_optimal_oracle.get("passed") is True
            and resident_race_optimal_oracle.get("all_exact") is True
            and resident_race_optimal_oracle.get("all_verified") is True
            and len(resident_race_optimal_oracle_rows) >= 3
            and any(
                row.get("mode") == "resident_race"
                and row.get("case_id") == "shallow_r_u_f2"
                and row.get("started_backends") == "resident-h48,nissy-optimal"
                and row.get("selected_backend") in {"nissy-optimal", "resident-h48"}
                and row.get("status") == "exact"
                and row.get("solution_length") == 3
                and row.get("verified") is True
                for row in resident_race_optimal_oracle_rows
            )
            and sum(
                1
                for row in resident_race_optimal_oracle_rows
                if row.get("mode") == "resident_h48_reuse"
                and row.get("selected_backend") == "resident-h48"
                and row.get("started_backends") == "resident-h48"
                and row.get("status") == "exact"
                and row.get("solution_length") == 3
                and row.get("verified") is True
            )
            >= 2
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in resident_race_optimal_oracle_rows
            )
        ),
        "resident_race_nissy_core_direct_valid_if_present": not resident_race_nissy_core_direct
        or (
            resident_race_nissy_core_direct.get("profile") == "thesis"
            and resident_race_nissy_core_direct.get("solver") == "h48h7"
            and resident_race_nissy_core_direct.get("trusted_table") is True
            and resident_race_nissy_core_direct.get("nissy_core_direct_enabled") is True
            and float(resident_race_nissy_core_direct.get("h48_start_delay_seconds", 0.0) or 0.0) > 0.0
            and resident_race_nissy_core_direct.get("passed") is True
            and resident_race_nissy_core_direct.get("all_exact") is True
            and resident_race_nissy_core_direct.get("all_verified") is True
            and any(
                row.get("mode") == "resident_race"
                and row.get("selected_backend") == "nissy-core-direct"
                and row.get("started_backends") == "nissy-core-direct"
                and row.get("stopped_backends") == "resident-h48-deferred"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and "input_mode=cube_state" in str(row.get("notes", ""))
                and "table_symlink=true" in str(row.get("notes", ""))
                for row in resident_race_nissy_core_direct_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in resident_race_nissy_core_direct_rows
            )
        ),
        "universal_optimal_oracle_valid_if_present": not universal_optimal_oracle
        or (
            universal_optimal_oracle.get("profile") == "thesis"
            and universal_optimal_oracle.get("solver") == "h48h7"
            and universal_optimal_oracle.get("api_class") == "UniversalOptimalOracle"
            and universal_optimal_oracle.get("trusted_table") is True
            and universal_optimal_oracle.get("passed") is True
            and universal_optimal_oracle.get("all_exact") is True
            and universal_optimal_oracle.get("all_verified") is True
            and universal_optimal_oracle.get("fast_runtime_proven_for_every_possible_state") is False
            and len(universal_optimal_oracle_rows) >= 3
            and {"solved_fast_path", "exact-certificate-cache", "resident-race"}.issubset(
                set(universal_optimal_oracle.get("selected_backends", []))
            )
            and any(
                row.get("case_id") == "solved"
                and row.get("selected_backend") == "solved_fast_path"
                and row.get("status") == "exact"
                and row.get("solution_length") == 0
                and row.get("verified") is True
                for row in universal_optimal_oracle_rows
            )
            and any(
                row.get("case_id") == "superflip_distance_20"
                and row.get("selected_backend") == "exact-certificate-cache"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                for row in universal_optimal_oracle_rows
            )
            and any(
                row.get("case_id") == "shallow_r_u_f2"
                and row.get("selected_backend") == "resident-race"
                and row.get("status") == "exact"
                and row.get("solution_length") == 3
                and row.get("verified") is True
                for row in universal_optimal_oracle_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in universal_optimal_oracle_rows
            )
        ),
        "universal_nissy_core_direct_valid_if_present": not universal_nissy_core_direct
        or (
            universal_nissy_core_direct.get("profile") == "thesis"
            and universal_nissy_core_direct.get("solver") == "h48h7"
            and universal_nissy_core_direct.get("api_class") == "UniversalOptimalOracle"
            and universal_nissy_core_direct.get("trusted_table") is True
            and universal_nissy_core_direct.get("state_input_only") is True
            and universal_nissy_core_direct.get("passed") is True
            and universal_nissy_core_direct.get("all_exact") is True
            and universal_nissy_core_direct.get("all_verified") is True
            and universal_nissy_core_direct.get("fast_runtime_proven_for_every_possible_state") is False
            and universal_nissy_core_direct.get("direct_nissy_core_rows") == len(universal_nissy_core_direct_rows)
            and "resident-race" in set(universal_nissy_core_direct.get("selected_backends", []))
            and "nissy-core-direct" in set(universal_nissy_core_direct.get("nested_selected_backends", []))
            and len(universal_nissy_core_direct_rows) >= 1
            and all(
                row.get("selected_backend") == "resident-race"
                and row.get("direct_nissy_core_used") is True
                and row.get("source_sequence_provided_to_solver") is False
                and row.get("started_backends") == "nissy-core-direct"
                and row.get("stopped_backends") == "resident-h48-deferred"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and "input_mode=cube_state" in str(row.get("notes", ""))
                and "table_symlink=true" in str(row.get("notes", ""))
                for row in universal_nissy_core_direct_rows
            )
        ),
        "universal_h48_symmetry_valid_if_present": not universal_h48_symmetry
        or (
            universal_h48_symmetry.get("profile") == "thesis"
            and universal_h48_symmetry.get("solver") == "h48h7"
            and universal_h48_symmetry.get("api_class") == "UniversalOptimalOracle"
            and universal_h48_symmetry.get("trusted_table") is True
            and universal_h48_symmetry.get("state_input_only") is True
            and universal_h48_symmetry.get("passed") is True
            and universal_h48_symmetry.get("all_exact") is True
            and universal_h48_symmetry.get("all_verified") is True
            and universal_h48_symmetry.get("fast_runtime_proven_for_every_possible_state") is False
            and universal_h48_symmetry.get("resident_h48_symmetry_variants") == 2
            and "resident-h48-symmetry-batch" in set(universal_h48_symmetry.get("selected_backends", []))
            and len(universal_h48_symmetry_rows) >= 1
            and all(
                row.get("selected_backend") == "resident-h48-symmetry-batch"
                and row.get("backend_solver") == "fast_optimal_oracle_h48h7_symmetry_batch"
                and row.get("resident_h48_symmetry_used") is True
                and row.get("selected_rotation")
                and row.get("source_sequence_provided_to_solver") is False
                and row.get("status") == "exact"
                and row.get("verified") is True
                and "rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
                for row in universal_h48_symmetry_rows
            )
        ),
        "universal_batch_oracle_corpus_valid_if_present": not universal_batch_oracle_corpus
        or (
            universal_batch_oracle_corpus.get("profile") == "thesis"
            and universal_batch_oracle_corpus.get("solver") == "h48h7"
            and universal_batch_oracle_corpus.get("api_class") == "UniversalOptimalOracle"
            and universal_batch_oracle_corpus.get("trusted_table") is True
            and universal_batch_oracle_corpus.get("state_input_only") is True
            and universal_batch_oracle_corpus.get("passed") is True
            and universal_batch_oracle_corpus.get("all_exact") is True
            and universal_batch_oracle_corpus.get("all_verified") is True
            and universal_batch_oracle_corpus.get("all_universal_portfolio_batch") is True
            and len(universal_batch_oracle_corpus_rows) >= 3
            and all(
                row.get("selected_backend") == "portfolio-batch"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is False
                for row in universal_batch_oracle_corpus_rows
            )
        ),
        "universal_resident_h48_batch_valid_if_present": not universal_resident_h48_batch
        or (
            universal_resident_h48_batch.get("profile") == "thesis"
            and universal_resident_h48_batch.get("solver") == "h48h7"
            and universal_resident_h48_batch.get("api_class") == "UniversalOptimalOracle"
            and universal_resident_h48_batch.get("trusted_table") is True
            and universal_resident_h48_batch.get("state_input_only") is True
            and universal_resident_h48_batch.get("resident_h48_batch") is True
            and universal_resident_h48_batch.get("passed") is True
            and universal_resident_h48_batch.get("all_exact") is True
            and universal_resident_h48_batch.get("all_verified") is True
            and universal_resident_h48_batch.get("all_universal_resident_h48_batch") is True
            and len(universal_resident_h48_batch_rows) >= 3
            and all(
                row.get("selected_backend") == "resident-h48-batch"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is False
                and "resident_native_h48=true" in str(row.get("notes", ""))
                and "table_loaded_once=true" in str(row.get("notes", ""))
                and "input_mode=cube_state" in str(row.get("notes", ""))
                for row in universal_resident_h48_batch_rows
            )
        ),
        "universal_oracle_cli_valid_if_present": not universal_oracle_cli
        or (
            universal_oracle_cli.get("profile") == "thesis"
            and universal_oracle_cli.get("solver") == "h48h7"
            and universal_oracle_cli.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli.get("public_interface") == "rubik-optimal oracle --universal"
            and universal_oracle_cli.get("trusted_table") is True
            and universal_oracle_cli.get("passed") is True
            and universal_oracle_cli.get("all_exact") is True
            and universal_oracle_cli.get("all_verified") is True
            and universal_oracle_cli.get("all_universal_optimized_cli") is True
            and universal_oracle_cli.get("all_state_input_only") is True
            and int(universal_oracle_cli.get("resident_h48_batch_rows", 0)) >= 1
            and len(universal_oracle_cli_rows) >= 3
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend")
                in {
                    "upper-lower-certificate",
                    "exact-certificate-cache",
                    "resident-h48-batch",
                    "portfolio-after-resident-h48-fallback",
                    "solved_fast_path",
                }
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_rows
            )
        ),
        "universal_oracle_cli_broader_valid_if_present": not universal_oracle_cli_broader
        or (
            universal_oracle_cli_broader.get("profile") == "thesis"
            and universal_oracle_cli_broader.get("solver") == "h48h7"
            and universal_oracle_cli_broader.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_broader.get("public_interface") == "rubik-optimal oracle --universal"
            and universal_oracle_cli_broader.get("trusted_table") is True
            and universal_oracle_cli_broader.get("passed") is True
            and universal_oracle_cli_broader.get("all_exact") is True
            and universal_oracle_cli_broader.get("all_verified") is True
            and universal_oracle_cli_broader.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_broader.get("all_state_input_only") is True
            and int(universal_oracle_cli_broader.get("resident_h48_batch_rows", 0)) >= 1
            and int(universal_oracle_cli_broader.get("resident_h48_fallback_rows", 0)) >= 1
            and len(universal_oracle_cli_broader_rows) >= 5
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend")
                in {
                    "upper-lower-certificate",
                    "exact-certificate-cache",
                    "resident-h48-batch",
                    "portfolio-after-resident-h48-fallback",
                    "solved_fast_path",
                }
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_broader_rows
            )
        ),
        "universal_oracle_cli_adaptive_valid_if_present": not universal_oracle_cli_adaptive
        or (
            universal_oracle_cli_adaptive.get("profile") == "thesis"
            and universal_oracle_cli_adaptive.get("solver") == "h48h7"
            and universal_oracle_cli_adaptive.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_adaptive.get("public_interface") == "rubik-optimal oracle --universal"
            and universal_oracle_cli_adaptive.get("trusted_table") is True
            and universal_oracle_cli_adaptive.get("passed") is True
            and universal_oracle_cli_adaptive.get("all_exact") is True
            and universal_oracle_cli_adaptive.get("all_verified") is True
            and universal_oracle_cli_adaptive.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_adaptive.get("all_state_input_only") is True
            and universal_oracle_cli_adaptive.get("try_portfolio_batch_before_resident_h48_batch") is True
            and int(universal_oracle_cli_adaptive.get("portfolio_prepass_rows", 0)) >= 1
            and len(universal_oracle_cli_adaptive_rows) >= 5
            and (
                not universal_oracle_cli_broader
                or float(universal_oracle_cli_adaptive.get("max_runtime_seconds", 10**9))
                < float(universal_oracle_cli_broader.get("max_runtime_seconds", 0))
            )
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend")
                in {
                    "upper-lower-certificate",
                    "exact-certificate-cache",
                    "portfolio-before-resident-h48-batch",
                    "resident-h48-batch",
                    "resident-h48-batch-after-portfolio-prepass",
                    "portfolio-after-resident-h48-fallback",
                    "portfolio-after-resident-h48-fallback-after-prepass",
                    "solved_fast_path",
                }
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_adaptive_rows
            )
        ),
        "universal_oracle_cli_expanded_valid_if_present": not universal_oracle_cli_expanded
        or (
            universal_oracle_cli_expanded.get("profile") == "thesis"
            and universal_oracle_cli_expanded.get("solver") == "h48h7"
            and universal_oracle_cli_expanded.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_expanded.get("public_interface") == "rubik-optimal oracle --universal"
            and universal_oracle_cli_expanded.get("trusted_table") is True
            and universal_oracle_cli_expanded.get("passed") is True
            and universal_oracle_cli_expanded.get("all_exact") is True
            and universal_oracle_cli_expanded.get("all_verified") is True
            and universal_oracle_cli_expanded.get("all_expected_distances_match") is True
            and universal_oracle_cli_expanded.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_expanded.get("all_state_input_only") is True
            and universal_oracle_cli_expanded.get("try_portfolio_batch_before_resident_h48_batch") is True
            and universal_oracle_cli_expanded.get("include_hard") is True
            and universal_oracle_cli_expanded.get("contains_superflip") is True
            and int(universal_oracle_cli_expanded.get("hard_case_count", 0)) >= 2
            and int(universal_oracle_cli_expanded.get("expected_distance_checked_count", 0)) >= 1
            and int(universal_oracle_cli_expanded.get("portfolio_prepass_rows", 0)) >= 1
            and len(universal_oracle_cli_expanded_rows) >= 12
            and any(
                row.get("case_id") == "cli_hard_superflip_distance_20"
                and row.get("expected_distance") == 20
                and row.get("solution_length") == 20
                and row.get("selected_backend") == "exact-certificate-cache"
                for row in universal_oracle_cli_expanded_rows
            )
            and all(
                row.get("input_kind") == "facelets"
                and isinstance(row.get("state"), str)
                and row.get("solution") is not None
                and row.get("selected_backend")
                in {
                    "upper-lower-certificate",
                    "exact-certificate-cache",
                    "portfolio-before-resident-h48-batch",
                    "resident-h48-batch",
                    "resident-h48-batch-after-portfolio-prepass",
                    "portfolio-after-resident-h48-fallback",
                    "portfolio-after-resident-h48-fallback-after-prepass",
                    "solved_fast_path",
                }
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_expanded_rows
            )
        ),
        "universal_oracle_cli_h48_symmetry_valid_if_present": not universal_oracle_cli_h48_symmetry
        or (
            universal_oracle_cli_h48_symmetry.get("profile") == "thesis"
            and universal_oracle_cli_h48_symmetry.get("solver") == "h48h7"
            and universal_oracle_cli_h48_symmetry.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_h48_symmetry.get("public_interface") == "rubik-optimal oracle --universal"
            and universal_oracle_cli_h48_symmetry.get("trusted_table") is True
            and universal_oracle_cli_h48_symmetry.get("passed") is True
            and universal_oracle_cli_h48_symmetry.get("all_exact") is True
            and universal_oracle_cli_h48_symmetry.get("all_verified") is True
            and universal_oracle_cli_h48_symmetry.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_h48_symmetry.get("all_state_input_only") is True
            and universal_oracle_cli_h48_symmetry.get("resident_h48_symmetry_variants") == 2
            and int(universal_oracle_cli_h48_symmetry.get("resident_h48_symmetry_rows", 0)) >= 1
            and len(universal_oracle_cli_h48_symmetry_rows) >= 1
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend") == "resident-h48-symmetry-batch"
                and row.get("backend_solver") == "fast_optimal_oracle_h48h7_symmetry_batch"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
                for row in universal_oracle_cli_h48_symmetry_rows
            )
        ),
        "universal_oracle_cli_h48_parallel_symmetry_valid_if_present": (
            not universal_oracle_cli_h48_parallel_symmetry
        )
        or (
            universal_oracle_cli_h48_parallel_symmetry.get("profile") == "thesis"
            and universal_oracle_cli_h48_parallel_symmetry.get("solver") == "h48h7"
            and universal_oracle_cli_h48_parallel_symmetry.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_h48_parallel_symmetry.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_h48_parallel_symmetry.get("trusted_table") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("passed") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("all_exact") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("all_verified") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("all_state_input_only") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("try_certificate_cache") is False
            and universal_oracle_cli_h48_parallel_symmetry.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_h48_parallel_symmetry.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_h48_parallel_symmetry.get("parallel_h48_symmetry_variants") == 2
            and int(universal_oracle_cli_h48_parallel_symmetry.get("parallel_h48_symmetry_rows", 0)) >= 1
            and len(universal_oracle_cli_h48_parallel_symmetry_rows) >= 1
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend") == "parallel-h48-symmetry-race"
                and row.get("backend_solver") == "fast_optimal_oracle_h48h7_parallel_symmetry_race"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "first_rotated_exact_solution_mapped_back_and_verified" in str(row.get("notes", ""))
                for row in universal_oracle_cli_h48_parallel_symmetry_rows
            )
        ),
        "universal_oracle_cli_live_no_shortcuts_valid_if_present": not universal_oracle_cli_live_no_shortcuts
        or (
            universal_oracle_cli_live_no_shortcuts.get("profile") == "thesis"
            and universal_oracle_cli_live_no_shortcuts.get("solver") == "h48h7"
            and universal_oracle_cli_live_no_shortcuts.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_live_no_shortcuts.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_live_no_shortcuts.get("trusted_table") is True
            and universal_oracle_cli_live_no_shortcuts.get("passed") is True
            and universal_oracle_cli_live_no_shortcuts.get("all_exact") is True
            and universal_oracle_cli_live_no_shortcuts.get("all_verified") is True
            and universal_oracle_cli_live_no_shortcuts.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_live_no_shortcuts.get("all_state_input_only") is True
            and universal_oracle_cli_live_no_shortcuts.get("try_certificate_cache") is False
            and universal_oracle_cli_live_no_shortcuts.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_live_no_shortcuts.get("live_solver_shortcuts_disabled") is True
            and len(universal_oracle_cli_live_no_shortcuts_rows) >= 1
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend")
                not in {"exact-certificate-cache", "upper-lower-certificate", "solved_fast_path"}
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_live_no_shortcuts_rows
            )
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_valid_if_present": (
            not universal_oracle_cli_live_no_shortcuts_broader
        )
        or (
            universal_oracle_cli_live_no_shortcuts_broader.get("profile") == "thesis"
            and universal_oracle_cli_live_no_shortcuts_broader.get("solver") == "h48h7"
            and universal_oracle_cli_live_no_shortcuts_broader.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_live_no_shortcuts_broader.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_live_no_shortcuts_broader.get("trusted_table") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("passed") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("all_exact") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("all_verified") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("all_state_input_only") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("try_certificate_cache") is False
            and universal_oracle_cli_live_no_shortcuts_broader.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_live_no_shortcuts_broader.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get("preload_table") is True
            and universal_oracle_cli_live_no_shortcuts_broader.get(
                "try_portfolio_batch_before_resident_h48_batch"
            )
            is False
            and int(universal_oracle_cli_live_no_shortcuts_broader.get("resident_h48_batch_rows") or 0) >= 5
            and list(universal_oracle_cli_live_no_shortcuts_broader.get("selected_backends", []))
            == ["resident-h48-batch"]
            and list(universal_oracle_cli_live_no_shortcuts_broader.get("depths", []))
            == [5, 10, 15, 20, 25]
            and len(universal_oracle_cli_live_no_shortcuts_broader_rows) >= 5
            and float(universal_oracle_cli_live_no_shortcuts_broader.get("max_runtime_seconds", 10**9))
            <= 20.0
            and float(universal_oracle_cli_live_no_shortcuts_broader.get("wrapper_wall_seconds", 10**9))
            <= 20.0
            and all(
                row.get("input_kind") == "facelets"
                and row.get("selected_backend")
                not in {"exact-certificate-cache", "upper-lower-certificate", "solved_fast_path"}
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                for row in universal_oracle_cli_live_no_shortcuts_broader_rows
            )
        ),
        "universal_oracle_cli_known_distance_17_valid_if_present": not universal_oracle_cli_known_distance_17
        or (
            universal_oracle_cli_known_distance_17.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_17.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_17.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_17.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_17.get("trusted_table") is True
            and universal_oracle_cli_known_distance_17.get("passed") is True
            and universal_oracle_cli_known_distance_17.get("all_exact") is True
            and universal_oracle_cli_known_distance_17.get("all_verified") is True
            and universal_oracle_cli_known_distance_17.get("all_expected_distances_match") is True
            and universal_oracle_cli_known_distance_17.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_known_distance_17.get("all_state_input_only") is True
            and universal_oracle_cli_known_distance_17.get("try_certificate_cache") is False
            and universal_oracle_cli_known_distance_17.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_known_distance_17.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_known_distance_17.get("random_cases_enabled") is False
            and universal_oracle_cli_known_distance_17.get("nissy_benchmark_distances_present") == [17]
            and int(universal_oracle_cli_known_distance_17.get("resident_h48_batch_rows") or 0) >= 1
            and list(universal_oracle_cli_known_distance_17.get("selected_backends", [])) == ["resident-h48-batch"]
            and len(universal_oracle_cli_known_distance_17_rows) >= 1
            and float(universal_oracle_cli_known_distance_17.get("max_backend_solve_seconds", 10**9))
            <= 120.0
            and all(
                row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") == 17
                and row.get("solution_length") == 17
                and row.get("selected_backend") == "resident-h48-batch"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and float(row.get("backend_solve_seconds") or 10**9) <= 120.0
                for row in universal_oracle_cli_known_distance_17_rows
            )
        ),
        "universal_oracle_cli_known_distance_adaptive_valid_if_present": not universal_oracle_cli_known_distance_adaptive
        or (
            universal_oracle_cli_known_distance_adaptive.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_adaptive.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_adaptive.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_adaptive.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_adaptive.get("trusted_table") is True
            and universal_oracle_cli_known_distance_adaptive.get("passed") is True
            and universal_oracle_cli_known_distance_adaptive.get("outer_command_timed_out") is False
            and universal_oracle_cli_known_distance_adaptive.get("all_exact") is True
            and universal_oracle_cli_known_distance_adaptive.get("all_verified") is True
            and universal_oracle_cli_known_distance_adaptive.get("all_expected_distances_match") is True
            and universal_oracle_cli_known_distance_adaptive.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_known_distance_adaptive.get("all_state_input_only") is True
            and universal_oracle_cli_known_distance_adaptive.get("try_certificate_cache") is False
            and universal_oracle_cli_known_distance_adaptive.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_known_distance_adaptive.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_known_distance_adaptive.get("random_cases_enabled") is False
            and universal_oracle_cli_known_distance_adaptive.get("nissy_benchmark_distances_present") == [17, 18]
            and int(universal_oracle_cli_known_distance_adaptive.get("portfolio_prepass_rows") or 0) >= 2
            and list(universal_oracle_cli_known_distance_adaptive.get("selected_backends", []))
            == ["portfolio-before-resident-h48-batch"]
            and float(universal_oracle_cli_known_distance_adaptive.get("max_runtime_seconds", 10**9)) <= 90.0
            and float(universal_oracle_cli_known_distance_adaptive.get("wrapper_wall_seconds", 10**9)) <= 90.0
            and float(universal_oracle_cli_known_distance_adaptive.get("command_timeout_seconds", 0)) >= 600.0
            and len(universal_oracle_cli_known_distance_adaptive_rows) >= 2
            and all(
                row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") in {17, 18}
                and row.get("solution_length") == row.get("expected_distance")
                and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
                and row.get("backend_solver") == "portfolio_optimal_oracle"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
                and "scramble_source=inverse_verified_kociemba_solution" in str(row.get("notes", ""))
                for row in universal_oracle_cli_known_distance_adaptive_rows
            )
        ),
        "universal_oracle_cli_known_distance_19_valid_if_present": not universal_oracle_cli_known_distance_19
        or (
            universal_oracle_cli_known_distance_19.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_19.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_19.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_19.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_19.get("trusted_table") is True
            and universal_oracle_cli_known_distance_19.get("passed") is True
            and universal_oracle_cli_known_distance_19.get("outer_command_timed_out") is False
            and universal_oracle_cli_known_distance_19.get("all_exact") is True
            and universal_oracle_cli_known_distance_19.get("all_verified") is True
            and universal_oracle_cli_known_distance_19.get("all_expected_distances_match") is True
            and universal_oracle_cli_known_distance_19.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_known_distance_19.get("all_state_input_only") is True
            and universal_oracle_cli_known_distance_19.get("try_certificate_cache") is False
            and universal_oracle_cli_known_distance_19.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_known_distance_19.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_known_distance_19.get("random_cases_enabled") is False
            and universal_oracle_cli_known_distance_19.get("nissy_benchmark_distances_present") == [19]
            and int(universal_oracle_cli_known_distance_19.get("portfolio_prepass_rows") or 0) >= 1
            and list(universal_oracle_cli_known_distance_19.get("selected_backends", []))
            == ["portfolio-before-resident-h48-batch"]
            and float(universal_oracle_cli_known_distance_19.get("max_runtime_seconds", 10**9)) <= 240.0
            and float(universal_oracle_cli_known_distance_19.get("wrapper_wall_seconds", 10**9)) <= 240.0
            and float(universal_oracle_cli_known_distance_19.get("max_backend_solve_seconds", 10**9)) <= 60.0
            and float(universal_oracle_cli_known_distance_19.get("command_timeout_seconds", 0)) >= 690.0
            and len(universal_oracle_cli_known_distance_19_rows) >= 1
            and all(
                row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") == 19
                and row.get("solution_length") == 19
                and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
                and row.get("backend_solver") == "portfolio_optimal_oracle"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
                and "nissy_status=timeout" in str(row.get("notes", ""))
                and "resident_h48_invoked=true" in str(row.get("notes", ""))
                and float(row.get("backend_solve_seconds") or 10**9) <= 60.0
                for row in universal_oracle_cli_known_distance_19_rows
            )
        ),
        "universal_oracle_cli_known_distance_20_valid_if_present": not universal_oracle_cli_known_distance_20
        or (
            universal_oracle_cli_known_distance_20.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_20.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_20.get("api_class") == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_20.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_20.get("trusted_table") is True
            and universal_oracle_cli_known_distance_20.get("passed") is True
            and universal_oracle_cli_known_distance_20.get("outer_command_timed_out") is False
            and universal_oracle_cli_known_distance_20.get("all_exact") is True
            and universal_oracle_cli_known_distance_20.get("all_verified") is True
            and universal_oracle_cli_known_distance_20.get("all_expected_distances_match") is True
            and universal_oracle_cli_known_distance_20.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_known_distance_20.get("all_state_input_only") is True
            and universal_oracle_cli_known_distance_20.get("try_certificate_cache") is False
            and universal_oracle_cli_known_distance_20.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_known_distance_20.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_known_distance_20.get("random_cases_enabled") is False
            and universal_oracle_cli_known_distance_20.get("nissy_benchmark_distances_present") == [20]
            and int(universal_oracle_cli_known_distance_20.get("portfolio_prepass_rows") or 0) >= 1
            and list(universal_oracle_cli_known_distance_20.get("selected_backends", []))
            == ["portfolio-before-resident-h48-batch"]
            and float(universal_oracle_cli_known_distance_20.get("max_runtime_seconds", 10**9)) <= 540.0
            and float(universal_oracle_cli_known_distance_20.get("wrapper_wall_seconds", 10**9)) <= 540.0
            and float(universal_oracle_cli_known_distance_20.get("max_backend_solve_seconds", 10**9)) <= 240.0
            and float(universal_oracle_cli_known_distance_20.get("command_timeout_seconds", 0)) >= 1080.0
            and len(universal_oracle_cli_known_distance_20_rows) >= 1
            and all(
                row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") == 20
                and row.get("solution_length") == 20
                and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
                and row.get("backend_solver") == "portfolio_optimal_oracle"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
                and "nissy_status=timeout" in str(row.get("notes", ""))
                and "resident_h48_invoked=true" in str(row.get("notes", ""))
                and float(row.get("backend_solve_seconds") or 10**9) <= 240.0
                for row in universal_oracle_cli_known_distance_20_rows
            )
        ),
        "universal_oracle_cli_known_distance_20_offset1_valid_if_present": (
            not universal_oracle_cli_known_distance_20_offset1
        )
        or (
            universal_oracle_cli_known_distance_20_offset1.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_20_offset1.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_20_offset1.get("api_class")
            == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_20_offset1.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_20_offset1.get("trusted_table") is True
            and universal_oracle_cli_known_distance_20_offset1.get("passed") is True
            and universal_oracle_cli_known_distance_20_offset1.get("outer_command_timed_out") is False
            and universal_oracle_cli_known_distance_20_offset1.get("all_exact") is True
            and universal_oracle_cli_known_distance_20_offset1.get("all_verified") is True
            and universal_oracle_cli_known_distance_20_offset1.get("all_expected_distances_match") is True
            and universal_oracle_cli_known_distance_20_offset1.get("all_universal_optimized_cli") is True
            and universal_oracle_cli_known_distance_20_offset1.get("all_state_input_only") is True
            and universal_oracle_cli_known_distance_20_offset1.get("try_certificate_cache") is False
            and universal_oracle_cli_known_distance_20_offset1.get("try_upper_lower_certificate") is False
            and universal_oracle_cli_known_distance_20_offset1.get("live_solver_shortcuts_disabled") is True
            and universal_oracle_cli_known_distance_20_offset1.get("random_cases_enabled") is False
            and universal_oracle_cli_known_distance_20_offset1.get("benchmark_offset_per_distance") == 1
            and universal_oracle_cli_known_distance_20_offset1.get("nissy_benchmark_distances_present")
            == [20]
            and int(universal_oracle_cli_known_distance_20_offset1.get("portfolio_prepass_rows") or 0) >= 1
            and list(universal_oracle_cli_known_distance_20_offset1.get("selected_backends", []))
            == ["portfolio-before-resident-h48-batch"]
            and float(universal_oracle_cli_known_distance_20_offset1.get("max_runtime_seconds", 10**9))
            <= 540.0
            and float(universal_oracle_cli_known_distance_20_offset1.get("wrapper_wall_seconds", 10**9))
            <= 540.0
            and float(
                universal_oracle_cli_known_distance_20_offset1.get(
                    "max_backend_solve_seconds",
                    10**9,
                )
            )
            <= 240.0
            and float(universal_oracle_cli_known_distance_20_offset1.get("command_timeout_seconds", 0))
            >= 1080.0
            and len(universal_oracle_cli_known_distance_20_offset1_rows) >= 1
            and all(
                row.get("case_id") == "nissy_benchmark_distance_20_1"
                and row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") == 20
                and row.get("solution_length") == 20
                and row.get("selected_backend") == "portfolio-before-resident-h48-batch"
                and row.get("backend_solver") == "portfolio_optimal_oracle"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
                and "nissy_status=timeout" in str(row.get("notes", ""))
                and "resident_h48_invoked=true" in str(row.get("notes", ""))
                and float(row.get("backend_solve_seconds") or 10**9) <= 240.0
                for row in universal_oracle_cli_known_distance_20_offset1_rows
            )
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_valid_if_present": (
            not universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
        )
        or (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("profile") == "thesis"
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("solver") == "h48h7"
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("api_class")
            == "UniversalOptimalOracle"
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("public_interface")
            == "rubik-optimal oracle --universal"
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("trusted_table") is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("passed") is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("outer_command_timed_out")
            is False
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("all_exact") is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("all_verified") is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "all_expected_distances_match"
            )
            is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "all_universal_optimized_cli"
            )
            is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "all_state_input_only"
            )
            is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "try_certificate_cache"
            )
            is False
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "try_upper_lower_certificate"
            )
            is False
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "live_solver_shortcuts_disabled"
            )
            is True
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "random_cases_enabled"
            )
            is False
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "benchmark_offset_per_distance"
            )
            == 1
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "portfolio_prepass_timeout_seconds"
            )
            == 30.0
            and universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "nissy_benchmark_distances_present"
            )
            == [20]
            and list(universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("selected_backends", []))
            == ["resident-h48-batch-after-portfolio-prepass"]
            and float(
                universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                    "max_runtime_seconds",
                    10**9,
                )
            )
            <= 240.0
            and float(
                universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                    "wrapper_wall_seconds",
                    10**9,
                )
            )
            <= 240.0
            and float(
                universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                    "max_backend_solve_seconds",
                    10**9,
                )
            )
            <= 180.0
            and float(
                universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                    "command_timeout_seconds",
                    0,
                )
            )
            >= 540.0
            and len(universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_rows) >= 1
            and all(
                row.get("case_id") == "nissy_benchmark_distance_20_1"
                and row.get("case_kind") == "nissy_core_benchmark_known_distance"
                and row.get("input_kind") == "facelets"
                and row.get("expected_distance") == 20
                and row.get("solution_length") == 20
                and row.get("selected_backend") == "resident-h48-batch-after-portfolio-prepass"
                and row.get("backend_solver") == "fast_optimal_oracle_h48h7"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("source_sequence_provided_to_solver") is not True
                and "nissy_optimal_batch_invoked=true" in str(row.get("notes", ""))
                and "nissy_status=timeout" in str(row.get("notes", ""))
                and "timed out after 30.0s" in str(row.get("notes", ""))
                and "h48_fallback_disabled=true" in str(row.get("notes", ""))
                and float(row.get("backend_solve_seconds") or 10**9) <= 180.0
                for row in universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_rows
            )
        ),
        "universal_symmetry_oracle_valid_if_present": not universal_symmetry_oracle
        or (
            universal_symmetry_oracle.get("profile") == "thesis"
            and universal_symmetry_oracle.get("solver") == "h48h7"
            and universal_symmetry_oracle.get("api_class") == "UniversalOptimalOracle"
            and universal_symmetry_oracle.get("trusted_table") is True
            and universal_symmetry_oracle.get("passed") is True
            and universal_symmetry_oracle.get("all_exact") is True
            and universal_symmetry_oracle.get("all_verified") is True
            and universal_symmetry_oracle.get("all_nissy_symmetry_batch") is True
            and universal_symmetry_oracle.get("fast_runtime_proven_for_every_possible_state") is False
            and len(universal_symmetry_oracle_rows) >= 1
            and all(
                row.get("selected_backend") == "nissy-symmetry-batch"
                and row.get("backend_solver") == "nissy_symmetry_batch_oracle"
                and row.get("selected_rotation")
                and row.get("status") == "exact"
                and row.get("verified") is True
                for row in universal_symmetry_oracle_rows
            )
        ),
        "certificate_cache_inverse_closure_valid_if_present": not certificate_cache_inverse_closure
        or (
            certificate_cache_inverse_closure.get("profile") == "thesis"
            and certificate_cache_inverse_closure.get("solver") == "h48h7"
            and certificate_cache_inverse_closure.get("api_class") == "UniversalOptimalOracle"
            and certificate_cache_inverse_closure.get("certificate_store") == "ExactCertificateStore"
            and certificate_cache_inverse_closure.get("certificate_cache_derivation") == "inverse"
            and certificate_cache_inverse_closure.get("passed") is True
            and certificate_cache_inverse_closure.get("all_exact") is True
            and certificate_cache_inverse_closure.get("all_verified") is True
            and certificate_cache_inverse_closure.get("all_inverse_certificate_cache") is True
            and len(certificate_cache_inverse_closure_rows) >= 10
            and all(
                row.get("selected_backend") == "exact-certificate-cache"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("certificate_derivation") == "inverse"
                for row in certificate_cache_inverse_closure_rows
            )
        ),
        "certificate_cache_symmetry_closure_valid_if_present": not certificate_cache_symmetry_closure
        or (
            certificate_cache_symmetry_closure.get("profile") == "thesis"
            and certificate_cache_symmetry_closure.get("solver") == "h48h7"
            and certificate_cache_symmetry_closure.get("api_class") == "UniversalOptimalOracle"
            and certificate_cache_symmetry_closure.get("certificate_store") == "ExactCertificateStore"
            and certificate_cache_symmetry_closure.get("passed") is True
            and certificate_cache_symmetry_closure.get("all_exact") is True
            and certificate_cache_symmetry_closure.get("all_verified") is True
            and certificate_cache_symmetry_closure.get("all_symmetry_certificate_cache") is True
            and certificate_cache_symmetry_closure.get("symmetry_closure_proven_for_saved_certificates") is True
            and len(certificate_cache_symmetry_closure_rows) >= 700
            and all(
                row.get("selected_backend") == "exact-certificate-cache"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("certificate_derivation") in {"symmetry", "inverse_symmetry"}
                for row in certificate_cache_symmetry_closure_rows
            )
        ),
        "certificate_cache_expanded_symmetry_closure_valid_if_present": not certificate_cache_expanded_symmetry_closure
        or (
            certificate_cache_expanded_symmetry_closure.get("profile") == "thesis"
            and certificate_cache_expanded_symmetry_closure.get("solver") == "h48h7"
            and certificate_cache_expanded_symmetry_closure.get("api_class") == "UniversalOptimalOracle"
            and certificate_cache_expanded_symmetry_closure.get("certificate_store") == "ExactCertificateStore"
            and certificate_cache_expanded_symmetry_closure.get("passed") is True
            and certificate_cache_expanded_symmetry_closure.get("all_exact") is True
            and certificate_cache_expanded_symmetry_closure.get("all_verified") is True
            and certificate_cache_expanded_symmetry_closure.get("all_symmetry_certificate_cache") is True
            and certificate_cache_expanded_symmetry_closure.get("symmetry_closure_proven_for_saved_certificates")
            is True
            and len(certificate_cache_expanded_symmetry_closure_rows) > len(certificate_cache_symmetry_closure_rows)
            and all(
                row.get("selected_backend") == "exact-certificate-cache"
                and row.get("status") == "exact"
                and row.get("verified") is True
                and row.get("certificate_derivation") in {"symmetry", "inverse_symmetry"}
                for row in certificate_cache_expanded_symmetry_closure_rows
            )
        ),
        "learned_certificate_cache_valid_if_present": not learned_certificate_cache
        or (
            learned_certificate_cache.get("profile") == "thesis"
            and learned_certificate_cache.get("solver") == "h48h7"
            and learned_certificate_cache.get("api_class") == "UniversalOptimalOracle"
            and learned_certificate_cache.get("certificate_store") == "ExactCertificateStore"
            and learned_certificate_cache.get("passed") is True
            and learned_certificate_cache.get("learned_jsonl_all_exact") is True
            and learned_certificate_cache.get("first_pass_all_exact") is True
            and learned_certificate_cache.get("first_pass_all_verified") is True
            and learned_certificate_cache.get("first_pass_all_cache_miss") is True
            and learned_certificate_cache.get("replay_live_backends_enabled") is False
            and learned_certificate_cache.get("replay_all_exact") is True
            and learned_certificate_cache.get("replay_all_verified") is True
            and learned_certificate_cache.get("replay_all_certificate_cache") is True
            and len(learned_certificate_cache_rows) >= 2
            and int(learned_certificate_cache.get("learned_jsonl_row_count", 0) or 0)
            >= len(learned_certificate_cache_rows)
            and all(
                row.get("first_selected_backend") != "exact-certificate-cache"
                and row.get("replay_selected_backend") == "exact-certificate-cache"
                and row.get("first_status") == "exact"
                and row.get("first_verified") is True
                and row.get("replay_status") == "exact"
                and row.get("replay_verified") is True
                and row.get("solution_length") == row.get("replay_solution_length")
                for row in learned_certificate_cache_rows
            )
        ),
        "h48_oracle_contract_valid_if_present": not h48_oracle_contract
        or (
            h48_oracle_contract.get("profile") == "thesis"
            and h48_oracle_contract.get("solver") == "h48h7"
            and h48_oracle_contract.get("passed") is True
            and h48_oracle_contract.get("all_state_exact_contract_supported") is True
            and h48_oracle_contract.get("fast_optimal_oracle_implemented_for_every_valid_3x3_state") is True
            and h48_oracle_contract.get("empirical_fast_corpus_supported") is True
            and h48_contract_fast_runtime_flag_valid
            and all(bool(value) for value in h48_oracle_contract.get("source_checks", {}).values())
            and all(bool(value) for value in h48_oracle_contract.get("artifact_checks", {}).values())
            and all(bool(value) for value in h48_oracle_contract.get("empirical_checks", {}).values())
        ),
        "h48_capacity_stronger_table_plan_valid_if_present": not h48_capacity
        or (
            h48_capacity.get("profile") == "thesis"
            and h48_capacity.get("seed") == 2026
            and h48_capacity.get("strongest_local_oracle_solver") == "h48h7"
            and h48_capacity.get("next_missing_oracle_grade_solver") == "h48h8"
            and h48_capacity.get("h48_first_stronger_solver") == "h48h8"
            and h48_capacity.get("h48_fast_target_solver") == "h48h10"
            and h48_capacity.get("fast_runtime_proven_for_every_possible_state") is False
            and [row.get("solver") for row in h48_capacity_build_plan] == [
                "h48h8",
                "h48h9",
                "h48h10",
                "h48h11",
            ]
            and all("--require-safe" in str(row.get("recommended_command", "")) for row in h48_capacity_build_plan)
            and (h48_capacity.get("h48_stronger_table_generation_plan_options") or {}).get(
                "h48_generation_distribution_mode"
            )
            == "expected_constants"
            and (h48_capacity.get("h48_stronger_table_generation_plan_options") or {}).get(
                "h48_generation_mmap_sync_mode"
            )
            == "async"
            and (h48_capacity.get("h48_stronger_table_generation_plan_options") or {}).get(
                "h48_backend_extra_cflags"
            )
            == ["-march=native"]
            and all(
                "--skip-generation-distribution-scan" in str(row.get("recommended_command", ""))
                and "--mmap-sync-mode async" in str(row.get("recommended_command", ""))
                and "--backend-cflag=-march=native" in str(row.get("recommended_command", ""))
                for row in h48_capacity_build_plan
            )
            and h48_capacity_gate.get("target_solver") == "h48h10"
            and h48_capacity_gate.get("first_missing_ladder_solver") == "h48h8"
            and h48_capacity_gate.get("target_table_expected_size_bytes") == 30_336_314_216
            and h48_capacity_gate.get("target_upstream_benchmark_has_distance20_timing") is True
            and h48_capacity_gate.get("target_upstream_benchmark_has_superflip_timing") is True
            and h48_capacity_gate.get("can_claim_fast_oracle_for_every_possible_state") is False
        ),
        "h48_generation_probe_valid_if_present": not h48_generation_probe
        or (
            h48_generation_probe.get("profile") == "thesis"
            and h48_generation_probe.get("seed") == 2026
            and h48_generation_probe.get("solver") == "h48h8"
            and h48_generation_probe.get("status") == "timed_out"
            and h48_generation_probe.get("probe_completed") is True
            and h48_generation_probe.get("full_table_generated") is False
            and h48_generation_probe.get("partial_cleanup_status") == "deleted_partial_probe_file"
            and h48_generation_probe.get("expected_table_size_bytes") == 7_585_624_040
            and (h48_generation_probe.get("safety") or {}).get("safe_to_start") is False
        ),
        "h48_oracle_certification_trusted_preload_valid_if_present": not h48_oracle_certification_trusted_preload
        or (
            h48_oracle_certification_trusted_preload.get("profile") == "thesis"
            and h48_oracle_certification_trusted_preload.get("solver") == "h48h7"
            and h48_oracle_certification_trusted_preload.get("trusted_table") is True
            and h48_oracle_certification_trusted_preload.get("preload_table") is True
            and h48_oracle_certification_trusted_preload.get("passed") is True
            and h48_oracle_certification_trusted_preload.get("all_exact") is True
            and h48_oracle_certification_trusted_preload.get("all_expected_distances_match") is True
            and h48_oracle_certification_trusted_preload.get("within_runtime_target") is True
            and len(h48_oracle_certification_trusted_preload_rows) >= 4
            and any(
                row.get("case_id") == "superflip_distance_20"
                and row.get("status") == "exact"
                and row.get("solution_length") == 20
                and row.get("verified") is True
                and row.get("expected_distance_matches") is True
                for row in h48_oracle_certification_trusted_preload_rows
            )
            and all(
                row.get("status") == "exact" and row.get("verified") is True
                for row in h48_oracle_certification_trusted_preload_rows
            )
        ),
        "pocket_profile_is_thesis": bool(pocket) and pocket.get("profile") == "thesis",
        "pocket_complete_state_count_met": (
            bool(pocket_distribution)
            and pocket_distribution.get("complete") is True
            and pocket_distribution.get("state_count") == pocket.get("expected_state_count") == 3_674_160
        ),
        "pocket_representatives_verified_exact": bool(pocket_representatives) and all(
            row.get("status") == "exact" and row.get("verified") is True for row in pocket_representatives
        ),
    }
    return {
        "summary_present": summary is not None,
        "pocket_summary_present": pocket is not None,
        "table_metadata_present": table_metadata is not None,
        "corner_pdb_metadata_present": corner_pdb is not None,
        "edge_pdb_metadata_present": edge_pdb is not None,
        "h48_metadata_present": h48_metadata is not None,
        "h48_oracle_metadata_present": h48_oracle_metadata is not None,
        "e2e_3x3_present": e2e is not None,
        "optimal_3x3_present": optimal is not None,
        "external_optimal_stress_present": stress_optimal is not None,
        "h48_stress_present": h48_stress is not None,
        "h48_oracle_stress_present": h48_oracle_stress is not None,
        "h48_oracle_certification_present": h48_oracle_certification is not None,
        "h48_batch_overhead_present": h48_batch_overhead is not None,
        "h48_trusted_speedup_present": h48_trusted_speedup is not None,
        "h48_trusted_batch_overhead_present": h48_trusted_batch_overhead is not None,
        "h48_oracle_cli_trusted_present": h48_oracle_cli_trusted is not None,
        "h48_oracle_stream_trusted_present": h48_oracle_stream_trusted is not None,
        "h48_resident_oracle_present": h48_resident_oracle is not None,
        "h48_resident_certification_present": h48_resident_certification is not None,
        "fast_optimal_oracle_api_present": fast_optimal_oracle_api is not None,
        "nissy_core_direct_present": nissy_core_direct is not None,
        "portfolio_nissy_first_present": portfolio_nissy_first is not None,
        "portfolio_nissy_state_recovery_present": portfolio_nissy_state_recovery is not None,
        "portfolio_nissy_core_direct_state_present": portfolio_nissy_core_direct_state is not None,
        "portfolio_superflip_fallback_present": portfolio_superflip_fallback is not None,
        "portfolio_superflip_certificate_cache_present": portfolio_superflip_certificate_cache is not None,
        "race_optimal_oracle_present": race_optimal_oracle is not None,
        "race_nissy_core_direct_present": race_nissy_core_direct is not None,
        "resident_race_optimal_oracle_present": resident_race_optimal_oracle is not None,
        "resident_race_nissy_core_direct_present": resident_race_nissy_core_direct is not None,
        "universal_optimal_oracle_present": universal_optimal_oracle is not None,
        "universal_nissy_core_direct_present": universal_nissy_core_direct is not None,
        "universal_h48_symmetry_present": universal_h48_symmetry is not None,
        "universal_batch_oracle_corpus_present": universal_batch_oracle_corpus is not None,
        "universal_resident_h48_batch_present": universal_resident_h48_batch is not None,
        "universal_oracle_cli_present": universal_oracle_cli is not None,
        "universal_oracle_cli_broader_present": universal_oracle_cli_broader is not None,
        "universal_oracle_cli_adaptive_present": universal_oracle_cli_adaptive is not None,
        "universal_oracle_cli_expanded_present": universal_oracle_cli_expanded is not None,
        "universal_oracle_cli_h48_symmetry_present": universal_oracle_cli_h48_symmetry is not None,
        "universal_oracle_cli_live_no_shortcuts_present": universal_oracle_cli_live_no_shortcuts is not None,
        "universal_oracle_cli_live_no_shortcuts_broader_present": (
            universal_oracle_cli_live_no_shortcuts_broader is not None
        ),
        "universal_oracle_cli_known_distance_17_present": universal_oracle_cli_known_distance_17 is not None,
        "universal_oracle_cli_known_distance_adaptive_present": (
            universal_oracle_cli_known_distance_adaptive is not None
        ),
        "universal_oracle_cli_known_distance_19_present": universal_oracle_cli_known_distance_19 is not None,
        "universal_oracle_cli_known_distance_20_present": universal_oracle_cli_known_distance_20 is not None,
        "universal_oracle_cli_known_distance_20_offset1_present": (
            universal_oracle_cli_known_distance_20_offset1 is not None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_present": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass is not None
        ),
        "universal_symmetry_oracle_present": universal_symmetry_oracle is not None,
        "certificate_cache_inverse_closure_present": certificate_cache_inverse_closure is not None,
        "certificate_cache_symmetry_closure_present": certificate_cache_symmetry_closure is not None,
        "certificate_cache_expanded_symmetry_closure_present": (
            certificate_cache_expanded_symmetry_closure is not None
        ),
        "learned_certificate_cache_present": learned_certificate_cache is not None,
        "h48_oracle_contract_present": h48_oracle_contract is not None,
        "h48_capacity_present": h48_capacity is not None,
        "h48_generation_probe_present": h48_generation_probe is not None,
        "h48_oracle_certification_trusted_preload_present": (
            h48_oracle_certification_trusted_preload is not None
        ),
        "required_solvers": REQUIRED_THESIS_SOLVERS,
        "missing_solvers": missing_solvers,
        "non_applicable_primary_solvers": non_applicable_primary,
        "native_kociemba_verified_solutions": native_kociemba_verified,
        "native_thistlethwaite_verified_solutions": native_thistle_verified,
        "korf_statuses": sorted(korf_statuses),
        "generated_table_count": len(table_rows),
        "corner_pdb_state_count": corner_pdb.get("state_count") if corner_pdb else None,
        "corner_pdb_max_distance": corner_pdb.get("max_distance") if corner_pdb else None,
        "corner_pdb_size_bytes": corner_pdb.get("size_bytes") if corner_pdb else None,
        "edge_pdb_subset_count": len(edge_pdb_subsets),
        "edge_pdb_total_state_count": edge_pdb.get("total_state_count") if edge_pdb else None,
        "edge_pdb_total_size_bytes": edge_pdb.get("total_size_bytes") if edge_pdb else None,
        "edge_pdb_binary_size_bytes": edge_pdb_binary_size,
        "edge_cpdb_present": edge_cpdb is not None,
        "edge_cpdb_complete": edge_cpdb.get("complete") if edge_cpdb else None,
        "edge_cpdb_cost_partition_count": edge_cpdb.get("cost_partition_count") if edge_cpdb else None,
        "edge_cpdb_total_state_count": edge_cpdb.get("total_state_count") if edge_cpdb else None,
        "edge_cpdb_total_size_bytes": edge_cpdb.get("total_size_bytes") if edge_cpdb else None,
        "edge_cpdb_coverage_present": edge_cpdb_coverage is not None,
        "edge_cpdb_additive_improved_case_count": (
            edge_cpdb_coverage.get("additive_improved_case_count") if edge_cpdb_coverage else None
        ),
        "h48_solver": h48_metadata.get("solver") if h48_metadata else None,
        "h48_table_size_bytes": h48_metadata.get("table_size_bytes") if h48_metadata else None,
        "h48_oracle_solver": h48_oracle_metadata.get("solver") if h48_oracle_metadata else None,
        "h48_oracle_table_size_bytes": h48_oracle_metadata.get("table_size_bytes") if h48_oracle_metadata else None,
        "e2e_3x3_case_count": len(e2e_rows),
        "optimal_3x3_case_count": len(optimal_rows),
        "optimal_3x3_backend": optimal.get("backend") if optimal else None,
        "optimal_3x3_all_exact": optimal.get("all_exact") if optimal else None,
        "external_optimal_stress_case_count": len(stress_optimal_rows),
        "external_optimal_stress_all_exact": stress_optimal.get("all_exact") if stress_optimal else None,
        "h48_stress_case_count": len(h48_stress_rows),
        "h48_stress_all_exact": h48_stress.get("all_exact") if h48_stress else None,
        "h48_oracle_stress_case_count": len(h48_oracle_stress_rows),
        "h48_oracle_stress_all_exact": h48_oracle_stress.get("all_exact") if h48_oracle_stress else None,
        "h48_oracle_certification_case_count": len(h48_oracle_certification_rows),
        "h48_oracle_certification_passed": h48_oracle_certification.get("passed") if h48_oracle_certification else None,
        "h48_oracle_certification_max_runtime_seconds": h48_oracle_certification.get("max_runtime_seconds") if h48_oracle_certification else None,
        "h48_batch_overhead_repetitions": h48_batch_overhead.get("repetitions") if h48_batch_overhead else None,
        "h48_batch_overhead_speedup": h48_batch_overhead.get("throughput_speedup") if h48_batch_overhead else None,
        "h48_batch_overhead_batch_wall_seconds": h48_batch_overhead.get("batch_wall_seconds") if h48_batch_overhead else None,
        "h48_trusted_speedup": h48_trusted_speedup.get("trusted_speedup") if h48_trusted_speedup else None,
        "h48_trusted_checked_total_seconds": (
            h48_trusted_speedup.get("checked_total_seconds") if h48_trusted_speedup else None
        ),
        "h48_trusted_total_seconds": (
            h48_trusted_speedup.get("trusted_total_seconds") if h48_trusted_speedup else None
        ),
        "h48_trusted_batch_overhead_speedup": (
            h48_trusted_batch_overhead.get("throughput_speedup") if h48_trusted_batch_overhead else None
        ),
        "h48_oracle_cli_trusted_wrapper_wall_seconds": (
            h48_oracle_cli_trusted.get("wrapper_wall_seconds") if h48_oracle_cli_trusted else None
        ),
        "h48_oracle_stream_trusted_wrapper_wall_seconds": (
            h48_oracle_stream_trusted.get("wrapper_wall_seconds") if h48_oracle_stream_trusted else None
        ),
        "h48_resident_oracle_speedup": (
            h48_resident_oracle.get("resident_speedup") if h48_resident_oracle else None
        ),
        "h48_resident_certification_max_runtime_seconds": (
            h48_resident_certification.get("max_runtime_seconds") if h48_resident_certification else None
        ),
        "h48_resident_certification_resident_wall_seconds": (
            h48_resident_certification.get("resident_wall_seconds") if h48_resident_certification else None
        ),
        "fast_optimal_oracle_api_case_count": len(fast_optimal_oracle_api_rows),
        "fast_optimal_oracle_api_max_runtime_seconds": (
            fast_optimal_oracle_api.get("max_runtime_seconds") if fast_optimal_oracle_api else None
        ),
        "fast_optimal_oracle_api_p95_runtime_seconds": (
            fast_optimal_oracle_api.get("p95_runtime_seconds") if fast_optimal_oracle_api else None
        ),
        "nissy_core_direct_case_count": len(nissy_core_direct_rows),
        "nissy_core_direct_max_runtime_seconds": max(
            [float(row.get("runtime_seconds", 0.0) or 0.0) for row in nissy_core_direct_rows],
            default=None,
        ),
        "portfolio_nissy_first_case_count": len(portfolio_nissy_first_rows),
        "portfolio_nissy_first_max_runtime_seconds": (
            portfolio_nissy_first.get("max_runtime_seconds") if portfolio_nissy_first else None
        ),
        "portfolio_nissy_state_recovery_case_count": len(portfolio_nissy_state_recovery_rows),
        "portfolio_nissy_state_recovery_max_runtime_seconds": (
            portfolio_nissy_state_recovery.get("max_runtime_seconds") if portfolio_nissy_state_recovery else None
        ),
        "portfolio_nissy_core_direct_state_case_count": len(portfolio_nissy_core_direct_state_rows),
        "portfolio_nissy_core_direct_state_max_runtime_seconds": (
            portfolio_nissy_core_direct_state.get("max_runtime_seconds")
            if portfolio_nissy_core_direct_state
            else None
        ),
        "portfolio_superflip_fallback_runtime_seconds": (
            portfolio_superflip_fallback.get("max_runtime_seconds") if portfolio_superflip_fallback else None
        ),
        "portfolio_superflip_certificate_cache_runtime_seconds": (
            portfolio_superflip_certificate_cache.get("max_runtime_seconds")
            if portfolio_superflip_certificate_cache
            else None
        ),
        "race_optimal_oracle_case_count": len(race_optimal_oracle_rows),
        "race_optimal_oracle_max_runtime_seconds": (
            race_optimal_oracle.get("max_runtime_seconds") if race_optimal_oracle else None
        ),
        "race_nissy_core_direct_case_count": len(race_nissy_core_direct_rows),
        "race_nissy_core_direct_max_runtime_seconds": (
            race_nissy_core_direct.get("max_runtime_seconds")
            if race_nissy_core_direct
            else None
        ),
        "resident_race_optimal_oracle_case_count": len(resident_race_optimal_oracle_rows),
        "resident_race_optimal_oracle_max_runtime_seconds": (
            resident_race_optimal_oracle.get("max_runtime_seconds")
            if resident_race_optimal_oracle
            else None
        ),
        "resident_race_optimal_oracle_h48_reuse_wall_seconds": (
            resident_race_optimal_oracle.get("h48_reuse_wall_seconds")
            if resident_race_optimal_oracle
            else None
        ),
        "resident_race_nissy_core_direct_case_count": len(resident_race_nissy_core_direct_rows),
        "resident_race_nissy_core_direct_max_runtime_seconds": (
            resident_race_nissy_core_direct.get("max_runtime_seconds")
            if resident_race_nissy_core_direct
            else None
        ),
        "universal_optimal_oracle_case_count": len(universal_optimal_oracle_rows),
        "universal_optimal_oracle_max_runtime_seconds": (
            universal_optimal_oracle.get("max_runtime_seconds") if universal_optimal_oracle else None
        ),
        "universal_optimal_oracle_selected_backends": (
            universal_optimal_oracle.get("selected_backends") if universal_optimal_oracle else None
        ),
        "universal_nissy_core_direct_case_count": len(universal_nissy_core_direct_rows),
        "universal_nissy_core_direct_max_runtime_seconds": (
            universal_nissy_core_direct.get("max_runtime_seconds")
            if universal_nissy_core_direct
            else None
        ),
        "universal_nissy_core_direct_nested_backends": (
            universal_nissy_core_direct.get("nested_selected_backends")
            if universal_nissy_core_direct
            else None
        ),
        "universal_h48_symmetry_case_count": len(universal_h48_symmetry_rows),
        "universal_h48_symmetry_max_runtime_seconds": (
            universal_h48_symmetry.get("max_runtime_seconds")
            if universal_h48_symmetry
            else None
        ),
        "universal_h48_symmetry_selected_backends": (
            universal_h48_symmetry.get("selected_backends")
            if universal_h48_symmetry
            else None
        ),
        "universal_batch_oracle_corpus_case_count": len(universal_batch_oracle_corpus_rows),
        "universal_batch_oracle_corpus_max_runtime_seconds": (
            universal_batch_oracle_corpus.get("max_runtime_seconds")
            if universal_batch_oracle_corpus
            else None
        ),
        "universal_batch_oracle_corpus_nested_backends": (
            universal_batch_oracle_corpus.get("nested_selected_backends")
            if universal_batch_oracle_corpus
            else None
        ),
        "universal_resident_h48_batch_case_count": len(universal_resident_h48_batch_rows),
        "universal_resident_h48_batch_max_runtime_seconds": (
            universal_resident_h48_batch.get("max_runtime_seconds")
            if universal_resident_h48_batch
            else None
        ),
        "universal_resident_h48_batch_nested_backends": (
            universal_resident_h48_batch.get("nested_selected_backends")
            if universal_resident_h48_batch
            else None
        ),
        "universal_oracle_cli_case_count": len(universal_oracle_cli_rows),
        "universal_oracle_cli_max_runtime_seconds": (
            universal_oracle_cli.get("max_runtime_seconds")
            if universal_oracle_cli
            else None
        ),
        "universal_oracle_cli_resident_h48_batch_rows": (
            universal_oracle_cli.get("resident_h48_batch_rows")
            if universal_oracle_cli
            else None
        ),
        "universal_oracle_cli_selected_backends": (
            universal_oracle_cli.get("selected_backends")
            if universal_oracle_cli
            else None
        ),
        "universal_oracle_cli_broader_case_count": len(universal_oracle_cli_broader_rows),
        "universal_oracle_cli_broader_max_runtime_seconds": (
            universal_oracle_cli_broader.get("max_runtime_seconds")
            if universal_oracle_cli_broader
            else None
        ),
        "universal_oracle_cli_broader_wrapper_wall_seconds": (
            universal_oracle_cli_broader.get("wrapper_wall_seconds")
            if universal_oracle_cli_broader
            else None
        ),
        "universal_oracle_cli_broader_resident_h48_batch_rows": (
            universal_oracle_cli_broader.get("resident_h48_batch_rows")
            if universal_oracle_cli_broader
            else None
        ),
        "universal_oracle_cli_broader_resident_h48_fallback_rows": (
            universal_oracle_cli_broader.get("resident_h48_fallback_rows")
            if universal_oracle_cli_broader
            else None
        ),
        "universal_oracle_cli_broader_selected_backends": (
            universal_oracle_cli_broader.get("selected_backends")
            if universal_oracle_cli_broader
            else None
        ),
        "universal_oracle_cli_adaptive_case_count": len(universal_oracle_cli_adaptive_rows),
        "universal_oracle_cli_adaptive_max_runtime_seconds": (
            universal_oracle_cli_adaptive.get("max_runtime_seconds")
            if universal_oracle_cli_adaptive
            else None
        ),
        "universal_oracle_cli_adaptive_wrapper_wall_seconds": (
            universal_oracle_cli_adaptive.get("wrapper_wall_seconds")
            if universal_oracle_cli_adaptive
            else None
        ),
        "universal_oracle_cli_adaptive_portfolio_prepass_rows": (
            universal_oracle_cli_adaptive.get("portfolio_prepass_rows")
            if universal_oracle_cli_adaptive
            else None
        ),
        "universal_oracle_cli_adaptive_selected_backends": (
            universal_oracle_cli_adaptive.get("selected_backends")
            if universal_oracle_cli_adaptive
            else None
        ),
        "universal_oracle_cli_expanded_case_count": len(universal_oracle_cli_expanded_rows),
        "universal_oracle_cli_expanded_hard_case_count": (
            universal_oracle_cli_expanded.get("hard_case_count")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_expanded_max_runtime_seconds": (
            universal_oracle_cli_expanded.get("max_runtime_seconds")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_expanded_wrapper_wall_seconds": (
            universal_oracle_cli_expanded.get("wrapper_wall_seconds")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_expanded_portfolio_prepass_rows": (
            universal_oracle_cli_expanded.get("portfolio_prepass_rows")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_expanded_selected_backends": (
            universal_oracle_cli_expanded.get("selected_backends")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_expanded_contains_superflip": (
            universal_oracle_cli_expanded.get("contains_superflip")
            if universal_oracle_cli_expanded
            else None
        ),
        "universal_oracle_cli_h48_symmetry_case_count": len(universal_oracle_cli_h48_symmetry_rows),
        "universal_oracle_cli_h48_symmetry_max_runtime_seconds": (
            universal_oracle_cli_h48_symmetry.get("max_runtime_seconds")
            if universal_oracle_cli_h48_symmetry
            else None
        ),
        "universal_oracle_cli_h48_symmetry_wrapper_wall_seconds": (
            universal_oracle_cli_h48_symmetry.get("wrapper_wall_seconds")
            if universal_oracle_cli_h48_symmetry
            else None
        ),
        "universal_oracle_cli_h48_symmetry_rows": (
            universal_oracle_cli_h48_symmetry.get("resident_h48_symmetry_rows")
            if universal_oracle_cli_h48_symmetry
            else None
        ),
        "universal_oracle_cli_h48_symmetry_selected_backends": (
            universal_oracle_cli_h48_symmetry.get("selected_backends")
            if universal_oracle_cli_h48_symmetry
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_case_count": len(
            universal_oracle_cli_live_no_shortcuts_rows
        ),
        "universal_oracle_cli_live_no_shortcuts_max_runtime_seconds": (
            universal_oracle_cli_live_no_shortcuts.get("max_runtime_seconds")
            if universal_oracle_cli_live_no_shortcuts
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_wrapper_wall_seconds": (
            universal_oracle_cli_live_no_shortcuts.get("wrapper_wall_seconds")
            if universal_oracle_cli_live_no_shortcuts
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_selected_backends": (
            universal_oracle_cli_live_no_shortcuts.get("selected_backends")
            if universal_oracle_cli_live_no_shortcuts
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_case_count": len(
            universal_oracle_cli_live_no_shortcuts_broader_rows
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_depths": (
            universal_oracle_cli_live_no_shortcuts_broader.get("depths")
            if universal_oracle_cli_live_no_shortcuts_broader
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_max_runtime_seconds": (
            universal_oracle_cli_live_no_shortcuts_broader.get("max_runtime_seconds")
            if universal_oracle_cli_live_no_shortcuts_broader
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_wrapper_wall_seconds": (
            universal_oracle_cli_live_no_shortcuts_broader.get("wrapper_wall_seconds")
            if universal_oracle_cli_live_no_shortcuts_broader
            else None
        ),
        "universal_oracle_cli_live_no_shortcuts_broader_selected_backends": (
            universal_oracle_cli_live_no_shortcuts_broader.get("selected_backends")
            if universal_oracle_cli_live_no_shortcuts_broader
            else None
        ),
        "universal_oracle_cli_known_distance_17_case_count": len(
            universal_oracle_cli_known_distance_17_rows
        ),
        "universal_oracle_cli_known_distance_17_distances": (
            universal_oracle_cli_known_distance_17.get("nissy_benchmark_distances_present")
            if universal_oracle_cli_known_distance_17
            else None
        ),
        "universal_oracle_cli_known_distance_17_max_backend_solve_seconds": (
            universal_oracle_cli_known_distance_17.get("max_backend_solve_seconds")
            if universal_oracle_cli_known_distance_17
            else None
        ),
        "universal_oracle_cli_known_distance_adaptive_case_count": len(
            universal_oracle_cli_known_distance_adaptive_rows
        ),
        "universal_oracle_cli_known_distance_adaptive_distances": (
            universal_oracle_cli_known_distance_adaptive.get("nissy_benchmark_distances_present")
            if universal_oracle_cli_known_distance_adaptive
            else None
        ),
        "universal_oracle_cli_known_distance_adaptive_max_runtime_seconds": (
            universal_oracle_cli_known_distance_adaptive.get("max_runtime_seconds")
            if universal_oracle_cli_known_distance_adaptive
            else None
        ),
        "universal_oracle_cli_known_distance_adaptive_wrapper_wall_seconds": (
            universal_oracle_cli_known_distance_adaptive.get("wrapper_wall_seconds")
            if universal_oracle_cli_known_distance_adaptive
            else None
        ),
        "universal_oracle_cli_known_distance_adaptive_selected_backends": (
            universal_oracle_cli_known_distance_adaptive.get("selected_backends")
            if universal_oracle_cli_known_distance_adaptive
            else None
        ),
        "universal_oracle_cli_known_distance_19_case_count": len(
            universal_oracle_cli_known_distance_19_rows
        ),
        "universal_oracle_cli_known_distance_19_distances": (
            universal_oracle_cli_known_distance_19.get("nissy_benchmark_distances_present")
            if universal_oracle_cli_known_distance_19
            else None
        ),
        "universal_oracle_cli_known_distance_19_max_runtime_seconds": (
            universal_oracle_cli_known_distance_19.get("max_runtime_seconds")
            if universal_oracle_cli_known_distance_19
            else None
        ),
        "universal_oracle_cli_known_distance_19_wrapper_wall_seconds": (
            universal_oracle_cli_known_distance_19.get("wrapper_wall_seconds")
            if universal_oracle_cli_known_distance_19
            else None
        ),
        "universal_oracle_cli_known_distance_19_max_backend_solve_seconds": (
            universal_oracle_cli_known_distance_19.get("max_backend_solve_seconds")
            if universal_oracle_cli_known_distance_19
            else None
        ),
        "universal_oracle_cli_known_distance_19_selected_backends": (
            universal_oracle_cli_known_distance_19.get("selected_backends")
            if universal_oracle_cli_known_distance_19
            else None
        ),
        "universal_oracle_cli_known_distance_20_case_count": len(
            universal_oracle_cli_known_distance_20_rows
        ),
        "universal_oracle_cli_known_distance_20_distances": (
            universal_oracle_cli_known_distance_20.get("nissy_benchmark_distances_present")
            if universal_oracle_cli_known_distance_20
            else None
        ),
        "universal_oracle_cli_known_distance_20_max_runtime_seconds": (
            universal_oracle_cli_known_distance_20.get("max_runtime_seconds")
            if universal_oracle_cli_known_distance_20
            else None
        ),
        "universal_oracle_cli_known_distance_20_wrapper_wall_seconds": (
            universal_oracle_cli_known_distance_20.get("wrapper_wall_seconds")
            if universal_oracle_cli_known_distance_20
            else None
        ),
        "universal_oracle_cli_known_distance_20_max_backend_solve_seconds": (
            universal_oracle_cli_known_distance_20.get("max_backend_solve_seconds")
            if universal_oracle_cli_known_distance_20
            else None
        ),
        "universal_oracle_cli_known_distance_20_selected_backends": (
            universal_oracle_cli_known_distance_20.get("selected_backends")
            if universal_oracle_cli_known_distance_20
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_case_count": len(
            universal_oracle_cli_known_distance_20_offset1_rows
        ),
        "universal_oracle_cli_known_distance_20_offset1_distances": (
            universal_oracle_cli_known_distance_20_offset1.get("nissy_benchmark_distances_present")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_max_runtime_seconds": (
            universal_oracle_cli_known_distance_20_offset1.get("max_runtime_seconds")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_wrapper_wall_seconds": (
            universal_oracle_cli_known_distance_20_offset1.get("wrapper_wall_seconds")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_max_backend_solve_seconds": (
            universal_oracle_cli_known_distance_20_offset1.get("max_backend_solve_seconds")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_selected_backends": (
            universal_oracle_cli_known_distance_20_offset1.get("selected_backends")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_benchmark_offset_per_distance": (
            universal_oracle_cli_known_distance_20_offset1.get("benchmark_offset_per_distance")
            if universal_oracle_cli_known_distance_20_offset1
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_case_count": len(
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_rows
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_distances": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "nissy_benchmark_distances_present"
            )
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_runtime_seconds": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("max_runtime_seconds")
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_wrapper_wall_seconds": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("wrapper_wall_seconds")
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_max_backend_solve_seconds": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "max_backend_solve_seconds"
            )
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_selected_backends": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get("selected_backends")
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_oracle_cli_known_distance_20_offset1_trimmed_prepass_timeout_seconds": (
            universal_oracle_cli_known_distance_20_offset1_trimmed_prepass.get(
                "portfolio_prepass_timeout_seconds"
            )
            if universal_oracle_cli_known_distance_20_offset1_trimmed_prepass
            else None
        ),
        "universal_symmetry_oracle_case_count": len(universal_symmetry_oracle_rows),
        "universal_symmetry_oracle_max_runtime_seconds": (
            universal_symmetry_oracle.get("max_runtime_seconds")
            if universal_symmetry_oracle
            else None
        ),
        "universal_symmetry_oracle_selected_backends": (
            universal_symmetry_oracle.get("selected_backends")
            if universal_symmetry_oracle
            else None
        ),
        "certificate_cache_inverse_closure_case_count": len(certificate_cache_inverse_closure_rows),
        "certificate_cache_inverse_closure_max_runtime_seconds": (
            certificate_cache_inverse_closure.get("max_runtime_seconds")
            if certificate_cache_inverse_closure
            else None
        ),
        "certificate_cache_symmetry_closure_case_count": len(certificate_cache_symmetry_closure_rows),
        "certificate_cache_symmetry_closure_max_runtime_seconds": (
            certificate_cache_symmetry_closure.get("max_runtime_seconds")
            if certificate_cache_symmetry_closure
            else None
        ),
        "certificate_cache_symmetry_closure_derivation_counts": (
            certificate_cache_symmetry_closure.get("derivation_counts")
            if certificate_cache_symmetry_closure
            else None
        ),
        "certificate_cache_expanded_symmetry_closure_case_count": (
            len(certificate_cache_expanded_symmetry_closure_rows)
        ),
        "certificate_cache_expanded_symmetry_closure_max_runtime_seconds": (
            certificate_cache_expanded_symmetry_closure.get("max_runtime_seconds")
            if certificate_cache_expanded_symmetry_closure
            else None
        ),
        "certificate_cache_expanded_symmetry_closure_derivation_counts": (
            certificate_cache_expanded_symmetry_closure.get("derivation_counts")
            if certificate_cache_expanded_symmetry_closure
            else None
        ),
        "learned_certificate_cache_case_count": len(learned_certificate_cache_rows),
        "learned_certificate_cache_jsonl_row_count": (
            learned_certificate_cache.get("learned_jsonl_row_count")
            if learned_certificate_cache
            else None
        ),
        "learned_certificate_cache_max_first_runtime_seconds": (
            learned_certificate_cache.get("max_first_runtime_seconds")
            if learned_certificate_cache
            else None
        ),
        "learned_certificate_cache_max_replay_runtime_seconds": (
            learned_certificate_cache.get("max_replay_runtime_seconds")
            if learned_certificate_cache
            else None
        ),
        "h48_oracle_contract_all_state_exact_supported": (
            h48_oracle_contract.get("all_state_exact_contract_supported") if h48_oracle_contract else None
        ),
        "h48_oracle_contract_fast_optimal_oracle_implemented": (
            h48_oracle_contract.get("fast_optimal_oracle_implemented_for_every_valid_3x3_state")
            if h48_oracle_contract
            else None
        ),
        "h48_oracle_contract_every_state_fast_runtime_proven": (
            h48_oracle_contract.get("fast_runtime_proven_for_every_possible_state")
            if h48_oracle_contract
            else None
        ),
        "h48_oracle_contract_cloud_runtime_proof_passed": (
            h48_contract_cloud_runtime_proof.get("passed") if h48_oracle_contract else None
        ),
        "h48_oracle_contract_cloud_runtime_claim_scope": (
            h48_contract_cloud_runtime_proof.get("claim_scope") if h48_oracle_contract else None
        ),
        "h48_capacity_stronger_table_plan_solvers": [
            row.get("solver") for row in h48_capacity_build_plan
        ],
        "h48_capacity_can_claim_every_state_fast": (
            h48_capacity_gate.get("can_claim_fast_oracle_for_every_possible_state")
            if h48_capacity_gate
            else None
        ),
        "h48_capacity_safe_to_start_h48h8_generation_now": (
            h48_capacity.get("safe_to_start_h48h8_generation_now") if h48_capacity else None
        ),
        "h48_capacity_fast_target_solver": (
            h48_capacity.get("h48_fast_target_solver") if h48_capacity else None
        ),
        "h48_capacity_fast_target_safe_to_generate_now": (
            (h48_capacity.get("h48_fast_target_generation_safety") or {}).get("safe_to_start")
            if h48_capacity
            else None
        ),
        "h48_capacity_fast_target_has_upstream_distance20_timing": (
            h48_capacity_gate.get("target_upstream_benchmark_has_distance20_timing")
            if h48_capacity_gate
            else None
        ),
        "h48_generation_probe_status": h48_generation_probe.get("status") if h48_generation_probe else None,
        "h48_generation_probe_runtime_seconds": (
            h48_generation_probe.get("runtime_seconds") if h48_generation_probe else None
        ),
        "h48_generation_probe_partial_allocated_size_bytes": (
            h48_generation_probe.get("partial_allocated_size_bytes_before_cleanup")
            if h48_generation_probe
            else None
        ),
        "h48_generation_probe_latest_processed_short_cubes": (
            h48_generation_probe.get("latest_processed_short_cubes") if h48_generation_probe else None
        ),
        "h48_oracle_certification_trusted_preload_max_runtime_seconds": (
            h48_oracle_certification_trusted_preload.get("max_runtime_seconds")
            if h48_oracle_certification_trusted_preload
            else None
        ),
        "pocket_state_count": pocket_distribution.get("state_count") if pocket_distribution else None,
        "pocket_max_distance": pocket_distribution.get("max_distance") if pocket_distribution else None,
        "pocket_representative_count": len(pocket_representatives),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _front_matter_placeholders(paths: list[Path] | None = None) -> list[dict[str, object]]:
    """Return unresolved administrative metadata placeholders.

    These placeholders are allowed by the acceptance file for review drafts,
    but they must be visible because they block a final submission-ready claim.
    """

    findings: list[dict[str, object]] = []
    search_paths = paths or [THESIS / "main.tex", THESIS / "chapters" / "00_front_matter.tex"]
    for path in search_paths:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for field, pattern in FRONT_MATTER_PLACEHOLDER_PATTERNS.items():
                if pattern.search(line):
                    findings.append({
                        "field": field,
                        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                        "line": line_no,
                        "text": line.strip()[:220],
                    })
    return findings


def _bibliography_audit(
    tex_paths: list[Path] | None = None,
    bib_path: Path | None = None,
    research_notes_path: Path | None = None,
) -> dict[str, object]:
    """Check that bibliography keys are cited and backed by research notes."""

    search_paths = tex_paths or _tex_files()
    references_path = bib_path or THESIS / "references.bib"
    notes_path = research_notes_path or ROOT / "docs" / "research_notes.md"

    bib_text = references_path.read_text(encoding="utf-8") if references_path.exists() else ""
    bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)", bib_text))

    citation_keys: set[str] = set()
    citation_pattern = re.compile(
        r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|nocite)"
        r"(?:\[[^\]]*\]){0,2}\{([^}]+)\}"
    )
    for path in search_paths:
        if not path.exists():
            continue
        for match in citation_pattern.finditer(path.read_text(encoding="utf-8")):
            for key in match.group(1).split(","):
                cleaned = key.strip()
                if cleaned and cleaned != "*":
                    citation_keys.add(cleaned)

    research_note_keys: set[str] = set()
    if notes_path.exists():
        for line in notes_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("BibTeX key"):
                research_note_keys.update(re.findall(r"`([^`]+)`", line))

    missing_bib_entries = sorted(citation_keys - bib_keys)
    uncited_bib_entries = sorted(bib_keys - citation_keys)
    missing_research_notes = sorted(bib_keys - research_note_keys)
    note_keys_without_bib = sorted(research_note_keys - bib_keys)

    checks = {
        "minimum_verified_source_count_met": len(bib_keys) >= 20,
        "all_citations_have_bib_entries": not missing_bib_entries,
        "all_bib_entries_are_cited": not uncited_bib_entries,
        "all_bib_entries_have_research_notes": not missing_research_notes,
    }
    return {
        "bib_entry_count": len(bib_keys),
        "citation_key_count": len(citation_keys),
        "research_note_key_count": len(research_note_keys),
        "bib_keys": sorted(bib_keys),
        "citation_keys": sorted(citation_keys),
        "research_note_keys": sorted(research_note_keys),
        "missing_bib_entries": missing_bib_entries,
        "uncited_bib_entries": uncited_bib_entries,
        "missing_research_notes": missing_research_notes,
        "research_note_keys_without_bib": note_keys_without_bib,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _handoff_document_audit(root: Path = ROOT) -> dict[str, object]:
    """Check that unresolved final metadata has concrete handoff documents."""

    missing_documents: list[str] = []
    missing_terms: dict[str, list[str]] = {}
    for relative, terms in REQUIRED_HANDOFF_DOCUMENTS.items():
        path = root / relative
        if not path.exists():
            missing_documents.append(relative)
            missing_terms[relative] = terms
            continue
        text = path.read_text(encoding="utf-8")
        missing_for_doc = [term for term in terms if term not in text]
        if missing_for_doc:
            missing_terms[relative] = missing_for_doc

    return {
        "required_documents": sorted(REQUIRED_HANDOFF_DOCUMENTS),
        "missing_documents": missing_documents,
        "missing_terms": missing_terms,
        "passed": not missing_documents and not missing_terms,
    }


def _supervisor_approval_audit(root: Path = ROOT) -> dict[str, object]:
    """Check whether final supervisor/Secretariat approval evidence exists."""

    path = root / SUPERVISOR_APPROVAL_RECORD
    if not path.exists():
        return {
            "path": SUPERVISOR_APPROVAL_RECORD,
            "exists": False,
            "missing_terms": REQUIRED_SUPERVISOR_APPROVAL_TERMS,
            "placeholder_findings": [],
            "passed": False,
        }

    text = path.read_text(encoding="utf-8")
    missing_terms = [term for term in REQUIRED_SUPERVISOR_APPROVAL_TERMS if term not in text]
    placeholder_findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if SUPERVISOR_APPROVAL_PLACEHOLDER_PATTERN.search(line):
            placeholder_findings.append({"line": line_no, "text": line.strip()[:220]})

    return {
        "path": SUPERVISOR_APPROVAL_RECORD,
        "exists": True,
        "missing_terms": missing_terms,
        "placeholder_findings": placeholder_findings,
        "passed": not missing_terms and not placeholder_findings,
    }


def _submission_blockers(
    front_matter_placeholders: list[dict[str, object]],
    bibliography: dict[str, object] | None = None,
    repository: dict[str, object] | None = None,
    implementation: dict[str, object] | None = None,
    cli: dict[str, object] | None = None,
    solver_evidence: dict[str, object] | None = None,
    handoff_documents: dict[str, object] | None = None,
    supervisor_approval: dict[str, object] | None = None,
    pdf_artifacts: dict[str, object] | None = None,
    git_provenance: dict[str, object] | None = None,
    third_party_notices: dict[str, object] | None = None,
    topic_brief_artifacts: dict[str, object] | None = None,
    backend_identity: dict[str, object] | None = None,
    source_state: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Return human/supervisor inputs that block final submission readiness."""

    blockers: list[dict[str, object]] = []
    if front_matter_placeholders:
        fields = sorted({str(finding["field"]) for finding in front_matter_placeholders})
        blockers.append({
            "id": "front_matter_metadata_placeholders",
            "status": "supervisor_or_secretariat_required",
            "description": "Final ECE front-matter metadata still contains placeholders.",
            "fields": [SUPERVISOR_REQUIRED_FIELD_LABELS.get(field, field) for field in fields],
            "evidence_count": len(front_matter_placeholders),
        })
    if bibliography is not None and not bibliography["passed"]:
        blockers.append({
            "id": "bibliography_consistency",
            "status": "repository_required",
            "description": "Bibliography, citation, or research-note consistency checks failed.",
            "missing_bib_entries": bibliography["missing_bib_entries"],
            "uncited_bib_entries": bibliography["uncited_bib_entries"],
            "missing_research_notes": bibliography["missing_research_notes"],
        })
    if repository is not None and not repository["passed"]:
        blockers.append({
            "id": "repository_structure",
            "status": "repository_required",
            "description": "Required repository paths are missing.",
            "missing": repository["missing"],
        })
    if implementation is not None and not implementation["passed"]:
        blockers.append({
            "id": "implementation_artifacts",
            "status": "repository_required",
            "description": "Required implementation source paths or status labels are missing.",
            "missing_source_paths": implementation["missing_source_paths"],
            "missing_status_labels": implementation["missing_status_labels"],
        })
    if cli is not None and not cli["passed"]:
        blockers.append({
            "id": "cli_commands",
            "status": "repository_required",
            "description": "Required CLI commands are missing or CLI help failed.",
            "missing_commands": cli["missing_commands"],
            "return_code": cli["return_code"],
        })
    if solver_evidence is not None and not solver_evidence["passed"]:
        blockers.append({
            "id": "solver_result_evidence",
            "status": "repository_required",
            "description": "Required thesis-profile solver, table, or Pocket Cube evidence is missing.",
            "checks": solver_evidence["checks"],
            "missing_solvers": solver_evidence["missing_solvers"],
        })
    if handoff_documents is not None and not handoff_documents["passed"]:
        blockers.append({
            "id": "handoff_documentation",
            "status": "repository_required",
            "description": "Final metadata blockers are missing concrete handoff documentation.",
            "missing_documents": handoff_documents["missing_documents"],
            "missing_terms": handoff_documents["missing_terms"],
        })
    if supervisor_approval is not None and not supervisor_approval["passed"]:
        blockers.append({
            "id": "supervisor_approval_evidence",
            "status": "supervisor_or_secretariat_required",
            "description": (
                "Final approval evidence for front-matter/bibliography style "
                "and scoped solver claims is missing or incomplete."
            ),
            "path": supervisor_approval["path"],
            "exists": supervisor_approval["exists"],
            "missing_terms": supervisor_approval["missing_terms"],
            "placeholder_findings": supervisor_approval["placeholder_findings"],
        })
    if pdf_artifacts is not None and not pdf_artifacts["passed"]:
        blockers.append({
            "id": "pdf_artifact_identity",
            "status": "repository_required",
            "description": "Root main.pdf and thesis/main.pdf do not identify the same final PDF artifact.",
            "root_sha256": pdf_artifacts["root_sha256"],
            "thesis_sha256": pdf_artifacts["thesis_sha256"],
        })
    if git_provenance is not None and not git_provenance["passed"]:
        blockers.append({
            "id": "final_artifact_git_provenance",
            "status": "repository_required",
            "description": "Final artifact provenance is not tied to a clean committed checkout.",
            "head_sha": git_provenance["head_sha"],
            "dirty_path_count": git_provenance["dirty_path_count"],
            "dirty_paths_sample": git_provenance["dirty_paths_sample"],
        })
    if third_party_notices is not None and not third_party_notices["passed"]:
        blockers.append({
            "id": "third_party_notices",
            "status": "repository_required",
            "description": "Third-party public-solver notices are missing or incomplete.",
            "path": third_party_notices["path"],
            "missing_terms": third_party_notices["missing_terms"],
        })
    if topic_brief_artifacts is not None and not topic_brief_artifacts["passed"]:
        blockers.append({
            "id": "topic_brief_artifact_evidence",
            "status": "repository_required",
            "description": "Topic-brief distance-recognition or heuristic evidence artifacts are missing or stale.",
            "checks": topic_brief_artifacts["checks"],
        })
    if backend_identity is not None and not backend_identity["passed"]:
        blockers.append({
            "id": "backend_identity",
            "status": "repository_required",
            "description": "Public-solver-derived backend identity is not consistently visible in metadata/source/thesis.",
            "checks": backend_identity["checks"],
            "metadata": backend_identity["metadata"],
        })
    if source_state is not None and not source_state["passed"]:
        blockers.append({
            "id": "source_snapshot_reproducibility",
            "status": "repository_required",
            "description": (
                "Final generated metadata must come from a clean committed checkout or approved immutable source archive; "
                "current evidence includes no-commit, dirty, or otherwise non-reproducible source-state records."
            ),
            "current_source_state": source_state["current_source_state"],
            "non_reproducible_entry_count": source_state["non_reproducible_entry_count"],
            "unique_non_reproducible_states": source_state["unique_non_reproducible_states"],
            "examples": source_state["non_reproducible_examples"][:10],
            "regeneration_plan": source_state["regeneration_plan"],
        })
    return blockers


def _generated_artifacts() -> dict[str, object]:
    required = [
        "results/raw/benchmarks_seed_2026_thesis.jsonl",
        "results/processed/summary_seed_2026_thesis.json",
        "results/raw/pocket_cube_distribution_seed_2026_thesis.json",
        "results/processed/pocket_cube_summary_seed_2026_thesis.json",
        "results/processed/table_metadata_thesis_seed_2026.json",
        "results/processed/corner_pdb_metadata_seed_2026_thesis.json",
        "results/processed/edge_pdb_metadata_seed_2026_thesis.json",
        "results/processed/edge_pdb_coverage_seed_2026_thesis_expanded8.json",
        "results/processed/edge_cpdb_metadata_seed_2026_thesis.json",
        "results/processed/edge_cpdb_metadata_urf_subset_0_1_2_3_4_5_seed_2026_thesis.json",
        "results/processed/edge_cpdb_metadata_dlb_subset_6_7_8_9_10_11_seed_2026_thesis.json",
        "results/processed/edge_pdb_coverage_seed_2026_thesis_cpdb_additive.json",
        "results/processed/distance_recognition_corpus_seed_2026_thesis_topic_brief_bullet2.json",
        "results/processed/heuristic_comparison_seed_2026_thesis.json",
        "results/processed/heuristic_comparison_seed_2026_thesis.csv",
        "results/processed/h48_metadata_seed_2026_thesis_h48h0.json",
        "results/processed/h48_metadata_seed_2026_thesis_h48h7.json",
        "results/processed/e2e_3x3_seed_2026_thesis.json",
        "results/processed/optimal_3x3_seed_2026_thesis.json",
        "results/processed/optimal_3x3_seed_2026_stress_h48h0.json",
        "results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json",
        "results/processed/h48_oracle_certification_seed_2026_thesis.json",
        "results/processed/h48_batch_overhead_seed_2026_thesis.json",
        "results/processed/h48_oracle_cli_seed_2026_thesis.json",
        "results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json",
        "results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json",
        "results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json",
        "results/processed/h48_oracle_stream_seed_2026_thesis_trusted.json",
        "results/processed/h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json",
        "results/processed/h48_resident_certification_seed_2026_thesis_h48h7_trusted.json",
        "results/processed/fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json",
        "results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json",
        "results/processed/h48_capacity_seed_2026_thesis_lowload.json",
        "results/processed/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.json",
        "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_goal.json",
        "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_cornerprun.json",
        "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_safe_refusal.json",
        "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_phase1x24.json",
        "results/processed/rubikoptimal_oracle_corpus_seed_2026_thesis_lowload.json",
        "results/processed/rubikoptimal_oracle_corpus_seed_2026_thesis_superflip_lowload.json",
        "results/processed/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.json",
        "results/processed/nissy_public_tables_complete_seed_2026_thesis_complete_public.json",
        "results/processed/optimal_3x3_seed_2026_thesis_nissy_optimal.json",
        "results/processed/optimal_3x3_seed_2026_thesis_nissy_core_direct_lowload.json",
        "results/processed/optimal_3x3_seed_2026_stress_nissy_optimal.json",
        "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json",
        "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_state_recovery_lowload.json",
        "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_core_direct_state_lowload.json",
        "results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json",
        "results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json",
        "results/processed/race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "results/processed/resident_race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/resident_race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
        "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_h48_symmetry_lowload.json",
        "results/processed/universal_batch_oracle_corpus_seed_2026_thesis_h48h7_batch_lowload.json",
        "results/processed/universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_optimized_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_broader_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_adaptive_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_h48_symmetry_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_broader_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_no_shortcuts_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_18_adaptive_symmetry_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_19_adaptive_symmetry_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_adaptive_symmetry_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_adaptive_symmetry_lowload.json",
        "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.json",
        "results/processed/universal_symmetry_oracle_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/certificate_cache_inverse_closure_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_expanded_default_lowload.json",
        "results/processed/learned_certificate_cache_seed_2026_thesis_h48h7_lowload.json",
        "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json",
        "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json",
        "results/processed/nissy_core_resident_mmap_seed_2026_thesis_h48h7_lowload.json",
        "data/generated/h48/thesis_seed_2026/h48h0.bin",
        "data/generated/h48/thesis_seed_2026/h48h7.bin",
        "data/generated/thesis_seed_2026_corner_state_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_0_1_2_3_4_5_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_6_7_8_9_10_11_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_0_2_4_6_8_10_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_1_3_5_7_9_11_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_0_1_4_5_8_9_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_2_3_6_7_10_11_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_0_3_5_6_8_11_pdb.bin",
        "data/generated/thesis_seed_2026_edge_subset_1_2_4_7_9_10_pdb.bin",
        "data/generated/thesis_seed_2026_edge_cpdb_urf_subset_0_1_2_3_4_5.bin",
        "data/generated/thesis_seed_2026_edge_cpdb_dlb_subset_6_7_8_9_10_11.bin",
        "thesis/tables/benchmark_summary.tex",
        "thesis/tables/algorithm_status.tex",
        "thesis/tables/benchmark_dataset_summary.tex",
        "thesis/tables/benchmark_case_catalog.tex",
        "thesis/tables/distance_recognition_summary.tex",
        "thesis/tables/solver_status_counts.tex",
        "thesis/tables/solver_runtime_summary.tex",
        "thesis/tables/solver_solution_length_summary.tex",
        "thesis/tables/solver_node_summary.tex",
        "thesis/tables/benchmark_timeout_cases.tex",
        "thesis/tables/benchmark_case_status_matrix.tex",
        "thesis/tables/generated_table_metadata.tex",
        "thesis/tables/corner_pdb_metadata.tex",
        "thesis/tables/edge_pdb_metadata.tex",
        "thesis/tables/edge_pdb_coverage_expanded8.tex",
        "thesis/tables/edge_cpdb_metadata.tex",
        "thesis/tables/edge_pdb_coverage_cpdb_additive.tex",
        "thesis/tables/heuristic_comparison.tex",
        "thesis/tables/h48_metadata.tex",
        "thesis/tables/e2e_3x3_status.tex",
        "thesis/tables/optimal_3x3_status.tex",
        "thesis/tables/optimal_3x3_status_stress_h48h0.tex",
        "thesis/tables/optimal_3x3_status_stress_h48h7_oracle.tex",
        "thesis/tables/h48_oracle_certification.tex",
        "thesis/tables/h48_batch_overhead.tex",
        "thesis/tables/h48_oracle_cli.tex",
        "thesis/tables/h48_trusted_table_speedup.tex",
        "thesis/tables/h48_batch_overhead_trusted.tex",
        "thesis/tables/h48_oracle_cli_trusted.tex",
        "thesis/tables/h48_oracle_stream_trusted.tex",
        "thesis/tables/h48_resident_oracle_h48h7_trusted.tex",
        "thesis/tables/h48_resident_certification_h48h7_trusted.tex",
        "thesis/tables/fast_optimal_oracle_api_h48h7_trusted.tex",
        "thesis/tables/h48_oracle_contract_h48h7.tex",
        "thesis/tables/h48_capacity_seed_2026_thesis_lowload.tex",
        "thesis/tables/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.tex",
        "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_goal.tex",
        "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_cornerprun.tex",
        "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_safe_refusal.tex",
        "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_phase1x24.tex",
        "thesis/tables/rubikoptimal_oracle_corpus_lowload.tex",
        "thesis/tables/rubikoptimal_oracle_corpus_superflip_lowload.tex",
        "thesis/tables/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.tex",
        "thesis/tables/nissy_public_tables_complete_seed_2026_thesis_complete_public.tex",
        "thesis/tables/optimal_3x3_status_thesis_nissy_optimal.tex",
        "thesis/tables/optimal_3x3_status_thesis_nissy_core_direct_lowload.tex",
        "thesis/tables/optimal_3x3_status_stress_nissy_optimal.tex",
        "thesis/tables/portfolio_optimal_oracle_nissy_first_lowload.tex",
        "thesis/tables/portfolio_optimal_oracle_nissy_state_recovery_lowload.tex",
        "thesis/tables/portfolio_optimal_oracle_nissy_core_direct_state_lowload.tex",
        "thesis/tables/portfolio_optimal_oracle_superflip_fallback_lowload.tex",
        "thesis/tables/portfolio_optimal_oracle_superflip_certificate_cache_lowload.tex",
        "thesis/tables/race_optimal_oracle_h48h7_lowload.tex",
        "thesis/tables/race_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        "thesis/tables/resident_race_optimal_oracle_h48h7_lowload.tex",
        "thesis/tables/resident_race_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        "thesis/tables/universal_optimal_oracle_h48h7_lowload.tex",
        "thesis/tables/universal_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        "thesis/tables/universal_optimal_oracle_h48h7_h48_symmetry_lowload.tex",
        "thesis/tables/universal_batch_oracle_corpus_h48h7_batch_lowload.tex",
        "thesis/tables/universal_batch_oracle_corpus_h48h7_resident_h48_batch_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_optimized_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_broader_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_adaptive_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_expanded_adaptive_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_17_no_shortcuts_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_17_18_adaptive_symmetry_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_19_adaptive_symmetry_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_adaptive_symmetry_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_offset1_adaptive_symmetry_lowload.tex",
        "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.tex",
        "thesis/tables/universal_symmetry_oracle_h48h7_lowload.tex",
        "thesis/tables/certificate_cache_inverse_closure_h48h7_lowload.tex",
        "thesis/tables/certificate_cache_symmetry_closure_h48h7_lowload.tex",
        "thesis/tables/certificate_cache_symmetry_closure_h48h7_expanded_default_lowload.tex",
        "thesis/tables/learned_certificate_cache_h48h7_lowload.tex",
        "thesis/tables/h48_oracle_certification_trusted_preload.tex",
        "thesis/tables/h48_oracle_certification_trusted_no_preload.tex",
        "thesis/tables/nissy_core_resident_mmap_h48h7_lowload.tex",
        "thesis/tables/pocket_cube_distribution.tex",
        "thesis/tables/pocket_cube_representatives.tex",
        "thesis/figures/runtime_depth_data.tex",
        "thesis/figures/runtime_by_solver_data.tex",
        "thesis/figures/solution_length_depth_data.tex",
        "thesis/figures/status_counts_data.tex",
    ]
    missing = []
    empty = []
    mtimes = {}
    for relative in required:
        path = ROOT / relative
        if not path.exists():
            missing.append(relative)
            continue
        if path.stat().st_size == 0:
            empty.append(relative)
        mtimes[relative] = path.stat().st_mtime

    stale = []
    pairs = [
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/benchmark_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/algorithm_status.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/benchmark_dataset_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/benchmark_case_catalog.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/distance_recognition_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/solver_status_counts.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/solver_runtime_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/solver_solution_length_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/solver_node_summary.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/benchmark_timeout_cases.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/tables/benchmark_case_status_matrix.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/figures/runtime_depth_data.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/figures/runtime_by_solver_data.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/figures/solution_length_depth_data.tex"),
        ("results/processed/summary_seed_2026_thesis.json", "thesis/figures/status_counts_data.tex"),
        ("results/processed/table_metadata_thesis_seed_2026.json", "thesis/tables/generated_table_metadata.tex"),
        ("results/processed/corner_pdb_metadata_seed_2026_thesis.json", "thesis/tables/corner_pdb_metadata.tex"),
        ("results/processed/edge_pdb_metadata_seed_2026_thesis.json", "thesis/tables/edge_pdb_metadata.tex"),
        ("results/processed/edge_pdb_coverage_seed_2026_thesis_expanded8.json", "thesis/tables/edge_pdb_coverage_expanded8.tex"),
        ("results/processed/edge_cpdb_metadata_seed_2026_thesis.json", "thesis/tables/edge_cpdb_metadata.tex"),
        ("results/processed/edge_pdb_coverage_seed_2026_thesis_cpdb_additive.json", "thesis/tables/edge_pdb_coverage_cpdb_additive.tex"),
        ("results/processed/heuristic_comparison_seed_2026_thesis.json", "thesis/tables/heuristic_comparison.tex"),
        ("results/processed/h48_metadata_seed_2026_thesis_h48h0.json", "thesis/tables/h48_metadata.tex"),
        ("results/processed/h48_metadata_seed_2026_thesis_h48h7.json", "thesis/tables/h48_metadata.tex"),
        ("results/processed/e2e_3x3_seed_2026_thesis.json", "thesis/tables/e2e_3x3_status.tex"),
        ("results/processed/optimal_3x3_seed_2026_thesis.json", "thesis/tables/optimal_3x3_status.tex"),
        ("results/processed/optimal_3x3_seed_2026_stress_h48h0.json", "thesis/tables/optimal_3x3_status_stress_h48h0.tex"),
        (
            "results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json",
            "thesis/tables/optimal_3x3_status_stress_h48h7_oracle.tex",
        ),
        (
            "results/processed/h48_oracle_certification_seed_2026_thesis.json",
            "thesis/tables/h48_oracle_certification.tex",
        ),
        (
            "results/processed/h48_batch_overhead_seed_2026_thesis.json",
            "thesis/tables/h48_batch_overhead.tex",
        ),
        (
            "results/processed/h48_oracle_cli_seed_2026_thesis.json",
            "thesis/tables/h48_oracle_cli.tex",
        ),
        (
            "results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json",
            "thesis/tables/h48_trusted_table_speedup.tex",
        ),
        (
            "results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json",
            "thesis/tables/h48_batch_overhead_trusted.tex",
        ),
        (
            "results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json",
            "thesis/tables/h48_oracle_cli_trusted.tex",
        ),
        (
            "results/processed/h48_oracle_stream_seed_2026_thesis_trusted.json",
            "thesis/tables/h48_oracle_stream_trusted.tex",
        ),
        (
            "results/processed/h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json",
            "thesis/tables/h48_resident_oracle_h48h7_trusted.tex",
        ),
        (
            "results/processed/h48_resident_certification_seed_2026_thesis_h48h7_trusted.json",
            "thesis/tables/h48_resident_certification_h48h7_trusted.tex",
        ),
        (
            "results/processed/fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json",
            "thesis/tables/fast_optimal_oracle_api_h48h7_trusted.tex",
        ),
        (
            "results/processed/nissy_core_resident_mmap_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/nissy_core_resident_mmap_h48h7_lowload.tex",
        ),
        (
            "results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json",
            "thesis/tables/h48_oracle_contract_h48h7.tex",
        ),
        (
            "results/processed/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.json",
            "thesis/tables/h48_generation_probe_seed_2026_thesis_h48h8_lowload_15s.tex",
        ),
        (
            "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_goal.json",
            "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_goal.tex",
        ),
        (
            "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_cornerprun.json",
            "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_cornerprun.tex",
        ),
        (
            "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_safe_refusal.json",
            "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_safe_refusal.tex",
        ),
        (
            "results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_phase1x24.json",
            "thesis/tables/rubikoptimal_tables_seed_2026_thesis_current_20260531_phase1x24.tex",
        ),
        (
            "results/processed/rubikoptimal_oracle_corpus_seed_2026_thesis_lowload.json",
            "thesis/tables/rubikoptimal_oracle_corpus_lowload.tex",
        ),
        (
            "results/processed/rubikoptimal_oracle_corpus_seed_2026_thesis_superflip_lowload.json",
            "thesis/tables/rubikoptimal_oracle_corpus_superflip_lowload.tex",
        ),
        (
            "results/processed/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.json",
            "thesis/tables/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.tex",
        ),
        (
            "results/processed/nissy_public_tables_complete_seed_2026_thesis_complete_public.json",
            "thesis/tables/nissy_public_tables_complete_seed_2026_thesis_complete_public.tex",
        ),
        (
            "results/processed/optimal_3x3_seed_2026_thesis_nissy_optimal.json",
            "thesis/tables/optimal_3x3_status_thesis_nissy_optimal.tex",
        ),
        (
            "results/processed/optimal_3x3_seed_2026_thesis_nissy_core_direct_lowload.json",
            "thesis/tables/optimal_3x3_status_thesis_nissy_core_direct_lowload.tex",
        ),
        (
            "results/processed/optimal_3x3_seed_2026_stress_nissy_optimal.json",
            "thesis/tables/optimal_3x3_status_stress_nissy_optimal.tex",
        ),
        (
            "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json",
            "thesis/tables/portfolio_optimal_oracle_nissy_first_lowload.tex",
        ),
        (
            "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_state_recovery_lowload.json",
            "thesis/tables/portfolio_optimal_oracle_nissy_state_recovery_lowload.tex",
        ),
        (
            "results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_core_direct_state_lowload.json",
            "thesis/tables/portfolio_optimal_oracle_nissy_core_direct_state_lowload.tex",
        ),
        (
            "results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json",
            "thesis/tables/portfolio_optimal_oracle_superflip_fallback_lowload.tex",
        ),
        (
            "results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json",
            "thesis/tables/portfolio_optimal_oracle_superflip_certificate_cache_lowload.tex",
        ),
        (
            "results/processed/race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/race_optimal_oracle_h48h7_lowload.tex",
        ),
        (
            "results/processed/race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
            "thesis/tables/race_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        ),
        (
            "results/processed/resident_race_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/resident_race_optimal_oracle_h48h7_lowload.tex",
        ),
        (
            "results/processed/resident_race_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
            "thesis/tables/resident_race_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        ),
        (
            "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/universal_optimal_oracle_h48h7_lowload.tex",
        ),
        (
            "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_nissy_core_direct_lowload.json",
            "thesis/tables/universal_optimal_oracle_h48h7_nissy_core_direct_lowload.tex",
        ),
        (
            "results/processed/universal_optimal_oracle_seed_2026_thesis_h48h7_h48_symmetry_lowload.json",
            "thesis/tables/universal_optimal_oracle_h48h7_h48_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_batch_oracle_corpus_seed_2026_thesis_h48h7_batch_lowload.json",
            "thesis/tables/universal_batch_oracle_corpus_h48h7_batch_lowload.tex",
        ),
        (
            "results/processed/universal_batch_oracle_corpus_seed_2026_thesis_h48h7_resident_h48_batch_lowload.json",
            "thesis/tables/universal_batch_oracle_corpus_h48h7_resident_h48_batch_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_optimized_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_optimized_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_broader_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_broader_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_adaptive_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_adaptive_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_expanded_adaptive_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_expanded_adaptive_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_h48_symmetry_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_h48_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_live_no_shortcuts_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_live_no_shortcuts_broader_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_live_no_shortcuts_broader_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_no_shortcuts_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_17_no_shortcuts_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_17_18_adaptive_symmetry_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_17_18_adaptive_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_19_adaptive_symmetry_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_19_adaptive_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_adaptive_symmetry_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_adaptive_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_adaptive_symmetry_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_offset1_adaptive_symmetry_lowload.tex",
        ),
        (
            "results/processed/universal_oracle_cli_seed_2026_thesis_h48h7_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.json",
            "thesis/tables/universal_oracle_cli_h48h7_known_distance_20_offset1_trimmed_prepass_h48_420_lowload.tex",
        ),
        (
            "results/processed/universal_symmetry_oracle_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/universal_symmetry_oracle_h48h7_lowload.tex",
        ),
        (
            "results/processed/certificate_cache_inverse_closure_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/certificate_cache_inverse_closure_h48h7_lowload.tex",
        ),
        (
            "results/processed/certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/certificate_cache_symmetry_closure_h48h7_lowload.tex",
        ),
        (
            "results/processed/certificate_cache_symmetry_closure_seed_2026_thesis_h48h7_expanded_default_lowload.json",
            "thesis/tables/certificate_cache_symmetry_closure_h48h7_expanded_default_lowload.tex",
        ),
        (
            "results/processed/learned_certificate_cache_seed_2026_thesis_h48h7_lowload.json",
            "thesis/tables/learned_certificate_cache_h48h7_lowload.tex",
        ),
        (
            "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json",
            "thesis/tables/h48_oracle_certification_trusted_preload.tex",
        ),
        (
            "results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json",
            "thesis/tables/h48_oracle_certification_trusted_no_preload.tex",
        ),
        ("results/processed/pocket_cube_summary_seed_2026_thesis.json", "thesis/tables/pocket_cube_distribution.tex"),
        ("results/processed/pocket_cube_summary_seed_2026_thesis.json", "thesis/tables/pocket_cube_representatives.tex"),
    ]
    for source, generated in pairs:
        source_path = ROOT / source
        generated_path = ROOT / generated
        if source_path.exists() and generated_path.exists() and generated_path.stat().st_mtime < source_path.stat().st_mtime:
            stale.append({"source": source, "generated": generated})

    return {
        "required_count": len(required),
        "missing": missing,
        "empty": empty,
        "stale": stale,
    }


def main() -> int:
    pdf_path = THESIS / "main.pdf"
    source = _source_text()
    table_files = sorted((THESIS / "tables").glob("*.tex"))
    figure_files = sorted((THESIS / "figures").glob("*.tex"))
    todo_pattern = re.compile(r"\b(TODO|FIXME|TBD|placeholder|συμπλήρωση|εκκρεμ)", re.IGNORECASE)
    claim_pattern = re.compile(
        r"(βέλτισ|optimal|exact distance|God'?s Number|God|complete solver|πλήρης|πλήρως|αυθαίρετ)",
        re.IGNORECASE,
    )

    pdf_pages = _pdf_pages(pdf_path)
    pdf_words = _pdf_word_count(pdf_path)
    source_words = _source_word_count(source)
    figure_table_count = len(table_files) + len(figure_files)
    pdf_deliverable = _pdf_deliverable_audit()
    generated = _generated_artifacts()
    todo_markers = _line_findings(todo_pattern, _tex_files())
    front_matter_placeholders = _front_matter_placeholders()
    repository = _repository_audit()
    implementation = _implementation_artifact_audit()
    cli = _cli_audit()
    solver_evidence = _solver_evidence_audit()
    bibliography = _bibliography_audit()
    handoff_documents = _handoff_document_audit()
    supervisor_approval = _supervisor_approval_audit()
    git_provenance = _git_provenance_audit()
    source_state = _source_state_audit()
    third_party_notices = _third_party_notice_audit()
    topic_brief_artifacts = _topic_brief_artifact_audit()
    cloud_scope_drift = _cloud_scope_drift_audit()
    backend_identity = _backend_identity_audit()
    submission_blockers = _submission_blockers(
        front_matter_placeholders,
        bibliography,
        repository,
        implementation,
        cli,
        solver_evidence,
        handoff_documents,
        supervisor_approval,
        pdf_deliverable,
        git_provenance,
        third_party_notices,
        topic_brief_artifacts,
        backend_identity,
        source_state,
    )

    checks = {
        "page_target_met": pdf_pages is not None and pdf_pages >= TARGET_MIN_PAGES,
        "word_target_met": (pdf_words or source_words) >= TARGET_MIN_WORDS,
        "figure_table_target_met": figure_table_count >= TARGET_MIN_FIGURES_TABLES,
        "pdf_deliverable_current": pdf_deliverable["passed"],
        "generated_artifacts_present": not generated["missing"] and not generated["empty"],
        "generated_artifacts_not_stale": not generated["stale"],
        "git_provenance_clean": git_provenance["passed"],
        "source_state_reproducible": source_state["passed"],
        "third_party_notices_present": third_party_notices["passed"],
        "topic_brief_artifacts_valid": topic_brief_artifacts["passed"],
        "cloud_scope_drift_classified": cloud_scope_drift["passed"],
        "backend_identity_valid": backend_identity["passed"],
    }
    payload = {
        "schema_version": 2,
        "pdf": str(pdf_path.relative_to(ROOT)),
        "page_count": pdf_pages,
        "pdf_word_count": pdf_words,
        "source_word_count": source_words,
        "target_min_pages": TARGET_MIN_PAGES,
        "target_min_words": TARGET_MIN_WORDS,
        "table_file_count": len(table_files),
        "figure_file_count": len(figure_files),
        "figure_table_file_count": figure_table_count,
        "target_min_figure_table_count": TARGET_MIN_FIGURES_TABLES,
        "pdf_deliverable": pdf_deliverable,
        "todo_markers": todo_markers,
        "front_matter_placeholders": front_matter_placeholders,
        "repository": repository,
        "implementation": implementation,
        "cli": cli,
        "solver_evidence": solver_evidence,
        "bibliography": bibliography,
        "handoff_documents": handoff_documents,
        "supervisor_approval": supervisor_approval,
        "git_provenance": git_provenance,
        "source_state": source_state,
        "third_party_notices": third_party_notices,
        "topic_brief_artifacts": topic_brief_artifacts,
        "cloud_scope_drift": cloud_scope_drift,
        "backend_identity": backend_identity,
        "submission_blockers": submission_blockers,
        "claim_risk_markers": _line_findings(claim_pattern, _tex_files()),
        "generated_artifacts": generated,
        "checks": checks,
        "acceptance_scale_passed": all(checks.values()),
        "acceptance_repository_passed": repository["passed"],
        "acceptance_implementation_passed": implementation["passed"] and cli["passed"] and solver_evidence["passed"],
        "acceptance_research_passed": bibliography["passed"],
        "final_submission_ready": (
            all(checks.values())
            and repository["passed"]
            and implementation["passed"]
            and cli["passed"]
            and solver_evidence["passed"]
            and bibliography["passed"]
            and not todo_markers
            and not submission_blockers
        ),
    }
    output_path = ROOT / "results" / "processed" / "thesis_audit.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if not pdf_deliverable["passed"]:
        return 1
    acceptance_gates_passed = (
        payload["acceptance_scale_passed"]
        and payload["acceptance_repository_passed"]
        and payload["acceptance_implementation_passed"]
        and payload["acceptance_research_passed"]
    )
    if not acceptance_gates_passed or not payload["final_submission_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
