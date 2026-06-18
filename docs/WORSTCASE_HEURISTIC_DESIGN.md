# Design & Handoff: making worst-case (depth 18–20) optimal solving tractable

**Status:** design + handoff for a *focused follow-up effort*.
**Baseline commit:** `a57fa81` (`.git` clean, 9.3 MB). Full suite: **294 passed / 14 skipped / 0 failed**.
**Owner of this note:** the audit + remediation session (2026-06-08).

This document exists so a new, clean session can pick up the *one remaining optional* goal —
optimally solving the hardest depth-18–20 states (e.g. the superflip) on a conventional laptop —
without re-deriving context or repeating a dead end we already measured.

---

## 0. UPDATE (2026-06-09): Path 1 and Path 3 were built + measured

A follow-up session implemented **Path 1 (7-edge PDB)** and **Path 3 (two-phase-to-optimal)** end to
end, each behind its own mandatory §5 gate. Both are correct, admissible, and regression-free
(full suite `314 passed / 14 skipped`). The measured outcomes **revise the optimistic estimates below**:

- **Path 1 measured (`results/processed/seven_edge_strength_seed_2026.json`):** a complete 7-edge PDB
  maxes at distance **11** (not the ~13 estimated in §3), and on the **superflip it gives h = 8 —
  identical to the 6-edge (gain +0)**. Flipping 7 in-place edges costs the same 8 moves as 6 within the
  projection; the extra max (11) is realized only on permutation-scrambled states, never the pure-
  orientation superflip. Mean gain on random deep states is **+0.50** (occasional +1). So Path 1 is a
  real but modest win for *typical* hard states and **does not help the superflip at all** — a stronger
  negative result than §3's "likely not enough alone". Implementation: `native/edge_pdb/edge_pdb.cpp`
  (subset size 6 or 7; 6-edge output proven byte-identical to the original), `tables/edge_pdb.py`,
  `optimal_solver.cpp` (7-edge hot path + `--emit-edge-coords` cross-check), `search/heuristics.py`,
  `solvers/optimal_native.py`; gate `tests/test_seven_edge_heuristic.py`.
- **Path 3 built (`src/rubik_optimal/solvers/kociemba_optimal.py`, `solve_kociemba_two_phase_optimal`):**
  provably optimal via subgroup decomposition (G1 closure ⇒ every solution = phase-1 maneuver + phase-2
  maneuver of equal length; enumerate phase-1 by depth, optimal phase-2 per reachable G1 state, stop when
  `d ≥ best`). It NEVER claims `exact` unless optimality is proven within budget. **Honest tractability:**
  pure-Python iterated two-phase proves optimality for depth ≤ ~12 (seconds–~30 s) and is an independent
  optimal cross-check for the native Korf solver, but it is **slower than native Korf and does not extend
  the depth frontier**; on depth-14 within 60 s it correctly returns a verified non-optimal solution
  rather than over-claiming. It does **not** crack the depth-20 superflip quickly — the outer loop would
  need `d ≥ 20`, i.e. ~13.3²⁰ phase-1 maneuvers. Gate `tests/test_kociemba_optimal.py`.

**Net conclusion for the worst case:** neither Path 1 nor a pure-Python Path 3 makes the depth-20
superflip tractable. The remaining real levers are **Path 2 (symmetry reduction, in native code)** — the
superflip is invariant under all 48 symmetries, so this is the technique that actually tames it — or the
already-in-place **Path 4 (isolated H48/nissy oracle)**, which already certifies the superflip optimal at
length 20. A future session wanting a fast *own-code* superflip solve should pursue Path 2 (heeding its
high silent-inadmissibility risk and the §5 gate), ideally as native symmetry-reduced coordinates feeding
either the Korf engine or a native two-phase optimal driver.

## 0.1. UPDATE (2026-06-09): Path 2 root-stabilizer pruning started

A first exact-safe slice of **Path 2** is now implemented in the student's own native Korf path:
`src/rubik_optimal/symmetry.py` computes the 24 proper whole-cube rotations that stabilize the input
state and collapses first moves into one representative per stabilizer orbit; `solve_korf_native_optimal`
can pass that caller-certified mask to `native/optimal_solver/optimal_solver.cpp` via
`--root-move-mask`. For the canonical superflip the current 24-rotation stabilizer reduces first-move
representatives from 18 to **3** (`U`, `U'`, `U2`). On a shallow symmetric state (`U2 D2`) the native
solver still matches BFS exactly with the mask enabled. On bounded superflip probes, the compiled native
engine reports:

- `max_depth=10`: generated nodes **1872 -> 354**, `root_move_count=3`, still `lower_bound`;
- `max_depth=12`: generated nodes **170682 -> 36651**, `root_move_count=3`, still `lower_bound`
  with `final_bound=13`.
- `max_depth=20`, 8 threads, 60 s timeout: **timeout**, `final_bound=17`, `expanded_nodes=77577392`,
  `generated_nodes=1036298958`, `root_move_count=3`, no solution returned.

This is real own-code symmetry pruning, but it is **not yet the requested fast proven-optimal superflip
solve**. It uses the repository's existing 24 proper rotations, not the full 48 rotational/reflection
symmetry group described above, and it prunes only the root. The deeper symmetry-aware transposition
follow-up is recorded in §0.2; the remaining gap is still too large without stronger symmetry-reduced
coordinates, a stronger admissible heuristic, or a native phase/coset proof strategy.

## 0.2. UPDATE (2026-06-09): Native rotational symmetry transposition table measured

