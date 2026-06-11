# `scripts/experimental/` — out-of-scope cloud/AWS proof scaffolding

**These scripts are NOT part of the thesis.** They are an experimental
cloud/AWS/remote "fast-target" proof harness that was explored during the
project but is outside the scope of the diploma thesis *"Optimal Solution
Algorithms for Rubik's Cube"*. They are kept here for provenance, **not run**
as part of the thesis pipeline, and are excluded from the thesis acceptance
gate, the figures/tables regeneration, and the core test suite.

## Why they were quarantined

The thesis brief covers three solver algorithms (Thistlethwaite, Kociemba,
Korf/IDA*) plus their supporting tables and benchmarks. The files in this
directory instead provision and drive **remote/cloud compute** for an H48
"fast-target" proof campaign. Per the Phase-2 audit
(`docs/IMPLEMENTATION_REVIEW_2026-06.md`, finding **P2-1**), this is ~13.2k
lines of AWS/cloud/fast-target/hardtail orchestration (~30% of `scripts/`) that
is unrelated to the brief, and the AWS path itself was already abandoned in
favor of a non-AWS / local path.

## WARNING — these may start PAID cloud instances

Some of these scripts (notably `provision_h48_fasttarget_aws.py`,
`prepare_h48_fasttarget_aws_security_group.py`, `run_h48_fasttarget_aws_proof.py`,
`run_h48_fasttarget_remote.py`) render or execute commands that can **launch
paid AWS EC2 instances, create security groups, and allocate remote storage**.
Do not run them unless you understand the cost implications and have configured
your own credentials. Several support a `--dry-run` mode; prefer that.

## Files

- `plan_cloud_hardtail_campaign.py`, `run_cloud_hardtail_campaign.py`,
  `run_cloud_hardtail_workload.py`, `evaluate_cloud_hardtail_campaign.py`,
  `render_cloud_hardtail_runbook.py`, `cloud_hardtail_preflight.py`,
  `validate_cloud_hardtail_archive.py` — the cloud "hardtail" campaign harness.
- `provision_h48_fasttarget_aws.py`,
  `prepare_h48_fasttarget_aws_security_group.py`,
  `run_h48_fasttarget_aws_proof.py` — the (abandoned) AWS provisioning path.
- `prepare_h48_fasttarget_nonaws_launch.py`,
  `run_h48_fasttarget_nonaws_proof.py`, `run_h48_fasttarget_local_proof.py`,
  `run_h48_fasttarget_remote.py`, `build_h48_fasttarget_proof_package.py` —
  the non-AWS / local / remote fast-target proof runners and packaging.

## Imports

These modules still import a few **core** helpers that remain under
`scripts/` (e.g. `scripts.inspect_h48_capacity`,
`scripts.inspect_h48_proof_volumes`); the dependency direction is one-way.
**No core thesis script imports anything in this directory.** Run from the
repository root so the `scripts.experimental.*` package path resolves
(e.g. `PYTHONPATH=. python3 -m scripts.experimental.<module>`).

The matching cloud/fast-target **result artifacts** were moved out of the
thesis tree to `../../archive/` (see `archive/README.md`), and the cloud/infra
**tests** live under `tests/infrastructure/`.
