"""Persistence boundary for immutable P0-06 Claim audits."""

from abc import ABC, abstractmethod

from app.models.reviews.claims import ClaimJudgement, ClaimRecord


class BaseClaimRepository(ABC):
    def list_claims_by_runs(self, run_ids: list[str]) -> list[ClaimRecord]:
        return [claim for run_id in dict.fromkeys(run_ids) for claim in self.list_claims_by_run(run_id)]

    def list_judgements_by_runs(self, run_ids: list[str]) -> list[ClaimJudgement]:
        return [item for run_id in dict.fromkeys(run_ids) for item in self.list_judgements_by_run(run_id)]

    @abstractmethod
    def save_audit(self, claims: list[ClaimRecord], judgements: list[ClaimJudgement]) -> None:
        """Atomically persist Claims, judgements and frozen-Evidence bindings."""

    @abstractmethod
    def list_claims_by_run(self, run_id: str) -> list[ClaimRecord]:
        pass

    @abstractmethod
    def list_judgements_by_run(self, run_id: str) -> list[ClaimJudgement]:
        pass
