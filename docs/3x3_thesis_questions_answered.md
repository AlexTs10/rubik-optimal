# 3x3 Thesis Questions Answered

**Status:** technical answer matrix for the 3x3 Rubik's Cube part of the thesis.
**Source brief:** `specs/topic_brief.pdf`, dated 2024-06-06.
**Last updated:** 2026-06-08.

This note answers the three 3x3 requirements in the topic brief without strengthening
the thesis claims beyond the current code and saved evidence.

## Topic-brief requirement 1: Thistlethwaite, Kociemba, Korf

**Question:** Do we have implementations of the requested algorithms?

**Answer:** Yes, with scoped and explicitly documented boundaries.

- Thistlethwaite: implemented as a native four-phase subgroup-chain solver:
  G0->G1 edge orientation, G1->G2 corner orientation plus UD-slice placement,
  G2->G3 square/half-turn subgroup membership, and final G3->solved half-turn
  search. It is acceptable as an educational/practical staged solver only if the
  thesis states that it is not a reproduction of the historical static
  maneuver-table package.
- Kociemba: implemented as a native scoped two-phase solver plus optional external
  comparison/reference paths. It is a practical verified solver, not an optimal solver.
- Korf: implemented through IDA* search with admissible table lower bounds, including
  a complete 3x3 corner PDB, eight complete 6-edge PDBs, and selected native full-cube
  optimal evidence rows. Exact claims are valid only for rows where the search/backend
  completes and the returned solution independently verifies.
- Prolog is not technically required by the Greek brief because it says Python and/or
  Prolog. If the supervisor wants a Prolog appendix, that is a presentation/scope
  decision, not a blocker in the current implementation.

**Safe thesis wording:** "Υλοποιούνται σε Python/native code οι βασικές διαδρομές
Thistlethwaite, Kociemba και Korf/IDA*. Η Thistlethwaite διαδρομή είναι τετραφασική
αλυσίδα υποομάδων με τελικό half-turn στάδιο, η Kociemba διαδρομή είναι scoped
two-phase solver, και η Korf/IDA* διαδρομή είναι exact μόνο όταν η αναζήτηση
ολοκληρώνεται."

## Topic-brief requirement 2: state input and distance recognition

**Question:** Can the program accept a cube state and recognize how far it is from
the solved state?

**Answer:** Yes, with explicit result categories rather than a false universal exact
claim.

- `CubeState.from_facelets()` accepts canonical 54-facelet `URFDLB` states.
- The parser now rejects count-valid but malformed states by enforcing fixed centers,
  legal corner/edge sticker sets, cubie physical invariants, and a final facelet
  round trip.
- `rubik-optimal distance` returns `exact_distance`, `lower_bound`,
  `unknown_timeout`, or `invalid_state`.
- `rubik-optimal solve`, `rubik-optimal verify`, `rubik-optimal distance`, and
  `rubik-optimal oracle` expose state-input paths with independent verification.
- This requirement is about recognizing/proving the state distance, not merely
  producing a practical solving sequence. A practical solver row may be verified and
  still not answer the distance question unless it also proves optimality.
- `scripts/run_distance_recognition_corpus.py` produces
  `results/processed/distance_recognition_corpus_seed_2026_thesis_topic_brief_bullet2.json`
  as the direct evidence artifact for this bullet. The passing corpus contains solved
  and shallow exact rows, a deterministic random-state lower-bound row, invalid
  facelet rejection, a safe live h48h0 exact facelet-state row, and a saved
  superflip distance-20 reference from existing h48h7 certification.
- The saved superflip row is evidence reuse, not a new hard-tail solve by the corpus
  script; the artifact records `hard_search_started=false`.

**Safe thesis wording:** "Η αναγνώριση απόστασης επιστρέφει exact distance μόνο όταν
η εξαντλητική ή παραδεκτή αναζήτηση ολοκληρωθεί. Διαφορετικά επιστρέφει τεκμηριωμένο
lower bound, timeout/unknown status ή invalid-state αποτέλεσμα."

## Topic-brief requirement 3: heuristic for optimal A* or variant

**Question:** Is the screenshot's third bullet covered?

