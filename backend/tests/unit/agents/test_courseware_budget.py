from datetime import datetime, timedelta, timezone

from app.agents.resource_workflows.interactive_courseware.budget import CoursewareBudgetCoordinator


class FakeRepo:
    def __init__(self):
        self.job = {"deadline_at": datetime.now(timezone.utc) + timedelta(minutes=5)}
        self.events = []

    def get_job(self, run_id):
        return self.job

    def list_events(self, run_id):
        return self.events


class Settings:
    courseware_total_llm_token_budget = 32768
    courseware_planner_token_budget = 4096
    courseware_scene_composition_token_budget = 14336
    courseware_scene_call_max_tokens = 4096
    courseware_quality_review_token_budget = 4096
    courseware_revision_token_budget = 10240
    courseware_quality_review_reserved_tokens = 4096
    courseware_revision_reserved_tokens = 10240
    courseware_planner_max_seconds = 90
    courseware_scene_composition_max_seconds = 450
    courseware_quality_review_max_seconds = 120
    courseware_revision_max_seconds = 180


def test_default_stage_budgets_and_future_reserves_are_enforced():
    repo = FakeRepo()
    coordinator = CoursewareBudgetCoordinator(repo, lambda: Settings())

    assert coordinator.before_call("run", "planner").max_output_tokens == 4096
    # Planner's unused 4096 can flow forward, but quality + revision reserves
    # remain protected from the scene call.
    assert coordinator.before_call("run", "scene").max_output_tokens == 4096
    assert coordinator.before_call("run", "quality_review").max_output_tokens == 4096
    assert coordinator.before_call("run", "revision").max_output_tokens == 4096


def test_stage_usage_is_charged_to_the_recorded_stage_and_exhaustion_denies():
    repo = FakeRepo()
    repo.events = [
        {"stage": "llm_observation", "payload": {"trace": {
            "node_name": "courseware_scene_composer", "budget_stage": "scene",
            "input_tokens": 13000, "output_tokens": 6000,
        }}},
    ]
    coordinator = CoursewareBudgetCoordinator(repo, lambda: Settings())
    decision = coordinator.before_call("run", "scene", requested_output_tokens=4096)
    assert decision.allowed is False
    assert decision.warning["code"] == "COURSEWARE_STAGE_BUDGET_EXHAUSTED"
    assert decision.warning["budget_stage"] == "scene"


def test_deadline_gate_is_task_scoped():
    repo = FakeRepo()
    repo.job["deadline_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    decision = CoursewareBudgetCoordinator(repo, lambda: Settings()).before_call("run", "planner")
    assert decision.allowed is False
    assert decision.warning["code"] == "COURSEWARE_RUN_TIMEOUT"
    assert decision.warning["budget_scope"] == "task"
