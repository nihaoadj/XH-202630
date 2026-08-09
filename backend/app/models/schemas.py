from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatusResponse(BaseModel):
    """通用成功响应模型"""
    status: str = Field(default="success", description="响应状态")
    message: Optional[str] = Field(default=None, description="响应消息")


class ErrorResponse(BaseModel):
    """通用错误响应模型"""
    status: str = Field(default="error", description="响应状态")
    message: str = Field(..., description="错误描述")
    detail: Optional[Any] = Field(default=None, description="错误详情")


class ProfileStatusResponse(StatusResponse):
    """学习者画像写入响应模型"""
    learner_id: str = Field(..., description="学习者唯一标识")


class LearnerProfileUpdate(BaseModel):
    """学习者画像的白名单部分更新请求。"""
    learner_type: Optional[str] = None
    education: Optional[str] = None
    major: Optional[str] = None
    target_domain: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    theory_scores: Optional[Dict[str, float]] = None
    knowledge_states: Optional[Dict[str, "KnowledgeState"]] = None
    skill_level: Optional[str] = None
    weak_points: Optional[List[str]] = None
    strong_points: Optional[List[str]] = None
    learning_goal: Optional[str] = None
    learning_preferences: Optional["LearningPreferences"] = None
    last_feedback_summary: Optional[Dict[str, Any]] = None


class KnowledgeState(BaseModel):
    """通用知识点掌握状态"""
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="掌握度，建议 0-1")
    status: Optional[str] = Field(default=None, description="掌握状态")
    evidence: List[str] = Field(default_factory=list, description="状态依据")
    last_updated: Optional[str] = Field(default=None, description="最近更新时间")


class LearningPreferences(BaseModel):
    """学习偏好"""
    preferred_resource_types: List[str] = Field(default_factory=list, description="偏好的资源类型")
    difficulty_preference: Optional[str] = Field(default=None, description="难度偏好")
    time_budget_minutes: Optional[int] = Field(default=None, ge=0, description="单次学习时间预算")
    language: Optional[str] = Field(default=None, description="输出语言")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展偏好")


class LearnerProfile(BaseModel):
    """学习者画像模型"""
    learner_id: str = Field(..., description="学习者唯一标识")
    learner_type: str = Field(..., description="学习者类型")
    education: str = Field(..., description="学历背景")
    major: str = Field(..., description="专业方向")
    target_domain: Optional[str] = Field(default=None, description="目标领域，由用户或知识库决定")
    knowledge_base_id: Optional[str] = Field(default=None, description="当前知识库 ID")
    theory_scores: Dict[str, float] = Field(default_factory=dict, description="理论测试得分")
    knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict, description="知识点掌握状态")
    skill_level: str = Field(default="初级", description="技能水平")
    weak_points: List[str] = Field(default_factory=list, description="知识盲区")
    strong_points: List[str] = Field(default_factory=list, description="优势领域")
    learning_goal: str = Field(..., description="学习目标")
    learning_preferences: Optional[LearningPreferences] = Field(default=None, description="学习偏好")
    last_feedback_summary: Dict[str, Any] = Field(default_factory=dict, description="最近反馈摘要")


class InitialProfileQuestionnaire(BaseModel):
    """初始画像问卷提交；具体题目字段由数据库问卷定义决定。"""
    model_config = ConfigDict(extra="allow")

    learner_id: str
    learning_direction_id: Optional[str] = Field(default=None, description="用户选择的学习方向 ID")
    answers: Dict[str, Any] = Field(default_factory=dict, description="问卷答案；也兼容旧版平铺字段")


class InitialProfileResponse(BaseModel):
    """初始画像创建结果及只针对已了解节点的诊断题。"""
    learner_id: str
    profile: LearnerProfile
    diagnostic_node_ids: List[str]
    not_started_node_ids: List[str]
    screening_results: Dict[str, bool] = Field(default_factory=dict)
    diagnostic_questions: List[Dict[str, Any]]
    next_step: str


class SkillNode(BaseModel):
    """能力图谱节点"""
    node_id: str
    knowledge_base_id: str
    name: str
    description: Optional[str] = None
    level: Optional[str] = None
    prerequisites: List[str] = Field(default_factory=list)
    children: List[str] = Field(default_factory=list)
    knowledge_points: List[str] = Field(default_factory=list)
    assessment_methods: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiagnosticQuestion(BaseModel):
    """诊断题"""
    question_id: str
    knowledge_base_id: str
    skill_node_id: Optional[str] = None
    knowledge_point: Optional[str] = None
    question_type: str
    difficulty: Optional[str] = None
    question: str
    options: List[str] = Field(default_factory=list)
    answer: Optional[Any] = None
    explanation: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiagnosticAnswerSubmission(BaseModel):
    """学习者提交的诊断作答；正确性只能由服务端计算。"""
    question_id: str
    answer: Any


