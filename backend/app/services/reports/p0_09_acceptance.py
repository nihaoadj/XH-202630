"""Deterministic P0-09 fixture and competition metric contracts.

This module does not call a model, mutate the demo database, or turn a small
fixture into a competition claim.  The CLI runner composes existing executable
specifications around these contracts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.retrieval.knowledge_base import chunk_documents, load_documents


SUITE_ID = "p0-09-demo-suite"
SUITE_VERSION = "v1"
FIXTURE_VERSION = "v1"
OFFICIAL_MINIMUM_SAMPLE_COUNT = 50
AcceptanceStatus = Literal["PASS", "FAIL", "SKIP", "NOT_MEASURABLE"]


@dataclass(frozen=True)
class MetricGate:
    metric_id: str
    official_definition: str
    official_threshold: str
    formula: str
    sample_count: int
    actual_value: float | None
    status: AcceptanceStatus
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "official_definition": self.official_definition,
            "official_threshold": self.official_threshold,
            "formula": self.formula,
            "sample_count": self.sample_count,
            "actual_value": self.actual_value,
            "status": self.status,
            "evidence": self.evidence,
        }


def default_suite_path() -> Path:
    # This service now lives one domain package deeper than the former flat
    # services module; keep the fixture rooted at backend/tests.
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "p0_09" / "suite.json"


def load_suite(path: str | Path | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else default_suite_path()
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_suite(payload, fixture_path.parent)
    return payload


def validate_suite(payload: dict[str, Any], fixture_root: Path) -> None:
    if payload.get("suite_id") != SUITE_ID:
        raise ValueError("unexpected P0-09 suite_id")
    if payload.get("suite_version") != SUITE_VERSION:
        raise ValueError("unexpected P0-09 suite_version")
    if payload.get("fixture_version") != FIXTURE_VERSION:
        raise ValueError("unexpected P0-09 fixture_version")

    learners = payload.get("learners") or []
    if {item.get("profile") for item in learners} != {
        "beginner",
        "intermediate",
        "advanced",
    }:
        raise ValueError("P0-09 requires beginner/intermediate/advanced learners")
    if len({item.get("learner_id") for item in learners}) != len(learners):
        raise ValueError("P0-09 learner IDs must be unique")
    if len(set(payload.get("resource_types") or [])) < 3:
        raise ValueError("P0-09 requires at least three resource forms")

    attempt_ids = {item.get("id") for item in payload.get("attempts") or []}
    if attempt_ids != {
        "attempt-low",
        "attempt-mid",
        "attempt-high",
        "attempt-high-blocker",
    }:
        raise ValueError("P0-09 attempt fixture set is incomplete")
    required_reviews = {"approve", "revise", "reject", "human_review", "invalid_output"}
    if set(payload.get("review_cases") or []) != required_reviews:
        raise ValueError("P0-09 review fixture set is incomplete")
    required_claims = {
        "all_supported",
        "contradicted",
        "not_in_evidence",
        "non_factual",
        "mixed",
    }
    if set(payload.get("claim_cases") or []) != required_claims:
        raise ValueError("P0-09 claim fixture set is incomplete")
    required_failures = {
        "llm_timeout",
        "llm_schema_invalid",
        "reviewer_failure",
        "claim_judge_failure",
        "retriever_no_hit",
        "retriever_infrastructure_error",
        "persistence_conflict",
        "sse_disconnect",
        "stale_profile_version",
        "duplicate_idempotency_key",
    }
    if set(payload.get("failure_injections") or []) != required_failures:
        raise ValueError("P0-09 failure injection matrix is incomplete")

    knowledge_dir = fixture_root / "knowledge"
    documents = load_documents(str(knowledge_dir.resolve()))
    chunks = chunk_documents(documents, chunk_size=500, chunk_overlap=50)
    knowledge = payload["knowledge"]
    if len(documents) != 1:
        raise ValueError("P0-09 knowledge fixture must contain exactly one active document")
    if documents[0].metadata["document_id"] != knowledge["document_id"]:
        raise ValueError("P0-09 logical document ID drift")
    if documents[0].metadata["document_version"] != knowledge["document_version"]:
        raise ValueError("P0-09 document version drift")
    if [item.metadata["chunk_id"] for item in chunks] != knowledge["chunk_ids"]:
        raise ValueError("P0-09 chunk ID drift")


def evaluate_official_metrics(payload: dict[str, Any]) -> list[MetricGate]:
    """Compute fixture values while refusing to overclaim the official gates."""

    metric_fixture = payload["metric_fixture"]
    claims = metric_fixture["published_leaf_claims"]
    factual = [item for item in claims if item["claim_type"] == "factual"]
    unsupported = [
        item
        for item in factual
        if item["verdict"] in {"contradicted", "not_in_evidence"}
    ]
    hallucination = len(unsupported) / len(factual) if factual else None
    target_points = set(payload["knowledge"]["knowledge_point_ids"])
    supported_points = {
        item["knowledge_point_id"]
        for item in factual
        if item["verdict"] == "supported" and item.get("knowledge_point_id")
    }
    coverage = len(target_points & supported_points) / len(target_points) if target_points else None
    learners = payload["learners"]
    difficulty = (
        sum(item["expected_difficulty"] == item["predicted_difficulty"] for item in learners)
        / len(learners)
        if learners
        else None
    )
    sample_count = len(learners)
    minimum = int(metric_fixture.get("minimum_official_sample_count", OFFICIAL_MINIMUM_SAMPLE_COUNT))
    measurable = sample_count >= minimum
    suffix = (
        f"fixture sample_count={sample_count}; official high-score test plan requires >= {minimum} profiles"
    )
    return [
        MetricGate(
            metric_id="M-HALLUCINATION",
            official_definition="专业知识谬误率（幻觉率）",
            official_threshold="< 5%",
            formula="(contradicted + not_in_evidence) / factual_claim_total on final published leaves",
            sample_count=sample_count,
            actual_value=hallucination,
            status=("PASS" if measurable and hallucination is not None and hallucination < 0.05 else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=suffix,
        ),
        MetricGate(
            metric_id="M-DIFFICULTY",
            official_definition="学习者画像-资源难度适配准确率",
            official_threshold=">= 85%",
            formula="correct expected-vs-predicted difficulty / gold learner fixtures",
            sample_count=sample_count,
            actual_value=difficulty,
            status=("PASS" if measurable and difficulty is not None and difficulty >= 0.85 else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=suffix,
        ),
        MetricGate(
            metric_id="M-COVERAGE",
            official_definition="核心知识点覆盖率",
            official_threshold=">= 90%",
            formula="target knowledge_point_ids covered by supported factual claims on final published leaves",
            sample_count=sample_count,
            actual_value=coverage,
            status=("PASS" if measurable and coverage is not None and coverage >= 0.90 else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=suffix,
        ),
        MetricGate(
            metric_id="M-FEEDBACK-UPLIFT",
            official_definition="反馈后测试提升率（仓库需求，比赛 PDF 无数值阈值）",
            official_threshold="no numeric threshold in competition PDF",
            formula="paired post-test - pre-test over a real learner cohort",
            sample_count=0,
            actual_value=None,
            status="NOT_MEASURABLE",
            evidence="no paired real pre/post-test cohort is stored in the fixture suite",
        ),
    ]


def safe_fixture_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only stable IDs/counts suitable for an acceptance manifest."""

    return {
        "suite_id": payload["suite_id"],
        "suite_version": payload["suite_version"],
        "fixture_version": payload["fixture_version"],
        "knowledge_base_id": payload["knowledge"]["knowledge_base_id"],
        "document_version": payload["knowledge"]["document_version"],
        "chunk_count": len(payload["knowledge"]["chunk_ids"]),
        "knowledge_point_count": len(payload["knowledge"]["knowledge_point_ids"]),
        "learner_profiles": [item["profile"] for item in payload["learners"]],
        "resource_types": list(payload["resource_types"]),
        "attempt_cases": [item["id"] for item in payload["attempts"]],
        "review_cases": list(payload["review_cases"]),
        "claim_cases": list(payload["claim_cases"]),
        "sse_phases": list(payload["sse_phases"]),
        "failure_injections": list(payload["failure_injections"]),
    }


