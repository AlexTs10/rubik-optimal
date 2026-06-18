# Completion Audit Matrix

Audit date: 2026-05-27 07:46 EEST

This file maps the active objective, `docs/goal.md`, and `docs/acceptance.md`
to concrete repository evidence. It is intentionally stricter than a simple
"tests pass" statement: green commands are treated as evidence only where the
repository artifact they validate covers the requirement.

## Decision

The repository is **not complete** as a final submission package.

The current checkout satisfies the repository, implementation, research,
generated-artifact, page/word/table, benchmark, citation, XeLaTeX/PDF identity,
source-state, and handoff-document checks that can be verified locally. The
final readiness gate is still false because external institutional metadata plus
approval are missing:
`results/processed/thesis_audit.json` reports `acceptance_scale_passed: false`,
`final_submission_ready: false`, `handoff_documents.passed: true`, and missing
final approval evidence under `supervisor_approval_evidence`.

Do not mark the goal complete until those metadata values are supplied and
verified, or until the supervisor/Secretariat explicitly accepts the remaining
placeholders as submission-ready.

Cloud/AWS/H48H10/H48H11 proof-host material is not part of the completion decision. The audit now exposes
it under `cloud_scope_drift` as `classification=archived_stretch_or_negative_evidence` with
`completion_gate=false`; any matching runbooks, dry-runs, status artifacts, or negative capacity probes are
kept for traceability but do not satisfy or block the topic brief's three required bullets.

## Evidence Snapshot

| Evidence item | Current value |
|---|---|
| Thesis PDF | `thesis/main.pdf` |
| Page count | 114 |
| PDF words | 32,742 |
| Source words | 27,490 |
| Figure/table files | 274 |
| Required generated artifacts | 178 required, none missing/stale/empty |
| Repository gate | `acceptance_repository_passed: true` |
| Implementation gate | `acceptance_implementation_passed: true` |
| Scale gate | Source-state artifact entries are reproducible after H48 metadata adoption; final result still blocked by front-matter/approval |
| Research gate | `acceptance_research_passed: true` |
| Handoff-document gate | `handoff_documents.passed: true` |
| Supervisor approval evidence | `supervisor_approval.passed: false` |
| Final readiness | `final_submission_ready: false` |
| Submission blockers | `front_matter_metadata_placeholders`; `supervisor_approval_evidence` |
| Cloud/H48H10 scope drift | `cloud_scope_drift.classification: archived_stretch_or_negative_evidence`; `completion_gate: false` |

## Required Read-First Sources

| Requirement | Evidence inspected | Status |
|---|---|---|
| Read `AGENTS.md` | File read during this audit pass | Pass |
| Read `docs/goal.md` | File read during this audit pass | Pass |
| Read `docs/acceptance.md` | File read during this audit pass | Pass |
| Read `docs/reference_thesis_calibration.md` | File read during this audit pass | Pass |
| Read `docs/roadmap_to_delivered_thesis.md` | File read during this audit pass | Pass |
| Read `docs/requirements_from_brief.md` | File read during this audit pass | Pass |
| Read `specs/topic_brief.pdf` if accessible | `pdftotext specs/topic_brief.pdf -` succeeded | Pass |

## Objective Deliverables

| Deliverable | Evidence | Status |
|---|---|---|
| Source code for Rubik algorithms | `src/rubik_optimal/` contains cube, moves, validity, coordinates, tables, search, solvers, Pocket Cube, CLI, verifier, and result modules | Pass |
| Reproducible table, experiment, and figure scripts | `scripts/generate_tables.py`, `scripts/generate_corner_pdb.py`, `scripts/generate_edge_pdb.py`, `scripts/generate_h48_tables.py`, `scripts/inspect_h48_capacity.py`, `scripts/run_h48_oracle_certification.py`, `scripts/benchmark_h48_batch_overhead.py`, `scripts/benchmark_h48_trusted_table.py`, `scripts/run_h48_oracle_cli.py`, `scripts/run_portfolio_optimal_oracle.py`, `scripts/run_race_optimal_oracle.py`, `scripts/run_resident_race_optimal_oracle.py`, `scripts/run_universal_optimal_oracle.py`, `scripts/run_universal_batch_oracle_corpus.py`, `scripts/run_universal_symmetry_oracle.py`, `scripts/run_certificate_cache_inverse_closure.py`, `scripts/run_certificate_cache_symmetry_closure.py`, `scripts/run_benchmarks.py`, `scripts/run_3x3_end_to_end.py`, `scripts/run_3x3_optimal.py`, `scripts/verify_results.py`, `scripts/generate_figures.py`, `scripts/generate_pocket_cube.py` | Pass |
| Verified bibliography and research notes | `results/processed/thesis_audit.json`: 29 BibTeX entries, 29 cited keys, 29 research-note keys, no missing or uncited keys | Pass with final style-review caveat |
| Full Greek LaTeX thesis ready for supervisor review | `latexmk` builds `thesis/main.pdf`; 114 pages and delivered-scale word count | Pass for review draft; blocked for final submission metadata |
| Documentation explaining limitations/setup/reproducibility/metadata | `README.md`, `REPRODUCIBILITY.md`, `docs/limitations.md`, `docs/final_metadata_packet.md`, `docs/final_metadata_values.template.json`, `docs/supervisor_handoff_request.md`, `docs/final_supervisor_approval.template.md`, `docs/completion_audit_matrix.md`, `docs/final_audit.md`, `docs/supervisor_questions.md`; audit reports `handoff_documents.passed: true` and `supervisor_approval.passed: false` until real approval is recorded | Pass for handoff; approval blocked |

