# Reproducibility Guide

## Status

This guide documents the current delivered-scale thesis draft. The repository, implementation, scale, research, benchmark, citation, and XeLaTeX gates pass locally, but final submission readiness is still blocked by unresolved front-matter metadata and supervisor/Secretariat approval evidence. Source-state provenance must be checked with `python scripts/source_state_report.py` and `python scripts/thesis_audit.py` after any final artifact regeneration. The retained H48 `h48h7` table is handled through explicit adoption metadata: the canonical table bytes are validated, re-checksummed, and stamped from a clean committed checkout without claiming byte-for-byte table regeneration. See `docs/final_metadata_packet.md`, `docs/final_metadata_values.template.json`, `docs/supervisor_handoff_request.md`, `docs/final_supervisor_approval.template.md`, `docs/source_state_reproducibility.md`, and `docs/repository_hygiene_runbook.md`.

## Environment Observed During Prototype Build

```text
Python: 3.12.2
pytest: 9.0.3
c++: Apple clang 17.0.0 observed for native corner/edge-PDB generation and native optimal search
Nissy: 2.0.8 was locally built under ignored `.codex_external/` for optional external optimal-reference stress evidence
Nissy-core H48: vendored GPL-3.0-or-later snapshot under `native/h48_backend/third_party/nissy_core/`
tectonic: 0.15.0Tectonic 0.15.0
latexmk: 4.87
xelatex: XeTeX 3.141592653-2.6-0.999998 (TeX Live 2026/Homebrew)
bibtex: 0.99e (TeX Live 2026/Homebrew)
```

The final Python checks, benchmark scripts, audit script, and `latexmk -xelatex` command run in the current environment.

## Installation

The canonical package lives in `src/rubik_optimal` (a `src/` layout). The single
source of truth is that tree; install it editable **from this repository root**:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

After this, `import rubik_optimal`, the `rubik-optimal` console script, and
`python -m rubik_optimal.cli` all resolve to `src/rubik_optimal`.

Without installing, run anything against the canonical tree by putting `src` on
the path:

```bash
PYTHONPATH=src python3 -m rubik_optimal.cli --help
PYTHONPATH=src python3 scripts/run_benchmarks.py --quick --seed 2026
```

The repository root also keeps a thin import shim, `rubik_optimal/__init__.py`,
so a *fresh checkout* run from the repo root (no install, no `PYTHONPATH=src`)
can still `import rubik_optimal` and `python -m rubik_optimal.cli`. The shim only
appends `src/rubik_optimal` to its own `__path__` and re-exports the canonical
public API dynamically; it keeps **no** hand-maintained symbol list, so it can
no longer drift out of date with `src`. Prefer the editable install or
`PYTHONPATH=src`; the shim is a convenience, not the supported entry point.

### Optional dependencies

The default install pulls **no** third-party solver. The student's own
algorithms (Thistlethwaite, Kociemba two-phase, Korf IDA*) and the native C++
optimal engine all work with zero runtime dependencies.

The pip `kociemba` package (GPLv2; see `THIRD_PARTY_NOTICES.md`) is used only by
`solve_kociemba_adapter` as a *non-exact* cross-check baseline, and the adapter
returns a `not_applicable` row when the package is absent. To opt in to that
baseline, install the extra:

```bash
python -m pip install -e ".[baselines]"   # adds kociemba>=1.2 (GPLv2)
```

### Known stale editable-install footgun

A previous editable install on this machine registered the project under the
name `rubik_cube_thesis` (not `rubik-optimal`) with its source mapping pointing
at a **different** checkout, `/Users/alextoska/Desktop/rubicCubeThesis/src`, via
`site-packages/__editable__.rubik_cube_thesis-0.1.0.pth` and the matching
`__editable___rubik_cube_thesis_0_1_0_finder.py`. That mapping exposes a bare
top-level `src` module from the other repo; it does **not** shadow
`rubik_optimal`, but it is misleading provenance. `pip show rubik-optimal`
returns nothing because the package name in this repo's `pyproject.toml` is
`rubik-optimal` and was never installed from here.