**Answer:** Yes, and it should be presented as the Korf/IDA* contribution, not as a
generic oracle claim.

- IDA* is the implemented A* variant for optimal search: it uses increasing
  `f = g + h` thresholds and preserves optimality when `h` is admissible.
- The thesis-owned admissible heuristic evidence is the native table lower-bound
  stack: projection pruning tables, complete corner PDB, complete edge PDBs, and
  documented cost-partitioned CPDB experiments.
- The direct generated evidence for this bullet is
  `results/processed/heuristic_comparison_seed_2026_thesis.json`, with row-level
  CSV in `results/processed/heuristic_comparison_seed_2026_thesis.csv` and thesis
  table `thesis/tables/heuristic_comparison.tex`. It compares the misplaced-cubie
  bound, coordinate pruning lower bound, corner PDB bound, edge PDB bound, combined
  default bound, and optional CPDB sum on a deterministic corpus.
- H48/Nissy/RubikOptimal paths may be discussed as exact public-solver-derived
  backend/oracle evidence with attribution and saved artifacts. They are not the
  answer to the brief's heuristic-function bullet; that bullet is answered by the
  native admissible Korf/IDA* lower-bound stack.
- Learned/neural or approximate heuristics, if ever added, must be labelled
  non-admissible unless proven otherwise, and cannot support an optimality claim.

**Safe thesis wording:** "Η ευρετική συνάρτηση για τη βέλτιστη αναζήτηση βασίζεται
σε παραδεκτές αφαιρέσεις και pattern databases. Η IDA* παραλλαγή επιστρέφει βέλτιστη
λύση μόνο όταν ολοκληρώσει την αναζήτηση κάτω από αυτά τα όρια."

## What can be claimed today

- The repository implements the three named 3x3 algorithm families in the bounded
  form documented above: native Kociemba remains scoped, native Thistlethwaite is
  now four-phase, and Korf/IDA* supplies the admissible-heuristic exact-search track.
- It accepts sequence and facelet state input, validates physical solvability, and
  independently verifies returned solutions.
- It has exact 3x3 evidence for saved native/H48/Nissy/RubikOptimal/portfolio rows
  where the selected exact backend completed and verification passed.
- It has a direct topic-brief bullet-2 corpus artifact that demonstrates
  `exact_distance`, `lower_bound`, and `invalid_state` categories without launching
  hard-tail generation or proof workloads.
- It has a defensible A*/IDA* heuristic answer through admissible native PDB/lower
  bound tables.
- It can cite God's Number as an external theorem, but it does not re-prove that
  theorem.

## What must not be claimed

- Do not claim that every arbitrary 3x3 state is solved optimally in practical time
  by this repository.
- Do not present H48H7 corpus evidence as a formal worst-case runtime theorem.
- Do not present timed-out, lower-bound, or approximate rows as exact distance.
- Do not present vendored public-solver code as original thesis algorithmic work.
- Do not claim a Prolog implementation exists unless one is actually added and tested.

## Brief-reference handling

- The brief's Wikipedia links are context sources, not the preferred technical
  citations for thesis claims. The thesis should cite verified algorithm, PDB,
  group-theory, and state-space sources for those claims.
- The brief's cube20.org link may be cited as the original topic-brief God's Number
  source, but the thesis should pair it with the stronger published diameter source
  and keep the repository limitation explicit: this work does not reproduce the
  all-state proof of God's Number.
- The Kallipos/Prolog DOI from the brief is cited directly as the Prolog/AI context;
  no Prolog implementation is claimed unless one is added and tested.

## Remaining supervisor decisions

- Whether the scoped native Kociemba implementation and bounded four-phase native
  Thistlethwaite implementation are sufficient for the first topic-brief bullet.
- Whether the vendored GPL public-solver backend is acceptable in the repository and
  how the attribution/non-originality wording should appear.
- Whether the exact wording may say "oracle for arbitrary valid 3x3 state input" if
  it is immediately qualified as row-exact/corpus-backed and not an every-state
  runtime proof.
- Whether any Prolog appendix or comparison is required despite the "Python and/or
  Prolog" wording.
