# Roadmap to Delivered Thesis

This roadmap replaces the earlier "base scaffold is complete" framing. The current repository is a starting point, not a final thesis.

## Phase A: acceptance reset

Status: done on 2026-05-16.

Deliverables:

- compare against delivered thesis example;
- update `docs/goal.md`;
- update `docs/acceptance.md`;
- mark old final audit as superseded;
- document current limitations honestly.

## Phase B: research and thesis shell expansion

Deliverables:

- verify 20-30 sources;
- expand `docs/research_notes.md`;
- update `thesis/references.bib`;
- build formal front matter;
- expand chapter skeleton to delivered-thesis page targets;
- add thesis-scale audit script.

Exit gate:

- `python scripts/thesis_audit.py` reports no placeholder chapters and a realistic path to the target page/word count.

## Phase C: coordinate and table foundation

Deliverables:

- implement 3x3 coordinate modules;
- implement coordinate roundtrip tests;
- implement move-table generation;
- implement table metadata and checksums;
- document coordinates in thesis.

Exit gate:

- table generation script runs reproducibly;
- direct cubie moves and coordinate move tables agree in tests.

## Phase D: native solver tracks

Deliverables:

- native Kociemba-style phase 1 and phase 2 solver;
- native Thistlethwaite-style subgroup solver;
- Korf/IDA* with generated table-based heuristic;
- complete 2x2x2 optimal case study if arbitrary 3x3 optimal solving remains computationally limited.

Exit gate:

- every returned solution is independently verified;
- `not_applicable` is not the dominant status for required solver tracks;
- exact/non-exact/lower-bound/timeout labels are correct.

## Phase E: thesis benchmark profile

Deliverables:

- `quick`, `thesis`, and optional `stress` profiles;
- saved raw results;
- processed summaries;
- generated tables and figures;
- result verifier with stale-artifact checks.

Exit gate:

- `python scripts/run_benchmarks.py --profile thesis --seed 2026` passes;
- `python scripts/verify_results.py` passes;
- generated thesis tables/figures match result files.

## Phase F: full thesis writing

Deliverables:

- Greek thesis body expanded to target density;
- theory, design, implementation, experiment, discussion, and conclusion chapters fully written;
- every figure/table introduced and interpreted;
- limitations section aligned with actual results;
- Supervisor-facing metadata and approval packet drafted.

Exit gate:

- XeLaTeX build passes;
- thesis audit passes;
- no unsupported claims remain.

## Phase G: final audit

Deliverables:

- final `docs/final_audit.md`;
- command log;
- thesis scale report;
- algorithm status table;
- unresolved supervisor metadata/questions;
- final manual review checklist.

Exit gate:

- `docs/acceptance.md` is satisfied or a documented, supervisor-accepted blocker remains.