## Repository Completeness

| Named path from `docs/acceptance.md` | Evidence | Status |
|---|---|---|
| `pyproject.toml` | Present | Pass |
| `README.md` | Present | Pass |
| `REPRODUCIBILITY.md` | Present | Pass |
| `AGENTS.md` | Present | Pass |
| `docs/` | Present | Pass |
| `specs/topic_brief.pdf` | Present and text-extractable | Pass |
| `src/rubik_optimal/` | Present | Pass |
| `tests/` | Present | Pass |
| `scripts/` | Present | Pass |
| `data/generated/` | Present with thesis-profile table artifacts | Pass |
| `results/raw/` | Present with thesis raw benchmark and Pocket Cube artifacts | Pass |
| `results/processed/` | Present with summaries, table metadata, and audit JSON | Pass |
| `thesis/main.tex` | Present | Pass |
| `thesis/references.bib` | Present | Pass |
| `thesis/chapters/` | Present with front matter, body chapters, and appendices | Pass |
| `thesis/figures/` | Present with generated figure data | Pass |
| `thesis/tables/` | Present with generated LaTeX tables | Pass |

The audit script independently reports 17 required repository paths checked and
0 missing paths.

## Delivered-Scale Thesis Checks

| Requirement | Evidence | Status |
|---|---|---|
| 90-120 page target | Audit reports 114 pages | Pass |
| At least 22,000 thesis words | Audit reports 32,742 PDF words | Pass |
| Formal front matter | ECE-template-style cover, declaration/copyright, certification, preface, abstracts, contents, figures/tables | Pass structurally; final metadata blocked |
| Greek abstract | `thesis/chapters/00_abstracts.tex` | Pass |
| English abstract | `thesis/chapters/00_abstracts.tex` | Pass |
| At least 20 traceable figures/tables | Audit reports 274 figure/table files | Pass |
| Implementation and experiment chapters with substance | `thesis/chapters/04_implementation.tex`, `05_experiments.tex`, `06_validation.tex`, `06_discussion.tex` | Pass for draft; human proofread still required |
| No placeholder sections | Audit reports 0 TODO markers; placeholder findings are limited to front-matter metadata | Pass for body; blocked for final front matter |

## Core Implementation Checks

