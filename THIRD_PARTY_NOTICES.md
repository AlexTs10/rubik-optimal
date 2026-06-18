# Third-Party Notices and Provenance

This file records the third-party solver code, public tables, and external
backend evidence used by this thesis repository. It is a provenance and notice
file, not legal advice and not a replacement for supervisor or institutional
approval.

## Summary

The original thesis code and writing do not currently have a project-wide
license. See `LICENSE`.

The repository includes or uses the following non-original components:

- vendored `nissy-core` H48 C source under
  `native/h48_backend/third_party/nissy_core/`;
- local external Nissy 2.0.8 source/binary cache under
  `.codex_external/nissy-2.0.8/`, statically linked into the optional
  `optimal_solver_nissy` combined-work binary (see below);
- public Nissy 2.x pruning-table archive entries installed under
  `.codex_external/nissy_data/tables/`;
- locally generated H48 tables derived through the vendored nissy-core H48
  generator under `data/generated/h48/`;
- the PyPI `kociemba` package (a GPLv2 two-phase solver) used only as a
  non-exact comparison baseline;
- RubikOptimal-style public solver/table evidence through an installed Python
  package and local generated table cache under
  `.codex_external/rubikoptimal_tables/`.

These components support public-solver-derived exact-backend evidence. They
are not presented as original student implementations, and they do not replace
the native Korf/IDA* heuristic contribution described in the thesis.

## Vendored nissy-core H48

Path:

```text
native/h48_backend/third_party/nissy_core/
```

Local license file:

```text
native/h48_backend/third_party/nissy_core/LICENSE
```

Upstream source URL recorded by the code:

```text
https://git.tronto.net/nissy-core
```

Upstream license URL checked for this notice:

```text
https://git.tronto.net/nissy-core/file/LICENSE.html
```

Snapshot/commit recorded by the code and generated H48 metadata:

```text
3cb60bcbf4ab9af4e9452a43681f1e7176b0c88f
```

License/provenance boundary:

- The vendored license file identifies the H48/nissy-core C source as
  GPL-3.0-or-later.
- The local vendored directory does not contain a `.git` directory, so the
  repository relies on `src/rubik_optimal/tables/h48.py` and generated metadata
  rows for the recorded commit.
- Generated H48 metadata rows record:
  `backend_source=vendored_nissy_core_h48`,
  `backend_source_url=https://git.tronto.net/nissy-core`,
  `backend_source_commit=3cb60bcbf4ab9af4e9452a43681f1e7176b0c88f`, and
  `license=GPL-3.0-or-later`.

Relevant local evidence files:

```text
results/processed/h48_metadata_seed_2026_thesis_h48h0.json
results/processed/h48_metadata_seed_2026_thesis_h48h7.json
```

## Nissy 2.0.8 external solver cache

Path:

```text
.codex_external/nissy-2.0.8/
```

Local license file:

```text
.codex_external/nissy-2.0.8/LICENSE
```

Observed local version anchor:

```text
src/rubik_optimal/solvers/nissy_external.py uses -DVERSION="2.0.8"
```

License/provenance boundary:

- The local Nissy 2.0.8 license file identifies Nissy as GPL-3.0-or-later.
- The archive directory has no `.git` directory in this checkout.
- The Nissy 2.x path is treated as an external/reference optimal backend and
  public table consumer. It is not claimed as a native student implementation.

## Public Nissy pruning tables

Source URL recorded by local table manifests:

```text
https://nissy.tronto.net/nissy-tables-2.0.4.zip
```

Installed table directory:

```text
.codex_external/nissy_data/tables/
```

Relevant local evidence files:

```text
results/processed/nissy_public_tables_manifest_seed_2026_thesis.json
results/processed/nissy_public_tables_complete_seed_2026_thesis_complete_public.json
results/processed/nissy_public_table_install_seed_2026_thesis_pt_nxopt31_HTM_installed.json
```

Recorded integrity anchor for `pt_nxopt31_HTM`:

```text
CRC32: 8c7e4d23
size: 2,465,897,307 bytes
target: .codex_external/nissy_data/tables/pt_nxopt31_HTM
```

License/provenance boundary:

- The repository records the source archive URL and CRC/size checks for the
  installed table entries.
- No separate table-specific license file was found in this checkout.
- Thesis wording must therefore describe these as public Nissy table artifacts
  with recorded source URL and integrity metadata, not as original generated
  student tables.

## RubikOptimal-style external backend and tables

Bridge source:

```text
src/rubik_optimal/solvers/rubikoptimal_external.py
```

Local table directory:

```text
.codex_external/rubikoptimal_tables/
```

Observed package/table evidence:

```text
results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_safe_check.json
results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_phase1x24.json
results/processed/rubikoptimal_tables_seed_2026_thesis_current_20260531_cornerprun.json
```

Recorded local package path in evidence:

```text
/opt/miniconda3/lib/python3.12/site-packages
```

License/provenance boundary:

- This repository does not vendor the RubikOptimal package source in the
  project tree.
- No RubikOptimal package license file was found in the repository checkout.
- The thesis and docs should present RubikOptimal only as optional external
  public-backend evidence when the installed package and required tables are
  present.

## PyPI `kociemba` two-phase solver (non-exact comparison baseline)