To clean it up (run in the environment you use for this repo; this does not
touch the other repository's working tree):

```bash
python -m pip uninstall -y rubik-cube-thesis   # removes the stale .pth/finder
python -m pip install -e ".[dev]"              # install THIS repo correctly
pip show rubik-optimal                          # should now report this checkout
```

## Quick Verification Commands

This is the **conventional-machine quick gate**: it runs in minutes on a normal
laptop, needs no multi-GiB tables, and is the recommended first check after a
fresh clone. The "Final Verification Commands" block below is the full
regeneration pipeline (multi-hour, heavy RAM/disk) and is **not** required on a
conventional machine.

```bash
python -m pytest -q
python -m rubik_optimal.cli --help
python scripts/run_benchmarks.py --quick --seed 2026
python scripts/verify_results.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
```

If you have not installed the package, prefix the Python commands with
`PYTHONPATH=src` (for example `PYTHONPATH=src python3 -m rubik_optimal.cli --help`).

These are useful for a faster sanity check. They are not sufficient for final delivered-thesis acceptance.

## Student-Algorithm Tables and Caches

The student's own solvers are backed by deterministic, checksummed tables under
`data/generated/`. They are committed/regenerable evidence, not opaque blobs.

### Thistlethwaite per-phase coset tables

The rewritten Thistlethwaite solver uses BFS-generated per-phase coset distance
tables (module `src/rubik_optimal/tables/thistlethwaite_tables.py`). Generate or
regenerate them with:

```bash
PYTHONPATH=src python3 scripts/generate_thistlethwaite_tables.py
```

This writes four raw little-endian uint8 binaries plus a checksummed manifest
under `data/generated/thistlethwaite/`:

```text
data/generated/thistlethwaite/thistlethwaite_g0_eo.bin            # G0->G1 edge orientation,        max distance 7
data/generated/thistlethwaite/thistlethwaite_g1_co_udslice.bin    # G1->G2 corner orientation x UD-slice, max distance 10
data/generated/thistlethwaite/thistlethwaite_g2_coset.bin         # G2->G3 corner/edge left-coset,   max distance 13
data/generated/thistlethwaite/thistlethwaite_g3_square.bin        # G3->G4 square group,             max distance 15
data/generated/thistlethwaite/thistlethwaite_manifest.json
```

Generation is deterministic (re-running yields byte-identical files and
checksums; observed ~19 s total in this environment). The reported per-phase
maximum distances 7 / 10 / 13 / 15 are the published Thistlethwaite phase
bounds, which independently confirms the coset spaces are correct.

### Kociemba coordinate move/pruning cache

The native scoped Kociemba solver (`src/rubik_optimal/solvers/kociemba.py`)
persists its coordinate move and pruning tables to a deterministic on-disk
cache under `data/generated/` (`kociemba_coordinate_cache_manifest.json` plus the
per-table JSON files), so the tables are built once and subsequent processes
load them from disk instead of recomputing them every run. The cache is
schema-validated on load and silently rebuilt if the manifest signature does not
match. Set `RUBIK_OPTIMAL_DATA_DIR` (or `RUBIK_GENERATED_DATA_DIR`) to redirect
the cache location, e.g. for tests; the cache profile/seed default to
`thesis` / `2026`.

## Final Verification Commands (Full Regeneration)

This is the **full regeneration pipeline**: multi-hour, heavy RAM/disk, and it
materialises multi-GiB tables (corner/edge PDBs, the ~3.5 GiB H48 table, the
public Nissy optimal table, etc.). It is **not** the conventional-machine gate —
use the "Quick Verification Commands" above for a normal laptop. Run the block
below only on a machine provisioned for the heavy artifacts and only when
regenerating final thesis evidence:

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
python scripts/generate_h48_oracle_contract.py --profile thesis --seed 2026 --solver h48h7
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 300 --runtime-target 300 --threads 8 --trusted-table --artifact-suffix trusted_no_preload
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 180 --runtime-target 180 --threads 8 --trusted-table --preload-table --artifact-suffix trusted_preload
python scripts/run_benchmarks.py --profile thesis --seed 2026
python scripts/verify_results.py
python scripts/generate_figures.py --profile thesis --seed 2026
python scripts/apply_final_metadata.py --help
python scripts/source_state_report.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
cp main.pdf thesis/main.pdf
cmp main.pdf thesis/main.pdf
python scripts/thesis_audit.py
```

These commands currently pass in this checkout. The audit command still reports `final_submission_ready: false` because front-matter metadata and final approval evidence are pending.

If the thesis benchmark run is interrupted, restart it with:

```bash
python scripts/run_benchmarks.py --profile thesis --seed 2026 --resume
```

The resume mode validates the existing raw JSONL seed/profile, skips completed `(case_id, solver)` rows, and appends the missing rows before the normal verifier/figure-generation steps.

## Source-State Gate

Generated result metadata keeps a compact `source_state` label and new metadata producers also write `source_state_details`, `source_snapshot_reproducible`, `source_snapshot_limitation`, and `source_reproduction_plan`. Final metadata must come from a clean committed checkout or an approved immutable source archive. The retained H48 `h48h7` table is the special case: its bytes are adopted only through `--adopt-existing-table-metadata`, which validates the existing table, recomputes its checksum, and records the clean source state of the adoption operation while preserving previous provenance in `adoption_previous_*` fields.

The safe path is:

```bash
git status --short
# after reviewing the intended baseline, create a clean commit or an approved immutable source archive
python scripts/generate_h48_tables.py --profile thesis --seed 2026 --oracle --threads 8 --adopt-existing-table-metadata
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --timeout 90 --runtime-target 90 --threads 8
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 300 --runtime-target 300 --threads 8 --trusted-table --artifact-suffix trusted_no_preload
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 180 --runtime-target 180 --threads 8 --trusted-table --preload-table --artifact-suffix trusted_preload
python scripts/source_state_report.py
python scripts/thesis_audit.py
```

The audit scans generated JSON metadata for non-reproducible source states and adds `source_snapshot_reproducibility` to `submission_blockers` until all final artifact metadata comes from a clean committed checkout or approved archive.

The current shared checkout also has a repository-hygiene blocker: `.git` is
large because of garbage pack files, while `data` and `results` contain
multi-GiB generated thesis artifacts. Do not delete or prune these directories
in-place. Follow `docs/repository_hygiene_runbook.md` to create a clean baseline
and decide which binary artifacts are tracked, force-added, archived externally,
or regenerated.

The recorded thesis H48 timings use `--threads 8`. When the Mac is under heavy interactive load, use lower exploratory settings such as `--threads 2` or `--threads 4`; the `FastOptimalOracle` API reads `RUBIK_OPTIMAL_H48_THREADS` first and `RUBIK_OPTIMAL_THREADS` second when a thread count is not passed explicitly. Reduced-thread runs are valid new artifacts if saved, but they must not be mixed with the existing 8-thread timing claims.

Optional H48 table regeneration with overwrite:

```bash
python scripts/generate_h48_tables.py --profile thesis --seed 2026 --solver h48h0 --threads 8 --force
python scripts/generate_h48_tables.py --profile thesis --seed 2026 --oracle --threads 8 --force
```

The H48 table generator writes `data/generated/h48/thesis_seed_2026/h48h0.bin` and `data/generated/h48/thesis_seed_2026/h48h7.bin`, records matching metadata JSON files, and refreshes `thesis/tables/h48_metadata.tex`.

The H48 oracle certification script writes `results/processed/h48_oracle_certification_seed_2026_thesis.json` and `thesis/tables/h48_oracle_certification.tex`. It includes direct CubeState rows for solved, shallow, deterministic depth-25, and the standard superflip distance-20 state. The batch-overhead benchmark writes `results/processed/h48_batch_overhead_seed_2026_thesis.json` and `thesis/tables/h48_batch_overhead.tex`; it measures repeated h48h7 exact solves as separate processes versus one native batch process that loads/checks the 3.5 GiB table once. The oracle CLI script writes `results/processed/h48_oracle_cli_seed_2026_thesis.json` and `thesis/tables/h48_oracle_cli.tex`; it verifies the public `rubik-optimal oracle` command on line-delimited solved, sequence, and facelet inputs. The streaming CLI script writes `results/processed/h48_oracle_stream_seed_2026_thesis_trusted.json` and `thesis/tables/h48_oracle_stream_trusted.tex`; it verifies `rubik-optimal oracle --stream`, which keeps one resident H48 backend alive and emits JSONL rows. The resident benchmark writes `results/processed/h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json` and `thesis/tables/h48_resident_oracle_h48h7_trusted.tex`. The resident hard-certification script writes `results/processed/h48_resident_certification_seed_2026_thesis_h48h7_trusted.json` and `thesis/tables/h48_resident_certification_h48h7_trusted.tex`; it keeps one native process/table mapping alive for the solved, shallow, deterministic depth-25, and superflip rows. The package API script writes `results/processed/fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json` and `thesis/tables/fast_optimal_oracle_api_h48h7_trusted.tex`; it exercises `FastOptimalOracle` directly and records 4/4 exact verified rows with max runtime 2.664585s in the saved artifact. `scripts/install_nissy_public_table.py` writes `results/processed/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.json`, installs only `tables/pt_nxopt31_HTM` from the public Nissy archive, and validates the 2,465,897,307-byte extracted table against CRC `8c7e4d23`. The `nissy-optimal` runs write `results/processed/optimal_3x3_seed_2026_thesis_nissy_optimal.json` and `results/processed/optimal_3x3_seed_2026_stress_nissy_optimal.json`; the stress artifact is exact/verified on 5/5 rows, with `random_3_20` at distance 17 in 23.734412s on 2 threads. The oracle-contract script writes `results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json` and `thesis/tables/h48_oracle_contract_h48h7.tex`; it checks local nissy-core docs/API text, backend call shape, the first-class `FastOptimalOracle` API, table metadata, independent verification, the installed public Nissy optimal table, and saved empirical evidence. The trusted-table scripts write `results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json`, `results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json`, `results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json`, `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json`, and `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json`. These artifacts measure the optimized path that skips per-call full-table distribution scans only after using generated/checksum-verified tables. The trusted/no-preload hard certification is exact with max runtime 91.629342s; the resident hard certification is exact with max runtime 77.822389s and resident wall time 154.755697s; the external Nissy optimal superflip probe timed out at 120s on 2 threads and 240s on 8 threads under heavy Mac load; the contract artifact records `fast_optimal_oracle_implemented_for_every_valid_3x3_state: true`, `all_state_exact_contract_supported: true`, `empirical_fast_corpus_supported: true`, and `fast_runtime_proven_for_every_possible_state: false`. They still do not prove a 10x speedup for every hard single-state search.

The portfolio oracle script writes `results/processed/portfolio_optimal_oracle_seed_2026_thesis_nissy_first_lowload.json` plus `thesis/tables/portfolio_optimal_oracle_nissy_first_lowload.tex` for the Nissy-first corpus, `results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_fallback_lowload.json` plus `thesis/tables/portfolio_optimal_oracle_superflip_fallback_lowload.tex` for the targeted hard fallback, and `results/processed/portfolio_optimal_oracle_seed_2026_thesis_superflip_certificate_cache_lowload.json` plus `thesis/tables/portfolio_optimal_oracle_superflip_certificate_cache_lowload.tex` for the revalidated certificate-cache repeat. The saved low-priority runs use a single Nissy optimal batch process with 2 threads, 4 H48 fallback threads for the original superflip proof, and record 5/5 exact Nissy-first rows with max batch runtime 10.097333s, superflip exact at distance 20 in 135.679618s, and repeat superflip exact via certificate cache in 0.012885s.

Optional native-certified stress run, after building Nissy and making its tables available:

```bash
python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 20 --hard-timeout 240 --include-hard --backend native --threads 8 --split-depth 3 --nissy-heuristic --nissy-certificate
```

This produces `results/processed/optimal_3x3_seed_2026_stress.json`. It is exact stress-row evidence when the native lower-bound certificate reaches the verified Nissy-light candidate length. The Nissy-derived DR/UD table and candidate source must be labelled explicitly.

Optional native stress probe without the Nissy-derived certificate path:

```bash
python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 20 --hard-timeout 180 --include-hard --backend native --threads 8 --split-depth 4
```

This preserves the older native timeout behavior as data. The optimized native path still must only be reported as exact on rows where it completes or where a verified upper bound matches the native lower-bound proof.

## Randomness and Seeds

All benchmark scrambles must be deterministic. The required thesis seed starts with:

```text
seed = 2026
```

## Result Provenance

Current thesis raw benchmark results:

```text
results/raw/benchmarks_seed_2026_thesis.jsonl
```

Current thesis processed summaries:

```text
results/processed/summary_seed_2026_thesis.json
results/processed/benchmarks_seed_2026_thesis.csv
results/processed/table_metadata_thesis_seed_2026.json
data/generated/thesis_seed_2026_corner_state_pdb.bin
results/processed/corner_pdb_metadata_seed_2026_thesis.json
results/processed/edge_pdb_metadata_seed_2026_thesis.json
data/generated/h48/thesis_seed_2026/h48h0.bin
data/generated/h48/thesis_seed_2026/h48h7.bin
results/processed/h48_metadata_seed_2026_thesis_h48h0.json
results/processed/h48_metadata_seed_2026_thesis_h48h7.json
results/processed/optimal_3x3_seed_2026_thesis.json
results/processed/optimal_3x3_seed_2026_stress.json
results/processed/optimal_3x3_seed_2026_stress_h48h0.json
results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json
results/processed/h48_oracle_certification_seed_2026_thesis.json
results/processed/h48_batch_overhead_seed_2026_thesis.json
results/processed/h48_oracle_cli_seed_2026_thesis.json
results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json
results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json
results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json
results/processed/h48_oracle_stream_seed_2026_thesis_trusted.json
results/processed/h48_resident_oracle_seed_2026_thesis_h48h7_trusted.json
results/processed/h48_resident_certification_seed_2026_thesis_h48h7_trusted.json
results/processed/fast_optimal_oracle_api_seed_2026_thesis_h48h7_trusted.json
results/processed/h48_oracle_contract_seed_2026_thesis_h48h7.json
results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json
results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json
results/processed/e2e_3x3_seed_2026_thesis.json
results/processed/pocket_cube_summary_seed_2026_thesis.json
results/processed/thesis_audit.json
```

Generated thesis artifacts:

```text
thesis/tables/benchmark_summary.tex
thesis/tables/algorithm_status.tex
thesis/figures/runtime_depth_data.tex
```

Final thesis artifacts are generated from the thesis profile and checked for staleness by `python scripts/thesis_audit.py`.
The canonical review PDF is `thesis/main.pdf`; because the existing latexmk command
writes root `main.pdf`, every thesis rebuild must copy `main.pdf` to `thesis/main.pdf`
and verify `cmp main.pdf thesis/main.pdf` before the audit. The audit records the
root/canonical PDF hashes and exits nonzero if both files exist but differ.

## Final Metadata Gate

After final student/committee/exam metadata and AI/style approvals are supplied, fill a copy of `docs/final_metadata_values.template.json`, use `scripts/apply_final_metadata.py` to apply it, and create `docs/final_supervisor_approval.md` from `docs/final_supervisor_approval.template.md` with the real approval source/date and approved decisions, then run:

```bash
python scripts/apply_final_metadata.py <approved-values.json> --dry-run
python scripts/apply_final_metadata.py <approved-values.json>
python scripts/source_state_report.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
cp main.pdf thesis/main.pdf
cmp main.pdf thesis/main.pdf
python scripts/thesis_audit.py
```

The target final-submission audit state is:

```text
front_matter_placeholders: []
supervisor_approval.passed: true
submission_blockers: []
final_submission_ready: true
```

If those fields are not empty/true, do not claim final submission readiness.

## Solver Output Policy

Every solver row records:

- solver name;
- input scramble/state;
- solution sequence and HTM length;
- runtime;
- expanded/generated nodes where available;
- table size where available;
- status label;
- independent verification result.

The status labels are intentionally strict:

- `exact`: the search completed and proves optimality for that case;
- `non_exact`: the solution verifies but no global optimality proof is claimed;
- `lower_bound`: only an admissible lower bound is known;
- `timeout`: exact search did not complete inside configured limits;
- `not_applicable`: the solver is outside the implemented scope for that case;
- `failed`: the solver failed or returned an invalid result.
