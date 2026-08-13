from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.audit.base import PersistenceConflict
from app.models.feedback_loop import (
    FeedbackContext,
    FeedbackDecision,
    FeedbackLoopResult,
    KnowledgeStateMutation,
    LearningAttempt,
    LearningPath,
    PathMutation,
    ProfileVersionRecord,
)


class FeedbackIdempotencyConflict(PersistenceConflict):
    pass


class LearnerProfileVersionConflict(PersistenceConflict):
    pass


class LearningPathMutationConflict(PersistenceConflict):
    pass


class BaseFeedbackLoopRepository(ABC):
    @abstractmethod
    def get_context(self, learner_id: str, knowledge_point_ids: list[str]) -> FeedbackContext:
        pass

    @abstractmethod
    def get_by_idempotency_key(
        self,
        learner_id: str,
        idempotency_key: str,
    ) -> FeedbackLoopResult | None:
        pass

    @abstractmethod
    def apply_feedback(
        self,
        *,
        attempt: LearningAttempt,
        decision: FeedbackDecision,
        state_mutations: list[KnowledgeStateMutation],
        learning_path: LearningPath,
        path_mutation: PathMutation,
        profile_version: ProfileVersionRecord,
        profile_patch: dict,
    ) -> FeedbackLoopResult:
        """Atomically apply all local learner-state facts."""

    @abstractmethod
    def attach_followup(
        self,
        *,
        attempt_id: str,
        decision_id: str,
        parent_run_id: str | None,
        child_run_id: str | None,
        trigger_type: str,
        status: str,
        error_code: str | None = None,
    ) -> FeedbackLoopResult:
        pass

    @abstractmethod
    def list_attempts(self, learner_id: str, limit: int = 20) -> list[LearningAttempt]:
        pass

    @abstractmethod
    def list_results(self, learner_id: str, limit: int = 20) -> list[FeedbackLoopResult]:
        """Return persisted feedback aggregates for reports and audit views."""
        pass

    @abstractmethod
    def get_current_path(self, learner_id: str) -> LearningPath | None:
        pass

    @abstractmethod
    def list_profile_versions(self, learner_id: str, limit: int = 20) -> list[ProfileVersionRecord]:
        pass

    @abstractmethod
    def get_followup_relation(self, child_run_id: str) -> dict | None:
        pass