Declared dependency in `pyproject.toml`:

```text
kociemba>=1.2; python_version >= '3.10'
```

Verified package metadata (from the installed distribution metadata):

```text
Name:    kociemba
Version: 1.2.1
Author:  muodov
License: GPLv2
Home:    https://github.com/muodov/kociemba
```

Repository integration:

```text
src/rubik_optimal/solvers/kociemba.py  (solve_kociemba_adapter)
```

License/provenance boundary:

- The `kociemba` PyPI package is licensed `GPLv2`. The author of record in the
  package metadata is `muodov` (`muodov@gmail.com`), upstream at
  `https://github.com/muodov/kociemba`. It is NOT authored by "Maxim Tsoy" and
  must not be attributed that way.
- This package is used ONLY through `solve_kociemba_adapter` as a **non-exact
  comparison baseline**. It implements Kociemba's two-phase algorithm, which is
  near-optimal but not provably optimal, so its results carry a `non_exact`
  status and are never relabeled as exact/optimal.
- The package is **not part of the student's native implementation**. The
  student's own Thistlethwaite, Kociemba, and Korf algorithms and the native
  C++ optimal solver are independent of this package.
- Because `kociemba` is GPLv2, redistributing this repository together with the
  `kociemba` dependency (or any vendored copy of it) is subject to the GPLv2
  copyleft terms and is covered by the blocking release gate below.

## Static-linking / combined-work obligation: `optimal_solver_nissy`

The native build can optionally produce a combined binary, `optimal_solver_nissy`,
by statically compiling and linking the student's own `optimal_solver.cpp`
together with the GPL-3.0-or-later Nissy 2.0.8 C sources.

Build mechanics recorded by the code:

```text
src/rubik_optimal/solvers/optimal_native.py  (_compile with_nissy=True)
  - compiles native/optimal_solver/nissy_bridge.c and
    .codex_external/nissy-2.0.8/src/*.c into object files;
  - links them with optimal_solver.cpp (-DRUBIK_WITH_NISSY_BRIDGE) into a
    single statically linked executable:
        native/build/optimal_solver_nissy
```

License/provenance boundary:

- Statically linking the GPL-3.0-or-later Nissy 2.0.8 sources with the student's
  `optimal_solver.cpp` produces a **combined / derivative work**. The combined
  `optimal_solver_nissy` binary may therefore be distributed **only under
  GPL-3.0-or-later, with complete corresponding source**.
- The **default shipped optimal artifact is the NON-nissy `optimal_solver`**
  binary (built by `_compile(with_nissy=False)`, which links no Nissy sources)
  **plus the process-isolated `h48_backend` subprocess**. The h48 cross-check
  runs in a separate process and is not statically linked into the student's
  optimal solver, so it does not create a combined-work binary.
- `optimal_solver_nissy` is **opt-in only** (it must be explicitly requested via
  `with_nissy=True` / the corresponding solver flags) and is **excluded from any
  distribution package unless that package is itself GPL-3.0-or-later licensed
  with the complete corresponding source provided**.

## Generated Tables and Result Files

The generated result files and table binaries are research artifacts. Their
algorithmic provenance is recorded by the scripts and JSON metadata that
created them. They are not separate license grants.

Key generated H48 table paths:

```text
data/generated/h48/thesis_seed_2026/h48h0.bin
data/generated/h48/thesis_seed_2026/h48h7.bin
```

Key generated H48 metadata:

```text
results/processed/h48_metadata_seed_2026_thesis_h48h0.json
results/processed/h48_metadata_seed_2026_thesis_h48h7.json
```

## BLOCKING release gate (supervisor license decision required)

**This is a hard, blocking gate, not advisory.** A public push, a public
release, or a submission package **MUST NOT proceed** until the supervisor (or
institution) has recorded an **explicit, written license decision** that covers
**all** of the copyleft components listed below. No automated step and no
contributor may bypass this gate.

The release decision MUST explicitly cover:

- **Vendored GPL-3.0-or-later `nissy-core` H48 source** under
  `native/h48_backend/third_party/nissy_core/` (its presence in the repository
  and any redistribution of it).
- **The optional GPL-3.0-or-later Nissy 2.0.8 static link** in
  `optimal_solver_nissy`. If this opt-in combined-work binary (or its build
  inputs) is to be shipped, the entire distribution must be GPL-3.0-or-later
  with complete corresponding source; otherwise it must be excluded.
- **The GPLv2 PyPI `kociemba` dependency** (non-exact baseline). Shipping the
  repository with this dependency declared, vendored, or bundled is subject to
  GPLv2 copyleft and requires an explicit decision.

The release decision SHOULD also record agreement on:

- treating the H48/Nissy/RubikOptimal/`kociemba` paths as public-solver-derived
  or comparison-baseline evidence rather than original student implementation;
- redistributing any external source caches, generated large tables, public
  table entries, or result artifacts derived from those components;
- the final thesis wording for attribution, non-originality boundaries,
  exactness claims, and every-state runtime limitations.

Until that written decision exists and is referenced from the release, the
default shipped configuration is the **non-nissy `optimal_solver` + the
process-isolated `h48_backend` subprocess**, with `optimal_solver_nissy` and the
GPL `nissy-core` redistribution held back.
