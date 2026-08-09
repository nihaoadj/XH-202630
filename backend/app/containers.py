"""
依赖注入容器配置

集中管理所有依赖关系，实现企业级标准架构。
"""
from dependency_injector import containers, providers

from app.config import get_settings
from app.core.llm import LangChainChatTransport
from app.core.llm_gateway import LLMGateway
from app.core.vector_store import get_vector_store
from app.core.vector_store import ChromaVectorSearchBackend
from app.core.evidence_retriever import EvidenceRetriever
from app.agents.workflow import build_workflow
from app.db.database import get_session_factory
from app.db.learner.repository import create_learner_repository
from app.db.resource.repository import create_resource_repository
from app.db.feedback.repository import create_feedback_repository
from app.db.audit.repository import create_audit_repository
from app.db.diagnosis.repository import create_diagnosis_repository
from app.db.questionnaire.repository import create_questionnaire_repository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.services.profile_service import ProfileService
from app.services.generation_service import GenerationService
from app.services.resource_service import ResourceService
from app.services.feedback_service import FeedbackService
from app.services.report_service import ReportService
from app.services.knowledge_service import KnowledgeService
from app.services.diagnosis_service import DiagnosisService
from app.services.review_service import ReviewService
from app.services.evaluation_service import EvaluationService
from app.services.onboarding_service import OnboardingService
from app.services.ingestion_service import ChromaKnowledgeVectorIndex, IngestionService
from app.services.run_query_service import RunQueryService
from app.models.llm import LLMCallOptions


class Container(containers.DeclarativeContainer):
    """应用依赖注入容器
    
    集中配置所有依赖关系，支持灵活的生命周期管理。
    """
    
    # ==================== 配置层 ====================
    config = providers.Configuration()
    
    # ==================== 基础设施层（单例）====================
    
    # LLM transport 与 Gateway 均可在测试或部署组装时替换。
    runtime_settings = providers.Singleton(get_settings)
    llm_transport = providers.Singleton(
        LangChainChatTransport,
        settings=runtime_settings,
    )
    llm_call_options = providers.Factory(
        LLMCallOptions,
        request_timeout_seconds=config.llm_request_timeout_seconds,
        max_attempts=config.llm_max_attempts,
        max_output_tokens=config.llm_max_output_tokens,
        structured_output_mode=config.llm_structured_output_mode,
    )
    llm_gateway = providers.Singleton(
        LLMGateway,
        transport=llm_transport,
        retry_base_delay_seconds=config.llm_retry_base_delay_seconds,
        retry_max_delay_seconds=config.llm_retry_max_delay_seconds,
        default_options=llm_call_options,
        generator_max_output_tokens=config.llm_generator_max_output_tokens,
    )
    
    # 向量数据库
    vector_store = providers.Singleton(get_vector_store)
    
    # 数据库会话工厂
    db_session_factory = providers.Singleton(get_session_factory)
    
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

    # 学习反馈仓库
    feedback_repository = providers.Singleton(
        create_feedback_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )

    # Agent 运行轨迹与审核证据仓库
    audit_repository = providers.Singleton(
        create_audit_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )

    diagnosis_repository = providers.Singleton(
        create_diagnosis_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )

    questionnaire_repository = providers.Singleton(
        create_questionnaire_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )

    knowledge_catalog = providers.Singleton(
        KnowledgeCatalogRepository,
        session_factory=db_session_factory,
    )

    vector_search_backend = providers.Singleton(
        ChromaVectorSearchBackend,
        settings=runtime_settings,
    )
    evidence_retriever = providers.Singleton(
        EvidenceRetriever,
        backend=vector_search_backend,
        chunk_repository=knowledge_catalog,
        settings=runtime_settings,
    )
    knowledge_vector_index = providers.Singleton(
        ChromaKnowledgeVectorIndex,
        search_backend=vector_search_backend,
    )
    ingestion_service = providers.Singleton(
        IngestionService,
        catalog=knowledge_catalog,
        vector_index=knowledge_vector_index,
    )

    # Agent 工作流必须显式注入证据检索边界。
    workflow = providers.Singleton(
        build_workflow,
        llm_gateway=llm_gateway,
        evidence_retriever=evidence_retriever,
        lifecycle_repository=audit_repository,
    )
    
    # ==================== Service层（单例）====================
    
    # 问卷画像查询与维护服务
    profile_service = providers.Singleton(
        ProfileService,
        repo=learner_repository
    )
    
    # 资源生成服务
    generation_service = providers.Singleton(
        GenerationService,
        resource_repo=resource_repository,
        workflow=workflow,
        audit_repo=audit_repository,
        knowledge_catalog=knowledge_catalog,
    )

    # 资源查询服务
    resource_service = providers.Singleton(
        ResourceService,
        repo=resource_repository
    )
    
    # 学习反馈服务
    feedback_service = providers.Singleton(
        FeedbackService,
        feedback_repo=feedback_repository
    )
    
    # 学情报告服务
    report_service = providers.Singleton(
        ReportService,
        resource_repo=resource_repository,
        feedback_repo=feedback_repository,
    )

    knowledge_service = providers.Singleton(
        KnowledgeService,
        catalog=knowledge_catalog,
    )

    diagnosis_service = providers.Singleton(
        DiagnosisService,
        knowledge_service=knowledge_service,
        learner_repo=learner_repository,
        diagnosis_repo=diagnosis_repository,
    )

    review_service = providers.Singleton(
        ReviewService,
        audit_repo=audit_repository,
    )

    run_query_service = providers.Singleton(
        RunQueryService,
        repository=audit_repository,
        resource_repository=resource_repository,
    )

    evaluation_service = providers.Singleton(
        EvaluationService,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )

    onboarding_service = providers.Singleton(
        OnboardingService,
        learner_repo=learner_repository,
        knowledge_service=knowledge_service,
        questionnaire_repo=questionnaire_repository,
    )


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
