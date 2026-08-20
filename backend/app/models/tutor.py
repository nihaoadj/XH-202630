"""Strict contracts for the evidence-grounded interactive Tutor subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TUTOR_SCHEMA_VERSION = "1.0"

TutorSourceType = Literal["resource", "run", "batch"]
TutorContextType = Literal["resource_help", "question_help"]
TutorSessionStatus = Literal["active", "closed", "failed"]
TutorGroundingStatus = Literal["grounded", "evidence_insufficient"]
TutorGroundingSource = Literal[
    "frozen_evidence",
    "source_refs",
    "fresh_retrieval",
    "none",
]
TutorPedagogyAction = Literal[
    "hint",
    "guided_question",
    "scaffold",
    "explanation",
    "check_understanding",
    "evidence_insufficient",
]


class StrictTutorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        protected_namespaces=(),
    )


class TutorSessionCreateRequest(StrictTutorModel):
    learner_id: str = Field(min_length=1, max_length=64)
    source_type: TutorSourceType
    resource_id: str | None = Field(default=None, min_length=1, max_length=128)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    batch_id: str | None = Field(default=None, min_length=1, max_length=128)
    context_type: TutorContextType
    question_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_source_and_context(self) -> "TutorSessionCreateRequest":
        if self.source_type == "resource" and self.resource_id is None:
            raise ValueError("resource source requires resource_id")
        if self.source_type == "run" and self.run_id is None:
            raise ValueError("run source requires run_id")
        if self.source_type == "batch" and self.batch_id is None:
            raise ValueError("batch source requires batch_id")
        if self.context_type == "question_help" and self.question_id is None:
            raise ValueError("question_help requires question_id")
        if self.context_type == "resource_help" and self.question_id is not None:
            raise ValueError("resource_help forbids question_id")
        return self


class TutorSession(StrictTutorModel):
    schema_version: Literal["1.0"] = TUTOR_SCHEMA_VERSION
    session_id: str = Field(min_length=1, max_length=128)
    learner_id: str = Field(min_length=1, max_length=64)
    source_type: TutorSourceType
    source_resource_id: str | None = Field(default=None, max_length=128)
    source_run_id: str | None = Field(default=None, max_length=128)
    source_batch_id: str | None = Field(default=None, max_length=128)
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    context_type: TutorContextType
    question_id: str | None = Field(default=None, max_length=128)
    skill_node_id: str | None = Field(default=None, max_length=128)
    path_node_id: str | None = Field(default=None, max_length=128)
    knowledge_point: str | None = Field(default=None, max_length=256)
    status: TutorSessionStatus = "active"
    current_hint_level: int = Field(default=0, ge=0, le=3)
    turn_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_session(self) -> "TutorSession":
        if (
            self.source_resource_id is None
            and self.source_run_id is None
            and self.source_batch_id is None
        ):
            raise ValueError(
                "source_resource_id, source_run_id, or source_batch_id is required"
            )
        if self.context_type == "question_help" and self.question_id is None:
            raise ValueError("question_help requires question_id")
        if self.status == "closed" and self.closed_at is None:
            raise ValueError("closed session requires closed_at")
        return self


class TutorTurnSubmitRequest(StrictTutorModel):
    client_message_id: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message cannot be blank")
        return value


class TutorEvidenceRef(StrictTutorModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    snippet: str = Field(min_length=1, max_length=4000)
    grounding_source: TutorGroundingSource
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    document_id: str | None = Field(default=None, max_length=128)
    document_version: str | None = Field(default=None, max_length=128)
    chunk_id: str | None = Field(default=None, max_length=128)
    source_path: str | None = Field(default=None, max_length=1024)
    section: str | None = Field(default=None, max_length=512)
    page: int | None = Field(default=None, ge=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class TutorTurn(StrictTutorModel):
    schema_version: Literal["1.0"] = TUTOR_SCHEMA_VERSION
    turn_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    client_message_id: str = Field(min_length=8, max_length=128)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_message: str = Field(min_length=1, max_length=4000)
    assistant_message: str = Field(min_length=1, max_length=12000)
    pedagogy_action: TutorPedagogyAction
    hint_level: int = Field(ge=0, le=3)
    follow_up_question: str | None = Field(default=None, max_length=4000)
    target_knowledge_points: list[str] = Field(default_factory=list, max_length=50)
    grounding_status: TutorGroundingStatus
    grounding_source: TutorGroundingSource
    evidence_refs: list[TutorEvidenceRef] = Field(default_factory=list, max_length=10)
    retrieval_query_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retrieval_status: str | None = Field(default=None, max_length=64)
    llm_call_id: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=128)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    llm_duration_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_grounding(self) -> "TutorTurn":
        if self.grounding_status == "grounded":
            if self.grounding_source == "none" or not self.evidence_refs:
                raise ValueError("grounded turn requires evidence refs")
        elif self.grounding_source != "none" or self.evidence_refs:
            raise ValueError("evidence_insufficient turn forbids evidence refs")
        return self


class TutorTurnResponse(StrictTutorModel):
    session_id: str
    turn_id: str
    sequence: int
    client_message_id: str
    user_message: str
    hint_level: int = Field(ge=0, le=3)
    pedagogy_action: TutorPedagogyAction
    message: str
    follow_up_question: str | None = None
    target_knowledge_points: list[str] = Field(default_factory=list)
    grounding_status: TutorGroundingStatus
    grounding_source: TutorGroundingSource
    source_refs: list[TutorEvidenceRef] = Field(default_factory=list)
    llm_call_id: str | None = None
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    llm_duration_ms: int | None = None
    error_code: str | None = None
    idempotent_replay: bool = False
    created_at: datetime

    @classmethod
    def from_turn(
        cls,
        turn: TutorTurn,
        *,
        idempotent_replay: bool = False,
    ) -> "TutorTurnResponse":
        return cls(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            sequence=turn.sequence,
            client_message_id=turn.client_message_id,
            user_message=turn.user_message,
            hint_level=turn.hint_level,
            pedagogy_action=turn.pedagogy_action,
            message=turn.assistant_message,
            follow_up_question=turn.follow_up_question,
            target_knowledge_points=turn.target_knowledge_points,
            grounding_status=turn.grounding_status,
            grounding_source=turn.grounding_source,
            source_refs=turn.evidence_refs,
            llm_call_id=turn.llm_call_id,
            model_name=turn.model_name,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            total_tokens=turn.total_tokens,
            llm_duration_ms=turn.llm_duration_ms,
            error_code=turn.error_code,
            idempotent_replay=idempotent_replay,
            created_at=turn.created_at,
        )


class TutorSessionDetail(StrictTutorModel):
    session: TutorSession
    turns: list[TutorTurnResponse] = Field(default_factory=list)


class TutorSessionListResponse(StrictTutorModel):
    learner_id: str
    total: int = Field(ge=0)
    sessions: list[TutorSession] = Field(default_factory=list)


class TutorLLMOutput(StrictTutorModel):
    pedagogy_action: Literal[
        "hint",
        "guided_question",
        "scaffold",
        "explanation",
        "check_understanding",
    ]
    answer_text: str = Field(min_length=1, max_length=12000)
    follow_up_question: str = Field(min_length=1, max_length=4000)
    target_knowledge_points: list[str] = Field(default_factory=list, max_length=50)
    cited_evidence_ids: list[str] = Field(min_length=1, max_length=10)

    @field_validator("cited_evidence_ids")
    @classmethod
    def unique_citations(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("cited_evidence_ids must be unique")
        return values


class TutorProfileProjection(StrictTutorModel):
    skill_level: str
    weak_points: list[str] = Field(default_factory=list, max_length=20)
    strong_points: list[str] = Field(default_factory=list, max_length=20)
    learning_goal: str
    learning_preferences: dict[str, Any] = Field(default_factory=dict)
    target_domain: str | None = None
    current_knowledge_state: dict[str, Any] | None = None


class TutorResourceContext(StrictTutorModel):
    resource_id: str
    run_id: str | None = None
    topic: str | None = None
    resource_type: str
    difficulty: str
    knowledge_points: list[str] = Field(default_factory=list, max_length=50)
    relevant_excerpt: str = Field(max_length=6000)


class TutorQuestionContext(StrictTutorModel):
    question_id: str
    question: str
    question_type: str
    options: list[str] = Field(default_factory=list, max_length=50)
    skill_node_id: str | None = None
    path_node_id: str | None = None
    knowledge_point: str | None = None
    difficulty: str | None = None


class TutorConversationItem(StrictTutorModel):
    sequence: int = Field(ge=1)
    user_message: str
    assistant_message: str
    hint_level: int = Field(ge=0, le=3)


class TutorAgentInput(StrictTutorModel):
    session_id: str
    turn_id: str
    learner_context: TutorProfileProjection
    resource_context: TutorResourceContext
    question_context: TutorQuestionContext | None = None
    evidence: list[TutorEvidenceRef] = Field(min_length=1, max_length=10)
    conversation_context: list[TutorConversationItem] = Field(default_factory=list, max_length=12)
    current_message: str
    hint_level: int = Field(ge=0, le=3)
    allowed_pedagogy_actions: list[str] = Field(min_length=1)


class TutorGroundingResolution(StrictTutorModel):
    status: TutorGroundingStatus
    source: TutorGroundingSource
    evidence: list[TutorEvidenceRef] = Field(default_factory=list, max_length=10)
    retrieval_query_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retrieval_status: str | None = None
