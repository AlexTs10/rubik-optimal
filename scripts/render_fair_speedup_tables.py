"""Render the fair-accounting h48 speedup tables from the *_fair.json artifacts.

Reads only existing processed artifacts (no benchmarks are run) and writes
presentation tables under thesis/tables/. Values are copied verbatim from the
artifacts so the thesis text and tables stay traceable to
results/processed/*_fair.json.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "results" / "processed"
TABLES = ROOT / "thesis" / "tables"


def _load(name: str) -> dict:
    with open(PROCESSED / name, encoding="utf-8") as handle:
        return json.load(handle)


def _write(name: str, body: str) -> None:
    path = TABLES / name
    path.write_text(body, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    trusted = _load("h48_trusted_table_speedup_seed_2026_thesis_h48h7_fair.json")
    batch = _load("h48_batch_overhead_seed_2026_thesis_trusted_fair.json")
    resident = _load("h48_resident_oracle_seed_2026_thesis_h48h7_trusted_fair.json")

    _write(
        "h48_trusted_table_speedup_fair.tex",
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Mode & Total (s) & Steady-state (s) & Exact \\\\\n"
        "\\hline\n"
        f"Verified each call & {trusted['checked_total_seconds']} & {trusted['checked_steady_state_seconds']} & {trusted['checked_exact_count']} \\\\\n"
        f"Trusted generated table & {trusted['trusted_total_seconds']} & {trusted['trusted_steady_state_seconds']} & {trusted['trusted_exact_count']} \\\\\n"
        f"Speedup & {trusted['trusted_speedup']}x & {trusted['trusted_speedup_steady_state']}x & -- \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
    )

    _write(
        "h48_batch_overhead_trusted_fair.tex",
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Mode & Total (s) & Steady-state (s) & Exact \\\\\n"
        "\\hline\n"
        f"Single process per solve & {batch['sequential_total_seconds']} & {batch['sequential_steady_state_seconds']} & {batch['sequential_exact_count']} \\\\\n"
        f"Batch, table loaded once & {batch['batch_wall_seconds']} & -- & {batch['batch_exact_count']} \\\\\n"
        f"Throughput speedup & {batch['throughput_speedup']}x & {batch['throughput_speedup_steady_state']}x & -- \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
    )

    _write(
        "h48_resident_oracle_h48h7_trusted_fair.tex",
        "{\\small\n"
        "\\begin{tabular}{lrrr}\n"
        "\\hline\n"
        "Mode & Total (s) & Steady-state (s) & Exact \\\\\n"
        "\\hline\n"
        f"Separate native process & {resident['separate_total_seconds']} & {resident['separate_steady_state_seconds']} & {resident['separate_exact_count']} \\\\\n"
        f"Resident native process & {resident['resident_total_seconds']} & {resident['resident_steady_state_seconds']} & {resident['resident_exact_count']} \\\\\n"
        f"Speedup & {resident['resident_speedup']}x & {resident['resident_speedup_steady_state']}x & -- \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n"
        "}\n",
    )


if __name__ == "__main__":
    main()
