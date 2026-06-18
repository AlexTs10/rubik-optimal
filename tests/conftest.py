"""Shared pytest configuration for the Rubik-optimal test suite.

Registers the two custom markers the core requirement-defending tests use so
that ``-m native`` / ``-m "not native"`` deselection works without emitting
``PytestUnknownMarkWarning`` and without depending on ``pyproject.toml`` (which
is owned by another work-stream).

Also exposes a small fixture that warms the corner/edge pattern-database cache
once per session, so the randomized BFS-exact optimality test does not pay the
PDB load cost on every parametrized case.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "native: requires the compiled native C++ binary "
        "(native/build/optimal_solver); deselect with -m 'not native' when the "
        "binary is absent or being rebuilt.",
    )
    config.addinivalue_line(
        "markers",
        "infrastructure: exercises cloud/oracle scaffolding rather than the "
        "thesis-core required algorithms.",
    )


@pytest.fixture(scope="session")
def warm_pattern_databases() -> bool:
    """Load the corner/edge PDB lower-bound caches once.

    Returns ``True`` if the native PDB artifacts are present (so a heuristic
    backed by them is in play), ``False`` otherwise.  Either way the combined
    lower bound is callable and admissible; the return value just lets a test
    note whether the strong PDB component is active.
    """

    from rubik_optimal.cube import CubeState
    from rubik_optimal.search.heuristics import combined_table_lower_bound
    from rubik_optimal.tables.edge_pdb import edge_pdbs_available

    # Touch the cached projection/PDB tables so the first parametrized case in a
    # test does not absorb the one-time build/load cost.
    combined_table_lower_bound(CubeState.from_sequence("R U"))
    return edge_pdbs_available()
