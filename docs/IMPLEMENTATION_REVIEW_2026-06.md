# Implementation Review & Audit — Rubik Optimal Thesis

**Date:** 2026-06-08
**Method:** 14-dimension adversarial audit (49 agents, every critical/high/correctness/honesty
finding independently re-verified by a second agent that re-read the code and ran bounded checks).
**Stance:** Assume nothing is correct; verify by reading *and* running.

Raw machine output: workflow `wf_fa27b9bf-815`. 66 raw findings → 34 confirmed/partial, 1 refuted,
31 low-severity.

---

## 0. Verdict in one paragraph

The **foundations are genuinely solid and honest**: the cubie model, the 18 HTM moves, the
validity/parity checks, the verifier, the coordinate encodings, the move/pruning tables, and — crucially
for requirement #3 — the **admissible heuristics (corner PDB exact over 88,179,840 states, eight 6-edge
PDBs, and a correctly *disjoint* additive cost-partitioned edge PDB)** are all verified correct against
exact BFS. Solver outputs are honestly labelled `non_exact`; no solver falsely claims optimality. **However**,
the student's own three required algorithms are weak where it matters: **Thistlethwaite times out on most
states deeper than ~10 moves and delegates 9/13 corpus cases to a Kociemba phase-2 fallback**;
**Kociemba returns the first solving candidate instead of minimizing total length** (leaving verified
shorter solutions on the table); and the **Python "Korf" is a toy capped at depth 8 / 500k nodes** — real
optimality is offloaded to a native C++ solver and, by default, to a **vendored GPL-3.0 `nissy` backend
statically linked into the student's own `optimal_solver.cpp`** (an undisclosed combined-work copyleft
obligation). Surrounding this core is **massive scope creep** (~13k lines of AWS/cloud scripts, a
5,533-line `oracle.py`, ~7 GB of cloud result artifacts, ~63% of the 558 tests defending scaffolding) that
is unrelated to the brief's "run on a conventional computer" framing. Finally, **the repo has zero git
commits and a 40 GB pile of garbage temp packs** — no provenance baseline at all.

---

## 1. What is verified CORRECT (do not "fix")

- **Cube model / moves / validity / verifier** (`cube.py`, `moves.py`, `validity.py`, `verify.py`,
  `scramble.py`): all 18 HTM moves are correct permutations (order checks, inverse round-trips, superflip
  reproduction, cross-checked vs the `kociemba` URFDLB reference); `verify_physical` accepts solvable and
  rejects each unsolvable class; verifier and `move_count` are genuinely independent of the solvers.
- **Coordinates & tables** (`coordinates/*`, `tables/move_tables.py`, `pruning_tables.py`): encode/decode
  bijective over full domains; move tables match real cube application over their *entire* domains; pruning
  tables equal exact coordinate-space BFS; regeneration is byte-identical (deterministic); checksums are
  really computed, not hardcoded. **Strongest area in the repo.**
- **Heuristic admissibility** (`search/heuristics.py`, `tables/corner_pdb.py`, `tables/edge_pdb.py`):
  every component (misplaced-cubie, coordinate-pruning, corner PDB, edge PDBs, additive CPDB) is `≤` exact
  BFS distance on shallow states. The **additive partition is disjoint and unit-sum — the classic additive-PDB
  double-count bug is absent.** Combined IDA* bound uses `max` over overlapping PDBs (admissible). **This
  satisfies the spirit of requirement #3's "suitable heuristic."**
- **Korf/IDA\* correctness on shallow states**: `solve_korf_ida` length == exact BFS distance where it
  completes; IDA* logic is sound (it is only *capped*, not wrong).
- **Native C++ cube model is byte-identical to the Python model** (a PDB built in C++ is valid for Python).
- **2×2×2 pocket cube**: full 3,674,160-state distribution proof, max depth 11 — a genuine complete result.
- **External wrappers are framed as baselines, not original work** (framing is honest; specific
  *attribution* entries are missing — see P1).

