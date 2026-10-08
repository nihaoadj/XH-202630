"""Print a read-only, sanitized database integrity preflight report."""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import get_engine  # noqa: E402
from app.db.integrity import inspect_database_integrity  # noqa: E402


def main() -> int:
    report = inspect_database_integrity(get_engine())
    blocking = bool(
        report.get("foreign_keys_enabled") is False
        or report.get("foreign_key_violations")
        or report.get("resource_version_duplicates")
        or report.get("resource_version_null_count")
        or report.get("resource_reference_orphans")
        or report.get("missing_resource_version_columns")
        or not report.get("resource_version_unique")
    )
    warnings = bool(report.get("missing_resource_foreign_keys"))
    report["status"] = "not_ready" if blocking else "degraded" if warnings else "ready"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if blocking else 2 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
