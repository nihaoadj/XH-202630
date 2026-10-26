"""Real SQLite report reads: no live models, every Session owns its thread."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend.scripts.report_benchmark import LEARNER, NOW, make_service, seed_database
from app.api.dependencies import get_current_user
from app.api.reports import report as routes
from app.config import get_settings
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.migrations.p0_35_report_read_model import rollback_p0_35_report_read_model_migration
from app.db.reports.watermarks import expected_triggers
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import GeneratedResourceORM, UserProfileORM, FeedbackFollowUpRunORM, FeedbackRecordORM
from app.db.shared.extended_models import DiagnosticRunORM
from app.models.learners.mastery import AbilityEvidenceV1
from app.models.users.users import UserProfile
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportCursorInvalid, ReportService, ReportSnapshotUnstable
from app.services.reports.snapshots import ReportSnapshot


@pytest.fixture
def reports(tmp_path):
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'reports.db'}", connect_args={"check_same_thread": False}))
    seed_database(engine, 10)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = make_service(factory)
    service.profile_repo = SQLLearnerRepository(factory)
    service._clock = lambda: NOW
    profiles = ProfileService(service.profile_repo)
    app = FastAPI()
    app.container = SimpleNamespace(profile_service=lambda: profiles, report_service=lambda: service)
    app.include_router(routes.router, prefix="/api/report")
    yield SimpleNamespace(engine=engine, factory=factory, service=service, profiles=profiles, app=app)
    engine.dispose()


@contextmanager
def _queries(engine):
    statements = []

    def before(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _count_builds(service, monkeypatch):
    original = service._build_report_once
    calls = []

    def build(*args, **kwargs):
        calls.append(kwargs.get("now"))
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_build_report_once", build)
    return calls


def test_warm_conditional_get_and_sse_use_metadata_without_history_or_body_copy(reports, monkeypatch):
    calls = _count_builds(reports.service, monkeypatch)
    with TestClient(reports.app) as client:
        first = client.get(f"/api/report/{LEARNER}")
        assert first.status_code == 200
        count = len(calls)
        monkeypatch.setattr(ReportSnapshot, "materialize", lambda _self: pytest.fail("metadata path copied report body"))
        with _queries(reports.engine) as sql:
            unchanged = client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": first.headers["etag"]})
            metadata = routes._stream_snapshot(SimpleNamespace(app=reports.app, state=SimpleNamespace()), reports.service, LEARNER, 30)
        assert unchanged.status_code == 304 and unchanged.content == b""
        assert metadata["report_revision"] == first.json()["report_revision"]
        assert len(calls) == count
        assert len(sql) <= 8
        assert not any("FROM learning_attempts" in query or "FROM generated_resources" in query for query in sql)


@pytest.mark.parametrize("days", [7, 30, 90])
def test_time_alone_invalidates_current_previous_and_future_attempt_windows(reports, days):
    window = timedelta(days=days)
    with reports.engine.begin() as db:
        db.execute(text("UPDATE learning_attempts SET submitted_at=:stamp"), {"stamp": (NOW - window).replace(tzinfo=None)})
    profile = reports.profiles.get(LEARNER)
    at_edge = reports.service.get_snapshot(profile, window_days=days, now=NOW)
    assert at_edge.materialize()["learning_activity"]["verified_attempt_count"] == 10
    after = NOW + timedelta(microseconds=1)
    previous = reports.service.get_snapshot(profile, window_days=days, now=after)
    assert previous.metadata()["report_revision"] != at_edge.metadata()["report_revision"]
    assert previous.materialize()["learning_activity"]["verified_attempt_count"] == 0
    assert previous.materialize()["learning_activity"]["previous_period_accuracy"] == 0.5
    departed = reports.service.get_snapshot(profile, window_days=days, now=after + window)
    assert departed.metadata()["report_revision"] != previous.metadata()["report_revision"]
    assert departed.materialize()["learning_activity"]["previous_period_accuracy"] is None
    with reports.engine.begin() as db:
        db.execute(text("UPDATE learning_attempts SET submitted_at=:stamp"), {"stamp": NOW.replace(tzinfo=None)})
    future = reports.service.get_snapshot(profile, window_days=days, now=NOW)
    entered = reports.service.get_snapshot(profile, window_days=days, now=after)
    assert future.materialize()["learning_activity"]["verified_attempt_count"] == 0
    assert entered.materialize()["learning_activity"]["verified_attempt_count"] == 10
    assert future.metadata()["report_revision"] != entered.metadata()["report_revision"]


def test_old_etag_becomes_200_and_native_stream_emits_changed_when_window_crosses(reports, monkeypatch):
    with reports.engine.begin() as db:
        db.execute(text("UPDATE learning_attempts SET submitted_at=:stamp"), {"stamp": (NOW - timedelta(days=30)).replace(tzinfo=None)})
    with TestClient(reports.app) as client:
        first = client.get(f"/api/report/{LEARNER}")
        reports.service._clock = lambda: NOW + timedelta(microseconds=1)
        changed = client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": first.headers["etag"]})
        assert changed.status_code == 200 and changed.headers["etag"] != first.headers["etag"]
    reports.service._cache.discard_learner(LEARNER)
    reports.service._clock = lambda: NOW
    polls = [0]

    async def disconnected():
        polls[0] += 1
        if polls[0] == 3:
            reports.service._clock = lambda: NOW + timedelta(microseconds=1)
        return polls[0] > 3

    request = SimpleNamespace(app=reports.app, state=SimpleNamespace(), headers={}, is_disconnected=disconnected)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(report_sse_poll_interval_seconds=0, report_sse_heartbeat_seconds=0))

    async def consume():
        response = await routes.stream_report(LEARNER, request, window_days=30, after_revision=None)
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(consume())
    assert len(chunks) == 3
    assert "event: report_snapshot" in chunks[0]
    assert "event: ping" in chunks[1]
    assert "event: report_changed" in chunks[2] and '"activity"' in chunks[2]
    assert "content_text" not in "".join(chunks)


@pytest.mark.parametrize("statement,parameters", [
    ("UPDATE learner_profile_versions SET change_summary=:value WHERE version_id='version-0'", {"value": '{"corrected":true}'}),
    ("UPDATE feedback_decisions SET decision_reason='corrected' WHERE decision_id='decision-0'", {}),
    ("UPDATE learning_attempts SET metadata=:value WHERE attempt_id='attempt-000000'", {"value": '{"llm_analysis":{"learner_suggestions":["corrected"]},"total_score":0,"max_score":2}'}),
    ("UPDATE generated_resources SET content_text='corrected' WHERE resource_id='resource-001'", {}),
    ("UPDATE resource_reviews SET issues=:value WHERE review_id='review-1'", {"value": '[{"severity":"high","message":"corrected"}]'}),
    ("UPDATE claim_judgements SET verdict='contradicted' WHERE resource_id='resource-001'", {}),
])
def test_content_corrections_without_timestamp_or_profile_version_change_revision(reports, statement, parameters):
    profile = reports.profiles.get(LEARNER)
    before = reports.service.get_snapshot(profile).metadata()
    with reports.engine.begin() as db:
        db.execute(text(statement), parameters)
    after = reports.service.get_snapshot(profile).metadata()
    assert before["as_of_profile_version"] == after["as_of_profile_version"]
    assert before["report_revision"] != after["report_revision"]


def test_same_key_concurrent_subscribers_build_once_and_receive_independent_bodies(reports, monkeypatch):
    profile = reports.profiles.get(LEARNER)
    reports.service.build_report(profile)  # Settle first-read curriculum/tier writes.
    reports.service._cache.discard_learner(LEARNER)
    original = reports.service._build_report_once
    entered, release, lock = Event(), Event(), Lock()
    calls = []

    def build(*args, **kwargs):
        with lock:
            calls.append(1)
        entered.set()
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(reports.service, "_build_report_once", build)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(reports.service.get_snapshot, profile) for _ in range(6)]
        assert entered.wait(timeout=5)
        release.set()
        snapshots = [future.result(timeout=10) for future in futures]
    assert len(calls) == 1 and len({id(item) for item in snapshots}) == 1
    snapshots[0].materialize()["recent_attempts"].clear()
    assert len(snapshots[1].materialize()["recent_attempts"]) == 10


def test_watermark_changes_during_build_retry_and_continuous_changes_return_503(reports, monkeypatch):
    profile = reports.profiles.get(LEARNER)
    reports.service.build_report(profile)
    reports.service._cache.discard_learner(LEARNER)
    original = reports.service._build_report_once
    counter = [0]

    def build(*args, **kwargs):
        value = original(*args, **kwargs)
        counter[0] += 1
        with reports.engine.begin() as db:
            db.execute(text("UPDATE learner_profiles SET learning_goal=:goal WHERE learner_id=:learner"), {"goal": str(counter[0]), "learner": LEARNER})
        return value

    monkeypatch.setattr(reports.service, "_build_report_once", build)
    with pytest.raises(ReportSnapshotUnstable):
        reports.service.get_snapshot(profile)
    assert counter[0] == 3 and not reports.service._cache.entries
    monkeypatch.setattr(reports.service, "_build_report_once", original)
    assert reports.service.build_report(profile)["learning_goal"] == "3"


def test_missing_watermark_trigger_and_mixed_dependencies_disable_cache(reports, monkeypatch):
    profile = reports.profiles.get(LEARNER)
    reports.service.build_report(profile)
    name = next(iter(expected_triggers()))
    with reports.engine.begin() as db:
        db.execute(text(f'DROP TRIGGER "{name}"'))
    calls = _count_builds(reports.service, monkeypatch)
    reports.service.build_report(profile)
    reports.service.build_report(profile)
    assert len(calls) == 4  # Full semantic double-read, never old cache hits.
    reports.service.feedback_repo = MemoryFeedbackRepository()
    assert reports.service._reader() is None
    rollback_p0_35_report_read_model_migration(reports.engine)
    reports.service.build_report(profile)
    assert len(calls) == 6


def test_native_cache_checks_current_owner_and_api_and_each_sse_poll_reauthorize(reports):
    with reports.factory() as db:
        for user_id in ("owner", "other"):
            db.add(UserProfileORM(user_id=user_id, display_name=user_id, identity="test", education="本科", major="software"))
        db.commit()
    with reports.engine.begin() as db:
        db.execute(text("UPDATE learner_profiles SET user_id='owner' WHERE learner_id=:learner"), {"learner": LEARNER})
    owner = reports.profiles.get(LEARNER)
    user = UserProfile(user_id="owner", display_name="owner", identity="test", education="本科", major="software")
    reports.app.container.auth_service = lambda: SimpleNamespace(resolve_token=lambda token: user if token == "owner-token" else user.model_copy(update={"user_id": "other"}))
    reports.app.include_router(routes.router, prefix="/private/report", dependencies=[Depends(get_current_user)])
    with TestClient(reports.app) as client:
        client.cookies.set(get_settings().auth_cookie_name, "owner-token")
        first = client.get(f"/private/report/{LEARNER}")
        assert first.status_code == 200
        client.cookies.set(get_settings().auth_cookie_name, "other-token")
        assert client.get(f"/private/report/{LEARNER}", headers={"If-None-Match": first.headers["etag"]}).status_code == 404
        with reports.engine.begin() as db:
            db.execute(text("UPDATE learner_profiles SET user_id='other' WHERE learner_id=:learner"), {"learner": LEARNER})
        client.cookies.set(get_settings().auth_cookie_name, "owner-token")
        assert client.get(f"/private/report/{LEARNER}", headers={"If-None-Match": first.headers["etag"]}).status_code == 404
    with pytest.raises(ReportSnapshotUnstable):
        reports.service.get_snapshot(owner)
    assert not reports.service._cache.entries
    request = SimpleNamespace(app=reports.app, state=SimpleNamespace(current_user=user))
    assert routes._stream_snapshot(request, reports.service, LEARNER, 30) is None


def test_native_keyset_pages_match_memory_visibility_sorting_and_only_load_page_resources(reports):
    with reports.engine.begin() as db:
        db.execute(text("UPDATE generated_resources SET published_at=NULL WHERE resource_id IN ('resource-028','resource-029')"))
        db.execute(text("UPDATE generated_resources SET published_at=:stamp WHERE resource_id IN ('resource-001','resource-002')"), {"stamp": NOW.replace(tzinfo=None)})
        # Same batch, real replacement only for the type that is published.
        db.execute(text("UPDATE generated_resources SET batch_id='shared' WHERE run_id IN ('run-1','run-2')"))
        db.execute(text("UPDATE generation_jobs SET batch_id='shared', created_at=:stamp WHERE run_id IN ('run-1','run-2')"), {"stamp": NOW.replace(tzinfo=None)})
        db.execute(text("UPDATE generation_jobs SET request_payload=:value WHERE run_id='run-2'"), {"value": '{"constraints":{"replacement_resource_types":["讲义","non-published-type"]}}'})
        db.execute(text("UPDATE generation_jobs SET superseded_by_run_id='run-4' WHERE run_id='run-3'"))
        db.execute(text("UPDATE generated_resources SET publication_status='unpublished' WHERE resource_id='resource-026'"))
    memory_resources, memory_jobs = MemoryResourceRepository(), MemoryGenerationJobRepository()
    for resource in reports.service.resource_repo.list_by_learner(LEARNER):
        memory_resources.save(resource, LEARNER, resource.topic)
    for job in reports.service.generation_job_repo.list_by_learner(LEARNER):
        memory_jobs.create(job.run_id, job.learner_id, job.topic, job.knowledge_base_id, job.request_payload, job.batch_id)
        memory_jobs._store[job.run_id] = job.model_dump(exclude={"focus_snapshot"})
    memory = ReportService(memory_resources, MemoryFeedbackRepository(), generation_job_repo=memory_jobs,
                           claim_repo=reports.service.claim_repo, audit_repo=reports.service.audit_repo)
    expected = memory._resource_credibility(memory._visible_resources(LEARNER))["items"]
    actual, cursor = [], None
    resource_loads = []

    def loaded(_session, obj):
        if isinstance(obj, GeneratedResourceORM):
            resource_loads.append(obj.resource_id)

    event.listen(reports.factory, "loaded_as_persistent", loaded)
    try:
        while True:
            resource_loads.clear()
            page = reports.service.list_resource_credibility(LEARNER, limit=3, cursor=cursor)
            assert len(resource_loads) <= 4
            actual.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
    finally:
        event.remove(reports.factory, "loaded_as_persistent", loaded)
    assert actual == expected
    assert len({item["resource_id"] for item in actual}) == len(actual)
    assert "resource-000" not in {item["resource_id"] for item in actual}


@pytest.mark.parametrize("change", ["delete", "timestamp", "parent", "superseded"])
def test_cursor_anchor_must_remain_visible_with_exact_publication_time(reports, change):
    first = reports.service.list_resource_credibility(LEARNER, limit=1)
    anchor = first["items"][0]["resource_id"]
    with reports.engine.begin() as db:
        if change == "delete":
            # Unpublishing has the same public deletion semantics without
            # violating immutable Claim/review foreign keys in this fixture.
            db.execute(text("UPDATE generated_resources SET publication_status='unpublished' WHERE resource_id=:rid"), {"rid": anchor})
        elif change == "timestamp":
            db.execute(text("UPDATE generated_resources SET published_at=:stamp WHERE resource_id=:rid"), {"rid": anchor, "stamp": NOW.replace(tzinfo=None)})
        elif change == "parent":
            db.execute(text("UPDATE generated_resources SET parent_resource_id=:rid WHERE resource_id='resource-029'"), {"rid": anchor})
        else:
            db.execute(text("UPDATE generation_jobs SET superseded_by_run_id='replacement' WHERE run_id=(SELECT run_id FROM generated_resources WHERE resource_id=:rid)"), {"rid": anchor})
    with pytest.raises(ReportCursorInvalid):
        reports.service.list_resource_credibility(LEARNER, limit=1, cursor=first["next_cursor"])


def test_10001_formal_attempts_are_complete_and_point_queries_are_batched(tmp_path):
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'history.db'}"))
    try:
        seed_database(engine, 10001)
        factory = sessionmaker(bind=engine)
        service = make_service(factory)
        profile = SQLLearnerRepository(factory).get(LEARNER)
        with _queries(engine) as queries:
            report = service.build_report(profile, now=NOW)
        assert report["learning_activity"]["verified_attempt_count"] == 10001
        assert report["learning_activity"]["answered_item_count"] == 20002
        assert len(service.feedback_loop_repo.list_attempts(LEARNER)) == 20
        assert len(service.feedback_loop_repo.list_attempts(LEARNER, None)) == 10001
        assert sum("FROM learning_attempt_point_results" in query for query in queries) < 100
    finally:
        engine.dispose()


def _add_mastery_node(reports):
    catalog = reports.service.mastery_service.knowledge_service.catalog
    catalog.upsert_skill_nodes([{"node_id": "skill", "name": "Synthetic skill", "tier": 1, "level": "初级"}], "benchmark")
    return catalog


def test_mastery_event_window_expires_without_writes_and_keeps_complete_history(reports):
    _add_mastery_node(reports)
    evidence = AbilityEvidenceV1(
        evidence_id="edge-evidence", learner_id=LEARNER, knowledge_base_id="benchmark", skill_node_id="skill",
        source_type="learning_attempt", source_id="edge-source", source_hash="a" * 64,
        observed_score=0.5, verified=True, occurred_at=NOW - timedelta(days=30),
    )
    reports.service.mastery_service.repository.apply_evidence([evidence], {"skill": "Synthetic skill"}, increment_profile_version=False)
    profile = reports.profiles.get(LEARNER)
    first = reports.service.get_snapshot(profile, now=NOW)
    token = reports.service.read_repo.read_token()
    expired = reports.service.get_snapshot(profile, now=NOW + timedelta(microseconds=1))
    assert reports.service.read_repo.read_token() == token
    assert len(first.materialize()["mastery_trends"]) == 1
    assert expired.materialize()["mastery_trends"] == []
    assert len(expired.materialize()["mastery_trend"]) == 1
    assert first.metadata()["report_revision"] != expired.metadata()["report_revision"]


@pytest.mark.parametrize("statement,parameters", [
    ("UPDATE rag_skill_nodes SET name='renamed' WHERE node_id='skill'", {}),
    ("UPDATE learner_curriculum_nodes SET progress_status='scheduled' WHERE skill_node_id='skill'", {}),
    ("UPDATE learner_tier_progress SET row_version=row_version+1 WHERE learner_id=:learner", {"learner": LEARNER}),
    ("UPDATE generation_jobs SET request_payload=:value WHERE run_id='run-0'", {"value": '{"target_skill_nodes":["skill"]}'}),
    ("UPDATE diagnostic_runs SET raw_result=:value WHERE diagnostic_result_id='diagnostic'", {"value": '{"measurement_coverage":{"skill":{"coverage":0.8}}}'}),
])
def test_catalog_curriculum_tier_job_and_diagnosis_inputs_invalidate_complete_projection(reports, statement, parameters):
    _add_mastery_node(reports)
    with reports.factory() as db:
        db.add(DiagnosticRunORM(diagnostic_result_id="diagnostic", learner_id=LEARNER, knowledge_base_id="benchmark",
                                ability_level="初级", raw_result={"measurement_coverage": {"skill": {"coverage": 0.4}}}))
        db.commit()
    profile = reports.profiles.get(LEARNER)
    before = reports.service.get_snapshot(profile).metadata()
    with reports.engine.begin() as db:
        db.execute(text(statement), parameters)
    after = reports.service.get_snapshot(profile).metadata()
    assert before["report_revision"] != after["report_revision"]


def test_followup_insert_update_and_delete_change_revision_without_profile_version_bump(reports):
    profile = reports.profiles.get(LEARNER)
    original = reports.service.get_snapshot(profile).metadata()
    with reports.factory() as db:
        db.add(FeedbackFollowUpRunORM(relation_id="followup", attempt_id="attempt-000000", decision_id="decision-0",
                                     child_run_id="run-0", trigger_type="hold", status="queued"))
        db.commit()
    inserted = reports.service.get_snapshot(profile)
    assert inserted.materialize()["recent_followup_runs"][0]["status"] == "queued"
    with reports.engine.begin() as db:
        db.execute(text("UPDATE feedback_followup_runs SET status='failed', error_code='SYNTHETIC' WHERE relation_id='followup'"))
    updated = reports.service.get_snapshot(profile)
    assert updated.materialize()["recent_followup_runs"][0]["status"] == "failed"
    assert len({original["report_revision"], inserted.metadata()["report_revision"], updated.metadata()["report_revision"]}) == 3
    assert original["as_of_profile_version"] == updated.metadata()["as_of_profile_version"]
    with reports.engine.begin() as db:
        db.execute(text("DELETE FROM feedback_followup_runs WHERE relation_id='followup'"))
    assert reports.service.get_snapshot(profile).materialize()["recent_followup_runs"] == []


def test_legacy_feedback_is_versioned_when_no_formal_loop_is_injected(reports):
    reports.service.feedback_loop_repo = None
    with reports.factory() as db:
        db.add(FeedbackRecordORM(feedback_id="legacy", learner_id=LEARNER, resource_id="resource-001", correct_rate=0.4, decision="hold"))
        db.commit()
    profile = reports.profiles.get(LEARNER)
    before = reports.service.get_snapshot(profile)
    with reports.engine.begin() as db:
        db.execute(text("UPDATE feedback_records SET correct_rate=0.9 WHERE feedback_id='legacy'"))
    after = reports.service.get_snapshot(profile)
    assert before.metadata()["report_revision"] != after.metadata()["report_revision"]
    assert after.materialize()["recent_feedback"][0].correct_rate == 0.9


def test_claim_binding_and_latest_review_mismatch_remain_authoritative(reports):
    resources = reports.service.resource_repo.list_by_learner(LEARNER)
    resource = next(item for item in resources if item.resource_id == "resource-001")
    with reports.engine.begin() as db:
        # A newer audit for a different version must not bind to this resource.
        db.execute(text("UPDATE resource_claims SET resource_version=2 WHERE resource_id='resource-001'"))
        db.execute(text("UPDATE claim_judgements SET resource_version=2 WHERE resource_id='resource-001'"))
        db.execute(text("INSERT INTO resource_reviews (review_id,resource_id,status,claim_total,claim_supported,claim_unsupported,suspected_hallucinations,hallucination_rate,review_pass_rate,revision_count,created_at,issues) VALUES ('wrong-review','resource-001','rejected',0,0,0,0,0,0,0,:stamp,'[]')"), {"stamp": NOW.replace(tzinfo=None)})
    with _queries(reports.engine) as queries:
        result = reports.service._resource_credibility([resource])["items"][0]
    assert result["publication_review"]["review_status"] == "approved"
    assert result["publication_review"]["status"] == "not_measured"
    assert result["claim_support"]["status"] == "not_measured"
    assert sum("FROM claim_judgements" in query for query in queries) == 1


def test_keys_isolate_learners_windows_knowledge_bases_and_recreated_profile(reports):
    profile = reports.profiles.get(LEARNER)
    first = reports.service.get_snapshot(profile, window_days=7)
    other_window = reports.service.get_snapshot(profile, window_days=30)
    assert first.metadata()["report_revision"] != other_window.metadata()["report_revision"]
    second = profile.model_copy(update={"learner_id": "second", "learning_goal": "Second"})
    reports.service.profile_repo.save(second)
    separate = reports.service.get_snapshot(second)
    assert separate.materialize()["learner_id"] == "second" and separate.materialize()["recent_attempts"] == []
    with reports.engine.begin() as db:
        db.execute(text("INSERT INTO knowledge_bases (knowledge_base_id,name,version) VALUES ('benchmark-2','Second','1')"))
        db.execute(text("UPDATE learner_profiles SET knowledge_base_id='benchmark-2' WHERE learner_id='second'"))
    switched = reports.service.get_snapshot(second)
    assert switched.materialize()["generation_options"].knowledge_base_id == "benchmark-2"
    assert switched is not separate
    assert reports.profiles.delete("second")
    with pytest.raises(ReportSnapshotUnstable):
        reports.service.get_snapshot(second)
    reports.service.profile_repo.save(second.model_copy(update={"learning_goal": "Recreated"}))
    assert reports.service.get_snapshot(second).materialize()["learning_goal"] == "Recreated"
    # A fresh installation token prevents a recreated cache source from
    # aliasing an earlier zero epoch, even if all fact timestamps are retained.
    from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration
    old_token = reports.service.read_repo.read_token()
    rollback_p0_35_report_read_model_migration(reports.engine)
    apply_p0_35_report_read_model_migration(reports.engine)
    assert reports.service.read_repo.read_token()[0] != old_token[0]
    assert reports.service.get_snapshot(profile, window_days=7) is not first


def test_uncached_authoritative_reads_retry_if_build_crosses_time_boundary(reports):
    reports.service.read_repo = None
    with reports.engine.begin() as db:
        db.execute(text("UPDATE learning_attempts SET submitted_at=:stamp"), {"stamp": (NOW - timedelta(days=30)).replace(tzinfo=None)})
    later = NOW + timedelta(microseconds=1)
    clock = iter([NOW, later, later, later])
    reports.service._clock = lambda: next(clock, later)
    value = reports.service.build_report(reports.profiles.get(LEARNER))
    assert value["generated_at"] == later
    assert value["learning_activity"]["verified_attempt_count"] == 0


def test_unknown_repository_extension_cannot_claim_watermark_coverage(reports):
    class ExtendedResourceRepository(type(reports.service.resource_repo)):
        pass

    reports.service.resource_repo = ExtendedResourceRepository(reports.factory)
    assert reports.service._reader() is None