| Requirement | Evidence | Status |
|---|---|---|
| 3x3 cubie model | `src/rubik_optimal/cube.py`; covered by tests and audit source-path check | Pass |
| Legal move parser | `src/rubik_optimal/moves.py`; CLI and tests cover parsing/verification paths | Pass |
| Half-turn metric | HTM move set in move/parser/tests and thesis explanation | Pass |
| Deterministic scramble generator | `src/rubik_optimal/scramble.py`; CLI `scramble`; benchmark seed 2026 | Pass |
| Cube validity/solvability checks | `src/rubik_optimal/validity.py`; tests and thesis discussion | Pass |
| Independent solution verifier | `src/rubik_optimal/verify.py`; `scripts/verify_results.py` reports 52 rows, 0 errors | Pass |
| CLI entry point | `python -m rubik_optimal.cli --help` lists required commands | Pass |
| 3x3 E2E practical solve path | `src/rubik_optimal/solvers/end_to_end.py`, expanded CLI solver choices, `scripts/run_3x3_end_to_end.py`, and `results/processed/e2e_3x3_seed_2026_thesis.json` cover sequence and facelet inputs with independently verified solutions | Pass for practical E2E functionality; not an optimality proof |
| Status labels | Audit finds `exact`, `non_exact`, `lower_bound`, `timeout`, `not_applicable`, `failed` | Pass |
| Coordinate layer | `src/rubik_optimal/coordinates/` includes CO, EO, CP, EP, UD-slice, phase-2 projections, a combined corner-state coordinate for the PDB, and 6-edge subset coordinates | Pass |
| Reproducible move/pruning/PDB tables | `data/generated/table_manifest_thesis_seed_2026.json`, `data/generated/thesis_seed_2026_corner_state_pdb.bin`, eight `data/generated/thesis_seed_2026_edge_subset_*_pdb.bin` artifacts, two `data/generated/thesis_seed_2026_edge_cpdb_*.bin` artifacts, `data/generated/h48/thesis_seed_2026/h48h0.bin`, `data/generated/h48/thesis_seed_2026/h48h7.bin`; 12 JSON table metadata rows plus complete corner/edge PDB, CPDB, and H48 metadata | Pass |
| Native Kociemba | `src/rubik_optimal/solvers/kociemba.py`; thesis summary 13/13 verified `non_exact` | Pass for scoped native solver; not optimal |
| Native Thistlethwaite | `src/rubik_optimal/solvers/thistlethwaite.py`; four-phase G0->G1->G2->G3->solved subgroup chain with explicit half-turn final stage; focused tests pass; regenerated thesis benchmark summary verifies 13/13 `non_exact` rows | Pass for bounded educational solver; not optimal and not historical static maneuver-table reproduction |
| Korf/IDA*/H48 table heuristic | `src/rubik_optimal/solvers/korf.py`, `src/rubik_optimal/solvers/h48_native.py`, `search/ida_star.py`, generated projection pruning tables, native corner PDB, native edge PDBs, native optimal solver, H48 h0/h48h7 tables/backend, optional Nissy DR/UD heuristic bridge, upper-bound certificate support, H48 superflip certification, batch table-load amortization, trusted-table validation skip, `rubik-optimal oracle`, `FastOptimalOracle`, `PortfolioOptimalOracle`, `RaceOptimalOracle`, `ResidentRaceOptimalOracle`, and `UniversalOptimalOracle`; benchmark has 11 exact rows and 2 Python-track lower-bound rows, while native optimal evidence has 4 thesis exact rows plus H48 h0/h48h7 stress/certification/CLI/trusted/race/resident-race/universal/batched-universal/inverse-certificate/symmetry-certificate evidence | Pass as scoped exact-search track with real 3x3 PDBs and public-solver-derived H48 oracle-grade support; not a formal all-state runtime proof |
| H48 public-solver-derived backend | `native/h48_backend/h48_backend.c`, vendored `native/h48_backend/third_party/nissy_core/`, `src/rubik_optimal/tables/h48.py`, `src/rubik_optimal/runtime.py`, `src/rubik_optimal/solvers/h48_native.py`, `scripts/generate_h48_tables.py`, `scripts/inspect_h48_capacity.py`, `scripts/run_h48_oracle_certification.py`, `scripts/benchmark_h48_batch_overhead.py`, `scripts/benchmark_h48_trusted_table.py`, `scripts/run_h48_oracle_cli.py`, `results/processed/h48_metadata_seed_2026_thesis_h48h0.json`, `results/processed/h48_metadata_seed_2026_thesis_h48h7.json`, `results/processed/h48_capacity_seed_2026_thesis_lowload.json`, `results/processed/h48_oracle_certification_seed_2026_thesis.json`, `results/processed/h48_batch_overhead_seed_2026_thesis.json`, `results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json`, `results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json`, `results/processed/h48_oracle_cli_seed_2026_thesis_trusted.json`, `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json`, `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json`, and `results/processed/h48_oracle_cli_seed_2026_thesis.json` | Pass as in-repository vendored backend with attribution/license, strongest-local table auto-selection, and load-aware thread sizing; supervisor approval of GPL vendoring still needed |
| External optimal reference/certificate backend | `src/rubik_optimal/solvers/nissy_external.py`, CLI solver `nissy-light`, and `scripts/run_3x3_optimal.py --nissy-certificate`; stress artifact proves deterministic `random_3_20` at distance 17 by matching a verified Nissy-light candidate upper bound with native `final_bound=17`; the portfolio state-input-only artifact proves the Nissy optimal path can recover a verified representative scramble when no source sequence is supplied | Pass as optional external-assisted certificate/evidence path; direct raw cube-state Nissy CLI input is not claimed |
| 2x2x2 exact case study | `src/rubik_optimal/pocket/`; thesis Pocket Cube summary reports 3,674,160 states, max distance 11 | Pass |

## Algorithm Tracks

| Track | Evidence | Status |
|---|---|---|
| A: 3x3 model, notation, validation | Cubie model, all HTM turns, parser, inverse/verify paths, solvability checks, serialization in results | Pass |
| B: coordinate/tables | CO, EO, CP, EP/phase-specific permutations, UD-slice, move/pruning generators, native corner and edge PDB generators, H48 h0 and h48h7 table generator, metadata with size/runtime/checksum | Pass |
| C: native Kociemba | In-repo phase 1/phase 2 search, phase-specific projections/pruning, thesis benchmark verification | Pass scoped; not globally optimal |
| D: native Thistlethwaite | Four-phase subgroup-chain solver, explicit G0/G1/G2/G3 goals, allowed move sets/search support, generated G3 projection encodings, reconstruction, thesis results | Pass bounded four-phase; not full historical static maneuver-table implementation |
| E: Korf/IDA*/H48 | IDA*, admissible lower bound, generated projection heuristics, native `8! * 3^7` corner PDB, eight native full-cost 6-edge PDBs, two native cost-partitioned edge CPDBs, expanded/CPDB coverage benchmarks, H48 h0 and h48h7 tables, native full-cube optimal evidence rows, timeout labels, optional Nissy DR/UD symmetry-table heuristic bridge, native-certificate evidence, H48 stress evidence, superflip distance-20 certification, H48 batch mode, trusted-table mode, batched universal solving, and inverse-certificate plus symmetry-certificate closure | Pass scoped; fixed depth-20 stress row, 10 extra depth-25 rows, superflip, batched live-state rows, and inverse-derived and symmetry-derived certificate rows are exact with H48/Nissy/cache support; batch/trusted/resident/cache modes improve repeated-call and certificate-covered throughput |
| F: 2x2x2 exact study | Complete normalized BFS distribution and representatives | Pass |

