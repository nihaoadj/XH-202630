"""案例分析 (case study) adapter: prose material with paragraph locations."""

from __future__ import annotations

from dataclasses import replace

from .lecture import LectureAdapter

CASE_STUDY_RULE_IDS = ("self_contained", "target_coverage", "difficulty", "organization")


class CaseStudyAdapter(LectureAdapter):
    resource_type = "案例分析"
    schema_version = "1.0"

    def build_material(self, *, resource, evidence, spec, targets):
        material = super().build_material(resource=resource, evidence=evidence, spec=spec, targets=targets)
        return replace(material, rule_ids=CASE_STUDY_RULE_IDS)
