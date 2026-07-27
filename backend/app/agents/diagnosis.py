import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.llm import get_llm


DIAGNOSIS_PROMPT = """你是一名专业的学情诊断 Agent。请根据学习者的画像信息，分析其理论强项、知识盲区、整体能力水平，并输出：
1. ability_tags: 能力标签列表
2. weak_points: 知识盲区列表（按优先级排序）
3. recommended_difficulty: 建议的学习路径起点难度（初级/中级/高级）
4. suggestion: 针对学习目标的个性化建议

请用 JSON 格式输出，字段名必须使用上述英文名称，不要包含额外解释。
"""


def diagnose_node(state: AgentState) -> AgentState:
    """学情诊断 Agent：解析学习者画像"""
    learner = state["learner"]

    user_input = f"""
学习者画像：
- education（学历）：{learner.education}
- major（专业）：{learner.major}
- skill_level（技能水平）：{learner.skill_level}
- theory_scores（理论测试得分）：{learner.theory_scores}
- weak_points（知识盲区）：{learner.weak_points}
- strong_points（优势领域）：{learner.strong_points}
- learning_goal（学习目标）：{learner.learning_goal}
- 当前主题：{state['topic']}
"""
    fallback_code = None
    try:
        llm = get_llm()
        messages = [
            SystemMessage(content=DIAGNOSIS_PROMPT),
            HumanMessage(content=user_input),
        ]
        response = llm.invoke(messages)
        diagnosis = json.loads(response.content)
    except Exception:
        fallback_code = require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE)
        diagnosis = {
            "ability_tags": learner.strong_points,
            "weak_points": learner.weak_points,
            "recommended_difficulty": learner.skill_level or "中级",
            "suggestion": "LLM 不可用，已按显式降级策略使用画像信息生成保底诊断。",
        }

    trace_item = {
        "agent_name": "diagnosis",
        "action": "学情诊断",
        "input_summary": f"画像：{learner.skill_level}；主题：{state['topic']}",
        "output_summary": f"推荐难度：{diagnosis.get('recommended_difficulty', '未知')}; 盲区：{diagnosis.get('weak_points', [])}",
        "decision_reason": diagnosis.get("suggestion", "根据画像得分、知识盲区和学习目标判断能力起点。"),
        "status": "degraded" if fallback_code else "success",
        "error_code": fallback_code,
    }

    return {
        "diagnosis": diagnosis,
        "trace": [trace_item],
    }
