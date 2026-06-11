# Codex Phase Prompts

Use these prompts after setting the short `/goal`.

## Goal command

```text
/goal Follow docs/goal.md and docs/acceptance.md to build the delivered Rubik thesis repository. Treat the current short draft as a prototype only. Keep docs/progress.md updated. Stop only when all revised acceptance checks pass or a verified, supervisor-accepted blocker is documented.
```

## Phase A: acceptance reset

```text
Read AGENTS.md, docs/goal.md, docs/acceptance.md, docs/reference_thesis_calibration.md, and docs/roadmap_to_delivered_thesis.md. Verify that the current repository is marked as a prototype, not complete. Update docs/progress.md and docs/final_audit.md if needed. End with the next Phase B prompt.
```

## Phase B: research and thesis shell expansion

```text
Continue with Phase B only. Expand the research base and thesis shell toward the delivered-thesis target: verify 20-30 sources, update docs/research_notes.md and thesis/references.bib, expand the front matter/chapter skeleton, and add scripts/thesis_audit.py to report page count, word count, figure/table counts, TODOs, and claim-risk markers. Do not claim final completion. Update docs/progress.md and end with the next Phase C prompt.
```

## Phase C: coordinate and table foundation

```text
Continue with Phase C only. Implement coordinate modules, coordinate roundtrip tests, move-table generation, pruning-table metadata, generated table checksums, and direct-cubie cross-checks. Update docs/architecture_plan.md if the design changes. Run tests and table-generation smoke checks. Update docs/progress.md and end with the next Phase D prompt.
```

## Phase D: native solver tracks

```text
Continue with Phase D. Implement native solver tracks in dependency order: Kociemba-style two-phase search, Thistlethwaite-style subgroup-chain search, Korf/IDA* with generated table-based admissible heuristic, and a complete 2x2x2 optimal case study if arbitrary 3x3 optimality remains infeasible. Every solver must return structured statuses and independently verified solutions. Run focused tests and update docs/progress.md. End with the next Phase E prompt.
```

## Phase E: thesis benchmarks and generated artifacts

```text
Continue with Phase E only. Add quick/thesis/stress benchmark profiles, generate thesis-profile result files with seed 2026, generate final thesis tables and figures from saved results, expand scripts/verify_results.py to catch stale artifacts and invalid claims, and update docs/progress.md. End with the next Phase F prompt.
```

## Phase F: full thesis writing

```text
Continue with Phase F only. Expand the Greek thesis to the delivered-thesis structure in docs/thesis_structure.md using verified citations and generated results only. Include dense theory, model, design, implementation, methodology, results, discussion, conclusions, appendices, and AI-assistance disclosure. Build the thesis PDF and run scripts/thesis_audit.py. Update docs/progress.md. End with the next Phase G prompt.
```

## Phase G: final audit and repair

```text
Continue with Phase G. Run every command in docs/acceptance.md. Audit code, tests, results, bibliography, LaTeX references, thesis claims, figures, tables, limitations, scale, and reproducibility. Create/update docs/final_audit.md. Fix real issues found. Do not hide failures. Update docs/progress.md and tell me whether the delivered thesis is complete or which verified blockers remain.
```

## Emergency audit prompt

Use if Codex seems to overclaim or drift.

```text
Pause implementation. Audit the repository against docs/acceptance.md and docs/goal.md. Identify any claims that are not backed by code, tests, results, or verified citations. Fix wording or implementation so the repository becomes academically honest. Update docs/limitations.md and docs/progress.md before continuing.
```

