import json

from scripts import thesis_audit
from scripts import verify_results


def test_front_matter_placeholder_detection(tmp_path):
    source = tmp_path / "front.tex"
    source.write_text(
        "\\newcommand{\\thesisStudentName}{ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ}\n"
        "\\newcommand{\\thesisRegistrationNumber}{ΧΧΧΧΧΧΧ}\n"
        "\\newcommand{\\thesisLaboratory}{ΕΡΓΑΣΤΗΡΙΟ ΕΠΙΒΛΕΠΟΝΤΟΣ}\n"
        "© 20XX -- Με την επιφύλαξη παντός δικαιώματος\n"
        "Όνομα Επώνυμο, Βαθμίδα, Τμήμα (μέλος επιτροπής)\n",
        encoding="utf-8",
    )

    findings = thesis_audit._front_matter_placeholders([source])
    fields = {finding["field"] for finding in findings}

    assert "student_name" in fields
    assert "registration_number" in fields
    assert "supervisor_laboratory" in fields
    assert "copyright_year" in fields
    assert "committee_member" in fields
    assert "rank_placeholder" in fields


def test_submission_blockers_report_front_matter_fields(tmp_path):
    source = tmp_path / "front.tex"
    source.write_text(
        "\\newcommand{\\thesisStudentName}{ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ}\n"
        "\\newcommand{\\thesisRegistrationNumber}{ΧΧΧΧΧΧΧ}\n",
        encoding="utf-8",
    )

    blockers = thesis_audit._submission_blockers(thesis_audit._front_matter_placeholders([source]))

    assert len(blockers) == 1
    assert blockers[0]["id"] == "front_matter_metadata_placeholders"
    assert blockers[0]["status"] == "supervisor_or_secretariat_required"
    assert blockers[0]["evidence_count"] == 2
    assert set(blockers[0]["fields"]) == {"student display name", "student registration number"}


def test_bibliography_audit_requires_citations_and_research_notes(tmp_path):
    tex = tmp_path / "chapter.tex"
    tex.write_text("Reference \\cite{usedKey,missingBib}.\n", encoding="utf-8")
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{usedKey,\n  title = {Used}\n}\n"
        "@article{uncitedKey,\n  title = {Uncited}\n}\n",
        encoding="utf-8",
    )
    notes = tmp_path / "research_notes.md"
    notes.write_text("BibTeX key: `usedKey`\nBibTeX key: `staleNoteKey`\n", encoding="utf-8")

    audit = thesis_audit._bibliography_audit([tex], bib, notes)

    assert audit["bib_entry_count"] == 2
    assert audit["citation_key_count"] == 2
    assert audit["research_note_key_count"] == 2
    assert audit["missing_bib_entries"] == ["missingBib"]
    assert audit["uncited_bib_entries"] == ["uncitedKey"]
    assert audit["missing_research_notes"] == ["uncitedKey"]
    assert audit["research_note_keys_without_bib"] == ["staleNoteKey"]
    assert audit["passed"] is False

    blockers = thesis_audit._submission_blockers([], audit)
    assert blockers[0]["id"] == "bibliography_consistency"
    assert blockers[0]["status"] == "repository_required"


def test_cli_audit_detects_missing_required_command():
    audit = thesis_audit._cli_audit("usage: rubik-optimal {scramble,solve,verify}\n")

    assert audit["passed"] is False
    assert audit["missing_commands"] == ["benchmark", "distance", "oracle", "tables"]


def test_repository_and_implementation_audits_detect_missing_paths(tmp_path):
    repository = thesis_audit._repository_audit(tmp_path)
    implementation = thesis_audit._implementation_artifact_audit(tmp_path)

    assert repository["passed"] is False
    assert "pyproject.toml" in repository["missing"]
    assert implementation["passed"] is False
    assert "src/rubik_optimal/cube.py" in implementation["missing_source_paths"]


