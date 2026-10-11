"""Structural refactors preserve production workflow artifacts and gate outcomes.

The fixture was captured before T13's complexity and runtime extraction. It
contains synthetic inputs only. Fix identities and clock so HTML byte hashes
compare output rather than per-run metadata; keep every original gate outcome.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.agents.resource_workflows.interactive_courseware import workflow
from app.db.courseware import repository
from scripts.courseware_harness.offline import execute_workflow_case

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "courseware" / "evals"
CASES = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))["cases"]
BASELINE = json.loads((FIXTURE_DIR / "workflow-baseline.json").read_text(encoding="utf-8"))


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 10, tzinfo=timezone.utc) if tz else cls(2026, 10, 10)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_workflow_matches_pre_extraction_baseline(case, monkeypatch):
    counter = iter(range(1, 10_000))
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter)))
    monkeypatch.setattr(repository, "_now", lambda: FixedDateTime.now(timezone.utc))
    monkeypatch.setattr(workflow, "datetime", FixedDateTime)

    actual = execute_workflow_case(case)
    expected = BASELINE[case["id"]]

    assert {key: actual.get(key) for key in expected} == expected
