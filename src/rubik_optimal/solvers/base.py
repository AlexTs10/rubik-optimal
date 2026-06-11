"""Shared solver result model."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SolverResult:
    solver_name: str
    input_state: str
    solution_moves: list[str]
    solution_length: int | None
    metric: str
    runtime_seconds: float
    expanded_nodes: int | None
    generated_nodes: int | None
    table_bytes: int | None
    status: str
    is_verified: bool
    notes: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
