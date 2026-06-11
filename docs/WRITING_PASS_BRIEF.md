# Writing-Pass Brief (2026-06-11)

You are running an audit + fix pass on the **writing quality** of this thesis (Greek, University of Patras ECE, "Optimal Solution Algorithms for Rubik's Cube"). The technical substance was deep-audited and fixed in a prior session — your job is style, flow, coherence, and the small list of deferred prose items below. **Facts are locked; prose is yours.**

## Ground rules — read first

1. **(Updated 2026-06-11)** The artifact-regeneration job has finished and the worktree was merged and removed; work directly on `main` in `/Users/alextoska/Desktop/sgarbas`. Commit in small batches per chapter group; never push; never git reset/checkout/stash.
2. **Edit only prose**: `thesis/chapters/*.tex` and `docs/` prose files. Do NOT touch `src/`, `native/`, `scripts/`, `tests/`, `results/`, `data/`, or `thesis/tables/*.tex` (generated). Do not run result-generating scripts or `scripts/thesis_audit.py` here.
3. **Style authority**: `docs/writing_style_guide.md`, plus the register of the existing text. Formal Greek academic style; Greek chapter headings; English only for established technical terms; consistent notation.
4. **Integrity rules** (`AGENTS.md`): never present approximate/timed-out/lower-bound results as exact; never overstate optimality; every number must trace to a file in `results/processed/`. If you reword a sentence containing a number or a guarantee, the number/guarantee must survive verbatim in meaning.
5. **PDF must keep building**: `latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex` (run from the worktree root; aux files land in the worktree root). Build after each chapter batch. Do not introduce TODO/FIXME markers in .tex (the audit greps for them).
6. Do not run solvers, native tests, or result-generating scripts — prose only. Running the fast pytest subset and `latexmk` is allowed.

## Locked facts — any rewrite must preserve these exactly

- **Thistlethwaite**: table-guided greedy descent over four exact BFS coset distance tables (2048 / 1,082,565 / 58,800 with 29,400 reachable / 663,552 entries; stage max depths 7/10/13/15). Always terminates; **no** IDA*, no candidate collection, no timeouts; statuses only `non_exact`/`failed`. The old "bounded IDA*" narrative was the critical audit finding — do not let it creep back.
- **Kociemba scoped solver**: defaults are the full phase diameters (phase 1 ≤ 12, phase 2 ≤ 18); phase 1 uses the exact sym-reduced depth-12 distance table as heuristic; budget split guarantees phase 2 always runs when candidates exist; solves typical random 18–20-move scrambles with defaults.
- **Korf/IDA* heuristic (default, frozen evidence)**: corner PDB + **eight** 6-edge PDBs (total 428,803,832 bytes). The 7-edge PDBs exist but are **opt-in**, not part of the frozen thesis evidence.
- **h48 speedups (fair re-measurement)**: trusted-table ≈ **218.9× total / 232.6× steady-state** (genuine — the checked arm re-scans the 3.8 GB table per call); batch overhead ≈ **3.7× / 3.1×**; resident ≈ **3.8× / ~6.6×**. The old 38.198×/40.16× totals included a one-time cold 3.8 GB page-in charged to the slow arm; the old 189.894× is superseded by the fair 218.9×. Exact values: `results/processed/*_fair.json`.
- **Superflip**: distance exactly 20; the only exact result backed by a dedicated own-code exhaustive lower-bound proof. Deeper exact rows (depth 15–25) rest on completed admissible searches of the producing backends, cross-validated where multiple backends exist.
- **NEW (2026-06-11)**: all 11 previously h48-only exact rows (the ten extra_random_*_25 stress rows + deterministic_depth_25) are now ALSO independently confirmed by external Nissy 2.0.8 with its own tables — evidence artifact `results/processed/h48only_rows_independent_reverify_seed_2026_thesis.json` (11/11 length matches, all replays valid). The validation chapter may now state that every deep exact row has at least one independent cross-check; cite this artifact where chapter 06 discusses the stress rows.
- **Live test certification depths**: pure-Python Korf/IDA* path verified optimal to distance 6 (native-oracle anchored); native-Korf vs two-phase-optimal mutual gate to distance 11.
- **Certificates**: rows imported from nissy benchmark labels carry `external_label_exact` status and are excluded from the exact store by default. Masked native searches report `exact_under_root_mask`, upgraded only by the certified stabilizer wrapper.
- **Audit semantics**: `python -m pytest -q` passes at HEAD; `scripts/thesis_audit.py` intentionally exits non-zero while submission blockers remain (placeholders, supervisor approval).
- Front matter: supervisor = Κυριάκος Σγάρμπας (real); student = ΑΛΕΞΑΝΔΡΟΣ ΤΟΣΚΑ; placeholders remain for patronymic, registration number, committee members, examination month, division director. Leave them as placeholders.