class DiagnosticAnswerRecord(DiagnosticAnswerSubmission):
    """服务端判定后的诊断答题记录。"""
    correct: bool
    score: float = Field(ge=0.0, le=1.0)


class DiagnosticQuestionListResponse(BaseModel):
    knowledge_base_id: str
    total: int
    questions: List[Dict[str, Any]]


class DiagnosticSubmitRequest(BaseModel):
    learner_id: str
    learning_direction_id: Optional[str] = Field(default=None, description="用户选择的学习方向 ID")
    knowledge_base_id: Optional[str] = None
    answers: List[DiagnosticAnswerSubmission] = Field(min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LearningPathItem(BaseModel):
    """学习路径数据项"""
    order: int
    topic: str
    reason: str


class DiagnosticResult(BaseModel):
    """诊断结果"""
    diagnostic_result_id: str
    learner_id: str
    knowledge_base_id: Optional[str] = None
    ability_level: str
    weak_points: List[str] = Field(default_factory=list)
    strong_points: List[str] = Field(default_factory=list)
    knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict)
    recommended_path: List[LearningPathItem] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class GenerateRequest(BaseModel):
    """生成资源请求模型"""
    learner_id: str
    topic: str = Field(..., description="学习主题")
    knowledge_base_id: Optional[str] = Field(default=None, description="当前知识库 ID")
    diagnostic_result_id: Optional[str] = Field(default=None, description="诊断结果 ID")
    target_skill_nodes: List[str] = Field(default_factory=list, description="目标能力节点")
    resource_types: List[str] = Field(
        default_factory=lambda: ["讲义", "实操指南", "分阶测试题"],
        min_length=1,
    )
    difficulty_preference: Optional[str] = Field(default=None, description="难度偏好")
    generation_mode: Optional[Literal["draft", "standard", "strict"]] = Field(
        default="standard",
        description="生成模式：draft | standard | strict",
    )
    include_review: bool = Field(default=True, description="是否进入审核")
    include_claim_check: bool = Field(default=False, description="是否进行 Claim 级审核")
    max_iterations: int = Field(default=2, ge=0, le=3, description="最大业务返工次数")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="生成约束")

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("topic cannot be blank")
        return normalized

    @field_validator("target_skill_nodes")
    @classmethod
    def deduplicate_target_nodes(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values if value and value.strip()]
        return list(dict.fromkeys(normalized))

    @field_validator("resource_types")
    @classmethod
    def normalize_resource_types(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values if value and value.strip()]
        normalized = list(dict.fromkeys(normalized))
        if not normalized:
            raise ValueError("resource_types cannot be empty")
        return normalized


class GenerationJobCreateResponse(StatusResponse):
    """异步资源生成任务创建响应"""
    run_id: str
    learner_id: str
    topic: str
    knowledge_base_id: Optional[str] = None
    job_status: Literal["queued", "running", "completed", "failed"] = "queued"


class GenerationJobStatusResponse(BaseModel):
    """异步资源生成任务状态响应"""
    run_id: str
    learner_id: str
    topic: str
    knowledge_base_id: Optional[str] = None
    job_status: Literal["queued", "running", "completed", "failed"]
    resource_ids: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class GenerationJobListResponse(BaseModel):
    """学习者生成任务列表响应"""
    learner_id: str
    total: int
    items: List[GenerationJobStatusResponse] = Field(default_factory=list)


class LearningPlan(BaseModel):
    """学习路径规划"""
    learning_path: List[LearningPathItem] = Field(default_factory=list)
    skip_points: List[str] = Field(default_factory=list)
    remedial_points: List[str] = Field(default_factory=list)
    challenge_points: List[str] = Field(default_factory=list)
    resource_requirements: Dict[str, str] = Field(default_factory=dict)
    decision_reason: Optional[str] = None


