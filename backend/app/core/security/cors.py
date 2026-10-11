"""Credentialed CORS allows configured origins and local development ports."""

from typing import Any

from app.config import Settings


def cors_options(settings: Settings) -> dict[str, Any]:
    return {
        "allow_origins": settings.cors_allow_origins,
        "allow_origin_regex": (
            r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?"
            if settings.app_mode != "production" else None
        ),
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        "allow_headers": ["Authorization", "Content-Type", "Last-Event-ID", "If-None-Match", "X-Admin-Token"],
        "expose_headers": ["ETag"],
    }
