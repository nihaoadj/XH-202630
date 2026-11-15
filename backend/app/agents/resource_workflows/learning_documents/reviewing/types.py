"""Immutable static rules and per-request values; no registry or clients."""

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.models.reviews.review_audit import ReviewPolicySnapshotV1


@dataclass(frozen=True)
class PromptFragment:
    id: str
    version: str
    text: str


@dataclass(frozen=True)
class ReviewProfile:
    resource_type: str
    phase: str
    version: str
    fragments: tuple[PromptFragment, ...]
    allowed_specialties: tuple[PromptFragment, ...]
    output_schema: type[BaseModel]
    gateway_role: str
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class ReviewPromptBundle:
    resource_type: str
    phase: str
    profile_version: str
    system_text: str
    fragments: tuple[PromptFragment, ...]
    fingerprint: str


@dataclass(frozen=True)
class ReviewAuditInput:
    resource: Any = None
    evidence: tuple = ()
    difficulty: str | None = None
    constraints: Any = None
    scope_payload: Any = None
    policy: ReviewPolicySnapshotV1 | None = None


@dataclass(frozen=True)
class ReviewRequest:
    profile: ReviewProfile
    prompt_bundle: ReviewPromptBundle
    messages: tuple[BaseMessage, ...]
    resource_id: str | None
    max_output_tokens: int | None
    context_tokens: int | None = None