## Required Experiments

| Requirement | Evidence | Status |
|---|---|---|
| Solved-state sanity checks | Thesis benchmark dataset includes solved row and solver summaries | Pass |
| Exact shallow 3x3 states generated by BFS | Benchmark corpus and Korf exact rows cover shallow exact cases | Pass |
| Deterministic random scrambles at multiple depths | Thesis profile seed 2026 includes random depth-10/15/20 cases | Pass |
| End-to-end 3x3 sequence and facelet solving | E2E profile seed 2026 includes solved, shallow sequence, depth-20 sequence, and depth-20 facelet cases; all validate and verify | Pass for practical E2E workflow |
| Native optimal 3x3 selected evidence | `results/processed/optimal_3x3_seed_2026_thesis.json` has 4 exact verified native rows, including `random_2_15` at length 14 | Pass for recorded native rows; not exhaustive performance proof |
| Native-certified 3x3 stress evidence | `results/processed/optimal_3x3_seed_2026_stress.json` has 5 exact verified native-backend rows, including deterministic `random_3_20` at length 17 with `nissy_heuristic=True`, `nissy_certificate=True`, native `final_bound=17`, and `exact_certified_by_upper_bound=True` | Pass as labelled Nissy-derived/native-certificate evidence; keep distinct from pure in-repository table-generation claims |
| H48-native 3x3 stress/certification evidence | `results/processed/optimal_3x3_seed_2026_stress_h48h0.json` has 5 exact verified H48 rows, including deterministic `random_3_20` at length 17; `results/processed/optimal_3x3_seed_2026_stress_h48h7_oracle.json` has 15 exact verified direct-state H48 rows, including 10 extra deterministic depth-25 states; `results/processed/h48_oracle_certification_seed_2026_thesis.json` proves superflip exact at length 20; `results/processed/h48_batch_overhead_seed_2026_thesis.json` records 11.56x repeated-call throughput speedup; `results/processed/h48_trusted_table_speedup_seed_2026_thesis_h48h7.json` records 189.894x checked-versus-trusted speedup for repeated shallow calls; `results/processed/h48_batch_overhead_seed_2026_thesis_trusted.json` records 38.198x trusted batch speedup; `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json` proves trusted/no-preload certification exact with max 91.629342s; `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json` proves trusted/preloaded certification exact but with superflip at 158.440286s; `results/processed/h48_oracle_cli_seed_2026_thesis.json` and `_trusted.json` prove 4/4 public CLI oracle rows exact/verified; H48 metadata records h48h0 and h48h7 table sizes/checksums | Pass as public-solver-derived in-repository H48 evidence; keep distinct from formal all-state runtime claims |
| 2x2x2 complete-state optimal distribution | `results/processed/pocket_cube_summary_seed_2026_thesis.json` | Pass |
| Kociemba/Thistlethwaite/Korf/BFS/heuristic comparisons | Benchmark tables and solver summaries generated from saved results | Pass for scoped corpus |
| Table-generation time and storage measurements | `results/processed/table_metadata_thesis_seed_2026.json`, `results/processed/corner_pdb_metadata_seed_2026_thesis.json`, `results/processed/edge_pdb_metadata_seed_2026_thesis.json`, `results/processed/h48_metadata_seed_2026_thesis_h48h0.json`, `results/processed/h48_metadata_seed_2026_thesis_h48h7.json` | Pass |
| Timeout and lower-bound reporting | Korf lower-bound rows, timeout status support, and raw benchmark notes; status tables in thesis | Pass |
| Deterministic repeated-enough corpus | Thesis profile seed 2026, 13 cases per solver, saved raw/processed outputs | Pass for thesis corpus |

## Required Commands