The next Path 2 slice adds an opt-in exact-safe rotational canonicalization for native Korf transposition
keys, still without H48/Nissy. `native/optimal_solver/optimal_solver.cpp` now builds the same 24 proper
whole-cube rotations from sticker geometry, rotates cubie states natively, maps `last_face` through the
rotation, and stores the lexicographically smallest rotated transposition key when
`--symmetry-transpositions` is enabled. Because the solver's opposite-face ordering prune depends on
numeric face order and is not invariant under arbitrary rotations, that mode disables only the
opposite-face ordering prune while keeping the same-face prune. The Python wrapper exposes this as
`solve_korf_native_optimal(..., symmetry_transpositions=True)` and records
`symmetry_transpositions`/`symmetry_rotation_count` in result notes.

The correctness gate passed on 2026-06-09: native compilation succeeded; Python py-compile passed for the
wrapper/tests; `PYTHONPATH=src python -m pytest tests/test_symmetry.py tests/test_optimal_native.py
tests/test_seven_edge_heuristic.py -q` reported **29 passed in 68.61 s** after the invariant-tree fix.
The new native tests compare
symmetry-transposition solving against BFS on shallow scrambles while also exercising root pruning.

Measured superflip probes with 8 threads, split depth 3, root symmetry pruning, and 7-edge PDBs:

- 20 s, 1M ordinary exact transposition entries: **timeout**, `final_bound=16`,
  `expanded_nodes=14634206`, `generated_nodes=195607062`, `tt_hits=1235`.
- 20 s, 1M rotational canonical transposition entries: **timeout**, `final_bound=16`,
  `expanded_nodes=12349271`, `generated_nodes=185238957`, `tt_hits=348093`.
- 60 s, 1M rotational canonical transposition entries: **timeout**, `final_bound=16`,
  `expanded_nodes=39204427`, `generated_nodes=588066297`, `tt_hits=399551`, no solution.
- 20 s, 8M ordinary exact transposition entries: **timeout**, `final_bound=16`,
  `expanded_nodes=12793188`, `generated_nodes=171020316`, `tt_hits=6086`.
- 20 s, 8M rotational canonical transposition entries: **timeout**, `final_bound=16`,
  `expanded_nodes=10280895`, `generated_nodes=154213317`, `tt_hits=1264110`, no capacity skips.

The result is important but negative for the hardest-state goal: the canonical rotational table is active
and exact-safe, and it reduces generated nodes in the corrected probes, but it still does **not** create a
fast own-code proof of the superflip distance. More table capacity and 24-rotation canonicalization both
help locally, yet every run above remains stuck at `final_bound=16`. The next useful Path 2 step is no
longer a shallow root mask or ordinary transposition-key canonicalization; it must be a true
symmetry-reduced coordinate/heuristic or phase/coset proof layer. The later §0.3 full-48 measurement
removes the orientation-reversing half as a missing prerequisite but still leaves the §5 harness mandatory.

## 0.3. UPDATE (2026-06-09): Larger edge-projection probe identifies the first useful PDB target

The small orientation projections were checked before more native code was added:

- 12-edge orientation only: complete 2048-state BFS, superflip projection distance **7**.
- corner-orientation x edge-orientation: complete 4,478,976-state BFS, superflip projection distance
  **8**.
- edge-orientation x UD-slice: complete 1,013,760-state BFS, superflip projection distance **8**.

So the missing worst-case signal is not just "more orientation"; the heuristic must see enough edge
identity/permutation restoration. To find the next viable target without building multi-GB tables blindly,
`scripts/probe_edge_projection_distance.py` now runs exact bidirectional BFS in the full edge-subset
projection for a chosen subset and writes reproducible evidence to
`results/processed/edge_projection_superflip_probe_seed_2026.json`. For prefix subsets `(0..N-1)`:

- 6-edge projection: projected superflip distance **7** for that subset
  (`42,577,920` raw states).
- 7-edge projection: projected superflip distance **8** (`510,935,040` raw states).
- 8-edge projection: projected superflip distance **8** (`5,109,350,400` raw states).
- 9-edge projection: projected superflip distance **11** (`40,874,803,200` raw states).

A native sparse bidirectional probe was then added under
`native/edge_projection_probe/edge_projection_probe.cpp` and wired through the same Python script for
larger prefix subsets:

- 9-edge native check: projected distance **11** in `1.22334 s`, matching the Python result
  (`results/processed/edge_projection_superflip_probe_native_check_seed_2026.json`).
- 10-edge native probe: no projected path of length <= 12, so projected distance is **> 12**
  (`245,248,819,200` raw states; `49.2911 s`;
  `results/processed/edge_projection_superflip_probe_native_10_seed_2026.json`).
- 11-edge native probe: no projected path of length <= 12, so projected distance is **> 12**
  (`980,995,276,800` raw states; `78.842 s`;
  `results/processed/edge_projection_superflip_probe_native_11_seed_2026.json`).

The arbitrary prefix subset was then replaced with rotation-orbit representatives, so the next table
choice is not an accident of edge numbering:

- 9-edge has **13** representatives under the repository's 24 proper whole-cube rotations. The native
  orbit sweep found distances **11** or **12** only: distribution `11: 5`, `12: 8`
  (`results/processed/edge_projection_superflip_probe_native_9edge_orbits_seed_2026.json`).
- 10-edge has **5** rotation-orbit representatives. All five are exactly projected distance **13**
  from solved to superflip
  (`results/processed/edge_projection_superflip_probe_native_10edge_orbits_depth13_seed_2026.json`).

This is the first own-code heuristic evidence in this follow-up that raises the superflip lower bound
above 8. It also revises the implementation target: **9-edge is too weak** for the next worst-case push,
while **10-edge is the smallest measured edge-identity projection that gives h = 13** on the superflip.
But a raw 10-edge byte PDB would be about `245,248,819,200` entries, and even a one-bit threshold table is
about 30.7 GB before metadata/frontiers. A direct fixed-subset threshold-table feasibility probe confirms
that this is not a laptop path: the 10-edge solved-side BFS ball reached the 50,000,000-state safety cap
before completing depth 7
(`results/processed/edge_projection_10edge_ball_growth_seed_2026.json`).

