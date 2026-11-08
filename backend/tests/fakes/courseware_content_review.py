"""Synthetic sources and a scripted gateway. No provider or credentials."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json

from app.config import Settings
from app.models.courseware.content_review import json_hash
from app.models.learning_documents.schemas import LearningResource, SourceRef
from app.models.shared.agent_contracts import PracticeGuidePackageV3, ReviewPracticePackageV2
from app.models.shared.llm import LLMCallOptions, LLMCallResult, LLMUsage, StructuredOutputMode


def fixture_settings(**updates):
    values = dict(_env_file=None, courseware_content_review_enabled=True,
        courseware_content_review_context_tokens=262144, courseware_ai_enabled=True, llm_model="fixture-content-review",
        courseware_total_llm_token_budget=262144, courseware_planner_token_budget=90000,
        courseware_scene_composition_token_budget=110000, courseware_quality_review_token_budget=40000,
        courseware_revision_token_budget=22144, courseware_quality_review_reserved_tokens=4000,
        courseware_revision_reserved_tokens=4000)
    return Settings(**{**values, **updates})


def source_package(group="review"):
    if group == "review":
        evidence = ["synthetic-evidence"]
        node = {"skill_node_id": "node-1", "skill_node_name": "冻结来源核对",
            "knowledge_summary": "本节点强调先明确输入和适用边界，再使用冻结来源核对每个结论。闭卷回忆用于发现记忆缺口，概念辨析用于识别必要条件，正反例练习用于确认判断边界。自评仅记录本次学习状态，不代表正式成绩或已经掌握；遇到模糊或不会时，应回到相应题目的原文和答案重新核对。", "summary_evidence_ids": evidence, "evidence_ids": evidence,
            "recall_questions": [{"local_id": f"recall-{i}", "question_id": f"q-{i:03}", "prompt": f"核对来源前的第{i}项检查是什么？",
                "reference_answer": f"先确认第{i}项输入的版本与依据，再记录核对结果。", "explanation": "核对版本、条件和证据可以避免混用来源。", "evidence_ids": evidence, "pass_criteria": "说明输入、条件与依据。"} for i in range(1, 5)],
            "distinction_questions": [{"local_id": f"distinction-{i}", "question_id": f"q-{i+4:03}", "statement": f"第{i}项判断可以省略来源核对。",
                "truth_value": i % 2 == 0, "correction": "按冻结题目给定的条件核对结论。", "explanation": "必须区分给定条件与未确认的推断。", "evidence_ids": evidence, "pass_criteria": "对照给定条件判断。"} for i in range(1, 5)],
            "example_recognition_questions": [{"local_id": f"example-{i}", "question_id": f"q-{i+8:03}", "candidate_a": f"第{i}组：核对输入版本和证据。", "candidate_b": "直接猜测结论。",
                "positive_candidate": "A", "decisive_boundary": "结论能否回到冻结依据。", "explanation": "保留输入与依据，才可复核结论。", "evidence_ids": evidence, "pass_criteria": "指出决定性边界。"} for i in range(1, 3)], "omitted_slots": []}
        raw = ReviewPracticePackageV2(title="冻结来源复习", instructions="先独立完成本节点的闭卷回忆，再揭示答案、记录自评并核对冻结依据；不确定时回到对应题目复盘适用条件。", node_blocks=[node]).model_dump(mode="json", exclude={"payload_hash"})
    else:
        pad = "确认输入、来源、适用条件和记录方式，遇到不符合预期的结果先修正再继续。"
        code = [{"language": "python", "code": "value = 1\nassert value == 1", "purpose": "核对确定性赋值与结果。", "evidence_ids": ["synthetic-evidence"]}] if group == "practice_code" else []
        raw = PracticeGuidePackageV3.model_validate({"schema_version": "3.0", "title": "冻结来源实操",
            "preparation": {"goal": "准备核对环境并记录本轮输入。"+pad*2, "items": [f"准备项目{i}："+pad for i in range(1, 4)], "evidence_ids": ["synthetic-evidence"]},
            "practice": {"goal": "核对输入和结果。", "steps": [{"step_id": "step-1", "title": "核对当前结果", "instruction_text": "打开记录表，核对输入版本并记录实际结果。"+pad*3,
                "code_blocks": code, "verification": "实际结果与冻结预期一致，记录差异后再继续。"+pad, "evidence_ids": ["synthetic-evidence"]}]},
            "verification": {"goal": "逐项验证结果。"+pad*2, "checklist": [f"验证项目{i}："+pad for i in range(1, 4)], "evidence_ids": ["synthetic-evidence"]},
            "reflection": {"goal": "复盘条件与证据。"+pad*2, "summary": "记录结果、适用条件、失败现象和修正动作。"+pad*4, "evidence_ids": ["synthetic-evidence"]}}).model_dump(mode="json")
    return {**raw, "payload_hash": json_hash(raw)}


def resource(group="review", *, resource_id=None, version=1, document_version="legacy-doc-v1"):
    package = source_package(group)
    key = "review_practice_payload" if group == "review" else "practice_guide_payload"
    return LearningResource(resource_id=resource_id or f"fixture-{group}", learner_id="content-learner", resource_type="复习清单" if group == "review" else "实操指南",
        topic="冻结来源核对", difficulty="初级", knowledge_points=["冻结来源核对"], version=version, publication_status="published", content_text="冻结来源：核对输入、条件和结果，保留证据以便复盘。",
        source_refs=[SourceRef(doc_id="frozen-doc", title="合成来源", snippet="先确认输入版本与适用条件，再核对实际结果并记录证据。", score=1, knowledge_base_id="content-kb", document_version=document_version, chunk_id="frozen-chunk", evidence_id="synthetic-evidence")],
        **{key: package, key+"_hash": package["payload_hash"]})


def candidate(group="review"):
    if group == "review":
        return {"course_title": "冻结来源复习", "overview_lead": "先独立回忆并核对适用条件，再揭示答案、查看依据并完成自评。", "learning_scope": "核对本轮输入、条件与冻结依据。", "learning_method": "先回忆，再辨析与辨认正反例，最后核对来源。",
            "completion_lead": "回顾本轮各道题目的自评记录，并确认仍需回看的条件与来源。", "completion_message": "不确定时返回对应节点核对依据，重新闭卷回忆并说明自己的判断条件。", "overall_summary": "本轮围绕冻结来源核对输入、条件与结果。完成闭卷回忆、概念辨析和正反例辨认后，回到模糊或不会的题目核对证据。复盘时保留适用条件与证据边界，区分已确认的输入和仍缺少支持的判断；自评只描述当前学习状态，不应当作正式成绩或掌握证明。", "node_summaries": [{"skill_node_id": "node-1", "summary": "对照本节点的冻结依据复盘输入与条件。"}]}
    return {"schema_version": "2.0", "course_title": "冻结来源实操", "course_summary": "未消费的辅助摘要", "objectives": [], "scenes": [],
        "practice_cover": {"cover_title": "核对输入与结果", "cover_lead": "根据冻结来源完成准备、操作、验证和复盘。", "learning_goal": "按来源核对输入与预期结果。", "learning_method": "先阅读操作说明，再完成当前操作并核对验证结果；不一致时停留在当前步骤修正。", "completion_standard": "输入、结果和证据均已核对并记录。"}}


class ContentReviewGateway:
    offline_content_review = True

    def __init__(self, group="review", *, candidate_values=None, fault=None, unknown_usage=False, quality_fault=None):
        self.group, self.values, self.fault = group, candidate_values or candidate(group), fault
        self.unknown_usage, self.quality_fault, self.calls = unknown_usage, quality_fault, []

    def options_for(self, *_args, **_kwargs):
        return LLMCallOptions(max_attempts=1, max_output_tokens=4096, allow_schema_repair=False, structured_output_mode=StructuredOutputMode.JSON_SCHEMA)

    def invoke_structured(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["output_schema"]
        payload = json.loads(kwargs["messages"][-1].content)
        if schema.__name__ in {"CoursewarePlanEnrichmentV2", "ReviewPracticeCoursewarePlanEnrichment", "CoursewarePlanEnrichmentCandidateV1", "ReviewPracticeEnrichmentCandidateV1"}:
            output = self.values
        elif schema.__name__ == "BatchResultV1":
            results = []
            for item in payload["items"]:
                bad = "错误候选" in item["value"]
                rules = []
                for rule in item["rule_ids"]:
                    rules.append({"rule_id": rule, "verdict": "fail" if bad else "pass", "evidence_ids": item["evidence_ids"][:1],
                        "problems": [{"code": "factual_conflict", "severity": "error", "reason": "候选与冻结依据冲突"}] if bad else [],
                        "factual_support": ("contradicted" if bad else "supported") if rule == "factual_support" else None})
                results.append({"item_id": item["item_id"], "value_hash": item["value_hash"], "rules": rules})
            output = {"batch_id": payload["batch_id"], "identity": payload["identity"], "value_hash": payload["value_hash"], "results": results}
            if callable(self.fault):
                output = self.fault(output, payload)
        elif schema.__name__ == "RevisionPatchV1":
            output = {"identity": payload["identity"], "changes": [{"item_id": item["item_id"], "old_value_hash": item["value_hash"], "new_value": "根据冻结来源核对输入与结果。"} for item in payload["items"]]}
            if self.fault == "patch_outside":
                output["changes"][0]["item_id"] = "source:forbidden"
        elif schema.__name__ == "CoursewareReviewDecisionV2Draft":
            if self.quality_fault == "unavailable":
                raise RuntimeError("scripted unavailable")
            output = {"schema_version": "2.0", "status": "pass", "issues": [], "rubric_scores": {k: 4 for k in ("objective_alignment", "coherence", "explanation_depth", "example_usefulness", "misconception_handling", "practice_gradient", "feedback_quality", "interaction_purpose", "cognitive_load")}}
            if self.quality_fault == "revise_once":
                self.quality_fault = None
                output.update(status="revise", issues=[{"code": "GUIDANCE", "dimension": "objective_alignment", "severity": "error", "scope": "scene", "scene_id": payload["document"]["scenes"][0]["scene_id"], "instruction": "核对封面引导"}])
        else:
            raise AssertionError(f"unexpected schema {schema.__name__}")
        output = schema.model_validate(output)
        return LLMCallResult(output=output, call_id=f"fixture-call-{len(self.calls)}", model_name="fixture-content-review", attempt_count=1, retry_count=0, latency_ms=1,
            structured_output_mode=StructuredOutputMode.JSON_SCHEMA, usage=LLMUsage() if self.unknown_usage else LLMUsage(input_tokens=128, output_tokens=128, total_tokens=256))


@contextmanager
def fixture_environment(directory, settings=None):
    from app.agents.resource_workflows.interactive_courseware import workflow, runtime
    from app.core.storage import file_storage
    settings = settings or fixture_settings()
    with patch.object(workflow, "get_settings", lambda: settings), patch.object(runtime, "get_settings", lambda: settings), patch.object(file_storage, "_get_resources_dir", lambda: Path(directory)):
        yield settings


def make_workflow(directory, group="review", *, repo=None, gateway=None, settings=None):
    from app.agents.resource_workflows.interactive_courseware.workflow import InteractiveCoursewareWorkflow
    from app.db.courseware.repository import MemoryCoursewareRepository
    source = resource(group)
    resources = SimpleNamespace(get=lambda rid: source if rid == source.resource_id else None)
    workflow = InteractiveCoursewareWorkflow(repo or MemoryCoursewareRepository(), resources, SimpleNamespace(get_run=lambda _: None), gateway or ContentReviewGateway(group))
    return workflow, source