class SourceRef(BaseModel):
    """知识溯源引用"""
    doc_id: str
    title: str
    snippet: str
    score: float
    provenance_status: Literal["legacy", "verified"] = "legacy"
    evidence_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    document_version: Optional[str] = None
    chunk_id: Optional[str] = None
    knowledge_point: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    source_path: Optional[str] = None
    source_type: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    timestamp_start_ms: Optional[int] = None
    timestamp_end_ms: Optional[int] = None
    retrieval_query: Optional[str] = None
    query_hash: Optional[str] = None
    raw_score: Optional[float] = None
    score_kind: Optional[str] = None
    normalized_score: Optional[float] = None
    excerpt_hash: Optional[str] = None
    retrieval_config_hash: Optional[str] = None
    rank: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExerciseItem(BaseModel):
    """资源内练习项"""
    question_id: str
    knowledge_point: Optional[str] = None
    difficulty: Optional[str] = None
    question: str
    answer: Optional[Any] = None
    explanation: Optional[str] = None


class LearningResource(BaseModel):
    """学习资源模型"""
    resource_id: str
    learner_id: Optional[str] = None
    topic: Optional[str] = None
    resource_type: str
    difficulty: str
    storage_type: str = Field(default="text", description="存储方式：text | file")
    content_text: Optional[str] = Field(default=None, description="文本内容或文件摘要")
    file_path: Optional[str] = Field(default=None, description="文件相对路径（文件类资源）")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    mime_type: Optional[str] = Field(default=None, description="文件 MIME 类型")
    knowledge_points: List[str]
    source_refs: List[SourceRef]
    learning_path_node: Optional[str] = None
    review_status: Optional[str] = None
    review_id: Optional[str] = None
    publication_status: Literal["unpublished", "published"] = "unpublished"
    published_at: Optional[datetime] = None
    run_id: Optional[str] = None
    claim_count: Optional[int] = None
    hallucination_rate: Optional[float] = None
    difficulty_match: Optional[bool] = None
    version: int = 1
    parent_resource_id: Optional[str] = None
    created_at: Optional[datetime] = None
    exercise_items: List[ExerciseItem] = Field(default_factory=list)


class ResourceClaim(BaseModel):
    """Claim 级审核项"""
    claim_id: str
    text: str
    knowledge_point: Optional[str] = None
    supported: bool
    confidence: Optional[float] = None
    evidence_refs: List[SourceRef] = Field(default_factory=list)
    issue_type: Optional[str] = None
    correction: Optional[str] = None
    review_comment: Optional[str] = None


class ReviewSummary(BaseModel):
    """资源审核摘要"""
    review_id: str
    resource_id: str
    status: str
    claim_total: int = 0
    claim_supported: int = 0
    claim_unsupported: int = 0
    suspected_hallucinations: int = 0
    hallucination_rate: float = 0.0
    review_pass_rate: float = 0.0
    revision_count: int = 0
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    revision_instructions: List[Dict[str, Any]] = Field(default_factory=list)
    claims: List[ResourceClaim] = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def normalize_legacy_issues(cls, value: Any) -> List[Dict[str, Any]]:
        return [
            item
            if isinstance(item, dict)
            else {
                "code": "other",
                "severity": "medium",
                "description": str(item),
            }
            for item in (value or [])
        ]

    @field_validator("revision_instructions", mode="before")
    @classmethod
    def normalize_legacy_instructions(cls, value: Any) -> List[Dict[str, Any]]:
        return [
            item
            if isinstance(item, dict)
            else {
                "issue_codes": ["other"],
                "target_resource_type": "legacy_unknown",
                "action": str(item),
                "priority": 1,
            }
            for item in (value or [])
        ]


class AgentTrace(BaseModel):
    """Agent 执行轨迹"""
    model_config = ConfigDict(protected_namespaces=())

    schema_version: Literal["1.0"] = "1.0"
    agent_name: str
    node_name: Optional[str] = None
    action: str
    output_summary: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    sequence: Optional[int] = Field(default=None, ge=1)
    attempt: int = Field(default=1, ge=1)
    status: Literal[
        "running",
        "success",
        "degraded",
        "retryable_error",
        "failed",
        "human_review",
        "skipped",
    ]
    input_summary: Optional[str] = None
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    decision_reason: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    resource_ids: List[str] = Field(default_factory=list)
    review_ids: List[str] = Field(default_factory=list)
    review_summary: Dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error: Optional[Dict[str, Any]] = None
    llm_call_id: Optional[str] = None
    model_name: Optional[str] = None
    provider_request_id: Optional[str] = None
    structured_output_mode: Optional[str] = None
    finish_reason: Optional[str] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    llm_duration_ms: Optional[int] = Field(default=None, ge=0)
    llm_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_status: Optional[str] = None
    retrieval_config_hash: Optional[str] = None
    retrieval_query_hashes: List[str] = Field(default_factory=list)
    retrieval_candidate_count: Optional[int] = Field(default=None, ge=0)
    retrieval_dropped_candidate_count: Optional[int] = Field(default=None, ge=0)
    retrieval_partial_failure_count: Optional[int] = Field(default=None, ge=0)
    retrieval_query_count: Optional[int] = Field(default=None, ge=0)
    retrieval_evidence_count: Optional[int] = Field(default=None, ge=0)
    retrieval_dropped_count: Optional[int] = Field(default=None, ge=0)
    timestamp: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None