The simplest 24-rotation quotient was also measured and is **not enough**. The native probe can now
canonicalize each 10-edge projected state over the repository's 24 proper whole-cube rotations with
`--ball --canonical-rotations`. It completed depth 7, but still needed **47,030,192** quotient states,
with a **43,206,124**-state frontier and **607.726 s** runtime
(`results/processed/edge_projection_10edge_canonical_ball_growth_seed_2026.json`). This is only about a
2x state-count reduction at the measured radius, one layer before the radius that would be needed for a
useful h=13 threshold table. The next implementation target is therefore **not** "generate a raw larger-edge
PDB" and is also **not** the simple 24-rotation quotient alone; it must be a stronger compression/quotient
or a different native phase/coset proof layer that preserves the 10-edge h=13 signal while fitting the
8-core/16 GiB machine. Until such a table or proof layer is generated and wired into native Korf, this is
design evidence, not a completed fast solve.

The formerly missing orientation-reversing half of the cube symmetry group was then implemented and measured. The
Python symmetry layer now exposes the full 48-element whole-cube symmetry group; exact-safe root pruning
collapses the superflip first moves from `U,U',U2` to `U,U2`. The native Korf solver keeps the measured
24-rotation transposition mode and adds `--full-symmetry-transpositions` for all 48 rotations/reflections.
The edge-projection probe also adds `--canonical-full-symmetries`. This halves the 10-edge quotient again
at the measured radius, but it still does **not** make a table viable: depth 7 needs **23,517,154** seen
quotient states with a **21,604,439**-state frontier and **459.908 s** runtime
(`results/processed/edge_projection_10edge_fullsym_ball_growth_seed_2026.json`). On actual native Korf
superflip probes, 20 s root-only / 24-rotation TT / 48-symmetry TT rows all timed out at `final_bound=16`
(`results/processed/native_symmetry_superflip_probe_seed_2026_fullsym20.json`), and a 60 s 48-symmetry TT
probe also timed out at `final_bound=16`
(`results/processed/native_symmetry_superflip_probe_seed_2026_fullsym60.json`). So full 48 symmetry is now
implemented as own code and useful as an exact-safe pruning component, but it is still only a constant-factor
reduction. It does not produce the requested fast own-code proof of superflip distance 20.

## 0.4. UPDATE (2026-06-09): Compact exact TT + upper-bound proof probe

The next native-engine slice removed a practical transposition-table storage bottleneck but still did not
close the superflip. `native/optimal_solver/optimal_solver.cpp` now has opt-in
`--compact-transpositions`, which stores an exact packed key (12-edge permutation rank, all edge
orientations, full corner coordinate, and last-face code) in an open-addressed table. It is not a Bloom
filter and should not introduce false positives. The wrapper exposes
`solve_korf_native_optimal(..., compact_transpositions=True)`, and shallow native/BFS tests now exercise
compact + full-symmetry transpositions.

A new reproducible probe, `scripts/probe_native_superflip_upper_bound.py`, uses the saved verified
length-20 H48 superflip solution only as an upper bound, then asks the student's native Korf engine to
exhaust bound 19. The native JSON flag was tightened so `upper_bound_proof_exhaustive=false` on timeout
rows. The saved artifact is
`results/processed/native_superflip_upper_bound_probe_seed_2026_compact20.json`.

20 s rows with 8 threads, split depth 3, full 48-symmetry transpositions, root symmetry pruning, 7-edge
PDBs, and the verified length-20 upper solution:

- legacy 4M exact TT: **timeout**, `final_bound=19`, `generated_nodes=189,996,617`,
  `tt_capacity_skips=8,497,055`.
- compact 4M exact TT: **timeout**, `final_bound=19`, `generated_nodes=128,369,897`,
  `tt_capacity_skips=4,417,120`.
- compact 32M exact TT: **timeout**, `final_bound=19`, `generated_nodes=98,143,577`,
  `tt_capacity_skips=0`.

So compact TT is a correct optimization and the 32M row removes capacity skips, but all rows still record
`native_optimality_proved=false`. This rejects "make the existing TT bigger/leaner" as the next serious
worst-case lever. Further own-code work should move to a stronger admissible 10-edge quotient/threshold
heuristic or a native phase/coset proof layer, not another simple transposition-storage tweak.

## 0.5. UPDATE (2026-06-09): Native Kociemba phase/coset bridge measured

A focused phase/coset bridge now replaces the slow Python phase-2 search with own-code C++. The new
`native/kociemba_phase2_probe/kociemba_phase2_probe.cpp` builds phase-2 CP, UD-edge, and slice-edge
move/pruning tables at startup and solves only valid Kociemba G1 states with the phase-2 move set. It does
not use H48, Nissy, or a third-party oracle. The wrapper script is
`scripts/probe_native_kociemba_phase2_superflip.py`, with regression coverage in
`tests/test_kociemba_phase2_native_probe.py`.

Saved measurements:

- `results/processed/native_kociemba_phase2_superflip_probe_seed_2026_depth10_exact24.json`: exhaustive
  phase-1 depth 10 collection found 6 handoffs. Native phase 2 solved them exactly with suffix lengths
  13 or 14 in 0.184520-1.293660 s, for total lengths 23 or 24.
- `results/processed/native_kociemba_phase2_superflip_probe_seed_2026_depth11.json`: a 90.121169 s
  Python phase-1 collection sampled 22 handoffs. Every sampled native phase-2 cap row returned
  `lower_bound` for the cap needed to reach total length <= 20, and all 22 native phase-2 cap checks took
  only 0.350161 s total.