| Command | Latest evidence | Status |
|---|---|---|
| `python -m pytest -q` | 101 passed in 65.64s | Pass |
| `python -m rubik_optimal.cli --help` | Required commands listed, including `oracle` | Pass |
| `python scripts/generate_tables.py --profile thesis --seed 2026` | 12 thesis table artifacts and metadata regenerated | Pass |
| `python scripts/generate_corner_pdb.py --profile thesis --seed 2026` | Complete 88,179,840-state native corner PDB regenerated | Pass |
| `python scripts/generate_edge_pdb.py --profile thesis --seed 2026` | Eight complete 42,577,920-state native edge PDBs generated/reused | Pass |
| `python scripts/generate_edge_pdb.py --profile thesis --seed 2026 --additive-face-partition` | Two complete cost-partitioned edge CPDBs generated, 85,155,840 projected states total | Pass |
| `python scripts/generate_h48_tables.py --profile thesis --seed 2026 --solver h48h0 --threads 8 --force` | 31,683,944-byte h48h0 table generated with SHA-256 metadata | Pass |
| `python scripts/generate_h48_tables.py --profile thesis --seed 2026 --oracle --threads 8 --force` | 3,793,842,344-byte h48h7 table generated with SHA-256 metadata | Pass |
| `python scripts/run_3x3_end_to_end.py --profile thesis --seed 2026 --timeout 5` | E2E 3x3 JSON and thesis table generated; 4/4 cases passed | Pass |
| `python scripts/run_3x3_optimal.py --profile thesis --seed 2026 --timeout 120` | Native optimal 3x3 JSON and thesis table generated; 4/4 recorded rows exact and verified | Pass |
| `python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 20 --hard-timeout 240 --include-hard --backend native --threads 8 --split-depth 3 --nissy-heuristic --nissy-certificate` | Native-backed stress JSON and stress table generated; 5/5 rows exact and verified, including deterministic `random_3_20` at length 17 with native `final_bound=17` and a verified Nissy-light upper-bound candidate | Pass as labelled certificate evidence |
| `python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 5 --hard-timeout 20 --include-hard --backend h48-native --threads 8 --h48-solver h48h0 --h48-table-profile thesis --artifact-suffix h48h0` | H48 stress JSON and table generated; 5/5 rows exact and verified, including deterministic `random_3_20` at length 17 | Pass as H48 evidence |
| `python scripts/run_3x3_optimal.py --profile stress --seed 2026 --timeout 10 --hard-timeout 60 --include-hard --backend h48-native --threads 8 --h48-oracle --h48-table-profile thesis --artifact-suffix h48h7_oracle --extra-random-cases 10 --extra-random-depth 25` | H48 h48h7 oracle stress JSON and table generated; 15/15 rows exact and verified, including deterministic `random_3_20` at length 17 and 10 extra depth-25 rows | Pass as oracle-grade H48 evidence |
| `python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --timeout 90 --runtime-target 90 --threads 8` | H48 h48h7 oracle certification JSON and table generated; 4/4 rows exact and verified, including superflip at length 20 with max single-call wrapper runtime 51.813928s | Pass as direct-state oracle certification evidence |
| `python scripts/benchmark_h48_batch_overhead.py --profile thesis --seed 2026 --solver h48h7 --repetitions 12 --timeout 180 --threads 8` | H48 h48h7 repeated-call benchmark generated; 12/12 sequential and 12/12 batch rows exact and verified; 69.740540s separate-process total vs 6.033133s batch wall time, 11.56x throughput speedup | Pass as batch-overhead evidence |
| `python scripts/run_h48_oracle_cli.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --threads 8` | Public `rubik-optimal oracle` JSON and table generated; 4/4 line-delimited rows exact and verified through h48h7; wrapper wall 5.917467s and CLI batch wall 5.853855s | Pass as oracle CLI evidence |
| `python scripts/benchmark_h48_trusted_table.py --profile thesis --seed 2026 --solver h48h7 --repetitions 4 --timeout 120 --threads 8` | H48 trusted-table benchmark generated; 4/4 checked and 4/4 trusted rows exact/verified; 36.643667s checked total vs 0.192970s trusted total, 189.894x speedup | Pass as table-validation overhead evidence |
| `python scripts/benchmark_h48_batch_overhead.py --profile thesis --seed 2026 --solver h48h7 --repetitions 12 --timeout 180 --threads 8 --trusted-table --artifact-suffix trusted` | H48 trusted batch benchmark generated; 12/12 sequential and 12/12 batch rows exact/verified; 4.015766s trusted separate-process total vs 0.105130s trusted batch wall time, 38.198x speedup | Pass as trusted batch-overhead evidence |
| `python scripts/run_h48_oracle_cli.py --profile thesis --seed 2026 --solver h48h7 --timeout 60 --threads 8 --trusted-table --artifact-suffix trusted` | Trusted public `rubik-optimal oracle` JSON and table generated; 4/4 line-delimited rows exact and verified through h48h7; wrapper wall 2.132448s | Pass as trusted oracle CLI evidence |
| `python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 300 --runtime-target 300 --threads 8 --trusted-table --artifact-suffix trusted_no_preload` | H48 trusted/no-preload certification generated; 4/4 rows exact and verified, including deterministic depth-25 at length 18 in 63.444134s and superflip at length 20 in 91.629342s | Pass as trusted hard-corpus evidence; not a 10x hard-search speed claim |
| `python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 180 --runtime-target 180 --threads 8 --trusted-table --preload-table --artifact-suffix trusted_preload` | H48 trusted/preloaded certification generated; 4/4 rows exact and verified, including superflip at length 20 with max wrapper runtime 158.440286s | Pass as trusted/preload hard-corpus evidence; not a 10x hard-search speed claim |
| `python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set thesis --nissy-timeout 45 --nissy-threads 2 --h48-timeout 240 --h48-threads 2 --trusted-table --artifact-suffix nissy_first_lowload` | Portfolio oracle Nissy-first artifact generated; 5/5 rows exact and verified with max batch runtime 10.097333s | Pass as optimized exact portfolio evidence |
| `python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set thesis --state-input-only --no-certificate-cache --no-upper-lower-certificate --nissy-timeout 45 --nissy-threads 2 --h48-timeout 240 --h48-threads 2 --h48-solver auto --trusted-table --artifact-suffix nissy_state_recovery_lowload` | Portfolio state-input-only artifact generated; 5/5 rows exact and verified with max batch runtime 11.431923s, no source sequence passed to the solver, `random_3_20` exact at length 17, and `scramble_source=inverse_verified_kociemba_solution` recorded | Pass as optimized state-input recovery evidence; not raw cube-state Nissy CLI support |
| `python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set hard --case-id superflip_distance_20 --nissy-timeout 3 --nissy-threads 2 --h48-timeout 360 --h48-threads 4 --trusted-table --artifact-suffix superflip_fallback_lowload` | Portfolio hard fallback artifact generated; superflip exact at length 20 in 135.679618s through resident H48 | Pass as hard-case exact fallback evidence |
| `python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set hard --case-id superflip_distance_20 --nissy-timeout 3 --nissy-threads 2 --h48-timeout 360 --h48-threads 4 --trusted-table --artifact-suffix superflip_certificate_cache_lowload` | Portfolio certificate-cache artifact generated; revalidates the saved exact superflip certificate and returns exact length 20 in 0.012885s without rerunning hard search | Pass as repeat-use optimization evidence |
| `python scripts/run_benchmarks.py --profile thesis --seed 2026` | Raw JSONL, summary JSON, and CSV refreshed | Pass |
| `python scripts/verify_results.py` | 52 rows, 0 errors | Pass |
| `python scripts/generate_figures.py --profile thesis --seed 2026` | Benchmark-derived tables/figure data regenerated | Pass |
| `python scripts/run_universal_optimal_oracle.py --profile thesis --seed 2026 --solver h48h7 --timeout 45 --threads 1 --trusted-table --h48-start-delay 10 --artifact-suffix lowload` | Universal oracle artifact generated; 3/3 rows exact and verified across solved fast path, superflip exact-certificate cache, and shallow resident race with H48 deferred | Pass as top-level optimized exact-oracle evidence; not a formal all-state runtime proof |
| `python scripts/run_universal_batch_oracle_corpus.py --profile thesis --seed 2026 --solver h48h7 --depth 5 --depth 10 --depth 15 --cases-per-depth 1 --timeout 45 --threads 1 --trusted-table --state-input-only --artifact-suffix batch_lowload` | Batched universal corpus artifact generated; 3/3 direct-state rows exact and verified, source sequences withheld from the oracle, max runtime 5.164220s | Pass as optimized batched live-state evidence; not a formal all-state runtime proof |
| `python scripts/run_universal_symmetry_oracle.py --profile thesis --seed 2026 --solver h48h7 --timeout 45 --threads 1 --trusted-table --symmetry-variants 2 --case-id shallow_r_u_f2 --artifact-suffix lowload` | Live symmetry-batched universal artifact generated; 1/1 direct-state row exact and verified through `nissy-symmetry-batch`, selected rotation `rot01`, max runtime 6.002269s | Pass as optimized exact symmetry-batch evidence; not a formal all-state runtime proof |
| `python scripts/run_certificate_cache_inverse_closure.py --profile thesis --seed 2026 --solver h48h7 --artifact-suffix lowload` | Inverse-certificate closure artifact generated; 16/16 inverse-derived direct-state rows exact and verified through `exact-certificate-cache`, max runtime 0.021839s, no H48/Nissy backend process required | Pass as zero-search certificate-coverage expansion; not arbitrary-state coverage |
| `python scripts/run_certificate_cache_symmetry_closure.py --profile thesis --seed 2026 --solver h48h7 --artifact-suffix lowload` | Symmetry-certificate closure artifact generated; 736/736 symmetry-derived direct-state rows exact and verified through `exact-certificate-cache`, max runtime 0.416615s, no H48/Nissy backend process required | Pass as zero-search certificate-coverage expansion for rotationally equivalent proven states; not arbitrary-state coverage |
| `python scripts/thesis_audit.py` | Command succeeds; reports local gates true, 114 pages, required generated artifacts, figure/table files, required `oracle` CLI command, trusted H48/portfolio/state-recovery/race/resident-race/universal/batched-universal/live-symmetry/inverse-certificate/symmetry-certificate evidence present, eight edge PDBs plus two edge CPDBs present, and final readiness false | Pass command; final blocked |
| `latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex` | Builds 112-page `main.pdf`; copied to `thesis/main.pdf` | Pass |
| `python scripts/apply_final_metadata.py --help` | Script help runs; approved values must be supplied before real use | Pass |

