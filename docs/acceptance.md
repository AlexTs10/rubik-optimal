# Acceptance Checks

The goal is complete only when every required check passes or a verified blocker is documented with evidence and accepted as a thesis-scope decision. The current short draft does not satisfy this file.

## 1. Repository completeness

Required files or folders:

```text
pyproject.toml
README.md
REPRODUCIBILITY.md
AGENTS.md
docs/
specs/topic_brief.pdf
src/rubik_optimal/
tests/
scripts/
data/generated/
results/raw/
results/processed/
thesis/main.tex
thesis/references.bib
thesis/chapters/
thesis/figures/
thesis/tables/
```

## 2. Delivered-thesis scale checks

The final thesis must meet the delivered-thesis target unless the supervisor explicitly approves a smaller scope in writing and the approval is documented.

Required:

- target PDF length: about 90-120 pages;
- minimum body size: about 22,000 Greek thesis words, excluding bibliography, generated tables, and code listings;
- formal front matter: cover, declaration/copyright page, certification/exam metadata placeholders or final values, Greek abstract, English abstract, table of contents, lists of figures/tables if useful;
- at least 20 traceable figures/tables combined;
- implementation and experiment chapters with enough depth to stand as a delivered thesis;
- no placeholder sections.

Required audit support:

```bash
python scripts/thesis_audit.py
```

The audit script must report page count, approximate word count, figure/table counts, unresolved TODOs, stale generated artifacts, and claim-risk markers such as unsupported "optimal" wording.

## 3. Core implementation checks

The implementation must include:

- a 3x3 Rubik's Cube cubie model;
- legal move parser;
- half-turn metric;
- deterministic scramble generator;
- cube validity/solvability checks;
- independent solution verifier;
- CLI entry point;
- solver status labels;
- coordinate layer for solver tables;
- reproducible generated move/pruning tables;
- native-generated 3x3 corner-state pattern database or equivalent non-trivial 3x3 pattern database evidence;
- native Kociemba-style two-phase solver;
- native Thistlethwaite-style subgroup-chain solver;
- Korf/IDA* solver with non-trivial admissible table/PDB-based heuristics;
- first-class optimized H48 oracle API for arbitrary valid 3x3 state input, with exact/timeout/failed status and independent solution verification;
- complete 2x2x2 optimal case study if full arbitrary-state 3x3 exact solving remains computationally limited.

Solver status labels must clearly distinguish:

```text
exact
non_exact
lower_bound
timeout
not_applicable
failed
```

`not_applicable` is acceptable for a solver that legitimately does not support a dataset, but it is not acceptable as the final primary status for the required Thistlethwaite or Kociemba tracks.

## 4. Required command checks

