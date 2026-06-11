"""JSON-line worker for resident nissy-core Python solves."""

from __future__ import annotations

import argparse
import json
import mmap
import sys
import time
from pathlib import Path


def _load_nissy(module_root: Path):
    sys.path.insert(0, str(module_root))
    sys.path.insert(0, str(module_root / "python"))
    import nissy  # type: ignore[import-not-found]

    return nissy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module-root", required=True)
    parser.add_argument("--table-path", required=True)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--max-depth", type=int, default=20)
    args = parser.parse_args(argv)

    try:
        module_root = Path(args.module_root)
        table_path = Path(args.table_path)
        nissy = _load_nissy(module_root)
        table_file = table_path.open("rb")
        table_mmap = mmap.mmap(table_file.fileno(), 0, access=mmap.ACCESS_READ)
        solve_buffer_available = hasattr(nissy, "solve_buffer")
        table_data = table_mmap if solve_buffer_available else bytearray(table_mmap)
        solve_fn = nissy.solve_buffer if solve_buffer_available else nissy.solve
        print(
            json.dumps(
                {
                    "event": "ready",
                    "solver": args.solver,
                    "table_path": str(table_path),
                    "table_bytes": table_path.stat().st_size,
                    "table_data_mode": "mmap" if solve_buffer_available else "bytearray",
                    "solve_buffer_available": solve_buffer_available,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"event": "startup_failed", "error": str(exc)},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 2

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        begin = time.perf_counter()
        try:
            request = json.loads(line)
            request_id = request.get("id")
            cube = request["cube"]
            solutions = solve_fn(
                cube,
                args.solver,
                nissy.nissflag_normal,
                0,
                args.max_depth,
                1,
                0,
                max(1, args.threads),
                table_data,
            )
            response = {
                "id": request_id,
                "status": "ok",
                "solutions": solutions,
                "runtime_seconds": time.perf_counter() - begin,
            }
        except Exception as exc:
            response = {
                "id": request.get("id") if "request" in locals() else None,
                "status": "error",
                "error": str(exc),
                "runtime_seconds": time.perf_counter() - begin,
            }
        print(json.dumps(response, separators=(",", ":")), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