## Research Checks

| Requirement | Evidence | Status |
|---|---|---|
| Rubik state space and metrics | Cited BibTeX/research notes include Rubik/group and metric sources | Pass |
| God's Number = 20 | `rokicki2010godsnumber`, `rokicki2013diameter` | Pass |
| Thistlethwaite algorithm | `scherphuisThistlethwaite` and Kociemba background sources | Pass for background |
| Kociemba two-phase | `kociembaTwoPhase`, `kociembaImplementationDetails`, `kociembaCubeExplorer` | Pass |
| Korf IDA*/PDB | `korf1985iddfs`, `korf1997pattern`, `culberson1996pdb`, `felner2004additivePDB` | Pass |
| A*/IDA*/heuristics/PDBs | `hart1968astar`, `pearl1984heuristics`, `russellNorvig2020aima`, Korf/PDB sources | Pass |
| Group theory/cube constraints | `joyner2008adventures`, `gapRubikExample`, `sageCubeGroup`, `singmaster1981notes` | Pass |
| Official UPatras/ECE rules | `eceDiplomaRegulation2023`, `eceStudyGuide2025`, `eceOrkomosiaPage2026`, `eceDiplomaThesesPage2026` | Pass |
| Topic-brief Prolog/Kallipos reference | `sgarbas2024prolog` | Pass |
| At least 20 verified sources | Audit reports 26 | Pass |
| Every BibTeX source cited or removed | Audit reports no uncited entries | Pass |
| Every citation resolves | LaTeX/citation grep has no unresolved citation warnings | Pass |
| Every source has research note | Audit reports no missing research notes | Pass |
| Unverifiable items tracked | `docs/SOURCES_TO_FETCH.md` tracks remaining policy/metadata items | Pass |

