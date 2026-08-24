"""Evidence-scoped structured assessment generation."""

from __future__ import annotations

import hashlib
import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import AssessmentNodeBlockV2, GeneratedArtifact, ResourceGenerationContext, ResourceSpec

from .base import BaseResourceGenerationAgent


ASSESSMENT_PROMPT = """你是 AssessmentAgent。一次只能为一个能力节点生成严格 JSON 题组。
只使用给定 evidence 和允许知识点；不得输出 Markdown、代码围栏或额外说明。
返回 schema_version=2.0 和输入 skill_node_id，必须有 2 道 single_choice、1 道 multiple_choice、2 道 short_answer。
选择题必须有 A/B/C/D 四个选项；问答题必须有 reference_answer 和至少两项 rubric。
"""


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _assign_scores(rows: list[dict]) -> None:
    weights = {"single_choice": 2, "multiple_choice": 4, "short_answer": 5}
    total = sum(weights[item["question_type"]] for item in rows)
    raw = [10000 * weights[item["question_type"]] / total for item in rows]
    floors = [int(value) for value in raw]
    for index in sorted(range(len(rows)), key=lambda item: (-(raw[item] - floors[item]), rows[item]["question_id"]))[:10000 - sum(floors)]:
        floors[index] += 1
    for row, cents in zip(rows, floors):
        row["max_score"] = cents / 100


def render_assessment_markdown(package: dict) -> str:
    lines = [f"# {package['title']}", "", package["instructions"], ""]
    for block in package["node_blocks"]:
        lines += [f"## 能力节点：{block['skill_node_name']}", ""]
        for label, kind in (("单选题", "single_choice"), ("多选题", "multiple_choice"), ("问答题", "short_answer")):
            lines += [f"### {label}", ""]
            for question in (item for item in block["questions"] if item["question_type"] == kind):
                lines += [f"#### {question['question_id']}（{question['max_score']:.2f} 分）", "", question["stem"], "", f"知识点：{'、'.join(question['knowledge_point_tags'])}", ""]
                for option in question.get("options", []):
                    lines += [f"- {option['option_id']}. {option['text']}", ""]
    return "\n".join(lines).rstrip() + "\n"


class AssessmentAgent(BaseResourceGenerationAgent[AssessmentNodeBlockV2]):
    resource_type = "分阶测试题"
    agent_name = "AssessmentAgent"
    prompt_version = "assessment-resource-v6-node-json"
    artifact_format = "json"
    default_max_output_tokens = 6000
    validation_retry_attempts = 2

    def _messages(self, spec: ResourceSpec, context: ResourceGenerationContext, node_id: str):
        payload = {
            "schema_version": "2.0", "skill_node_id": node_id, "skill_node_name": node_id,
            "allowed_knowledge_point_tags": [node_id], "allowed_evidence_ids": list(spec.evidence_ids),
            "difficulty": spec.difficulty,
            "evidence": [item.model_dump(mode="json") for item in context.evidence if item.evidence_id in spec.evidence_ids],
        }
        return [SystemMessage(content=ASSESSMENT_PROMPT), HumanMessage(content=self.json_payload(payload))]

    @staticmethod
    def _validate_node(block: AssessmentNodeBlockV2, spec: ResourceSpec, node_id: str) -> None:
        if block.skill_node_id != node_id:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        for question in block.single_choice_questions + block.multiple_choice_questions + block.short_answer_questions:
            if set(question.knowledge_point_tags) - {node_id} or set(question.evidence_ids) - set(spec.evidence_ids):
                raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)

    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        self._ensure_route(spec)
        self._scoped_evidence(spec, context)
        blocks: list[AssessmentNodeBlockV2] = []
        traces: list[dict] = []
        for index, node_id in enumerate(spec.knowledge_points, start=1):
            node_context = context.model_copy(update={"step_id": f"{context.step_id}:node:{index}"})
            last_error: ApplicationError | None = None
            for _ in range(self.validation_retry_attempts):
                try:
                    result = self.invoke(spec=spec, context=node_context, llm_gateway=llm_gateway,
                        messages=self._messages(spec, node_context, node_id), output_schema=AssessmentNodeBlockV2,
                        representation="text", max_output_tokens=self.default_max_output_tokens)
                    self._validate_node(result.output, spec, node_id)
                    blocks.append(result.output)
                    traces.append(result.trace_metadata())
                    break
                except Exception as exc:
                    last_error = exc if isinstance(exc, ApplicationError) else ApplicationError(
                        ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422
                    )
            else:
                raise last_error or ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        merged_blocks, rows, number = [], [], 1
        for block in blocks:
            questions = []
            for question_type, items in (("single_choice", block.single_choice_questions), ("multiple_choice", block.multiple_choice_questions), ("short_answer", block.short_answer_questions)):
                for item in items:
                    row = item.model_dump(mode="json")
                    row.update({"question_id": f"q-{number:03d}", "question_type": question_type,
                                "skill_node_id": block.skill_node_id, "skill_node_name": block.skill_node_name})
                    number += 1
                    questions.append(row)
                    rows.append(row)
            merged_blocks.append({"skill_node_id": block.skill_node_id, "skill_node_name": block.skill_node_name, "questions": questions})
        _assign_scores(rows)
        package = {"schema_version": "2.0", "title": f"{context.topic} 分阶测试题", "instructions": "请独立完成全部题目；总分 100 分。", "node_blocks": merged_blocks}
        package["payload_hash"] = _canonical_hash(package)
        exercises = [{"question_id": item["question_id"], "question_type": item["question_type"],
                      "options": [f"{choice['option_id']}. {choice['text']}" for choice in item.get("options", [])],
                      "skill_node_id": item["skill_node_id"], "knowledge_point": item["knowledge_point_tags"][0],
                      "question": item["stem"], "difficulty": spec.difficulty} for item in rows]
        artifact = GeneratedArtifact(metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)),
            difficulty=spec.difficulty, content_text=render_assessment_markdown(package), knowledge_points=list(spec.knowledge_points),
            artifact_data={"assessment_package": package, "exercise_items": exercises}, storage_type="text", mime_type="text/markdown",
            llm_metadata={"node_calls": traces})
        return self.validate(artifact, spec=spec, context=context)

    def validate(self, artifact: GeneratedArtifact, *, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact:
        package = artifact.artifact_data.get("assessment_package")
        blocks = package.get("node_blocks") if isinstance(package, dict) else None
        if not isinstance(blocks, list) or [item.get("skill_node_id") for item in blocks] != list(spec.knowledge_points):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        questions = [item for block in blocks for item in block.get("questions", [])]
        if len(questions) != 5 * len(spec.knowledge_points) or round(sum(item.get("max_score", 0) for item in questions), 2) != 100:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if "参考答案" in artifact.content_text or "rubric" in artifact.content_text.lower():
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
