"""Dependency injection container configuration."""

from dependency_injector import containers, providers

from app.agents.workflow import build_workflow
from app.config import get_settings
from app.core.evidence_retriever import EvidenceRetriever
from app.core.llm import LangChainChatTransport
from app.core.llm_gateway import LLMGateway
from app.core.vector_store import ChromaVectorSearchBackend, get_vector_store
from app.db.audit.repository import create_audit_repository
from app.db.database import get_session_factory
from app.db.claim.repository import create_claim_repository
from app.db.diagnosis.repository import create_diagnosis_repository
from app.db.feedback.repository import create_feedback_repository
from app.db.feedback_loop.repository import create_feedback_loop_repository
from app.db.generation_job.repository import create_generation_job_repository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learner.repository import create_learner_repository
from app.db.questionnaire.repository import create_questionnaire_repository
from app.db.resource.repository import create_resource_repository
from app.db.user.repository import create_user_repository
from app.models.llm import LLMCallOptions
from app.services.diagnosis_service import DiagnosisService
from app.services.evaluation_service import EvaluationService
from app.services.feedback_service import FeedbackService
from app.services.generation_job_service import GenerationJobService
from app.services.generation_service import GenerationService
from app.services.ingestion_service import ChromaKnowledgeVectorIndex, IngestionService
from app.services.knowledge_service import KnowledgeService
from app.services.learning_history_service import LearningHistoryService
from app.services.onboarding_service import OnboardingService
from app.services.profile_service import ProfileService
from app.services.report_service import ReportService
from app.services.resource_service import ResourceService
from app.services.review_service import ReviewService
from app.services.run_query_service import RunQueryService
from app.services.user_service import UserService


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

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

    vector_store = providers.Singleton(get_vector_store)
    db_session_factory = providers.Singleton(get_session_factory)

    learner_repository = providers.Singleton(
        create_learner_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    user_repository = providers.Singleton(
        create_user_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    resource_repository = providers.Singleton(
        create_resource_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    feedback_repository = providers.Singleton(
        create_feedback_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    audit_repository = providers.Singleton(
        create_audit_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    feedback_loop_repository = providers.Singleton(
        create_feedback_loop_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
        learner_repository=learner_repository,
    )
    claim_repository = providers.Singleton(
        create_claim_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    diagnosis_repository = providers.Singleton(
        create_diagnosis_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    generation_job_repository = providers.Singleton(
        create_generation_job_repository,
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
    workflow = providers.Singleton(
        build_workflow,
        llm_gateway=llm_gateway,
        evidence_retriever=evidence_retriever,
        lifecycle_repository=audit_repository,
    )

    profile_service = providers.Singleton(ProfileService, repo=learner_repository)
    user_service = providers.Singleton(UserService, repo=user_repository)
    generation_service = providers.Singleton(
        GenerationService,
        resource_repo=resource_repository,
        workflow=workflow,
        audit_repo=audit_repository,
        knowledge_catalog=knowledge_catalog,
        claim_repo=claim_repository,
    )
    generation_job_service = providers.Singleton(
        GenerationJobService,
        job_repo=generation_job_repository,
        generation_service=generation_service,
    )
    resource_service = providers.Singleton(ResourceService, repo=resource_repository)
    feedback_service = providers.Singleton(
        FeedbackService,
        feedback_repo=feedback_repository,
        feedback_loop_repo=feedback_loop_repository,
        generation_job_service=generation_job_service,
        audit_repo=audit_repository,
        knowledge_catalog=knowledge_catalog,
    )
    report_service = providers.Singleton(
        ReportService,
        resource_repo=resource_repository,
        feedback_repo=feedback_repository,
        feedback_loop_repo=feedback_loop_repository,
    )
    knowledge_service = providers.Singleton(KnowledgeService, catalog=knowledge_catalog)
    diagnosis_service = providers.Singleton(
        DiagnosisService,
        knowledge_service=knowledge_service,
        learner_repo=learner_repository,
        diagnosis_repo=diagnosis_repository,
    )
    review_service = providers.Singleton(ReviewService, audit_repo=audit_repository)
    run_query_service = providers.Singleton(
        RunQueryService,
        repository=audit_repository,
        resource_repository=resource_repository,
        claim_repository=claim_repository,
        feedback_loop_repository=feedback_loop_repository,
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
        user_repo=user_repository,
    )
    learning_history_service = providers.Singleton(
        LearningHistoryService,
        profile_service=profile_service,
        questionnaire_repo=questionnaire_repository,
        diagnosis_repo=diagnosis_repository,
        generation_job_repo=generation_job_repository,
    )


def init_container() -> Container:
    container = Container()
    settings = get_settings()
    container.config.from_dict(settings.__dict__)
    return container
