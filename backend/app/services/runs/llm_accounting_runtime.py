"""Optional per-process accounting runtime: bounded queue + writer subprocess.

Each Web / text-Worker / courseware-Worker host process owns at most one
writer child.  The producer side never blocks the business path:

* ``submit`` serializes an immutable whitelist snapshot, splits it into
  bounded chunk frames (60 KiB data + small header, final ``end`` frame
  < 4 KiB) and enqueues with ``put_nowait`` only;
* any failure (queue full, writer dead, serialization error) refuses the
  snapshot and degrades to a no-op - the business return/raise is untouched;
* startup/shutdown happens only at explicit application/Worker lifecycle
  points, never at first model call or DI resolution.

The child process imports only the independent accounting data layer; it
never initializes the business container or any model client.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import threading
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR, get_settings
from app.core.llm import accounting
from app.models.shared.llm_accounting import SegmentSubmissionV1

logger = logging.getLogger(__name__)

# Frozen IPC protocol guards (T41 §6.1).
MAX_CHUNK_BYTES = 60 * 1024
MAX_HEADER_BYTES = 4 * 1024
MAX_END_FRAME_BYTES = 4 * 1024
MAX_QUEUE_FRAMES = 512
MAX_INFLIGHT_BYTES = 32 * 1024 * 1024
CONSUMER_REASSEMBLY_MAX_BYTES = 32 * 1024 * 1024
CONSUMER_REASSEMBLY_MAX_SEGMENTS = 128
CONSUMER_IDLE_TIMEOUT_SECONDS = 300.0
WRITER_JOIN_BUDGET_SECONDS = 0.2


def resolve_llm_accounting_db_path() -> Path | None:
    """Resolve and validate the independent accounting database path.

    Returns ``None`` (accounting persistence disabled) when the resolved path
    collides with any business SQLite/知识库 file or the resource-artifact
    directory.  Business path/readiness is never modified.
    """

    settings = get_settings()
    configured = str(getattr(settings, "llm_accounting_db_path", "") or "").strip()
    if not configured:
        return None
    try:
        path = Path(configured)
        if not path.is_absolute():
            path = (BACKEND_DIR / path).resolve()
        else:
            path = path.resolve()
        forbidden: set[str] = set()
        database_url = str(settings.database_url or "")
        if database_url.startswith("sqlite:///"):
            suffix = database_url[len("sqlite:///"):]
            forbidden.add(str((Path(suffix) if Path(suffix).is_absolute() else (BACKEND_DIR / Path(suffix))).resolve()))
        for candidate in (
            Path("data/domain_knowledge.db"),
            Path("data/domain_knowledge_m3.db"),
            Path("data/domain_knowledge_writable_probe.db"),
        ):
            forbidden.add(str((BACKEND_DIR / candidate).resolve()))
        for name in ("vector_store_dir", "knowledge_base_dir"):
            protected = getattr(settings, name, None)
            if protected:
                root = Path(protected)
                root = (root if root.is_absolute() else BACKEND_DIR / root).resolve()
                if path.is_relative_to(root):
                    return None
        resolved = str(path)
        if resolved in forbidden:
            logger.warning("llm-accounting db path rejected: business database collision")
            return None
        resources_dir = Path(str(getattr(settings, "resources_dir", "") or "./data/generated_resources"))
        if not resources_dir.is_absolute():
            resources_dir = (BACKEND_DIR / resources_dir).resolve()
        try:
            path.relative_to(resources_dir)
            logger.warning("llm-accounting db path rejected: inside resource artifact directory")
            return None
        except ValueError:
            pass
        return path
    except Exception:
        logger.warning("llm-accounting db path resolution failed type=path_invalid")
        return None


class _NullPublisher:
    """No-op publisher used when the writer cannot be started."""

    def submit(self, submission: SegmentSubmissionV1) -> bool:
        return False


class _QueuePublisher:
    """Non-blocking producer: chunk frames + end frame, bounded budgets."""

    def __init__(self, queue: "multiprocessing.Queue", credit_queue: "multiprocessing.Queue"):
        self._queue = queue
        self._credit_queue = credit_queue
        self._inflight_bytes = 0
        self._inflight_lock = threading.Lock()
        self._closed = False
        self._collect_credits()

    def _collect_credits(self) -> None:
        """Return consumed-frame byte reservations to the budget."""

        try:
            while True:
                credit = self._credit_queue.get_nowait()
                with self._inflight_lock:
                    self._inflight_bytes = max(0, self._inflight_bytes - int(credit))
        except Exception:
            return

    def submit(self, submission: SegmentSubmissionV1) -> bool:
        if self._closed:
            return False
        try:
            self._collect_credits()
            segment = submission.segment
            payload = json.dumps(
                {
                    "segment": segment.stable_payload(),
                    "payload_hash": submission.payload_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            total_chunks = max(1, (len(payload) + MAX_CHUNK_BYTES - 1) // MAX_CHUNK_BYTES)
            chunks = [
                payload[index * MAX_CHUNK_BYTES : (index + 1) * MAX_CHUNK_BYTES]
                for index in range(total_chunks)
            ]
            frames: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks):
                frames.append(
                    {
                        "kind": "chunk",
                        "domain": segment.domain,
                        "run_id": segment.run_id,
                        "segment_id": segment.segment_id,
                        "seq": index + 1,
                        "total": total_chunks,
                        "payload": chunk,
                    }
                )
            frames.append(
                {
                    "kind": "end",
                    "domain": segment.domain,
                    "run_id": segment.run_id,
                    "segment_id": segment.segment_id,
                    "seq": total_chunks + 1,
                    "total": total_chunks,
                    "payload_hash": submission.payload_hash,
                    "call_count": segment.call_count,
                    "sealed": bool(segment.sealed),
                    "capacity_exceeded": bool(segment.capacity_exceeded),
                    "incomplete_count": len(segment.incomplete_reasons),
                }
            )
            frame_bytes = sum(len(frame.get("payload") or b"") + MAX_HEADER_BYTES for frame in frames)
            with self._inflight_lock:
                if self._inflight_bytes + frame_bytes > MAX_INFLIGHT_BYTES:
                    return False
                if self._queue.qsize() + len(frames) > MAX_QUEUE_FRAMES:
                    return False
                reserved = True
                self._inflight_bytes += frame_bytes
            try:
                for frame in frames:
                    self._queue.put_nowait(frame)
            except Exception:
                with self._inflight_lock:
                    self._inflight_bytes = max(0, self._inflight_bytes - frame_bytes)
                return False
            return True
        except Exception:
            logger.warning("llm-accounting publisher submit failed type=ipc_submit")
            return False

    def close(self) -> None:
        self._closed = True


def _writer_main(
    queue: "multiprocessing.Queue",
    credit_queue: "multiprocessing.Queue",
    db_path: str,
) -> None:
    """Writer child: reassemble frames and persist in short transactions.

    Never touches business models, services or containers.  Failures only
    affect accounting availability; no callback into the parent business path.
    """

    import time

    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository
    from app.models.shared.llm_accounting import AccountingSegmentV1, SegmentSubmissionV1

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("llm-accounting-writer")
    try:
        repository = SQLLLMAccountingRepository(db_path)
    except Exception:
        log.warning("llm-accounting writer repository init failed type=storage_init")
        return

    reassembly: dict[tuple[str, str, str], dict[str, Any]] = {}
    reassembly_bytes = 0
    last_activity = time.monotonic()

    def _abandon(key: tuple[str, str, str]) -> None:
        nonlocal reassembly_bytes
        buffer = reassembly.pop(key, None)
        if buffer:
            reassembly_bytes = max(0, reassembly_bytes - buffer.get("bytes", 0))

    def _persist(key: tuple[str, str, str]) -> None:
        nonlocal reassembly_bytes
        buffer = reassembly.pop(key, None)
        if not buffer:
            return
        reassembly_bytes = max(0, reassembly_bytes - buffer.get("bytes", 0))
        if not buffer.get("end_received"):
            return
        try:
            chunks = [buffer["chunks"][index] for index in range(1, buffer["total"] + 1)]
            if any(chunk is None for chunk in chunks):
                log.warning("llm-accounting segment incomplete type=missing_chunk")
                return
            payload = b"".join(chunks)
            data = json.loads(payload.decode("utf-8"))
            segment = AccountingSegmentV1.model_validate(data["segment"])
            expected_hash = str(data.get("payload_hash") or buffer.get("payload_hash"))
            from app.models.shared.llm_accounting import canonical_accounting_hash

            if (expected_hash != canonical_accounting_hash(segment.stable_payload())
                    or expected_hash != buffer.get("payload_hash")
                    or segment.call_count != buffer.get("call_count")
                    or segment.call_count != len(segment.calls)) :
                log.warning("llm-accounting segment hash mismatch type=integrity")
                return
            submission = SegmentSubmissionV1(segment=segment, payload_hash=expected_hash)
            repository.save_segment(submission)
        except Exception:
            log.warning("llm-accounting writer persist failed type=storage_write")

    while True:
        try:
            frame = queue.get(timeout=1.0)
        except Exception:
            if not reassembly:
                continue
            if time.monotonic() - last_activity > CONSUMER_IDLE_TIMEOUT_SECONDS:
                for key in list(reassembly):
                    _abandon(key)
            continue
        last_activity = time.monotonic()
        try:
            kind = frame.get("kind")
            credit = int(len(frame.get("payload") or b"") + MAX_HEADER_BYTES)
            try:
                credit_queue.put_nowait(credit)
            except Exception:
                pass
            if kind == "stop":
                for key in list(reassembly):
                    _abandon(key)
                repository.close()
                return
            key = (
                str(frame.get("domain")),
                str(frame.get("run_id")),
                str(frame.get("segment_id")),
            )
            if kind == "end":
                buffer = reassembly.get(key)
                if buffer is None:
                    # Chunks may have been dropped; the end alone cannot
                    # fabricate a complete segment.
                    continue
                if int(frame.get("total") or 0) != buffer["total"]:
                    _abandon(key)
                    continue
                buffer["end_received"] = True
                buffer["call_count"] = frame.get("call_count")
                buffer["payload_hash"] = str(frame.get("payload_hash") or "")
                buffer["sealed"] = bool(frame.get("sealed"))
                _persist(key)
                continue
            if kind != "chunk":
                continue
            chunk = frame.get("payload")
            if not isinstance(chunk, (bytes, bytearray)):
                continue
            chunk = bytes(chunk)
            buffer = reassembly.get(key)
            if buffer is None:
                if len(reassembly) >= CONSUMER_REASSEMBLY_MAX_SEGMENTS:
                    continue
                if reassembly_bytes + len(chunk) > CONSUMER_REASSEMBLY_MAX_BYTES:
                    continue
                buffer = {"chunks": {}, "total": int(frame.get("total") or 0), "bytes": 0}
                reassembly[key] = buffer
            if buffer["bytes"] + len(chunk) > 8 * 1024 * 1024:
                _abandon(key)
                continue
            ordinal = int(frame.get("seq") or 0)
            if not 1 <= ordinal <= buffer["total"]:
                _abandon(key)
                continue
            previous = buffer["chunks"].get(ordinal)
            if previous is not None:
                if previous != chunk:
                    _abandon(key)
                continue
            if reassembly_bytes + len(chunk) > CONSUMER_REASSEMBLY_MAX_BYTES:
                _abandon(key)
                continue
            buffer["chunks"][ordinal] = chunk
            buffer["bytes"] += len(chunk)
            reassembly_bytes += len(chunk)
        except Exception:
            log.warning("llm-accounting writer frame failed type=consumer_frame")


class LLMAccountingRuntime:
    """One optional accounting runtime per host process."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._context = multiprocessing.get_context("spawn")
        self._queue: "multiprocessing.Queue" = self._context.Queue(maxsize=MAX_QUEUE_FRAMES)
        self._credit_queue: "multiprocessing.Queue" = self._context.Queue()
        self._process = None
        self._publisher: _QueuePublisher | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> bool:
        if self._started:
            return True
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._process = self._context.Process(
                target=_writer_main,
                args=(self._queue, self._credit_queue, str(self.db_path)),
                name="llm-accounting-writer",
                daemon=True,
            )
            self._process.start()
            self._publisher = _QueuePublisher(self._queue, self._credit_queue)
            accounting.install_publisher(self._publisher)
            self._started = True
            logger.info("llm-accounting writer started pid=%s", self._process.pid)
            return True
        except Exception:
            logger.warning("llm-accounting writer start failed type=runtime_start")
            accounting.install_publisher(_NullPublisher())
            self._started = False
            return False

    def stop(self) -> None:
        if not self._started:
            return
        publisher = self._publisher
        if publisher is not None:
            publisher.close()
        accounting.install_publisher(None)
        process = self._process
        try:
            self._queue.put_nowait({"kind": "stop"})
        except Exception:
            pass
        try:
            # Prevent the feeder thread from deadlocking host shutdown.
            self._queue.cancel_join_thread()
        except Exception:
            pass
        if process is not None and process.is_alive():
            process.join(timeout=WRITER_JOIN_BUDGET_SECONDS)
            if process.is_alive():
                try:
                    process.terminate()
                except Exception:
                    pass
        self._started = False


_RUNTIME: LLMAccountingRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def start_llm_accounting_runtime() -> LLMAccountingRuntime | None:
    """Start the optional writer child; failures leave a no-op publisher."""

    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is not None and _RUNTIME.started:
            return _RUNTIME
        settings = get_settings()
        if not bool(getattr(settings, "llm_accounting_enabled", True)):
            return None
        path = resolve_llm_accounting_db_path()
        if path is None:
            accounting.install_publisher(_NullPublisher())
            return None
        runtime = LLMAccountingRuntime(path)
        if runtime.start():
            _RUNTIME = runtime
            return runtime
        return None


def stop_llm_accounting_runtime() -> None:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            return
        runtime = _RUNTIME
        _RUNTIME = None
    runtime.stop()


def current_runtime() -> LLMAccountingRuntime | None:
    return _RUNTIME


__all__ = [
    "LLMAccountingRuntime",
    "resolve_llm_accounting_db_path",
    "start_llm_accounting_runtime",
    "stop_llm_accounting_runtime",
    "current_runtime",
]