The result is useful but still negative for the hardest-state goal. Phase 2 is no longer the immediate
bottleneck for sampled G1 handoffs, but the depth-11 artifact records `phase1_exhaustive=false` and
`artifact_proves_no_solution_at_or_below_target=false`, because Python phase-1 enumeration timed out.
The next serious phase/coset implementation is native phase-1 enumeration or a full native two-phase proof
driver. Until phase-1 handoffs are enumerated exhaustively, this bridge cannot prove superflip distance 20.

That next implementation is now partially built. The same native binary has `--mode two-phase`, which builds
phase-1 CO, EO, and UD-slice combination move/pruning tables, enumerates exact phase-1 depths with the
same canonical same-face/commuting-order restrictions as the Python proof, carries full cubie states to
each G1 handoff, and runs the native phase-2 cap solver immediately. The reproducible wrapper is
`scripts/probe_native_kociemba_two_phase_superflip.py`. The first native frontier run used the full
whole-cube superflip root representatives `U,U2`, but that is too broad for a fixed-UD-axis Kociemba proof:
whole-cube symmetries that move the UD axis preserve ordinary optimality but not the axis-specific phase-1
target. The wrapper now uses the G1-preserving root representatives `U,U2,R,R2`. The native probe also
builds admissible pair pruning tables for phase 1 (`COxEO`, `COxUD-slice`, `EOxUD-slice`) and phase 2
(`CPxslice`, `UD-edgexslice`), and exposes `--no-handoff-dedup`, `--threads`, and `--split-depth`. A later
target-set layer adds a corner-permutation distance-to-phase-2-suffix-ball lower bound. The wrapper still
disables CP target pruning automatically for threaded runs unless `--allow-threaded-cp-target-pruning` is
passed, but the native code now supports explicit threaded read-only target-table sharing. Newer target-set
experiments add cache-patterned combined CP x labeled-UD-slice bounded reverse tables and an opt-in labeled
UD-edge bounded reverse table, both with max-distance guards so the large tables are only consulted at
remaining phase-1 depths where they can actually prune.

Saved frontier measurements:

- Without root symmetry, native two-phase depth 12 completed in 88.4408 s, checked 1,192,960 distinct G1
  handoffs, and every phase-2 cap row returned `lower_bound` for total length <= 20.
- With the corrected G1-preserving root mask and pair pruning,
  `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_depth12_g1rootsym_pair.json`
  completes depth 12 in 0.899044 s and raises the initial phase-1 lower bound to 8.
- `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_depth16_g1rootsym_pair_nodedup_threads8.json`
  finds a verified length-20 superflip solution in 0.66088 s native runtime with 8 threads, no H48/Nissy,
  and no handoff-dedup hash table.
- `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_g1rootsym_pair_nodedup_threads8.json`
  is the strict lower-bound proof attempt: it times out at 600.043 s after completing phase-1 depth 15
  and entering depth 16, with `proves_no_solution_at_or_below_target=false`.
- `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_g1rootsym_pair_cpprune_nodedup_threads1_timeout600.json`
  is the serial CP-target pruning attempt: it prunes 2,311,094,861 phase-1 branches, expands
  4,433,526,784 phase-1 nodes, and still times out after completing depth 15 and entering depth 16.
  The labeled UD-slice target projection pruned zero branches in the 60 s superflip measurement.
- `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_depth16_g1rootsym_pair_cp_cpsliceprune_cachehit_skip_nodedup_threads1_timeout600.json`
  is the cached combined CP x labeled-slice depth-16 measurement. It loads the 457 MiB cap-3 table in
  1.52082 s, records a complete table with max target distance 8, prunes 122,182,461 combined branches,
  reduces handoffs to 2,231,322, and still times out after 600.001 s. Because this row starts at
  `phase1_start_depth=16`, it is partial-depth measurement evidence, not a standalone target-19 proof.
- `results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_depth17_g1rootsym_pair_cp_cpslice_udedgeprune_cache_nodedup_threads8_split3_timeout900.json`
  is the current strongest threaded target-pruning measurement. It enables explicit threaded CP-target
  pruning, cached CP x labeled-slice target pruning, and the new labeled UD-edge target projection. The
  run builds and saves the complete 19 MiB cap-2/depth-17 UD-edge target table in 1.92178 s, records
  `phase1_ud_edge_target_max_distance=7`, prunes 27,382,581 UD-edge branches plus 1,199,973,642 CP x
  slice branches, cuts phase-2 handoffs to 543, and has no phase-2 timeout rows. It still times out after
  901.249 s with `completed_phase1_depth=-1` and `proves_no_solution_at_or_below_target=false`.

So the phase/coset path has advanced from Python's incomplete depth-11 sampling to a fast own-code verified
length-20 superflip solution. It still does **not** prove superflip distance 20: the proof requires
exhausting the target-19 lower-bound query, or adding a stronger admissible phase/coset lower bound,
full-state quotient, or target-set reverse-pruning layer that safely eliminates the remaining phase-1
frontier past depth 15. The measured CP x labeled-slice and labeled UD-edge layers are useful negative
evidence: they are exact-safe and reduce phase-2 handoffs sharply, but they do not eliminate enough of the
phase-1 frontier to close the proof on this 8-core/16 GiB Mac.

## 0.6. UPDATE (2026-06-09): Thesis-scope decision after topic-brief/reference-thesis review

The topic brief states God's Number as background ("20 at most" in HTM) and asks the work to achieve as
many listed objectives as possible: implement Thistlethwaite/Kociemba/Korf, run them on a conventional
computer, recognize distance where an exact method completes, and develop a suitable A*/IDA* heuristic.
It does **not** require this thesis to reproduce the published proof of God's Number or to prove the
superflip lower bound from scratch with the student's own engine.

Therefore the technically precise boundary is:

- a verified length-20 own-code superflip solution proves only `distance <= 20`;
- an own-code claim `distance = 20` would still require proving no solution of length 19 or less;
- the current native target-19 proof attempts do not complete, so that own-code optimality claim remains
  future work;
