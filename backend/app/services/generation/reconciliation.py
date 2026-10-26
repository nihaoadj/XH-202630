"""One bounded reconciliation entry point for startup and durable workers."""
class GenerationReconciler:
    def __init__(self, jobs, feedback, queued_timeout_seconds=1260, *, curriculum=None):
        self.jobs = jobs
        self.feedback = feedback
        self.queued_timeout_seconds = queued_timeout_seconds
        self.curriculum = curriculum

    def run_once(self):
        result = self.jobs.reconcile(queued_timeout_seconds=self.queued_timeout_seconds, limit=100)
        if hasattr(self.feedback, "reconcile_failed_generation_jobs"):
            result["feedback"] = self.feedback.reconcile_failed_generation_jobs(limit=100)
        else:
            result["feedback"] = self.feedback.reconcile_incomplete_followups(
                stale_child_run_ids=result["failed_run_ids"], error_code="GENERATION_JOB_INTERRUPTED")
        if self.curriculum is not None and hasattr(self.curriculum, "reconcile_failed_generations"):
            result["curriculum"] = self.curriculum.reconcile_failed_generations(limit=100)
        return result