---

## 2. Prioritized fix list

### P0 — Blockers (required-algorithm correctness, integrity, provenance)

| # | Finding | Location | Fix |
|---|---------|----------|-----|
| P0-1 | **Thistlethwaite times out on deep (≥10-move) states**; uses bounded IDA* over raw cubies instead of coset/pruning distance tables; `stage2_max_depth=8` makes some states structurally unreachable; 9/13 corpus cases actually solved by a Kociemba phase-2 fallback. | `solvers/thistlethwaite.py:496-853` | Build **BFS-generated coset/pruning distance tables per phase** (G0→G1 EO 2048; G1→G2 combined CO×UDslice; G2→G3 over the 96/6912 projections; G3→I square-group BFS). Then each phase is a fast IDA* that always terminates — real Thistlethwaite, no Kociemba fallback. Remove the depth-8 cap. |
| P0-2 | **Kociemba does not minimize total length** — returns the first solving candidate; verified shorter solutions exist (demonstrated: returns 17 where 15 is achievable). | `solvers/kociemba.py:559-599` | Iterate all ranked phase-1 candidates, compute verified `len(phase1)+len(phase2)`, keep the minimum; prune by `phase1_len + phase2_lb ≥ best`. Optionally deepen phase-1 collection. Keep `non_exact` label. |
| P0-3 | **GPL-3.0 nissy is statically linked into the student's `optimal_solver.cpp`** (combined/derivative work), **on by default** via `native_korf_upper_bound_proof_nissy_heuristic=True`, and the copyleft/linking implication is undisclosed. | `optimal_native.py:26-92`, `native/optimal_solver/nissy_bridge.c`, `optimal_solver.cpp:24-26,605-609`, `oracle.py:149/226/3154` | Decide handling (see decision Q2). Minimum: document the combined-work obligation in `THIRD_PARTY_NOTICES.md`, **flip the default to False**, and either process-isolate (like `h48_backend.c`) or exclude the nissy-linked binary from distribution. |
| P0-4 | **Zero git commits + 40 GB of garbage `tmp_pack_*` files**; no provenance baseline; artifacts stamped `no_commit+dirty`. | `.git/objects` (616 garbage packs, 40.46 GiB) | Delete garbage packs, `git gc --prune=now`, create a real initial commit baseline, regenerate metadata so `source_state` references a real SHA. (Destructive — see decision Q3.) |

### P1 — Important (correctness / honesty / contract gaps)

