"""V2 review: questions/answers remain exact source projections."""
from app.core.courseware.content_review.adapters.base import DeclaredAdapter
from app.core.courseware.content_review.projections import review_projection
from app.models.courseware.content import ReviewPracticeCoursewarePlanEnrichment
from app.models.shared.agent_contracts import ReviewPracticePackageV2


class ReviewPracticeAdapter(DeclaredAdapter):
    version = "review-practice-v1"
    source_key = "review_practice_payload"
    source_model = ReviewPracticePackageV2
    candidate_model = ReviewPracticeCoursewarePlanEnrichment
    candidate_slot = "review_practice_enrichment"

    def fields(self, candidate, design):
        for key in ("course_title", "overview_lead", "learning_scope", "learning_method", "completion_lead", "completion_message", "overall_summary"):
            if key in candidate:
                yield "course", [key], {"course_title": 160, "overall_summary": 800}.get(key, 500), True, ["factual_support", "scope_alignment", "learning_guidance"]
        known = {n["skill_node_id"] for n in design["source_payload"]["node_blocks"]}
        for index, item in enumerate(candidate.get("node_summaries", [])):
            if item["skill_node_id"] not in known:
                raise ValueError("unknown summary owner")
            yield item["skill_node_id"], ["node_summaries", index, "summary"], 500, True, ["factual_support", "scope_alignment", "learning_guidance"]

    def evidence_for(self, owner, available):
        # A node summary cannot borrow another node's answer. Course-wide
        # guidance sees all frozen answers; each node only its own IDs.
        if owner == "course":
            return available
        return [e for e in available if e in {f"node:{owner}", "course:rules"}]

    def validate_source(self, snapshot):
        payload = super().validate_source(snapshot)
        nodes = payload["node_blocks"]
        ids = []
        for node in nodes:
            for q in node["recall_questions"] + node["distinction_questions"] + (node.get("example_recognition_questions") or ([node["example_recognition"]] if node.get("example_recognition") else [])):
                if not q.get("question_id") or not set(q["evidence_ids"]) <= set(node["evidence_ids"]):
                    raise ValueError("review question identity/evidence invalid")
                ids.append(q["question_id"])
        if len(ids) != len(set(ids)) or len({n["skill_node_id"] for n in nodes}) != len(nodes):
            raise ValueError("duplicate frozen owner")
        blocks = {b.get("review_question_id") for b in snapshot["blocks"] if b.get("review_question_id")}
        if set(ids) != blocks:
            raise ValueError("missing frozen question binding")
        return payload

    def validate_projection(self, snapshot, design, candidate, document):
        self.validate_source(snapshot)
        return review_projection(snapshot, candidate, document, design)
