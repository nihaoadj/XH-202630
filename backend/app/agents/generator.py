import json
import uuid
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.llm import get_llm
from app.models.agent_contracts import (
    GeneratorInput,
    GeneratorOutput,
    NodeResult,
    build_trace_item,
    make_error_info,
    start_step,
)
from app.models.schemas import LearningResource, SourceRef
from app.models.workflow import ResourceStatus, StepStatus


GENERATION_PROMPT = """你是一名个性化资源生成 Agent。请严格依据用户输入的学习主题、学习者画像、学习路径规划和知识库片段，为学习者生成个性化领域知识训练资源。
要求：
1. 必须基于给定的知识片段内容，不得编造未提供的专业知识。
2. 根据学习者能力水平调整语言深度与示例难度。
3. 输出内容必须围绕用户输入的学习主题和当前知识库证据。
4. 不得预设、暗示或偏向任何固定领域；领域范围只能从用户输入、学习者画像和知识库片段中推断。
5. 按当前主题所属领域的知识结构组织内容，明确核心概念、实操步骤、常见错误、练习或测试要求。
6. 输出包含：resource_type（资源类型）、difficulty（难度等级）、content_text（内容）、knowledge_points（覆盖知识点）、source_refs（引用来源）。
7. 用 JSON 数组格式输出，每个元素对应一种资源类型，字段名必须使用英文。
"""


def _build_source_refs(chunks):
    refs = []
    for i, c in enumerate(chunks[:3]):
        refs.append(SourceRef(
            doc_id=c.get("document_id") or f"legacy_doc_{i}",
            title=c.get("title") or c.get("source", "unknown"),
            snippet=c["content"][:200],
            score=c["score"],
            chunk_id=c.get("chunk_id"),
            knowledge_point=(c.get("knowledge_points") or [None])[0],
            source_path=c.get("source"),
            retrieval_query=c.get("retrieval_query"),
            rank=c.get("rank"),
            metadata={"knowledge_base_id": c.get("knowledge_base_id")},
        ))
    return refs


def _fallback_resources(state: AgentState):
    learner = state["learner"]
    topic = state["topic"]
    resource_types = state.get("resource_types", ["定制讲义", "实操指南", "分阶测试题"])
    learning_plan = state.get("learning_plan", {})
    chunks = state.get("retrieved_chunks", [])
    source_refs = _build_source_refs(chunks)
    knowledge_points = list(dict.fromkeys(
        (learner.weak_points or []) + [item.get("topic", "") for item in learning_plan.get("learning_path", [])]
    ))
    knowledge_points = [item for item in knowledge_points if item] or [topic]

    previous_by_type = {
        resource.resource_type: resource
        for resource in state.get("generated_resources", [])
    }
    resources = []
    for resource_type in resource_types:
        previous = previous_by_type.get(resource_type)
        content = f"""# {topic} - {resource_type}

## 学习目标
{learner.learning_goal}

## 当前能力与薄弱点
- 能力水平：{learner.skill_level}
- 优势：{'、'.join(learner.strong_points) or '暂无'}
- 薄弱点：{'、'.join(learner.weak_points) or '暂无'}

## 推荐学习路径
{chr(10).join([f"{item.get('order', index + 1)}. {item.get('topic', topic)}：{item.get('reason', '建议按顺序学习')}" for index, item in enumerate(learning_plan.get('learning_path', []))]) or '1. 先理解核心概念，再完成基础实操，最后通过测试题反馈学习效果。'}

## 资源内容
当前为最小链路保底生成内容。请结合知识库证据继续完善该主题的概念解释、操作步骤、常见错误和练习题。
"""
        resources.append(LearningResource(
            resource_id=str(uuid.uuid4()),
            resource_type=resource_type,
            difficulty=state.get("difficulty_preference") or learner.skill_level or "中级",
            content_text=content,
            knowledge_points=knowledge_points,
            source_refs=source_refs,
            review_status=(
                ResourceStatus.PENDING_REVIEW.value
                if state.get("include_review", True)
                else ResourceStatus.UNREVIEWED_DRAFT.value
            ),
            version=(previous.version + 1) if previous else 1,
            parent_resource_id=previous.resource_id if previous else None,
        ))
    return resources


