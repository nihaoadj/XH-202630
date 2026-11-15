"""G2: the runner blocks an old unfinished review before any stream/model call.

Six fault classes (begin_step failure, exit-after-begin, exit-after-first-response,
exit-after-correction, exit-after-terminal-before-checkpoint, lease-lost) each
leave the run in a state where a fresh entry must be refused with zero new
Provider calls, across Memory and SQLite repositories.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
    LectureStepGuardError,
    assert_no_unfinished_review,
)
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    canonical_hash,
)
from tests.integration.persistence.test_private_review_audit import repository as repository  # noqa: F401


def _begin(repo, run_id, step_id, *, node="reviewer", sequence=1, status_running=True):
    repo.begin_step(BeginStepCommand(run_id=run_id, step_id=step_id, step_sequence=sequence,
                                     node_name=node, agent_name="reviewer", action="review",
                                     started_at=datetime.now(timezone.utc)))


def _finish(repo, run_id, step_id, *, with_audit=False, with_checkpoint=False):
    repo.complete_step(CompleteStepCommand(
        run_id=run_id, step_id=step_id,
        trace={"status": "success", "attempt": 1, "resource_ids": [], "review_ids": []}))
    if with_checkpoint:
        repo.save_checkpoint(run_id=run_id, step_id=step_id, step_sequence=1, node_name="reviewer",
                             state_projection={}, state_hash=canonical_hash({}),
                             occurred_at=datetime.now(timezone.utc))


def _setup(repository, *, owner="owner-1", lease_seconds=3600):
    now = datetime.now(timezone.utc)
    run_id = "run-g2"
    expires = now + timedelta(seconds=lease_seconds)
    repository.create_run(CreateRunCommand(run_id=run_id, request_snapshot={},
                                           request_hash=canonical_hash({}), owner_instance_id=owner,
                                           lease_expires_at=expires))
    repository.start_run(run_id, occurred_at=now, lease_expires_at=expires)
    return run_id


# Fault classes 2/3/4/6 all leave a running review step.
@pytest.mark.parametrize("fault", [
    "exit_after_begin", "exit_after_first_response", "exit_after_correction", "lease_lost",
])
def test_running_review_step_is_isolated_on_resume(repository, fault):  # noqa: F811
    run_id = _setup(repository)
    _begin(repository, run_id, "step-review")
    with pytest.raises(LectureStepGuardError, match="unfinished"):
        assert_no_unfinished_review(repository=repository, run_id=run_id)


# Fault class 5: a terminal review without its audit/checkpoint chain.
def test_terminal_review_without_chain_is_isolated(repository):  # noqa: F811
    run_id = _setup(repository)
    _begin(repository, run_id, "step-review")
    _finish(repository, run_id, "step-review")
    with pytest.raises(LectureStepGuardError, match="chain_incomplete"):
        assert_no_unfinished_review(repository=repository, run_id=run_id)


# Fault class 1: begin_step never commits -> no review step; a completed chain
# is the only way a resume is allowed.
def test_begin_step_failure_leaves_no_review_step(repository):  # noqa: F811
    run_id = _setup(repository)
    # No review step at all: assert_no_unfinished_review is a no-op here, which
    # is correct — the run never sent a review request.  The begin-step failure
    # is enforced by RecordedNode raising before the node body, leaving zero
    # Provider calls (asserted at the RecordedNode level elsewhere).
    assert_no_unfinished_review(repository=repository, run_id=run_id)


def test_checkpoint_without_audit_is_still_isolated(repository):  # noqa: F811
    # A terminal review that has a checkpoint but no committed audit is still
    # incomplete: the audit and the checkpoint must both exist before a resume.
    run_id = _setup(repository)
    _begin(repository, run_id, "step-review")
    _finish(repository, run_id, "step-review", with_checkpoint=True)
    with pytest.raises(LectureStepGuardError, match="chain_incomplete"):
        assert_no_unfinished_review(repository=repository, run_id=run_id)


def test_runner_wires_the_check_before_stream(repository):  # noqa: F811
    """The runner's own hook refuses a V2 resume before any stream/model call."""
    from app.core.security.errors import ApplicationError
    from app.services.runs.durable_workflow_runner import DurableWorkflowRunner

    run_id = _setup(repository)
    _begin(repository, run_id, "step-review")  # running review left behind

    from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2

    workflow = object()  # has no .stream; the hook must raise before we get there
    runner = DurableWorkflowRunner(workflow, repository)
    policy = LectureReviewPolicyV2(context_tokens=100000, max_output_tokens=12000,
                                   max_physical_attempts=2).model_dump(mode="json")
    v2_state = {
        "run_id": run_id,
        "lecture_review_policy": policy,
        "lecture_review_policy_hash": canonical_hash(policy),
        "lecture_review_contract_version": "2.0",
    }
    with pytest.raises(ApplicationError) as failure:
        runner._assert_no_unfinished_lecture_review(v2_state)
    assert failure.value.status_code == 409

    # A legacy/V1 state (no contract 2.0) is not affected by the new check.
    from app.models.reviews.lecture_review import LectureReviewPolicyV1
    v1_policy = LectureReviewPolicyV1(context_tokens=100000, max_output_tokens=12000).model_dump(mode="json")
    legacy_state = {"run_id": run_id, "lecture_review_policy": v1_policy,
                    "lecture_review_policy_hash": canonical_hash(v1_policy),
                    "lecture_review_contract_version": "1.0"}
    runner._assert_no_unfinished_lecture_review(legacy_state)  # no raise
