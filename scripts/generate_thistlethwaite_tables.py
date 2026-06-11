#!/usr/bin/env python3
"""Generate (or regenerate) the exact Thistlethwaite per-phase coset tables.

Run from the repository root:

    PYTHONPATH=src python3 scripts/generate_thistlethwaite_tables.py

The four phase distance tables are written under
``data/generated/thistlethwaite/`` as raw little-endian uint8 binaries, with a
checksummed ``thistlethwaite_manifest.json``.  Generation is deterministic, so
re-running produces byte-identical files and identical checksums.

The reported maximum distances (7 / 10 / 13 / 15) are the published
Thistlethwaite phase bounds, which independently confirms the coordinate / coset
spaces are correct.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rubik_optimal.tables.thistlethwaite_tables import generate_thistlethwaite_tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (defaults to the directory containing data/generated).",
    )
    args = parser.parse_args()

    begin = time.perf_counter()
    manifest = generate_thistlethwaite_tables(root=args.root)
    total = time.perf_counter() - begin

    print(f"Generated Thistlethwaite tables in {total:.2f}s")
    print("Coset signature:")
    for key, value in sorted(manifest["coset_signature"].items()):
        print(f"  {key}: {value}")
    print("Tables:")
    for row in manifest["tables"]:
        print(
            f"  {row['phase']}: {row['description']}\n"
            f"    file={row['file']} size={row['size_bytes']} bytes "
            f"reachable={row['reachable_states']} max_distance={row['max_distance']} "
            f"gen={row['generation_seconds']}s\n"
            f"    sha256={row['checksum_sha256']}"
        )


if __name__ == "__main__":
    main()
