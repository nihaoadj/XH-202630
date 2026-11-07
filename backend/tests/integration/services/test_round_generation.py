"""Offline learning-round facade exercises real repositories and feedback scoring."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.curriculum import MemoryCurriculumRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import MemoryTierProgressRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.feedback.rounds import GenerateRoundCreateRequestV1, RoundAttemptSubmitV1
from app.models.learning_documents.schemas import ExerciseItem, LearnerProfile, LearningResource, SkillNode
from app.services.feedback.feedback import FeedbackService
from app.services.feedback.round_assessment import RoundAssessment
from app.services.feedback.round_feedback import RoundFeedback
from app.services.feedback.round_learning import RoundLearningService
from app.services.generation.jobs import GenerationJobService
from app.services.learners.mastery import MasteryService


def fixture(sql=False):
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(learner_id="learner", learner_type="test", education="test", major="test",
                             knowledge_base_id="kb", learning_goal="test")
    learners.save(profile)
    resources = MemoryResourceRepository()
    nodes = [SkillNode(node_id=key, knowledge_base_id="kb", name=key, tier=1) for key in ("a", "b")]
    knowledge = SimpleNamespace(list_skill_nodes=lambda *_: nodes, load_assessment_questions=lambda *_: [],
                                load_diagnostic_questions=lambda *_: [], select_diagnostic_questions=lambda *args, **kwargs: [])
    mastery_repository = MemoryMasteryRepository(learners)
    mastery = MasteryService(mastery_repository, knowledge, resource_repo=resources,
                              curriculum_repo=MemoryCurriculumRepository(), tier_progress_repo=MemoryTierProgressRepository())
    mastery.ensure_profile_projection(profile)
    rounds = MemoryRoundRepository()
    jobs = GenerationJobService(MemoryGenerationJobRepository(), SimpleNamespace(audit_repo=None), mastery,
                                 round_repository=rounds)
    if sql:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.db.shared.database import configure_sqlite_foreign_keys
        from app.db.shared.models import Base
        from app.db.learners.sql_repository import SQLLearnerRepository
        from app.db.learning_documents.sql_repository import SQLResourceRepository
        from app.db.feedback.round_sql_repository import SQLRoundRepository
        from app.db.generation.sql_repository import SQLGenerationJobRepository
        from app.db.learners.mastery import SQLMasteryRepository
        from app.db.learners.curriculum import SQLCurriculumRepository
        from app.db.learners.tier_progress import SQLTierProgressRepository
        engine = configure_sqlite_foreign_keys(create_engine("sqlite://", poolclass=StaticPool,
                                                              connect_args={"check_same_thread": False}))
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        from app.db.shared.models import KnowledgeBaseORM, RagSkillNodeORM
        with factory() as db:
            db.add(KnowledgeBaseORM(knowledge_base_id="kb", name="fixture"))
            db.commit()
            db.add_all([RagSkillNodeORM(node_id=node.node_id, knowledge_base_id="kb", name=node.name, tier=1) for node in nodes])
            db.commit()
        learners = SQLLearnerRepository(factory)
        learners.save(profile)
        resources = SQLResourceRepository(factory)
        mastery_repository = SQLMasteryRepository(factory)
        mastery = MasteryService(mastery_repository, knowledge, resource_repo=resources,
                                curriculum_repo=SQLCurriculumRepository(factory), tier_progress_repo=SQLTierProgressRepository(factory))
        rounds = SQLRoundRepository(factory)
        jobs = GenerationJobService(SQLGenerationJobRepository(factory), SimpleNamespace(audit_repo=None), mastery,
                                    round_repository=rounds)
    feedback_repository = MemoryFeedbackRepository()
    loop_repository = MemoryFeedbackLoopRepository(learners, mastery_repository)
    if sql:
        from app.db.feedback.sql_repository import SQLFeedbackRepository
        from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
        feedback_repository = SQLFeedbackRepository(factory)
        loop_repository = SQLFeedbackLoopRepository(factory)
    feedback = FeedbackService(feedback_repository, loop_repository,
                                 jobs, mastery_service=mastery, resource_repo=resources)
    service = RoundLearningService(rounds, feedback, learners, Settings(learning_round_creation_enabled=True))
    return service, profile


def publish(service, result, members=None):
    for member in (members or result.members):
        for index, resource_type in enumerate(member.resource_types):
            run_id = member.job_ids[min(index, len(member.job_ids) - 1)]
            resource = LearningResource(resource_id=f"resource-{member.node_id}-{index}-{result.stage_id[-6:]}",
                learner_id="learner", topic=member.node_id, resource_type=resource_type, difficulty="初级",
                content_text="frozen synthetic content", knowledge_points=[member.node_id], source_refs=[],
                learning_path_node=member.node_id, publication_status="published", run_id=run_id, batch_id=member.batch_id,
                exercise_items=[ExerciseItem(question_id=f"q-{member.node_id}", question_type="single_choice", question="synthetic?",
                                              options=["A", "B"], answer="A", skill_node_id=member.node_id)])
            if hasattr(service.repository, "session_factory"):
                from app.db.shared.models import AgentRunORM
                with service.repository.session_factory() as db:
                    if db.get(AgentRunORM, run_id) is None:
                        db.add(AgentRunORM(run_id=run_id, learner_id="learner", knowledge_base_id="kb", topic=member.node_id))
                        db.commit()
            service.feedback.resource_repo.save(resource, learner_id="learner", topic=member.node_id)


def create_payload(key="selection-key", node="a"):
    return GenerateRoundCreateRequestV1(learner_id="learner", topic=node, knowledge_base_id="kb", target_skill_nodes=[node],
                                        resource_types=["讲义"], selection_key=key)


def test_create_round_is_single_target_and_replay_does_not_duplicate_jobs():
    service, profile = fixture()
    first = service.create(profile, create_payload())
    second = service.create(profile, create_payload())
    assert first.model_dump() == second.model_dump()
    assert len(service.repository.find("learning_rounds")) == 1
    assert len(service.feedback.generation_job_service.job_repo.list_by_learner("learner")) == 1


@pytest.mark.parametrize("sql", [False, True])
def test_frozen_session_and_single_formal_submit_are_idempotent(sql):
    service, profile = fixture(sql)
    result = service.create(profile, create_payload())
    publish(service, result)
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    assert session == RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id, manifest_hash=session.manifest_hash,
        idempotency_key="submission-key", expected_profile_version=profile.profile_version, submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": q.question_id, "answer": "A"} for group in session.groups for q in group.questions])
    submitted = RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)
    assert submitted.nodes[0].score == 1
    assert RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload) == submitted
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner")) == 1


def test_missing_answer_never_creates_a_formal_attempt():
    service, profile = fixture()
    result = service.create(profile, create_payload())
    publish(service, result)
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id, manifest_hash=session.manifest_hash,
        idempotency_key="submission-key", expected_profile_version=profile.profile_version, submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": "wrong", "answer": "A"}])
    with pytest.raises(Exception):
        RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)
    assert service.feedback.feedback_loop_repo.list_attempts("learner") == []


def submit(service, profile, result, key, answer="A"):
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id, manifest_hash=session.manifest_hash,
        idempotency_key=key, expected_profile_version=service.learners.get("learner").profile_version,
        submitted_at=datetime.now(timezone.utc), answers=[{"question_id": q.question_id, "answer": answer}
                                                       for group in session.groups for q in group.questions])
    return RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)


def dual_round(service, profile):
    first = service.create(profile, create_payload())
    publish(service, first)
    submit(service, profile, first, "first-submit")
    current = service.learners.get("learner")
    second = service._create_round(current, "dual-selection", {"fixture": "dual"}, "b", ["讲义"], False,
                                   review_node_id="a")
    publish(service, second)
    return second


@pytest.mark.parametrize("sql", [False, True])
def test_two_members_commit_once_and_both_can_correct_in_same_round(sql):
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections
    service, profile = fixture(sql)
    result = dual_round(service, profile)
    before = service.learners.get("learner").profile_version
    submitted = submit(service, profile, result, "dual-submit", "B")
    assert len(submitted.nodes) == 2
    assert {node.score for node in submitted.nodes} == {0}
    assert service.learners.get("learner").profile_version == before + 1
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner", None)) == 2
    payload = RoundCorrectionSelectionV1(learner_id="learner", selection_key="dual-correction",
        targets=[{"node_id": node.node_id, "source_attempt_id": submitted.attempt_id} for node in submitted.nodes])
    created = RoundCorrections(service).create(service.learners.get("learner"), result.round_id, payload)
    assert created.round_id == result.round_id
    assert len(created.members) == 2
    assert all(member.resource_types == ["个性化纠错训练包", "分阶测试题"] for member in created.members)
    assert RoundCorrections(service).create(service.learners.get("learner"), result.round_id, payload) == created
    # Publishing unstructured exercises must not silently become a correction assessment.
    publish(service, created)
    with pytest.raises(Exception):
        RoundAssessment(service).session(service.learners.get("learner"), created.round_id, created.stage_id)


@pytest.mark.parametrize("sql", [False, True])
def test_review_only_correction_keeps_round_primary_without_a_default_run(sql):
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections

    service, profile = fixture(sql)
    result = dual_round(service, profile)
    submitted = submit(service, profile, result, "dual-submit", "B")
    review = next(node for node in submitted.nodes if node.role == "review")
    payload = RoundCorrectionSelectionV1(learner_id="learner", selection_key="review-only-correction",
        targets=[{"node_id": review.node_id, "source_attempt_id": submitted.attempt_id}])
    created = RoundCorrections(service).create(service.learners.get("learner"), result.round_id, payload)

    assert created.round_id == result.round_id
    assert created.primary_node_id == result.primary_node_id
    assert [member.role for member in created.members] == ["review"]
    assert created.primary_default_run_id is None
    # The replay of the same selection must keep the same shape.
    assert RoundCorrections(service).create(service.learners.get("learner"), result.round_id, payload) == created


@pytest.mark.parametrize("sql", [False, True])
def test_second_member_failure_rolls_back_entire_formal_commit(sql, monkeypatch):
    import app.services.feedback.round_feedback as module
    service, profile = fixture(sql)
    result = dual_round(service, profile)
    before = service.learners.get("learner").model_dump(mode="json")
    original = module.update_need
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("injected second member failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "update_need", fail_second)
    with pytest.raises(RuntimeError, match="second member"):
        submit(service, profile, result, "dual-rollback", "B")
    assert service.learners.get("learner").model_dump(mode="json") == before
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner", None)) == 1
    assert service.repository.find("feedback_node_decisions", attempt_id="dual-rollback") == []
    assert not service.repository.find("learner_remediation_needs", last_score=0)
    session = service.repository.one("learning_round_evaluation_sessions", stage_id=result.stage_id)
    assert session["attempt_id"] is None
    assert session["grading_state"] == "idle"


def submit_with_roles(service, profile, result, key, answers_by_role):
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    answers = []
    for group in session.groups:
        answers.extend({"question_id": question.question_id, "answer": answers_by_role[group.role]}
                       for question in group.questions)
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id, manifest_hash=session.manifest_hash,
        idempotency_key=key, expected_profile_version=service.learners.get("learner").profile_version,
        submitted_at=datetime.now(timezone.utc), answers=answers)
    return RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)


@pytest.mark.parametrize("sql", [False, True])
def test_primary_path_uses_the_primary_node_instead_of_the_mixed_score(sql):
    service, profile = fixture(sql)
    result = dual_round(service, profile)
    submitted = submit_with_roles(service, profile, result, "split-submit", {"primary": "A", "review": "B"})
    by_role = {node.role: node for node in submitted.nodes}

    assert by_role["primary"].score == 1
    assert by_role["review"].score == 0
    assert submitted.primary_path_action == by_role["primary"].action
    assert by_role["primary"].action != by_role["review"].action
    # The review low score is still persisted as its own remediation need.
    review_need = service.repository.one("learner_remediation_needs", learner_id="learner",
                                        knowledge_base_id="kb", skill_node_id=by_role["review"].node_id)
    assert review_need["status"] == "remediate"


@pytest.mark.parametrize("sql", [False, True])
def test_late_result_on_an_older_round_holds_the_newer_primary_path(sql):
    from app.models.feedback.feedback_loop import FeedbackAction

    service, profile = fixture(sql)
    older = dual_round(service, profile)
    publish(service, older)
    current = service.learners.get("learner")
    service._create_round(current, "newer-round", {"fixture": "newer"}, "a", ["讲义"], False)

    submitted = submit(service, profile, older, "late-submit", "B")

    assert submitted.primary_path_action == FeedbackAction.HOLD
    assert len(submitted.nodes) == 2
    stored = service.feedback.feedback_loop_repo.get_attempt("learner", submitted.attempt_id)
    assert stored.path_node_id is None
    assert len(service.repository.find("feedback_node_decisions", attempt_id=submitted.attempt_id)) == 2


@pytest.mark.parametrize("sql", [False, True])
def test_job_status_exposes_the_server_resolved_round_binding(sql):
    service, profile = fixture(sql)
    result = dual_round(service, profile)
    jobs = service.feedback.generation_job_service

    for member in result.members:
        status = jobs.get_job(member.job_ids[0])
        assert status.round_binding.round_id == result.round_id
        assert status.round_binding.member_id == member.member_id
        assert status.round_binding.stage_id == result.stage_id
        assert status.round_binding.role == member.role
    from app.models.learning_documents.schemas import GenerateRequest

    legacy = jobs.create_job(profile, GenerateRequest(learner_id="learner", knowledge_base_id="kb", topic="a",
                                                      target_skill_nodes=["a"], resource_types=["讲义"],
                                                      difficulty_preference="初级"), run_id="legacy-run",
                             batch_id="legacy-batch", submission_hash="legacy-hash")
    assert jobs.get_job(legacy.run_id).round_binding is None


@pytest.mark.parametrize("sql", [False, True])
def test_full_score_node_is_not_offered_for_this_round_correction(sql):
    from app.core.security.errors import ApplicationError
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections

    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    submitted = submit(service, profile, created, "perfect-submit", "A")

    assert submitted.nodes[0].score == 1
    assert submitted.nodes[0].correction_eligible is False
    payload = RoundCorrectionSelectionV1(learner_id="learner", selection_key="perfect-correction",
        targets=[{"node_id": submitted.nodes[0].node_id, "source_attempt_id": submitted.attempt_id}])
    with pytest.raises(ApplicationError):
        RoundCorrections(service).create(service.learners.get("learner"), created.round_id, payload)


@pytest.mark.parametrize("sql", [False, True])
def test_two_explicit_targets_never_create_a_round_or_a_job(sql):
    from app.core.security.errors import ApplicationError, ErrorCode

    service, profile = fixture(sql)
    payload = create_payload("two-targets")
    payload.target_skill_nodes = ["a", "b"]

    with pytest.raises(ApplicationError) as caught:
        service.create(profile, payload)
    assert caught.value.code == ErrorCode.GENERATION_TARGET_INVALID
    assert service.repository.find("learning_rounds") == []
    assert service.feedback.generation_job_service.job_repo.list_by_learner("learner") == []


@pytest.mark.parametrize("sql", [False, True])
def test_review_must_be_published_and_formally_assessed(sql):
    from app.core.security.errors import ApplicationError, ErrorCode

    service, profile = fixture(sql)
    with pytest.raises(ApplicationError) as caught:
        service._create_round(profile, "bad-review", {"fixture": "bad-review"}, "a", ["讲义"], False,
                              review_node_id="b")
    assert caught.value.code == ErrorCode.ROUND_SELECTION_INVALID
    assert service.repository.find("learning_rounds") == []
    assert service.feedback.generation_job_service.job_repo.list_by_learner("learner") == []


@pytest.mark.parametrize("sql", [False, True])
def test_unselected_review_need_survives_the_next_round_and_its_wait_grows(sql):
    service, profile = fixture(sql)
    result = dual_round(service, profile)
    submitted = submit(service, profile, result, "dual-low", "B")
    assert {node.score for node in submitted.nodes} == {0}
    before = service.repository.one("learner_remediation_needs", learner_id="learner",
                                    knowledge_base_id="kb", skill_node_id="b")

    service._create_round(service.learners.get("learner"), "primary-only-next", {"fixture": "next"}, "a", ["讲义"], False)

    after = service.repository.one("learner_remediation_needs", learner_id="learner",
                                   knowledge_base_id="kb", skill_node_id="b")
    assert after["status"] == "remediate"
    assert after["last_score"] == before["last_score"]
    assert after["wait_rounds"] == before["wait_rounds"] + 1


def publish_shared_question(service, result):
    for member in result.members:
        for index, resource_type in enumerate(member.resource_types):
            run_id = member.job_ids[min(index, len(member.job_ids) - 1)]
            exercises = ([ExerciseItem(question_id="shared-question", question_type="single_choice",
                                       question="synthetic?", options=["A", "B"], answer="A",
                                       skill_node_id=member.node_id)]
                         if resource_type in {"讲义", "分阶测试题"} else [])
            resource = LearningResource(
                resource_id=f"shared-{member.member_id}-{index}", learner_id="learner", topic=member.node_id,
                resource_type=resource_type, difficulty=member.difficulty or "初级",
                content_text="frozen synthetic content", knowledge_points=[member.node_id], source_refs=[],
                learning_path_node=member.node_id, publication_status="published", run_id=run_id,
                batch_id=member.batch_id, exercise_items=exercises,
            )
            if hasattr(service.repository, "session_factory"):
                from app.db.shared.models import AgentRunORM
                with service.repository.session_factory() as db:
                    if db.get(AgentRunORM, run_id) is None:
                        db.add(AgentRunORM(run_id=run_id, learner_id="learner", knowledge_base_id="kb", topic=member.node_id))
                        db.commit()
            service.feedback.resource_repo.save(resource, learner_id="learner", topic=member.node_id)


@pytest.mark.parametrize("sql", [False, True])
def test_identical_source_question_ids_still_map_to_distinct_group_questions(sql):
    service, profile = fixture(sql)
    first = service.create(profile, create_payload())
    publish(service, first)
    submit(service, profile, first, "shared-source-first")
    result = service._create_round(service.learners.get("learner"), "shared-source-round",
                                   {"fixture": "shared-source"}, "b", ["讲义"], False, review_node_id="a")
    publish_shared_question(service, result)
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)

    ids = [question.question_id for group in session.groups for question in group.questions]
    assert len(ids) == len(set(ids)) == 2
    assert {question.question_id for group in session.groups for question in group.questions} == set(ids)
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id,
        manifest_hash=session.manifest_hash, idempotency_key="shared-question-submit",
        expected_profile_version=service.learners.get("learner").profile_version,
        submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": question_id, "answer": "A"} for question_id in ids])
    submitted = RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)
    assert {node.score for node in submitted.nodes} == {1}


@pytest.mark.parametrize("sql", [False, True])
def test_a_95_percent_node_stays_correctable_after_its_need_is_resolved(sql, monkeypatch):
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections

    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    original = RoundAssessment.prepare

    def high_score(self, profile, session, payload):
        prepared, anchor = original(self, profile, session, payload)
        # Round groups ask one question per node, so 95% can only be observed by
        # injecting the already-graded score; the production submit path and the
        # correction boundary below still run unmodified.
        points = [point.model_copy(update={"score": 0.95}) for point in prepared.knowledge_point_results]
        return prepared.model_copy(update={"knowledge_point_results": points, "overall_score": 0.95}), anchor

    monkeypatch.setattr(RoundAssessment, "prepare", high_score)
    submitted = submit(service, profile, created, "high-score-submit", "B")
    node = submitted.nodes[0]

    assert node.score == 0.95
    assert node.correction_eligible is True
    need = service.repository.one("learner_remediation_needs", learner_id="learner",
                                  knowledge_base_id="kb", skill_node_id=node.node_id)
    assert need["status"] == "resolved"
    payload = RoundCorrectionSelectionV1(learner_id="learner", selection_key="high-score-correction",
        targets=[{"node_id": node.node_id, "source_attempt_id": submitted.attempt_id}])
    corrected = RoundCorrections(service).create(service.learners.get("learner"), created.round_id, payload)

    assert corrected.round_id == created.round_id
    assert corrected.stage_id != created.stage_id
    assert [member.role for member in corrected.members] == ["primary"]
    assert service.repository.one("learner_remediation_needs", learner_id="learner",
                                  knowledge_base_id="kb", skill_node_id=node.node_id)["status"] == "resolved"


@pytest.mark.parametrize("sql", [False, True])
def test_repeated_submission_with_other_content_or_key_is_a_conflict(sql):
    from app.core.security.errors import ApplicationError, ErrorCode
    from app.models.feedback.rounds import RoundAnswerV1

    service, profile = fixture(sql)
    result = service.create(profile, create_payload())
    publish(service, result)
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    answers = [RoundAnswerV1(question_id=q.question_id, answer="A")
               for group in session.groups for q in group.questions]
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id,
        manifest_hash=session.manifest_hash, idempotency_key="conflict-key",
        expected_profile_version=profile.profile_version, submitted_at=datetime.now(timezone.utc),
        answers=answers)
    submitted = RoundFeedback(service).submit(profile, result.round_id, result.stage_id, payload)

    changed = payload.model_copy(update={"answers": [item.model_copy(update={"answer": "B"}) for item in answers]})
    with pytest.raises(ApplicationError) as other_content:
        RoundFeedback(service).submit(profile, result.round_id, result.stage_id, changed)
    assert other_content.value.code == ErrorCode.ROUND_ATTEMPT_CONFLICT

    new_key = payload.model_copy(update={"idempotency_key": "different-key"})
    with pytest.raises(ApplicationError) as other_key:
        RoundFeedback(service).submit(profile, result.round_id, result.stage_id, new_key)
    assert other_key.value.code == ErrorCode.ROUND_ATTEMPT_CONFLICT
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner")) == 1
    assert service.repository.one("learning_round_evaluation_sessions",
                                  session_id=session.session_id)["attempt_id"] == submitted.attempt_id


@pytest.mark.parametrize("sql", [False, True])
def test_a_frozen_session_cannot_submit_into_a_later_correction_stage(sql):
    from app.core.security.errors import ApplicationError, ErrorCode
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections

    service, profile = fixture(sql)
    result = service.create(profile, create_payload())
    publish(service, result)
    submitted = submit(service, profile, result, "stage-one", "B")
    session = RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    correction = RoundCorrections(service).create(service.learners.get("learner"), result.round_id,
        RoundCorrectionSelectionV1(learner_id="learner", selection_key="stage-two-correction",
            targets=[{"node_id": submitted.nodes[0].node_id, "source_attempt_id": submitted.attempt_id}]))
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id,
        manifest_hash=session.manifest_hash, idempotency_key="cross-stage",
        expected_profile_version=service.learners.get("learner").profile_version,
        submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": q.question_id, "answer": "A"} for group in session.groups for q in group.questions])

    with pytest.raises(ApplicationError) as caught:
        RoundFeedback(service).submit(profile, result.round_id, correction.stage_id, payload)
    assert caught.value.code == ErrorCode.ROUND_ASSESSMENT_INVALID
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner")) == 1


@pytest.mark.parametrize("sql", [False, True])
def test_session_reports_not_ready_when_one_member_has_no_published_resource(sql):
    from app.core.security.errors import ApplicationError, ErrorCode

    service, profile = fixture(sql)
    first = service.create(profile, create_payload())
    publish(service, first)
    submit(service, profile, first, "not-ready-source")
    result = service._create_round(service.learners.get("learner"), "not-ready-round",
                                   {"fixture": "not-ready"}, "b", ["讲义"], False, review_node_id="a")
    primary = next(member for member in result.members if member.role == "primary")
    publish(service, result, members=[primary])

    with pytest.raises(ApplicationError) as caught:
        RoundAssessment(service).session(profile, result.round_id, result.stage_id)
    assert caught.value.code == ErrorCode.ROUND_STAGE_NOT_READY
    assert service.repository.one("learning_round_evaluation_sessions", stage_id=result.stage_id) is None


def structured_correction_payload(node_id):
    def single(number):
        return {"question_id": f"{node_id}-single-{number}", "question_type": "single_choice",
                "difficulty_stage": "基础", "stem": f"single {number}",
                "options": [{"option_id": "A", "text": "A"}, {"option_id": "B", "text": "B"}],
                "answer_option_ids": ["A"], "knowledge_point_tags": [node_id],
                "evidence_ids": [], "max_score": 15.0}

    def multiple(number):
        return {"question_id": f"{node_id}-multiple-{number}", "question_type": "multiple_choice",
                "difficulty_stage": "基础", "stem": f"multiple {number}",
                "options": [{"option_id": "A", "text": "A"}, {"option_id": "B", "text": "B"},
                            {"option_id": "C", "text": "C"}],
                "answer_option_ids": ["A", "B"], "knowledge_point_tags": [node_id],
                "evidence_ids": [], "max_score": 20.0}

    def short(number):
        return {"question_id": f"{node_id}-short-{number}", "question_type": "short_answer",
                "difficulty_stage": "基础", "stem": f"short {number}",
                "reference_answer": "A", "rubric": [{"criterion": "synthetic", "points": 15}],
                "knowledge_point_tags": [node_id], "max_score": 15.0}

    return {"schema_version": "2.0", "title": "synthetic correction", "instructions": "offline",
            "node_blocks": [{"skill_node_id": node_id, "skill_node_name": node_id,
                             "single_choice_questions": [single(1), single(2)],
                             "multiple_choice_questions": [multiple(1), multiple(2)],
                             "short_answer_questions": [short(1), short(2)]}]}


def publish_correction_questions(service, result):
    import hashlib
    import json

    for member in result.members:
        for index, resource_type in enumerate(member.resource_types):
            run_id = member.job_ids[min(index, len(member.job_ids) - 1)]
            payload = structured_correction_payload(member.node_id) if resource_type == "分阶测试题" else None
            payload_hash = (hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                                       separators=(",", ":")).encode("utf-8")).hexdigest()
                            if payload else None)
            resource = LearningResource(
                resource_id=f"correction-{member.member_id}-{index}", learner_id="learner",
                topic=member.node_id, resource_type=resource_type, difficulty=member.difficulty or "初级",
                content_text="frozen correction content", knowledge_points=[member.node_id],
                source_refs=[], learning_path_node=member.node_id, publication_status="published",
                run_id=run_id, batch_id=member.batch_id, assessment_payload=payload,
                assessment_payload_hash=payload_hash,
            )
            if hasattr(service.repository, "session_factory"):
                from app.db.shared.models import AgentRunORM
                with service.repository.session_factory() as db:
                    if db.get(AgentRunORM, run_id) is None:
                        db.add(AgentRunORM(run_id=run_id, learner_id="learner", knowledge_base_id="kb", topic=member.node_id))
                        db.commit()
            service.feedback.resource_repo.save(resource, learner_id="learner", topic=member.node_id)


@pytest.mark.parametrize("sql", [False, True])
def test_review_only_correction_retests_only_its_group_and_holds_the_primary(sql, monkeypatch):
    from app.models.feedback.feedback_loop import FeedbackAction
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections

    service, profile = fixture(sql)
    monkeypatch.setattr(FeedbackService, "_short_answer_score", lambda self, question, actual: 1.0)
    result = dual_round(service, profile)
    first_submit = submit(service, profile, result, "dual-before-correction", "B")
    primary_decision = service.repository.one("feedback_node_decisions", attempt_id=first_submit.attempt_id,
                                              role="primary")
    before_tier = service.feedback.mastery_service.next_generation_options(
        service.learners.get("learner")).tier_progress
    before_version = service.learners.get("learner").profile_version
    review = next(node for node in first_submit.nodes if node.role == "review")
    correction = RoundCorrections(service).create(service.learners.get("learner"), result.round_id,
        RoundCorrectionSelectionV1(learner_id="learner", selection_key="review-retest",
            targets=[{"node_id": review.node_id, "source_attempt_id": first_submit.attempt_id}]))
    publish_correction_questions(service, correction)
    session = RoundAssessment(service).session(service.learners.get("learner"), result.round_id, correction.stage_id)

    assert len(session.groups) == 1 and session.groups[0].role == "review"
    assert len(session.groups[0].questions) == 6
    payload = RoundAttemptSubmitV1(learner_id="learner", session_id=session.session_id,
        manifest_hash=session.manifest_hash, idempotency_key="review-retest-submit",
        expected_profile_version=service.learners.get("learner").profile_version,
        submitted_at=datetime.now(timezone.utc),
        answers=[{"question_id": question.question_id,
                  "answer": ["A", "B"] if question.question_type == "multiple_choice" else "A"}
                 for question in session.groups[0].questions])
    retested = RoundFeedback(service).submit(service.learners.get("learner"), result.round_id,
                                             correction.stage_id, payload)

    assert [node.role for node in retested.nodes] == ["review"]
    assert retested.nodes[0].score == 1
    assert retested.primary_path_action == FeedbackAction.HOLD
    assert service.feedback.feedback_loop_repo.get_attempt("learner", retested.attempt_id).path_node_id is None
    # The earlier primary result is not rewritten by the review re-test.
    assert service.repository.one("feedback_node_decisions", attempt_id=first_submit.attempt_id,
                                  role="primary") == primary_decision
    assert service.feedback.mastery_service.next_generation_options(
        service.learners.get("learner")).tier_progress == before_tier
    assert service.learners.get("learner").profile_version == before_version + 1
    assert len(service.feedback.feedback_loop_repo.list_attempts("learner")) == 3