def test_pdf_deliverable_audit_passes_when_root_pdf_is_absent(tmp_path):
    thesis_dir = tmp_path / "thesis"
    thesis_dir.mkdir()
    thesis_pdf = thesis_dir / "main.pdf"
    thesis_pdf.write_bytes(b"current-pdf")

    audit = thesis_audit._pdf_deliverable_audit(root=tmp_path)

    assert audit["passed"] is True
    assert audit["root_exists"] is False
    assert audit["thesis_exists"] is True
    assert audit["hashes_match"] is None


def test_pdf_deliverable_audit_passes_when_root_and_thesis_pdfs_match(tmp_path):
    thesis_dir = tmp_path / "thesis"
    thesis_dir.mkdir()
    (tmp_path / "main.pdf").write_bytes(b"current-pdf")
    (thesis_dir / "main.pdf").write_bytes(b"current-pdf")

    audit = thesis_audit._pdf_deliverable_audit(root=tmp_path)

    assert audit["passed"] is True
    assert audit["hashes_match"] is True


def test_pdf_deliverable_audit_fails_when_root_and_thesis_pdfs_differ(tmp_path):
    thesis_dir = tmp_path / "thesis"
    thesis_dir.mkdir()
    (tmp_path / "main.pdf").write_bytes(b"fresh-build")
    (thesis_dir / "main.pdf").write_bytes(b"stale-deliverable")

    audit = thesis_audit._pdf_deliverable_audit(root=tmp_path)

    assert audit["passed"] is False
    assert audit["hashes_match"] is False
    assert "differs" in audit["notes"][0]