Before final completion, run:

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
python scripts/run_portfolio_optimal_oracle.py --profile thesis --seed 2026 --case-set hard --case-id superflip_distance_20 --nissy-timeout 3 --nissy-threads 2 --h48-timeout 360 --h48-threads 4 --trusted-table --artifact-suffix superflip_fallback_lowload
python scripts/generate_h48_oracle_contract.py --profile thesis --seed 2026 --solver h48h7
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 300 --runtime-target 300 --threads 8 --trusted-table --artifact-suffix trusted_no_preload
python scripts/run_h48_oracle_certification.py --profile thesis --seed 2026 --solver h48h7 --timeout 180 --runtime-target 180 --threads 8 --trusted-table --preload-table --artifact-suffix trusted_preload
python scripts/run_benchmarks.py --profile thesis --seed 2026
python scripts/verify_results.py
python scripts/generate_figures.py --profile thesis --seed 2026
python scripts/thesis_audit.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
```

A quick profile may exist for development, but quick-profile success is not final acceptance.

If a command cannot run because a dependency is unavailable, document:

- command attempted;
- exact error;
- whether this blocks final acceptance;
- how to reproduce/fix it;
- whether the supervisor has accepted the limitation.

## 5. Research checks

The bibliography must include verified sources for:

- Rubik's Cube state space and metrics;
- God's Number = 20;
- Thistlethwaite algorithm;
- Kociemba two-phase algorithm;
- Korf IDA* and pattern databases;
- A*, IDA*, admissible heuristics, and pattern databases;
- group theory and cube-state constraints;
- official University of Patras / ECE thesis formatting or deposit guidance, if available;
- the Prolog/Kallipos reference from the topic brief, if used.

Required:

- at least 20 verified academic/technical sources unless the supervisor approves fewer;
- every source in `thesis/references.bib` is cited or removed;
- every citation in the thesis resolves;
- every source has an entry in `docs/research_notes.md`;
- unverifiable items are tracked in `docs/SOURCES_TO_FETCH.md`.

## 6. Experiment checks

The repository must contain:

```text
scripts/run_benchmarks.py
scripts/verify_results.py
scripts/generate_tables.py
scripts/generate_corner_pdb.py
scripts/generate_edge_pdb.py
scripts/run_3x3_end_to_end.py
scripts/run_3x3_optimal.py
scripts/generate_figures.py
results/raw/
results/processed/
thesis/figures/
thesis/tables/
```

Benchmark output must include:

- solver name;
- scramble or state identifier;
- scramble depth, if known;
- solution length;
- runtime;
- expanded nodes, if available;
- generated nodes, if available;
- memory or table size, if available;
- pattern-database metadata where relevant;
- exact/non-exact/lower-bound/timeout/not-applicable status;
- seed/profile;
- verification status;
- table-generation metadata where relevant.

Required benchmark profiles:

- `quick`: CI/development sanity only;
- `thesis`: final thesis data generation;
- `stress`: optional, for deeper exploratory runs.

All thesis benchmark tables and figures must be generated from saved result files.

## 7. Thesis checks

The thesis must include:

- Greek title;
- English title;
- formal front matter;
- Greek abstract;
- English abstract;
- introduction;
- mathematical/computational background;
- cube representation and metric explanation;
- literature review;
- algorithm design chapters;
- implementation chapter;
- experimental methodology;
- results;
- discussion;
- conclusions and future work;
- bibliography;
- appendices;
- AI-assistance disclosure draft for supervisor review;
- reproducibility notes.

The thesis must build using XeLaTeX.

The final writing must not read like an outline. Each chapter must contain explanatory prose, citations, implementation details, and result interpretation where relevant.

## 8. Claim integrity checks

For each major thesis claim, verify that it is backed by one of:

- citation;
- test;
- reproducible benchmark;
- proof/explanation;
- documented limitation.

Claims that require special care:

- "optimal"
- "exact distance"
- "God's Number"
- "complete solver"
- "general solver"
- "admissible heuristic"
- "pattern database"
- "University of Patras required format"

The following are not allowed in a final delivered thesis:

- saying arbitrary 3x3 states are solved optimally without proof;
- presenting an external Kociemba adapter as the native implementation contribution;
- leaving Kociemba, Thistlethwaite, and PDB work all as future work;
- treating a 2x2 case study as a substitute for all 3x3 implementation work;
- manually typed benchmark numbers in the thesis.

## 9. Final audit

Before final response, create or update:

```text
docs/final_audit.md
```

It must include:

- all commands run;
- pass/fail status;
- thesis page/word/figure/table counts;
- known limitations;
- unresolved supervisor questions;
- evidence that thesis claims match code/results;
- reference-thesis calibration status;
- files that should be reviewed manually before submission.

## 10. Final Codex response format

The final response must contain:

1. Done summary
2. Files created/modified
3. Sources collected
4. Algorithm status table
5. Benchmark summary
6. Thesis PDF path
7. Thesis scale audit
8. Commands run and pass/fail status
9. Known limitations
10. Supervisor questions before submission

The response must not say the work is complete unless this file is satisfied.
