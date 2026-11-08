"""复习清单 (review checklist) adapter: full active-recall package + Markdown."""

from __future__ import annotations

import copy

from app.agents.resource_agents.checklist import render_review_practice_markdown
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

CHECKLIST_RULE_IDS = ("self_contained", "target_coverage", "difficulty", "organization")

CHECKLIST_QUESTION_FIELDS = ("prompt", "reference_answer", "explanation", "evidence_ids",
                             "pass_criteria", "statement", "truth_value", "correction",
                             "candidate_a", "candidate_b", "positive_candidate",
                             "decisive_boundary")
NODE_FIELDS = ("knowledge_summary", "summary_evidence_ids", "evidence_ids", "omitted_slots")


def checklist_questions(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for block in payload.get("node_blocks", []):
        for field_name in ("recall_questions", "distinction_questions"):
            for question in block.get(field_name, []):
                rows.append({**question, "skill_node_id": block.get("skill_node_id")})
        for question in block.get("example_recognition_questions") or []:
            rows.append({**question, "skill_node_id": block.get("skill_node_id")})
    return rows


def checklist_comparison_projection(package: dict) -> dict:
    projection = copy.deepcopy(package)
    projection.pop("payload_hash", None)
    for block in projection.get("node_blocks", []):
        for field_name in ("recall_questions", "distinction_questions", "example_recognition_questions"):
            for question in block.get(field_name, []):
                question["question_id"] = "MECH_Q"
    return projection


class ChecklistAdapter:
    resource_type = "复习清单"
    schema_version = "1.0"

    def build_location_index(self, *, resource, evidence, targets):
        payload = resource.review_practice_payload or {}
        unit_fields: dict[str, frozenset[str]] = {}
        for block in payload.get("node_blocks", []):
            unit_fields[block.get("skill_node_id")] = frozenset(NODE_FIELDS)
            for question in checklist_questions({"node_blocks": [block]}):
                unit_fields[question["question_id"]] = frozenset(CHECKLIST_QUESTION_FIELDS)
        questions = checklist_questions(payload)
        return LocationIndex(
            unit_ids=frozenset({*(block.get("skill_node_id") for block in payload.get("node_blocks", [])),
                                *(q["question_id"] for q in questions)}),
            unit_fields=unit_fields,
            root_allowed=True,
        )

    def build_material(self, *, resource, evidence, spec, targets):
        text = resource.content_text or ""
        payload = resource.review_practice_payload
        index = self.build_location_index(resource=resource, evidence=evidence, targets=targets)
        if not isinstance(payload, dict):
            return ResourceMaterial(
                resource_type=self.resource_type, text=text, structured_payload=None,
                text_exact_hash=text_hash(text), structured_payload_hash=None,
                artifact_exact_hash=combined_exact_hash(text, None),
                comparison_hash=comparison_text_hash(text),
                comparison_projection=comparison_text_hash(text), presentation_comparison=None,
                index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
                difficulty=resource.difficulty, rule_ids=CHECKLIST_RULE_IDS,
                projection_consistent=False,
            )
        projection = checklist_comparison_projection(payload)
        rendered = render_review_practice_markdown(payload)
        # GeneratedArtifact strips outer whitespace; accept both renderer and stored form.
        consistent = text in (rendered, rendered.strip())
        presentation = render_review_practice_markdown(projection) if consistent else None
        return ResourceMaterial(
            resource_type=self.resource_type, text=text, structured_payload=payload,
            text_exact_hash=text_hash(text), structured_payload_hash=canonical_hash(payload),
            artifact_exact_hash=combined_exact_hash(text, payload),
            comparison_hash=comparison_hash_material(projection, presentation),
            comparison_projection=projection, presentation_comparison=presentation,
            index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
            difficulty=resource.difficulty, rule_ids=CHECKLIST_RULE_IDS,
            projection_consistent=consistent,
        )

    def validate_findings(self, *, output, material, open_issues=None):
        if output.findings:
            from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
                ValidationError,
            )
            raise ValidationError("FINDING_INVALID", "findings", "checklist cannot carry findings")

    def project_public_summary(self, *, decision, output, material):
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.decisions import (
            project_public_summary,
        )
        return project_public_summary(decision=decision, output=output, material=material)
