import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.models.agent_contracts import (
    NodeResult,
    PlannerLLMOutput,
    PlannerInput,
    PlannerOutput,
    build_trace_item,
    require_agent_fallback,
    start_step,
)
from app.models.llm import LLMCallContext
from app.models.workflow import StepStatus


PLANNER_PROMPT = """你是一名学习路径规划 Agent。请根据学习者画像、学情诊断结果、学习主题和已检索到的知识库证据，规划个性化学习路径。
规划目标：
1. 决定学习者先学什么、跳过什么、补什么、挑战什么。
2. 输出资源生成要求，使后续生成 Agent 能生成定制讲义、实操指南、分阶测试题。
3. 路径必须围绕用户输入的学习主题和当前知识库证据。
4. 不得预设、暗示或偏向任何固定领域；领域范围只能从用户输入、学习者画像和知识库片段中推断。
5. 按当前主题所属领域的知识结构安排先修知识、补救内容和进阶挑战。

请用 JSON 格式输出：
{
  "learning_path": [{"order": 1, "topic": "知识点", "reason": "推荐原因"}],
  "skip_points": ["可跳过知识点"],
  "remedial_points": ["需要补救知识点"],
  "challenge_points": ["可进阶挑战知识点"],
  "resource_requirements": {
    "讲义": "讲义生成要求",
    "实操指南": "实操指南生成要求",
    "分阶测试题": "测试题生成要求"
  },
  "decision_reason": "总体规划理由"
}
不要包含额外解释。
"""


def _fallback_plan(state: AgentState) -> dict:
    learner = state["learner"]
    diagnosis = state.get("diagnosis", {})
    topic = state["topic"]
    weak_points = diagnosis.get("weak_points") or learner.weak_points or [topic]

    learning_path = []
    for index, point in enumerate(weak_points[:3], start=1):
        learning_path.append({
            "order": index,
            "topic": point,
            "reason": "该知识点是当前画像或诊断结果中的薄弱项，需要优先补齐。",
        })
    learning_path.append({
        "order": len(learning_path) + 1,
        "topic": topic,
        "reason": "围绕当前学习主题完成综合实操。",
    })

    return {
        "learning_path": learning_path,
        "skip_points": learner.strong_points[:2],
        "remedial_points": weak_points[:3],
        "challenge_points": [f"{topic} 进阶挑战"] if learner.skill_level in {"高级", "进阶"} else [],
        "resource_requirements": {
            "讲义": "先解释薄弱知识点，再串联到当前学习主题的完整知识结构。",
            "实操指南": "提供可执行步骤、参数选择和常见错误排查。",
            "分阶测试题": "覆盖基础理解、参数判断和小型实操分析。",
        },
        "decision_reason": "LLM 规划结果不可解析，按薄弱知识点、学习主题和优势能力生成保底路径。",
    }


def plan_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
) -> dict:
    """学习路径规划 Agent：输出路径和资源生成要求"""
    step_context = start_step(state)
    node_input = PlannerInput.model_validate(state)
    learner = node_input.learner
    diagnosis = node_input.diagnosis
    evidence = node_input.retrieved_evidence
    if not evidence:
        raise ApplicationError(ErrorCode.EVIDENCE_INSUFFICIENT, status_code=422)

    evidence_summary = [
        {
            "evidence_id": item.evidence_id,
            "source_path": item.locator.source_path,
            "section": item.locator.section,
            "excerpt": item.excerpt[:160],
            "normalized_score": item.normalized_score,
        }
        for item in evidence[:5]
    ]

    user_input = f"""
学习主题：{node_input.topic}
诊断结果 ID：{node_input.diagnostic_result_id or '无'}
目标能力节点：{node_input.target_skill_nodes or ['未指定']}
请求难度：{node_input.difficulty_preference or '未指定'}
生成模式：{node_input.generation_mode}
生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}
学习者画像：
- skill_level: {learner.skill_level}
- theory_scores: {learner.theory_scores}
- weak_points: {learner.weak_points}
- strong_points: {learner.strong_points}
- learning_goal: {learner.learning_goal}

学情诊断结果：
{json.dumps(diagnosis, ensure_ascii=False)}

知识库证据摘要：
{json.dumps(evidence_summary, ensure_ascii=False)}
"""

    llm_result = None
    error = None
    try:
        messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=user_input),
        ]
        llm_result = llm_gateway.invoke_structured(
            messages=messages,
            output_schema=PlannerLLMOutput,
            context=LLMCallContext(
                run_id=node_input.run_id,
                step_id=step_context["step_id"],
                node_name="planner",
                schema_name=PlannerLLMOutput.__name__,
                generation_attempt=step_context["attempt"],
                workflow_deadline_at=state.get("workflow_deadline_at"),
            ),
            options=llm_gateway.options_for("planner", temperature=0.1),
        )
        plan = llm_result.output.model_dump(mode="python")
    except LLMGatewayError as exc:
        error = require_agent_fallback(state, exc.error)
        llm_result = exc
        plan = _fallback_plan(state)

    path = plan.get("learning_path", [])
    plan["target_skill_nodes"] = node_input.target_skill_nodes
    plan["difficulty_preference"] = node_input.difficulty_preference
    plan["generation_mode"] = node_input.generation_mode
    plan["constraints"] = node_input.constraints
    path_summary = " -> ".join([item.get("topic", "") for item in path[:4]]) or node_input.topic
    status = StepStatus.DEGRADED if error else StepStatus.SUCCESS
    NodeResult[PlannerOutput](
        status=status,
        output=PlannerOutput(learning_plan=plan),
        error=error,
    )
    trace_item = build_trace_item(
        state,
        agent_name="planner",
        action="学习路径规划",
        status=status,
        input_summary=f"目标节点：{node_input.target_skill_nodes}；诊断盲区：{diagnosis.get('weak_points', learner.weak_points)}；证据数：{len(evidence)}",
        output_summary=f"学习路径：{path_summary}",
        decision_reason=plan.get("decision_reason", "根据诊断盲区、知识库证据和学习目标规划资源生成顺序。"),
        evidence_refs=[item.evidence_id for item in evidence[:5]],
        error=error,
        step_context=step_context,
        llm_metadata=llm_result.trace_metadata() if llm_result else None,
    )

    return {
        "learning_plan": plan,
        "current_node": "planner",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
    }
