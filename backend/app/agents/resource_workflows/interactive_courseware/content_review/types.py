"""Immutable execution values, separate from the Pydantic wire contracts."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptFragment:
    id: str
    version: str
    text: str


@dataclass(frozen=True)
class ReviewProfile:
    id: str
    version: str
    schema: type
    role: str
    fragments: tuple[PromptFragment, ...]


@dataclass(frozen=True)
class ReviewBatch:
    batch_id: str
    identity: str
    value_hash: str
    items: tuple[Any, ...]
    evidence: tuple[Any, ...]
    messages: tuple[Any, ...]
    input_tokens: int
    output_tokens: int
