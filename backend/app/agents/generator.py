import json
import uuid
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.llm import get_llm
from app.models.schemas import LearningResource, SourceRef


GENERATION_PROMPT = """你是一名领域知识生成 Agent。请严格依据提供的专业知识片段，为学习者生成个性化学习资源。
要求：
1. 必须基于给定的知识片段内容，不得编造未提供的专业知识。
2. 根据学习者能力水平调整语言深度与示例难度。
3. 输出包含：resource_type（资源类型）、difficulty（难度等级）、content_text（内容）、knowledge_points（覆盖知识点）、source_refs（引用来源）。
4. 用 JSON 数组格式输出，每个元素对应一种资源类型，字段名必须使用英文。
"""


def _build_source_refs(chunks):
    refs = []
    for i, c in enumerate(chunks[:3]):
        refs.append(SourceRef(
            doc_id=f"doc_{i}",
            title=c["source"],
            snippet=c["content"][:200],
            score=c["score"],
        ))
    return refs


def generate_node(state: AgentState) -> AgentState:
    """领域知识生成 Agent：生成讲义、实操指南、分阶测试题"""
    llm = get_llm()
    learner = state["learner"]
    diagnosis = state.get("diagnosis", {})
    chunks = state.get("retrieved_chunks", [])
    resource_types = state.get("resource_types", ["讲义", "实操指南", "分阶测试题"])
    topic = state["topic"]

    context = "\n\n".join(
        [f"[片段 {i+1}] 来源：{c['source']}\n{c['content']}" for i, c in enumerate(chunks[:5])]
    )

    user_input = f"""
学习主题：{topic}
学习者水平：{diagnosis.get('recommended_difficulty', learner.skill_level)}
weak_points（知识盲区）：{diagnosis.get('weak_points', learner.weak_points)}
strong_points（优势领域）：{learner.strong_points}
需要生成的资源类型：{resource_types}

专业知识片段：
{context}

请生成对应资源，每个资源字段：resource_type, difficulty, content_text, knowledge_points, source_refs。
"""
    messages = [
        SystemMessage(content=GENERATION_PROMPT),
        HumanMessage(content=user_input),
    ]
    response = llm.invoke(messages)

    try:
        raw_resources = json.loads(response.content)
    except json.JSONDecodeError:
        raw_resources = []

    resources = []
    for r in raw_resources:
        resources.append(LearningResource(
            resource_id=str(uuid.uuid4()),
            resource_type=r.get("resource_type", "讲义"),
            difficulty=r.get("difficulty", "中级"),
            content_text=r.get("content_text") or r.get("content", ""),
            knowledge_points=r.get("knowledge_points", []),
            source_refs=_build_source_refs(chunks),
        ))

    trace_item = {
        "agent_name": "generator",
        "action": "内容生成",
        "output_summary": f"生成 {len(resources)} 种资源：{[r.resource_type for r in resources]}",
    }

    return {
        "generated_resources": resources,
        "trace": [trace_item],
        "iteration": state.get("iteration", 0) + 1,
    }
