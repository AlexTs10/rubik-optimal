#!/usr/bin/env python
"""Regenerate derived thesis figure/table data from saved benchmark rows."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.benchmark import generate_benchmark_artifacts_from_saved_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default=None)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)
    profile = args.profile or ("quick" if args.quick else "thesis")
    generate_benchmark_artifacts_from_saved_results(seed=args.seed, profile=profile, root=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