def test_solver_evidence_audit_accepts_current_thesis_shape(tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps({
            "profile": "thesis",
            "seed": 2026,
            "solvers": {
                "korf_ida_star_scoped": {
                    "statuses": ["exact", "timeout"],
                    "verified_solutions": 10,
                },
                "kociemba_native_scoped": {
                    "statuses": ["non_exact"],
                    "verified_solutions": 13,
                },
                "kociemba_two_phase_adapter": {
                    "statuses": ["non_exact"],
                    "verified_solutions": 13,
                },
                "thistlethwaite_native_scoped": {
                    "statuses": ["non_exact"],
                    "verified_solutions": 13,
                },
            },
        }),
        encoding="utf-8",
    )
    pocket = tmp_path / "pocket.json"
    pocket.write_text(
        json.dumps({
            "profile": "thesis",
            "expected_state_count": 3_674_160,
            "distribution": {
                "complete": True,
                "state_count": 3_674_160,
                "max_distance": 11,
            },
            "representative_solutions": [
                {"status": "exact", "verified": True},
            ],
        }),
        encoding="utf-8",
    )
    tables = tmp_path / "tables.json"
    tables.write_text(
        json.dumps({"profile": "thesis", "tables": [{} for _ in range(12)]}),
        encoding="utf-8",
    )
    corner_binary = tmp_path / "corner.bin"
    corner_binary.write_bytes(b"0" * 16)
    corner = tmp_path / "corner.json"
    corner.write_text(
        json.dumps({
            "profile": "thesis",
            "complete": True,
            "state_count": 88_179_840,
            "visited_states": 88_179_840,
            "max_distance": 11,
            "size_bytes": 16,
            "file_path": str(corner_binary),
        }),
        encoding="utf-8",
    )
    e2e = tmp_path / "e2e.json"
    e2e.write_text(
        json.dumps({
            "profile": "thesis",
            "passed": True,
            "rows": [
                {"input_kind": "sequence"},
                {"input_kind": "facelets"},
            ],
        }),
        encoding="utf-8",
    )
    edge_binaries = []
    for index in range(8):
        edge_binary = tmp_path / f"edge_{index}.bin"
        edge_binary.write_bytes(b"0" * 8)
        edge_binaries.append(edge_binary)
    edge = tmp_path / "edge.json"
    edge.write_text(
        json.dumps({
            "profile": "thesis",
            "complete": True,
            "total_state_count": 340_623_360,
            "total_size_bytes": 64,
            "subsets": [
                {
                    "visited_states": 42_577_920,
                    "file_path": str(edge_binary),
                }
                for edge_binary in edge_binaries
            ],
        }),
        encoding="utf-8",
    )
    h48_binary = tmp_path / "h48h0.bin"
    h48_binary.write_bytes(b"0" * 12)
    h48 = tmp_path / "h48.json"
    h48.write_text(
        json.dumps({
            "profile": "thesis",
            "solver": "h48h0",
            "table_kind": "h48_pruning_table",
            "backend_source": "vendored_nissy_core_h48",
            "license": "GPL-3.0-or-later",
            "table_size_bytes": 12,
            "file_path": str(h48_binary),
        }),
        encoding="utf-8",
    )
    optimal = tmp_path / "optimal.json"
    optimal.write_text(
        json.dumps({
            "profile": "thesis",
            "all_exact": True,
            "backend": "native",
            "rows": [
                {"case_id": "random_2_15", "status": "exact", "solver": "optimal_native"},
                {"case_id": "shallow_sequence", "status": "exact", "solver": "optimal_native"},
            ],
        }),
        encoding="utf-8",
    )
    h48_stress = tmp_path / "h48_stress.json"
    h48_stress.write_text(
        json.dumps({
            "profile": "stress",
            "backend": "h48-native",
            "h48_solver": "h48h0",
            "all_exact": True,
            "rows": [
                {
                    "case_id": "random_3_20",
                    "status": "exact",
                    "solution_length": 17,
                    "verified": True,
                }
            ],
        }),
        encoding="utf-8",
    )
    h48_oracle_certification = tmp_path / "h48_oracle_certification.json"
    h48_oracle_certification.write_text(
        json.dumps({
            "profile": "thesis",
            "solver": "h48h7",
            "all_exact": True,
            "all_expected_distances_match": True,
            "within_runtime_target": True,
            "passed": True,
            "max_runtime_seconds": 42.0,
            "rows": [
                {
                    "case_id": "superflip_distance_20",
                    "status": "exact",
                    "solution_length": 20,
                    "verified": True,
                    "expected_distance_matches": True,
                },
                {"case_id": "solved", "status": "exact", "solution_length": 0, "verified": True},
                {"case_id": "shallow_r_u_f2", "status": "exact", "solution_length": 3, "verified": True},
                {"case_id": "deterministic_depth_25", "status": "exact", "solution_length": 18, "verified": True},
            ],
        }),
        encoding="utf-8",
    )
    h48_batch_overhead = tmp_path / "h48_batch_overhead.json"
    h48_batch_overhead.write_text(
        json.dumps({
            "profile": "thesis",
            "solver": "h48h7",
            "passed": True,
            "repetitions": 12,
            "throughput_speedup": 11.56,
            "batch_wall_seconds": 6.03,
            "sequential_exact_count": 12,
            "batch_exact_count": 12,
            "batch_rows": [
                {"status": "exact", "is_verified": True}
                for _ in range(12)
            ],
        }),
        encoding="utf-8",
    )
    portfolio_certificate_cache = tmp_path / "portfolio_certificate_cache.json"
    portfolio_certificate_cache.write_text(
        json.dumps({
            "profile": "thesis",
            "case_set": "hard",
            "case_ids": ["superflip_distance_20"],
            "passed": True,
            "all_exact": True,
            "max_runtime_seconds": 0.012885,
            "selected_backends": ["exact-certificate-cache"],
            "rows": [
                {
                    "case_id": "superflip_distance_20",
                    "selected_backend": "exact-certificate-cache",
                    "status": "exact",
                    "solution_length": 20,
                    "verified": True,
                    "expected_distance_matches": True,
                }
            ],
        }),
        encoding="utf-8",
    )

    audit = thesis_audit._solver_evidence_audit(
        summary,
        pocket,
        tables,
        corner,
        edge_pdb_metadata_path=edge,
        h48_metadata_path=h48,
        e2e_path=e2e,
        optimal_path=optimal,
        h48_stress_path=h48_stress,
        h48_oracle_certification_path=h48_oracle_certification,
        h48_batch_overhead_path=h48_batch_overhead,
        portfolio_superflip_certificate_cache_path=portfolio_certificate_cache,
    )

    assert audit["passed"] is True
    assert audit["native_kociemba_verified_solutions"] == 13
    assert audit["native_thistlethwaite_verified_solutions"] == 13
    assert audit["generated_table_count"] == 12
    assert audit["corner_pdb_state_count"] == 88_179_840
    assert audit["edge_pdb_total_state_count"] == 340_623_360
    assert audit["edge_pdb_subset_count"] == 8
    assert audit["optimal_3x3_backend"] == "native"
    assert audit["h48_solver"] == "h48h0"
    assert audit["h48_table_size_bytes"] == 12
    assert audit["e2e_3x3_case_count"] == 2
    assert audit["optimal_3x3_all_exact"] is True
    assert audit["h48_stress_all_exact"] is True
    assert audit["h48_oracle_certification_passed"] is True
    assert audit["h48_oracle_certification_max_runtime_seconds"] == 42.0
    assert audit["h48_batch_overhead_speedup"] == 11.56
    assert audit["portfolio_superflip_certificate_cache_runtime_seconds"] == 0.012885
    assert audit["pocket_state_count"] == 3_674_160