| # | Finding | Location | Fix |
|---|---------|----------|-----|
| P1-1 | Thistlethwaite **`timeout_seconds` is not a hard wall** (5 s request ran 24 s; inner phase-2/IDA* checks the clock too rarely at deep `max_depth`). | `thistlethwaite.py:424,455-463,664-674`; `kociemba.py:362-478`; `search/ida_star.py` | Thread one absolute deadline through all inner searches; check the clock at the top of each recursive entry (or every N nodes). Add a regression test (`T+0.5s` bound). |
| P1-2 | **Distance recognition default path can never emit `unknown_timeout`** — a timed-out IDA* is mislabelled `lower_bound`, breaking the advertised 4-category contract. | `distance.py:119-136` | Branch on `ida.status`: `timeout` → `unknown_timeout`; completed depth-bound → `lower_bound` with distinct wording. Add a default-path timeout test. |
| P1-3 | **Python `solve_korf_ida` toy-cap (depth 8 / 500k nodes) is invisible at point of use** — `--solver korf` gives no hint that deep states need the native/H48 path. | `solvers/korf.py:17-23`, `cli.py:1162-1163` | Add notes on `lower_bound`/`timeout` outcomes pointing to `--solver optimal-native`; add a module docstring; ensure thesis presents native C++ PDB IDA* as the requirement-#3 answer. |
| P1-4 | **Native optimal "exact" correctness is never genuinely tested** — the two `test_optimal_native.py` tests mock `subprocess.run` to a hardcoded `status:"exact"` payload; only one real depth-3 case exists (silent-return-gated). | `tests/test_optimal_native.py:22-137`; `tests/test_search_and_solvers.py:157-189` | Rename the mock tests `*_cli_argument_forwarding`; add a real test running `solve_korf_native_optimal` on BFS-checkable scrambles asserting `length == exact_distance_bfs`; use `pytest.skip` not bare `return`. |
| P1-5 | **No randomized BFS-exact equivalence test for Korf/IDA\*** — optimality (the thesis's central guarantee) is only spot-checked on 2–3 move fixed sequences; a heuristic-inadmissibility regression would pass all tests. | `tests/test_search_and_solvers.py:96-167` | Add a fixed-seed parametrized test: ~30–50 scrambles len 1–7, assert `solve_korf_ida(...).solution_length == exact_distance_bfs(...)` and `ida_star_solve(...)` likewise. |
| P1-6 | **`exact_certificate` revalidation proves only an upper bound**; optimality is inherited from the source solver's `exact` flag, not re-proven (doc gap — contained, since `distance.py` doesn't use the store). | `exact_certificates.py:1,69,254-279`; `verify.py:18-29` | Document the upper-bound/inherited-optimality distinction in the module/class docstrings and any thesis text citing "revalidated exact certificates". Optionally add a BFS cross-check test. |
| P1-7 | **pip `kociemba` (declared dependency, GPLv2) is absent from `THIRD_PARTY_NOTICES.md`** while every other external component is documented. | `THIRD_PARTY_NOTICES.md`, `pyproject.toml:13` | Add an entry: package `kociemba` v1.2.1, author muodov, GPLv2, used only via `solve_kociemba_adapter` as a non-exact baseline; add to the supervisor-approval redistribution list. |
| P1-8 | **Vendored GPL-3.0 `nissy_core` (61 files) is in-tree while the repo declares no project-wide license** — internally inconsistent for any public release. | `native/h48_backend/third_party/nissy_core/`, `LICENSE`, `THIRD_PARTY_NOTICES.md` | Before any public push: declare a GPL-compatible license for the native subtree, or fetch nissy via a pinned submodule/script; convert the "Supervisor Approval Required" note into a blocking release gate. |
| P1-9 | **README status line is stale**: "112 pages / 31,961 words / 273 files" vs the cited audit JSON's actual **114 / 32,742 / 274**. | `README.md:43` | Update to current values; ideally generate the sentence from `thesis_audit.json`. |
| P1-10 | **Thesis says "four 6-edge PDBs"** in one chapter, contradicting "eight" everywhere else and the code/artifact (`edge_pdb_subset_count=8`). | `thesis/chapters/05_system_design.tex:41` | Change to "οι οκτώ 6-edge PDBs". |

