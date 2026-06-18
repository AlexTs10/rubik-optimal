from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.inspect_nissy_public_tables import parse_zip_central_directory
from scripts.install_nissy_public_table import parse_local_header, write_entry_from_compressed_chunks


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_parse_local_header_and_stream_one_public_table_entry(tmp_path: Path):
    original = (b"nxopt-test-data-" * 128) + b"end"
    archive = _zip_bytes({"tables/pt_nxopt31_HTM": original})
    parsed = parse_zip_central_directory(archive, content_length=len(archive))
    entry = next(row for row in parsed["entries"] if row["name"] == "tables/pt_nxopt31_HTM")

    local_offset = int(entry["local_header_offset"])
    local_header = parse_local_header(archive[local_offset : local_offset + 512], expected_name="tables/pt_nxopt31_HTM")
    data_offset = local_offset + int(local_header["data_offset_delta"])
    compressed = archive[data_offset : data_offset + int(entry["compressed_size"])]
    target = tmp_path / "pt_nxopt31_HTM"

    result = write_entry_from_compressed_chunks(
        [compressed[:7], compressed[7:]],
        compression_method=int(entry["compression_method"]),
        expected_crc32=str(entry["crc32"]),
        expected_uncompressed_size=int(entry["uncompressed_size"]),
        target_path=target,
    )

    assert target.read_bytes() == original
    assert result["crc32"] == entry["crc32"]
    assert result["uncompressed_bytes_written"] == len(original)


def test_parse_local_header_rejects_wrong_entry_name():
    archive = _zip_bytes({"tables/pt_nxopt31_HTM": b"x"})
    parsed = parse_zip_central_directory(archive, content_length=len(archive))
    entry = parsed["entries"][0]

    with pytest.raises(ValueError, match="expected"):
        parse_local_header(
            archive[int(entry["local_header_offset"]) : int(entry["local_header_offset"]) + 512],
            expected_name="tables/other",
        )


def test_stream_extraction_removes_tmp_file_on_validation_error(tmp_path: Path):
    archive = _zip_bytes({"tables/pt_nxopt31_HTM": b"x" * 64})
    parsed = parse_zip_central_directory(archive, content_length=len(archive))
    entry = parsed["entries"][0]
    local_offset = int(entry["local_header_offset"])
    local_header = parse_local_header(archive[local_offset : local_offset + 512], expected_name=str(entry["name"]))
    data_offset = local_offset + int(local_header["data_offset_delta"])
    compressed = archive[data_offset : data_offset + int(entry["compressed_size"])]
    target = tmp_path / "pt_nxopt31_HTM"

    with pytest.raises(RuntimeError, match="uncompressed size mismatch"):
        write_entry_from_compressed_chunks(
            [compressed],
            compression_method=int(entry["compression_method"]),
            expected_crc32=str(entry["crc32"]),
            expected_uncompressed_size=65,
            target_path=target,
        )

    assert not target.exists()
    assert not target.with_suffix(".tmp").exists()
