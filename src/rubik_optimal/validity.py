"""Physical-validity helpers."""

from __future__ import annotations

from .cube import CubeState


def validate_cube(cube: CubeState) -> tuple[bool, str]:
    code, message = cube.verify_physical()
    return code == 0, message