## Thesis Content Checks

| Required thesis component | Evidence | Status |
|---|---|---|
| Greek title | `thesis/main.tex`; source-backed from topic brief | Pass |
| English title | `thesis/main.tex`; source-backed from topic brief | Pass |
| Formal front matter | `thesis/chapters/00_front_matter.tex` | Pass structurally; final metadata blocked |
| Greek abstract | `thesis/chapters/00_abstracts.tex` | Pass |
| English abstract | `thesis/chapters/00_abstracts.tex` | Pass |
| Introduction | `thesis/chapters/01_introduction.tex` | Pass |
| Mathematical/computational background | `thesis/chapters/02_background.tex` | Pass |
| Cube representation and metric | `thesis/chapters/03_cube_model.tex` | Pass |
| Literature review | `thesis/chapters/04_literature_review.tex` | Pass |
| Algorithm design | `thesis/chapters/03_algorithms.tex`, `05_system_design.tex` | Pass |
| Implementation chapter | `thesis/chapters/04_implementation.tex` | Pass |
| Experimental methodology/results | `thesis/chapters/05_experiments.tex` | Pass |
| Discussion | `thesis/chapters/06_discussion.tex` | Pass |
| Conclusions/future work | `thesis/chapters/07_conclusions.tex` | Pass |
| Bibliography | `thesis/references.bib`; `main.bbl`; citation checks | Pass |
| Appendices | `thesis/chapters/a_reproducibility.tex`, `b_result_schema.tex`, `c_submission_checklist.tex`, `d_cli_reference.tex` | Pass |
| Reproducibility notes | `REPRODUCIBILITY.md`, appendix A | Pass |

## Claim Integrity Checks

| Risk area | Evidence | Status |
|---|---|---|
| "Optimal" wording | Audit lists claim-risk markers; thesis explicitly limits optimal claims to completed exact searches and Pocket Cube | Pass with human proofread caveat |
| Exact distance | Status labels distinguish exact/lower_bound/timeout/non_exact; Korf exact rows only when completed; `distance --h48-native` and `distance --h48-oracle` can use direct H48 state input for exact distance when the backend completes | Pass |
| God's Number | Cited to verified sources; not used as implementation claim | Pass |
| Complete solver | Thesis states native full-cube optimal search is exact only when completed and does not claim fast all-state coverage | Pass |
| General solver | Kociemba/native staged solvers presented as practical/scoped and `non_exact` | Pass |
| Admissible heuristic | Projection pruning tables and corner PDB described as admissible lower bounds for projections, not full oracle | Pass |
| Pattern database | Thesis distinguishes native complete corner/edge PDBs from full historical additive/cost-partitioned multi-PDB systems | Pass |
| UPatras format | Official sources/templates archived; final metadata/style approval still blocked | Partial |
| No manually typed benchmark values | Thesis tables/figures generated from saved results; generated-artifact audit has no stale artifacts | Pass |

