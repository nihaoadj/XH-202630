from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.models.learners.mastery import AbilityEvidenceV1
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.services.generation.jobs import GenerationJobService
from app.services.learners.mastery import MasteryService


def _fixture():
    learner_repo = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    )
    learner_repo.save(profile)
    nodes = [
        SimpleNamespace(node_id="weak", name="Weak", description=None, level=None, prerequisites=[], children=["next"]),
        SimpleNamespace(node_id="next", name="Next", description=None, level=None, prerequisites=["weak"], children=[]),
    ]
    mastery_repo = MemoryMasteryRepository(learner_repo)
    mastery = MasteryService(mastery_repo, SimpleNamespace(list_skill_nodes=lambda _kb: nodes))
    mastery.ensure_profile_projection(profile)
    mastery_repo.apply_evidence([AbilityEvidenceV1(
        evidence_id="event-weak", learner_id="learner", knowledge_base_id="kb", skill_node_id="weak",
        source_type="diagnosis", source_id="diag-1", source_hash="a" * 64,
        observed_score=0.1, verified=True, occurred_at=datetime.now(timezone.utc),
    )], {"weak": "Weak", "next": "Next"}, increment_profile_version=True)
    profile = learner_repo.get("learner")
    jobs = GenerationJobService(
        MemoryGenerationJobRepository(), SimpleNamespace(), mastery_service=mastery
    )
    return jobs, profile


def _request(**updates):
    values = dict(
        learner_id="learner", topic="用户指定主题", knowledge_base_id="kb",
        resource_types=["讲义"], include_review=False,
    )
    values.update(updates)
    return GenerateRequest(**values)


def test_generation_job_freezes_auto_focus_and_reuses_it_on_retry():
    jobs, profile = _fixture()
    request = _request()
    created = jobs.create_job(profile, request, run_id="run-auto")
    assert request.topic == "用户指定主题"
    assert request.target_skill_nodes == ["weak"]
    assert created.focus_snapshot.focus_mode == "auto"
    frozen_hash = created.focus_snapshot.mastery_snapshot_hash

    retry_request = _request()
    replay = jobs.create_job(profile, retry_request, run_id="run-auto")
    assert replay.focus_snapshot.mastery_snapshot_hash == frozen_hash
    assert retry_request.target_skill_nodes == ["weak"]


def test_generation_focus_off_and_explicit_override_auto():
    jobs, profile = _fixture()
    off = _request(profile_focus_mode="off")
    off_job = jobs.create_job(profile, off, run_id="run-off")
    assert off.target_skill_nodes == []
    assert off_job.focus_snapshot.focus_mode == "off"

    explicit = _request(target_skill_nodes=["next"])
    explicit_job = jobs.create_job(profile, explicit, run_id="run-explicit")
    assert explicit.target_skill_nodes == ["next"]
    assert explicit_job.focus_snapshot.focus_mode == "explicit"

