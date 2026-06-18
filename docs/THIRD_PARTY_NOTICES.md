# Third-Party Notices

This repository includes third-party solver code and public-table evidence that must remain visibly separate from the original thesis implementation work.

This docs copy mirrors the canonical root file `THIRD_PARTY_NOTICES.md`; keep both consistent.

## nissy-core H48 backend

- Component: `nissy-core`, vendored under `native/h48_backend/third_party/nissy_core/`.
- Local license file: `native/h48_backend/third_party/nissy_core/LICENSE`.
- Recorded license: `GPL-3.0-or-later`.
- Repository integration: `native/h48_backend/h48_backend.c` wraps the vendored H48 API for generated H48 table creation, lower-bound checks, and exact/timeout-only state solving.
- Thesis boundary: H48 results are public-solver-derived evidence. They may support exact backend/oracle experiments when the selected backend completes and the returned solution is independently verified, but they are not original thesis algorithmic work.

## External Nissy optimal table evidence

- Component: public Nissy optimal table artifacts installed by repository scripts when explicitly requested.
- Evidence scripts: `scripts/install_nissy_public_table.py`, `scripts/verify_nissy_public_tables.py`, and Nissy-backed runs in `scripts/run_3x3_optimal.py` / portfolio-oracle scripts.
- Thesis boundary: these artifacts are external/public-solver evidence and certificate support. They must not be described as native Korf, Kociemba, or Thistlethwaite implementation output.

## PyPI `kociemba` two-phase solver (non-exact comparison baseline)

- Component: PyPI `kociemba`, declared in `pyproject.toml` as `kociemba>=1.2; python_version >= '3.10'`.
- Verified metadata: version `1.2.1`, author `muodov` (`muodov@gmail.com`), license `GPLv2`, upstream `https://github.com/muodov/kociemba`. It is NOT authored by "Maxim Tsoy".
- Repository integration: used only through `solve_kociemba_adapter` in `src/rubik_optimal/solvers/kociemba.py` as a **non-exact comparison baseline** (two-phase / near-optimal; results keep `non_exact` status and are never relabeled exact/optimal).
- Boundary: this package is **not part of the student's native implementation**. Because it is GPLv2, redistributing the repository with this dependency is subject to GPLv2 copyleft and is covered by the blocking release gate below.

## Static-linking / combined-work obligation: `optimal_solver_nissy`

- The optional native binary `native/build/optimal_solver_nissy` is produced by `_compile(with_nissy=True)` in `src/rubik_optimal/solvers/optimal_native.py`, which **statically links** the student's `optimal_solver.cpp` with the GPL-3.0-or-later Nissy 2.0.8 C sources.
- This makes a **combined / derivative work**: `optimal_solver_nissy` may be distributed **only under GPL-3.0-or-later with complete corresponding source**.
- The **default shipped optimal artifact is the NON-nissy `optimal_solver`** (built without any Nissy sources) **plus the process-isolated `h48_backend` subprocess** (a separate process, not statically linked, so no combined-work binary). `optimal_solver_nissy` is **opt-in only** and **excluded from distribution unless the whole package is GPL-3.0-or-later licensed with corresponding source**.

## BLOCKING release gate (supervisor license decision required)

**Hard, blocking gate, not advisory.** A public push, public release, or submission package **MUST NOT proceed** without an **explicit written supervisor/institutional license decision** covering all copyleft components:

- the vendored **GPL-3.0-or-later `nissy-core`** H48 source under `native/h48_backend/third_party/nissy_core/`;
- the optional **GPL-3.0-or-later Nissy 2.0.8 static link** in `optimal_solver_nissy` (ship only as GPL-3.0-or-later with corresponding source, else exclude);
- the **GPLv2 PyPI `kociemba`** dependency (non-exact baseline).

Until that written decision exists and is referenced from the release, the default shipped configuration is the **non-nissy `optimal_solver` + process-isolated `h48_backend` subprocess**, with `optimal_solver_nissy` and the GPL `nissy-core` redistribution held back.

## Review rule

Any thesis, README, or handoff claim that uses H48/Nissy evidence must identify it as public-solver-derived or external-assisted evidence and must keep exact-distance claims tied to saved, independently verified result rows.
