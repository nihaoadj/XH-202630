"""Regression coverage for permanent learner-profile deletion."""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.storage import file_storage
from app.db.shared import extended_models  # noqa: F401 - registers diagnostic_runs
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.shared.models import (
    AbilityStateEventORM,
    AgentRunORM,
    AgentStepORM,
    ClaimEvidenceORM,
    ClaimJudgementORM,
    ContestEvalCaseORM,
    ContestEvalResultORM,
    DiagnosticAnswerORM,
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    FeedbackRecordORM,
    GeneratedResourceORM,
    GenerationJobORM,
    KnowledgeBaseORM,
    KnowledgeStateMutationORM,
    KnowledgeStateORM,
    LearnerProfileORM,
    LearnerProfileVersionORM,
    LearnerCurriculumNodeORM,
    LearnerTierProgressORM,
    LearningAttemptORM,
    LearningAttemptPointResultORM,
    LearningPathMutationORM,
    LearningPathNodeORM,
    LearningPathORM,
    QuestionnaireAnswerORM,
    QuestionnaireSubmissionORM,
    QuestionnaireTemplateORM,
    RagSkillNodeORM,
    ResourceClaimORM,
    ResourceExecutionORM,
    ResourceReviewORM,
    ResourceSpecORM,
    RetrievalEvidenceSnapshotORM,
    TutorSessionORM,
    TutorTurnORM,
    WorkflowCheckpointORM,
    WorkflowEventORM,
    Base,
    DiagnosticQuestionORM,
)
from app.db.shared.extended_models import DiagnosticRunORM


