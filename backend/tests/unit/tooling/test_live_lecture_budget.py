"""T37 acceptance quota: reserved-at-start, never refunded, serialized."""
import importlib.util
import json
import threading
from pathlib import Path

import pytest

from scripts import acceptance_budget as budget

LIVE = Path(__file__).resolve().parents[3] / "scripts/live_lecture_claim_once.py"


def load_live(*, strict_authorization=False):
    spec = importlib.util.spec_from_file_location("live_lecture_claim_once_t37", LIVE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Most tests isolate slot accounting. Real path/cap authorization is tested
    # separately below without this stub.
    if not strict_authorization:
        module._check_authorization = lambda *a: None
    return module


def fresh(tmp_path):
    path = tmp_path / "budget.json"
    budget.init_budget(path)
    return path


def test_init_creates_three_unused_slots_and_refuses_reset(tmp_path):
    path = fresh(tmp_path)
    data = budget.load(path)
    assert data["plan_id"] == "T37"
    assert data["max_generations"] == 3
    assert {key: entry["state"] for key, entry in data["slots"].items()} == {
        "1": "unused", "2": "unused", "3": "unused"}
    with pytest.raises(budget.BudgetError):
        budget.init_budget(path)


def test_reserve_consumes_a_slot_and_replay_is_rejected(tmp_path):
    path = fresh(tmp_path)
    data = budget.reserve_slot(path, 1)
    assert data["slots"]["1"]["state"] == "reserved"
    assert budget.used_slots(data) == 1
    with pytest.raises(budget.BudgetExhausted):
        budget.reserve_slot(path, 1)
    # A fresh reserve on a different slot is still allowed.
    data = budget.reserve_slot(path, 2)
    assert budget.used_slots(data) == 2


def test_failure_and_unknown_outcomes_never_refund(tmp_path):
    path = fresh(tmp_path)
    for slot, outcome in ((1, "failed"), (2, "unknown"), (3, "completed")):
        budget.reserve_slot(path, slot)
        budget.settle_slot(path, slot, outcome=outcome)
    data = budget.load(path)
    assert budget.used_slots(data) == 3
    assert budget.summary(data)["remaining"] == 0
    with pytest.raises(budget.BudgetExhausted):
        budget.reserve_slot(path, 1)


def test_takeover_reopens_one_unsettled_slot_without_refunding(tmp_path):
    path = fresh(tmp_path)
    budget.reserve_slot(path, 3)
    budget.mark_running(path, 3, "run-killed")
    with pytest.raises(budget.BudgetError):
        budget.takeover_slot(path, 3, reason="   ")  # a reason is mandatory
    data = budget.takeover_slot(path, 3, reason="operator stopped a run that wrote max_iterations=0")
    entry = data["slots"]["3"]
    assert entry["state"] == "reserved" and entry["run_id"] is None
    assert entry["takeovers"][0]["previous_run_id"] == "run-killed"
    assert entry["takeovers"][0]["previous_state"] == "running"
    # Still consumed: a takeover never creates a fourth generation.
    summary = budget.summary(data)
    assert (summary["used"], summary["remaining"]) == (1, 2)
    with pytest.raises(budget.BudgetError):
        budget.takeover_slot(path, 3, reason="second attempt")


def test_takeover_is_rejected_once_a_slot_is_settled(tmp_path):
    path = fresh(tmp_path)
    budget.reserve_slot(path, 2)
    budget.settle_slot(path, 2, outcome="failed")
    with pytest.raises(budget.BudgetError):
        budget.takeover_slot(path, 2, reason="too late")


def test_slot_run_passes_the_requested_rework_instead_of_zero(monkeypatch, tmp_path):
    """Regression: _run_slot used to hardcode 0/0 and silently drop both flags."""
    live = load_live()
    monkeypatch.setattr(live, '_preflight', lambda *a: {'ok':True})
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    seen = {}

    def fake_run(args, _budget, max_iterations, claim_max_iterations, timeout_seconds):
        seen.update(max_iterations=max_iterations,
                    claim_max_iterations=claim_max_iterations,
                    timeout_seconds=timeout_seconds)
        return 0

    monkeypatch.setattr(live, "_run_live", fake_run)
    assert live.main(["--acceptance-budget", str(path), "--acceptance-slot", "2",
                      "--learner-id", "l", "--target-node", "rerank",
                      "--max-iterations", "2", "--claim-max-iterations", "1"]) == 0
    assert (seen["max_iterations"], seen["claim_max_iterations"]) == (2, 1)
    assert budget.summary(budget.load(path))["used"] == 1


def test_crash_after_reserve_leaves_the_slot_consumed(tmp_path):
    path = fresh(tmp_path)
    budget.reserve_slot(path, 1)  # process dies here
    data = budget.load(path)
    assert data["slots"]["1"]["state"] == "reserved"
    with pytest.raises(budget.BudgetExhausted):
        budget.reserve_slot(path, 1)
    assert budget.summary(data)["remaining"] == 2


def test_invalid_slot_and_outcome_are_rejected(tmp_path):
    path = fresh(tmp_path)
    with pytest.raises(budget.BudgetError):
        budget.reserve_slot(path, 4)
    with pytest.raises(budget.BudgetError):
        budget.reserve_slot(path, 0)
    budget.reserve_slot(path, 1)
    with pytest.raises(budget.BudgetError):
        budget.settle_slot(path, 1, outcome="retry")


def test_concurrent_reservation_yields_exactly_one_winner(tmp_path):
    path = fresh(tmp_path)
    outcomes = []

    def attempt():
        try:
            budget.reserve_slot(path, 1)
            outcomes.append("ok")
        except budget.BudgetError:
            outcomes.append("blocked")

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert budget.load(path)["slots"]["1"]["state"] == "reserved"


def test_missing_or_corrupt_budget_is_rejected(tmp_path):
    with pytest.raises(budget.BudgetError):
        budget.load(tmp_path / "absent.json")
    path = fresh(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["max_generations"] = 4
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(budget.BudgetError):
        budget.load(path)
    data["max_generations"] = 3
    data["slots"]["1"]["state"] = "replayed"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(budget.BudgetError):
        budget.load(path)


def test_live_cli_parses_slots_and_uses_the_production_rework_defaults():
    live = load_live()
    assert live._parse_args([]).acceptance_slot == 0
    assert live._parse_args(["--acceptance-slot", "3"]).acceptance_slot == 3
    with pytest.raises(SystemExit):
        live._parse_args(["--acceptance-slot", "4"])
    args = live._parse_args(["--acceptance-budget", "b.json", "--acceptance-slot", "1"])
    # Mirrors GenerateRequest defaults: two body reworks (three generations)
    # and one Claim rework. These are also the acceptance ceiling.
    assert (args.max_iterations, args.claim_max_iterations) == (2, 1)


def test_init_via_cli_needs_no_live_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("RUN_LIVE_LLM", raising=False)
    live = load_live()
    path = tmp_path / "quota.json"
    assert live.main(["--acceptance-budget", str(path), "--init-acceptance-budget"]) == 0
    assert path.exists()
    # Second init must fail without touching the existing quota.
    assert live.main(["--acceptance-budget", str(path), "--init-acceptance-budget"]) == 4
    assert budget.used_slots(budget.load(path)) == 0


def test_missing_live_switch_does_not_consume_a_slot(monkeypatch, tmp_path):
    """The live switch is a preflight condition, so it must not spend quota."""
    live = load_live()
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.delenv("RUN_LIVE_LLM", raising=False)
    with pytest.raises(SystemExit):
        live.main(["--acceptance-budget", str(path), "--acceptance-slot", "1",
                   "--learner-id", "l", "--target-node", "rerank",
                   "--max-iterations", "0", "--claim-max-iterations", "0"])
    assert budget.load(path)["slots"]["1"]["state"] == "unused"


def test_job_creation_failure_after_reserve_is_never_refunded(monkeypatch, tmp_path):
    live = load_live()
    monkeypatch.setattr(live, '_preflight', lambda *a: {'ok':True})
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.setenv("RUN_LIVE_LLM", "1")

    def boom():
        raise RuntimeError("container unavailable")

    monkeypatch.setattr(live, "init_container", boom)
    with pytest.raises(RuntimeError):
        live.main(["--acceptance-budget", str(path), "--acceptance-slot", "1",
                   "--learner-id", "l", "--target-node", "rerank",
                   "--max-iterations", "0", "--claim-max-iterations", "0"])
    entry = budget.load(path)["slots"]["1"]
    assert entry["state"] == "unknown"
    assert budget.summary(budget.load(path))["remaining"] == 2


def test_reserve_and_settle_reuse_the_callers_lock(tmp_path):
    """The nested calls must not attempt a second O_EXCL acquisition."""
    path = fresh(tmp_path)
    with budget.budget_lock(path):
        budget.reserve_slot(path, 1, locked=True)
        budget.mark_running(path, 1, "run-1", locked=True)
        budget.settle_slot(path, 1, outcome="completed", locked=True)
    assert budget.load(path)["slots"]["1"]["state"] == "completed"


def test_nested_call_without_the_hint_reports_the_held_lock(tmp_path):
    path = fresh(tmp_path)
    with budget.budget_lock(path):
        with pytest.raises(budget.BudgetLocked):
            budget.reserve_slot(path, 1)


def test_plan_lock_covers_the_whole_slot_not_only_the_write(monkeypatch, tmp_path):
    """T37 7.3: concurrency is 1 for reserve -> run -> settle, not per write.

    While slot 1 executes, another process must not be able to reserve slot 2.
    """
    live = load_live()
    monkeypatch.setattr(live, '_preflight', lambda *a: {'ok':True})
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    observed = {}

    def fake_run(args, state, max_iterations, claim_max_iterations, timeout_seconds):
        observed["lock_held"] = budget.lock_path(path).exists()
        observed["slot1"] = budget.load(path)["slots"]["1"]["state"]
        observed["iterations"] = (max_iterations, claim_max_iterations, timeout_seconds)
        with pytest.raises(budget.BudgetLocked):
            budget.reserve_slot(path, 2)
        return 0

    monkeypatch.setattr(live, "_run_live", fake_run)
    assert live.main(["--acceptance-budget", str(path), "--acceptance-slot", "1",
                      "--learner-id", "l", "--target-node", "rerank",
                      "--max-iterations", "0", "--claim-max-iterations", "0"]) == 0
    assert observed["lock_held"] is True
    assert observed["slot1"] == "reserved"
    assert observed["iterations"] == (0, 0, 1800)
    assert budget.load(path)["slots"]["2"]["state"] == "unused"
    # The lock is released only after the slot window closes.
    assert budget.lock_path(path).exists() is False


def test_a_crash_inside_the_slot_keeps_the_quota_and_releases_no_lock(monkeypatch, tmp_path):
    live = load_live()
    monkeypatch.setattr(live, '_preflight', lambda *a: {'ok':True})
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    observed = {}

    def crash(args, state, max_iterations, claim_max_iterations, timeout_seconds):
        observed["lock_held"] = budget.lock_path(path).exists()
        raise RuntimeError("worker died")

    monkeypatch.setattr(live, "_run_live", crash)
    with pytest.raises(RuntimeError):
        live.main(["--acceptance-budget", str(path), "--acceptance-slot", "3",
                   "--learner-id", "l", "--target-node", "rerank",
                   "--max-iterations", "0", "--claim-max-iterations", "0"])
    assert observed["lock_held"] is True
    data = budget.load(path)
    assert data["slots"]["3"]["state"] == "unknown"
    assert budget.summary(data)["remaining"] == 2
    # A handled exception unwinds the context manager; only a hard kill leaves it.
    assert budget.lock_path(path).exists() is False


def test_a_leftover_lock_blocks_every_slot_until_removed_manually(monkeypatch, tmp_path):
    live = load_live()
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    monkeypatch.setenv("RUN_LIVE_LLM", "1")
    budget.lock_path(path).write_text("999999", encoding="utf-8")  # killed process
    for slot in ("1", "2", "3"):
        assert live.main(["--acceptance-budget", str(path), "--acceptance-slot", slot,
                          "--learner-id", "l", "--target-node", "rerank",
                          "--max-iterations", "0", "--claim-max-iterations", "0"]) == 4
    assert budget.used_slots(budget.load(path)) == 0
    assert budget.lock_path(path).exists() is True  # never auto-removed


class _FakeRepo:
    def __init__(self, profiles):
        self._profiles = profiles

    def list_all(self):
        return dict(self._profiles)


class _FakeProfileService:
    def __init__(self, profiles):
        self.repo = _FakeRepo(profiles)

    def get_profile(self, learner_id):  # pragma: no cover - not used by preflight
        return self.repo.list_all()[learner_id]


class _FakeMastery:
    def __init__(self, error):
        self.error = error
        self.calls = []

    def validate_generation_targets(self, profile, nodes):
        self.calls.append((profile.learner_id, list(nodes)))
        if self.error is not None:
            raise self.error
        return 3


class _FakeContainer:
    def __init__(self, profiles, mastery):
        self._profiles = profiles
        self._mastery = mastery

    def profile_service(self):
        return _FakeProfileService(self._profiles)

    def mastery_service(self):
        return self._mastery

    def llm_gateway(self):
        raise RuntimeError("gateway not configured in this test")


def _preflight_env(monkeypatch, tmp_path, live):
    monkeypatch.setattr(live, 'REPAIR_ROOT', tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/x.db")
    monkeypatch.setenv("RESOURCES_DIR", str(tmp_path / "resources"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "kb"))


def _fake_settings(monkeypatch, key="fake"):
    class _Settings:
        llm_api_key = key
        llm_model = "m"
        llm_thinking_mode = "disabled"

    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _Settings())


def test_preflight_runs_the_production_target_gate(monkeypatch, tmp_path):
    """A tier-ineligible target must be reported before any slot is reserved."""
    from app.models.learning_documents.schemas import LearnerProfile

    live = load_live()
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    _preflight_env(monkeypatch, tmp_path, live)
    _fake_settings(monkeypatch)
    profile = LearnerProfile(learner_id="t37-density-learner", learner_type="test",
                             education="本科", major="软件", learning_goal="理解RAG重排序并核验其依据", skill_level="中级",
                             knowledge_base_id="rag_engineering_training")
    mastery = _FakeMastery(ValueError(
        "target skill nodes are outside the active learning tier"))
    monkeypatch.setattr(live, "init_container",
                        lambda: _FakeContainer({"t37-density-learner": profile}, mastery))
    monkeypatch.setattr(live, "_queued_jobs", lambda: 0)
    args = ["--acceptance-budget", str(path), "--preflight-only",
            "--learner-id", "t37-density-learner", "--target-node", "rerank",
            "--max-iterations", "0", "--claim-max-iterations", "0"]
    assert live.main(args) == 4
    assert mastery.calls == [("t37-density-learner", ["rerank"])]
    assert budget.used_slots(budget.load(path)) == 0


@pytest.mark.parametrize("extra", [
    ["--max-iterations", "4", "--claim-max-iterations", "1"],
    ["--max-iterations", "2", "--claim-max-iterations", "4"],
    ["--max-iterations=4", "--claim-max-iterations", "1"],
])
def test_preflight_rejects_values_outside_generate_request_contract(
        monkeypatch, tmp_path, extra):
    """Internal revisions use GenerateRequest bounds, independent of slot quota."""
    from app.models.learning_documents.schemas import LearnerProfile

    live = load_live()
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    _preflight_env(monkeypatch, tmp_path, live)
    _fake_settings(monkeypatch)
    profile = LearnerProfile(learner_id="t37-density-learner", learner_type="test",
                             education="本科", major="软件", learning_goal="理解RAG重排序并核验其依据",
                             skill_level="进阶 RAG",
                             knowledge_base_id="rag_engineering_training")
    monkeypatch.setattr(live, "init_container",
                        lambda: _FakeContainer({"t37-density-learner": profile},
                                               _FakeMastery(None)))
    monkeypatch.setattr(live, "_queued_jobs", lambda: 0)
    args = live._parse_args(["--acceptance-budget", str(path), "--preflight-only",
                             "--learner-id", "t37-density-learner",
                             "--target-node", "rerank", *extra])
    report = live._preflight(args, budget.load(path))
    assert report["ok"] is False
    assert any("max-iterations" in problem or "claim-max-iterations" in problem
               for problem in report["problems"]), report["problems"]
    assert budget.used_slots(budget.load(path)) == 0


def test_preflight_reports_the_resolved_tier_when_the_target_is_allowed(monkeypatch, tmp_path):
    from app.models.learning_documents.schemas import LearnerProfile

    live = load_live()
    path = tmp_path / "quota.json"
    budget.init_budget(path)
    _preflight_env(monkeypatch, tmp_path, live)
    _fake_settings(monkeypatch)
    profile = LearnerProfile(learner_id="t37-density-learner", learner_type="test",
                             education="本科", major="软件", learning_goal="理解RAG重排序并核验其依据", skill_level="进阶 RAG",
                             knowledge_base_id="rag_engineering_training")
    mastery = _FakeMastery(None)
    monkeypatch.setattr(live, "init_container",
                        lambda: _FakeContainer({"t37-density-learner": profile}, mastery))
    monkeypatch.setattr(live, "_queued_jobs", lambda: 0)
    report = live._preflight(
        live._parse_args(["--acceptance-budget", str(path), "--preflight-only",
                          "--learner-id", "t37-density-learner", "--target-node", "rerank",
                          "--max-iterations", "0", "--claim-max-iterations", "0"]),
        budget.load(path),
    )
    assert report["target_tier"] == 3
    assert not any("generation target rejected" in item for item in report["problems"])
    assert report["provider_calls"] == 0
    assert budget.used_slots(budget.load(path)) == 0


def test_new_authorization_can_be_one_task_and_preserves_old_budget(tmp_path):
    old = fresh(tmp_path)
    original = old.read_bytes()
    new = tmp_path/'repair.json'
    budget.init_budget(new, max_generations=1)
    budget.reserve_slot(new, 1)
    budget.settle_slot(new, 1, outcome='unknown')
    assert budget.summary(budget.load(new))['remaining'] == 0
    for slot in [1, 2]:
        with pytest.raises(budget.BudgetError):
            budget.reserve_slot(new, slot)
    assert old.read_bytes() == original


def test_actual_slot_requires_preflight_without_spending_quota(monkeypatch, tmp_path):
    live = load_live()
    path = fresh(tmp_path)
    monkeypatch.setenv('RUN_LIVE_LLM','1')
    seen = []
    monkeypatch.setattr(live, '_preflight', lambda *a: {'ok':False,'problems':['wrong configuration']})
    monkeypatch.setattr(live, '_run_live', lambda *a: seen.append('called'))
    assert live.main(['--acceptance-budget',str(path),'--acceptance-slot','1']) == 4
    assert not seen and budget.used_slots(budget.load(path)) == 0


def test_failed_extraction_cannot_report_pass():
    live = load_live()
    report = dict(job={'status':'completed'}, nodes={'claim_extract':{'statuses':['failed']}},
                  extraction=dict(result_statuses=['failed'], candidates=0, judgements_complete=False,
                                  settled=True, budget_exhausted=False, overrun_tokens=0,
                                  current_resources_covered=True))
    assert live.classify_acceptance(report) == ('FAIL',2)
    report['extraction'].update(result_statuses=['completed'], candidates=75, judgements_complete=False)
    assert live.classify_acceptance(report) == ('FAIL',2)
    report['extraction']['judgements_complete'] = True
    assert live.classify_acceptance(report) == ('PASS',0)
    report['extraction']['current_resources_covered'] = False
    assert live.classify_acceptance(report) == ('FAIL',2)


def test_extraction_summary_counts_failed_parent_usage_and_unknown_separately():
    live = load_live()
    ledger = dict(calls=3, attempts=4, time_ms=10, budget_exhausted=False, overrun_tokens=0,
                  results={}, tickets={str(i):dict(usage_status=status, actual_tokens=tokens,
                        reserved_tokens=100, settled=True) for i,(status,tokens) in enumerate([
                            ('known',11),('known',13),('unknown',None),('known',17)])})
    result = live.extraction_summary({'resource_claims':128}, ledger, set())
    assert result['known_tokens'] == 41
    assert result['unknown_reserved_tokens'] == 100
    assert result['attempts'] == 4


def test_repair_authorization_rejects_other_files_and_larger_caps(tmp_path, monkeypatch):
    live = load_live(strict_authorization=True)
    authorized = tmp_path/'repair.json'
    monkeypatch.setattr(live, 'REPAIR_BUDGET', authorized)
    for path, cap in [(tmp_path/'other.json', 1), (authorized, 3)]:
        assert live.main(['--acceptance-budget',str(path),'--init-acceptance-budget',
                          '--max-generations',str(cap)]) == 4
        assert not path.exists()
    assert live.main(['--acceptance-budget',str(authorized),'--init-acceptance-budget',
                      '--max-generations','1']) == 0
    assert budget.load(authorized)['max_generations'] == 1
    with pytest.raises(budget.BudgetError):
        live._check_authorization(live._parse_args(['--acceptance-budget',str(authorized)]),
                                  {'max_generations':3})


def test_isolation_rejects_absolute_sibling_directory(tmp_path, monkeypatch):
    live = load_live(strict_authorization=True)
    _preflight_env(monkeypatch, tmp_path/'allowed', live)
    monkeypatch.setenv('RESOURCES_DIR',str(tmp_path/'other-production'))
    assert live._isolation_report()['ok'] is False


def test_current_resource_versions_excludes_replaced_ids_and_old_versions():
    live = load_live()
    resources = [dict(resource_id='old',parent_resource_id=None,version=1),
                 dict(resource_id='new',parent_resource_id='old',version=2)]
    assert live.current_resource_versions(resources) == {'new':2}
    resources = [dict(resource_id='stable',parent_resource_id=None,version=1),
                 dict(resource_id='stable',parent_resource_id=None,version=2)]
    assert live.current_resource_versions(resources) == {'stable':2}


def test_missing_trace_usage_is_explicitly_unknown():
    live = load_live()
    stats = live.attempt_usage([dict(input_tokens=10,output_tokens=5),
                               dict(input_tokens=None,output_tokens=None),
                               dict(input_tokens=0,output_tokens=0)])
    assert stats == dict(input_tokens=10,output_tokens=5,unknown_attempts=1)
