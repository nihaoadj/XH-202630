"""讲义 (lecture) adapter: prose material with paragraph locations."""

from __future__ import annotations

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import (
    LocationIndex,
    ResourceMaterial,
    combined_exact_hash,
    comparison_text_hash,
    evidence_hashes,
    paragraph_heading_paths,
    paragraphs,
    text_hash,
)

LECTURE_RULE_IDS = ("self_contained", "target_coverage", "difficulty", "organization", "synthetic_input")


class LectureAdapter:
    resource_type = "讲义"
    schema_version = "1.0"

    def build_location_index(self, *, resource, evidence, targets):
        text = resource.content_text or ""
        return LocationIndex(
            paragraph_ids=frozenset(paragraphs(text)),
            heading_paths={k: tuple(v) for k, v in paragraph_heading_paths(text).items()},
            paragraph_text=paragraphs(text),
            root_allowed=True,
        )

    def build_material(self, *, resource, evidence, spec, targets):
        text = resource.content_text or ""
        index = self.build_location_index(resource=resource, evidence=evidence, targets=targets)
        return ResourceMaterial(
            resource_type=self.resource_type, text=text, structured_payload=None,
            text_exact_hash=text_hash(text), structured_payload_hash=None,
            artifact_exact_hash=combined_exact_hash(text, None),
            comparison_hash=comparison_text_hash(text), comparison_projection=comparison_text_hash(text),
            presentation_comparison=None, index=index, targets=tuple(targets),
            evidence_hashes=evidence_hashes(evidence), difficulty=resource.difficulty,
            rule_ids=LECTURE_RULE_IDS,
        )

    def validate_findings(self, *, output, material, open_issues=None):
        if output.findings:
            from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
                ValidationError,
            )
            raise ValidationError("FINDING_INVALID", "findings", "prose resources cannot carry findings")

    def project_public_summary(self, *, decision, output, material):
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.decisions import (
            project_public_summary,
        )
        return project_public_summary(decision=decision, output=output, material=material)
