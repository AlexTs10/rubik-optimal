# Benchmark Plan

The purpose of benchmarking is to compare solver behavior honestly and reproducibly. Quick benchmarks are useful for development, but final thesis data must come from the `thesis` benchmark profile.

## Benchmark principles

- Use deterministic seeds.
- Save raw outputs.
- Generate processed tables from raw outputs.
- Do not manually type benchmark values into the thesis.
- Label exact and non-exact results clearly.
- Include timeouts as data.
- Record generated table sizes and table-generation times.
- Keep quick, thesis, and stress profiles separate.

## Benchmark profiles

### quick

Purpose:

- development sanity;
- CI-friendly runtime;
- checks that schema, solvers, and verifier still work.

This profile cannot satisfy final thesis acceptance.

### thesis

Purpose:

- final reported benchmark data;
- reproducible thesis tables and figures;
- enough cases to support meaningful discussion.

Required command:

```bash
python scripts/generate_corner_pdb.py --profile thesis --seed 2026
python scripts/generate_edge_pdb.py --profile thesis --seed 2026
python scripts/run_3x3_end_to_end.py --profile thesis --seed 2026
python scripts/run_3x3_optimal.py --profile thesis --seed 2026
python scripts/run_benchmarks.py --profile thesis --seed 2026
```

### stress

Purpose:

- optional deeper exploratory runs;
- timeouts, scaling curves, and hard-case discussion.

Stress results may be included only if generated and verified.

## Benchmark datasets

### Dataset A: solved cube

One case:

```text
solved
```

Purpose:

- sanity check;
- distance 0;
- every solver should return empty or zero-length solution.

### Dataset B: exact shallow 3x3 states

Generate states by BFS at depths:

```text
1 2 3 4 5 6 7 8
```

The final thesis profile should include multiple cases per depth where feasible.

Purpose:

- exact BFS comparison;
- heuristic admissibility;
- shallow optimality verification.

Avoid immediate inverse moves when generating scrambles.

### Dataset C: deterministic 3x3 scrambles

Use fixed seeds and target lengths such as:

```text
5 10 15 20 25
```

Purpose:

- general solver evaluation;
- runtime and solution-length comparison;
- timeout/lower-bound behavior.

### Dataset D: table-generation benchmarks

Record:

- coordinate/table name;
- profile;
- state count;
- generated entries;
- runtime;
- file size;
- checksum;
- memory notes where available.

Purpose:

- connect implementation work to thesis claims;
- support comparison between simple and table-based heuristics.
- record the native 3x3 corner-state PDB and 6-edge PDBs used by the Korf/IDA* heuristic.

### Dataset E: selected native optimal 3x3 evidence

Record:

- solved and shallow exact sanity cases;
- deterministic random depth-10 and depth-15 exact-search cases;
- optional depth-20 stress case, with native rows reported as native and Nissy-light rows reported either as external reference evidence or as a labelled upper-bound certificate source for native lower-bound proof;
- optional H48-native stress rows reported separately with `h48h0` and oracle-grade `h48h7` table metadata and exact/timeout-only status;
- runtime, nodes, initial lower bound, table bytes, and verification status.

Purpose:

- show the strongest currently implemented arbitrary-state exact-search path and, where enabled, an external optimal reference backend;
- show the public-solver-derived in-repository H48 backend as separate evidence, including the generated `h48h7` oracle-grade stress artifact, not as an original all-state runtime theorem;
- keep exact claims tied to completed exact search and label external evidence separately from native implementation claims.

### Dataset F: 2x2x2 optimal case study

Required if full arbitrary-state optimal 3x3 solving is not achieved.

Record:

- full distance distribution or justified canonical distribution;
- representative optimal paths;
- generation runtime;
- state count;
- verification checks.

Purpose:

- demonstrate complete optimal search at feasible scale;
- provide real exact-distance results beyond shallow 3x3 cases.

### Dataset G: selected hard cases

Only add after the base system is stable.

Purpose:

- demonstrate computational difficulty;
- compare timeout behavior;
- report limitations.

## Solvers to compare

Required final comparison:

- BFS for shallow states;
- IDA* with trivial/simple admissible heuristic;
- IDA* with table-based heuristic;
- native Kociemba two-phase solver;
- native Thistlethwaite subgroup solver;
- native optimal 3x3 full-cube IDA* with corner and edge PDBs for selected exact evidence;
- native H48 backend with generated/reused H48 table metadata for selected exact stress evidence;
- optional external Kociemba adapter as comparison only;
- 2x2x2 optimal solver where applicable.

## Metrics

Record:

```text
case_id
profile
seed
scramble
known_depth
solver
solution
solution_length
metric
runtime_seconds
expanded_nodes
generated_nodes
table_name
table_size_bytes
table_generation_seconds
status
verified
notes
```

## Required scripts

```text
scripts/run_benchmarks.py
scripts/verify_results.py
scripts/generate_figures.py
scripts/generate_tables.py
scripts/generate_corner_pdb.py
scripts/generate_edge_pdb.py
scripts/generate_h48_tables.py
scripts/run_3x3_end_to_end.py
scripts/run_3x3_optimal.py
scripts/thesis_audit.py
```

## Output paths

Raw results:

```text
results/raw/
```

Processed results:

```text
results/processed/
```

Thesis figures:

```text
thesis/figures/
```

Thesis tables:

```text
thesis/tables/
```

Generated algorithm tables:

```text
data/generated/
```

## Required figures

Generate at least:

1. runtime vs scramble depth;
2. expanded nodes vs scramble depth;
3. solution length by solver;
4. heuristic comparison;
5. table size vs search performance;
6. table-generation time by table;
7. 2x2x2 distance distribution, if the case study is used;
8. timeout/lower-bound summary for deeper 3x3 cases.

## Required tables

Generate at least:

1. solver feature comparison;
2. benchmark dataset summary;
3. exact-distance shallow cases;
4. practical/general scramble results;
5. Kociemba phase/table status;
6. Thistlethwaite stage status;
7. IDA* heuristic-ablation summary;
8. generated table metadata;
9. 2x2x2 optimal-distance distribution, if used;
10. limitations and timeout summary.

## Verification

`python scripts/verify_results.py` must check:

- result files exist;
- schemas are valid;
- every successful solution verifies;
- exact distances match BFS where available;
- lower bounds are not greater than known exact distances;
- table metadata exists for table-based runs;
- corner PDB metadata and binary checksum match when PDB-backed Korf runs are reported;
- thesis tables/figures are not stale relative to processed results, if detectable.
