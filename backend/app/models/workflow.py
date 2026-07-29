"""Versioned workflow state and execution semantics for the Agent graph."""

from __future__ import annotations

import operator
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.common import ErrorInfo
from app.models.knowledge import EvidenceItem, RetrievalStatus
from app.models.schemas import LearnerProfile, LearningResource


WORKFLOW_SCHEMA_VERSION = "1.0"


class StepStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    RETRYABLE_ERROR = "retryable_error"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"


class ReviewDecision(str, Enum):
    NOT_REQUESTED = "not_requested"
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"
    HUMAN_REVIEW = "human_review"


class ClaimCheckStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ResourceStatus(str, Enum):
    DRAFT = "draft"
    UNREVIEWED_DRAFT = "unreviewed_draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    HUMAN_REVIEW = "human_review"


class WorkflowConstraints(BaseModel):
    """Known generation constraints while preserving additive client extensions."""

    model_config = ConfigDict(extra="allow")

    must_include_citations: bool = False
    language: Optional[str] = None
    max_length: Optional[int] = Field(default=None, ge=1)


class WorkflowState(TypedDict, total=False):
    """LangGraph channels for the complete GenerateRequest contract."""

    schema_version: Literal["1.0"]
    run_id: str
    learner_id: str
    learner: LearnerProfile
    topic: str
    knowledge_base_id: Optional[str]
    diagnostic_result_id: Optional[str]
    target_skill_nodes: List[str]
    resource_types: List[str]
    difficulty_preference: Optional[str]
    generation_mode: str
    include_review: bool
    include_claim_check: bool
    max_iterations: int
    constraints: Dict[str, Any]

    workflow_status: str
    current_node: str
    generation_attempt: int
    revision_count: int
    workflow_started_at: datetime
    workflow_deadline_at: datetime
    claim_check_status: str
    retrieval_status: str
    retrieval_config_hash: Optional[str]
    retrieval_query_hashes: List[str]
    retrieval_candidate_count: int
    retrieval_dropped_candidate_count: int
    retrieval_partial_failure_count: int

    diagnosis: Dict[str, Any]
    retrieved_evidence: List[EvidenceItem]
    # Compatibility projection retained for P0-02 callers. It is never accepted
    # as factual evidence by the P0-03 generation path.
    retrieved_chunks: List[Dict[str, Any]]
    learning_plan: Dict[str, Any]
    generated_resources: List[LearningResource]
    review_result: Dict[str, Any]
    final_decision: str

    trace: Annotated[List[Dict[str, Any]], operator.add]
    errors: Annotated[List[Dict[str, Any]], operator.add]

    # Compatibility alias retained while callers migrate to generation_attempt.
    iteration: int


class WorkflowStateSnapshot(BaseModel):
    """Validated, JSON-serializable snapshot used at the workflow boundary."""

    schema_version: Literal["1.0"] = WORKFLOW_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    learner_id: str = Field(min_length=1)
    learner: LearnerProfile
    topic: str = Field(min_length=1)
    knowledge_base_id: Optional[str] = None
    diagnostic_result_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    resource_types: List[str] = Field(min_length=1)
    difficulty_preference: Optional[str] = None
    generation_mode: Literal["draft", "standard", "strict"] = "standard"
    include_review: bool = True
    include_claim_check: bool = False
    max_iterations: int = Field(default=2, ge=0, le=3)
    constraints: Dict[str, Any] = Field(default_factory=dict)

    workflow_status: WorkflowStatus = WorkflowStatus.RUNNING
    current_node: str = "pending"
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)
    workflow_started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workflow_deadline_at: datetime
    claim_check_status: ClaimCheckStatus = ClaimCheckStatus.NOT_REQUESTED
    retrieval_status: RetrievalStatus = RetrievalStatus.PENDING
    retrieval_config_hash: Optional[str] = None
    retrieval_query_hashes: List[str] = Field(default_factory=list)
    retrieval_candidate_count: int = Field(default=0, ge=0)
    retrieval_dropped_candidate_count: int = Field(default=0, ge=0)
    retrieval_partial_failure_count: int = Field(default=0, ge=0)

    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    retrieved_evidence: List[EvidenceItem] = Field(default_factory=list)
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    learning_plan: Dict[str, Any] = Field(default_factory=dict)
    generated_resources: List[LearningResource] = Field(default_factory=list)
    review_result: Dict[str, Any] = Field(default_factory=dict)
    final_decision: str = ""
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[ErrorInfo] = Field(default_factory=list)
    iteration: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_invariants(self) -> "WorkflowStateSnapshot":
        if self.learner_id != self.learner.learner_id:
            raise ValueError("learner_id must match learner.learner_id")
        if self.revision_count > self.max_iterations:
            raise ValueError("revision_count cannot exceed max_iterations")
        if self.generation_attempt != self.revision_count + 1:
            raise ValueError("generation_attempt must equal revision_count + 1")
        return self

    def as_state(self) -> WorkflowState:
        payload = self.model_dump(mode="python")
        # LangGraph keeps these runtime values in-process; preserve typed models for
        # existing node code while normalizing public enum channels to strings.
        payload["learner"] = self.learner
        payload["generated_resources"] = self.generated_resources
        payload["workflow_status"] = self.workflow_status.value
        payload["claim_check_status"] = self.claim_check_status.value
        payload["retrieval_status"] = self.retrieval_status.value
        return payload  # type: ignore[return-value]
