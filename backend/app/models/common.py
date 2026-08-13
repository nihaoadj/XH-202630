"""Small cross-domain models shared without creating import cycles."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    """Sanitized workflow error safe for API responses and audit storage."""

    code: str
    category: str
    message: str
    retryable: bool = False
    source: str
    attempt: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    safe_detail: Optional[str] = None