def build_safe_evidence_bundle(
    *,
    run_id: str,
    timeline_summary: dict[str, Any],
    resource_versions: list[dict[str, Any]],
    review_decisions: list[dict[str, Any]],
    claim_metric_summary: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    feedback_summary: dict[str, Any] | None = None,
    child_run_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create an allowlisted export without prompts, model payloads, or learner PII."""

    return {
        "bundle_schema": "p0-09-safe-evidence-v1",
        "run_id": run_id,
        "timeline_summary": {
            key: timeline_summary.get(key)
            for key in ("status", "last_event_sequence", "step_count", "revision_count")
        },
        "resource_versions": [
            {
                key: item.get(key)
                for key in (
                    "resource_id",
                    "resource_type",
                    "version",
                    "parent_resource_id",
                    "review_status",
                    "publication_status",
                )
            }
            for item in resource_versions
        ],
        "review_decisions": [
            {key: item.get(key) for key in ("review_id", "decision", "issue_codes")}
            for item in review_decisions
        ],
        "claim_metric_summary": {
            key: claim_metric_summary.get(key)
            for key in (
                "metric_status",
                "factual_claim_total",
                "supported_count",
                "contradicted_count",
                "not_in_evidence_count",
                "claim_hallucination_rate",
            )
        },
        "evidence": [
            {
                key: item.get(key)
                for key in ("evidence_id", "chunk_id", "document_version", "locator")
            }
            for item in evidence_items
        ],
        "feedback_summary": {
            key: (feedback_summary or {}).get(key)
            for key in (
                "attempt_id",
                "action",
                "profile_version_before",
                "profile_version_after",
                "path_version_before",
                "path_version_after",
            )
        },
        "child_run_ids": list(child_run_ids or []),
    }
