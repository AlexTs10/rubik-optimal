"""Solver entry points."""

from .base import SolverResult
from .korf import solve_korf_ida
from .h48_native import (
    compute_h48_native_lower_bound,
    compute_h48_native_rotational_lower_bound,
    solve_h48_native_optimal,
)
from .optimal_native import solve_korf_native_optimal
from .kociemba import solve_kociemba_adapter
from .kociemba_optimal import solve_kociemba_two_phase_optimal
from .nissy_external import (
    solve_nissy_core_direct_optimal,
    solve_nissy_light_optimal,
    solve_nissy_light_optimal_batch,
    solve_nissy_optimal,
    solve_nissy_optimal_batch,
)
from .rubikoptimal_external import solve_rubikoptimal_external
from .thistlethwaite import solve_thistlethwaite_native_full, solve_thistlethwaite_scoped

__all__ = [
    "SolverResult",
    "solve_kociemba_adapter",
    "solve_kociemba_two_phase_optimal",
    "solve_h48_native_optimal",
    "compute_h48_native_lower_bound",
    "compute_h48_native_rotational_lower_bound",
    "solve_korf_ida",
    "solve_korf_native_optimal",
    "solve_nissy_core_direct_optimal",
    "solve_nissy_light_optimal",
    "solve_nissy_light_optimal_batch",
    "solve_nissy_optimal",
    "solve_nissy_optimal_batch",
    "solve_rubikoptimal_external",
    "solve_thistlethwaite_native_full",
    "solve_thistlethwaite_scoped",
]
