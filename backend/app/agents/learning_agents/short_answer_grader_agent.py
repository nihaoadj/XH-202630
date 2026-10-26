"""Structured short-answer grading; the service owns errors and score policy."""
from __future__ import annotations

import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.gateway import LLMGateway
from app.models.shared.agent_contracts import AssessmentShortAnswerGradeV1
from app.models.shared.llm import LLMCallContext, LLMCallResult


def grade_short_answer(
    llm_gateway: LLMGateway, question: dict, actual: object, *, maximum: float,
) -> LLMCallResult[AssessmentShortAnswerGradeV1]:
    prompt = {
        "question": question.get("stem"),
        "learner_answer": str(actual or ""),
        "reference_answer": question.get("reference_answer"),
        "rubric": question.get("rubric"),
        "max_score": maximum,
        "scoring_rules": [
            "仅依据 reference_answer、rubric 和冻结题目证据评分，不补充证据外事实。",
            "逐项判断 rubric，得分范围为 0 到 max_score；空答案必须为 0 分。",
            "得分保留 1 位小数，反馈简短说明失分或得分依据。",
        ],
    }
    return llm_gateway.invoke_structured(
        messages=[SystemMessage(content=(
            "你是分阶测试反馈评分 Agent。按参考答案和 rubric 逐项评分，只返回结构化得分和简短反馈。"
            "分数必须在 0 到 max_score 之间；空答案必须得 0 分；不要因表达方式不同而重复扣分。"
        )), HumanMessage(content=json.dumps(prompt, ensure_ascii=False))],
        output_schema=AssessmentShortAnswerGradeV1,
        context=LLMCallContext(run_id="feedback-grading", step_id=str(question.get("question_id")), node_name="short_answer_grader", schema_name="AssessmentShortAnswerGradeV1"),
        options=llm_gateway.options_for("feedback_agent", temperature=0.0),
    )