def test_handoff_document_audit_requires_metadata_packet_request_and_matrix(tmp_path):
    packet = tmp_path / "docs" / "final_metadata_packet.md"
    request = tmp_path / "docs" / "supervisor_handoff_request.md"
    matrix = tmp_path / "docs" / "completion_audit_matrix.md"
    packet.parent.mkdir()
    packet.write_text(
        "\\thesisStudentName\n"
        "\\thesisRegistrationNumber\n"
        "final_metadata_values.template.json\n"
        "scripts/apply_final_metadata.py\n"
        "final_supervisor_approval.md\n"
        "front_matter_placeholders: []\n"
        "final_submission_ready: true\n"
        "AI-assistance\n",
        encoding="utf-8",
    )
    request.write_text(
        "Student name in Greek\n"
        "Second committee member\n"
        "scripts/apply_final_metadata.py\n"
        "AI-assistance disclosure\n"
        "final_supervisor_approval.md\n"
        "latexmk -xelatex\n"
        "final_submission_ready: true\n",
        encoding="utf-8",
    )
    matrix.write_text(
        "Remaining Missing or Externally Blocked Requirements\n"
        "Student identity metadata\n"
        "scripts/apply_final_metadata.py\n"
        "AI disclosure approval\n"
        "final_supervisor_approval.md\n"
        "front_matter_placeholders: []\n"
        "final_submission_ready: true\n",
        encoding="utf-8",
    )

    audit = thesis_audit._handoff_document_audit(tmp_path)

    assert audit["passed"] is True
    assert audit["missing_documents"] == []
    assert audit["missing_terms"] == {}


def test_handoff_document_audit_reports_missing_terms(tmp_path):
    packet = tmp_path / "docs" / "final_metadata_packet.md"
    request = tmp_path / "docs" / "supervisor_handoff_request.md"
    matrix = tmp_path / "docs" / "completion_audit_matrix.md"
    packet.parent.mkdir()
    packet.write_text("front_matter_placeholders: []\n", encoding="utf-8")
    request.write_text("Student name in Greek\n", encoding="utf-8")
    matrix.write_text("Student identity metadata\n", encoding="utf-8")

    audit = thesis_audit._handoff_document_audit(tmp_path)

    assert audit["passed"] is False
    assert audit["missing_documents"] == []
    assert "\\thesisStudentName" in audit["missing_terms"]["docs/final_metadata_packet.md"]
    assert "AI-assistance disclosure" in audit["missing_terms"]["docs/supervisor_handoff_request.md"]
    assert "final_submission_ready: true" in audit["missing_terms"]["docs/completion_audit_matrix.md"]


def test_supervisor_approval_audit_requires_final_record(tmp_path):
    audit = thesis_audit._supervisor_approval_audit(tmp_path)

    assert audit["passed"] is False
    assert audit["exists"] is False
    assert audit["path"] == "docs/final_supervisor_approval.md"
    assert "AI-assistance disclosure approved" in audit["missing_terms"]


