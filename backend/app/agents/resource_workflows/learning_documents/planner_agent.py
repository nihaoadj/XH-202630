import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.learning_documents.state import AgentState
from app.agents.shared.evidence_scope import allocation_for_state
from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.agent_contracts import (
    NodeResult,
    PlannerLLMOutput,
    PlannerInput,
    PlannerOutput,
    build_trace_item,
    require_agent_fallback,
    make_error_info,
    start_step,
)
from app.models.shared.llm import LLMCallContext
from app.models.shared.workflow import StepStatus


PLANNER_PROMPT = """你是一名学习路径规划 Agent。请根据学习者画像、学情诊断结果、学习主题和已检索到的知识库证据，规划个性化学习路径。
规划目标：
1. 决定学习者先学什么、跳过什么、补什么、挑战什么。
2. 输出资源生成要求，使后续生成 Agent 能生成讲义、实操指南、分阶测试题、复习清单和案例分析。
3. 路径必须围绕用户输入的学习主题和当前知识库证据。
4. 不得预设、暗示或偏向任何固定领域；领域范围只能从用户输入、学习者画像和知识库片段中推断。
5. 按当前主题所属领域的知识结构安排先修知识、补救内容和进阶挑战。
6. 当输入提供目标能力节点时，目标节点是本次生成的硬范围；weak_points 只能作为画像背景，不能新增、替换或扩展目标节点。
7. 若选择实操指南，其生成要求必须指定一个可亲手完成的最小操作目标，说明示例输入、运行环境和可观察的完成结果；仅使用当前资源可用的冻结证据，不得把概念复述或纸笔推演当作实操目标。

请用 JSON 格式输出：
{
  "learning_path": [{"order": 1, "topic": "知识点", "reason": "推荐原因"}],
  "skip_points": ["可跳过知识点"],
  "remedial_points": ["需要补救知识点"],
  "challenge_points": ["可进阶挑战知识点"],
  "resource_requirements": {
    "讲义": "讲义生成要求",
    "实操指南": "实操指南生成要求",
    "分阶测试题": "测试题生成要求",
    "复习清单": "复习清单生成要求",
    "案例分析": "案例分析生成要求"
  },
  "decision_reason": "总体规划理由"
}
不要包含额外解释。
"""

LECTURE_PLANNING_GUIDANCE = """
本次包含讲义。仅在 resource_requirements["讲义"] 中安排读者应理解的目标概念、概念关系和适用边界，按请求难度组织讲解。需要示例时优先选用所分配冻结证据支持的短例，明确它要解释哪个概念。只有同一情境有助于串联多个目标概念且材料齐全时才安排贯穿案例。可以省略示例或缩小示例范围，避免依赖缺失的原文、题目或外部资料。正文以解释概念为主，末尾自检可省略。
"""

PRACTICE_PLANNING_GUIDANCE = """
本次包含实操指南。为 resource_requirements["实操指南"] 选择一个与目标节点和所分配冻结证据相符的最小可运行任务：学习者必须实际运行程序或命令，让输入经过处理并产生可观察的输出或文件。手动填写诊断表、摘录证据、回答问题、拆解观点和抄写预填答案可以作为辅助练习，不能充当主要操作；即使教材把它称作“实验”也一样。
该要求用一段文字明确写出五项内容：任务（运行什么以完成什么目标）、环境与工具（学习者需要准备什么）、输入（首次使用时在哪一步用代码创建或定义）、逐步执行动作（每个独立步骤运行哪段代码）、结果验证（每步观察什么输出或文件，如何核对）。不要规划“准备阶段给出整份脚本，再分步复制、运行和阅读”的流程；不含可运行代码的保存、阅读和检查动作并入相邻步骤。不要预先给出全部操作结果让学习者只需复制。示例输入可以是标明“教学示例”的短文或数据，但不能要求学习者自行查找未展示的资料。
优先使用冻结证据中与目标节点匹配的操作方法。若专有服务、模型或向量库的依赖超出当前节点或证据支持范围，选择更小的本地可运行演示，并明确它只是教学演示，不宣称实现完整服务；不要因此退化为纯手动演练，也不要编造 API、环境能力或实测数值。其他资源类型的要求仍按其自身用途规划。
"""


