"""Dependency injection container configuration."""

from dependency_injector import containers, providers

from app.agents.resource_workflows.learning_documents.workflow import build_workflow
from app.agents.learning_agents.tutor_agent import TutorAgent, TutorContextBuilder
from app.config import get_settings
from app.core.retrieval.retriever import EvidenceRetriever
from app.core.llm.transport import LangChainChatTransport
from app.core.llm.gateway import LLMGateway
from app.core.retrieval.vector_store import ChromaVectorSearchBackend, get_vector_store
from app.db.audit.repository import create_audit_repository
from app.db.shared.database import get_session_factory
from app.db.claim.repository import create_claim_repository
from app.db.diagnosis.repository import create_diagnosis_repository
from app.db.feedback.repository import create_feedback_repository
from app.db.feedback.feedback_loop_repository import create_feedback_loop_repository
from app.db.generation.repository import create_generation_job_repository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learners.repository import create_learner_repository
from app.db.learners.mastery import create_mastery_repository
from app.db.learners.curriculum import create_curriculum_repository
from app.db.learners.tier_progress import create_tier_progress_repository
from app.db.questionnaire.repository import create_questionnaire_repository
from app.db.learning_documents.repository import create_resource_repository
from app.db.courseware.repository import create_courseware_repository
from app.db.tutor.repository import create_tutor_repository
from app.db.users.repository import create_user_repository
from app.models.shared.llm import LLMCallOptions
from app.services.learners.diagnosis import DiagnosisService
from app.services.auth.authentication import AuthService
from app.services.reports.evaluation import EvaluationService
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService
from app.services.generation.generation import GenerationService
from app.services.knowledge.ingestion import ChromaKnowledgeVectorIndex, IngestionService
from app.services.knowledge.knowledge import KnowledgeService
from app.services.learners.history import LearningHistoryService
from app.services.learners.mastery import MasteryService
from app.services.onboarding.onboarding import OnboardingService
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService
from app.services.learning_documents.resources import ResourceService
from app.services.courseware import CoursewareService
from app.agents.resource_workflows.interactive_courseware.worker import CoursewareSceneWorker
from app.services.courseware.executor import CoursewareExecutor
from app.services.resource_library import ResourceLibraryService
from app.services.reviews.reviews import ReviewService
from app.services.runs.queries import RunQueryService
from app.services.runs.events import RunEventStreamService
from app.services.users.users import UserService
from app.services.runs.workflow_artifact_recorder import WorkflowArtifactRecorder
from app.services.tutor.tutor import TutorService


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
        resource_generation_max_attempts=config.llm_resource_generation_max_attempts,
        default_options=llm_call_options,
        generator_max_output_tokens=config.llm_generator_max_output_tokens,
        resource_generator_max_output_tokens=config.llm_resource_generator_max_output_tokens,
        claim_max_attempts=config.claim_max_attempts,
        claim_max_output_tokens=config.claim_max_output_tokens,
        claim_truncated_retry_output_tokens=config.claim_truncated_retry_output_tokens,
        claim_request_timeout_seconds=config.claim_request_timeout_seconds,
        claim_schema_repair_attempts=config.claim_schema_repair_attempts,
    )

    vector_store = providers.Singleton(get_vector_store)
    db_session_factory = providers.Singleton(get_session_factory)

    learner_repository = providers.Singleton(
        create_learner_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    mastery_repository = providers.Singleton(
        create_mastery_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
        learner_repository=learner_repository,
    )
    curriculum_repository = providers.Singleton(
        create_curriculum_repository,
        db_type=config.db_type,
        session_factory=db_session_factory,
    )
    tier_progress_repository = providers.Singleton(
        create_tier_progress_repository,
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
    courseware_repository = providers.Singleton(
        create_courseware_repository,
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
        mastery_repository=mastery_repository,
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
    tutor_repository = providers.Singleton(
        create_tutor_repository,
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
    knowledge_service = providers.Singleton(KnowledgeService, catalog=knowledge_catalog)
    mastery_service = providers.Singleton(
        MasteryService,
        repository=mastery_repository,
        knowledge_service=knowledge_service,
        resource_repo=resource_repository,
        curriculum_repo=curriculum_repository,
        tier_progress_repo=tier_progress_repository,
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
        resource_progress_recorder=providers.Singleton(
            WorkflowArtifactRecorder,
            resource_repository=resource_repository,
            audit_repository=audit_repository,
            claim_repository=claim_repository,
        ),
    )

    profile_service = providers.Singleton(ProfileService, repo=learner_repository)
    user_service = providers.Singleton(UserService, repo=user_repository)
    auth_service = providers.Singleton(AuthService, repo=user_repository)
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
        mastery_service=mastery_service,
    )
    resource_service = providers.Singleton(ResourceService, repo=resource_repository)
    courseware_service = providers.Singleton(
        CoursewareService,
        repo=courseware_repository,
        resource_service=resource_service,
        audit_repo=audit_repository,
        llm_gateway=llm_gateway,
    )
    courseware_scene_worker = providers.Singleton(
        CoursewareSceneWorker,
        workflow=courseware_service.provided.workflow,
        poll_interval_seconds=config.courseware_worker_poll_seconds,
        batch_size=config.courseware_worker_batch_size,
    )
    courseware_executor = providers.Singleton(
        CoursewareExecutor,
        repo=courseware_repository,
        workflow=courseware_service.provided.workflow,
        poll_interval_seconds=config.courseware_worker_poll_seconds,
        batch_size=config.courseware_worker_batch_size,
    )
    resource_library_service = providers.Singleton(
        ResourceLibraryService,
        resource_service=resource_service,
        courseware_service=courseware_service,
    )
    feedback_service = providers.Singleton(
        FeedbackService,
        feedback_repo=feedback_repository,
        feedback_loop_repo=feedback_loop_repository,
        generation_job_service=generation_job_service,
        audit_repo=audit_repository,
        knowledge_catalog=knowledge_catalog,
        llm_gateway=llm_gateway,
        tutor_repo=tutor_repository,
        mastery_service=mastery_service,
    )
    report_service = providers.Singleton(
        ReportService,
        resource_repo=resource_repository,
        feedback_repo=feedback_repository,
        feedback_loop_repo=feedback_loop_repository,
        generation_job_repo=generation_job_repository,
        mastery_service=mastery_service,
        claim_repo=claim_repository,
        audit_repo=audit_repository,
        diagnosis_repo=diagnosis_repository,
    )
    tutor_context_builder = providers.Singleton(
        TutorContextBuilder,
        audit_repository=audit_repository,
        evidence_retriever=evidence_retriever,
        knowledge_index=knowledge_catalog,
        settings=runtime_settings,
    )
    tutor_agent = providers.Singleton(
        TutorAgent,
        llm_gateway=llm_gateway,
        settings=runtime_settings,
    )
    tutor_service = providers.Singleton(
        TutorService,
        tutor_repo=tutor_repository,
        learner_repo=learner_repository,
        resource_repo=resource_repository,
        knowledge_service=knowledge_service,
        context_builder=tutor_context_builder,
        tutor_agent=tutor_agent,
        settings=runtime_settings,
    )
    diagnosis_service = providers.Singleton(
        DiagnosisService,
        knowledge_service=knowledge_service,
        learner_repo=learner_repository,
        diagnosis_repo=diagnosis_repository,
        mastery_service=mastery_service,
    )
    review_service = providers.Singleton(ReviewService, audit_repo=audit_repository)
    run_query_service = providers.Singleton(
        RunQueryService,
        repository=audit_repository,
        resource_repository=resource_repository,
        claim_repository=claim_repository,
        feedback_loop_repository=feedback_loop_repository,
    )
    run_event_stream_service = providers.Singleton(
        RunEventStreamService,
        repository=audit_repository,
        generation_job_repository=generation_job_repository,
        settings=runtime_settings,
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
        mastery_service=mastery_service,
    )
    learning_history_service = providers.Singleton(
        LearningHistoryService,
        profile_service=profile_service,
        questionnaire_repo=questionnaire_repository,
        diagnosis_repo=diagnosis_repository,
        generation_job_repo=generation_job_repository,
        feedback_repo=feedback_repository,
    )


def init_container() -> Container:
    container = Container()
    settings = get_settings()
    container.config.from_dict(settings.__dict__)
    return container