class GenerateReport(BaseModel):
    """单次生成摘要"""
    learner_id: str
    ability_level: Optional[str] = None
    ability_tags: List[str] = Field(default_factory=list)
    weak_points: List[str] = Field(default_factory=list)
    recommended_difficulty: Optional[str] = None
    learning_plan: Dict[str, Any] = Field(default_factory=dict)
    review_summary: Dict[str, Any] = Field(default_factory=dict)
    hallucination_rate: float = 0.0
    coverage_rate: float = 0.0
    difficulty_match: bool = False
    retrieval_hit_rate: float = 0.0
    revision_count: int = 0
    next_suggestions: List[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    """生成资源响应模型"""
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    workflow_status: Literal["running", "completed", "degraded", "failed", "human_review"]
    learner_id: str
    topic: str
    resources: List[LearningResource]
    trace: List[AgentTrace]
    report: GenerateReport
    execution_status: str = "success"
    error_codes: List[str] = Field(default_factory=list)


class ReportRadar(BaseModel):
    """学情报告雷达图数据"""
    dimensions: List[str]
    values: List[float]


class DifficultyCurveItem(BaseModel):
    """难度曲线数据项"""
    topic: str
    score: float
    recommended_difficulty: str


class FeedbackAnswer(BaseModel):
    """单题答题详情"""
    question_id: str
    correct: bool
    answer: Optional[Any] = Field(default=None, description="学习者作答内容")
    knowledge_point: Optional[str] = None
    difficulty: Optional[str] = None
    expected_answer: Optional[Any] = None
    error_type: Optional[str] = None


class FeedbackRequest(BaseModel):
    """学习反馈请求模型"""
    learner_id: str
    resource_id: str
    correct_rate: float = Field(..., ge=0.0, le=1.0)
    feedback_type: Optional[str] = Field(default=None, description="反馈类型")
    time_spent_seconds: Optional[int] = Field(default=None, ge=0, description="耗时")
    completed: Optional[bool] = Field(default=None, description="是否完成")
    self_rating: Optional[int] = Field(default=None, ge=1, le=5, description="自评")
    practice_result: Dict[str, Any] = Field(default_factory=dict, description="实操结果")
    answers: List[FeedbackAnswer] = Field(default_factory=list, description="答题详情")


class FeedbackResponse(BaseModel):
    """学习反馈响应模型"""
    learner_id: str
    decision: str
    message: str
    updated_profile: Optional[LearnerProfile] = None
    decision_reason: Optional[str] = None
    next_action: Optional[str] = None
    recommended_topics: List[str] = Field(default_factory=list)
    updated_knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict)
    regenerate_suggestion: Dict[str, Any] = Field(default_factory=dict)


class FeedbackDecisionResult(BaseModel):
    """反馈决策 Agent 输出"""
    decision: str
    decision_reason: str
    next_action: str
    recommended_topics: List[str] = Field(default_factory=list)
    updated_knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict)
    regenerate_suggestion: Dict[str, Any] = Field(default_factory=dict)
    profile_updates: Dict[str, Any] = Field(default_factory=dict)
    trace: AgentTrace


