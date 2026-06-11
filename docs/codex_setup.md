# Codex Setup

Use this file to configure and run Codex for the thesis build.

## Recommended model settings

Use:

```text
model: gpt-5.5
reasoning effort: xhigh
plan mode reasoning effort: xhigh
verbosity: medium
```

Cost is not the constraint for this project. Correctness, verification, and research quality matter more.

## Example Codex config

If using a TOML config, the idea is:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
plan_mode_reasoning_effort = "xhigh"
model_verbosity = "medium"

[features]
goals = true
```

If your local Codex version uses slightly different config names, use `/status` and `/model` to confirm.

## Start command

From the repository root:

```bash
codex
```

Inside Codex:

```text
/status
/model
```

Select gpt-5.5 and xhigh reasoning.

## Short goal command

Use this exact short goal:

```text
/goal Follow docs/goal.md and docs/acceptance.md to build the delivered Rubik thesis repository. Treat the current short draft as a prototype only. Keep docs/progress.md updated. Stop only when all revised acceptance checks pass or a verified, supervisor-accepted blocker is documented.
```

## First prompt after setting goal

Use:

```text
Read AGENTS.md, docs/goal.md, docs/acceptance.md, docs/reference_thesis_calibration.md, docs/roadmap_to_delivered_thesis.md, docs/requirements_from_brief.md, and specs/topic_brief.pdf if accessible. Start with Phase B only. Verify the revised delivered-thesis scope, update docs/progress.md, and create the research/thesis-shell expansion plan. Do not implement solvers yet. End with commands run, files changed, and the exact next Phase C prompt I should paste.
```

## Operating pattern

Use one phase at a time:

1. acceptance reset;
2. research and thesis shell expansion;
3. coordinate and table foundation;
4. native solver tracks;
5. thesis benchmarks and generated artifacts;
6. full thesis writing;
7. final audit and repair.

The persistent goal keeps the big direction. The phase prompts keep Codex from drifting.
