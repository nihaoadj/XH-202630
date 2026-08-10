"""Deterministic P0-06 competition metrics over reproducible fixtures."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.models.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimMetricStatus,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.schemas import LearningResource


class CompetitionClaimMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_status: ClaimMetricStatus
    claim_hallucination_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    factual_claim_total: int = Field(ge=0)
    unsupported_claim_total: int = Field(ge=0)
    target_skill_total: int = Field(ge=0)
    covered_skill_total: int = Field(ge=0)
    knowledge_coverage_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class DifficultyFixtureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    fixture_version: str
    expected_difficulty: str
    predicted_difficulty: str


class DifficultyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_version: str
    case_total: int = Field(ge=0)
    correct_total: int = Field(ge=0)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    labels: list[str]
    confusion_matrix: dict[str, dict[str, int]]


def final_published_leaf_ids(resources: Iterable[LearningResource]) -> set[str]:
    items = list(resources)
    parent_ids = {item.parent_resource_id for item in items if item.parent_resource_id}
    return {
        item.resource_id
        for item in items
        if item.publication_status == "published" and item.resource_id not in parent_ids
    }


def compute_competition_claim_metrics(
    *,
    resources: Iterable[LearningResource],
    claims: Iterable[ClaimRecord],
    judgements: Iterable[ClaimJudgement],
    target_skill_node_ids: Iterable[str],
) -> CompetitionClaimMetrics:
    leaf_ids = final_published_leaf_ids(resources)
    selected_claims = [
        item for item in claims
        if item.resource_id in leaf_ids and item.claim_type == ClaimType.FACTUAL
    ]
    completed = {
        item.claim_id: item
        for item in judgements
        if item.resource_id in leaf_ids and item.status == ClaimJudgementStatus.COMPLETED
    }
    incomplete = [item for item in selected_claims if item.claim_id not in completed]
    unsupported = sum(
        completed[item.claim_id].verdict in {ClaimVerdict.CONTRADICTED, ClaimVerdict.NOT_IN_EVIDENCE}
        for item in selected_claims
        if item.claim_id in completed
    )
    target_ids = set(target_skill_node_ids)
    covered_ids = {
        item.knowledge_point_id
        for item in selected_claims
        if item.knowledge_point_id in target_ids
        and item.claim_id in completed
        and completed[item.claim_id].verdict == ClaimVerdict.SUPPORTED
    }
    if incomplete:
        metric_status = ClaimMetricStatus.INCOMPLETE
        hallucination_rate = None
    elif not selected_claims:
        metric_status = ClaimMetricStatus.NOT_APPLICABLE
        hallucination_rate = 0.0
    else:
        metric_status = ClaimMetricStatus.COMPLETE
        hallucination_rate = unsupported / len(selected_claims)
    return CompetitionClaimMetrics(
        metric_status=metric_status,
        claim_hallucination_rate=hallucination_rate,
        factual_claim_total=len(selected_claims),
        unsupported_claim_total=unsupported,
        target_skill_total=len(target_ids),
        covered_skill_total=len(covered_ids),
        knowledge_coverage_rate=(len(covered_ids) / len(target_ids)) if target_ids else None,
    )


def evaluate_difficulty_fixtures(
    results: Iterable[DifficultyFixtureResult],
) -> DifficultyEvaluation:
    items = list(results)
    fixture_versions = {item.fixture_version for item in items}
    if len(fixture_versions) > 1:
        raise ValueError("difficulty results must use one fixture_version")
    labels = sorted({value for item in items for value in (item.expected_difficulty, item.predicted_difficulty)})
    matrix = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    correct = 0
    for item in items:
        matrix[item.expected_difficulty][item.predicted_difficulty] += 1
        correct += item.expected_difficulty == item.predicted_difficulty
    return DifficultyEvaluation(
        fixture_version=next(iter(fixture_versions), "unavailable"),
        case_total=len(items),
        correct_total=correct,
        accuracy=(correct / len(items)) if items else None,
        labels=labels,
        confusion_matrix=matrix,
    )
