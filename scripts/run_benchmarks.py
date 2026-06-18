#!/usr/bin/env python
"""Run reproducible Rubik thesis benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rubik_optimal.benchmark import run_benchmarks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Use the fast CI/supervisor-review dataset")
    parser.add_argument("--profile", choices=["quick", "thesis", "stress"], default=None)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--resume", action="store_true", help="Resume from already generated raw rows")
    args = parser.parse_args()
    profile = args.profile or ("quick" if args.quick else "thesis")
    paths = run_benchmarks(
        seed=args.seed,
        profile=profile,
        root=Path.cwd(),
        progress=lambda message: print(message, flush=True),
        resume=args.resume,
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
