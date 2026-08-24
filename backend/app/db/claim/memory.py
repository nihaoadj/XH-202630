from app.db.audit.base import PersistenceConflict
from app.db.claim.base import BaseClaimRepository
from app.models.reviews.claims import ClaimJudgement, ClaimRecord


class MemoryClaimRepository(BaseClaimRepository):
    def __init__(self) -> None:
        self._claims: dict[str, ClaimRecord] = {}
        self._judgements: dict[str, ClaimJudgement] = {}

    def save_audit(self, claims: list[ClaimRecord], judgements: list[ClaimJudgement]) -> None:
        claim_ids = {item.claim_id for item in claims}
        if any(item.claim_id not in claim_ids for item in judgements):
            raise PersistenceConflict("judgement references claim outside batch")
        for item in claims:
            existing = self._claims.get(item.claim_id)
            if existing and existing != item:
                raise PersistenceConflict("claim immutable payload conflict")
        for item in judgements:
            existing = self._judgements.get(item.judgement_id)
            if existing and existing != item:
                raise PersistenceConflict("judgement immutable payload conflict")
        self._claims.update({item.claim_id: item.model_copy(deep=True) for item in claims})
        self._judgements.update({item.judgement_id: item.model_copy(deep=True) for item in judgements})

    def list_claims_by_run(self, run_id: str) -> list[ClaimRecord]:
        return sorted(
            [item.model_copy(deep=True) for item in self._claims.values() if item.run_id == run_id],
            key=lambda item: (item.resource_id, item.resource_version, item.claim_index),
        )

    def list_judgements_by_run(self, run_id: str) -> list[ClaimJudgement]:
        return sorted(
            [item.model_copy(deep=True) for item in self._judgements.values() if item.run_id == run_id],
            key=lambda item: (item.resource_id, item.resource_version, item.claim_id),
        )
