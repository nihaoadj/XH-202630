"""Evidence-scoped structured assessment generation."""

from __future__ import annotations

import hashlib
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.security.errors import ApplicationError, ErrorCode
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import AssessmentNodeBlockV2, AssessmentPackageV2, GeneratedArtifact, ResourceGenerationContext, ResourceSpec
from app.models.shared.assessment import (
    ASSESSMENT_QUESTION_QUOTAS,
    ASSESSMENT_SCORE_BY_TYPE,
    ASSESSMENT_SCORE_DECIMAL_PLACES,
    ASSESSMENT_TOTAL_SCORE,
)

from .base import BaseResourceGenerationAgent


ASSESSMENT_PROMPT = """你是 AssessmentAgent。一次只能为一个能力节点生成严格 JSON 题组。
只使用给定 evidence 和允许知识点；不得输出 Markdown、代码围栏或额外说明。
返回 schema_version=2.0 和输入 skill_node_id，必须有 2 道 single_choice、2 道 multiple_choice、2 道 short_answer。
难度阶段由题型固定：single_choice 为“基础”、multiple_choice 为“进阶”、short_answer 为“挑战”；题干不得越出当前能力节点。
选择题必须有 A/B/C/D 四个选项；每道多选题必须有 2 或 3 个正确选项，且至少保留 1 个错误选项；
问答题必须有 reference_answer 和至少两项 rubric。单节点题组的基准分值为基础单选 15 分、15 分，进阶多选
20 分、20 分，挑战简答 15 分、15 分；多个能力节点合并时，服务端按节点数等比例归一化，整套试卷总分仍为 100 分。
知识点标签只能描述题干实际考查的概念，不能用允许标签掩盖相邻节点、评测调优、生产运维、
资源登记或摄取管线等未列入允许知识点的内容。若输入含有返工反馈，必须逐项消除其中指出的
越界题目和证据不足，不得复述或换一种说法保留该问题。
每一道题的题干、正确答案、reference_answer 和 rubric 中每个可验证断言，都必须能被该题 evidence_ids
中的冻结 excerpt 直接支持；优先只引用一条最直接的 evidence，不得依赖常识补全、相邻节点经验或未出现的产品细节。
若证据没有明确说明某个细节，就把题目改为只考查证据明确出现的概念，而不是猜测或扩展该细节。
如果输入包含 historical_assessment_questions，生成题干必须与其中任何题干不同；允许相似的知识点、题型和考查角度，但不得直接复用题干。
如果输入包含 previous_version_content 和 revision_feedback，这是审核返工：仅修改反馈指出的问题，保留上一版本其余正确内容。
JSON 示例（仅示意字段与嵌套结构；实际值必须来自输入白名单；question_id、difficulty_stage、max_score 由服务端生成）：
{
  "schema_version": "2.0",
  "skill_node_id": "node-001",
  "skill_node_name": "示例节点",
  "single_choice_questions": [
    {
      "local_id": "single-1",
      "question_type": "single_choice",
      "stem": "Evidence 明确支持的单选题。",
      "options": [
        {"option_id": "A", "text": "选项 A"},
        {"option_id": "B", "text": "选项 B"},
        {"option_id": "C", "text": "选项 C"},
        {"option_id": "D", "text": "选项 D"}
      ],
      "answer_option_ids": ["A"],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    },
    {
      "local_id": "single-2",
      "question_type": "single_choice",
      "stem": "Evidence 明确支持的第二道单选题。",
      "options": [
        {"option_id": "A", "text": "选项 A"},
        {"option_id": "B", "text": "选项 B"},
        {"option_id": "C", "text": "选项 C"},
        {"option_id": "D", "text": "选项 D"}
      ],
      "answer_option_ids": ["B"],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    }
  ],
  "multiple_choice_questions": [
    {
      "local_id": "multiple-1",
      "question_type": "multiple_choice",
      "stem": "Evidence 明确支持的多选题。",
      "options": [
        {"option_id": "A", "text": "选项 A"},
        {"option_id": "B", "text": "选项 B"},
        {"option_id": "C", "text": "选项 C"},
        {"option_id": "D", "text": "选项 D"}
      ],
      "answer_option_ids": ["A", "B"],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    },
    {
      "local_id": "multiple-2",
      "question_type": "multiple_choice",
      "stem": "Evidence 明确支持的第二道多选题。",
      "options": [
        {"option_id": "A", "text": "选项 A"},
        {"option_id": "B", "text": "选项 B"},
        {"option_id": "C", "text": "选项 C"},
        {"option_id": "D", "text": "选项 D"}
      ],
      "answer_option_ids": ["A", "C"],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    }
  ],
  "short_answer_questions": [
    {
      "local_id": "short-1",
      "question_type": "short_answer",
      "stem": "解释 Evidence 明确出现的概念。",
      "reference_answer": "只写 Evidence 明确支持的答案。",
      "rubric": [
        {"criterion": "指出核心结论", "points": 5},
        {"criterion": "说明证据边界", "points": 5}
      ],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    },
    {
      "local_id": "short-2",
      "question_type": "short_answer",
      "stem": "说明该概念的关键边界。",
      "reference_answer": "只写 Evidence 明确支持的边界。",
      "rubric": [
        {"criterion": "回答核心问题", "points": 5},
        {"criterion": "不超出证据范围", "points": 5}
      ],
      "knowledge_point_tags": ["node-001"],
      "evidence_ids": ["ev-001"]
    }
  ]
}
"""



