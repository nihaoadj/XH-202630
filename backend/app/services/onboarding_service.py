"""根据 RAG 入门问卷创建初始画像，并选择自适应诊断题。"""
from __future__ import annotations

from typing import Any

from app.db.learner.base import BaseLearnerRepository
from app.models.schemas import (
    InitialProfileQuestionnaire,
    InitialProfileResponse,
    KnowledgeState,
    LearnerProfile,
    LearningPreferences,
)
from app.services.knowledge_service import KnowledgeService


IDENTITY_PROFILE = {
    "在校学生": "在校学生",
    "已工作，技术岗位": "职场学习者",
    "已工作，非技术岗位，准备转向 AI 方向": "转行学习者",
    "其他": "其他",
}

LEVEL_SCORES = {
    "完全不会": 0,
    "会基础语法，但很少写项目": 25,
    "能写脚本和调用 API": 50,
    "能完成中小型项目": 75,
    "比较熟练，能独立调试工程代码": 100,
    "没用过": 0,
    "只在网页端用过 ChatGPT/通义/豆包等": 25,
    "调用过 OpenAI 或兼容 API": 50,
    "做过基于大模型 API 的小项目": 75,
    "做过较完整的大模型应用": 100,
    "不清楚 Prompt 是什么": 0,
    "会写简单提问": 25,
    "知道角色设定、格式约束、上下文注入": 50,
    "能设计结构化 Prompt": 75,
    "能针对不同任务优化 Prompt": 100,
    "完全不了解": 0,
    "听说过，但说不清流程": 25,
    "知道大致流程：文档、向量化、检索、生成": 50,
    "搭建过简单 RAG Demo": 75,
    "做过 RAG 调优或评测": 100,
}

# 问卷第 7 题的自我陈述只决定“是否值得进一步测”，不能直接当作掌握证据。
KNOWN_NODE_MAP = {
    "文档解析": ["document_parsing"],
    "Chunk 切分": ["chunking"],
    "Embedding": ["embedding"],
    "向量数据库": ["vector_store"],
    "Top-K 检索": ["similarity_retrieval"],
    "Query Rewrite": ["similarity_retrieval"],
    "Rerank": ["rerank"],
    "Prompt 组装": ["prompt_assembly"],
    "引用溯源": ["citation"],
    "幻觉率评测": ["hallucination_control", "rag_evaluation"],
}


# 由后端维护问卷定义，避免前端硬编码题目后与画像字段发生偏差。
QUESTIONNAIRE = [
    {"question_id": "identity", "title": "你目前的身份是？", "type": "single_choice", "required": True,
     "options": list(IDENTITY_PROFILE)},
    {"question_id": "education", "title": "你的当前学历或教育阶段是？", "type": "single_choice_or_other", "required": True,
     "options": ["高中/中职", "专科", "本科", "硕士及以上", "已毕业/在职", "其他"]},
    {"question_id": "major", "title": "你的专业或当前岗位方向是？", "type": "text", "required": True,
     "hint": "例如：软件工程、机械工程、后端开发、产品运营"},
    {"question_id": "learning_goals", "title": "你的主要学习目标是？", "type": "multiple_choice", "required": True,
     "options": ["了解 RAG 基础概念", "能独立搭建一个 RAG Demo", "能优化 RAG 检索效果", "为比赛/项目开发做准备", "为面试/转岗 AI 应用开发或大模型相关岗位做准备"]},
    {"question_id": "python_level", "title": "你的 Python 基础如何？", "type": "single_choice", "required": True,
     "options": ["完全不会", "会基础语法，但很少写项目", "能写脚本和调用 API", "能完成中小型项目", "比较熟练，能独立调试工程代码"]},
    {"question_id": "llm_api_level", "title": "你是否使用过大模型 API？", "type": "single_choice", "required": True,
     "options": ["没用过", "只在网页端用过 ChatGPT/通义/豆包等", "调用过 OpenAI 或兼容 API", "做过基于大模型 API 的小项目", "做过较完整的大模型应用"]},
    {"question_id": "prompt_level", "title": "你对 Prompt 的理解程度是？", "type": "single_choice", "required": True,
     "options": ["不清楚 Prompt 是什么", "会写简单提问", "知道角色设定、格式约束、上下文注入", "能设计结构化 Prompt", "能针对不同任务优化 Prompt"]},
    {"question_id": "rag_level", "title": "你对 RAG 的了解程度是？", "type": "single_choice", "required": True,
     "options": ["完全不了解", "听说过，但说不清流程", "知道大致流程：文档、向量化、检索、生成", "搭建过简单 RAG Demo", "做过 RAG 调优或评测"]},
    {"question_id": "known_rag_nodes", "title": "以下 RAG 环节中，你了解哪些？", "type": "multiple_choice", "required": False,
     "options": [*KNOWN_NODE_MAP, "都不了解"], "hint": "只对选中的节点安排后续诊断；“都不了解”不可与其他选项同时选择。"},
    {"question_id": "embedding_screening_answer", "title": "场景筛查：用户问法与文档措辞不同，仍希望召回相关片段。Embedding 在此最主要的作用是？", "type": "single_choice", "required": False,
     "show_when": {"known_rag_nodes_contains": "Embedding"},
     "options": ["把问题和文档编码为语义向量，再按相似度召回片段", "把文档按固定字数切分", "要求模型只回答“我不知道”", "用交叉编码器对候选结果重新排序"]},
    {"question_id": "vector_store_experience", "title": "你是否使用过向量数据库或向量检索工具？", "type": "single_choice", "required": False,
     "options": ["听说过 FAISS、Chroma、Milvus 等", "用过 FAISS 或 Chroma", "用过 Milvus、Qdrant、Elasticsearch 等", "做过向量库调优或线上应用", "没用过/没听说过"]},
    {"question_id": "rag_failure_causes", "title": "如果一个 RAG 系统回答不准确，你认为可能原因有哪些？", "type": "multiple_choice", "required": False,
     "options": ["文档切分不准确", "Embedding 效果不好", "检索没有命中相关内容", "Top-K 或相似度阈值设置不合适", "Prompt 没要求基于证据回答", "模型自身幻觉", "不太清楚"]},
    {"question_id": "desired_resource_types", "title": "希望系统优先生成哪些学习资源？", "type": "multiple_choice", "required": False,
     "options": ["图解讲义", "一步步实操教程", "代码模板", "分阶测试题", "项目案例", "调参建议", "面试/转岗建议"]},
    {"question_id": "learning_modes", "title": "你偏好的学习方式是？", "type": "multiple_choice", "required": False,
     "options": ["先讲概念，再做练习", "直接做项目，边做边学", "看代码案例理解", "看图解和类比理解", "先做测试，系统根据薄弱点推荐内容"]},
    {"question_id": "difficulty_preference", "title": "你希望第一轮学习资源的难度如何？", "type": "single_choice", "required": False,
     "options": ["自适应推荐", "从基础开始", "保持当前水平", "优先挑战进阶内容"]},
    {"question_id": "weekly_time_budget", "title": "你每周大概能投入多少时间学习 RAG？", "type": "single_choice", "required": False,
     "options": ["0.5-1 小时", "1-2 小时", "2-4 小时", "4-6 小时", "6 小时以上"]},
]


