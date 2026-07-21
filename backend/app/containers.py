"""
依赖注入容器配置

集中管理所有依赖关系，实现企业级标准架构。
"""
from dependency_injector import containers, providers

from app.config import get_settings
from app.core.llm import get_llm
from app.core.vector_store import get_vector_store
from app.agents.workflow import build_workflow
from app.db.database import get_session_factory
from app.db.learner.repository import create_learner_repository
from app.db.resource.repository import create_resource_repository
from app.services.learner_service import LearnerService
from app.services.generation_service import GenerationService
from app.services.feedback_service import FeedbackService
from app.services.report_service import ReportService


class Container(containers.DeclarativeContainer):
    """应用依赖注入容器
    
    集中配置所有依赖关系，支持灵活的生命周期管理。
    """
    
    # ==================== 配置层 ====================
    config = providers.Configuration()
    
    # ==================== 基础设施层（单例）====================
    
    # LLM客户端
    llm_client = providers.Singleton(get_llm)
    
    # 向量数据库
    vector_store = providers.Singleton(get_vector_store)
    
    # 数据库会话工厂
    db_session_factory = providers.Singleton(get_session_factory)
    
    # Agent工作流
    workflow = providers.Singleton(build_workflow)
    
    # ==================== Repository层（根据配置选择实现）====================
    
    # 学习者画像仓库
    learner_repository = providers.Singleton(
        create_learner_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    
    # 资源仓库
    resource_repository = providers.Singleton(
        create_resource_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    
    # ==================== Service层（单例）====================
    
    # 学习者画像服务
    learner_service = providers.Singleton(
        LearnerService,
        repo=learner_repository
    )
    
    # 资源生成服务
    generation_service = providers.Singleton(
        GenerationService,
        resource_repo=resource_repository,
        workflow=workflow
    )
    
    # 学习反馈服务（无外部依赖）
    feedback_service = providers.Singleton(FeedbackService)
    
    # 学情报告服务（无外部依赖）
    report_service = providers.Singleton(ReportService)


def init_container() -> Container:
    """初始化并配置依赖注入容器
    
    Returns:
        配置好的Container实例
    """
    container = Container()
    
    # 加载配置
    settings = get_settings()
    container.config.from_dict(settings.__dict__)
    
    return container