def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_stem(value: object) -> str:
    return re.sub(r"[\s\u3000，。！？；：、,.!?;:（）()【】\[\]『』‘’“”\"'`]+", "", str(value or "").casefold())


def _assign_scores(rows: list[dict]) -> None:
    questions_per_node = sum(ASSESSMENT_QUESTION_QUOTAS.values())
    if not rows or len(rows) % questions_per_node:
        raise ValueError("assessment rows do not match the fixed per-node quota")
    node_count = len(rows) // questions_per_node
    raw = [
        ASSESSMENT_SCORE_BY_TYPE[item["question_type"]] * 10 / node_count
        for item in rows
    ]
    floors = [int(value) for value in raw]
    target_tenths = int(ASSESSMENT_TOTAL_SCORE * 10)
    for index in sorted(
        range(len(rows)),
        key=lambda item: (-(raw[item] - floors[item]), rows[item]["question_id"]),
    )[:target_tenths - sum(floors)]:
        floors[index] += 1
    for row, cents in zip(rows, floors):
        row["max_score"] = cents / (10 ** ASSESSMENT_SCORE_DECIMAL_PLACES)


def render_assessment_markdown(package: dict) -> str:
    lines = [f"# {package['title']}", "", package["instructions"], ""]
    for block in package["node_blocks"]:
        lines += [f"## 能力节点：{block['skill_node_name']}", ""]
        for label, stage, field_name in (("单选题", "基础", "single_choice_questions"), ("多选题", "进阶", "multiple_choice_questions"), ("问答题", "挑战", "short_answer_questions")):
            lines += [f"### {label}（{stage}）", ""]
            for question in block[field_name]:
                lines += [f"#### {question['question_id']}（{question['max_score']:.1f} 分）", "", question["stem"], "", f"知识点：{'、'.join(question['knowledge_point_tags'])}", ""]
                for option in question.get("options", []):
                    lines += [f"- {option['option_id']}. {option['text']}", ""]
    return "\n".join(lines).rstrip() + "\n"


