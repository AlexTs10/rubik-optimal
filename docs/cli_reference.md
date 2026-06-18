# CLI Reference

This document is the operational reference for the `rubik-optimal` command-line
interface. The thesis PDF keeps only the academic summary of the interface; this
file is where command usage, options, and reproduction-oriented details belong.

## Entrypoints

After installing the package in editable mode, both entrypoints resolve to the
same CLI implementation:

```bash
rubik-optimal --help
python -m rubik_optimal.cli --help
```

From a raw checkout without installation, use `PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 -m rubik_optimal.cli --help
```

## Commands

| Command | Purpose |
| --- | --- |
| `scramble` | Generate a deterministic HTM scramble from a seed. |
| `facelets` | Generate a valid 54-character facelet string from a deterministic scramble. |
| `solve` | Solve a scramble or facelet state with a selected solver. |
| `verify` | Re-apply a proposed solution to a state and report whether it solves the cube. |
| `distance` | Report an exact distance when proved, otherwise a lower bound or timeout-style result. |
| `oracle` | Solve many states with the H48 oracle path, reusing table loading where possible. |
| `benchmark` | Run a configured benchmark profile and print generated artifact paths. |
| `tables` | Generate coordinate move/pruning tables for a configured profile. |

The exact option set is best checked with `--help`, because the CLI is part of
the implementation and can evolve faster than the thesis text.

## Common Usage

Generate deterministic inputs:

```bash
rubik-optimal scramble --length 20 --seed 2026
rubik-optimal facelets --length 20 --seed 2026 --offset 3 --json
```

Solve and verify:

```bash
rubik-optimal solve "R U R' U'" --solver auto --timeout 5
rubik-optimal verify "R U R' U'" "U R U' R'"
```

Distance recognition:

```bash
rubik-optimal distance "R U R' U'" --bfs-depth 5 --ida-depth 10
rubik-optimal distance solved --optimal-native --timeout 30
```

Batch/oracle style usage:

```bash
rubik-optimal oracle solved "R U R' U'" --timeout 300 --threads 8
rubik-optimal oracle --input-file states.txt --jsonl --trusted-table
rubik-optimal oracle --stream --input-file states.txt --trusted-table
```

## Solver Selection

The `solve` command accepts practical solvers, exact/native solvers, external
reference engines, and portfolio-style orchestration. The important thesis
boundary is semantic, not syntactic:

- `exact` rows are only valid when the selected backend completed an admissible
  proof and the returned solution verified.
- `non_exact` rows may be useful practical solutions but are not optimality
  claims.
- `lower_bound` rows prove only that no shorter solution exists below the
  reported bound.
- `timeout` rows prove no distance claim.

Common solver names include:

| Family | Names |
| --- | --- |
| Practical/local | `auto`, `native-kociemba`, `thistlethwaite`, `korf`, `bfs`, `inverse` |
| Adapter/baseline | `kociemba`, `adapter` |
| Exact/native | `optimal-native`, `h48-native`, `h48-oracle`, `nissy-core-direct` |
| External exact | `nissy-light`, `nissy-optimal`, `rubikoptimal` |
| Portfolio | `race-optimal`, `resident-race-optimal`, `universal-optimal` |

## H48 Options

The H48-related options appear on `solve`, `distance`, and `oracle` where
applicable. The main options are:

| Option | Purpose |
| --- | --- |
| `--h48-solver` | Select the H48 table level, such as `h48h0` or `h48h7`. |
| `--h48-oracle` | Select the oracle-grade H48 path used for exact rows. |
| `--h48-fastest` | Select the largest available generated oracle-grade table for the profile. |
| `--h48-trusted-table` | Skip repeated full-table validation only after generated/checksummed metadata has identified the table. |
| `--h48-preload-table` | Warm the table pages before search, useful for hard certification runs. |
| `--h48-auto-min-depth` | Start exact search from the admissible H48 lower bound. |
| `--h48-profile` | Select the table profile, normally `quick`, `thesis`, or `stress`. |
| `--h48-table` | Explicitly provide a table file path. |

Use trusted-table mode only for tables whose metadata and checksum have been
validated. The thesis treats the retained `h48h7` table as an explicitly adopted
artifact, not as a byte-for-byte regenerated claim.

## Benchmark And Table Profiles

The repository uses three profile names consistently:

| Profile | Use |
| --- | --- |
| `quick` | Fast development and laptop sanity checks. Not a thesis evidence source. |
| `thesis` | Canonical thesis evidence profile with seed `2026`. |
| `stress` | Deeper or harder cases used for supplementary pressure evidence. |

Typical lightweight check:

```bash
python -m pytest -q
rubik-optimal --help
python scripts/run_benchmarks.py --profile quick --seed 2026
python scripts/verify_results.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
```

The full regeneration sequence is intentionally kept in `REPRODUCIBILITY.md`
because it is long, machine-sensitive, and includes multi-GiB artifacts.

## Result Semantics

CLI output for solving/search commands keeps verification and optimality
separate:

| Field/status | Meaning |
| --- | --- |
| `verified=true` | The proposed move sequence solves the input state under the independent verifier. |
| `exact` | The solution is proven optimal for that row. |
| `non_exact` | The solution is verified but not proven optimal. |
| `lower_bound` | A lower bound was proven; no exact solution claim is made by that row. |
| `timeout` | A resource limit stopped the search. |
| `not_applicable` | The solver is unavailable or unsupported for the case. |
| `failed` | The run failed and cannot support a thesis claim. |

These meanings are the same ones used in the thesis appendices and generated
tables.