def generate_node(state: AgentState) -> dict:
    """个性化资源生成 Agent：生成讲义、实操指南、分阶测试题"""
    node_input = GeneratorInput.model_validate(state)
    learner = node_input.learner
    diagnosis = node_input.diagnosis
    chunks = node_input.retrieved_chunks
    resource_types = node_input.resource_types
    topic = node_input.topic
    learning_plan = node_input.learning_plan
    generation_attempt = node_input.generation_attempt
    step_context = start_step(state, attempt=generation_attempt)

    context = "\n\n".join(
        [f"[片段 {i+1}] 来源：{c['source']}\n{c['content']}" for i, c in enumerate(chunks[:5])]
    )

    user_input = f"""
学习主题：{topic}
学习者水平：{node_input.difficulty_preference or diagnosis.get('recommended_difficulty', learner.skill_level)}
weak_points（知识盲区）：{diagnosis.get('weak_points', learner.weak_points)}
strong_points（优势领域）：{learner.strong_points}
目标能力节点：{node_input.target_skill_nodes or ['未指定']}
生成模式：{node_input.generation_mode}
生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}
当前生成轮次：{generation_attempt}
上一轮审核意见：{json.dumps(node_input.review_result, ensure_ascii=False)}
学习路径规划：
{json.dumps(learning_plan, ensure_ascii=False)}
需要生成的资源类型：{resource_types}

专业知识片段：
{context}

请生成对应资源，每个资源字段：resource_type, difficulty, content_text, knowledge_points, source_refs。
"""
    fallback_code = None
    try:
        llm = get_llm()
        messages = [
            SystemMessage(content=GENERATION_PROMPT),
            HumanMessage(content=user_input),
        ]
        response = llm.invoke(messages)
        raw_resources = json.loads(response.content)
    except Exception:
        fallback_code = require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE)
        raw_resources = []

    previous_by_type = {
        resource.resource_type: resource
        for resource in node_input.generated_resources
    }
    resources = []
    for r in raw_resources if isinstance(raw_resources, list) else []:
        if not isinstance(r, dict):
            continue
        resource_type = r.get("resource_type", "讲义")
        previous = previous_by_type.get(resource_type)
        resources.append(LearningResource(
            resource_id=str(uuid.uuid4()),
            resource_type=resource_type,
            difficulty=node_input.difficulty_preference or r.get("difficulty", "中级"),
            content_text=r.get("content_text") or r.get("content", ""),
            knowledge_points=r.get("knowledge_points", []),
            source_refs=_build_source_refs(chunks),
            review_status=(
                ResourceStatus.PENDING_REVIEW.value
                if node_input.include_review
                else ResourceStatus.UNREVIEWED_DRAFT.value
            ),
            version=(previous.version + 1) if previous else 1,
            parent_resource_id=previous.resource_id if previous else None,
        ))
    if not resources:
        if fallback_code is None:
            fallback_code = require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE)
        resources = _fallback_resources(state)

    status = StepStatus.DEGRADED if fallback_code else StepStatus.SUCCESS
    error = (
        make_error_info(
            fallback_code,
            source="generator",
            attempt=generation_attempt,
        )
        if fallback_code
        else None
    )
    NodeResult[GeneratorOutput](
        status=status,
        output=GeneratorOutput(
            generated_resources=resources,
            generation_attempt=generation_attempt,
            revision_count=node_input.revision_count,
        ),
        error=error,
    )
    trace_item = build_trace_item(
        state,
        agent_name="generator",
        action="个性化资源生成",
        status=status,
        input_summary=f"资源类型：{resource_types}；路径节点数：{len(learning_plan.get('learning_path', []))}；返工次数：{node_input.revision_count}",
        output_summary=f"生成 {len(resources)} 种资源：{[r.resource_type for r in resources]}",
        decision_reason="依据学习路径、请求难度、生成约束、检索证据及上一轮审核意见生成资源。",
        evidence_refs=[c.get("chunk_id") or c.get("source", "unknown") for c in chunks[:5]],
        resource_ids=[resource.resource_id for resource in resources],
        error=error,
        attempt=generation_attempt,
        step_context=step_context,
    )

    return {
        "generated_resources": resources,
        "current_node": "generator",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
        "generation_attempt": generation_attempt,
        "iteration": generation_attempt,
    }
