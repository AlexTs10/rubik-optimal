# Architecture Plan

This file defines the intended software architecture for the delivered Rubik thesis project.

## Design goals

The implementation should be:

- correct before fast;
- testable;
- reproducible;
- modular;
- table-generation aware;
- suitable for thesis-scale benchmarking;
- clear enough to explain in the thesis.

## Proposed package layout

```text
src/rubik_optimal/
├── __init__.py
├── cli.py
├── cube.py
├── moves.py
├── notation.py
├── validity.py
├── scramble.py
├── coordinates/
│   ├── __init__.py
│   ├── corner_orientation.py
│   ├── edge_orientation.py
│   ├── corner_permutation.py
│   ├── edge_permutation.py
│   ├── ud_slice.py
│   ├── phase1.py
│   └── phase2.py
├── tables/
│   ├── __init__.py
│   ├── metadata.py
│   ├── move_tables.py
│   ├── pruning_tables.py
│   └── pattern_databases.py
├── search/
│   ├── __init__.py
│   ├── bfs.py
│   ├── ida_star.py
│   ├── astar.py
│   └── heuristics.py
├── solvers/
│   ├── __init__.py
│   ├── base.py
│   ├── thistlethwaite.py
│   ├── kociemba.py
│   ├── korf.py
│   └── pocket_cube.py
├── pocket/
│   ├── __init__.py
│   ├── cube.py
│   ├── tables.py
│   └── optimal.py
├── distance.py
├── verify.py
├── benchmark.py
├── results.py
└── thesis_audit.py
```

## Core abstractions

### CubeState

Represents a 3x3 cube state.

Required behavior:

- create solved cube;
- apply a move;
- apply a sequence;
- compare states;
- hash states;
- serialize/deserialize;
- check solved state;
- validate physical solvability.

### Coordinate

Represents an integer encoding of one projection of a cube state.

Required behavior:

- encode a `CubeState`;
- decode where feasible;
- report coordinate domain size;
- provide move-table indexing;
- support tests against direct cubie moves.

### GeneratedTable

Represents generated move, pruning, or pattern-database data.

Required metadata:

```text
name
profile
domain_size
entry_count
file_path
checksum
generated_at
generator
runtime_seconds
size_bytes
notes
```

### Move

Represents a face turn under the half-turn metric.

Supported moves:

```text
U U' U2 D D' D2 L L' L2 R R' R2 F F' F2 B B' B2
```

### SolverResult

Every solver returns a structured result with:

```text
solver_name
input_state
solution_moves
solution_length
metric
runtime_seconds
expanded_nodes
generated_nodes
table_bytes
status
is_verified
notes
```

Allowed status values:

```text
exact
non_exact
lower_bound
timeout
not_applicable
failed
```

### DistanceResult

The distance command returns:

```text
distance_value
kind
method
runtime_seconds
expanded_nodes
proof_notes
```

Allowed `kind` values:

```text
exact_distance
lower_bound
unknown_timeout
invalid_state
```

## Data and generated files

Generated lookup tables should go under:

```text
data/generated/
```

Benchmark outputs should go under:

```text
results/raw/
results/processed/
```

Thesis figures and tables should go under:

```text
thesis/figures/
thesis/tables/
```

## Correctness strategy

1. Keep the direct cubie representation as the correctness oracle.
2. Verify all moves using tests.
3. Add coordinate representation and cross-check it against direct moves.
4. Generate move tables from the direct move implementation.
5. Keep independent solution verification separate from solvers.
6. Cross-check solvers on shallow states.
7. Use BFS on shallow depths as ground truth.
8. Add performance optimization only after correctness is proven.

## Performance strategy

- Use compact integer coordinates for search-heavy modules.
- Cache or persist move/pruning tables.
- Provide quick benchmark mode for reproducibility checks.
- Provide thesis benchmark mode for final reported data.
- Report timeouts honestly.
- Keep table-generation metadata so results can be audited later.

## Solver architecture

Required solver modules:

- `solvers/kociemba.py`: native two-phase implementation;
- `solvers/thistlethwaite.py`: native subgroup-chain implementation;
- `solvers/korf.py`: IDA* with admissible table heuristic;
- `solvers/pocket_cube.py`: complete 2x2x2 optimal solver or bridge to `pocket/`.

External solvers may exist only as comparison adapters. They do not satisfy native implementation requirements.

## Thesis alignment

The code architecture should map cleanly to thesis chapters:

- cube representation chapter: `cube.py`, `moves.py`, `validity.py`;
- coordinate/table chapter: `coordinates/`, `tables/`;
- search background chapter: `search/`;
- algorithm chapter: `solvers/`, `pocket/`;
- experimental chapter: `benchmark.py`, `scripts/run_benchmarks.py`;
- reproducibility appendix: `REPRODUCIBILITY.md`.

