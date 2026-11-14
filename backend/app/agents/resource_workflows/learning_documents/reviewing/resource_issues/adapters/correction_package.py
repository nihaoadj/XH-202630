"""个性化纠错训练包 (correction package) adapter: prose-first material."""

from __future__ import annotations

from dataclasses import replace

from .lecture import LectureAdapter

CORRECTION_RULE_IDS = ("self_contained", "target_coverage", "difficulty")


class CorrectionPackageAdapter(LectureAdapter):
    resource_type = "个性化纠错训练包"
    schema_version = "1.0"

    def build_location_index(self, *, resource, evidence, targets):
        if resource.correction_package_payload is not None:
            return self.build_material(resource=resource, evidence=evidence, spec=None, targets=targets).index
        return super().build_location_index(resource=resource, evidence=evidence, targets=targets)

    def build_material(self, *, resource, evidence, spec, targets):
        if resource.correction_package_payload is not None:
            from app.core.learning_documents.correction_package import validated_correction_package, correction_audit_source
            from .base import LocationIndex, ResourceMaterial, text_hash, combined_exact_hash, canonical_hash, evidence_hashes, paragraphs, paragraph_heading_paths
            package = validated_correction_package(resource, targets=targets)
            audit = correction_audit_source(package)
            payload = package.model_dump(mode="json")
            text = resource.content_text or ""
            # Hashes bind the complete artifact. Semantic locations only index
            # content leaves, so status headings can never be cited as issues.
            index = LocationIndex(paragraph_ids=frozenset(paragraphs(audit.text)),
                paragraph_text=paragraphs(audit.text),
                heading_paths={k: tuple(v) for k,v in paragraph_heading_paths(audit.text).items()},
                unit_ids=frozenset({"content"}),
                unit_fields={"content": frozenset(f.path for f in audit.fields)}, root_allowed=True)
            comparison = package.content.model_dump(mode="json")
            return ResourceMaterial(resource_type=self.resource_type, text=text, structured_payload=payload,
                text_exact_hash=text_hash(text), structured_payload_hash=canonical_hash(payload),
                artifact_exact_hash=combined_exact_hash(text, payload),
                comparison_hash=canonical_hash(comparison), comparison_projection=comparison,
                presentation_comparison=None, index=index, targets=tuple(targets),
                evidence_hashes=evidence_hashes(evidence), difficulty=resource.difficulty, rule_ids=CORRECTION_RULE_IDS)
        material = super().build_material(resource=resource, evidence=evidence, spec=spec, targets=targets)
        return replace(material, rule_ids=CORRECTION_RULE_IDS)
