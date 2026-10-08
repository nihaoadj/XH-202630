"""Shared pytest configuration for the categorized backend test suite."""

from pathlib import Path

import pytest


_CATEGORY_MARKERS = {
    "unit": "unit",
    "integration": "integration",
    "migrations": "migration",
    "e2e": "e2e",
    "live": "live_llm",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Assign one execution-layer marker from each test file's directory."""

    for item in items:
        path_parts = set(Path(str(item.path)).parts)
        for directory, marker in _CATEGORY_MARKERS.items():
            if directory in path_parts:
                item.add_marker(marker)
                break
