import json
from pathlib import Path

import pytest

from scripts import apply_final_metadata


VALID_VALUES = {
    "thesis_student_name": "ΑΛΕΞΑΝΔΡΟΣ ΠΑΡΑΔΕΙΓΜΑ",
    "thesis_student_name_english": "ALEXANDROS PARADEIGMA",
    "thesis_student_full_name": "ΑΛΕΞΑΝΔΡΟΣ ΠΑΡΑΔΕΙΓΜΑ ΤΟΥ ΠΑΝΑΓΙΩΤΗ",
    "thesis_registration_number": "1234567",
    "thesis_place_date": "ΠΑΤΡΑ - ΜΑΪΟΣ 2026",
    "copyright_year": "2026",
    "exam_date": "17/05/2026",
    "committee_member_2": "Μέλος Δύο, Καθηγητής, Τμήμα ΗΜΤΥ",
    "committee_member_3": "Μέλος Τρία, Επίκουρος Καθηγητής, Τμήμα ΗΜΤΥ",
    "division_director_name": "Διευθυντής Τομέα",
    "division_director_rank": "Καθηγητής",
}


def _write_front_matter_fixture(root: Path) -> None:
    thesis = root / "thesis"
    chapters = thesis / "chapters"
    chapters.mkdir(parents=True)
    (thesis / "main.tex").write_text(
        "\\newcommand{\\thesisStudentName}{ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ}\n"
        "\\newcommand{\\thesisStudentNameEnglish}{STUDENT NAME, SURNAME}\n"
        "\\newcommand{\\thesisStudentFullName}{ΟΝΟΜΑ ΕΠΩΝΥΜΟ ΤΟΥ ΠΑΤΡΩΝΥΜΟ}\n"
        "\\newcommand{\\thesisRegistrationNumber}{ΧΧΧΧΧΧΧ}\n"
        "\\newcommand{\\thesisPlaceDate}{ΠΑΤΡΑ - ΜΗΝΑΣ ΕΤΟΣ}\n",
        encoding="utf-8",
    )
    (chapters / "00_front_matter.tex").write_text(
        "© 20XX -- Με την επιφύλαξη παντός δικαιώματος\n"
        "…….../……../………\n"
        "Όνομα Επώνυμο, Βαθμίδα, Τμήμα (μέλος επιτροπής)\\\\[0.25cm]\n"
        "Όνομα Επώνυμο, Βαθμίδα, Τμήμα (μέλος επιτροπής)\n"
        "\\centering \\thesisSupervisor && \\centering Ονοματεπώνυμο \\tabularnewline\n"
        "\\centering \\thesisSupervisorRank && \\centering Βαθμίδα \\tabularnewline\n",
        encoding="utf-8",
    )


def test_apply_metadata_replaces_only_final_front_matter_fields(tmp_path):
    _write_front_matter_fixture(tmp_path)

    result = apply_final_metadata.apply_metadata(tmp_path, VALID_VALUES)

    assert result["changed_files"] == ["thesis/main.tex", "thesis/chapters/00_front_matter.tex"]
    assert set(result["updated_fields"]) == set(apply_final_metadata.REQUIRED_FIELDS)
    main = (tmp_path / "thesis" / "main.tex").read_text(encoding="utf-8")
    front = (tmp_path / "thesis" / "chapters" / "00_front_matter.tex").read_text(encoding="utf-8")
    assert "ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ" not in main
    assert "ΑΛΕΞΑΝΔΡΟΣ ΠΑΡΑΔΕΙΓΜΑ" in main
    assert "20XX" not in front
    assert "© 2026 -- Με την επιφύλαξη παντός δικαιώματος" in front
    assert "Μέλος Δύο, Καθηγητής, Τμήμα ΗΜΤΥ" in front
    assert "Διευθυντής Τομέα" in front


def test_apply_metadata_dry_run_does_not_write(tmp_path):
    _write_front_matter_fixture(tmp_path)

    result = apply_final_metadata.apply_metadata(tmp_path, VALID_VALUES, dry_run=True)

    assert result["dry_run"] is True
    assert result["changed_files"] == ["thesis/main.tex", "thesis/chapters/00_front_matter.tex"]
    main = (tmp_path / "thesis" / "main.tex").read_text(encoding="utf-8")
    assert "ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ" in main


def test_apply_metadata_rejects_placeholder_values(tmp_path):
    _write_front_matter_fixture(tmp_path)
    values = dict(VALID_VALUES)
    values["thesis_registration_number"] = "TODO registration number"

    with pytest.raises(apply_final_metadata.MetadataError, match="thesis_registration_number"):
        apply_final_metadata.apply_metadata(tmp_path, values)


def test_load_values_requires_json_object(tmp_path):
    values_path = tmp_path / "values.json"
    values_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(apply_final_metadata.MetadataError, match="JSON object"):
        apply_final_metadata._load_values(values_path)
