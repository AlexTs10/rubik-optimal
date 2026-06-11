"""Permutation ranking helpers for Rubik coordinate encodings."""

from __future__ import annotations

import math
from collections.abc import Sequence


def rank_permutation(values: Sequence[int]) -> int:
    """Return the lexicographic Lehmer rank of a permutation."""

    n = len(values)
    expected = list(range(n))
    if sorted(values) != expected:
        raise ValueError(f"Expected a permutation of {expected}, got {list(values)}")

    unused = expected.copy()
    rank = 0
    for index, value in enumerate(values):
        digit = unused.index(value)
        rank += digit * math.factorial(n - index - 1)
        unused.pop(digit)
    return rank


def unrank_permutation(rank: int, size: int) -> tuple[int, ...]:
    """Return the permutation with the given lexicographic Lehmer rank."""

    domain_size = math.factorial(size)
    if rank < 0 or rank >= domain_size:
        raise ValueError(f"Permutation rank must be in [0, {domain_size}), got {rank}")

    unused = list(range(size))
    values: list[int] = []
    remaining = rank
    for index in range(size - 1, -1, -1):
        factor = math.factorial(index)
        digit, remaining = divmod(remaining, factor)
        values.append(unused.pop(digit))
    return tuple(values)