**P1 low-confirmed (smaller correctness/honesty items):**
- Korf move-pruning omits canonical opposite-face ordering (U/D, R/L, F/B commute) — misses a sound speedup. (`ida_star`/`korf`)
- CLI `--solver korf` ignores user `node_limit`, silently uses 500k. (`cli.py`)
- `ida_star_solve` enforces the node limit on `expanded` only — generated-node blow-ups unbounded between expansions.
- `recognize_distance` `invalid_state` check is only reachable for raw-constructor cubes (facelet-string validation happens upstream).
- Phase-2 LB ranking noisy (doesn't enforce orientation membership at ranking time).
- `seed`/`profile` parameters don't affect coordinate-table content but are presented as randomization controls — clarify.
- `optimal_solver.cpp` header omits attribution for the GPL nissy heuristic it can link.

### P2 — Scope / bloat (remove, quarantine, or reorganize)

| # | Finding | Scale | Fix |
|---|---------|-------|-----|
| P2-1 | AWS/cloud/fasttarget provisioning & remote-proof scripts — unrelated to the brief; the AWS path is already abandoned/non-AWS. | 15 files, **13,263 lines** (~30% of `scripts/`) + 12 orphaned `cloud_hardtail_campaign_plan_*.tex` (never `\input`). | Move to `scripts/experimental/` (or delete the abandoned AWS path); move the orphaned `.tex`. |
| P2-2 | `oracle.py` bundles 5 layered oracle classes (Fast→Race→ResidentRace→Portfolio→Universal). | **5,533 lines**. | **Reorganize, don't blanket-delete**: the resident-race path *is* cited (`05_experiments.tex:306`). Split into a thesis-core module (Fast, Portfolio, resident) + a clearly-labelled optional research harness; add a class→table map. |
| P2-3 | ~7 GB of cloud/fasttarget result JSON (258/403 processed files) not cited by any thesis table. | ~7 GB | Archive out of the thesis artifact gate; keep only files cited by `\input` tables. |
| P2-4 | ~63% of 558 tests defend cloud/oracle/runtime plumbing; portfolio/native "exact" tests assert on mocked payloads. | ~13,450 test lines | Split `tests/thesis_core/` vs `tests/infrastructure/`; keep the core gate small; move cloud tests with the cloud scripts. |
| P2-5 | `generate_h48_oracle_contract.py` — a 7,419-line generator producing an "all-state oracle contract" for an oracle that cannot cover all states. | 1 file, 7,419 lines | Trim to only checks whose tables are `\input`; rename away from "all-state". |
| P2-6 | Public API (`__init__.py __all__`) exposes oracle plumbing but **none of the three required algorithms**. | — | Add `solve_thistlethwaite` / `solve_kociemba` / `solve_korf` (+ native/distance) to `__all__`; demote internal Race/ResidentRace unless cited. |
| P2-7 | README "Final Verification Commands" is a 39-command, >4,000 s, multi-GiB block presented as the acceptance gate for a "conventional computer". | — | Relabel as "full regeneration (multi-hour, heavy RAM/disk)"; promote the existing quick subset as the conventional-machine gate. |
| P2-8 | `.gitignore` misses 3.6 GB of split table parts (`*.bin.part0000N` not matched by `*.bin`). | 3.6 GB | Add `*.bin.part*`. |

### P3 — Polish / hygiene

- `validity.py` is a redundant one-line wrapper of `is_valid` — pick a single source of truth.
- Chapter source filenames have duplicate numeric prefixes (rendered TOC is fine) — rename to reading order.
- Tests use bare `return` instead of `pytest.skip()` for unmet preconditions → silent green.
- Coordinate unit tests sample only 3 coordinates per spec; one test joins an absolute path to `tmp_path`.
- No build manifest/checksum for native corner/edge PDB generators (only h48 has one).
- Root-package shim works only from repo root (CWD-dependent) — prefer `pip install -e .` / `PYTHONPATH=src`.
- Native Kociemba tables recomputed in-memory (~184 s) per process instead of loaded from `data/generated`.
- **Prolog track absent** — *optional* under the brief ("Python ή/και Prolog"); note only, not a defect.

---

## 3. Requirements-coverage scorecard

| Brief requirement | Status | Note |
|---|---|---|
| Thistlethwaite implemented | **Partial** | Correct on shallow states; times out / falls back on deep states (P0-1). |
| Kociemba implemented | **Partial** | Correct two-phase + honest; but not length-minimizing (P0-2); leans on pip `kociemba` as a baseline. |
| Korf implemented (optimal) | **Partial** | Heuristic & IDA* correct; Python path capped to a toy; true optimality via native C++ (+ GPL nissy by default). |
| Distance recognition | **Mostly met** | Works; default path can't emit `unknown_timeout` (P1-2); defaults to shallow depth. |
| Suitable admissible heuristic for A\*/IDA\* | **Met** | Corner+edge PDBs + additive CPDB, all verified admissible. |
| Half-turn metric throughout | **Met** | Verified. |
| Prolog | n/a | Optional; absent. |
