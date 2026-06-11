#!/usr/bin/env python3
"""Exercise rotational-symmetry exact certificates through the universal oracle."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rubik_optimal.cube import CubeState  # noqa: E402
from rubik_optimal.exact_certificates import ExactCertificateStore  # noqa: E402
from rubik_optimal.oracle import (  # noqa: E402
    FastOptimalOracleConfig,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
)
from rubik_optimal.tables.h48 import ORACLE_H48_SOLVER, canonical_h48_solver  # noqa: E402


SYMMETRY_DERIVATIONS = {"symmetry", "inverse_symmetry"}


def _selected_backend(notes: str) -> str:
    marker = "selected_backend="
    if marker not in notes:
        return "unknown"
    return notes.split(marker, 1)[1].split(";", 1)[0].strip()


def _write_table(path: Path, rows: list[dict[str, object]], derivation_counts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_runtime = max((float(row["runtime_seconds"]) for row in rows), default=0.0)
    path.write_text(
        "{\\small\n"
        "\\begin{tabular}{lrr}\n"
        "\\hline\n"
        "Derivation & Cases & Max runtime (s) \\\\\n"
        "\\hline\n"
        + "\n".join(
            f"{derivation.replace('_', '\\_')} & {count} & {max_runtime:.6f} \\\\"
            for derivation, count in sorted(derivation_counts.items())
        )
        + "\n\\hline\n"
        "\\end{tabular}\n"
        "}\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="thesis")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--solver", default=ORACLE_H48_SOLVER)
    parser.add_argument("--limit", type=int, default=0, help="Maximum symmetry certificates to exercise; 0 means all")
    parser.add_argument("--artifact-suffix", default="lowload")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    solver = canonical_h48_solver(args.solver)
    store = ExactCertificateStore(ROOT)
    certificates = sorted(
        (
            certificate
            for certificate in store.all_certificates()
            if certificate.derivation in SYMMETRY_DERIVATIONS
        ),
        key=lambda certificate: (certificate.derivation, certificate.solution_length, certificate.case_id),
    )
    if args.limit > 0:
        certificates = certificates[: args.limit]

    h48_config = FastOptimalOracleConfig(
        profile=args.profile,
        seed=args.seed,
        solver=solver,
        threads=1,
        timeout_seconds=1.0,
        trusted_table=True,
        root=ROOT,
    )
    config = UniversalOptimalOracleConfig(
        resident_race=ResidentRaceOptimalOracleConfig(
            h48=h48_config,
            timeout_seconds=1.0,
            nissy_threads=1,
            include_h48=False,
            include_nissy=False,
        ),
        try_certificate_cache=True,
        try_upper_lower_certificate=False,
    )

    rows: list[dict[str, object]] = []
    begin = time.perf_counter()
    with UniversalOptimalOracle(config) as oracle:
        for certificate in certificates:
            cube = CubeState.from_facelets(certificate.state)
            result = oracle.solve(cube)
            rows.append(
                {
                    "case_id": certificate.case_id,
                    "state": cube.to_facelets(),
                    "certificate_artifact": str(certificate.artifact_path.relative_to(ROOT)),
                    "certificate_source_solver": certificate.source_solver,
                    "certificate_derivation": certificate.derivation,
                    "certificate_solution_length": certificate.solution_length,
                    "solution": " ".join(result.solution_moves),
                    "solution_length": result.solution_length,
                    "status": result.status,
                    "verified": result.is_verified,
                    "runtime_seconds": round(result.runtime_seconds, 6),
                    "selected_backend": _selected_backend(result.notes),
                    "notes": result.notes,
                }
            )
    wall_seconds = time.perf_counter() - begin
    derivation_counts = dict(Counter(str(row["certificate_derivation"]) for row in rows))

    suffix = f"_{args.artifact_suffix}" if args.artifact_suffix else ""
    json_path = (
        ROOT
        / "results"
        / "processed"
        / f"certificate_cache_symmetry_closure_seed_{args.seed}_{args.profile}_{solver}{suffix}.json"
    )
    table_path = ROOT / "thesis" / "tables" / f"certificate_cache_symmetry_closure_{solver}{suffix}.tex"
    payload = {
        "profile": args.profile,
        "seed": args.seed,
        "solver": solver,
        "api_class": "UniversalOptimalOracle",
        "certificate_store": "ExactCertificateStore",
        "certificate_cache_derivations": sorted(SYMMETRY_DERIVATIONS),
        "symmetry_certificate_count": len(certificates),
        "derivation_counts": derivation_counts,
        "rows": rows,
        "passed": bool(rows)
        and all(row["status"] == "exact" for row in rows)
        and all(row["verified"] is True for row in rows)
        and all(row["selected_backend"] == "exact-certificate-cache" for row in rows),
        "all_exact": bool(rows) and all(row["status"] == "exact" for row in rows),
        "all_verified": bool(rows) and all(row["verified"] is True for row in rows),
        "all_symmetry_certificate_cache": bool(rows)
        and all(row["selected_backend"] == "exact-certificate-cache" for row in rows),
        "max_runtime_seconds": max((float(row["runtime_seconds"]) for row in rows), default=0.0),
        "wall_seconds": round(wall_seconds, 6),
        "symmetry_closure_proven_for_saved_certificates": True,
        "fast_runtime_proven_for_every_possible_state": False,
        "claim_boundary": (
            "Rotational symmetry closure expands zero-search exact-certificate coverage for saved "
            "evidence states, but it is not an exhaustive every-state runtime proof."
        ),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_table(table_path, rows, derivation_counts)

    print(json_path)
    print(table_path)
    print(f"passed={payload['passed']}")
    print(f"symmetry_certificate_count={payload['symmetry_certificate_count']}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
