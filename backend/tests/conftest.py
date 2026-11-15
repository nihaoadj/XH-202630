"""Shared pytest configuration for the categorized backend test suite."""

import os
from pathlib import Path

import pytest


# Tests run from the repository root, so ``backend/.env`` is outside the default
# dotenv search path.  Supply the reviewed example window for the required
# resource reviewer context in this test process only: no strategy is disabled,
# no assertion changes, and the real ``.env`` stays untouched.  Tests that need
# to observe a missing value delete it themselves.
os.environ.setdefault("RESOURCE_REVIEW_CONTEXT_TOKENS", "129024")


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
