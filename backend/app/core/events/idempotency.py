"""Pure event identity helpers shared by workflow boundaries."""

from __future__ import annotations

from typing import Any, Mapping

from app.models.shared.persistence import canonical_hash


def idempotency_key(namespace: str, payload: Mapping[str, Any]) -> str:
    """Return a stable key for one logical operation and its input payload."""

    return f"{namespace}:{canonical_hash(dict(payload))}"


def event_id(namespace: str, payload: Mapping[str, Any]) -> str:
    """Return a compact deterministic event identifier."""

    return f"evt_{idempotency_key(namespace, payload).split(':', 1)[1][:32]}"


__all__ = ["event_id", "idempotency_key"]