## Certification artifacts — retention decision (final, 2026-06-11)

The five `h48_oracle_certification_*.json` artifacts and `h48_metadata_seed_2026_thesis_h48h7.json` were **NOT regenerated**: the decision is documented retention. Reason: the h48h7 table generation was thread-race nondeterministic at the time (~650 of ~7.6e9 nibbles stale-high, confined to the per-line fallback minima — the main pruning region is pinned exact by nissy's distribution check), so byte-exact regeneration is impossible; all 11 deep exact rows these artifacts support are now independently confirmed by external Nissy 2.0.8 (`results/processed/h48only_rows_independent_reverify_seed_2026_thesis.json`, 11/11 matches). The recorded wall-clock quotes (51.813928 s, 91.629342 s, 158.440286 s, 72.071228 s, 77.822389 s) remain the citable evidence as-is. Task E below documents this retention.

## Your actual task list

A. **Holistic per-chapter writing review** (style, register, flow, argument structure, redundancy, paragraph-level coherence) — all of: `00_front_matter` (prose bits only), `00_abstracts` (Greek + English), `01_introduction`, `02_background`, `03_cube_model`, `03_algorithms`, `04_literature_review`, `04_implementation`, `05_system_design`, `05_experiments`, `06_validation`, `06_discussion`, `07_conclusions`, `08_ai_disclosure`, appendices `a_reproducibility`, `b_result_schema`, `c_submission_checklist`, `d_cli_reference`. The background/literature chapters have never been reviewed by anyone.
B. **Seam repair**: chapters 01/03/04/05/06/07 had paragraphs surgically rewritten during the technical fixes (Thistlethwaite sections, h48 captions, Kociemba descriptions, validation claims). The facts are right; smooth the surrounding narrative so the rewritten passages read as part of the whole.
C. **Deferred prose findings** (from the technical audit, never applied):
   1. `timeout` vs `lower_bound` terminology: a few unedited passages still use them interchangeably; align with the benchmark schema's meaning (timeout = budget exhausted; lower_bound = proven bound without solution).
   2. Pocket-cube chapter **under-claims**: the fixed-DBL U/R/F model is exactly the standard rotation-quotient convention, so the computed maximum 11 IS the published 2×2×2 God's Number — state it as such (with the existing citation-needed caveat if the reference is still pending).
   3. e2e chapter: "ανεξάρτητη επαλήθευση" overstates verifier independence for the native-solver rows (replay uses the same cube model); qualify it.
   4. Cross-chapter consistency: notation, solver names, table/figure caption style, decimal formatting (the text mixes Greek and Anglo decimal conventions in places).
D. **Abstracts**: final read of Greek + English abstracts against the final results (they were claim-checked but not style-reviewed).
E. **Retention documentation** (the only NEW substance task — keep it faithful to the retention-decision section above):
   1. `docs/limitations.md`: add the h48h7 retention/nondeterminism note (English; base it on the drafted paragraph in the retention section and the investigation record).
   2. The thesis chapter that discusses h48 evidence validity (06_validation or 06_discussion): 2-3 Greek sentences stating the table nondeterminism finding, the distribution-check containment, the retention decision, and the 11/11 independent re-verification — citing `h48only_rows_independent_reverify_seed_2026_thesis.json`.
   3. `docs/final_supervisor_approval.template.md`: add a line item for supervisor approval of the retained six artifacts.
F. **Final report**: write `docs/writing_pass_report.md` listing every change by chapter and anything you deliberately did NOT change.

## Workflow suggestions

- Commit in small batches per chapter group with descriptive messages.
- Rebuild the PDF after each batch; a broken build must be fixed before moving on.
- When in doubt between a stylistic improvement and preserving a precise technical formulation — preserve the technical formulation.
