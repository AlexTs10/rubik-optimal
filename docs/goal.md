# Master Goal: Delivered Rubik's Cube Thesis

Build a complete, reproducible, academically honest University of Patras ECE thesis repository for:

**Greek title:** Αλγόριθμοι Βέλτιστης Επίλυσης για τον Κύβο του Rubik  
**English title:** Optimal Solution Algorithms for Rubik's Cube

Institution:

```text
Πανεπιστήμιο Πατρών
Τμήμα Ηλεκτρολόγων Μηχανικών και Τεχνολογίας Υπολογιστών
```

Supervisor:

```text
Κυριάκος Σγάρμπας
```

## Calibration Point

The previously produced short thesis draft is not an acceptable final target. A 21-page scaffold with a Kociemba adapter, `thistlethwaite_scoped` returning mostly `not_applicable`, and native Kociemba/Thistlethwaite/pattern databases left as future work does not match the level expected for a delivered diploma thesis.

The repository target is calibrated against the delivered example:

```text
/Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ ΚΟΝΤΟΥΛΗΣ.pdf
```

The calibration is documented in:

```text
docs/reference_thesis_calibration.md
```

Final output should be comparable in academic density and completeness, while staying Rubik-specific and claim-safe:

- about 90-120 pages, unless a supervisor-approved exception is documented;
- about 22,000-30,000 thesis words, excluding bibliography and generated code listings;
- formal University of Patras-style front matter;
- dense Greek academic chapters, not placeholder prose;
- at least 20 traceable figures/tables combined;
- implementation, experiment, and discussion chapters with enough substance to stand as a delivered thesis;
- honest limitations that do not replace required work unless a verified blocker exists.

## Source of Truth

Read the thesis topic brief first:

```text
specs/topic_brief.pdf
```

The extracted requirements are maintained in:

```text
docs/requirements_from_brief.md
```

If the PDF and this file disagree, the PDF wins.

## Objective

Create a repository containing:

1. all source code needed for the Rubik's Cube algorithms;
2. all reproducible table-generation, experiment, and figure scripts;
3. a verified bibliography and research notes;
4. a full Greek LaTeX thesis ready for supervisor review;
5. documentation explaining limitations, setup, reproducibility, and remaining institutional metadata.

The thesis must be ambitious enough to be defensible as an undergraduate/diploma thesis. It must still not overclaim.

## Hard Academic Rules

1. Do not invent papers, citations, DOI values, URLs, benchmark numbers, theorem claims, or university rules.
2. Do not claim an algorithm is optimal unless this is verified for the exact reported cases.
3. Do not claim arbitrary-state optimal 3x3 solving unless it is actually implemented and tested.
4. Every technical claim must be supported by one of:
   - a verified citation;
   - a reproducible experiment;
   - a test;
   - a proof/explanation based on the implemented model.
5. Every limitation must be stated directly and not hidden.
6. If internet access is unavailable, create or update `docs/SOURCES_TO_FETCH.md` and stop before claiming bibliography completion.
7. Keep authorship, third-party code, benchmark evidence, and thesis claims explicit for supervisor review.

## Final Thesis Outcome

The repository is not complete until it demonstrates all of the following:

1. correct 3x3 Rubik's Cube cubie representation;
2. correct legal move parser under the face-turn / half-turn metric;
3. cube validity and solvability checks;
4. deterministic scramble generation;
5. a native coordinate layer with reproducible move-table generation;
6. a native Kociemba-style two-phase implementation, not just an external adapter;
7. a native Thistlethwaite-style subgroup-chain implementation at educational/practical thesis level;
8. a Korf/IDA* optimal-search track with non-trivial admissible table/PDB-based heuristics, including a real 3x3 pattern-database component where feasible;
9. a complete 2x2x2 optimal-solver case study if full arbitrary 3x3 optimal solving remains computationally limited;
10. distance recognition that clearly reports exact distance, lower bound, timeout, or invalid state;
11. reproducible benchmarks over shallow exact states and deeper practical scrambles;
12. generated figures/tables from saved result files;
13. verified bibliography;
14. a full Greek thesis matching the scale described above;
15. limitations that explain real constraints without treating core missing algorithms as acceptable final omissions.

## Required Algorithm Tracks

### Track A: 3x3 model, notation, and validation

Required:

- cubie-level state with corner permutation, corner orientation, edge permutation, and edge orientation;
- all 18 HTM face turns;
- parser and inverse-sequence support;
- physical solvability checks;
- independent solution verifier;
- serialization suitable for result files.

### Track B: coordinate representation and tables

Required:

- corner-orientation coordinate;
- edge-orientation coordinate;
- corner-permutation coordinate;
- edge-permutation or phase-specific permutation coordinates;
- UD-slice coordinate;
- move-table generator;
- pruning-table generator where used by solvers;
- native-generated 3x3 pattern-database evidence where used by Korf/IDA*;
- saved metadata: table name, size, generation time, seed/config, checksum.

