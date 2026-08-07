"""Dependency injection container configuration."""
from dependency_injector import containers, providers

from app.agents.workflow import build_workflow
from app.config import get_settings
from app.core.llm import get_llm
from app.core.vector_store import get_vector_store
from app.db.audit.repository import create_audit_repository
from app.db.database import get_session_factory
from app.db.diagnosis.repository import create_diagnosis_repository
from app.db.feedback.repository import create_feedback_repository
from app.db.generation_job.repository import create_generation_job_repository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learner.repository import create_learner_repository
from app.db.questionnaire.repository import create_questionnaire_repository
from app.db.resource.repository import create_resource_repository
from app.db.user.repository import create_user_repository
from app.services.diagnosis_service import DiagnosisService
from app.services.auth_service import AuthService
from app.services.evaluation_service import EvaluationService
from app.services.feedback_service import FeedbackService
from app.services.generation_job_service import GenerationJobService
from app.services.generation_service import GenerationService
from app.services.knowledge_service import KnowledgeService
from app.services.learning_history_service import LearningHistoryService
from app.services.onboarding_service import OnboardingService
from app.services.profile_service import ProfileService
from app.services.report_service import ReportService
from app.services.resource_service import ResourceService
from app.services.review_service import ReviewService
from app.services.user_service import UserService


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    llm_client = providers.Singleton(get_llm)
    vector_store = providers.Singleton(get_vector_store)
    db_session_factory = providers.Singleton(get_session_factory)
    workflow = providers.Singleton(build_workflow)

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

    profile_service = providers.Singleton(ProfileService, repo=learner_repository)
    user_service = providers.Singleton(UserService, repo=user_repository)
    auth_service = providers.Singleton(AuthService, repo=user_repository)
    generation_service = providers.Singleton(
        GenerationService,
        resource_repo=resource_repository,
        workflow=workflow,
        audit_repo=audit_repository,
    )
    generation_job_service = providers.Singleton(
        GenerationJobService,
        job_repo=generation_job_repository,
        generation_service=generation_service,
    )
    resource_service = providers.Singleton(ResourceService, repo=resource_repository)
    feedback_service = providers.Singleton(FeedbackService, feedback_repo=feedback_repository)
    report_service = providers.Singleton(
        ReportService,
        resource_repo=resource_repository,
        feedback_repo=feedback_repository,
    )
    knowledge_service = providers.Singleton(KnowledgeService, catalog=knowledge_catalog)
    diagnosis_service = providers.Singleton(
        DiagnosisService,
        knowledge_service=knowledge_service,
        learner_repo=learner_repository,
        diagnosis_repo=diagnosis_repository,
    )
    review_service = providers.Singleton(ReviewService, audit_repo=audit_repository)
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
        feedback_repo=feedback_repository,
    )


def init_container() -> Container:
    container = Container()
    settings = get_settings()
    container.config.from_dict(settings.__dict__)
    return container
