read this file: AGENTS.md

## Repository structure: code and writing are SEPARATE repos

Implementation and thesis writing live in two distinct git repositories,
both under the shared parent `/Users/alextoska/Desktop/rubik-optimal/`.
Do NOT mix them — no writing files in the code repo, no code in the thesis repo.

- Code repo (this one): `/Users/alextoska/Desktop/rubik-optimal/code`
  → `github.com/AlexTs10/rubik-optimal` (public, code only).
  Holds `src/`, `scripts/`, `tests/`, `native/`, `data/`, `results/`, `output/`,
  `specs/`, `docs/`. The writing tree (`thesis/`, `main.bbl/.lof/.lot`,
  `apply_thesis_fixes.sh`) is gitignored here.

- Thesis repo (writing): `/Users/alextoska/Desktop/rubik-optimal/thesis`
  Holds the `thesis/` LaTeX tree and `apply_thesis_fixes.sh`.

Note: table-generating scripts live in the code repo but write into `thesis/`,
so regenerating thesis tables needs the thesis repo checked out alongside.
See AGENTS.md for the full description.
