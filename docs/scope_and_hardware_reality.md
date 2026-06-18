# Scope & Hardware Reality

**Status:** authoritative scope/guardrail note. Read this before any thread that proposes "solving every
3x3 state," generating large H48 tables locally, or using GPU/Metal/MLX to "finish" the optimal oracle.
**Last calibrated:** 2026-06-03.

This file exists to stop a recurring drift: earlier work threads inflated the thesis into "prove a fast
optimal oracle for **every** possible 3x3 state, gated on the H48H10 table." That is **not** the
assignment, is **not** achievable by anyone on any hardware as literally stated, and was holding the
project hostage to a table this machine cannot even store. This note records the honest scope, the
hardware ceiling, and why bigger/faster compute (including the GPU) does not change the picture.

Source-of-truth priority is still as defined in `AGENTS.md` (topic brief → ECE rules → `docs/goal.md` →
`docs/acceptance.md` → code/tests). This note refines *interpretation*; it does not override those files.

---

## 1. The machine (the real ceiling)

| Resource | This Mac |
|---|---|
| Model | Mac15,12 (Apple M3) |
| CPU cores | 8 |
| Unified RAM | 16 GiB (shared by CPU **and** GPU) |
| Free disk | ~23 GiB on a 95%-full drive |
| Local H48 working table | H48H7, ~3.6 GB (fits) |
| H48H10 table | ~30 GB (does **not** fit — see below) |

H48H10 fails on this machine **twice over**: it exceeds the 16 GiB RAM budget needed to hold it resident,
*and* it exceeds the ~23 GiB of free disk needed to even store it. This is a capacity wall, not a tuning
problem.

---

## 2. Two different claims hiding in "fast optimal oracle for every state"

These get conflated constantly. Keep them separate.

- **Claim A — an exact state-input solver contract.** Given a valid 3x3 state, run an admissible exact
  search/backend and return a provably optimal HTM solution when the search completes. **This exists and
  runs on this Mac for the saved native/H48/Nissy/RubikOptimal evidence rows**, with independent
  verification for each returned solution. Per *completed instance*, IDA* or an exact public-solver-derived
  backend yields a genuine optimality proof. This is real, done, and defensible for the recorded corpus;
  it is not a formal practical-runtime theorem for every possible unseen state.

- **Claim B — "for every possible state."** There are **43,252,003,274,489,856,000** (~4.3×10¹⁹) states.
  They cannot be enumerated — not on this Mac, not on a 64 GiB box, not on a GPU farm, not within any
  feasible time. So "for every state" can *only* legitimately mean one of:
  - a **statistical** statement over a large random/structured sample, or
  - the **published God's-number result**: every state is solvable in ≤20 HTM, proven in 2010
    (Rokicki, Kociemba, Davidson, Dethridge; ~35 CPU-years donated by Google). That proved the *bound*,
    not "fast runtime." We **cite** it; we do not re-run or re-prove it.

**No hardware makes Claim B literally true by brute force.** Therefore Claim B must never be a completion
gate. The completion gate is the honest deliverable in §4 plus `docs/acceptance.md`.

---

## 3. Why GPU / Metal / MLX do not change this

A natural instinct is "surely Metal or MLX on Apple Silicon can crack this." For optimal cube search,
the answer is no, for concrete computer-architecture reasons:

1. **The strong table's job is to *shrink* the search — and we can't fit the table that does the
   shrinking.** A bigger PDB (e.g. H48H10) is not faster because lookups are faster; it's faster because
   a stronger admissible heuristic *prunes harder*, so IDA* expands orders of magnitude fewer nodes.
   With a table that fits in 16 GiB, hard positions (superflip-class, distance-20) blow up into billions
   of nodes. The ~30 GB table is precisely what collapses that search — and it doesn't fit. **On Apple
   Silicon the GPU shares the same 16 GiB unified memory**, so Metal is under the *identical* ceiling; it
   cannot conjure 30 GB out of 16.

2. **The workload is latency- and branch-bound, not throughput-bound.** The inner loop is: apply a tiny
   permutation → do a *random* lookup into a multi-GB table → branch (prune or recurse). GPUs win on
   dense, regular arithmetic (TFLOPs); they are poor at random memory gather and at **branch divergence**
   — threads in a warp run in lockstep, and a search tree where every path prunes at a different depth
   serializes them. Depth-first recursion with dynamic work is the textbook anti-pattern for SIMT. GPU
   cube work in the literature targets *regular brute-force BFS* or *neural heuristics*, not single-
   instance optimal IDA*.

