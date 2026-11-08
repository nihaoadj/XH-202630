"""实操指南 (practice guide) adapter: full V3 payload + rendered Markdown."""

from __future__ import annotations

import copy

from app.agents.resource_agents.practice import render_practice_guide_markdown
from app.models.shared.agent_contracts import PracticeGuidePackageV3
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

PRACTICE_RULE_IDS = ("self_contained", "target_coverage", "difficulty", "organization", "procedure")

PHASE_FIELDS = {
    "prepare": ("goal", "items", "evidence_ids"),
    "practice": ("goal", "steps"),
    "verify": ("goal", "checklist", "evidence_ids"),
    "reflect": ("goal", "summary", "evidence_ids"),
}
STEP_FIELDS = ("title", "instruction_text", "code_blocks", "verification", "evidence_ids")


def practice_comparison_projection(package: dict) -> dict:
    projection = copy.deepcopy(package)
    for step in projection.get("practice", {}).get("steps", []):
        step["step_id"] = "MECH_STEP"
    return projection


class PracticeAdapter:
    resource_type = "实操指南"
    schema_version = "1.0"

    def build_location_index(self, *, resource, evidence, targets):
        package = resource.practice_guide_payload or {}
        steps = package.get("practice", {}).get("steps", [])
        unit_fields = {phase: frozenset(fields) for phase, fields in PHASE_FIELDS.items()}
        for step in steps:
            unit_fields[step.get("step_id")] = frozenset(STEP_FIELDS)
        return LocationIndex(
            unit_ids=frozenset({*PHASE_FIELDS.keys(), *(step.get("step_id") for step in steps)}),
            unit_fields=unit_fields,
            root_allowed=True,
        )

    def build_material(self, *, resource, evidence, spec, targets):
        text = resource.content_text or ""
        payload = resource.practice_guide_payload
        index = self.build_location_index(resource=resource, evidence=evidence, targets=targets)
        if not isinstance(payload, dict):
            # Structure gate fails first; material still exposes text identity.
            return ResourceMaterial(
                resource_type=self.resource_type, text=text, structured_payload=None,
                text_exact_hash=text_hash(text), structured_payload_hash=None,
                artifact_exact_hash=combined_exact_hash(text, None),
                comparison_hash=comparison_text_hash(text),
                comparison_projection=comparison_text_hash(text), presentation_comparison=None,
                index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
                difficulty=resource.difficulty, rule_ids=PRACTICE_RULE_IDS,
                projection_consistent=False,
            )
        projection = practice_comparison_projection(payload)
        rendered = render_practice_guide_markdown(payload)
        # GeneratedArtifact strips outer whitespace; accept both renderer and stored form.
        consistent = text in (rendered, rendered.strip())
        presentation = render_practice_guide_markdown(projection) if consistent else None
        return ResourceMaterial(
            resource_type=self.resource_type, text=text, structured_payload=payload,
            text_exact_hash=text_hash(text), structured_payload_hash=canonical_hash(payload),
            artifact_exact_hash=combined_exact_hash(text, payload),
            comparison_hash=comparison_hash_material(projection, presentation),
            comparison_projection=projection, presentation_comparison=presentation,
            index=index, targets=tuple(targets), evidence_hashes=evidence_hashes(evidence),
            difficulty=resource.difficulty, rule_ids=PRACTICE_RULE_IDS,
            projection_consistent=consistent,
        )

    def validate_findings(self, *, output, material, open_issues=None):
        if output.findings:
            from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
                ValidationError,
            )
            raise ValidationError("FINDING_INVALID", "findings", "practice guide cannot carry findings")

    def project_public_summary(self, *, decision, output, material):
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.decisions import (
            project_public_summary,
        )
        return project_public_summary(decision=decision, output=output, material=material)