def test_sql_profile_delete_removes_all_learner_artifacts_and_resource_files(tmp_path, monkeypatch):
    """All learner-scoped rows and controlled files disappear in one deletion."""

    resources_dir = tmp_path / "generated_resources"
    learner_id = "learner_to_delete"
    (resources_dir / "text" / learner_id).mkdir(parents=True)
    (resources_dir / "text" / learner_id / "guide.md").write_text("# guide", encoding="utf-8")
    monkeypatch.setattr(file_storage, "_get_resources_dir", lambda: resources_dir)

    engine = configure_sqlite_foreign_keys(create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)

    with session_factory() as db:
        db.add_all([
            KnowledgeBaseORM(knowledge_base_id="kb", name="Test knowledge base"),
            LearnerProfileORM(
                learner_id=learner_id,
                learner_type="test",
                education="本科",
                major="软件工程",
                learning_goal="delete me",
                knowledge_base_id="kb",
            ),
            LearnerProfileORM(
                learner_id="learner_to_keep",
                learner_type="test",
                education="本科",
                major="软件工程",
                learning_goal="keep me",
            ),
            RagSkillNodeORM(node_id="node", knowledge_base_id="kb", name="node"),
            QuestionnaireTemplateORM(
                questionnaire_id="questionnaire",
                scope="common",
                name="Questionnaire",
            ),
        ])
        db.flush()
        db.add(DiagnosticQuestionORM(
            question_id="diagnostic_question",
            knowledge_base_id="kb",
            skill_node_id="node",
            question_type="single_choice",
            question="question",
        ))
        db.flush()
        db.add_all([
            AgentRunORM(run_id="run", learner_id=learner_id, status="completed"),
            GenerationJobORM(
                run_id="run",
                batch_id="batch",
                learner_id=learner_id,
                topic="topic",
                status="completed",
            ),
            DiagnosticRunORM(
                diagnostic_result_id="diagnostic_run",
                learner_id=learner_id,
                knowledge_base_id="kb",
                ability_level="初级",
            ),
            DiagnosticAnswerORM(
                answer_id="diagnostic_answer",
                learner_id=learner_id,
                question_id="diagnostic_question",
                knowledge_base_id="kb",
                answer="A",
            ),
            KnowledgeStateORM(
                state_id="knowledge_state",
                learner_id=learner_id,
                knowledge_base_id="kb",
                skill_node_id="node",
            ),
            AbilityStateEventORM(
                event_id="ability_event",
                learner_id=learner_id,
                knowledge_base_id="kb",
                skill_node_id="node",
                source_type="diagnostic",
                source_id="diagnostic_run",
                source_hash="ability-hash",
                after_state={},
                occurred_at=now,
            ),
            LearnerCurriculumNodeORM(
                curriculum_node_id="curriculum_node",
                learner_id=learner_id,
                knowledge_base_id="kb",
                skill_node_id="node",
                progress_status="unplanned",
            ),
            LearnerTierProgressORM(
                tier_progress_id="tier_progress",
                learner_id=learner_id,
                knowledge_base_id="kb",
                placement_tier=1,
                active_tier=1,
                highest_unlocked_tier=1,
            ),
            QuestionnaireSubmissionORM(
                submission_id="submission",
                questionnaire_id="questionnaire",
                learner_id=learner_id,
            ),
        ])
        db.flush()
        db.add_all([
            AgentStepORM(
                step_id="step",
                run_id="run",
                step_no=1,
                agent_name="generator",
                action="generate resource",
            ),
            QuestionnaireAnswerORM(
                answer_id="questionnaire_answer",
                submission_id="submission",
                questionnaire_id="questionnaire",
                question_id="goal",
                answer="learn",
            ),
            ResourceSpecORM(
                resource_spec_id="spec",
                run_id="run",
                resource_family_id="family",
                resource_type="讲义",
                learning_objective="objective",
                difficulty="初级",
            ),
        ])
        db.flush()
        db.add_all([
            GeneratedResourceORM(
                resource_id="resource",
                run_id="run",
                batch_id="batch",
                generation_step_id="step",
                learner_id=learner_id,
                topic="topic",
                resource_type="讲义",
                difficulty="初级",
                content_text="content",
            ),
            WorkflowEventORM(
                event_id="event",
                run_id="run",
                event_sequence=1,
                event_type="step_completed",
                step_id="step",
                payload_hash="event-hash",
                occurred_at=now,
            ),
            WorkflowCheckpointORM(
                checkpoint_id="checkpoint",
                run_id="run",
                event_sequence=1,
                step_id="step",
                step_sequence=1,
                node_name="generator",
                state_projection={},
                state_hash="checkpoint-hash",
                created_at=now,
            ),
            RetrievalEvidenceSnapshotORM(
                evidence_id="evidence",
                run_id="run",
                retrieval_step_id="step",
                knowledge_base_id="kb",
                document_id="document",
                document_version="v1",
                chunk_id="chunk",
                query_hash="query-hash",
                query_rank=1,
                rank=1,
                raw_score=1.0,
                score_kind="cosine",
                normalized_score=1.0,
                excerpt="evidence",
                excerpt_hash="excerpt-hash",
                locator={},
                config_hash="config-hash",
                snapshot_hash="snapshot-hash",
                retrieved_at=now,
            ),
        ])
        db.flush()
        db.add_all([
            ResourceExecutionORM(
                execution_id="execution",
                run_id="run",
                resource_spec_id="spec",
                resource_type="讲义",
                representation="text",
                resource_id="resource",
                state="approved",
                agent_name="TextResourceAgent",
                prompt_version="v1",
                artifact_format="markdown",
            ),
            TutorSessionORM(
                session_id="tutor_session",
                learner_id=learner_id,
                source_type="resource",
                context_type="resource",
                created_at=now,
                updated_at=now,
            ),
            ResourceReviewORM(
                review_id="review",
                resource_id="resource",
                run_id="run",
                status="approved",
            ),
            LearningAttemptORM(
                attempt_id="attempt",
                learner_id=learner_id,
                source_resource_id="resource",
                source_resource_version=1,
                source_run_id="run",
                idempotency_key="attempt-key",
                request_hash="attempt-hash",
                expected_profile_version=1,
                overall_score=0.8,
                submitted_at=now,
            ),
            LearningPathORM(
                path_id="path",
                learner_id=learner_id,
                created_at=now,
                updated_at=now,
            ),
            FeedbackRecordORM(
                feedback_id="feedback",
                learner_id=learner_id,
                resource_id="resource",
                correct_rate=0.8,
                decision="continue",
            ),
            ContestEvalCaseORM(case_id="eval_case", knowledge_base_id="kb", query="query"),
        ])
        db.flush()
        db.add_all([
            ResourceClaimORM(
                claim_id="claim",
                review_id="review",
                resource_id="resource",
                run_id="run",
                claim_text="claim",
                supported=True,
            ),
            LearningAttemptPointResultORM(
                result_id="attempt_point",
                attempt_id="attempt",
                knowledge_point_id="node",
                correct_count=1,
                total_count=1,
                score=1.0,
            ),
            FeedbackDecisionORM(
                decision_id="decision",
                learner_id=learner_id,
                attempt_id="attempt",
                action="continue",
                decision_reason="good",
                decision_hash="decision-hash",
                created_at=now,
            ),
            KnowledgeStateMutationORM(
                mutation_id="state_mutation",
                learner_id=learner_id,
                knowledge_point_id="node",
                attempt_id="attempt",
                after_state={},
                reason="attempt submitted",
            ),
            LearningPathNodeORM(
                node_id="path_node",
                path_id="path",
                knowledge_point_id="node",
                node_type="learning",
                sequence=1,
                status="active",
                source="initial",
                created_at=now,
                updated_at=now,
            ),
            ContestEvalResultORM(
                result_id="eval_result",
                case_id="eval_case",
                experiment_name="learner-run",
                run_id="run",
            ),
        ])
        db.flush()
        db.add_all([
            ClaimJudgementORM(
                judgement_id="judgement",
                claim_id="claim",
                run_id="run",
                resource_id="resource",
                resource_version=1,
                review_id="review",
                status="completed",
                reason="supported",
                judge_type="llm",
                judge_prompt_version="v1",
                created_at=now,
            ),
            TutorTurnORM(
                turn_id="tutor_turn",
                session_id="tutor_session",
                sequence=1,
                client_message_id="client-message",
                request_hash="request-hash",
                user_message="question",
                assistant_message="answer",
                pedagogy_action="explain",
                hint_level=0,
                grounding_status="grounded",
                grounding_source="resource",
                created_at=now,
            ),
            LearnerProfileVersionORM(
                version_id="profile_version",
                learner_id=learner_id,
                profile_version=2,
                source_attempt_id="attempt",
                source_decision_id="decision",
                created_at=now,
            ),
            LearningPathMutationORM(
                mutation_id="path_mutation",
                learner_id=learner_id,
                path_id="path",
                attempt_id="attempt",
                decision_id="decision",
                mutation_type="advance",
                path_version_before=1,
                path_version_after=2,
                created_at=now,
            ),
            FeedbackFollowUpRunORM(
                relation_id="follow_up",
                attempt_id="attempt",
                decision_id="decision",
                parent_run_id="run",
                child_run_id="run",
                trigger_type="regenerate",
                status="completed",
            ),
        ])
        db.flush()
        db.add(ClaimEvidenceORM(
            binding_id="claim_evidence",
            judgement_id="judgement",
            claim_id="claim",
            evidence_id="evidence",
            run_id="run",
        ))
        db.commit()

    repository = SQLLearnerRepository(session_factory)
    assert repository.delete(learner_id) is True
    assert not (resources_dir / "text" / learner_id).exists()

    with session_factory() as db:
        assert db.get(LearnerProfileORM, learner_id) is None
        assert db.get(LearnerProfileORM, "learner_to_keep") is not None
        assert db.get(KnowledgeBaseORM, "kb") is not None
        assert db.get(QuestionnaireTemplateORM, "questionnaire") is not None
        for model in (
            AbilityStateEventORM, AgentRunORM, AgentStepORM, ClaimEvidenceORM, ClaimJudgementORM,
            ContestEvalResultORM, DiagnosticAnswerORM, DiagnosticRunORM,
            FeedbackDecisionORM, FeedbackFollowUpRunORM, FeedbackRecordORM,
            GeneratedResourceORM, GenerationJobORM, KnowledgeStateMutationORM,
            KnowledgeStateORM, LearnerCurriculumNodeORM, LearnerProfileVersionORM,
            LearnerTierProgressORM, LearningAttemptORM,
            LearningAttemptPointResultORM, LearningPathMutationORM,
            LearningPathNodeORM, LearningPathORM, QuestionnaireAnswerORM,
            QuestionnaireSubmissionORM, ResourceClaimORM, ResourceExecutionORM,
            ResourceReviewORM, ResourceSpecORM, RetrievalEvidenceSnapshotORM,
            TutorSessionORM, TutorTurnORM,
            WorkflowCheckpointORM, WorkflowEventORM,
        ):
            assert db.query(model).count() == 0, model.__tablename__
