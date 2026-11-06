"""V3 practice covers and teaching metadata, with optional code rules."""
import re
from app.core.courseware.content_review.adapters.base import DeclaredAdapter
from app.core.courseware.content_review.projections import practice_projection
from app.models.courseware.content import CoursewarePlanEnrichmentV2
from app.models.shared.agent_contracts import PracticeGuidePackageV3


class PracticeGuideAdapter(DeclaredAdapter):
    version = "practice-guide-v1"
    source_key = "practice_guide_payload"
    source_model = PracticeGuidePackageV3
    candidate_model = CoursewarePlanEnrichmentV2
    candidate_slot = "enrichment"

    def refine_design(self, snapshot, design):
        payload = self.validate_source(snapshot)
        steps = {s["step_id"]: s for s in payload["practice"]["steps"]}
        raw = design.model_dump(mode="json")
        for slot in raw["storyboard"]["scenes"]:
            bound = {b["practice_step_id"] for b in snapshot["blocks"] if b["block_id"] in slot["source_block_ids"] and b.get("practice_step_id")}
            if len(bound) == 1 and not steps[next(iter(bound))]["code_blocks"]:
                slot["content_budget"]["min_zones"] = 3
        return type(design).model_validate(raw)

    def fields(self, candidate, design):
        rules = ["factual_support", "scope_alignment", "learning_guidance", "procedural_consistency"]
        codes = [code for step in design["source_payload"]["practice"]["steps"] for code in step.get("code_blocks", [])]
        code_markers = {"代码", "命令", "版本", *[b["language"].casefold() for b in codes if b["language"] != "text"]}
        command_or_version = re.compile(r"\b(?:pip\d?|python\d?|npm|npx|node|git|docker|kubectl|conda|poetry|uv|apt|brew|curl|wget|powershell|bash|sh|yarn|pnpm)\b|\d+\.\d+(?:\.\d+)?|(?:==|>=|<=|≥|≤|\^|~)\s*\d|```|\b(?:import|from|def|class|function|const|let|var)\s+\w", re.IGNORECASE)
        def selected(value):
            return [*rules, "code_constraints"] if codes and (any(marker in value.casefold() for marker in code_markers) or command_or_version.search(value)) else rules
        for key, maximum, used in (("course_title", 160, True), ("course_summary", 500, False)):
            if key in candidate:
                yield "course", [key], maximum, used, selected(candidate[key])
        for key in ("cover_title", "cover_lead", "learning_goal", "learning_method", "completion_standard"):
            if candidate.get("practice_cover"):
                yield "cover", ["practice_cover", key], 120 if key == "cover_title" else 360, True, selected(candidate["practice_cover"][key])
        known = {"objectives": {o["objective_id"] for o in design["learning_design"]["objectives"]["objectives"]},
                 "scenes": {s["scene_id"] for s in design["learning_design"]["storyboard"]["scenes"] if s["kind"] != "recap"}}
        for collection, id_key in (("objectives", "objective_id"), ("scenes", "scene_id")):
            for index, item in enumerate(candidate.get(collection, [])):
                if item[id_key] not in known[collection]:
                    raise ValueError("unknown enrichment owner")
                for key in ("title", "teaching_intent"):
                    # Scene prose is persisted as teaching metadata. Objective
                    # enrichment is discarded by the established blueprint.
                    yield item[id_key], [collection, index, key], 160 if key == "title" else 240, collection == "scenes", selected(item[key])
                if collection == "scenes":
                    slot = next(s for s in design["learning_design"]["storyboard"]["scenes"] if s["scene_id"] == item[id_key])
                    if not set(item.get("preferred_component_ids", [])) <= set(slot["allowed_component_ids"]):
                        raise ValueError("component preference outside frozen slot")

    def validate_projection(self, snapshot, design, candidate, document):
        self.validate_source(snapshot)
        return practice_projection(snapshot, design, candidate, document)
