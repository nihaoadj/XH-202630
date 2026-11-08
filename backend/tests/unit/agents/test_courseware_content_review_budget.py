from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from app.models.courseware.contracts import CoursewareJobCreateRequest
from app.models.courseware.content_review import ContentReviewBlocked
from app.agents.resource_workflows.interactive_courseware.content_review.persistence import read_state
from tests.fakes.courseware_content_review import fixture_environment, fixture_settings, make_workflow


@pytest.mark.parametrize("missing", ["get_spec_by_run", "get_run_content_review_binding"])
def test_partial_private_repository_port_cannot_be_treated_as_legacy(missing):
    from types import SimpleNamespace
    methods = {"get_spec_by_run": lambda _: None, "get_run_content_review_binding": lambda _: None}
    methods.pop(missing)
    with pytest.raises(ContentReviewBlocked, match="incomplete private content repository port"):
        read_state(SimpleNamespace(**methods), "run")


def setup_budget(tmp_path, settings=None):
    wf, source = make_workflow(tmp_path)
    job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
    wf.content_review.claim(job.run_id)
    return wf, job.run_id


def test_cas_reservations_compete_for_same_frozen_total_and_unknown_usage_is_not_zero(tmp_path):
    settings = fixture_settings(courseware_total_llm_token_budget=1024, courseware_planner_token_budget=0,
        courseware_scene_composition_token_budget=1024, courseware_scene_call_max_tokens=256,
        courseware_quality_review_token_budget=0, courseware_revision_token_budget=0,
        courseware_quality_review_reserved_tokens=0, courseware_revision_reserved_tokens=0)
    with fixture_environment(tmp_path, settings):
        wf, run_id = setup_budget(tmp_path)
        with ThreadPoolExecutor(max_workers=3) as pool:
            decisions = list(pool.map(lambda _: wf.budget.before_call(run_id, "scene", requested_output_tokens=256, estimated_input_tokens=128), range(3)))
        assert sum(d.allowed for d in decisions) == 2
        decision = next(d for d in decisions if d.allowed)
        wf.budget.reconcile(run_id, decision.call_id)
        state, _ = read_state(wf.repo, run_id)
        unknown = next(t for t in state.ledger if t.ticket_id == decision.call_id and t.status == "unknown")
        assert unknown.charged_tokens == 384
        assert not wf.budget.before_call(run_id, "scene", requested_output_tokens=256, estimated_input_tokens=128).allowed
        with pytest.raises(ValueError):
            wf.budget.before_call(run_id, "unknown", requested_output_tokens=1, estimated_input_tokens=1)


def test_frozen_budget_is_not_replaced_by_changed_settings_and_deadline_denies_before_call(tmp_path):
    with fixture_environment(tmp_path):
        wf, run_id = setup_budget(tmp_path)
        wf.budget.settings_provider = lambda: object()
        assert wf.budget.before_call(run_id, "scene", requested_output_tokens=256, estimated_input_tokens=128).allowed
        wf.repo.update_job(run_id, deadline_at=datetime.now(timezone.utc)-timedelta(seconds=1))
        with pytest.raises(Exception):
            wf.content_review.gateway(run_id, "scene", "test").guard()
        assert not wf.llm_gateway.calls


def test_real_gateway_cannot_impersonate_fixture_estimator_even_with_marker(tmp_path):
    from app.core.llm.gateway import LLMGateway
    from app.agents.resource_workflows.interactive_courseware.content_review.batching import resolve_estimator
    from app.agents.resource_workflows.interactive_courseware.content_review.persistence import freeze_policy
    from tests.fakes.courseware_content_review import ContentReviewGateway
    policy = freeze_policy(fixture_settings(), ContentReviewGateway(), datetime.now(timezone.utc)+timedelta(minutes=10))
    real = object.__new__(LLMGateway); real.offline_content_review = True
    with pytest.raises(ContentReviewBlocked): resolve_estimator(policy, real)
    with pytest.raises(ContentReviewBlocked): freeze_policy(fixture_settings(), real, datetime.now(timezone.utc))


def test_second_owner_does_not_quarantine_or_mutate_active_job(tmp_path):
    with fixture_environment(tmp_path):
        wf, run_id = setup_budget(tmp_path)
        before = wf.repo.get_job(run_id)
        assert wf.run(run_id).status == "queued"
        assert wf.repo.get_job(run_id) == before and wf.repo.list_events(run_id)[-1]["status"] == "queued"