- the thesis may still cite God's Number/superflip distance 20 from established sources and/or the
  attributed H48/Nissy oracle lane, as long as the H48/Nissy proof is not presented as original
  student-authored algorithmic evidence.

The reference thesis used for calibration has explicit "Περιορισμοί" and "Προτάσεις για Μελλοντικές
Επεκτάσεις" sections, so leaving the native no-19 superflip proof as a future extension is academically
normal when the delivered implementation, measurements, and limitations are concrete. The next thesis
work is claim cleanup and finalization unless the supervisor explicitly requires the optional own-code
hardest-state proof as a condition for review.

## 0.7. UPDATE (2026-06-09): Web-research check for a real 10x local lever

Primary technical sources point to one real algorithmic direction that can plausibly move this Mac by
order-of-magnitude factors: **symmetry-reduced phase/coset pruning**, not another plain Korf edge PDB.

- Kociemba's pruning-table notes use a `FlipUDSlice` symmetry coordinate with 64,430 equivalence classes
  and corner twist to store phase-1 information in 140,908,410 entries with maximum pruning depth 12
  (`https://www.kociemba.org/math/pruning.htm`). Our raw full phase-1 projection is the same
  `CO x EO x UD-slice` domain without the 16-way symmetry reduction: 2,217,093,120 entries.
- Kociemba's optimal-solver notes describe Mike Reid's method: run phase-1-style searches in three axis
  directions and use `max(p1,p2,p3)` as the effective lower bound
  (`https://kociemba.org/math/optimal.htm`). This is a fundamentally stronger local path than only one
  fixed-UD-axis Kociemba target.
- Rokicki/Kociemba/Davidson/Dethridge report that the God's Number proof used cosets of H, reducing the
  2,217,093,120 raw cosets by 16-way symmetry to about 170 million entries, and then used neighbor-distance
  information to avoid wasting work on false nodes (`https://www.kociemba.org/math/papers/rubik20.pdf`).
- Nissy's H48 documentation confirms the same class of engineering levers: inverse estimates, tight-bound
  move restrictions, NISS-style switching to inverse search, pruning pipelines, prefetching, and task
  splitting (`https://git.tronto.net/nissy-core/file/doc/h48.md.html`).

Local measurements now support that conclusion:

- The existing full phase-1 table at depth 8 (`data/generated/kociemba_phase1_full_depth8.bin`) visited
  138,155,502 of 2,217,093,120 projection states and raised the superflip phase-1 lower bound from 8 to 9.
- The depth-9 table build completed locally in 47.8092s and wrote
  `data/generated/kociemba_phase1_full_depth9.bin`; it visited 959,761,462 projection states and raises
  the superflip phase-1 lower bound to 10
  (`results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_phase1full_depth9_build.json`).
- A 60s target-19 depth-17 measurement using full-depth-9 + CP x labeled-slice + labeled-UD-edge target
  pruning still timed out, with 108,281,921 expanded phase-1 nodes, 778 phase-2 calls, and
  `proves_no_solution_at_or_below_target=false`
  (`results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_depth17_g1rootsym_pair_full9_cp_cpslice_udedgeprune_cache_nodedup_threads8_split3_timeout60.json`).

The recommendation changes from "build a raw 10-edge table" to a tighter implementation target:

1. Implement the 16-way phase-1 `FlipUDSlice` sym-coordinate and conjugation tables so phase-1 pruning can
   be complete to depth 12 in about the Kociemba/Cube Explorer table shape instead of a 2.1 GiB raw byte
   table.
2. Add the three-axis Reid/Cube Explorer optimal-solver variant and use `max(p_ud, p_rl, p_fb)`.
3. Only after that, consider H48/NISS-style inverse estimates, tight-bound move restrictions, and pruning
   pipeline/prefetch improvements.

This is the first researched path that plausibly offers a 10x+ local speedup while remaining own-code and
admissible. It is still not a completed superflip proof until the target-19 run exhausts all relevant
phase-1 depths and records `proves_no_solution_at_or_below_target=true`.

## 0.8. UPDATE (2026-06-09): FlipUDSlice 16-symmetry phase-1 table + Mike Reid 3-axis bound built and wired

The §0.7 recommendation (steps 1 and 3) is now implemented as own code and is admissible, validated, and
wired into the native two-phase superflip proof driver. This is the first time the symmetry-reduced
phase-1 pruning and the three-axis bound exist in the repository rather than as a plan.

**FlipUDSlice 16-symmetry reduction (Kociemba/Cube-Explorer style).**
`scripts/generate_phase1_sym_tables.py` quotients the *combined* `FlipUDSlice` coordinate
(EO x UD-slice = 2048 * 495 = 1,013,760) by the 16 whole-cube symmetries that fix the UD axis, producing
Kociemba's **64,430 equivalence classes**. FlipUDSlice does **not** factor into independent flip/slice
actions — the symmetry conjugation mixes edge orientation with the edge permutation (verified empirically),
so it must be reduced as a combined coordinate. All reflection-correct symmetry math is done in Python via
the validated `g1_preserving_symmetries()` layer, transforming only the ~64,430 representatives (not all
1,013,760 coordinates, ~36 s), and emits `data/generated/phase1_sym_tables.bin` (classidx / sym / rep /
stabilizer-mask + twist conjugation). A subtlety that first produced an *inadmissible overestimate*:
**2,033 classes have a non-trivial FlipUDSlice stabilizer**, and for those the reduced twist must be the
*minimum over the stabilizer coset*, not an arbitrary choice — otherwise one orbit splits into several
reduced indices and the symmetry-reduced BFS reports distances that are too large. The native loader
(`--sym-phase1-pruning` in `native/kociemba_phase2_probe/kociemba_phase2_probe.cpp`) builds the
**64,430 x 2,187 = 140,908,410-entry** pruning table by BFS in the reduced space, complete to the phase-1
HTM diameter **12**, and caches it as a ~141 MB byte table (`kociemba_phase1_sym_depth12.bin`).

