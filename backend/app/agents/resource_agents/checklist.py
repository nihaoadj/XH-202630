"""Node-scoped active-recall review checklist generation."""
from __future__ import annotations
import hashlib
import json
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm.gateway import LLMGateway
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import GeneratedArtifact, ResourceGenerationContext, ResourceSpec, ReviewPracticeNodeBlockV2, ReviewPracticePackageV2
from .base import BaseResourceGenerationAgent

REVIEW_PRACTICE_PROMPT = """你是 ReviewChecklistAgent。一次只能为一个能力节点生成主动回忆训练的严格 JSON。
只使用输入的当前节点 Evidence 和允许知识点；不得使用常识补全、相邻节点或未冻结的前置知识。
目标配额是 4 道闭卷回忆、4 道概念辨析和 2 道正反例辨认；正反例放入 example_recognition_questions 数组。
证据不足时可以减量，但每个未生成槽位
必须写入 omitted_slots，原因只能是 INSUFFICIENT_DISTINCT_EVIDENCE 或 NO_EXPLICIT_CONCEPT_BOUNDARY；闭卷回忆
和概念辨析各至少保留一道。概念辨析有两道以上时必须同时含真、假陈述；错误陈述和反例只可违反 Evidence
明确支持的一个关键边界。每题必须绑定至少一个当前节点 Evidence。还必须输出 knowledge_summary：用 3—5 句、至少 100 字综合概括
本节点的核心概念、作用、关键边界和可执行的复习提醒，不得新增 Evidence 未支持的事实；summary_evidence_ids 必须列出
该小结所依据的当前节点 Evidence，且必须是 evidence_ids 的子集。不要输出 Markdown、代码围栏或额外文字。"""

def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

def render_review_practice_markdown(package: dict) -> str:
    """Render learner-facing content without exposing traceability identifiers.

    Question and evidence IDs remain in the structured package for review,
    claims, and source tracing. They are implementation details, not learning
    material, so the readable document uses stable visible ordinals instead.
    """
    lines = [f"# {package['title']}", "", "## 使用说明", "", package["instructions"], ""]
    answers: list[tuple[dict, str, int]] = []
    answer_number = 0
    numerals = ["一", "二", "三"]
    for index, block in enumerate(package["node_blocks"]):
        lines += [f"## 节点{numerals[index]}：{block['skill_node_name']}", ""]
        for label, key, kind in (("闭卷回忆", "recall_questions", "recall"), ("概念辨析", "distinction_questions", "distinction")):
            lines += [f"### {label}", ""]
            for item in block[key]:
                answer_number += 1
                answers.append((item, kind, answer_number)); lines += [f"#### 题目 {answer_number}", ""]
                lines += [f"判断下列陈述是否正确，并说明依据：{item['statement']}" if kind == "distinction" else item["prompt"], "", "[ ] 会  [ ] 模糊  [ ] 不会", ""]
        lines += ["### 正反例辨认", ""]
        examples = list(block.get("example_recognition_questions") or [])
        if not examples and block.get("example_recognition"):
            examples = [block["example_recognition"]]
        if examples:
            for item in examples:
                answer_number += 1
                answers.append((item, "example", answer_number)); lines += [f"#### 题目 {answer_number}", "", f"A. {item['candidate_a']}", "", f"B. {item['candidate_b']}", "", "判断哪个是正例、哪个是反例，并说明决定性差异。", "", "[ ] 会  [ ] 模糊  [ ] 不会", ""]
        else: lines += ["本节点证据未提供足以构成明确边界的正反例；请先完成上方回忆与辨析。", ""]
        lines += ["### 节点知识小结", "", block["knowledge_summary"], "", "小结依据：已完成来源核验。", ""]
    lines += ["## 答案与证据解释", ""]
    for item, kind, visible_number in answers:
        lines += [f"### 题目 {visible_number}", ""]
        if kind == "distinction": lines += [f"判断：{'正确' if item['truth_value'] else '错误'}", "", f"纠正：{item['correction']}", ""]
        elif kind == "example": lines += [f"正例：{item['positive_candidate']}", "", f"决定性边界：{item['decisive_boundary']}", ""]
        else: lines += [f"参考答案：{item['reference_answer']}", ""]
        lines += [f"解释：{item['explanation']}", "", f"达标标准：{item['pass_criteria']}", "", "证据依据：已完成来源核验。", ""]
    lines += ["## 自评与下一步", "", "出现“不会”：返回对应节点讲义或薄弱点强化包；两项及以上“模糊”：核对答案后重新闭卷作答；全部“会”且满足达标标准：进入实操指南或分阶测试题。", ""]
    return "\n".join(lines).rstrip()

