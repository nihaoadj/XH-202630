from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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


class LearnerProfile(BaseModel):
    """学习者画像模型"""
    learner_id: str = Field(..., description="学习者唯一标识")
    education: str = Field(..., description="学历背景")
    major: str = Field(..., description="专业方向")
    theory_scores: Dict[str, float] = Field(default_factory=dict, description="理论测试得分")
    skill_level: str = Field(default="初级", description="技能水平")
    weak_points: List[str] = Field(default_factory=list, description="知识盲区")
    strong_points: List[str] = Field(default_factory=list, description="优势领域")
    learning_goal: str = Field(..., description="学习目标")


class GenerateRequest(BaseModel):
    """生成资源请求模型"""
    learner_id: str
    topic: str = Field(..., description="学习主题")
    resource_types: List[str] = Field(default_factory=lambda: ["讲义", "实操指南", "分阶测试题"])


class SourceRef(BaseModel):
    """知识溯源引用"""
    doc_id: str
    title: str
    snippet: str
    score: float


class LearningResource(BaseModel):
    """学习资源模型

    支持文本资源与多媒体文件资源两种形态：
    - 文本资源：storage_type='text'，content_text 保存完整内容
    - 文件资源：storage_type='file'，file_path 指向文件位置，content_text 可保存摘要
    """
    resource_id: str
    resource_type: str
    difficulty: str
    storage_type: str = Field(default="text", description="存储方式：text | file")
    content_text: Optional[str] = Field(default=None, description="文本内容或文件摘要")
    file_path: Optional[str] = Field(default=None, description="文件相对路径（文件类资源）")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    mime_type: Optional[str] = Field(default=None, description="文件 MIME 类型")
    knowledge_points: List[str]
    source_refs: List[SourceRef]


class AgentTrace(BaseModel):
    """Agent 执行轨迹"""
    agent_name: str
    action: str
    output_summary: str
    timestamp: Optional[str] = None


class GenerateResponse(BaseModel):
    """生成资源响应模型"""
    learner_id: str
    topic: str
    resources: List[LearningResource]
    trace: List[AgentTrace]
    report: Dict


class ReportRadar(BaseModel):
    """学情报告雷达图数据"""
    dimensions: List[str]
    values: List[float]


class DifficultyCurveItem(BaseModel):
    """难度曲线数据项"""
    topic: str
    score: float
    recommended_difficulty: str


class LearningPathItem(BaseModel):
    """学习路径数据项"""
    order: int
    topic: str
    reason: str


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


class FeedbackAnswer(BaseModel):
    """单题答题详情"""
    question_id: str
    correct: bool
    answer: Optional[Any] = Field(default=None, description="学习者作答内容")


class FeedbackRequest(BaseModel):
    """学习反馈请求模型"""
    learner_id: str
    resource_id: str
    correct_rate: float = Field(..., ge=0.0, le=1.0)
    answers: List[FeedbackAnswer] = Field(default_factory=list, description="答题详情")


class FeedbackResponse(BaseModel):
    """学习反馈响应模型"""
    learner_id: str
    decision: str
    message: str
    updated_profile: Optional[LearnerProfile]