class OnboardingService:
    def __init__(self, learner_repo: BaseLearnerRepository, knowledge_service: KnowledgeService):
        self.learner_repo = learner_repo
        self.knowledge_service = knowledge_service

    def create_initial_profile(self, request: InitialProfileQuestionnaire) -> InitialProfileResponse:
        self._validate_answers(request)
        manifest = self.knowledge_service._ensure_knowledge_base(None)
        nodes = self.knowledge_service.list_skill_nodes(manifest["knowledge_base_id"])
        node_by_id = {node.node_id: node for node in nodes}

        diagnostic_node_ids, screening_results = self._diagnostic_node_ids(request, node_by_id)
        not_started_node_ids = [node.node_id for node in nodes if node.node_id not in diagnostic_node_ids]
        existing = self.learner_repo.get(request.learner_id)
        profile = self._build_profile(
            request,
            existing,
            manifest["knowledge_base_id"],
            node_by_id,
            diagnostic_node_ids,
            not_started_node_ids,
        )
        self.learner_repo.save(profile)

        questions = (
            self.knowledge_service.select_diagnostic_questions(
                manifest["knowledge_base_id"], skill_node_ids=diagnostic_node_ids
            )
            if diagnostic_node_ids
            else []
        )
        return InitialProfileResponse(
            learner_id=profile.learner_id,
            profile=profile,
            diagnostic_node_ids=diagnostic_node_ids,
            not_started_node_ids=not_started_node_ids,
            screening_results=screening_results,
            diagnostic_questions=[self.knowledge_service.public_question(question) for question in questions],
            next_step=(
                "提交 diagnostic_questions 的作答到 POST /api/diagnosis/submit；"
                "未了解节点已标记为 not_started，不会出现在本轮诊断中。"
            ),
        )

    @staticmethod
    def questionnaire() -> list[dict[str, Any]]:
        """返回前端渲染所需的问卷定义，不包含诊断题标准答案。"""
        return QUESTIONNAIRE

    def _validate_answers(self, request: InitialProfileQuestionnaire) -> None:
        if request.identity not in IDENTITY_PROFILE:
            raise ValueError("identity 必须使用 RAG 学习画像问卷中的选项")
        level_fields = (request.python_level, request.llm_api_level, request.prompt_level, request.rag_level)
        invalid_levels = [value for value in level_fields if value not in LEVEL_SCORES]
        if invalid_levels:
            raise ValueError(f"存在不支持的能力自评选项：{', '.join(invalid_levels)}")
        choices = set(request.known_rag_nodes)
        invalid_nodes = choices - (set(KNOWN_NODE_MAP) | {"都不了解"})
        if invalid_nodes:
            raise ValueError(f"第 7 题包含未知节点：{', '.join(sorted(invalid_nodes))}")
        if "都不了解" in choices and len(choices) > 1:
            raise ValueError("第 7 题选择“都不了解”时不能同时选择其他节点")

    def _diagnostic_node_ids(
        self, request: InitialProfileQuestionnaire, node_by_id: dict[str, Any]
    ) -> tuple[list[str], dict[str, bool]]:
        selected = set()
        for option in request.known_rag_nodes:
            selected.update(KNOWN_NODE_MAP.get(option, []))

        # 第 6 题不是掌握证明，但只要用户表示接触过 RAG，就补测 RAG 基础概念。
        if LEVEL_SCORES[request.rag_level] > 0:
            selected.add("rag_basics")
        if request.rag_level == "做过 RAG 调优或评测":
            selected.update({"rag_evaluation", "rag_tuning"})

        screening_results: dict[str, bool] = {}
        if "embedding" in selected:
            screening_results["embedding"] = (
                request.embedding_screening_answer == "把问题和文档编码为语义向量，再按相似度召回片段"
            )
            if not screening_results["embedding"]:
                selected.discard("embedding")

        return [node_id for node_id in node_by_id if node_id in selected], screening_results

    def _build_profile(
        self,
        request: InitialProfileQuestionnaire,
        existing: LearnerProfile | None,
        knowledge_base_id: str,
        node_by_id: dict[str, Any],
        diagnostic_node_ids: list[str],
        not_started_node_ids: list[str],
    ) -> LearnerProfile:
        learner_type = IDENTITY_PROFILE[request.identity]
        score_values = [
            LEVEL_SCORES[request.python_level],
            LEVEL_SCORES[request.llm_api_level],
            LEVEL_SCORES[request.prompt_level],
            LEVEL_SCORES[request.rag_level],
        ]
        average = sum(score_values) / len(score_values)
        skill_level = "初级" if average < 40 else "中级" if average < 75 else "进阶"

        prior_states = dict(existing.knowledge_states) if existing else {}
        for node_id in diagnostic_node_ids:
            name = node_by_id[node_id].name
            if name not in prior_states or self._is_onboarding_state(prior_states[name]):
                prior_states[name] = KnowledgeState(
                    status="self_reported",
                    evidence=["onboarding: user selected this node as known"],
                )
        for node_id in not_started_node_ids:
            name = node_by_id[node_id].name
            if name not in prior_states or self._is_onboarding_state(prior_states[name]):
                prior_states[name] = KnowledgeState(
                    status="not_started",
                    evidence=["onboarding: user did not select this node as known"],
                )

        prior_scores = dict(existing.theory_scores) if existing else {}
        prior_scores.update(
            {
                "自评：Python 基础": LEVEL_SCORES[request.python_level],
                "自评：大模型 API": LEVEL_SCORES[request.llm_api_level],
                "自评：Prompt": LEVEL_SCORES[request.prompt_level],
                "自评：RAG 基础": LEVEL_SCORES[request.rag_level],
            }
        )
        old_preferences = existing.learning_preferences if existing and existing.learning_preferences else LearningPreferences()
        metadata = dict(old_preferences.metadata)
        metadata["onboarding"] = request.model_dump(mode="json", exclude={"learner_id"})
        preferences = LearningPreferences(
            preferred_resource_types=request.desired_resource_types or old_preferences.preferred_resource_types,
            difficulty_preference=request.difficulty_preference or old_preferences.difficulty_preference or "自适应推荐",
            time_budget_minutes=old_preferences.time_budget_minutes,
            language=old_preferences.language or "zh-CN",
            metadata=metadata,
        )
        not_started_names = [node_by_id[node_id].name for node_id in not_started_node_ids]
        preserved_weak_points = list(existing.weak_points) if existing else []
        return LearnerProfile(
            learner_id=request.learner_id,
            learner_type=learner_type,
            education=request.education,
            major=request.major,
            target_domain="RAG 工程训练",
            knowledge_base_id=knowledge_base_id,
            theory_scores=prior_scores,
            knowledge_states=prior_states,
            skill_level=skill_level,
            weak_points=list(dict.fromkeys(preserved_weak_points + not_started_names)),
            strong_points=list(existing.strong_points) if existing else [],
            learning_goal="；".join(request.learning_goals),
            learning_preferences=preferences,
            last_feedback_summary=existing.last_feedback_summary if existing else {},
        )

    @staticmethod
    def _is_onboarding_state(state: KnowledgeState) -> bool:
        return bool(state.evidence) and all(item.startswith("onboarding:") for item in state.evidence)