**This replaces the 2.2 GiB raw phase-1 table at ~16x less memory** — decisive on this 16 GiB machine,
which is under heavy memory pressure. The new table gives the *exact* phase-1 distance up to 12 at every
node (the raw depth-9 table capped interior bounds at 10).

**§5 validation (mandatory gate, passed).** `--mode verify-sym-phase1` cross-checks the symmetry-reduced
distance against the trusted raw phase-1 BFS table byte-for-byte: **0 mismatches over all 959,761,462
known (<=9) entries**, `solved=0`, table `max_distance=12`, and the **superflip phase-1 distance is
exactly 10** (so completing the table to 12 does not raise the superflip *root* bound above the prior
value of 10 — its gain is exact interior bounds of 11/12 and the much smaller footprint). Regression gate:
`tests/test_kociemba_phase1_symmetry.py` (14 passed), including shallow two-phase optimality with symmetric
pruning (admissibility at the search level).

**Mike Reid three-axis bound.** `--three-axis-pruning` adds the admissible global prune
`g + max(p_ud, p_rl, p_fb) > target_bound`, where `p_axis` is the symmetric phase-1 distance of the state
conjugated onto that axis. The conjugation reuses the same fixed-UD-axis table via two whole-cube rotations
(`src/rubik_optimal/symmetry.py three_axis_phase1_inputs`), and the RL/FB coordinates are maintained
incrementally through the move-conjugation maps — justified by the conjugation homomorphism
`phi(s.m)phi^-1 == (phi s phi^-1)(phi m phi^-1)`, **verified with 0 mismatches over 10,800 cases**. Because
the superflip is invariant under all whole-cube symmetries, it is its own RL/FB conjugate, so the 3-axis
bound is `+0` at the superflip *root* (max(10,10,10)=10); it only tightens interior (asymmetric) nodes,
which is where the depth-15/16 frontier explodes.

**Measured effect on the target-19 superflip proof.** A sym-only run (8 threads, no target-set pruning,
180 s) completed phase-1 depth 15 and entered 16, dominated by ~1.68 billion phase-2 handoffs (no
`cp_slice`/`ud_edge` target pruning was active in that configuration). The strongest combined
configuration (sym + 3-axis + CP/CP-slice/UD-edge target pruning, 8 threads, 300 s) is recorded in
`results/processed/native_kociemba_two_phase_superflip_probe_seed_2026_target19_sym_3axis_cp_cpslice_udedge_threads8_t300.json`:
it **completes phase-1 depth 17 and enters depth 18** — two depths deeper than every prior target-19
attempt, all of which walled at completed depth 15. The three-axis bound pruned **1,771,626,716** phase-1
branches (more than the 1.42 billion expanded), target-set pruning cut phase-2 handoffs to 11.7 million
(`phase2_timeout_rows=0`), and the run records `proves_no_solution_at_or_below_target=false` (timeout at
342.7 s). This is the deepest own-code progress toward the superflip optimality proof so far, but it is
**not** a completed proof: depths 18 and 19 (where a <=19 solution would enter G1 late) are not yet
exhausted, and each is roughly an order of magnitude larger than the one before.

**Net status (sym + 3-axis, two-phase driver).** The own-code symmetry-reduced phase-1 pruning and
three-axis bound are correct, admissible, memory-appropriate (141 MB vs 2.2 GiB), validated against the
trusted BFS table, and wired into the two-phase proof driver. They advance the target-19 frontier from
depth 15 to depth 17 but do not complete it, because the two-phase enumeration re-runs a separate pass for
every phase-1 length and carries phase-2 handoff machinery.

## 0.9. UPDATE (2026-06-09): Reid single-bound IDA* optimal mode + measured node growth

The §0.7 step-4-adjacent lever is now also implemented: a Mike Reid / Cube-Explorer style **single bounded
IDA\*** search directly to the solved state (`--mode optimal-ida` in the same native binary), reusing the
symmetric phase-1 table and the three-axis heuristic, with full whole-cube root-symmetry masking. Unlike
the two-phase driver it runs **one** search at `bound = target` (no redundant depth passes, no phase-2
handoffs): the superflip has no solution of length `<= B` iff that search exhausts bound `B` with no solved
leaf. Correctness/admissibility is gated by `tests/test_kociemba_phase1_symmetry.py`: on shallow states it
finds the verified optimal at `bound = distance` and **proves no solution at `bound = distance - 1`**
(serial and threaded) — the prove-none direction is the admissibility gate, since an over-pruning heuristic
would falsely prove no solution at the true distance.

**Root-symmetry masking.** The superflip is invariant under all 48 whole-cube symmetries, so the first move
collapses to the orbit representatives `U, U2` (`root_symmetry_representative_moves`), measured to cut the
search ~**7.8x** (bound 16: 46,321,288 -> 5,943,221 expanded nodes, both proving no solution `<= 16`).

**Measured node growth (8 threads, root-masked, superflip).** The effective branching after pruning is a
steady ~**13x per bound**:

| bound | expanded nodes | runtime | proves no `<=` bound |
|---|---|---|---|
| 14 | 273,148 | 0.41 s | yes |
| 15 | 3,543,004 | 0.78 s | yes |
| 16 | 5,943,221 (masked) / 46,321,288 (unmasked) | 1.2 s / 7.9 s | yes |

**Own-code result — superflip distance > 18 proven.** The masked bound-18 search **exhausted with no
solved leaf** in 248.5 s (926,256,799 expanded / 12,317,880,504 generated nodes, 8 threads,
`results/processed/native_reid_optimal_superflip_probe_seed_2026_target18.json`):
`status=lower_bound`, `proves_no_solution_at_or_below_target=true`. This is the first **own-code (no
H48/Nissy) proof** that the superflip has no solution of length <= 18, i.e. its distance is > 18; with the
verified 20-move solution this pins the distance to {19, 20}. From the measured ~12.5x growth per bound,
the **bound-19** search is ~12 billion expanded nodes.

