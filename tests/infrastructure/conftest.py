"""Pytest configuration for the cloud/oracle infrastructure test suite.

Auto-applies the registered ``infrastructure`` marker (see the root
``tests/conftest.py`` and ``pyproject.toml``) to every test collected from
this directory, so that ``-m infrastructure`` / ``-m "not infrastructure"``
selection works as documented instead of being a no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_INFRASTRUCTURE_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path is not None and item.path.resolve().is_relative_to(_INFRASTRUCTURE_DIR):
            item.add_marker(pytest.mark.infrastructure)
