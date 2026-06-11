# Optimal Solution Algorithms for Rubik's Cube (`rubik-optimal`)

This repository contains the complete implementation, experiment pipeline, evidence artifacts and LaTeX text of a University of Patras ECE diploma thesis:

**Greek title:** Αλγόριθμοι Βέλτιστης Επίλυσης για τον Κύβο του Rubik  
**English title:** Optimal Solution Algorithms for Rubik's Cube  
**Author:** Alexandros Toska — **Supervisor:** Kyriakos Sgarbas, Associate Professor, ECE, University of Patras

The thesis implements the three goals of the official topic assignment: (1) the Thistlethwaite, Kociemba and Korf solving algorithms, running on a conventional computer; (2) exact recognition of how many moves a given state is from solved; (3) an admissible heuristic for provably optimal solving with IDA* (the chosen A* variant), backed by natively generated pattern databases. The full thesis text (Greek) is at `thesis/main.pdf`.

## Installation And Raw-Checkout Usage

For normal local development, create an environment and install the package in
editable mode:

```bash
python -m pip install -e ".[dev]"
python -m rubik_optimal.cli --help
rubik-optimal --help
```

The checkout also includes a small root-package shim so basic package imports and
module-style CLI calls work before an editable install:

```bash
python - <<'PY'
from rubik_optimal import CubeState, FastOptimalOracle, FastOptimalOracleConfig

print(CubeState.solved().to_facelets())
print(FastOptimalOracle.__name__, FastOptimalOracleConfig.__name__)
PY

python -m rubik_optimal.cli --help
```

This repository does not currently declare a single project-wide license in
`pyproject.toml`. See `LICENSE` and `THIRD_PARTY_NOTICES.md` before redistributing
the original thesis code or any third-party/vendored components.

## Overview

The codebase covers all implementation tracks at thesis scope: a 3x3 cubie model, move parser, validity checks, coordinate/table generation, practical 3x3 end-to-end sequence/facelet solving with independent verification, native Kociemba-style and Thistlethwaite-style solvers, Korf/IDA* with generated table-based lower bounds plus native C++ 3x3 corner and edge pattern databases, a compiled full-cube optimal-search path that is exact when it completes, an in-repository vendored H48 exact-search backend/table generator with single-call and batch modes, deterministic thesis benchmarks, generated thesis figures/tables, and a complete normalized 2x2x2 exact case study.

Every number printed in the thesis traces to a stored artifact under `results/`; the verification gates below re-check that property mechanically. The thesis builds to 129 pages with `latexmk` (see PDF convention below).

Licensing and third-party provenance are tracked in:

- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `native/h48_backend/third_party/nissy_core/LICENSE`

## Functionality Present

- 3x3 cubie-level Rubik's Cube model.
- Legal move parser for `U U' U2 D D' D2 L L' L2 R R' R2 F F' F2 B B' B2`.
- Half-turn metric move counting.
- Physical validity and solvability checks.
- Deterministic scramble generator.
- Independent solution verifier.
- Shallow BFS exact search.
- Coordinate move/pruning table generation with metadata and checksums.
- Native Kociemba-style two-phase solver with thesis-corpus benchmark evidence.
- Native Thistlethwaite-style four-phase subgroup-chain solver with bounded,
  verified-on-completion benchmark evidence.