class AssessmentAgent(BaseResourceGenerationAgent[AssessmentNodeBlockV2]):
    resource_type = "分阶测试题"
    agent_name = "AssessmentAgent"
    prompt_version = "assessment-resource-v8-scored-evidence-grounded"
    artifact_format = "json"
    default_max_output_tokens = 8192
    validation_retry_attempts = 2

    @staticmethod
    def _node_evidence_ids(spec: ResourceSpec, node_id: str) -> list[str]:
        """New specs must isolate node evidence; legacy specs retain their snapshot scope."""
        if spec.node_evidence_map:
            return list(spec.node_evidence_map.get(node_id) or [])
        return list(spec.evidence_ids)

    @staticmethod
    def _node_descriptor(node_id: str) -> tuple[str, list[str]]:
        """Resolve the frozen catalog label; IDs alone are too weak a model constraint."""
        try:
            nodes = load_knowledge_base_manifest().get("skill_nodes", [])
        except Exception:
            nodes = []
        for node in nodes:
            if isinstance(node, dict) and node.get("node_id") == node_id:
                tags = [str(value) for value in node.get("knowledge_points", []) if str(value).strip()]
                return str(node.get("name") or node_id), list(dict.fromkeys([node_id, *tags]))
        return node_id, [node_id]

    def _messages(self, spec: ResourceSpec, context: ResourceGenerationContext, node_id: str):
        node_name, allowed_tags = self._node_descriptor(node_id)
        revision_feedback = context.constraints.get("revision_feedback", {})
        node_index = list(spec.knowledge_points).index(node_id)
        node_question_ids = [f"q-{number:03d}" for number in range(node_index * 6 + 1, node_index * 6 + 7)]
        feedback_issues = revision_feedback.get("issues", []) if isinstance(revision_feedback, dict) else []
        node_feedback = [
            item for item in feedback_issues
            if isinstance(item, dict)
            and (item.get("knowledge_point") in {None, node_id} or node_id in str(item.get("description") or ""))
        ]
        rejected_question_ids = sorted({
            question_id
            for item in node_feedback
            for question_id in re.findall(r"q-\d{3}", str(item.get("description") or ""))
            if question_id in node_question_ids
        })
        payload = {
            "schema_version": "2.0", "skill_node_id": node_id, "skill_node_name": node_name,
            "allowed_knowledge_point_tags": allowed_tags, "allowed_evidence_ids": self._node_evidence_ids(spec, node_id),
            "difficulty": spec.difficulty,
            "server_assigned_question_ids_for_this_node": node_question_ids,
            "evidence": [item.model_dump(mode="json") for item in context.evidence if item.evidence_id in self._node_evidence_ids(spec, node_id)],
            "historical_assessment_questions": [
                item for item in context.constraints.get("historical_assessment_questions", [])
                if isinstance(item, dict) and str(item.get("skill_node_id") or node_id) == node_id
            ],
            # This is server-owned reviewer feedback.  Supplying it only on a
            # revision preserves the independent reviewer/generator boundary
            # while making a targeted regeneration genuinely corrective.
            "revision_feedback": {
                "rejected_question_ids": rejected_question_ids,
                "issues": node_feedback,
            } if context.generation_attempt > 1 else {},
            "previous_version_content": context.constraints.get("previous_version_content", "")
            if context.generation_attempt > 1 else "",
        }
        return [SystemMessage(content=ASSESSMENT_PROMPT), HumanMessage(content=self.json_payload(payload))]

    @staticmethod
    def _validate_node(block: AssessmentNodeBlockV2, spec: ResourceSpec, node_id: str, context: ResourceGenerationContext) -> None:
        if block.skill_node_id != node_id:
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        _, allowed_tags = AssessmentAgent._node_descriptor(node_id)
        allowed_evidence_ids = AssessmentAgent._node_evidence_ids(spec, node_id)
        if not allowed_evidence_ids:
            raise ApplicationError(ErrorCode.EVIDENCE_INSUFFICIENT, status_code=422)
        historical = {
            _normalize_stem(item.get("question_text"))
            for item in context.constraints.get("historical_assessment_questions", [])
            if isinstance(item, dict) and str(item.get("skill_node_id") or node_id) == node_id
            and _normalize_stem(item.get("question_text"))
        }
        for question in block.single_choice_questions + block.multiple_choice_questions + block.short_answer_questions:
            if set(question.knowledge_point_tags) - set(allowed_tags) or set(question.evidence_ids) - set(allowed_evidence_ids):
                raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
            if _normalize_stem(question.stem) in historical:
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
                    self._validate_node(result.output, spec, node_id, node_context)
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
            merged = block.model_dump(mode="json")
            for question_type, stage, field_name in (("single_choice", "基础", "single_choice_questions"), ("multiple_choice", "进阶", "multiple_choice_questions"), ("short_answer", "挑战", "short_answer_questions")):
                items = merged[field_name]
                for item in items:
                    item.update({"question_id": f"q-{number:03d}", "question_type": question_type,
                                 "difficulty_stage": stage})
                    number += 1
                    rows.append(item)
            merged_blocks.append(merged)
        _assign_scores(rows)
        package = AssessmentPackageV2(schema_version="2.0", title=f"{context.topic} 分阶测试题", instructions="请独立完成全部题目；总分 100 分。", node_blocks=merged_blocks).model_dump(mode="json")
        package["payload_hash"] = _canonical_hash(package)
        exercises = [
            {"question_id": item["question_id"], "question_type": item["question_type"],
             "options": [f"{choice['option_id']}. {choice['text']}" for choice in item.get("options", [])],
             "skill_node_id": block["skill_node_id"], "knowledge_point": item["knowledge_point_tags"][0],
             "question": item["stem"], "difficulty": spec.difficulty}
            for block in package["node_blocks"]
            for field_name in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions")
            for item in block[field_name]
        ]
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
        questions = [item for block in blocks for field_name in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions") for item in block.get(field_name, [])]
        expected_stages = {"single_choice": "基础", "multiple_choice": "进阶", "short_answer": "挑战"}
        expected_total_by_type = {
            question_type: ASSESSMENT_SCORE_BY_TYPE[question_type] * quota
            for question_type, quota in ASSESSMENT_QUESTION_QUOTAS.items()
        }
        blocks_have_fixed_quota = all(
            len(block.get("single_choice_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["single_choice"]
            and len(block.get("multiple_choice_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["multiple_choice"]
            and len(block.get("short_answer_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["short_answer"]
            for block in blocks
        )
        score_totals_match = all(
            round(
                sum(float(item.get("max_score", 0)) for item in questions if item.get("question_type") == question_type),
                ASSESSMENT_SCORE_DECIMAL_PLACES,
            ) == total
            for question_type, total in expected_total_by_type.items()
        )
        if (len(questions) != sum(ASSESSMENT_QUESTION_QUOTAS.values()) * len(spec.knowledge_points)
                or not blocks_have_fixed_quota
                or round(sum(item.get("max_score", 0) for item in questions), ASSESSMENT_SCORE_DECIMAL_PLACES) != ASSESSMENT_TOTAL_SCORE
                or not score_totals_match
                or any(item.get("difficulty_stage") != expected_stages[item["question_type"]] for item in questions)):
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if "参考答案" in artifact.content_text or "rubric" in artifact.content_text.lower():
            raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
