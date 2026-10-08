"""Exercise feedback persistence across two real Uvicorn process lifecycles."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db.database import (  # noqa: E402
    get_engine,
    get_session_factory,
    init_database,
)
from app.db.learner.sql_repository import SQLLearnerRepository  # noqa: E402
from app.db.models import KnowledgeBaseORM, RagSkillNodeORM  # noqa: E402
from app.db.resource.sql_repository import SQLResourceRepository  # noqa: E402
from app.models.schemas import LearnerProfile, LearningResource  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> tuple[int, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8")
        return exc.code, json.loads(response_body) if response_body else None


def _wait_until_started(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"UVICORN_EXITED_EARLY:{process.returncode}")
        try:
            status, _ = _request_json(f"{base_url}/", timeout=1)
            if status == 200:
                return
        except (OSError, TimeoutError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise RuntimeError("UVICORN_START_TIMEOUT")


def _start_server(environment: dict[str, str], port: int) -> subprocess.Popen:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_DIR,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        creationflags=creation_flags,
    )
    _wait_until_started(f"http://127.0.0.1:{port}", process)
    return process


def _stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _configure_isolated_runtime(output_dir: Path) -> dict[str, str]:
    database_path = output_dir / "feedback-process-restart.db"
    environment = os.environ.copy()
    environment.update({
        "DB_TYPE": "sqlite",
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "APP_MODE": "development",
        "ALLOW_DEGRADED_GENERATION": "true",
        "LLM_API_KEY": "",
        "RERANK_ENABLED": "false",
        "VECTOR_STORE_DIR": str(output_dir / "chroma"),
        "RESOURCES_DIR": str(output_dir / "resources"),
    })
    os.environ.update({key: value for key, value in environment.items() if key in {
        "DB_TYPE",
        "DATABASE_URL",
        "APP_MODE",
        "ALLOW_DEGRADED_GENERATION",
        "LLM_API_KEY",
        "RERANK_ENABLED",
        "VECTOR_STORE_DIR",
        "RESOURCES_DIR",
    }})
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return environment


def _seed_database() -> None:
    init_database()
    factory = get_session_factory()
    with factory() as db:
        db.add(KnowledgeBaseORM(
            knowledge_base_id="process-restart-kb",
            name="Process restart KB",
            version="1.0",
        ))
        db.add(RagSkillNodeORM(
            node_id="process-restart-skill",
            knowledge_base_id="process-restart-kb",
            name="Process restart skill",
            level="beginner",
        ))
        db.commit()
    learners = SQLLearnerRepository(factory)
    learners.save(LearnerProfile(
        learner_id="process-restart-learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="process-restart-kb",
        learning_goal="验证真实进程重启",
    ))
    SQLResourceRepository(factory).save(LearningResource(
        resource_id="process-restart-resource",
        learner_id="process-restart-learner",
        topic="检索",
        resource_type="测试题",
        difficulty="初级",
        content_text="process restart exercise",
        knowledge_points=["process-restart-skill"],
        source_refs=[],
        publication_status="published",
    ), "process-restart-learner", "检索")
    get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output_dir = (
        args.output_dir or Path(tempfile.mkdtemp(prefix="xh-feedback-restart-"))
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / "feedback-process-restart.db"
    if database_path.exists():
        database_path.unlink()

    environment = _configure_isolated_runtime(output_dir)
    _seed_database()
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = None
    payload = {
        "learner_id": "process-restart-learner",
        "source_resource_id": "process-restart-resource",
        "source_resource_version": 1,
        "idempotency_key": "process-restart-idempotency",
        "expected_profile_version": 1,
        "submitted_at": datetime(2026, 8, 15, tzinfo=timezone.utc).isoformat(),
        "knowledge_point_results": [{
            "knowledge_point_id": "process-restart-skill",
            "question_ids": ["question-1"],
            "correct_count": 7,
            "total_count": 10,
        }],
    }
    report: dict[str, Any] = {
        "rehearsal_type": "feedback_real_uvicorn_process_restart",
        "database": str(database_path),
        "configured_application_database_touched": False,
    }
    try:
        process = _start_server(environment, port)
        status, submitted = _request_json(
            f"{base_url}/api/feedback/attempts",
            method="POST",
            payload=payload,
        )
        if status != 200:
            raise RuntimeError(f"FEEDBACK_SUBMIT_FAILED:{status}:{submitted}")
        report["before_restart"] = {
            "process_id": process.pid,
            "attempt_id": submitted["attempt"]["attempt_id"],
            "profile_version": submitted["profile_version"],
            "decision": submitted["decision"]["action"],
            "followup_generation_status": submitted["followup_generation_status"],
        }
        _stop_server(process)
        process = None

        process = _start_server(environment, port)
        checks = {}
        endpoints = {
            "profile": "/api/profiles/process-restart-learner",
            "attempts": "/api/feedback/attempts/process-restart-learner",
            "path": "/api/feedback/path/process-restart-learner",
            "report": "/api/report/process-restart-learner",
            "learning_history": "/api/learning-history/process-restart-learner/timeline",
        }
        responses = {}
        for name, endpoint in endpoints.items():
            endpoint_status, body = _request_json(base_url + endpoint)
            checks[name] = endpoint_status == 200
            responses[name] = body
        attempt_id = submitted["attempt"]["attempt_id"]
        checks.update({
            "profile_version_persisted": responses["profile"]["profile_version"] == 2,
            "mastery_persisted": (
                responses["profile"]["knowledge_states"]["process-restart-skill"]["score"]
                == 0.7
            ),
            "single_attempt_persisted": (
                len(responses["attempts"]) == 1
                and responses["attempts"][0]["attempt_id"] == attempt_id
            ),
            "report_reads_attempt": attempt_id in json.dumps(responses["report"]),
            "history_reads_profile": (
                responses["learning_history"]["learner_id"] == "process-restart-learner"
            ),
        })
        replay_status, replay = _request_json(
            f"{base_url}/api/feedback/attempts",
            method="POST",
            payload=payload,
        )
        checks["idempotent_http_replay"] = (
            replay_status == 200
            and replay["idempotent_replay"] is True
            and replay["attempt"]["attempt_id"] == attempt_id
            and replay["profile_version"] == 2
        )
        report["after_restart"] = {
            "process_id": process.pid,
            "checks": checks,
            "attempt_count": len(responses["attempts"]),
            "profile_version": responses["profile"]["profile_version"],
        }
        report["status"] = "passed" if all(checks.values()) else "failed"
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)
        if process is not None:
            _stop_server(process)
            output = process.stdout.read() if process.stdout else ""
            report["server_log_tail"] = output[-6000:]
            process = None
    finally:
        _stop_server(process)

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
