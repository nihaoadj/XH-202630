"""Print a sanitized runtime readiness report without changing user configuration."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"


def _print_report(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _configuration_error_code(error):
    text = str(error)
    known_codes = (
        "CFG_INVALID_APP_MODE",
        "CFG_INVALID_DB_TYPE",
        "CFG_DATABASE_URL_MISMATCH",
        "CFG_PRODUCTION_DEGRADED_FORBIDDEN",
        "CFG_PRODUCTION_EPHEMERAL_STORAGE",
        "CFG_LLM_API_KEY_MISSING",
        "CFG_LLM_API_KEY_PLACEHOLDER",
        "CFG_LLM_ENDPOINT_INVALID",
        "CFG_LLM_MODEL_MISSING",
        "CFG_EMBEDDING_MODEL_MISSING",
    )
    return next((code for code in known_codes if code in text), "INTERNAL_ERROR")


def main():
    if sys.version_info < (3, 11):
        _print_report({
            "status": "not_ready",
            "error_codes": ["CFG_UNSUPPORTED_PYTHON"],
        })
        return 1

    sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.config import Settings
        from app.core.health import build_health_report

        settings = Settings()
        report = build_health_report(settings, prepare_directories=False)
    except Exception as exc:
        _print_report({
            "status": "not_ready",
            "error_codes": [_configuration_error_code(exc)],
        })
        return 1

    _print_report(report.model_dump(mode="json", exclude_none=True))
    return {"ready": 0, "degraded": 2, "not_ready": 1}[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
