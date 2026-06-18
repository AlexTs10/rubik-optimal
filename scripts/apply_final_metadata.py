#!/usr/bin/env python
"""Apply supervisor-approved final front-matter metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FIELDS = {
    "thesis_student_name": "Greek student display name",
    "thesis_student_name_english": "English student display name",
    "thesis_student_full_name": "Full student name with patronymic",
    "thesis_registration_number": "Student registration number",
    "thesis_place_date": "Cover place/month/year line",
    "copyright_year": "Copyright year",
    "exam_date": "Public examination date",
    "committee_member_2": "Second committee member name/rank/department",
    "committee_member_3": "Third committee member name/rank/department",
    "division_director_name": "Division director name",
    "division_director_rank": "Division director rank/title",
}

MACRO_FIELDS = {
    "thesis_student_name": "thesisStudentName",
    "thesis_student_name_english": "thesisStudentNameEnglish",
    "thesis_student_full_name": "thesisStudentFullName",
    "thesis_registration_number": "thesisRegistrationNumber",
    "thesis_place_date": "thesisPlaceDate",
}

PLACEHOLDER_PATTERN = re.compile(
    r"TODO|TBD|PENDING|NEEDS_CONFIRMATION|PLACEHOLDER|"
    r"ΟΝΟΜΑΤΕΠΩΝΥΜΟ ΦΟΙΤΗΤΗ|STUDENT NAME, SURNAME|"
    r"ΟΝΟΜΑ ΕΠΩΝΥΜΟ ΤΟΥ ΠΑΤΡΩΝΥΜΟ|ΧΧΧΧΧΧΧ|"
    r"ΜΗΝΑΣ ΕΤΟΣ|20XX|……|Όνομα Επώνυμο|Ονοματεπώνυμο|Βαθμίδα",
    re.IGNORECASE,
)


class MetadataError(ValueError):
    """Raised when approved metadata is incomplete or cannot be applied."""


def _load_values(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MetadataError("metadata file must contain a JSON object")
    return {str(key): str(value).strip() for key, value in data.items()}


def _validate_values(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for field, label in REQUIRED_FIELDS.items():
        value = values.get(field, "")
        if not value:
            errors.append(f"{field}: missing {label}")
        elif PLACEHOLDER_PATTERN.search(value):
            errors.append(f"{field}: value still looks like a placeholder")

    extra_fields = sorted(set(values) - set(REQUIRED_FIELDS))
    for field in extra_fields:
        errors.append(f"{field}: unexpected metadata field")

    return errors


def _replace_once(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if old not in text:
        raise MetadataError(f"placeholder not found for {label}")
    return text.replace(old, new, 1), old != new


def _replace_macro(text: str, macro_name: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(\\newcommand\{{\\{re.escape(macro_name)}\}}\{{)([^}}]*)(\}})")
    match = pattern.search(text)
    if not match:
        raise MetadataError(f"macro not found: {macro_name}")
    changed = match.group(2) != value
    return pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(3)}", text, count=1), changed


def _apply_main_tex(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    changed_fields: list[str] = []
    for field, macro_name in MACRO_FIELDS.items():
        text, changed = _replace_macro(text, macro_name, values[field])
        if changed:
            changed_fields.append(field)
    return text, changed_fields


def _apply_front_matter(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    replacements = [
        (
            "© 20XX -- Με την επιφύλαξη παντός δικαιώματος",
            f"© {values['copyright_year']} -- Με την επιφύλαξη παντός δικαιώματος",
            "copyright_year",
        ),
        ("…….../……../………", values["exam_date"], "exam_date"),
        (
            "Όνομα Επώνυμο, Βαθμίδα, Τμήμα (μέλος επιτροπής)\\\\[0.25cm]",
            f"{values['committee_member_2']}\\\\[0.25cm]",
            "committee_member_2",
        ),
        (
            "Όνομα Επώνυμο, Βαθμίδα, Τμήμα (μέλος επιτροπής)",
            values["committee_member_3"],
            "committee_member_3",
        ),
        (
            "\\centering \\thesisSupervisor && \\centering Ονοματεπώνυμο \\tabularnewline",
            f"\\centering \\thesisSupervisor && \\centering {values['division_director_name']} \\tabularnewline",
            "division_director_name",
        ),
        (
            "\\centering \\thesisSupervisorRank && \\centering Βαθμίδα \\tabularnewline",
            f"\\centering \\thesisSupervisorRank && \\centering {values['division_director_rank']} \\tabularnewline",
            "division_director_rank",
        ),
    ]

    changed_fields: list[str] = []
    for old, new, field in replacements:
        text, changed = _replace_once(text, old, new, field)
        if changed:
            changed_fields.append(field)
    return text, changed_fields


def apply_metadata(root: Path, values: dict[str, str], dry_run: bool = False) -> dict[str, Any]:
    errors = _validate_values(values)
    if errors:
        raise MetadataError("; ".join(errors))

    main_path = root / "thesis" / "main.tex"
    front_path = root / "thesis" / "chapters" / "00_front_matter.tex"
    if not main_path.exists():
        raise MetadataError(f"missing file: {main_path}")
    if not front_path.exists():
        raise MetadataError(f"missing file: {front_path}")

    main_text = main_path.read_text(encoding="utf-8")
    front_text = front_path.read_text(encoding="utf-8")
    updated_main, main_fields = _apply_main_tex(main_text, values)
    updated_front, front_fields = _apply_front_matter(front_text, values)

    changed_files: list[str] = []
    if updated_main != main_text:
        changed_files.append(str(main_path.relative_to(root)))
        if not dry_run:
            main_path.write_text(updated_main, encoding="utf-8")
    if updated_front != front_text:
        changed_files.append(str(front_path.relative_to(root)))
        if not dry_run:
            front_path.write_text(updated_front, encoding="utf-8")

    return {
        "dry_run": dry_run,
        "changed_files": changed_files,
        "updated_fields": main_fields + front_fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("values", type=Path, help="JSON file with supervisor-approved final metadata")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        values = _load_values(args.values)
        result = apply_metadata(args.root, values, dry_run=args.dry_run)
    except (json.JSONDecodeError, MetadataError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