## Roadmap Phase Status

| Phase | Evidence | Status |
|---|---|---|
| A: acceptance reset | `docs/goal.md`, `docs/acceptance.md`, calibration docs | Pass |
| B: research and shell expansion | 26 sources, formal front matter, scale audit script | Pass with style-review caveat |
| C: coordinate/table foundation | Coordinate modules, generated tables, tests | Pass |
| D: native solver tracks | Native Kociemba, four-phase Thistlethwaite, Korf/IDA*, Pocket Cube | Pass bounded/scoped; not arbitrary optimal 3x3 |
| E: thesis benchmark profile | Thesis profile benchmark, verifier, generated tables/figures | Pass |
| F: full thesis writing | 93-page Greek thesis with generated evidence and limitations | Pass for review draft; human proofread needed |
| G: final audit | `docs/final_audit.md`, this matrix, audit JSON, `handoff_documents.passed: true`, and `supervisor_approval.passed: false` | Blocked on external final metadata and approvals |

## Remaining Missing or Externally Blocked Requirements

| Missing or weak item | Evidence | Required next action |
|---|---|---|
| Student identity metadata | Placeholders in `thesis/main.tex` for Greek/English display name, full name with patronymic, and registration number; request captured in `docs/supervisor_handoff_request.md`; handoff docs audit passes | Obtain authoritative values from student/Secretariat |
| Cover date | `\thesisPlaceDate` remains `ΠΑΤΡΑ - ΜΗΝΑΣ ΕΤΟΣ` | Obtain final place/month/year format |
| Copyright year | `thesis/chapters/00_front_matter.tex` still has `20XX` | Obtain final year |
| Public examination date | Certification page still has date placeholder | Obtain final date |
| Second and third committee members | Committee placeholders remain | Obtain names, ranks, departments |
| Division director signature details | Name/rank placeholders remain | Obtain Secretariat-confirmed values |
| Bibliography/front-matter style approval | Machine consistency passes, but style approval is not verified; request captured in `docs/supervisor_handoff_request.md`; handoff docs audit passes | Supervisor/Secretariat confirmation needed |
| Final supervisor/Secretariat approval record | `docs/final_supervisor_approval.template.md` exists, but real `docs/final_supervisor_approval.md` is intentionally missing until approval is received; audit reports `supervisor_approval.passed: false` | Obtain approval source/date and approved style/scoped-claim decisions, then create the real record |
| Reproducible metadata application | `docs/final_metadata_values.template.json` and `scripts/apply_final_metadata.py` exist; template dry-run is expected to fail until real values replace `TODO` entries | Fill approved-values JSON from authoritative response, run dry-run, then apply |
| Final human proofread | Mechanical layout gates pass; underfull warnings remain around URLs/paths | Full PDF review before submission |
| Fast all-state optimal 3x3 oracle | Native full-cube exact search and H48-native exact search are implemented and prove selected rows, including the recorded depth-15 case, the deterministic depth-20 stress row under H48, 10 extra deterministic depth-25 rows under h48h7, and superflip exact at length 20. Direct arbitrary facelet/cubie H48 input is implemented and verified for saved H48 stress/certification corpora. Batch mode removes repeated table-load overhead and records 11.56x throughput speedup for repeated exact h48h7 calls, trusted-table mode records 189.894x speedup for repeated shallow table-check dominated calls, trusted batch mode records 38.198x throughput speedup, and `rubik-optimal oracle` exposes that batch path for line-delimited user inputs with saved exact/verified CLI evidence. Universal batched live-state solving is exact on the saved corpus, inverse-certificate closure gives zero-search exact answers for 16 derived states in at most 0.021839s, and symmetry-certificate closure gives zero-search exact answers for 736 rotationally derived states in at most 0.416615s. Trusted/no-preload hard certification is exact with max 91.629342s, while trusted/preloaded superflip takes 158.440286s and the experimental auto-min-depth hard run timed out. This still does not prove a formal worst-case practical runtime bound over every possible state | Keep limitation for all-state performance claims unless a formal h48h7 all-state/runtime boundary is documented |

## Completion Rule

This audit does not call the project complete. The next acceptance transition is
not another local rebuild; it is replacement or explicit acceptance of the
front-matter placeholders listed in `docs/final_metadata_packet.md`, followed by:

```bash
python scripts/apply_final_metadata.py <approved-values.json> --dry-run
python scripts/apply_final_metadata.py <approved-values.json>
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
cp main.pdf thesis/main.pdf
python scripts/thesis_audit.py
```

The target post-metadata audit state is:

```text
front_matter_placeholders: []
supervisor_approval.passed: true
submission_blockers: []
final_submission_ready: true
```
