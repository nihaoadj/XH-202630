from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.learners.mastery import (
    AbilityConfidence,
    AbilityEvidenceV1,
    AbilityMasteryStateV2,
    AbilityStatus,
)


def test_mastery_contracts_are_strict_and_bounded():
    state = AbilityMasteryStateV2(
        learner_id="learner",
        knowledge_base_id="kb",
        skill_node_id="skill-a",
        mastery_score=0.6,
        status=AbilityStatus.LEARNING,
        confidence=AbilityConfidence.MEDIUM,
    )
    assert state.schema_version == "2.0"

    with pytest.raises(ValidationError):
        AbilityMasteryStateV2(
            learner_id="learner",
            knowledge_base_id="kb",
            skill_node_id="skill-a",
            mastery_score=1.01,
            unknown=True,
        )


def test_self_report_evidence_is_explicitly_unverified():
    evidence = AbilityEvidenceV1(
        evidence_id="ev-1",
        learner_id="learner",
        knowledge_base_id="kb",
        skill_node_id="skill-a",
        source_type="onboarding_self_report",
        source_id="submission-1",
        source_hash="a" * 64,
        observed_score=0.2,
        verified=False,
        occurred_at=datetime.now(timezone.utc),
    )
    assert evidence.verified is False

