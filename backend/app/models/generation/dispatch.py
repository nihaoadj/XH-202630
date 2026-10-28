"""Internal frozen text-dispatch contract; never part of the HTTP response."""
from dataclasses import dataclass
from typing import Any

TEXT_WORKFLOW_VERSION = "learning_documents.v1"
RESOURCE_RETRY_WORKFLOW_VERSION = "learning_documents.resource_retry.v1"


@dataclass(frozen=True)
class GenerationClaim:
    run_id: str
    owner: str
    epoch: int
    learner_id: str
    batch_id: str
    request_payload: dict[str, Any]
    snapshot: dict[str, Any]
    claim_count: int