class ReviewChecklistAgent(BaseResourceGenerationAgent[ReviewPracticeNodeBlockV2]):
    resource_type = "复习清单"; agent_name = "ReviewChecklistAgent"; prompt_version = "review-practice-v3-node-summary"; artifact_format = "json"; validation_retry_attempts = 2
    @staticmethod
    def _node_descriptor(node_id: str) -> tuple[str, list[str]]:
        try: nodes = load_knowledge_base_manifest().get("skill_nodes", [])
        except Exception: nodes = []
        for node in nodes:
            if isinstance(node, dict) and node.get("node_id") == node_id:
                return str(node.get("name") or node_id), [str(v) for v in node.get("knowledge_points", []) if str(v).strip()]
        return node_id, []
    @staticmethod
    def _node_evidence_ids(spec: ResourceSpec, node_id: str) -> list[str]:
        return list(spec.node_evidence_map.get(node_id) or []) if spec.node_evidence_map else list(spec.evidence_ids)
    def _messages(self, spec: ResourceSpec, context: ResourceGenerationContext, node_id: str):
        name, points = self._node_descriptor(node_id); evidence_ids = self._node_evidence_ids(spec, node_id)
        if not evidence_ids: raise ApplicationError(ErrorCode.EVIDENCE_INSUFFICIENT, status_code=422)
        return [SystemMessage(content=REVIEW_PRACTICE_PROMPT), HumanMessage(content=self.json_payload({"schema_version":"2.0", "skill_node_id":node_id, "skill_node_name":name, "allowed_knowledge_points":[node_id,*points], "allowed_evidence_ids":evidence_ids, "evidence":[item.model_dump(mode="json") for item in context.evidence if item.evidence_id in evidence_ids], "difficulty":spec.difficulty}))]
    def _validate_block(self, block: ReviewPracticeNodeBlockV2, spec: ResourceSpec, node_id: str) -> None:
        allowed = set(self._node_evidence_ids(spec, node_id))
        examples = list(block.example_recognition_questions)
        if block.example_recognition:
            examples.append(block.example_recognition)
        questions = [*block.recall_questions, *block.distinction_questions, *examples]
        if (block.skill_node_id != node_id or not allowed or not set(block.evidence_ids) <= allowed
                or not set(block.summary_evidence_ids) <= allowed
                or any(not set(q.evidence_ids) <= allowed for q in questions)):
            raise ApplicationError(ErrorCode.EVIDENCE_SCOPE_VIOLATION, status_code=422)
    def generate(self, spec: ResourceSpec, context: ResourceGenerationContext, *, llm_gateway: LLMGateway, **_: object) -> GeneratedArtifact:
        self._ensure_route(spec); self._scoped_evidence(spec, context)
        if not spec.knowledge_points or not spec.node_evidence_map: raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        blocks, traces = [], []
        for index, node_id in enumerate(spec.knowledge_points):
            last_error: Exception | None = None
            for _ in range(self.validation_retry_attempts):
                try:
                    result = self.invoke(spec=spec, context=context.model_copy(update={"step_id":f"{context.step_id}:node:{index+1}"}), llm_gateway=llm_gateway, messages=self._messages(spec, context, node_id), output_schema=ReviewPracticeNodeBlockV2, representation="text", max_output_tokens=8192)
                    self._validate_block(result.output, spec, node_id); block = result.output.model_dump(mode="json"); base=index*10
                    for item in block["recall_questions"]: item["question_id"] = f"q-{base+int(item['local_id'][-1]):03d}"
                    for item in block["distinction_questions"]: item["question_id"] = f"q-{base+4+int(item['local_id'][-1]):03d}"
                    examples = list(block.get("example_recognition_questions") or [])
                    if not examples and block.get("example_recognition"):
                        examples = [block["example_recognition"]]
                    for item in examples:
                        item["question_id"] = f"q-{base+8+int(item['local_id'][-1]):03d}"
                    blocks.append(block); traces.append(result.trace_metadata()); break
                except Exception as exc: last_error = exc
            else: raise last_error if isinstance(last_error, ApplicationError) else ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        package = ReviewPracticePackageV2(title=f"{context.topic}复习清单", instructions="请先闭卷完成所有题目，再到文末核对答案与证据解释。", node_blocks=blocks).model_dump(mode="json"); package["payload_hash"] = _canonical_hash({key:value for key,value in package.items() if key != "payload_hash"})
        artifact = GeneratedArtifact(metadata=self.metadata(spec=spec, representation="text", source_evidence_ids=list(spec.evidence_ids)), difficulty=spec.difficulty, content_text=render_review_practice_markdown(package), knowledge_points=list(spec.knowledge_points), artifact_data={"review_practice_package":package}, storage_type="text", mime_type="text/markdown", llm_metadata={"node_calls":traces})
        return self.validate(artifact, spec=spec, context=context)
    def validate(self, artifact: GeneratedArtifact, *, spec: ResourceSpec, context: ResourceGenerationContext) -> GeneratedArtifact:
        package=artifact.artifact_data.get("review_practice_package")
        if not isinstance(package, dict) or [item.get("skill_node_id") for item in package.get("node_blocks", [])] != list(spec.knowledge_points): raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        if package.get("payload_hash") != _canonical_hash({key:value for key,value in package.items() if key != "payload_hash"}) or artifact.content_text != render_review_practice_markdown(package): raise ApplicationError(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, status_code=422)
        return artifact
