"""Rubik thesis package.

The package deliberately separates exact search results from practical,
non-exact solving so thesis claims can be traced to evidence.
"""

from .cube import CubeState
from .distance import recognize_distance
from .moves import ALL_MOVES, inverse_sequence, parse_sequence
from .oracle import (
    FastOptimalOracle,
    FastOptimalOracleConfig,
    PortfolioOptimalOracle,
    PortfolioOptimalOracleConfig,
    RaceOptimalOracle,
    RaceOptimalOracleConfig,
    ResidentRaceOptimalOracle,
    ResidentRaceOptimalOracleConfig,
    UniversalOptimalOracle,
    UniversalOptimalOracleConfig,
    solve_fast_optimal,
    solve_portfolio_optimal,
    solve_race_optimal,
    solve_resident_race_optimal,
    solve_universal_optimal,
)
from .solvers.kociemba import solve_kociemba_native_scoped
from .solvers.korf import solve_korf_ida
from .solvers.optimal_native import solve_korf_native_optimal
from .solvers.thistlethwaite import (
    solve_thistlethwaite_native_full,
    solve_thistlethwaite_native_scoped,
)

# Backward-compatible alias for the student's primary Thistlethwaite entry point.
solve_thistlethwaite = solve_thistlethwaite_native_full

__all__ = [
    # Core model and notation.
    "ALL_MOVES",
    "CubeState",
    "inverse_sequence",
    "parse_sequence",
    # The student's three required algorithms (Thistlethwaite, Kociemba, Korf)
    # plus distance recognition. These are the primary thesis contributions.
    "solve_thistlethwaite",
    "solve_thistlethwaite_native_full",
    "solve_thistlethwaite_native_scoped",
    "solve_kociemba_native_scoped",
    "solve_korf_ida",
    "solve_korf_native_optimal",
    "recognize_distance",
    # Optimal-search oracle API (H48/Nissy-backed cross-check plumbing).
    "FastOptimalOracle",
    "FastOptimalOracleConfig",
    "PortfolioOptimalOracle",
    "PortfolioOptimalOracleConfig",
    "UniversalOptimalOracle",
    "UniversalOptimalOracleConfig",
    "solve_fast_optimal",
    "solve_portfolio_optimal",
    "solve_universal_optimal",
    # NOTE: RaceOptimalOracle, RaceOptimalOracleConfig, ResidentRaceOptimalOracle,
    # ResidentRaceOptimalOracleConfig, solve_race_optimal, and
    # solve_resident_race_optimal remain importable from this package but are
    # internal cross-check plumbing and are intentionally omitted from __all__.
]
