"""Run the single SQLite text-generation consumer outside the Web process."""
import argparse
import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.containers import init_container
from app.core.health import build_health_report
from app.core.worker_lock import WorkerProcessLock
from app.db.shared.database import get_engine, init_database
from app.services.generation.worker import GenerationWorker


def health_server(worker, host, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            state = worker.health_snapshot()
            if self.path not in {"/health/live", "/health/ready", "/metrics"}:
                code, state = 404, {"code": "NOT_FOUND"}
            else:
                code = 200 if self.path == "/metrics" or state["live" if self.path.endswith("live") else "ready"] else 503
            body = json.dumps(state).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            return
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--health-host", default="127.0.0.1")
    parser.add_argument("--health-port", type=int, default=8082)
    parser.add_argument("--shutdown-file", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if settings.db_type != "sqlite" or get_engine().url.database in {None, ":memory:"}:
        logging.error("GENERATION_WORKER_REQUIRES_PERSISTENT_SQLITE")
        return 2
    try:
        with WorkerProcessLock(str(get_engine().url.database) + ".generation-worker.lock"):
            init_database()
            container = init_container()
            worker = GenerationWorker(container.generation_job_repository(), container.feedback_loop_repository(),
                container.generation_job_service, lease_seconds=settings.workflow_run_lease_seconds,
                poll_seconds=settings.generation_worker_poll_seconds,
                shutdown_seconds=settings.generation_worker_shutdown_seconds,
                queued_timeout_seconds=settings.generation_queue_timeout_seconds,
                curriculum=container.curriculum_repository(),
                ready=lambda: build_health_report(settings).status != "not_ready")
            for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                if hasattr(signal, name):
                    signal.signal(getattr(signal, name), lambda *_: worker.stop())
            if args.once:
                result = worker.run_once()
                logging.info("Generation worker once claimed=%s processed=%s failed=%s", *result.values())
                return 0 if not result["failed"] else 1
            server = health_server(worker, args.health_host, args.health_port)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            if args.shutdown_file:
                def shutdown_watch():
                    while not worker._stop.wait(0.1):
                        if args.shutdown_file.exists():
                            worker.stop()
                threading.Thread(target=shutdown_watch, daemon=True).start()
            try:
                worker.run_forever()
            finally:
                server.shutdown()
                server.server_close()
        return 0
    except RuntimeError as exc:
        if str(exc) == "GENERATION_WORKER_ALREADY_RUNNING":
            logging.error("GENERATION_WORKER_ALREADY_RUNNING")
            return 2
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
