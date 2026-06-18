#!/usr/bin/env python
"""Inspect the public Nissy 2.x table archive without downloading it.

The archive is large, so this script uses HTTP HEAD plus a byte-range read of
the ZIP central directory. The resulting manifest records whether the public
package contains H48 tables that could replace locally generated h48hN.bin
artifacts.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.results import write_json

PUBLIC_NISSY_TABLES_URL = "https://nissy.tronto.net/nissy-tables-2.0.4.zip"
_EOCD_SIGNATURE = 0x06054B50
_CENTRAL_SIGNATURE = 0x02014B50
_EOCD = struct.Struct("<IHHHHIIH")
_CENTRAL_FILE_HEADER = struct.Struct("<IHHHHHHIIIHHHHHII")


def _headers_to_dict(headers: Any) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def fetch_head(url: str, *, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = _headers_to_dict(response.headers)
        length = headers.get("content-length")
        return {
            "status": response.status,
            "content_length": int(length) if length is not None else None,
            "last_modified": headers.get("last-modified"),
            "etag": headers.get("etag"),
            "accept_ranges": headers.get("accept-ranges"),
            "content_type": headers.get("content-type"),
            "headers": headers,
        }


def fetch_zip_tail(url: str, *, tail_bytes: int, timeout: float) -> tuple[bytes, dict[str, object]]:
    request = urllib.request.Request(url, headers={"Range": f"bytes=-{tail_bytes}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        headers = _headers_to_dict(response.headers)
        return data, {
            "status": response.status,
            "requested_tail_bytes": tail_bytes,
            "received_bytes": len(data),
            "content_range": headers.get("content-range"),
            "headers": headers,
        }


def _decode_zip_name(raw: bytes, flags: int) -> str:
    encoding = "utf-8" if flags & 0x800 else "cp437"
    return raw.decode(encoding)


def parse_zip_central_directory(tail: bytes, *, content_length: int) -> dict[str, object]:
    """Parse a ZIP central directory from a suffix byte range."""

    if content_length < len(tail):
        raise ValueError("content_length is smaller than supplied tail")
    eocd_pos = tail.rfind(struct.pack("<I", _EOCD_SIGNATURE))
    if eocd_pos < 0:
        raise ValueError("ZIP end-of-central-directory record was not found in the supplied tail")
    if eocd_pos + _EOCD.size > len(tail):
        raise ValueError("truncated ZIP end-of-central-directory record")

    (
        signature,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = _EOCD.unpack_from(tail, eocd_pos)
    if signature != _EOCD_SIGNATURE:
        raise ValueError("invalid ZIP end-of-central-directory signature")
    if eocd_pos + _EOCD.size + comment_length > len(tail):
        raise ValueError("truncated ZIP comment after end-of-central-directory record")
    if disk_number != 0 or central_disk != 0:
        raise ValueError("multi-disk ZIP archives are not supported")

    tail_absolute_start = content_length - len(tail)
    central_absolute_end = central_offset + central_size
    if central_offset < tail_absolute_start:
        missing = tail_absolute_start - central_offset
        raise ValueError(f"supplied tail is too small for central directory; missing {missing} leading bytes")
    if central_absolute_end > content_length:
        raise ValueError("central directory extends past archive length")

    offset = central_offset - tail_absolute_start
    entries: list[dict[str, object]] = []
    for _ in range(total_entries):
        if offset + _CENTRAL_FILE_HEADER.size > len(tail):
            raise ValueError("truncated central-directory file header")
        fields = _CENTRAL_FILE_HEADER.unpack_from(tail, offset)
        (
            signature,
            version_made_by,
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
            comment_length,
            disk_start,
            internal_attrs,
            external_attrs,
            local_header_offset,
        ) = fields
        if signature != _CENTRAL_SIGNATURE:
            raise ValueError("invalid central-directory file-header signature")
        name_start = offset + _CENTRAL_FILE_HEADER.size
        name_end = name_start + name_length
        extra_end = name_end + extra_length
        comment_end = extra_end + comment_length
        if comment_end > len(tail):
            raise ValueError("truncated central-directory variable fields")
        name = _decode_zip_name(tail[name_start:name_end], flags)
        entries.append(
            {
                "name": name,
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "crc32": f"{crc32:08x}",
                "compression_method": compression_method,
                "flags": flags,
                "version_made_by": version_made_by,
                "version_needed": version_needed,
                "last_mod_time": last_mod_time,
                "last_mod_date": last_mod_date,
                "disk_start": disk_start,
                "internal_attrs": internal_attrs,
                "external_attrs": external_attrs,
                "local_header_offset": local_header_offset,
            }
        )
        offset = comment_end

    return {
        "central_directory": {
            "entries_this_disk": disk_entries,
            "total_entries": total_entries,
            "size_bytes": central_size,
            "offset": central_offset,
            "comment_length": comment_length,
        },
        "entries": entries,
    }


def build_manifest(
    *,
    source_url: str,
    head: dict[str, object],
    range_response: dict[str, object],
    zip_directory: dict[str, object],
) -> dict[str, object]:
    entries = list(zip_directory["entries"])
    table_entries = [
        entry
        for entry in entries
        if str(entry["name"]).startswith("tables/") and not str(entry["name"]).endswith("/")
    ]
    h48_entries = [entry for entry in table_entries if "h48" in str(entry["name"]).lower()]
    nxopt_entries = [entry for entry in table_entries if "nxopt" in str(entry["name"]).lower()]
    largest_entries = sorted(
        table_entries,
        key=lambda entry: int(entry["uncompressed_size"]),
        reverse=True,
    )[:10]
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "source_url": source_url,
        "request_strategy": "HTTP HEAD plus ZIP central-directory byte-range read; no full archive download",
        "head": head,
        "range_response": range_response,
        "central_directory": zip_directory["central_directory"],
        "entry_count": len(entries),
        "table_entry_count": len(table_entries),
        "table_entries": table_entries,
        "largest_table_entries": largest_entries,
        "h48_entries": h48_entries,
        "nxopt_entries": nxopt_entries,
        "conclusion": {
            "contains_h48_entries": bool(h48_entries),
            "h48_drop_in_for_native_backend": False,
            "reason": (
                "The public Nissy 2.x archive contains pt_* and nxopt-style tables, "
                "not h48hN.bin artifacts expected by the in-repository nissy-core H48 wrapper."
            ),
            "external_solver_use": (
                "The package can support the external Nissy 2.x solver after full download/extraction, "
                "but it is not a direct replacement for locally generated H48 h48h8/h48h11 tables."
            ),
        },
    }


def _tex(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")


def _write_latex_table(root: Path, payload: dict[str, object], suffix: str) -> Path:
    filename = f"nissy_public_tables_manifest{suffix}.tex" if suffix else "nissy_public_tables_manifest.tex"
    table_path = root / "thesis" / "tables" / filename
    table_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in payload["largest_table_entries"]:
        rows.append(
            f"{_tex(entry['name'])} & "
            f"{int(entry['compressed_size']) / (1024 * 1024):.1f} & "
            f"{int(entry['uncompressed_size']) / (1024 * 1024):.1f} & "
            f"{_tex(entry['crc32'])} \\\\"
        )
    table_path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrrl}\n"
        "\\hline\n"
        "Archive entry & Compressed MiB & Uncompressed MiB & CRC32 \\\\\n"
        "\\hline\n"
        + "\n".join(rows)
        + "\n\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )
    return table_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=PUBLIC_NISSY_TABLES_URL)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--tail-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--artifact-suffix", default="")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    if args.tail_bytes <= 0:
        raise SystemExit("--tail-bytes must be positive")

    head = fetch_head(args.url, timeout=args.timeout)
    content_length = head.get("content_length")
    if not isinstance(content_length, int):
        raise SystemExit("server did not report a content-length")
    tail, range_response = fetch_zip_tail(args.url, tail_bytes=args.tail_bytes, timeout=args.timeout)
    if range_response["status"] != 206:
        raise SystemExit(f"server did not honor range request: status {range_response['status']}")
    zip_directory = parse_zip_central_directory(tail, content_length=content_length)
    payload = build_manifest(
        source_url=args.url,
        head=head,
        range_response=range_response,
        zip_directory=zip_directory,
    )

    suffix_parts = [f"seed_{args.seed}", args.profile]
    if args.artifact_suffix:
        suffix_parts.append(args.artifact_suffix)
    suffix = "_" + "_".join(suffix_parts)
    output = args.root / "results" / "processed" / f"nissy_public_tables_manifest{suffix}.json"
    write_json(output, payload)
    table = _write_latex_table(args.root, payload, suffix)
    print(
        json.dumps(
            {
                "output": str(output),
                "table": str(table),
                "contains_h48_entries": payload["conclusion"]["contains_h48_entries"],
                "table_entry_count": payload["table_entry_count"],
                "request_strategy": payload["request_strategy"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