def test_supervisor_approval_audit_accepts_completed_record(tmp_path):
    record = tmp_path / "docs" / "final_supervisor_approval.md"
    record.parent.mkdir()
    record.write_text(
        "approval_status: approved\n"
        "approval_source: supervisor email dated 2026-05-17\n"
        "approval_date: 2026-05-17\n"
        "AI-assistance disclosure approved\n"
        "front-matter style approved\n"
        "bibliography style approved\n"
        "scoped solver claims approved\n",
        encoding="utf-8",
    )

    audit = thesis_audit._supervisor_approval_audit(tmp_path)

    assert audit["passed"] is True
    assert audit["exists"] is True
    assert audit["missing_terms"] == []
    assert audit["placeholder_findings"] == []


def test_submission_blockers_report_missing_supervisor_approval(tmp_path):
    approval = thesis_audit._supervisor_approval_audit(tmp_path)
    blockers = thesis_audit._submission_blockers([], supervisor_approval=approval)

    assert len(blockers) == 1
    assert blockers[0]["id"] == "supervisor_approval_evidence"
    assert blockers[0]["status"] == "supervisor_or_secretariat_required"
    assert blockers[0]["exists"] is False


def test_source_state_audit_reports_no_commit_dirty_artifact_metadata(tmp_path):
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init"], cwd=tmp_path, text=True, capture_output=True, check=True)
    (tmp_path / "draft.py").write_text("print('draft')\n", encoding="utf-8")
    artifact = tmp_path / "results" / "processed" / "table_metadata.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps({
            "source_state": "no_commit+dirty",
            "source_snapshot_reproducible": False,
            "source_snapshot_limitation": "Generated from an unborn Git branch.",
        }),
        encoding="utf-8",
    )

    audit = thesis_audit._source_state_audit(tmp_path, [artifact])
    blockers = thesis_audit._submission_blockers([], source_state=audit)

    assert audit["passed"] is False
    assert audit["non_reproducible_entry_count"] == 1
    assert audit["unique_non_reproducible_states"] == ["no_commit+dirty"]
    assert blockers[0]["id"] == "source_snapshot_reproducibility"
    assert blockers[0]["status"] == "repository_required"


def test_source_state_audit_accepts_clean_committed_artifact_metadata(tmp_path):
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init"], cwd=tmp_path, text=True, capture_output=True, check=True)
    artifact = tmp_path / "results" / "processed" / "table_metadata.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps({
            "source_state": "abc1234",
            "source_snapshot_reproducible": True,
        }),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, text=True, capture_output=True, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Codex Test",
            "-c",
            "user.email=codex-test@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )

    audit = thesis_audit._source_state_audit(tmp_path, [artifact])

    assert audit["passed"] is True
    assert audit["non_reproducible_entry_count"] == 0


def test_pdf_deliverable_audit_detects_root_thesis_pdf_mismatch(tmp_path):
    root_pdf = tmp_path / "main.pdf"
    thesis_pdf = tmp_path / "thesis" / "main.pdf"
    thesis_pdf.parent.mkdir()
    root_pdf.write_bytes(b"new-pdf")
    thesis_pdf.write_bytes(b"old-pdf")

    audit = thesis_audit._pdf_deliverable_audit(root_pdf=root_pdf, thesis_pdf=thesis_pdf, root=tmp_path)

    assert audit["passed"] is False
    assert audit["hashes_match"] is False
    assert "differs" in audit["notes"][0]


def test_third_party_notice_audit_requires_notice_terms(tmp_path):
    license_path = tmp_path / "native" / "h48_backend" / "third_party" / "nissy_core" / "LICENSE"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("GPL-3.0-or-later\n", encoding="utf-8")
    notice = tmp_path / "docs" / "THIRD_PARTY_NOTICES.md"
    notice.parent.mkdir()
    notice.write_text(
        "nissy-core\n"
        "GPL-3.0-or-later\n"
        "native/h48_backend/third_party/nissy_core/LICENSE\n"
        "public-solver-derived\n"
        "not original thesis algorithmic work\n",
        encoding="utf-8",
    )

    audit = thesis_audit._third_party_notice_audit(tmp_path)

    assert audit["passed"] is True
    assert audit["missing_terms"] == []