def _fallback_plan(state: AgentState) -> dict:
    learner = state["learner"]
    diagnosis = state.get("diagnosis", {})
    topic = state["topic"]
    target_nodes = list(dict.fromkeys(str(item).strip() for item in state.get("target_skill_nodes", []) if str(item).strip()))
    weak_points = diagnosis.get("weak_points") or learner.weak_points or [topic]
    focus_points = target_nodes or weak_points
    lecture_requirement = (
        "先解释目标节点，再串联到当前学习主题的完整知识结构。" if target_nodes
        else "先解释薄弱知识点，再串联到当前学习主题的完整知识结构。"
    )
    if "讲义" in state.get("resource_types", []):
        lecture_requirement = (
            "按难度解释当前目标范围内的概念、关系和边界。"
            "需要时用冻结证据支持的短例帮助讲解，自检可省略。"
        )

    learning_path = []
    for index, point in enumerate(focus_points[:3], start=1):
        learning_path.append({
            "order": index,
            "topic": point,
            "reason": "该节点是本次请求明确指定的生成范围。" if target_nodes else "该知识点是当前画像或诊断结果中的薄弱项，需要优先补齐。",
        })
    if not target_nodes:
        learning_path.append({
            "order": len(learning_path) + 1,
            "topic": topic,
            "reason": "围绕当前学习主题完成综合实操。",
        })

    return {
        "learning_path": learning_path,
        "skip_points": learner.strong_points[:2],
        "remedial_points": focus_points[:3],
        "challenge_points": [f"{point} 进阶挑战" for point in focus_points[:2]] if learner.skill_level in {"高级", "进阶"} else [],
        "resource_requirements": {
            "讲义": lecture_requirement,
            "实操指南": "围绕当前节点完成最小操作任务：准备阶段只说明环境；示例输入在首次使用的步骤用代码创建；每个独立步骤都有可运行代码，按顺序执行并观察输出；最后核查产物及关键失败条件。只使用冻结证据支持的接口和参数。",
            "分阶测试题": "覆盖基础理解、参数判断和小型实操分析。",
            "复习清单": "提炼必会要点、易错点、自测项目和可执行复习节奏。",
            "案例分析": "用受控证据构造情境，要求分析、决策并给出可追溯的参考方案。",
        },
        "decision_reason": "LLM 规划结果不可解析，按显式目标节点生成保底路径。" if target_nodes else "LLM 规划结果不可解析，按薄弱知识点、学习主题和优势能力生成保底路径。",
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

    allocation = allocation_for_state(state)
    evidence_summary = [
        {
            "evidence_id": item.evidence_id,
            "source_path": item.locator.source_path,
            "section": item.locator.section,
            "excerpt": item.excerpt if allocation else item.excerpt[:160],
            "normalized_score": item.normalized_score,
        }
        for item in (evidence if allocation else evidence[:5])
    ]

    if allocation:
        for summary, item in zip(evidence_summary, evidence):
            summary["locator"] = item.locator.model_dump(mode="json")

    user_input = f"""
学习主题：{node_input.topic}
诊断结果 ID：{node_input.diagnostic_result_id or '无'}
目标能力节点：{node_input.target_skill_nodes or ['未指定']}
目标节点约束：{('本次生成只能围绕上述目标节点；weak_points 仅作背景参考。' if node_input.target_skill_nodes else '未指定目标节点时才可使用 weak_points 作为回退候选。')}
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

    if allocation:
        user_input += "\n已选资源类型与冻结分配（正文仅在上述证据中提供）：\n" + json.dumps({
            "resource_types": node_input.resource_types,
            "allocation": allocation.model_dump(mode="json"),
            "node_evidence_map": node_input.node_evidence_map,
            "available_evidence_ids": {kind: allocation.available_ids(kind) for kind in node_input.resource_types},
        }, ensure_ascii=False)
    llm_result = None
    error = None
    try:
        messages = [
            SystemMessage(content=PLANNER_PROMPT
                          + (LECTURE_PLANNING_GUIDANCE if "讲义" in node_input.resource_types else "")
                          + (PRACTICE_PLANNING_GUIDANCE if "实操指南" in node_input.resource_types else "")
                          + ("\n只为已选资源类型输出要求；各类型要求必须依据其 available_evidence_ids，不得调整冻结分配。" if allocation else "")),
            HumanMessage(content=user_input),
        ]
        options = llm_gateway.options_for("planner", temperature=0.1)
        if allocation:
            settings = get_settings()
            # UTF-8 bytes plus framing reserve bound tokens conservatively; this is not tokenization.
            estimated = len(json.dumps({"messages": [message.content for message in messages], "schema": PlannerLLMOutput.model_json_schema()}, ensure_ascii=False).encode("utf-8")) + 1024
            window = settings.resource_aware_planner_context_tokens
            if window is None or estimated > settings.resource_aware_planner_input_budget_tokens or estimated + options.max_output_tokens > window:
                raise LLMGatewayError(error=make_error_info(ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, source="planner", category="input_budget", safe_detail="complete_planner_input_budget_exceeded_or_window_unconfigured"), call_id="planner-input-budget", retry_count=0, latency_ms=0, attempts=[])
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
            options=options,
        )
        plan = llm_result.output.model_dump(mode="python")
    except LLMGatewayError as exc:
        error = require_agent_fallback(state, exc.error)
        llm_result = exc
        plan = _fallback_plan(state)
        if exc.error.category == "input_budget":
            plan["decision_reason"] = "完整输入预算预检未通过，未执行 AI 规划；使用显式降级规则规划。"

    if allocation:
        plan["resource_requirements"] = {kind: value for kind, value in plan.get("resource_requirements", {}).items() if kind in node_input.resource_types}
    path = plan.get("learning_path", [])
    target_nodes = list(node_input.target_skill_nodes)
    if target_nodes:
        # Keep the model's explanatory reasons where possible, but make the
        # plan's actionable path deterministic and node-scoped.
        reasons = {
            str(item.get("topic")): str(item.get("reason") or "")
            for item in path
            if isinstance(item, dict)
        }
        plan["learning_path"] = [
            {"order": index, "topic": node_id,
             "reason": reasons.get(node_id) or "本次请求明确指定的目标节点。"}
            for index, node_id in enumerate(target_nodes, start=1)
        ]
        plan["remedial_points"] = [item for item in plan.get("remedial_points", []) if item in target_nodes] or target_nodes[:3]
        plan["skip_points"] = [item for item in plan.get("skip_points", []) if item in target_nodes]
        plan["challenge_points"] = [item for item in plan.get("challenge_points", []) if any(node in str(item) for node in target_nodes)]
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
        evidence_refs=[item.evidence_id for item in (evidence if allocation else evidence[:5])],
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