3. **Table *generation* is also memory-bound and also doesn't fit.** Building H48H10 is a BFS fill over a
   coset space that needs its working set resident, with heavy random writes. Same capacity/latency
   profile; a GPU does not help build a 30 GB structure that fits in neither RAM nor free disk.

**Bottom line:** the wall is **memory capacity + random-access latency on an irregular search**, which is
exactly the class of problem where GPU/Metal/MLX provide ~zero leverage. This was never "Python vs C" or
"CPU vs GPU."

**The one legitimate GPU/MLX use** is a *learned* heuristic (DeepCubeA-style): train a net on Apple
Silicon via MLX to estimate distance-to-solved and guide weighted A*. Apple Silicon is well suited to
this. **But a learned heuristic is not admissible**, so it produces fast *near-optimal* solutions, not
*provably optimal* ones. It may appear **only** as an explicitly non-optimal extension/comparison chapter
— never as backing for any "optimal" claim (see §6).

---

## 4. The honest deliverable (all achievable on this Mac)

The honest, fully-gradeable "fast optimal oracle" story is these four together:

1. **Per-instance provably-optimal solver** (Korf IDA* plus exact H48/Nissy/RubikOptimal-backed paths):
   for each completed valid-state row, a verified optimal HTM solution with a real optimality proof.
   *(Exists for the saved evidence rows; broader practical runtime remains empirical.)*
2. **Large, deterministic, independently-verified empirical sample** (random + structured states):
   runtime / solution-length / node-count distributions. This is the honest "fast oracle" evidence.
   Scale the sample as far as H48H7 allows locally. *(Benchmark scripts already produce this.)*
3. **Complete 2x2x2 optimal case study:** exhaustive BFS over all **3,674,160** states, full distance
   distribution and god's-number table. This is the rigorous "for every state" result *at the scale
   where 'every state' is tractable* — the honest mirror of the 3x3 claim.
4. **Cite God's Number = 20** (Rokicki/Kociemba/Davidson/Dethridge, 2010) for the universal 3x3 bound.

This quartet satisfies the topic brief (which asks to implement Thistlethwaite/Kociemba/Korf, a distance
recognizer, and a strong A*/IDA* heuristic, and to **"run on a conventional computer"**) and the academic
integrity rules simultaneously.

---

## 5. Mac-safe guardrails

- **No AWS. No SSH to remote hosts.**
- **Do not generate H48H10/H48H11 locally** (won't fit in 16 GiB RAM *or* ~23 GiB free disk). The local
  working table is **H48H7 (~3.6 GB)** — use it.
- Existing H48H10/H48H11 **cloud** runs in `results/` are an **optional stretch** (stronger oracle, bigger
  sample), **never** the completion gate.
- Any `cloud_hardtail`, `h48_fasttarget`, H48H10, H48H11, or proof-host artifacts that remain under
  `results/processed/`, `results/cloud_hardtail_runbook*`, or generated table directories are classified as
  **archived stretch or negative evidence** unless a later audit explicitly records trusted stronger-table
  metadata, completed certification, and accepted runtime-proof scope. Their presence must not be counted as
  thesis-core implementation evidence for the topic brief's three bullets.
- Do not delete those artifacts in a shared checkout just to reduce noise. The safe cleanup path is
  documentation/audit classification first, then an approved archive/packaging step after the final source
  baseline is fixed.
- Keep all heavy runs behind guards. On this Mac, run only: focused unit/smoke tests, H48H7, small probes,
  timeout/contract behavior, resident/batch/race paths, and the complete 2x2x2 enumeration.
- Do not start new heavy/hard-tail solves without explicit approval.

---

## 6. Claim integrity (non-negotiable, per `AGENTS.md`)

- "Optimal" / "exact distance" may attach **only** to results backed by an admissible-heuristic
  optimality proof or exhaustive search. Never present timed-out / lower-bound / approximate output as
  exact distance.
- Any neural/learned (MLX) heuristic is **not admissible** → non-optimal extension chapter only.
- Do not invent citations, benchmark numbers, theorems, or university rules. Every thesis number must
  trace to a saved result file produced by a script.

---

## 7. What completion means here

Completion is governed by `docs/acceptance.md` (code runs, tests pass, benchmark scripts produce saved
results, the XeLaTeX thesis builds, citations resolve, claims match evidence, limitations are honest).

**Claim B ("fast optimal for every 3x3 state") is explicitly NOT a completion requirement.** The §4
quartet plus `docs/acceptance.md` is. Do not claim completion unless `docs/acceptance.md` is satisfied,
and do not let scope drift back toward an all-state proof or local H48H10 generation.