def test_topic_brief_artifact_audit_requires_distance_and_heuristic_evidence(tmp_path):
    processed = tmp_path / "results" / "processed"
    table_dir = tmp_path / "thesis" / "tables"
    processed.mkdir(parents=True)
    table_dir.mkdir(parents=True)
    (processed / "edge_pdb_metadata_seed_2026_thesis.json").write_text(
        json.dumps({"total_size_bytes": 340_623_936}),
        encoding="utf-8",
    )
    (processed / "distance_recognition_corpus_seed_2026_thesis_topic_brief_bullet2.json").write_text(
        json.dumps({
            "profile": "thesis",
            "seed": 2026,
            "contains_live_exact": True,
            "contains_lower_bound": True,
            "contains_invalid_state": True,
            "contains_saved_hard_reference": True,
            "hard_search_started": False,
            "row_count": 6,
        }),
        encoding="utf-8",
    )
    (processed / "heuristic_comparison_seed_2026_thesis.json").write_text(
        json.dumps({
            "profile": "thesis",
            "seed": 2026,
            "a_star_variant": "IDA*",
            "all_exact_rows_admissible": True,
            "all_combined_not_weaker_than_components": True,
            "edge_pdb_bytes": 340_623_936,
            "case_count": 13,
        }),
        encoding="utf-8",
    )
    (processed / "heuristic_comparison_seed_2026_thesis.csv").write_text("case_id\nsolved\n", encoding="utf-8")
    (table_dir / "heuristic_comparison.tex").write_text("\\begin{tabular}{l}x\\end{tabular}\n", encoding="utf-8")

    audit = thesis_audit._topic_brief_artifact_audit(tmp_path)

    assert audit["passed"] is True
    assert audit["distance_row_count"] == 6
    assert audit["heuristic_case_count"] == 13


def test_backend_identity_audit_requires_h48_metadata_source_and_license(tmp_path):
    processed = tmp_path / "results" / "processed"
    processed.mkdir(parents=True)
    for solver in ("h48h0", "h48h7"):
        (processed / f"h48_metadata_seed_2026_thesis_{solver}.json").write_text(
            json.dumps({
                "backend_source": "vendored_nissy_core_h48",
                "license": "GPL-3.0-or-later",
            }),
            encoding="utf-8",
        )
    backend = tmp_path / "native" / "h48_backend" / "h48_backend.c"
    backend.parent.mkdir(parents=True)
    backend.write_text("vendored nissy-core wrapper\n", encoding="utf-8")

    audit = thesis_audit._backend_identity_audit(tmp_path)

    assert audit["passed"] is True
    assert audit["checks"]["metadata_identifies_vendored_backend"] is True


def test_verify_results_detects_stale_korf_pdb_byte_counts():
    row = {
        "solver": "korf_ida_star_scoped",
        "table_size_bytes": 258_496_594,
        "notes": "corner_pdb_bytes=88179896; edge_pdb_bytes=170311968",
    }

    errors = verify_results._pdb_byte_errors(
        row,
        1,
        88_179_896,
        340_623_936,
        verify_results.coordinate_pruning_table_bytes(),
    )

    assert len(errors) == 2
    assert "edge_pdb_bytes" in errors[0]
    assert "table_size_bytes" in errors[1]


def test_source_state_audit_does_not_self_ingest_thesis_audit_output(tmp_path):
    processed = tmp_path / "results" / "processed"
    processed.mkdir(parents=True)
    (processed / "thesis_audit.json").write_text(
        json.dumps({
            "source_state": {
                "current_source_state": {
                    "source_state": "no_commit+dirty",
                    "source_snapshot_reproducible": False,
                }
            }
        }),
        encoding="utf-8",
    )
    (processed / "edge_pdb_metadata_seed_2026_thesis.json").write_text(
        json.dumps({
            "source_state": "clean:abc123",
            "source_snapshot_reproducible": True,
        }),
        encoding="utf-8",
    )

    audit = thesis_audit._source_state_audit(tmp_path)

    assert audit["artifact_count_scanned"] == 1
    assert audit["source_state_entry_count"] == 1
    assert audit["non_reproducible_entry_count"] == 0
