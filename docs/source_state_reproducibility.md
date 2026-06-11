# Source-State Reproducibility

Final thesis artifacts must be tied either to a clean committed checkout or to
an explicitly approved immutable source archive. The current repository has a
real Git baseline, so `source_state: no_commit+dirty` is no longer acceptable in
final generated metadata.

## Current Policy

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

## H48 h48h7 Retention Boundary

The large H48 `h48h7` table is a retained binary artifact, not a file that is
rewritten casually during final packaging. Its original generation was
thread-race-nondeterministic at byte level, so rerunning the generator may
produce a functionally equivalent table with a different checksum.

The final-source fix for this case is explicit adoption, not silent metadata
editing:

```bash
python scripts/generate_h48_tables.py \
  --profile thesis --seed 2026 --oracle --threads 8 \
  --adopt-existing-table-metadata
```

That command must be run from a clean committed checkout. It validates the
existing table with the native table-check canary, recomputes the SHA-256
checksum, writes fresh adoption metadata, and preserves the previous table
metadata provenance in `adoption_previous_*` fields.

After adoption, regenerate the H48 certification artifacts that embed the table
metadata:

```bash
python scripts/run_h48_oracle_certification.py \
  --profile thesis --seed 2026 --timeout 90 --runtime-target 90 --threads 8
python scripts/run_h48_oracle_certification.py \
  --profile thesis --seed 2026 --solver h48h7 --timeout 300 \
  --runtime-target 300 --threads 8 --trusted-table \
  --artifact-suffix trusted_no_preload
python scripts/run_h48_oracle_certification.py \
  --profile thesis --seed 2026 --solver h48h7 --timeout 180 \
  --runtime-target 180 --threads 8 --trusted-table --preload-table \
  --artifact-suffix trusted_preload
```

If the retained-table exception is not accepted by the supervisor, the
alternative is a full H48 table regeneration from a clean committed checkout
using `--force`, followed by all dependent certification and audit commands.

## Safe Final Sequence

1. Review `git status --short` and commit the intended source baseline.
2. Run the H48 adoption or full regeneration command from that clean baseline.
3. Regenerate dependent certification artifacts.
4. Run `python scripts/verify_results.py`.
5. Run `python scripts/source_state_report.py`.
6. Run `python scripts/thesis_audit.py`.

Do not claim final submission readiness while generated metadata still records
`no_commit+dirty` or while the current checkout is dirty.

For the `.git`/`data`/`results` size snapshot and the safe cleanup boundary, see
`docs/repository_hygiene_runbook.md`. In particular, do not prune or delete
`.git`, `data`, or `results` in the shared checkout without explicit approval
and a backup.
