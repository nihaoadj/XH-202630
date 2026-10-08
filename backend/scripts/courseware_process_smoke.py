"""Start one real Web process and one real durable Worker against one SQLite file."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _probe(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=1) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except Exception:
        return 0, {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    db_path = (args.root / "courseware-process-smoke.db").resolve()
    shutdown_file = (args.root / "worker.shutdown").resolve()
    web_port, worker_port = _free_port(), _free_port()
    repo_root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": str(repo_root / "backend"),
        "DB_TYPE": "sqlite",
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "COURSEWARE_AI_ENABLED": "false",
        "COURSEWARE_WORKER_HEALTH_HOST": "127.0.0.1",
        "COURSEWARE_WORKER_HEALTH_PORT": str(worker_port),
        "COURSEWARE_WORKER_POLL_SECONDS": "0.2",
    }
    web = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(web_port)],
        cwd=repo_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    worker: subprocess.Popen | None = None
    web_status = worker_live_status = worker_ready_status = 0
    worker_health: dict = {}
    try:
        # Let Web finish creating the shared SQLite schema before Worker
        # starts polling. This is still two independent processes, but avoids
        # turning an expected cold-start race into a false Worker failure.
        web_deadline = time.monotonic() + 25
        while time.monotonic() < web_deadline:
            web_status, _ = _probe(f"http://127.0.0.1:{web_port}/health")
            if web_status in {200, 503}:
                break
            time.sleep(0.2)
        worker = subprocess.Popen(
            [sys.executable, "backend/scripts/courseware_worker.py", "--health-port", str(worker_port), "--shutdown-file", str(shutdown_file)],
            cwd=repo_root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            web_status, _ = _probe(f"http://127.0.0.1:{web_port}/health")
            worker_live_status, _ = _probe(f"http://127.0.0.1:{worker_port}/health/live")
            worker_ready_status, worker_health = _probe(f"http://127.0.0.1:{worker_port}/health/ready")
            if web_status in {200, 503} and worker_live_status == 200 and worker_ready_status == 200:
                break
            time.sleep(0.2)
        worker_failures = int((worker_health.get("metrics") or {}).get("failed_count") or 0)
        passed = web_status in {200, 503} and worker_live_status == 200 and worker_ready_status == 200 and worker_failures == 0
        report = {
            "schema_version": "1.0", "status": "LOCAL_READY" if passed else "PARTIAL",
            "topology": {
                "web_process": {"pid": web.pid, "health_status": web_status},
                "worker_process": {"pid": worker.pid, "live_status": worker_live_status, "ready_status": worker_ready_status, "metrics": worker_health.get("metrics", {})},
                "same_sqlite_file": db_path.is_file(), "worker_concurrency_limit": 1,
                "horizontal_scaling_supported": False,
            },
            "external_deployment": "EXTERNAL_PENDING",
        }
    finally:
        shutdown_file.touch()
        if worker is not None:
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=10)
        if web.poll() is None:
            web.terminate()
            try:
                web.wait(timeout=10)
            except subprocess.TimeoutExpired:
                web.kill()
                web.wait(timeout=10)
        report["process_exit_codes"] = {"web": web.returncode, "worker": worker.returncode if worker is not None else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "web_pid": web.pid, "worker_pid": worker.pid}, ensure_ascii=False))
    return 0 if report["status"] == "LOCAL_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
