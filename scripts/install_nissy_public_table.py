#!/usr/bin/env python
"""Install one table from the public Nissy 2.x table archive.

The public archive is large. This script reads the ZIP central directory,
downloads only the selected entry's compressed byte range, streams raw deflate
decompression to the local Nissy table directory, and validates the final CRC.
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import struct
import sys
import time
import urllib.request
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json
from scripts.inspect_nissy_public_tables import (
    PUBLIC_NISSY_TABLES_URL,
    fetch_head,
    fetch_zip_tail,
    parse_zip_central_directory,
)

DEFAULT_TABLE = "tables/pt_nxopt31_HTM"
LOCAL_HEADER_SIGNATURE = 0x04034B50
LOCAL_FILE_HEADER = struct.Struct("<IHHHHHIIIHH")


def _headers_to_dict(headers: object) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _request_range(url: str, start: int, end: int, *, timeout: float):
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    response = urllib.request.urlopen(request, timeout=timeout)
    if response.status != 206:
        response.close()
        raise RuntimeError(f"server did not honor range request {start}-{end}: status {response.status}")
    return response


def find_table_entry(
    *,
    url: str,
    table_name: str,
    tail_bytes: int,
    timeout: float,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    head = fetch_head(url, timeout=timeout)
    content_length = head.get("content_length")
    if not isinstance(content_length, int):
        raise RuntimeError("server did not report a content-length")
    tail, range_response = fetch_zip_tail(url, tail_bytes=tail_bytes, timeout=timeout)
    if range_response["status"] != 206:
        raise RuntimeError(f"server did not honor central-directory range request: {range_response['status']}")
    directory = parse_zip_central_directory(tail, content_length=content_length)
    entries = [entry for entry in directory["entries"] if entry["name"] == table_name]
    if not entries:
        available = ", ".join(str(entry["name"]) for entry in directory["entries"])
        raise RuntimeError(f"{table_name} not found in public Nissy archive; available entries: {available}")
    return head, range_response, directory, entries[0]


def parse_local_header(header: bytes, *, expected_name: str) -> dict[str, object]:
    if len(header) < LOCAL_FILE_HEADER.size:
        raise ValueError("local ZIP header is truncated")
    (
        signature,
        version_needed,
        flags,
        compression_method,
        last_mod_time,
        last_mod_date,
        crc32,
        compressed_size,
        uncompressed_size,
        name_length,
        extra_length,
    ) = LOCAL_FILE_HEADER.unpack_from(header)
    if signature != LOCAL_HEADER_SIGNATURE:
        raise ValueError("invalid local ZIP header signature")
    end = LOCAL_FILE_HEADER.size + name_length + extra_length
    if len(header) < end:
        raise ValueError("local ZIP header variable fields are truncated")
    encoding = "utf-8" if flags & 0x800 else "cp437"
    name = header[LOCAL_FILE_HEADER.size : LOCAL_FILE_HEADER.size + name_length].decode(encoding)
    if name != expected_name:
        raise ValueError(f"local ZIP header names {name!r}, expected {expected_name!r}")
    return {
        "version_needed": version_needed,
        "flags": flags,
        "compression_method": compression_method,
        "last_mod_time": last_mod_time,
        "last_mod_date": last_mod_date,
        "crc32": f"{crc32:08x}",
        "compressed_size": compressed_size,
        "uncompressed_size": uncompressed_size,
        "name": name,
        "name_length": name_length,
        "extra_length": extra_length,
        "data_offset_delta": end,
    }


def fetch_local_header(
    *,
    url: str,
    table_name: str,
    local_header_offset: int,
    timeout: float,
) -> dict[str, object]:
    # 64 KiB is enough for normal ZIP local headers and still cheap to fetch.
    with _request_range(url, local_header_offset, local_header_offset + 65535, timeout=timeout) as response:
        header = response.read()
    return parse_local_header(header, expected_name=table_name)


def write_entry_from_compressed_chunks(
    chunks: Iterable[bytes],
    *,
    compression_method: int,
    expected_crc32: str,
    expected_uncompressed_size: int,
    target_path: Path,
) -> dict[str, object]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + ".tmp")
    crc = 0
    compressed_bytes = 0
    uncompressed_bytes = 0
    started = time.perf_counter()
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS) if compression_method == 8 else None
    if compression_method not in {0, 8}:
        raise RuntimeError(f"unsupported ZIP compression method: {compression_method}")
    try:
        with temporary.open("wb") as output:
            for chunk in chunks:
                if not chunk:
                    continue
                compressed_bytes += len(chunk)
                data = decompressor.decompress(chunk) if decompressor is not None else chunk
                if data:
                    output.write(data)
                    crc = binascii.crc32(data, crc)
                    uncompressed_bytes += len(data)
            if decompressor is not None:
                data = decompressor.flush()
                if data:
                    output.write(data)
                    crc = binascii.crc32(data, crc)
                    uncompressed_bytes += len(data)
        actual_crc = f"{crc & 0xFFFFFFFF:08x}"
        if uncompressed_bytes != expected_uncompressed_size:
            raise RuntimeError(
                f"uncompressed size mismatch: expected {expected_uncompressed_size}, got {uncompressed_bytes}"
            )
        if actual_crc.lower() != expected_crc32.lower():
            raise RuntimeError(f"CRC32 mismatch: expected {expected_crc32}, got {actual_crc}")
        os.replace(temporary, target_path)
        return {
            "compressed_bytes_read": compressed_bytes,
            "uncompressed_bytes_written": uncompressed_bytes,
            "crc32": actual_crc,
            "runtime_seconds": round(time.perf_counter() - started, 6),
        }
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def stream_remote_entry_to_table(
    *,
    url: str,
    entry: dict[str, object],
    local_header: dict[str, object],
    target_path: Path,
    timeout: float,
    chunk_size: int,
    progress_mib: int,
) -> dict[str, object]:
    compressed_size = int(entry["compressed_size"])
    data_start = int(entry["local_header_offset"]) + int(local_header["data_offset_delta"])
    data_end = data_start + compressed_size - 1
    next_report = progress_mib * 1024 * 1024 if progress_mib > 0 else 0
    seen = 0

    def chunks() -> Iterable[bytes]:
        nonlocal seen, next_report
        with _request_range(url, data_start, data_end, timeout=timeout) as response:
            headers = _headers_to_dict(response.headers)
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                seen += len(chunk)
                if progress_mib > 0 and seen >= next_report:
                    print(
                        f"downloaded {seen / (1024 * 1024):.1f} MiB compressed "
                        f"of {compressed_size / (1024 * 1024):.1f} MiB",
                        file=sys.stderr,
                        flush=True,
                    )
                    next_report += progress_mib * 1024 * 1024
                yield chunk
            if int(headers.get("content-length", compressed_size)) != compressed_size:
                raise RuntimeError(
                    f"range response content-length mismatch for {entry['name']}: {headers.get('content-length')}"
                )

    return write_entry_from_compressed_chunks(
        chunks(),
        compression_method=int(entry["compression_method"]),
        expected_crc32=str(entry["crc32"]),
        expected_uncompressed_size=int(entry["uncompressed_size"]),
        target_path=target_path,
    )


def _write_latex_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    table_path = root / "thesis" / "tables" / f"nissy_public_table_install{suffix}.tex"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    status = "installed" if payload["installed"] else "present"
    table_name = str(payload["table_name"]).replace("\\", "\\textbackslash{}").replace("_", "\\_")
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrl}\n"
        "\\hline\n"
        "Table & Compressed MiB & Uncompressed MiB & Status \\\\\n"
        "\\hline\n"
        f"{table_name} & "
        f"{int(payload['archive_entry']['compressed_size']) / (1024 * 1024):.1f} & "
        f"{int(payload['archive_entry']['uncompressed_size']) / (1024 * 1024):.1f} & "
        f"{status} \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=PUBLIC_NISSY_TABLES_URL)
    parser.add_argument("--table-name", default=DEFAULT_TABLE)
    parser.add_argument("--target-dir", type=Path, default=ROOT / ".codex_external" / "nissy_data" / "tables")
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--tail-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--chunk-size", type=int, default=1024 * 1024)
    parser.add_argument("--progress-mib", type=int, default=128)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    if not args.table_name.startswith("tables/"):
        raise SystemExit("--table-name must be an archive entry under tables/")
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size must be positive")

    head, central_range, directory, entry = find_table_entry(
        url=args.url,
        table_name=args.table_name,
        tail_bytes=args.tail_bytes,
        timeout=args.timeout,
    )
    table_basename = Path(args.table_name).name
    target_path = args.target_dir / table_basename
    local_header: dict[str, object] | None = None
    install_result: dict[str, object] | None = None
    installed = False
    already_present = target_path.exists()
    errors: list[str] = []

    if args.dry_run:
        pass
    elif already_present and not args.force:
        if target_path.stat().st_size != int(entry["uncompressed_size"]):
            errors.append(
                f"existing table has size {target_path.stat().st_size}, expected {entry['uncompressed_size']}; "
                "rerun with --force"
            )
    else:
        local_header = fetch_local_header(
            url=args.url,
            table_name=args.table_name,
            local_header_offset=int(entry["local_header_offset"]),
            timeout=args.timeout,
        )
        install_result = stream_remote_entry_to_table(
            url=args.url,
            entry=entry,
            local_header=local_header,
            target_path=target_path,
            timeout=args.timeout,
            chunk_size=args.chunk_size,
            progress_mib=args.progress_mib,
        )
        installed = True

    suffix_parts = [f"seed_{args.seed}", args.profile, table_basename]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(suffix_parts)
    payload = {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "source_url": args.url,
        "table_name": args.table_name,
        "target_path": str(target_path.relative_to(args.root) if target_path.is_absolute() else target_path),
        "archive_head": head,
        "central_directory": directory["central_directory"],
        "central_directory_range_response": central_range,
        "archive_entry": entry,
        "local_header": local_header,
        "dry_run": args.dry_run,
        "already_present": already_present,
        "installed": installed,
        "install_result": install_result,
        "target_exists": target_path.exists(),
        "target_size_bytes": target_path.stat().st_size if target_path.exists() else None,
        "target_size_matches_archive": (
            target_path.exists() and target_path.stat().st_size == int(entry["uncompressed_size"])
        ),
        "errors": errors,
        "passed": not errors and (args.dry_run or (target_path.exists() and target_path.stat().st_size == int(entry["uncompressed_size"]))),
    }
    output = args.root / "results" / "processed" / f"nissy_public_table_install{suffix}.json"
    write_json(output, payload)
    table = _write_latex_table(args.root, payload, suffix)
    print(json.dumps({"output": str(output), "table": str(table), "passed": payload["passed"]}, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
