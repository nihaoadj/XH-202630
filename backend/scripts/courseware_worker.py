"""Run the durable interactive-courseware Worker as a separate process."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.containers import init_container


def _health_server(executor, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler contract
            snapshot = executor.health_snapshot()
            if self.path == "/health/live":
                status = 200 if snapshot["live"] else 503
                body = {"live": snapshot["live"], "status": snapshot["status"]}
            elif self.path == "/health/ready":
                status = 200 if snapshot["ready"] else 503
                body = snapshot
            elif self.path == "/metrics":
                status = 200
                body = snapshot
            else:
                status = 404
                body = {"code": "NOT_FOUND"}
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format, *_args):
            # Health probes must not add noisy request lines or client details
            # to the Worker log.
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the single-concurrency durable courseware Worker")
    parser.add_argument("--health-host", default=os.getenv("COURSEWARE_WORKER_HEALTH_HOST", "127.0.0.1"))
    parser.add_argument("--health-port", type=int, default=int(os.getenv("COURSEWARE_WORKER_HEALTH_PORT", "8081")))
    parser.add_argument("--once", action="store_true", help="claim at most one configured batch and exit")
    parser.add_argument("--shutdown-file", type=Path,
                        help="optional local orchestration sentinel; its creation requests graceful shutdown")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    container = init_container()
    executor = container.courseware_executor()
    server: ThreadingHTTPServer | None = None

    def stop(_signum, _frame):
        executor.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    # Windows control-break is the process-group equivalent of a terminal
    # graceful-shutdown request.  It is intentionally handled separately from
    # TerminateProcess, which cannot give a durable worker a chance to finish
    # its current lease boundary.
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    if args.once:
        result = executor.run_once()
        logging.info("courseware worker one-shot claimed=%s processed=%s failed=%s", result["claimed"], result["processed"], result["failed"])
        return 0 if result["failed"] == 0 else 1

    server = _health_server(executor, args.health_host, args.health_port)
    server_thread = threading.Thread(target=server.serve_forever, name="courseware-worker-health", daemon=True)
    server_thread.start()
    shutdown_watcher: threading.Thread | None = None
    if args.shutdown_file:
        shutdown_path = args.shutdown_file

        def watch_shutdown_file() -> None:
            while not executor._stop.wait(0.05):
                if shutdown_path.exists():
                    logging.info("courseware worker graceful shutdown requested by local sentinel")
                    executor.stop()
                    return

        shutdown_watcher = threading.Thread(target=watch_shutdown_file, name="courseware-worker-shutdown", daemon=True)
        shutdown_watcher.start()
    logging.info("courseware worker health listening host=%s port=%s", args.health_host, args.health_port)
    try:
        executor.run_forever()
        return 0
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        if shutdown_watcher:
            shutdown_watcher.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
