"""Raw-checkout import shim for the canonical ``src/rubik_optimal`` package.

The canonical, single source of truth for this package lives in
``src/rubik_optimal``. The recommended install is an editable install from this
repository root (``pip install -e .``) or running with ``PYTHONPATH=src``; both
make ``import rubik_optimal`` resolve to the ``src`` tree directly. See
``REPRODUCIBILITY.md`` for the supported invocations.

This thin shim exists only so a *fresh checkout* (run from the repository root
without any install and without ``PYTHONPATH=src``) can still do
``import rubik_optimal`` and ``python -m rubik_optimal.cli``. It deliberately
does NOT redefine the public API: it appends ``src/rubik_optimal`` to this
package's ``__path__`` so every submodule (``rubik_optimal.cli``,
``rubik_optimal.distance``, ``rubik_optimal.solvers.*``, ...) resolves to the
canonical implementation, and then re-exports the canonical package's public
symbols so ``rubik_optimal.__all__`` always mirrors ``src`` with no hand-kept
duplicate list to drift out of date.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "rubik_optimal"

if _SRC_PACKAGE.exists():
    # Make submodule imports (rubik_optimal.cli, rubik_optimal.solvers.korf, ...)
    # resolve to the canonical src implementation rather than this shim dir.
    _src_str = str(_SRC_PACKAGE)
    if _src_str not in __path__:  # type: ignore[name-defined]
        __path__.append(_src_str)  # type: ignore[name-defined]

    # Load the canonical package body (src/rubik_optimal/__init__.py) under a
    # private module name so we can mirror its public API here without a
    # circular ``from rubik_optimal import *``. The loaded module shares this
    # shim's __path__, so its own ``from .submodule import ...`` statements bind
    # to the canonical src submodules.
    _canonical_init = _SRC_PACKAGE / "__init__.py"
    _spec = importlib.util.spec_from_file_location(
        "rubik_optimal._canonical",
        _canonical_init,
        submodule_search_locations=list(__path__),  # type: ignore[name-defined]
    )
    if _spec is not None and _spec.loader is not None:
        _canonical = importlib.util.module_from_spec(_spec)
        # Bind submodule resolution for the canonical body's relative imports.
        _canonical.__package__ = "rubik_optimal"
        sys.modules["rubik_optimal._canonical"] = _canonical
        _spec.loader.exec_module(_canonical)

        _exported = getattr(_canonical, "__all__", None)
        if _exported is None:
            _exported = [n for n in vars(_canonical) if not n.startswith("_")]
        for _name in _exported:
            globals()[_name] = getattr(_canonical, _name)
        __all__ = list(_exported)
    else:  # pragma: no cover - defensive; spec failure is not expected.
        raise ImportError(
            "Could not load canonical rubik_optimal package from "
            f"{_canonical_init!s}"
        )
else:  # pragma: no cover - exercised only outside a source checkout.
    raise ImportError(
        "rubik_optimal root shim could not locate the canonical package at "
        f"{_SRC_PACKAGE!s}. Install with `pip install -e .` from the repo root "
        "or run with PYTHONPATH=src."
    )