- Scoped Korf-style IDA* exact search with generated projection-table lower bounds, a binary 3x3 corner PDB, eight binary 6-edge PDBs, two binary cost-partitioned 6-edge CPDBs, and a native full-cube optimal solver for completed cases.
- Native H48 backend wrapping vendored GPL nissy-core source, with reproducible h48h0 and oracle-grade h48h7 table generation, checksums, exact/timeout-only reporting, direct-state stress-row evidence, superflip distance-20 certification, a first-class `FastOptimalOracle` API, `rubik-optimal oracle`, batch mode that loads the h48h7 table once for repeated oracle calls, and `rubik-optimal oracle --stream` for a resident line-delimited oracle process.
- `PortfolioOptimalOracle`, which first reuses revalidated exact certificates, can certify verified upper-bound solutions when they match an H48 admissible lower bound, tries the CRC-validated public Nissy optimal table through a batch process under a bounded timeout, can recover a representative scramble for state-input-only Nissy runs when no source sequence is supplied, and falls back to resident H48 for hard direct-state cases.
- Trusted H48 table mode for generated/checksum-verified tables, with mmap loading, optional page preloading for hard states, and saved fair-accounting evidence (shared warm-up, so no arm is charged the one-time cold page-in): 218.855x total speedup for skipping repeated full-table validation, 3.743x batch throughput, and 3.808x for the resident process, while preserving exact/verified rows in the recorded cases.
- End-to-end 3x3 auto solve path for sequence and facelet inputs, with validation and independent verification.
- Optional Kociemba adapter as a comparison baseline.
- Complete normalized 2x2x2 exact case study.
- Distance recognition with `exact_distance`, `lower_bound`, `unknown_timeout`, and `invalid_state` categories.
- Quick and thesis benchmark profiles plus result verification scripts.
- Greek XeLaTeX thesis source and canonical review PDF at `thesis/main.pdf`.

PDF convention: `latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex`
writes the fresh build output as root `main.pdf`. After each build, sync it to
the canonical repository deliverable with `cp main.pdf thesis/main.pdf` and verify
`cmp main.pdf thesis/main.pdf`. `python scripts/thesis_audit.py` now records this
deliverable check and fails if the two PDFs both exist but differ.

## Verification

### Conventional-machine acceptance gate

This is the lightweight gate intended to pass on an ordinary laptop in minutes,
without multi-GiB tables or hour-long table generation. Run this first:

```bash
python -m pytest -q
rubik-optimal --help
python scripts/run_benchmarks.py --profile quick --seed 2026
python scripts/verify_results.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
```

This subset exercises the core test suite, the CLI entry point, a quick
benchmark profile, result verification, and the thesis PDF build. It does not
regenerate the heavy H48/PDB tables; it relies on the committed result evidence
and generated tables already present in the checkout.

### Full regeneration pipeline (multi-hour; requires substantial RAM/disk)

The following block regenerates every table and re-runs every benchmark from
scratch. It takes multiple hours of wall-clock time and needs substantial RAM
and many GiB of free disk (the oracle-grade h48h7 table alone is ~3.6 GiB). Do
not treat this as the conventional-machine acceptance gate; it is the full
reproduction pipeline for a well-resourced machine:

```bash
python -m pytest -q
python -m rubik_optimal.cli --help
python scripts/generate_tables.py --profile thesis --seed 2026
python scripts/generate_corner_pdb.py --profile thesis --seed 2026
python scripts/generate_edge_pdb.py --profile thesis --seed 2026
python scripts/generate_h48_tables.py --profile thesis --seed 2026 --solver h48h0 --threads 8
python scripts/generate_h48_tables.py --profile thesis --seed 2026 --oracle --threads 8
python scripts/run_3x3_end_to_end.py --profile thesis --seed 2026
python scripts/run_3x3_optimal.py --profile thesis --seed 2026
python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 5 --hard-timeout 20 --include-hard --backend h48-native --threads 8 --h48-solver h48h0 --h48-table-profile thesis --artifact-suffix h48h0
python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 10 --hard-timeout 60 --include-hard --backend h48-native --threads 8 --h48-oracle --h48-table-profile thesis --artifact-suffix h48h7_oracle --extra-random-cases 10 --extra-random-depth 25
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --timeout 90 --runtime-target 90 --threads 8
python scripts/benchmark_h48_batch_overhead.py --profile thesis --seed 2026 --solver h48h7 --repetitions 12 --timeout 180 --threads 8
python scripts/run_h48_oracle_cli.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --threads 8
python scripts/benchmark_h48_trusted_table.py --profile thesis --seed 2026 --solver h48h7 --repetitions 4 --timeout 120 --threads 8
python scripts/benchmark_h48_batch_overhead.py --profile thesis --seed 2026 --solver h48h7 --repetitions 12 --timeout 180 --threads 8 --trusted-table --artifact-suffix trusted
python scripts/run_h48_oracle_cli.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --threads 8 --trusted-table --artifact-suffix trusted
python scripts/run_h48_oracle_stream.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --threads 8 --trusted-table --artifact-suffix trusted
python scripts/benchmark_h48_resident_oracle.py --profile thesis --seed 2026 --solver h48h7 --repetitions 8 --timeout 30 --threads 8 --trusted-table
python scripts/run_h48_resident_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 240 --runtime-target 240 --threads 8 --trusted-table
python scripts/run_fast_optimal_oracle_api.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --runtime-target 60 --threads 8 --trusted-table
python scripts/install_nissy_public_table.py --profile thesis --seed 2026 --artifact-suffix installed
python scripts/run_3x3_optimal.py --profile thesis --seed 2026 --timeout 60 --backend nissy-optimal --threads 2 --artifact-suffix nissy_optimal
python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 60 --hard-timeout 120 --include-hard --backend nissy-optimal --threads 2 --artifact-suffix nissy_optimal
python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set thesis --nissy-timeout 45 --nissy-threads 2 --h48-timeout 240 --h48-threads 2 --trusted-table --artifact-suffix nissy_first_lowload
python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set thesis --state-input-only --no-certificate-cache --no-upper-lower-certificate --nissy-timeout 45 --nissy-threads 2 --h48-timeout 240 --h48-threads 2 --h48-solver auto --trusted-table --artifact-suffix nissy_state_recovery_lowload
python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set hard --case-id superflip_distance_20 --nissy-timeout 3 --nissy-threads 2 --h48-timeout 360 --h48-threads 4 --trusted-table --artifact-suffix superflip_fallback_lowload
python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set hard --case-id superflip_distance_20 --nissy-timeout 3 --nissy-threads 2 --h48-timeout 360 --h48-threads 4 --trusted-table --artifact-suffix superflip_certificate_cache_lowload
python scripts/generate_h48_oracle_contract.py --profile thesis --seed 2026 --solver h48h7
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 300 --runtime-target 300 --threads 8 --trusted-table --artifact-suffix trusted_no_preload
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 180 --runtime-target 180 --threads 8 --trusted-table --preload-table --artifact-suffix trusted_preload
python scripts/run_benchmarks.py --profile thesis --seed 2026
python scripts/verify_results.py
python scripts/generate_figures.py --profile thesis --seed 2026
python scripts/apply_final_metadata.py --help
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
cp main.pdf thesis/main.pdf
cmp main.pdf thesis/main.pdf
python scripts/thesis_audit.py
```

The latest observed pass/fail status for these commands is tracked in
`docs/progress.md` and `results/processed/thesis_audit.json`. `python
scripts/thesis_audit.py` deliberately reports `final_submission_ready: false`
until the front-matter placeholders are replaced and final approval evidence is
recorded, or explicitly accepted by the supervisor/Secretariat.

The saved H48 evidence above was generated with explicit thread counts recorded in each artifact. On a heavily loaded laptop, use lower thread counts such as `--threads 2` or `--threads 4` for new exploratory runs; the package-level `FastOptimalOracle` also honors `RUBIK_OPTIMAL_H48_THREADS=auto` or `RUBIK_OPTIMAL_THREADS=auto` for load-aware sizing. Lowering threads reduces machine pressure but may increase hard-case runtimes, so any new timing claim must come from the saved artifact for that run.

## Evidence Paths

