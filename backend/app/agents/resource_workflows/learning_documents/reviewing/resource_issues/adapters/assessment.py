"""分阶测试题 (assessment) adapter: single merged call with per-question findings.

Implements T44 3.1: one model call outputs both the complete per-question
professional findings and the generic dimensions/issues.  The deterministic
scope/finding rules are equivalent to the existing ``prepare_assessment_scope``
/ ``validate_assessment_findings``; the version-bound ``finding_keys`` are
derived here and must be referenced exactly once by the model's issues.
"""

from __future__ import annotations

import copy

from app.agents.resource_agents.assessment import render_assessment_markdown
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import (
    LocationIndex,
    ResourceMaterial,
    canonical_hash,
    combined_exact_hash,
    comparison_hash_material,
    comparison_text_hash,
    evidence_hashes,
    text_hash,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
    ValidationError,
    require,
)

ASSESSMENT_RULE_IDS = ("self_contained", "target_coverage", "difficulty", "organization")

QUESTION_FIELDS = ("single_choice_questions", "multiple_choice_questions", "short_answer_questions")
CHECK_FIELDS = ("stem", "options", "answer_option_ids", "reference_answer", "rubric",
                "knowledge_point_tags", "evidence_ids", "difficulty_stage")


def assessment_questions(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for block in payload.get("node_blocks", []):
        for field_name in QUESTION_FIELDS:
            for question in block.get(field_name, []):
                rows.append({**question, "skill_node_id": block.get("skill_node_id"),
                             "skill_node_name": block.get("skill_node_name")})
    return rows


def assessment_comparison_projection(package: dict) -> dict:
    projection = copy.deepcopy(package)
    for block in projection.get("node_blocks", []):
        for field_name in QUESTION_FIELDS:
            for question in block.get(field_name, []):
                question["question_id"] = "MECH_Q"
    return projection


def finding_key(question_id: str, check_kind: str, failure_code: str) -> str:
    return f"{question_id}:{check_kind}:{failure_code}"


def failed_check_keys(finding: dict, *, question_id: str, objective: bool) -> list[str]:
    """Derive the stable failure keys for one normalized finding."""
    keys: list[str] = []
    decision = finding["scope_decision"]
    if decision != "in_scope":
        keys.append(finding_key(question_id, "scope",
                                "coverage_gap" if decision == "out_of_scope" else "evidence_gap"))
    if finding.get("answer_check") not in (None, "pass"):
        keys.append(finding_key(question_id, "answer",
                                "factual_risk" if finding["answer_check"] == "fail" else "evidence_gap"))
    if finding.get("clarity_check") not in (None, "pass"):
        keys.append(finding_key(question_id, "clarity", "structure_quality"))
    if finding.get("rubric_check") not in (None, "pass", "not_applicable"):
        keys.append(finding_key(question_id, "rubric",
                                "evidence_gap" if finding["rubric_check"] == "insufficient_evidence" else "structure_quality"))
    return keys


class AssessmentAdapter:
    resource_type = "分阶测试题"
    schema_version = "1.0"

    def build_location_index(self, *, resource, evidence, targets):
        payload = resource.assessment_payload or {}
        questions = assessment_questions(payload)
        unit_fields = {q["question_id"]: frozenset(CHECK_FIELDS) for q in questions}
        return LocationIndex(
            unit_ids=frozenset(q["question_id"] for q in questions),
            unit_fields=unit_fields,
            root_allowed=True,
        )

    def build_material(self, *, resource, evidence, spec, targets):
        text = resource.content_text or ""
        payload = resource.assessment_payload
        index = self.build_location_index(resource=resource, evidence=evidence, targets=targets)
        if not isinstance(payload, dict):
            return ResourceMaterial(
                resource_type=self.resource_type, text=text, structured_payload=None,
                text_exact_hash=text_hash(text), structured_payload_hash=None,
                artifact_exact_hash=combined_exact_hash(text, None),
                comparison_hash=comparison_text_hash(text),
                comparison_projection=comparison_text_hash(text), presentation_comparison=None,
                index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
                difficulty=resource.difficulty, rule_ids=ASSESSMENT_RULE_IDS,
                projection_consistent=False,
            )
        projection = assessment_comparison_projection(payload)
        rendered = render_assessment_markdown(payload)
        # GeneratedArtifact strips outer whitespace; accept both renderer and stored form.
        consistent = text in (rendered, rendered.strip())
        presentation = render_assessment_markdown(projection) if consistent else None
        return ResourceMaterial(
            resource_type=self.resource_type, text=text, structured_payload=payload,
            text_exact_hash=text_hash(text), structured_payload_hash=canonical_hash(payload),
            artifact_exact_hash=combined_exact_hash(text, payload),
            comparison_hash=comparison_hash_material(projection, presentation),
            comparison_projection=projection, presentation_comparison=presentation,
            index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
            difficulty=resource.difficulty, rule_ids=ASSESSMENT_RULE_IDS,
            projection_consistent=consistent,
        )

    def validate_findings(self, *, output, material, open_issues=None):
        if material.structured_payload is None or output.findings:
            # Presence of findings is expected for assessment; absence means the
            # model produced no professional check, which is an invalid result.
            require(bool(output.findings), "FINDING_INVALID", "findings",
                    "assessment review requires complete per-question findings")
        payload = material.structured_payload
        questions = assessment_questions(payload)
        expected_ids = [q["question_id"] for q in questions]
        require(bool(expected_ids), "TARGET_EMPTY", "findings", "assessment has no questions")
        by_id = {item.question_id: item for item in output.findings}
        require(set(by_id) == set(expected_ids) and len(by_id) == len(output.findings),
                "FINDING_INVALID", "findings", "findings must cover each question exactly once")
        allowed_by_question = {q["question_id"]: set(q.get("evidence_ids") or []) for q in questions}
        objective = {q["question_id"]: q["question_type"] in {"single_choice", "multiple_choice"}
                     for q in questions}
        derived: list[str] = []
        for question in questions:
            qid = question["question_id"]
            item = by_id[qid]
            supported = item.supported_evidence_ids
            require(len(supported) <= 1 and len(supported) == len(set(supported)),
                    "FINDING_INVALID", f"findings.{qid}.supported_evidence_ids",
                    "at most one supported evidence per question")
            require(not (set(supported) - allowed_by_question[qid]),
                    "FINDING_INVALID", f"findings.{qid}.supported_evidence_ids",
                    "supported evidence outside the question whitelist")
            require(not (item.scope_decision == "in_scope" and len(supported) != 1),
                    "FINDING_INVALID", f"findings.{qid}.supported_evidence_ids",
                    "in_scope requires exactly one supported evidence")
            require(objective[qid] == (item.rubric_check == "not_applicable"),
                    "FINDING_INVALID", f"findings.{qid}.rubric_check",
                    "rubric status incompatible with question type")
            normalized = {"scope_decision": item.scope_decision,
                          "supported_evidence_ids": list(supported),
                          "answer_check": item.answer_check, "clarity_check": item.clarity_check,
                          "rubric_check": item.rubric_check}
            derived.extend(failed_check_keys(normalized, question_id=qid, objective=objective[qid]))
        # The model's issues must reference exactly the derived failure keys,
        # each key owned by exactly one logical issue.
        current_issues = open_issues if open_issues is not None else tuple(issue for issue in output.issues if issue.blocking)
        model_keys: list[str] = []
        for issue in current_issues:
            for key in issue.finding_keys:
                qid = key.split(":", 1)[0]
                require(issue.location.kind == "structured" and issue.location.unit_id == qid,
                        "FINDING_INVALID", "issues.finding_keys",
                        "finding key must belong to the current issue's question location")
                model_keys.append(key)
        require(sorted(model_keys) == sorted(derived), "FINDING_KEY_INCOMPLETE", "issues",
                "issue finding_keys must equal the derived failed-check key set")
        require(len(model_keys) == len(set(model_keys)), "FINDING_KEY_INCOMPLETE", "issues",
                "each finding key must belong to exactly one issue")

    def project_public_summary(self, *, decision, output, material):
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.decisions import (
            project_public_summary,
        )
        return project_public_summary(decision=decision, output=output, material=material)
