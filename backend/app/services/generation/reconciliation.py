"""One bounded reconciliation entry point for startup and durable workers."""
from datetime import datetime, timezone


class GenerationReconciler:
    def __init__(self, jobs, feedback, queued_timeout_seconds=1260, *, curriculum=None,
                 supplement_repository=None):
        self.jobs = jobs
        self.feedback = feedback
        self.queued_timeout_seconds = queued_timeout_seconds
        self.curriculum = curriculum
        # Optional: only a deployment that exposes Claim evidence retrieval has
        # in-flight sessions to reconcile when a run is interrupted.
        self.supplement_repository = supplement_repository

    def run_once(self):
        result = self.jobs.reconcile(queued_timeout_seconds=self.queued_timeout_seconds, limit=100)
        if self.supplement_repository is not None and result.get("failed_run_ids"):
            result["claim_evidence_interrupted"] = self.supplement_repository.interrupt_runs(
                result["failed_run_ids"], now=datetime.now(timezone.utc),
            )
        if hasattr(self.feedback, "reconcile_failed_generation_jobs"):
            result["feedback"] = self.feedback.reconcile_failed_generation_jobs(limit=100)
        else:
            result["feedback"] = self.feedback.reconcile_incomplete_followups(
                stale_child_run_ids=result["failed_run_ids"], error_code="GENERATION_JOB_INTERRUPTED")
        if self.curriculum is not None and hasattr(self.curriculum, "reconcile_failed_generations"):
            result["curriculum"] = self.curriculum.reconcile_failed_generations(limit=100)
        return result