- Raw thesis benchmark rows: `results/raw/benchmarks_seed_2026_thesis.jsonl`
- Processed thesis benchmark summary: `results/processed/summary_seed_2026_thesis.json`
- Table metadata: `results/processed/table_metadata_thesis_seed_2026.json`
- Native corner PDB binary: `data/generated/thesis_seed_2026_corner_state_pdb.bin`
- Native corner PDB metadata: `results/processed/corner_pdb_metadata_seed_2026_thesis.json`
- Native edge PDB metadata: `results/processed/edge_pdb_metadata_seed_2026_thesis.json`
- Native edge CPDB metadata: `results/processed/edge_cpdb_metadata_seed_2026_thesis.json`
- Native edge CPDB coverage: `results/processed/edge_pdb_coverage_seed_2026_thesis_cpdb_additive.json`
- Native H48 tables: `data/generated/h48/thesis_seed_2026/h48h0.bin`, `data/generated/h48/thesis_seed_2026/h48h7.bin`
- Native H48 metadata: `results/processed/h48_metadata_seed_2026_thesis_h48h0.json`, `results/processed/h48_metadata_seed_2026_thesis_h48h7.json`
- Native/H48-backed optimal 3x3 evidence: `results/processed/optimal_3x3_seed_2026_thesis.json`
- Native-certified stress evidence with Nissy-derived heuristic/candidate support: `results/processed/optimal_3x3_seed_2026_stress.json`
- Native H48 stress evidence: `results/processed/optimal_3x3_seed_2026_stress_h48h0.json`, `results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json`
- Native H48 oracle certification: `results/processed/h48_oracle_certification_seed_2026_thesis.json`
- Native H48 batch-overhead evidence: `results/processed/h48_batch_overhead_seed_2026_thesis.json`
- Native H48 oracle CLI evidence: `results/processed/h48_oracle_cli_seed_2026_thesis.json`
- Native H48 trusted-table speed evidence: `results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json`
- Native H48 trusted batch evidence: `results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json`
- Native H48 trusted CLI evidence: `results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json`
- Native H48 streaming CLI evidence: `results/processed/h48_oracle_stream_seed_2026_thesis_trusted.json`
- Native H48 resident-oracle speed evidence: `results/processed/h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json`
- Native H48 resident hard certification: `results/processed/h48_resident_certification_seed_2026_thesis_h48h7_trusted.json`
- Native H48 package API evidence: `results/processed/fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json`
- Native H48 oracle contract audit: `results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json`
- External Nissy optimal table install evidence: `results/processed/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.json`
- External Nissy optimal thesis/stress evidence: `results/processed/optimal_3x3_seed_2026_thesis_nissy_optimal.json`, `results/processed/optimal_3x3_seed_2026_stress_nissy_optimal.json`
- Portfolio oracle evidence: `results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json`, `results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_state_recovery_lowload.json`, `results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json`, `results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json`
- Native H48 trusted/no-preload hard certification: `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json`
- Native H48 trusted/preloaded hard certification: `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json`
- 3x3 end-to-end evidence: `results/processed/e2e_3x3_seed_2026_thesis.json`
- Pocket Cube summary: `results/processed/pocket_cube_summary_seed_2026_thesis.json`
- Thesis audit: `results/processed/thesis_audit.json`
- Generated thesis tables: `thesis/tables/`
- Generated thesis figure data: `thesis/figures/`
- Thesis source: `thesis/main.tex`
- Thesis PDF: `thesis/main.pdf`
- Bibliography: `thesis/references.bib`

## Claim Boundaries

This repository now contains an oracle-grade h48h7 H48 table and direct facelet/cubie state input for the H48 backend. It cites God's Number as an external result and does not reproduce that proof. Native Kociemba and native Thistlethwaite are scoped, non-exact practical solvers; saved benchmark artifacts are the source of truth for their current row counts, statuses, phase lengths, and runtimes, and bounded rows that time out or return lower bounds must not be described as solved. The Korf/IDA* track uses a complete 88,179,840-state 3x3 corner PDB plus eight complete 42,577,920-state edge PDBs; the expanded edge-PDB coverage artifact compares the old four-subset baseline with the eight-subset set over 80 deterministic samples and records 14 stronger lower bounds with no weaker rows. Native optimal, H48, Nissy, RubikOptimal, portfolio, resident, streaming, and certificate-cache evidence is recorded in the saved artifacts listed above. H48/Nissy/RubikOptimal material is public-solver-derived or vendored/external backend evidence, not original student algorithmic authorship and not a substitute for the native Korf/IDA* heuristic contribution. Exact claims remain limited to rows where the selected backend completed and the returned solution verifies; no blanket worst-case practical-runtime claim is made for every possible 3x3 state, and the oracle contract artifact records this boundary explicitly.
