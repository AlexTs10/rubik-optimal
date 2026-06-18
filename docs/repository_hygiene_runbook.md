# Repository Hygiene Runbook

This runbook records the current repository hygiene blocker and the safe path to
turn the shared local checkout into a reproducible thesis baseline.

## Current Snapshot

Re-measured on 2026-06-08 in `/Users/alextoska/Desktop/sgarbas` (the
garbage-pack pile kept growing during Phase-1/Phase-2 work, so the figures below
supersede the earlier ~17.81 GiB / 177-pack reading recorded in this section):

```text
du -sh .git
45G     .git

git rev-parse --verify HEAD
fatal: Needed a single revision

git ls-files | wc -l
0

git count-objects -vH
in-pack: 5
packs: 1
size-pack: 4.70 GiB
garbage: 617
size-garbage: 40.56 GiB

find .git -name 'tmp_pack_*' -type f | wc -l
617
```

The audit (`docs/IMPLEMENTATION_REVIEW_2026-06.md`, row P0-4) likewise records
~40 GiB of garbage `tmp_pack_*` files (616+ packs). `data` (~4 GiB) and `results`
(~7 GiB) still hold multi-GiB generated thesis artifacts.

The repository is an unborn `main` branch with no committed files. Current
generated metadata that records `source_state: no_commit+dirty` is development
evidence only, not final-submission provenance.

## Do Not Delete In This Shared Checkout

Do not run any of these commands without explicit user approval and a backup:

```bash
rm -rf .git
rm -rf data
rm -rf results
git clean -fdx
git reset --hard
git gc --prune=now
```

The `.git` directory contains roughly 40 GiB of garbage pack files (617
`tmp_pack_*` files as of the re-measurement above). Removing or pruning them may
be safe after approval, but it is still destructive in this shared checkout and
must not be done while other agents may be working.

## Safe Baseline Plan

1. Stop all solver generation, benchmark, LaTeX, and background worker activity.
2. Create an external copy or archive of the full current directory.
3. Decide which artifacts belong in the submitted source baseline:
   source code, thesis text, scripts, generated JSON/CSV/TEX evidence, required
   small metadata, and any explicitly approved binary tables.
4. Keep heavy binary tables, proof archives, and external caches out of Git
   unless the supervisor approves Git LFS, an external artifact bundle, or
   forced tracked binaries.
5. Build a clean baseline in a fresh directory or after an approved cleanup.
6. Add files intentionally. Use `git add -f <path>` only for binary/generated
   artifacts that are explicitly approved for the final source baseline.
7. Create the initial commit or approved immutable source archive.
8. Regenerate source-state-sensitive metadata from that baseline.
9. Run the final checks:

```bash
python scripts/source_state_report.py
python scripts/verify_results.py
latexmk -xelatex -interaction=nonstopmode -halt-on-error thesis/main.tex
cp main.pdf thesis/main.pdf
cmp main.pdf thesis/main.pdf
python scripts/thesis_audit.py
```

Final submission readiness must remain false until the source-state report and
the generated result metadata come from a clean committed checkout or an
approved immutable source archive.

## Lightweight Audit Commands

Use these commands to refresh the hygiene snapshot without modifying the tree:

```bash
du -sh .git data results 2>/dev/null
git status --porcelain=v1 --untracked-files=all | sed -n '1,80p'
git rev-parse --verify HEAD
git ls-files | wc -l
git count-objects -vH
find .git -name 'tmp_pack_*' -type f | wc -l
find data results -type f | wc -l
find data results -type f \( -name '*.bin' -o -name '*.o' -o -name '*.tar' -o -name '*.tar.gz' -o -name '*.zip' \) | wc -l
```