class FeedbackRecord(BaseModel):
    """学习反馈历史记录"""
    feedback_id: str
    learner_id: str
    resource_id: str
    correct_rate: float
    decision: str
    answers: List[FeedbackAnswer] = Field(default_factory=list)
    feedback_type: Optional[str] = None
    time_spent_seconds: Optional[int] = None
    completed: Optional[bool] = None
    self_rating: Optional[int] = None
    practice_result: Dict[str, Any] = Field(default_factory=dict)
    decision_reason: Optional[str] = None
    next_action: Optional[str] = None
    recommended_topics: List[str] = Field(default_factory=list)
    updated_knowledge_states: Dict[str, KnowledgeState] = Field(default_factory=dict)
    regenerate_suggestion: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class ReportResponse(BaseModel):
    """学情报告响应模型"""
    learner_id: str
    radar: ReportRadar
    weak_points: List[str]
    strong_points: List[str]
    skill_level: str
    learning_goal: str
    difficulty_curve: List[DifficultyCurveItem]
    learning_path: List[LearningPathItem] = Field(default_factory=list)
    blind_spot_heatmap: List[Dict[str, Any]] = Field(default_factory=list)
    agent_flow: List[AgentTrace] = Field(default_factory=list)
    resource_difficulty_match: List[Dict[str, Any]] = Field(default_factory=list)
    review_summary: Dict[str, Any] = Field(default_factory=dict)
    feedback_trend: List[Dict[str, Any]] = Field(default_factory=list)
    metric_summary: Dict[str, Any] = Field(default_factory=dict)
    next_suggestions: List[str] = Field(default_factory=list)
    recent_resources: List[LearningResource] = Field(default_factory=list)
    recent_feedback: List[FeedbackRecord] = Field(default_factory=list)


class FeedbackHistoryResponse(BaseModel):
    """学习反馈历史响应"""
    learner_id: str
    total: int
    items: List[FeedbackRecord]


class ResourceEvaluationSubmitResponse(BaseModel):
    """学习后测评与反馈结果"""
    learner_id: str
    resource_id: str
    correct_rate: float
    correct_count: int
    total_questions: int
    wrong_knowledge_points: List[str] = Field(default_factory=list)
    feedback: FeedbackResponse


class RunEvaluationSubmitResponse(BaseModel):
    """按生成任务聚合的学习后测评与反馈结果"""
    learner_id: str
    run_id: str
    resource_count: int
    correct_rate: float
    correct_count: int
    total_questions: int
    wrong_knowledge_points: List[str] = Field(default_factory=list)
    feedback: FeedbackResponse


class ResourceListResponse(BaseModel):
    """生成资源列表响应"""
    learner_id: str
    total: int
    resources: List[LearningResource]


class EvaluationSummary(BaseModel):
    """量化评测摘要"""
    sample_count: int
    metrics: Dict[str, float]
    ablation: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class ResourceEvaluationQuestion(BaseModel):
    """学习后测评题目"""
    question_id: str
    question_type: str
    question: str
    options: List[str] = Field(default_factory=list)
    knowledge_point: Optional[str] = None
    difficulty: Optional[str] = None
    source: Literal["resource", "knowledge_base"] = "resource"


class ResourceEvaluationSessionResponse(BaseModel):
    """资源学习后测评题目列表"""
    learner_id: str
    resource_id: str
    topic: Optional[str] = None
    total: int
    questions: List[ResourceEvaluationQuestion] = Field(default_factory=list)


class RunEvaluationSessionResponse(BaseModel):
    """按生成任务聚合的学习后测评题目列表"""
    learner_id: str
    run_id: str
    topic: Optional[str] = None
    resource_ids: List[str] = Field(default_factory=list)
    total: int
    questions: List[ResourceEvaluationQuestion] = Field(default_factory=list)


class ResourceEvaluationAnswerSubmission(BaseModel):
    """学习后测评单题作答"""
    question_id: str
    answer: Any


class ResourceEvaluationSubmitRequest(BaseModel):
    """学习后测评与反馈提交"""
    learner_id: str
    resource_id: str
    answers: List[ResourceEvaluationAnswerSubmission] = Field(default_factory=list, min_length=1)
    feedback_type: Optional[str] = Field(default=None, description="反馈类型")
    time_spent_seconds: Optional[int] = Field(default=None, ge=0, description="学习耗时")
    completed: Optional[bool] = Field(default=None, description="是否完成学习")
    self_rating: Optional[int] = Field(default=None, ge=1, le=5, description="自评")
    practice_result: Dict[str, Any] = Field(default_factory=dict, description="主观反馈与练习信息")


class RunEvaluationSubmitRequest(BaseModel):
    """按生成任务聚合的学习后测评与反馈提交"""
    learner_id: str
    run_id: str
    answers: List[ResourceEvaluationAnswerSubmission] = Field(default_factory=list, min_length=1)
    feedback_type: Optional[str] = Field(default=None, description="反馈类型")
    time_spent_seconds: Optional[int] = Field(default=None, ge=0, description="学习耗时")
    completed: Optional[bool] = Field(default=None, description="是否完成学习")
    self_rating: Optional[int] = Field(default=None, ge=1, le=5, description="自评")
    practice_result: Dict[str, Any] = Field(default_factory=dict, description="主观反馈与练习信息")
