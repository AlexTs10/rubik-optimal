# Implementation Specification

This file defines the expected implementation behavior for the delivered thesis. It supersedes the earlier scaffold-oriented implementation target.

## Metric

Use face-turn / half-turn metric.

Each of the following counts as one move:

```text
U U' U2 D D' D2 L L' L2 R R' R2 F F' F2 B B' B2
```

## 3x3 cube representation

Use cubie-level representation.

A 3x3 cube state must track:

- corner permutation;
- corner orientation;
- edge permutation;
- edge orientation.

The implementation must verify physical validity:

- all pieces exist exactly once;
- corner orientation sum is valid;
- edge orientation sum is valid;
- permutation parity constraints are valid.

Required tests:

- identity remains solved;
- each move has an inverse;
- applying a quarter turn four times returns identity;
- applying a half turn twice returns identity;
- applying `U U` equals `U2`;
- scramble followed by inverse sequence returns solved;
- invalid cubie states are rejected.

## Coordinate layer

The final implementation must include a coordinate layer suitable for table-driven search.

Required coordinates:

- corner orientation;
- edge orientation;
- corner permutation;
- edge permutation or phase-specific permutation coordinates;
- UD-slice coordinate;
- Kociemba phase coordinates;
- Thistlethwaite stage coordinates or equivalent subgroup-state encodings.

Required behavior:

- coordinate encode/decode roundtrip tests where feasible;
- move tables generated from direct cubie moves;
- table metadata saved with size, generation time, version, profile, and checksum;
- generated tables reproducible from scripts.

The thesis must explain the coordinate definitions and why they reduce the search problem.

## Search foundations

Implement BFS for shallow depths.

Use BFS to:

- verify exact distances for shallow states;
- test heuristic admissibility;
- cross-check solver outputs;
- create small benchmark instances;
- generate explanatory figures/tables for the thesis.

## Native Thistlethwaite-style solver

The final thesis target requires an in-repo subgroup-chain implementation.

Required:

- explicit subgroup chain and stage goals;
- allowed move set per stage;
- stage-specific search or table lookup;
- transition from each stage to the next;
- full solution reconstruction;
- independent solution verification;
- benchmark rows for non-trivial scrambles.

Required thesis behavior:

- explain subgroup progression;
- report stage lengths and runtime;
- distinguish stage-wise practical solving from global optimality;
- discuss where the implementation simplifies the historical method, if it does.

Not acceptable as final:

- only discussing Thistlethwaite in literature;
- returning `not_applicable` for most non-solved benchmark cases.

## Native Kociemba-style solver

The final thesis target requires an in-repo two-phase implementation. The optional external adapter can remain only as a comparison baseline.

Required:

- phase 1 goal: reach the standard restricted subgroup using orientation and slice-related coordinates;
- phase 2 goal: solve inside the restricted subgroup;
- phase-specific move tables;
- pruning tables;
- deterministic generation or verified checked-in generated data;
- solution reconstruction;
- independent verification;
- runtime, expanded-node, and table-size reporting.

Required thesis behavior:

- distinguish practical two-phase solving from proven global optimality;
- compare solution lengths and runtime against Thistlethwaite, Korf/IDA*, and baseline search;
- explain pruning-table construction and admissibility limits.

Not acceptable as final:

- relying only on a library call such as `kociemba.solve(...)`;
- calling two-phase output globally optimal without exact proof.

## Korf / IDA* optimal solver

Implement IDA* with an admissible heuristic.

Required:

- iterative deepening by cost bound;
- non-trivial admissible heuristic;
- generated table-based heuristic or pattern database, including the native 3x3 corner and edge PDBs when available;
- exact result when search completes;
- timeout status when infeasible;
- lower-bound status when only heuristic evidence is available;
- shallow BFS validation of heuristic admissibility.

Required thesis behavior:

- exact optimality only for completed cases;
- explain computational limits for arbitrary 3x3 states;
- compare trivial heuristic, simple cubie heuristic, and table-based heuristic where feasible.

## Pattern databases and table heuristics

At least one table-based admissible heuristic must be implemented for the delivered thesis.

Document:

- abstraction used;
- state count;
- generation algorithm;
- memory size;
- build time;
- admissibility argument;
- how it is combined with other heuristics;
- where it is weaker than full Korf-style databases.

The current delivered direction is to use native binary 3x3 corner and 6-edge pattern databases as the substantial PDB layer, while treating additive/cost-partitioned combinations, symmetry reduction, and larger stress coverage as the next scope increase. The complete 2x2x2 case study remains a supporting exhaustive example, not a replacement for the 3x3 Korf track.

## Complete 2x2x2/Pocket Cube case study

Required if full arbitrary-state optimal 3x3 solving remains computationally limited.

Required:

- state representation;
- legal moves under the same metric convention;
- full or justified canonical state enumeration;
- complete optimal-distance computation;
- distance distribution;
- representative optimal solutions;
- generated figures/tables;
- tests against known identities and inverse sequences.

Thesis purpose:

- demonstrate complete optimal search at a feasible scale;
- provide a concrete bridge to pattern databases and IDA*;
- avoid pretending that complete 2x2 optimality proves arbitrary 3x3 optimality.

## Distance recognition

Implement command:

```bash
python -m rubik_optimal.cli distance ...
```

It must return one of:

```text
exact_distance
lower_bound
unknown_timeout
invalid_state
```

Rules:

- BFS can report exact distance for shallow states.
- IDA* can report exact distance if it proves optimality.
- The H48 native backend can report exact distance when `--h48-native` completes and the returned solution verifies from the input state.
- Pattern databases can report lower bounds.
- Timeout must not be converted into a guessed distance.

## Solver verification

Every solver result must be checked by an independent verifier.

Verifier must:

1. start from the input state;
2. apply solver moves;
3. confirm solved state;
4. compute move count under half-turn metric;
5. report pass/fail.

## Error handling

Invalid cube states must be rejected clearly.

Invalid move notation must produce a clear error.

Timeouts must be reported as timeouts, not crashes.

## Generated data policy

All generated tables, benchmarks, figures, and thesis tables must be reproducible.

Required metadata for generated artifacts:

- generator script;
- profile;
- seed/configuration;
- timestamp;
- source commit or dirty-tree marker, if available;
- checksum;
- runtime;
- environment notes where relevant.
