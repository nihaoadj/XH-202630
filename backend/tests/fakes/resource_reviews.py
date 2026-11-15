"""Synthetic, answer-bearing inputs shared by deterministic review tests."""

import copy
import json
from pathlib import Path

from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.review_audit import ReviewPolicySnapshotV1


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/resource_reviews/manifest.json"


def approve():
    return {"decision": "approve", "hallucination_score": 0.0, "issues": [],
            "difficulty_match": True, "coverage_rate": 1.0,
            "suggestion": "符合冻结审核约束。", "revision_instructions": []}


def case(case_id="practice.clean.01"):
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return copy.deepcopy(next(c for c in manifest["cases"] if c["case_id"] == case_id))


def state_for(sample=None, *, strategy="two_stage_v1", window=262144):
    sample = sample or case()
    resource = LearningResource.model_validate(sample["resource"])
    return {
        "run_id": "run-review-test", "batch_id": "batch-review-test", "trace": [], "errors": [],
        "generated_resources": [resource], "retrieved_evidence": [EvidenceItem.model_validate_json(json.dumps(e)) for e in sample["evidence"]],
        "target_skill_nodes": sample["target_skill_nodes"], "difficulty_preference": "初级",
        "generation_attempt": 1, "revision_count": 0, "constraints": {},
        "review_policy": ReviewPolicySnapshotV1(assessment_strategy=strategy,
            combined_context_tokens=window if strategy == "combined_v2" else None).model_dump(mode="json"),
    }


def questions(sample):
    return [q for block in sample["resource"]["assessment_payload"]["node_blocks"]
            for field in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions") for q in block[field]]


def combined_output(sample, *, failed_ids=(), scope="out_of_scope"):
    return {"schema_version": "2.0", "summary": approve(), "findings": [{
        "question_id": q["question_id"], "scope_decision": scope if q["question_id"] in failed_ids else "in_scope",
        "supported_evidence_ids": [] if q["question_id"] in failed_ids else q["evidence_ids"][:1],
        "answer_check": "pass", "clarity_check": "pass",
        "rubric_check": "pass" if q["question_type"] == "short_answer" else "not_applicable",
        "reason": "测试安全定位。",
    } for q in questions(sample)]}


def scope_output(sample):
    return {"findings": [{"question_id": q["question_id"], "decision": "in_scope",
                          "supported_evidence_ids": q["evidence_ids"][:1], "reason": "符合节点范围。"} for q in questions(sample)]}
