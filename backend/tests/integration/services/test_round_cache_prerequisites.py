"""Round cache dependencies and real review-low prerequisite verification."""
from types import SimpleNamespace

import pytest

from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository
from app.db.reports.repository import SQLReportReadRepository
from app.models.learning_documents.schemas import SkillNode
from app.services.feedback.round_feedback import RoundFeedback
from tests.integration.services.test_report_read_model import reports  # noqa: F401
from tests.integration.services.test_round_generation import fixture, dual_round
from tests.integration.services.test_round_failure_recovery import freeze_submission


def test_round_cache_checks_same_factory_and_rejects_mixed_sources():
    from sqlalchemy.orm import sessionmaker
    from app.services.reports.reports import ReportService
    service, _ = fixture(True)
    factory = service.repository.session_factory
    reader = SQLReportReadRepository(factory)
    report = ReportService(None, None, read_repo=reader, round_service=service)
    assert report._reader() is reader
    report.round_service = SimpleNamespace(repository=MemoryRoundRepository())
    assert report._reader() is None
    report.round_service = SimpleNamespace(repository=SQLRoundRepository(sessionmaker(bind=factory.kw["bind"])))
    assert report._reader() is None
    report.round_service = None
    assert report._reader() is reader


@pytest.mark.parametrize("sql", [False, True])
@pytest.mark.parametrize("review_answer,fail_after_mark", [("A", False), ("B", False), ("B", True)])
def test_high_tier_review_low_marks_real_prerequisite_without_changing_primary(sql, review_answer, fail_after_mark, monkeypatch):
    service, profile = fixture(sql)
    mastery = service.feedback.mastery_service
    nodes = [SkillNode(node_id="base", knowledge_base_id="kb", name="base", tier=1),
             SkillNode(node_id="a", knowledge_base_id="kb", name="a", tier=2, prerequisites=["base"]),
             SkillNode(node_id="b", knowledge_base_id="kb", name="b", tier=2)]
    mastery.knowledge_service.list_skill_nodes = lambda *_: nodes
    if sql:
        from app.db.shared.models import RagSkillNodeORM
        with service.repository.session_factory() as db:
            db.add(RagSkillNodeORM(node_id="base", knowledge_base_id="kb", name="base", tier=1))
            for key in ("a", "b"):
                db.get(RagSkillNodeORM, key).tier = 2
            db.commit()
    profile.skill_level = "中级"
    service.learners.save(profile)
    mastery.finalize_initial_placement(profile, tier=2)
    created = dual_round(service, profile)
    current = service.learners.get(profile.learner_id)
    payload = freeze_submission(service, current, created)
    from app.services.feedback.round_assessment import RoundAssessment
    session = RoundAssessment(service).session(current, created.round_id, created.stage_id)
    review_ids = {q.question_id for g in session.groups if g.role == "review" for q in g.questions}
    payload = payload.model_copy(update={"answers": [a.model_copy(update={"answer": review_answer})
                                                    if a.question_id in review_ids else a for a in payload.answers]})
    before = mastery.initialize_tier_progress(current)
    version = current.profile_version
    if fail_after_mark:
        original = type(mastery).require_feedback_prerequisites
        def fail(self, profile, *, point_scores):
            original(self, profile, point_scores=point_scores)
            if any(score < .6 for score in point_scores.values()):
                raise RuntimeError("prerequisite failure after marking")
        monkeypatch.setattr(type(mastery), "require_feedback_prerequisites", fail)
        with pytest.raises(RuntimeError, match="prerequisite failure after marking"):
            RoundFeedback(service).submit(current, created.round_id, created.stage_id, payload)
        records, _ = mastery.curriculum_progress(service.learners.get(profile.learner_id))
        assert not next(row for row in records if row.skill_node_id == "base").placement_verification_required
        assert service.learners.get(profile.learner_id).profile_version == version
        assert len(service.feedback.feedback_loop_repo.list_attempts(profile.learner_id)) == 1
        return
    result = RoundFeedback(service).submit(current, created.round_id, created.stage_id, payload)
    records, _ = mastery.curriculum_progress(service.learners.get(profile.learner_id))
    base = next(row for row in records if row.skill_node_id == "base")
    assert base.placement_verification_required is (review_answer == "B")
    assert next(n for n in result.nodes if n.role == "primary").score == 1
    if review_answer == "B":
        after = mastery.initialize_tier_progress(service.learners.get(profile.learner_id))
        assert after.active_tier == before.active_tier == 2


def test_round_need_changes_invalidate_report_revision(reports):
    from datetime import datetime, timezone
    service = reports.service
    repository = SQLRoundRepository(reports.factory)
    service.round_service = SimpleNamespace(repository=repository)
    from tests.integration.services.test_report_read_model import LEARNER
    profile = reports.profiles.get(LEARNER)
    assert service._reader() is service.read_repo
    first = service.get_snapshot(profile)
    attempt = service.feedback_loop_repo.list_attempts(LEARNER, None)[0]
    values = dict(need_id="cache-boundary", learner_id=LEARNER, knowledge_base_id=profile.knowledge_base_id,
                  skill_node_id=attempt.knowledge_point_results[0].knowledge_point_id,
                  status="practice", first_unresolved_attempt_id=attempt.attempt_id,
                  last_attempt_id=attempt.attempt_id, last_score=.7, wait_rounds=1,
                  updated_at=datetime.now(timezone.utc))
    with repository.transaction() as tx:
        row = tx.insert("learner_remediation_needs", values)
    second = service.get_snapshot(profile)
    assert second.metadata()["report_revision"] != first.metadata()["report_revision"]
    assert second.materialize()["remediation_needs"][0]["wait_rounds"] == 1
    with repository.transaction() as tx:
        tx.compare_and_set("learner_remediation_needs", row["need_id"], row["row_version"], {"wait_rounds": 2})
    third = service.get_snapshot(profile)
    assert third.metadata()["report_revision"] != second.metadata()["report_revision"]
    assert reports.profiles.get(LEARNER).profile_version == profile.profile_version
