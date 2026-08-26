"""Run the local courseware user-journey evidence without external services.

The API journey uses the real courseware router/repository contract and the
process suite starts an independent file-backed Worker.  This command only
aggregates those existing executable checks; it does not turn a mock into a
production claim or contact a model provider.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--basetemp", type=Path, default=Path("backend/.pytest-tmp/courseware-next-journey"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.basetemp.mkdir(parents=True, exist_ok=True)
    commands = [
        ("api_and_ai_first_generation", ["backend/tests/integration/courseware/test_api.py", "backend/tests/integration/courseware/test_ai_first_generation.py"]),
        ("browser_smoke", ["backend/tests/integration/courseware/test_browser_smoke.py"]),
        ("c1_process_fault_matrix", ["backend/tests/e2e/courseware/test_c1_process_fault_matrix.py"]),
        ("q5_local_user_journey", ["backend/tests/e2e/courseware/test_q5_local_user_journey.py"]),
    ]
    cases = []
    for index, (case_id, paths) in enumerate(commands):
        command = [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:cacheprovider",
                   f"--basetemp={args.basetemp / str(index)}"]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        cases.append({
            "case_id": case_id,
            "command": " ".join(command[3:]),
            "status": "passed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        })
    report = {
        "schema_version": "1.1",
        "required_case_ids": [item[0] for item in commands],
        "status": "LOCAL_READY" if all(item["status"] == "passed" for item in cases) else "PARTIAL",
        "external_services": "not_called",
        "topology": {"web": "courseware API test boundary", "worker": "independent process suite", "database": "file-backed SQLite in process suite"},
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
