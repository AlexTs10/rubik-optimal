my thesis topic is this: specs/topic_brief.pdf
a thesis from a friend of mine that scored well and we generally follow its structure here is this: /Users/alextoska/Downloads/ΔΙΠΛΩΜΑΤΙΚΗ\ ΚΟΝΤΟΥΛΗΣ.pdf
thesis guidelines: /Users/alextoska/Downloads/writing_thesis_guidelines.pdf

## Repository structure: code and writing are SEPARATE repos

The implementation and the thesis writing live in two distinct git repositories,
both under the shared parent `/Users/alextoska/Desktop/rubik-optimal/`.
Do NOT add thesis writing files to the code repo, and do NOT add code to the thesis repo.

- Code repo (this one): `/Users/alextoska/Desktop/rubik-optimal/code`
  - Remote: `github.com/AlexTs10/rubik-optimal` (public — code only)
  - Contains: `src/`, `scripts/`, `tests/`, `native/`, `data/`, `results/`, `output/`,
    `specs/`, `docs/`, `pyproject.toml`, `README.md`, `REPRODUCIBILITY.md`, license/notices.
  - `.gitignore` excludes the writing tree (`thesis/`, `main.bbl`, `main.lof`, `main.lot`,
    `apply_thesis_fixes.sh`) so it can never be re-tracked here.

- Thesis repo (writing): `/Users/alextoska/Desktop/rubik-optimal/thesis`
  - Contains: the `thesis/` LaTeX tree (`main.tex`, `chapters/`, `figures/`, `tables/`,
    `assets/`, `references.bib`) and `apply_thesis_fixes.sh`.
  - LaTeX build intermediates (`.aux`, `.bbl`, `.log`, `.fdb_latexmk`, ...) are gitignored.

### Coupling to know about
Table/figure-generating scripts (e.g. `scripts/generate_edge_pdb.py`,
`scripts/generate_superflip_proof_table.py`, `scripts/render_fair_speedup_tables.py`)
stay in the CODE repo but write their output into `thesis/`. To regenerate thesis tables,
check out the thesis repo alongside this one. The code repo is otherwise self-contained
for building and testing the solver.
