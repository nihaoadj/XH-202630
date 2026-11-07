"""个性化纠错训练包 (correction package) adapter: prose-first material."""

from __future__ import annotations

from dataclasses import replace

from .lecture import LectureAdapter

CORRECTION_RULE_IDS = ("self_contained", "target_coverage", "difficulty")


class CorrectionPackageAdapter(LectureAdapter):
    resource_type = "个性化纠错训练包"
    schema_version = "1.0"

    def build_material(self, *, resource, evidence, spec, targets):
        material = super().build_material(resource=resource, evidence=evidence, spec=spec, targets=targets)
        return replace(material, rule_ids=CORRECTION_RULE_IDS)