**OWN-CODE PROOF COMPLETE — superflip distance = 20.** The masked bound-19 search
(`results/processed/native_reid_optimal_superflip_probe_seed_2026_target19.json`) **exhausted with no
solved leaf**: `status=lower_bound`, `proves_no_solution_at_or_below_target=true`, `solution_found=false`,
**`timed_out=false`, `node_limited=false`** (a genuine exhaustion, not a cutoff), 11,203,278,121 expanded /
149,020,204,380 generated nodes in 5200.8 s (~86.7 min, 8 threads), `uses_h48_or_nissy=false`. This proves
the superflip has **no solution of length <= 19**. Combined with the independently verified own-code
length-20 solution (distance <= 20), the superflip distance is **exactly 20, proven entirely by the
student's own code — no H48/Nissy, no external oracle.**

Soundness of the claim: (1) the heuristic is admissible — the symmetric phase-1 table is the *exact*
phase-1 distance (validated byte-for-byte against the raw BFS on all 959,761,462 known entries), and
phase-1 distance <= distance-to-solved, so max(p_ud,p_rl,p_fb) is an admissible lower bound; (2) the
three-axis conjugation is verified (homomorphism 0/10,800) and the shallow gate confirms the search *finds*
optima at the true distance and *proves none* one below (so it never over-prunes a real solution);
(3) root masking is exact-safe via the superflip's 48-symmetry stabilizer; (4) the same-face/commuting-order
move pruning is standard HTM-optimal; (5) the atomic task queue searches every subtree exactly once and,
with no solution found and no timeout, every task was completed. The expanded-node count is deterministic
(independent of thread count and task split), so the result is reproducible.

The throughput gap to Cube Explorer's minutes-scale superflip proof is engineering (4-bit packed tables,
assembly-level incremental pruning, prefetch), not algorithmic.

---

## 1. Where we are (measured, not assumed)

The student's own **native C++ Korf/IDA\*** (`native/optimal_solver/optimal_solver.cpp`, built by
`src/rubik_optimal/solvers/optimal_native.py` with `with_nissy=False`) is the requirement-#3 optimal
engine. After a hot-path optimization it runs at **~14 M nodes/s** (8 threads) and is verified optimal
(`solution_length == exact_distance_bfs`) on shallow states.

| State depth | Result on this 8-core / 16 GiB machine |
|---|---|
| ≤ 14 | optimal in **< 2 s** |
| 15 | optimal in **~30 s** |
| ~16 | borderline (1–few min) |
| 20 (superflip) | **does NOT complete** (timed out at 300 s / ~1.4 B nodes) |

**The blocker is heuristic strength, not engine speed.** The admissible heuristic is
`h = max(corner_pdb, edge_pdb_max)` where the corner PDB maxes at distance 11 and each of the eight
6-edge cost PDBs maxes at 10. For the superflip `h = 8`, so IDA* must blind-search a gap of
`20 − 8 = 12`; at branching ≈ 13.3 that's ~`10^13` nodes — days even at 100 M nodes/s. Each **+1 to
`h` divides the work by ~13×**, so the entire game is raising `h`.

PDB footprint today: corner 88 MB + eight 6-edge PDBs (42 MB each) = **0.43 GB** — trivial in 16 GiB.

---

## 2. DEAD END (already measured — do NOT repeat): the existing additive PDB + dual lookup

We prototyped "wire in the already-generated additive edge PDB (`additive_edge_cpdb_lower_bound`,
currently dead code) with SUM + dual lookup (state and its inverse)." **It buys nothing.** Measured
heuristic values (`/tmp/proto_A2.py`, seed 2026):

```
state         corner edgeMax cpdbSum current improved(=max) +dual
rand_d10..20    7-10    8-9     3-5     8-10     8-10        8-10
superflip20      0       8       5       8        8           8
  superflip: current h=8 -> improved+dual h=8  (+0)
  mean h-gain on random deep states: +0.00
  admissibility (BFS<=4): 0 inadmissible, 0 inverse-mismatch
```

Why: the repo's additive PDB is **operator-cost-partitioned by face** (`urf` charges only U/R/F moves
over edges {0–5}; `dlb` only D/L/B over edges {6–11} — see `DEFAULT_ADDITIVE_EDGE_PDB_SPECS` in
`src/rubik_optimal/tables/edge_pdb.py`). Each half ignores ~half the moves as free, so its bound is
weak (3–5) and is already dominated by the `edgeMax` (8) the solver uses. Dual lookup added +0 on the
sampled states. **Conclusion: skip this path.** (The inverse helper and admissibility checked out, so
the measurement is sound — the heuristic genuinely doesn't improve.)

---

## 3. The viable paths (effort / risk / expected payoff)

### Path 1 — 7-edge PDB  *(recommended first; broad, mechanical, low risk)*
A 6-edge cost PDB maxes at 10; a **7-edge cost PDB** sees more of the cube and maxes higher (estimated
~13 here pre-measurement; **measured 11** — see §0). For the superflip (all 12 edges flipped) a 7-edge
subset sees 7 flipped edges instead of 6, directly raising `h` above today's 8 (this estimate was also
refuted by measurement: superflip `h` stays 8 — see §0).
- **Size:** 12·11·10·9·8·7·6 positions × 2⁷ orient = **510,935,040 states ≈ 511 MB** (1 byte) or
  256 MB at 4-bit. Fits 16 GiB.
- **Effort:** mostly mechanical — generalize the existing generator.
- **Risk:** low (same structure as the 6-edge PDB; guard with the admissibility harness in §5).
- **Expected:** big win for *typical* hard states (depth 17–18, the median random state). For the
  superflip it raises `h` to perhaps ~10–11 (gap → ~9–10): helps ~100×, likely **not enough alone**.

