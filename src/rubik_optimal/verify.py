"""Independent solution verification."""

from __future__ import annotations

from dataclasses import dataclass

from .cube import CubeState
from .moves import parse_sequence


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    move_count: int
    message: str


def verify_solution(initial: CubeState, solution: str | list[str] | tuple[str, ...]) -> VerificationResult:
    try:
        moves = parse_sequence(solution)
    except ValueError as exc:
        return VerificationResult(False, 0, str(exc))
    code, message = initial.verify_physical()
    if code != 0:
        return VerificationResult(False, len(moves), f"Invalid physical cube state: {message}")
    final = initial.apply_sequence(moves)
    if not final.is_solved():
        return VerificationResult(False, len(moves), "Solution does not solve the cube")
    return VerificationResult(True, len(moves), "Solution verifies")
