"""Explicitly protected administrator-only runtime diagnostics."""

import hmac

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import ApplicationError, ErrorCode
from app.core.health import build_knowledge_base_health_report


router = APIRouter()


def _require_admin_token(supplied_token: str | None) -> None:
    expected_token = get_settings().admin_health_token.get_secret_value().strip()
    if not expected_token:
        raise ApplicationError(ErrorCode.ADMIN_HEALTH_DISABLED, status_code=404)
    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        raise ApplicationError(ErrorCode.ADMIN_UNAUTHORIZED, status_code=401)


@router.get("/knowledge-bases/health")
def knowledge_base_health(
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    """Return sanitized per-KB status; disabled unless an admin token is set."""
    _require_admin_token(x_admin_token)
    catalog = request.app.container.knowledge_catalog()
    report = build_knowledge_base_health_report(
        get_settings(),
        index_status_provider=catalog.get_index_status,
    )
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=report.model_dump(mode="json", exclude_none=True),
    )


@router.post("/knowledge-bases/{knowledge_base_id}/reconcile")
def reconcile_knowledge_base(
    knowledge_base_id: str,
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    """Idempotently re-ingest one KB and reconcile SQL with its Chroma index."""
    _require_admin_token(x_admin_token)
    try:
        report = request.app.container.ingestion_service().reconcile(knowledge_base_id)
    except FileNotFoundError as exc:
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_BASE_MANIFEST_INVALID,
            status_code=404,
        ) from exc
    except ValueError as exc:
        raise ApplicationError(
            ErrorCode.KNOWLEDGE_BASE_MANIFEST_INVALID,
            status_code=422,
        ) from exc
    return JSONResponse(
        status_code=200 if report.status == "ready" else 503,
        content=report.model_dump(mode="json", exclude_none=True),
    )
