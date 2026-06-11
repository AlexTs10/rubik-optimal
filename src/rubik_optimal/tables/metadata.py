"""Metadata helpers for generated Rubik lookup tables."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class GeneratedTableMetadata:
    table_name: str
    table_kind: str
    profile: str
    seed: int
    domain_size: int
    entry_count: int
    file_path: str
    checksum_sha256: str
    generated_at_utc: str
    generator: str
    runtime_seconds: float
    size_bytes: int
    moves: list[str]
    source_state: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