The thesis must explain the coordinates and show table-generation results.

### Track C: native Kociemba-style two-phase solver

Required:

- in-repo phase 1 search toward the restricted subgroup;
- in-repo phase 2 search inside the reduced subgroup;
- phase-specific coordinates and pruning tables;
- deterministic table generation or documented checked-in generated tables;
- solution verification for every returned sequence;
- benchmarking on the thesis dataset.

Allowed claim:

- practical/general 3x3 solver with verified solutions;
- not globally optimal unless an exact optimal variant is implemented and proven.

Not allowed as final completion:

- relying only on the optional external `kociemba` package adapter.

### Track D: native Thistlethwaite-style solver

Required:

- explicit subgroup-chain design;
- phase goals and allowed move sets;
- table or search support for each stage;
- solution reconstruction;
- thesis benchmarks and discussion.

Allowed claim:

- educational/practical subgroup-chain implementation;
- stage-wise reduction and verified final solved outputs.

Not allowed as final completion:

- `not_applicable` for most non-solved benchmark rows.

### Track E: Korf/IDA* and admissible heuristics

Required:

- IDA* implementation with iterative cost bounds;
- admissible lower-bound heuristic;
- generated table-based heuristics and a native-generated 3x3 pattern database where feasible;
- shallow BFS cross-checks;
- exact status only when the search proves optimality;
- timeout/lower-bound status when exact proof is unavailable.

### Track F: complete 2x2x2 optimal case study

Required if full arbitrary-state optimal 3x3 remains outside local compute limits:

- complete 2x2x2/Pocket Cube state model or a justified projection from the 3x3 corner system;
- exhaustive BFS or equivalent complete optimal-distance computation;
- distance distribution table;
- representative optimal solutions;
- generated plots/tables;
- discussion connecting the feasible complete case to 3x3 pattern databases and optimal search.

## Required Experiments

Experiments must include:

1. solved-state sanity checks;
2. exact shallow 3x3 states generated by BFS;
3. deterministic random scrambles at multiple depths;
4. 2x2x2 complete-state or large-sample optimal distribution;
5. Kociemba, Thistlethwaite, Korf/IDA*, BFS, and heuristic-ablation comparisons;
6. table-generation and pattern-database generation time and storage measurements;
7. timeout behavior and lower-bound reporting;
8. repeated runs or enough deterministic cases to support meaningful discussion.

Every benchmark value in the thesis must come from saved results generated by scripts.

## Required Repository Structure

Expected final repository:

```text
rubik-thesis/
├── pyproject.toml
├── README.md
├── REPRODUCIBILITY.md
├── AGENTS.md
├── docs/
├── specs/
│   └── topic_brief.pdf
├── src/
│   └── rubik_optimal/
├── tests/
├── scripts/
├── data/
│   └── generated/
├── results/
│   ├── raw/
│   └── processed/
└── thesis/
    ├── main.tex
    ├── references.bib
    ├── chapters/
    ├── figures/
    └── tables/
```

## Required Python CLI

Package name:

```text
rubik_optimal
```

Required CLI commands:

```text
scramble
solve
verify
benchmark
distance
oracle
tables
```

Additional thesis-grade commands should be added as implementation matures:

```text
generate-tables
generate-pdb
benchmark-profile
audit-thesis
```

## Required Tests

Create and maintain tests for:

- identity cube;
- move inverses;
- four quarter turns returning identity;
- half turn equals two quarter turns;
- legal and illegal move parsing;
- scramble followed by inverse returns solved;
- cube validity and solvability checks;
- coordinate roundtrips;
- move-table correctness against direct cube moves;
- pruning-table admissibility;
- solver output actually solves the input;
- shallow BFS exact distances;
- heuristic lower-bound admissibility on shallow states;
- Pocket Cube exhaustive/known-distance cases;
- deterministic benchmark output;
- thesis result-verifier checks.

## Required Research

Verify and cite sources for:

- Rubik's Cube state space and metrics;
- God's Number = 20;
- Thistlethwaite algorithm;
- Kociemba two-phase algorithm;
- Korf IDA* and pattern databases;
- A*, IDA*, admissible heuristics;
- pattern databases and disjoint pattern databases;
- group theory and permutation/orientation constraints;
- official University of Patras / ECE thesis rules or formatting guidance;
- Prolog/Kallipos chapter referenced in the topic brief, if relevant.

Target at least 20-30 verified thesis sources unless the supervisor approves a smaller bibliography.

## Required Thesis Structure

The thesis structure and page allocation are defined in:

```text
docs/thesis_structure.md
```

The final PDF should be supervisor-review ready, not a short technical report.
