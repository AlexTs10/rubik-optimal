# Final Supervisor Approval Record Template

Do not rename this template as the final approval record until the values below
come from the supervisor or Secretariat. When approval is received, copy this
file to `docs/final_supervisor_approval.md`, replace every placeholder, and
preserve the required audit terms exactly.

```text
approval_status: approved
approval_source: TODO supervisor or Secretariat message/reference
approval_date: TODO YYYY-MM-DD
```

Required approved decisions:

- front-matter style approved: TODO confirm template adaptation and final metadata.
- bibliography style approved: TODO confirm bibliography style/format.
- scoped solver claims approved: TODO confirm bounded Kociemba, Thistlethwaite, Korf, and Pocket Cube claim limits.
- retained/adopted h48h7 evidence artifacts approved: TODO confirm acceptance
  of the documented retention decision for the existing validated h48h7 table
  bytes, the clean-source metadata adoption record, and the refreshed or
  regenerated certification artifacts tied to the thread-race-nondeterministic h48h7 oracle table:
  `results/processed/h48_oracle_certification_seed_2026_thesis.json`,
  `results/processed/h48_oracle_certification_seed_2026_thesis_trusted.json`,
  `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_no_preload.json`,
  `results/processed/h48_oracle_certification_seed_2026_thesis_trusted_preload.json`,
  `results/processed/h48_oracle_certification_seed_2026_thesis_auto_min.json`, and
  `results/processed/h48_metadata_seed_2026_thesis_h48h7.json`, given the
  11/11 independent re-verification recorded in
  `results/processed/h48only_rows_independent_reverify_seed_2026_thesis.json`.

Evidence notes:

- TODO paste or summarize the authoritative approval source without inventing a
  decision.
- TODO list any conditions the supervisor requires before final deposit.

After creating `docs/final_supervisor_approval.md`, run:

```bash
python scripts/thesis_audit.py
```

The audit should report `supervisor_approval.passed: true`. If the final
front-matter placeholders have also been replaced, the target final state is:

```text
front_matter_placeholders: []
submission_blockers: []
final_submission_ready: true
```
