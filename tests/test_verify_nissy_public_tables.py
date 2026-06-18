from pathlib import Path

from scripts.verify_nissy_public_tables import build_public_table_completeness_payload


def _manifest() -> dict[str, object]:
    return {
        "source_url": "https://example.test/nissy-tables.zip",
        "table_entries": [
            {
                "name": "tables/pt_nxopt31_HTM",
                "uncompressed_size": 4,
                "crc32": "abcd1234",
            },
            {
                "name": "tables/mtables",
                "uncompressed_size": 3,
                "crc32": "00000000",
            },
        ],
    }


def _fake_nissy(path: Path, *, warning: bool = False) -> Path:
    output = (
        "--- Warning ---\nSome pruning tables are missing or unreadable\n"
        if warning
        else ""
    )
    output += "Available pruning tables:\n\tpt_nxopt31_HTM\n"
    binary = path / "nissy"
    binary.write_text(f"#!/bin/sh\ncat <<'NISSY_OUTPUT'\n{output}NISSY_OUTPUT\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_nissy_public_tables_completeness_passes_when_all_sizes_match_and_no_warning(tmp_path: Path):
    table_dir = tmp_path / "nissy_data" / "tables"
    table_dir.mkdir(parents=True)
    (table_dir / "pt_nxopt31_HTM").write_bytes(b"1234")
    (table_dir / "mtables").write_bytes(b"123")
    binary = _fake_nissy(tmp_path)

    payload = build_public_table_completeness_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        table_dir=table_dir,
        manifest=_manifest(),
        binary_path=binary,
        ptable_timeout=1.0,
    )

    assert payload["passed"] is True
    assert payload["all_archive_tables_installed"] is True
    assert payload["all_archive_table_sizes_match"] is True
    assert payload["nissy_ptable"]["reports_missing_tables"] is False
    assert payload["fast_runtime_proven_for_every_possible_state"] is False


def test_nissy_public_tables_completeness_fails_on_missing_table_or_warning(tmp_path: Path):
    table_dir = tmp_path / "nissy_data" / "tables"
    table_dir.mkdir(parents=True)
    (table_dir / "pt_nxopt31_HTM").write_bytes(b"1234")
    binary = _fake_nissy(tmp_path, warning=True)

    payload = build_public_table_completeness_payload(
        root=tmp_path,
        profile="thesis",
        seed=2026,
        table_dir=table_dir,
        manifest=_manifest(),
        binary_path=binary,
        ptable_timeout=1.0,
    )

    assert payload["passed"] is False
    assert payload["missing_tables"] == ["tables/mtables"]
    assert payload["nissy_ptable"]["reports_missing_tables"] is True
