"""Call-local service graph for atomic round creation and feedback commits."""

from copy import copy

from app.db.shared.unit_of_work import SharedTransaction


class RoundUnitOfWork:
    def __init__(self, rounds, feedback, learners):
        self.original_rounds = rounds
        self.original_feedback = feedback
        self.original_learners = learners
        jobs = feedback.generation_job_service
        mastery = feedback.mastery_service
        self.transaction = SharedTransaction([
            rounds, learners, feedback.feedback_loop_repo, feedback.audit_repo,
            jobs.job_repo if jobs else None,
            mastery.repository if mastery else None,
            mastery.curriculum_repo if mastery else None,
            mastery.tier_progress_repo if mastery else None,
        ])

    def __enter__(self):
        self.transaction.__enter__()
        try:
            self.rounds = self.transaction.bind(self.original_rounds)
            self.learners = self.transaction.bind(self.original_learners)
            self.feedback = copy(self.original_feedback)
            self.feedback.feedback_loop_repo = self.transaction.bind(self.feedback.feedback_loop_repo)
            if self.feedback.audit_repo is not None:
                self.feedback.audit_repo = self.transaction.bind(self.feedback.audit_repo)
            if self.transaction.mode == "sql":
                for field in ("resource_repo", "knowledge_catalog", "tutor_repo"):
                    setattr(self.feedback, field, self.transaction.bind_reader(getattr(self.feedback, field, None)))
            mastery = self.feedback.mastery_service
            if mastery is not None:
                self.feedback.mastery_service = copy(mastery)
                bound = self.feedback.mastery_service
                for field in ("repository", "curriculum_repo", "tier_progress_repo"):
                    value = getattr(mastery, field)
                    if value is not None:
                        setattr(bound, field, self.transaction.bind(value))
                if self.transaction.mode == "sql":
                    # Resource/catalog reads see the same transaction snapshot.
                    for field in ("resource_repo",):
                        value = getattr(mastery, field)
                        if value is not None and hasattr(value, "session_factory"):
                            setattr(bound, field, self.transaction.bind_reader(value))
                    bound.knowledge_service = copy(mastery.knowledge_service)
                    catalog = getattr(bound.knowledge_service, "catalog", None)
                    if catalog is not None and hasattr(catalog, "session_factory"):
                        bound.knowledge_service.catalog = self.transaction.bind_reader(catalog)
            jobs = self.feedback.generation_job_service
            if jobs is not None:
                self.jobs = copy(jobs)
                self.jobs.job_repo = self.transaction.bind(jobs.job_repo)
                self.jobs.mastery_service = self.feedback.mastery_service
                self.jobs.generation_service = copy(jobs.generation_service)
                self.jobs.generation_service.audit_repo = self.feedback.audit_repo
                self.jobs._continuation_atomicity_active = True
                self.feedback.generation_job_service = self.jobs
            return self
        except BaseException as error:
            self.transaction.__exit__(type(error), error, error.__traceback__)
            raise

    def __exit__(self, *args):
        return self.transaction.__exit__(*args)
