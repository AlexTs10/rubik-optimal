#!/usr/bin/env python
"""Generate coordinate move/pruning tables with reproducibility metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.tables.generation import generate_coordinate_tables


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default="quick")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    profile = "quick" if args.quick else args.profile
    manifest = generate_coordinate_tables(root=args.root, profile=profile, seed=args.seed)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
