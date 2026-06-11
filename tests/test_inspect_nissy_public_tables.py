from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.inspect_nissy_public_tables import build_manifest, parse_zip_central_directory


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_parse_zip_central_directory_from_tail_lists_table_entries():
    data = _zip_bytes(
        {
            "tables/pt_nxopt31_HTM": b"x" * 128,
            "tables/pt_corners_HTM": b"y" * 32,
            "README.txt": b"not a table",
        }
    )

    parsed = parse_zip_central_directory(data[-512:], content_length=len(data))
    manifest = build_manifest(
        source_url="https://example.test/nissy-tables.zip",
        head={"content_length": len(data)},
        range_response={"status": 206},
        zip_directory=parsed,
    )

    names = {entry["name"] for entry in manifest["table_entries"]}
    assert names == {"tables/pt_nxopt31_HTM", "tables/pt_corners_HTM"}
    assert manifest["table_entry_count"] == 2
    assert manifest["nxopt_entries"][0]["name"] == "tables/pt_nxopt31_HTM"
    assert manifest["conclusion"]["contains_h48_entries"] is False
    assert manifest["conclusion"]["h48_drop_in_for_native_backend"] is False


def test_parse_zip_central_directory_records_h48_names_when_present():
    data = _zip_bytes({"tables/h48h8.bin": b"z" * 16})

    parsed = parse_zip_central_directory(data, content_length=len(data))
    manifest = build_manifest(
        source_url="https://example.test/nissy-tables.zip",
        head={"content_length": len(data)},
        range_response={"status": 206},
        zip_directory=parsed,
    )

    assert manifest["h48_entries"][0]["name"] == "tables/h48h8.bin"
    assert manifest["conclusion"]["contains_h48_entries"] is True
    assert manifest["conclusion"]["h48_drop_in_for_native_backend"] is False
