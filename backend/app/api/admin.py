"""Explicitly protected administrator-only runtime diagnostics."""

import hmac

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import ApplicationError, ErrorCode
from app.core.health import build_knowledge_base_health_report


router = APIRouter()


def _require_admin_health_token(supplied_token: str | None) -> None:
    expected_token = get_settings().admin_health_token.get_secret_value().strip()
    if not expected_token:
        raise ApplicationError(ErrorCode.ADMIN_HEALTH_DISABLED, status_code=404)
    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        raise ApplicationError(ErrorCode.ADMIN_UNAUTHORIZED, status_code=401)


@router.get("/knowledge-bases/health")
def knowledge_base_health(x_admin_token: str | None = Header(default=None)):
    """Return sanitized per-KB status; disabled unless an admin token is set."""
    _require_admin_health_token(x_admin_token)
    report = build_knowledge_base_health_report(get_settings())
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=report.model_dump(mode="json", exclude_none=True),
    )