### Path 2 — symmetry reduction  *(the superflip-specific lever; medium-high risk)*
Exploit the cube's 48 symmetries: symmetry-reduced PDBs **and** symmetry pruning at the search root.
The superflip is invariant under all 48 symmetries, so this is *the* technique that tames it (and
other symmetric worst cases), and it shrinks PDB storage ~48×.
- **Effort:** medium-high; symmetry-coordinate math is fiddly.
- **Risk:** **high if done carelessly** — a wrong symmetry coordinate yields an *inadmissible*
  heuristic and *silently non-optimal* answers (worst possible outcome for a thesis on optimality).
  Mandatory: the §5 harness on every change.
- **Expected:** this is what makes depth-20 / superflip actually tractable.

### Path 3 — two-phase-to-optimal (iterated Kociemba)  *(strong pragmatic alternative)*
Instead of pushing IDA*+PDB, iterate Kociemba phase-1 over increasing depths with a coset/symmetry
lower bound to *prove* optimality. This is what nissy/`cube20` do; it solves **any** state optimally
in seconds–minutes and **reuses the Kociemba machinery already in `solvers/kociemba.py`**. Since
Kociemba is itself a required algorithm, a "to-optimal" mode is squarely thesis-legitimate.
- **Effort:** medium (a new driver + a lower-bound table on top of existing phase tables).
- **Risk:** medium; optimality proof rests on the lower bound being correct (test vs BFS + nissy).
- **Expected:** robust "every state in s–min" — arguably the best ROI for the stated goal.

### Path 4 (already in place) — isolated nissy oracle for the tail
`h48`/nissy remains as an opt-in, process-isolated, attributed cross-check. The honest thesis framing
already uses it as the independent optimal reference for the extreme tail; no new work needed.

### Not recommended
- The dead-end additive+dual of §2.
- A full from-scratch reimplementation of a `cube20`/nissy-grade solver (research-scale; nissy is
  years of work; God's-Number=20 was proven with ~35 CPU-years).

**Recommended sequence:** Path 1 (measure the actual `h` gain on superflip + random deep states via
§5) → if superflip still intractable, Path 2 (symmetry) **or** switch strategy to Path 3.

---

## 4. Exact files / functions to touch

- **PDB generation (Path 1):**
  - `native/edge_pdb/edge_pdb.cpp` — generalize `SUBSET_SIZE` 6 → 7 (combination ranking,
    orientation bits, BFS). It is already a C++ BFS generator.
  - `scripts/generate_edge_pdb.py` — add a 7-edge profile / subset list.
  - `src/rubik_optimal/tables/edge_pdb.py` — `SUBSET_SIZE`, `edge_subset_coord`, header dims, loaders
    must parameterize on subset size (currently hard-coded 6 in several constants).
- **Heuristic wiring:**
  - `src/rubik_optimal/search/heuristics.py` — `combined_table_lower_bound` (Python IDA*).
  - `native/optimal_solver/optimal_solver.cpp` — the `forward_heuristic` / `search_state_heuristic_bounded`
    MAX (keep incremental coords + early-exit; add the 7-edge lookup).
- **Symmetry (Path 2):** new symmetry-coordinate module (Python `src/rubik_optimal/symmetry.py`
  already has transform helpers to build on) + native support in `optimal_solver.cpp`.
- **Two-phase-to-optimal (Path 3):** extend `src/rubik_optimal/solvers/kociemba.py` with an
  iterate-phase1-to-optimal mode + a coset lower-bound table (reuse `tables/` machinery).

---

## 5. MANDATORY admissibility / optimality harness (the #1 risk)

Any heuristic change can silently break optimality. Every change MUST pass, as an automated gate:

1. **Admissibility:** for a fixed-seed sample of states, `h(s) ≤ exact_distance_bfs(s)` for all `s`.
   Use BFS depth **≤ 5–6** only (pure-Python BFS is exponential; depth ≥ 7 OOMs/stalls — we hit this).
2. **Shallow optimality:** native solver `solution_length == exact_distance_bfs(s)` on depth ≤ 6
   (currently the `@pytest.mark.native` test `test_native_optimal_matches_bfs_exact_distance`).
3. **Deep cross-check:** on depth-12–18 states, native solver length **==** the nissy oracle length
   (process-isolated `h48` backend). This is the only practical optimality check past BFS range.
4. Add regression tests under the `native` marker; never assert on a hand-guessed optimal constant
   (a scramble of length n is only an *upper bound* — e.g. `F R U R' U'` is optimally **5**, not 4;
   this exact bug was already found and fixed once).

A reusable heuristic-strength + inverse + admissibility scaffold from this session is committed at
`scripts/measure_heuristic_strength.py` (run: `PYTHONPATH=src python3 scripts/measure_heuristic_strength.py`).
Adapt it to measure any new heuristic's `h`-gain on deep states before wiring it into the solver.

---

## 6. Clean-session handoff checklist

- `git log -1` → baseline `a57fa81`; run `PYTHONPATH=src python3 -m pytest -q --ignore=tests/infrastructure tests/` (expect 294 passed / 14 skipped).
- Read `docs/IMPLEMENTATION_REVIEW_2026-06.md` (full audit + what was fixed) and this file.
- Native engine: build via `optimal_native._compile(with_nissy=False)`; binary `native/build/optimal_solver`.
- nissy oracle (cross-check only): `native/h48_backend/` (process-isolated; GPL — see `THIRD_PARTY_NOTICES.md` blocking release gate).
- Do the work as a workflow (file-disjoint generation vs heuristic-wiring vs harness), and gate every step on §5.
- Do NOT touch `thesis/` LaTeX (frozen this round).
