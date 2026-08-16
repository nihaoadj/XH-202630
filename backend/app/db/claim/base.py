"""Persistence boundary for immutable P0-06 Claim audits."""

from abc import ABC, abstractmethod

from app.models.claims import ClaimJudgement, ClaimRecord


class BaseClaimRepository(ABC):
    @abstractmethod
    def save_audit(self, claims: list[ClaimRecord], judgements: list[ClaimJudgement]) -> None:
        """Atomically persist Claims, judgements and frozen-Evidence bindings."""

    @abstractmethod
    def list_claims_by_run(self, run_id: str) -> list[ClaimRecord]:
        pass

    @abstractmethod
    def list_judgements_by_run(self, run_id: str) -> list[ClaimJudgement]:
        pass
