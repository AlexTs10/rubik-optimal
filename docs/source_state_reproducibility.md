# Source-State Reproducibility

The current local checkout is an unborn Git repository with no commit at `HEAD`.
Generated metadata that records `source_state: no_commit+dirty` is valid
development evidence, but it is not final-submission reproducibility evidence:
another reviewer cannot recreate the exact source tree by checking out a commit
SHA.

## Current Evidence

Run:

```bash
python scripts/source_state_report.py
python scripts/thesis_audit.py
```

The report is written to:

```text
results/processed/source_state_report.json
```

The thesis audit scans generated JSON metadata for `source_state` fields. If any
final artifact metadata is `no_commit`, `no_commit+dirty`, `git_unavailable`, or
otherwise dirty, the audit records a `source_snapshot_reproducibility`
submission blocker and keeps `final_submission_ready: false`.

## Safe Regeneration Plan

1. Review `git status --short` and decide the exact thesis source baseline.
2. Create an intentional commit, or create and record an approved immutable
   source archive if a commit is not allowed.
3. From that clean baseline, rerun the final generation commands whose metadata
   currently records `no_commit+dirty`.
4. Run `python scripts/source_state_report.py`.
5. Run `python scripts/thesis_audit.py`.

Do not claim final submission readiness while generated metadata still records
`no_commit+dirty` or while the current checkout is dirty.

For the current `.git`/`data`/`results` size snapshot and the safe cleanup
boundary, see `docs/repository_hygiene_runbook.md`. In particular, do not prune
or delete `.git`, `data`, or `results` in the shared checkout without explicit
approval and a backup.
