"""T37 acceptance budget: at most three lecture generations, reserved up front.

A slot counts as consumed the moment it is reserved. Submission failures,
timeouts, crashes and unknown usage never refund it, and a terminated slot can
never be replayed. The file is the single source of truth for the quota, so
changing the path is not a way to obtain more generations.

``live_lecture_claim_once`` holds ``budget_lock`` for the whole
reserve -> run -> settle window, so two processes cannot run two slots at the
same time. A crash therefore leaves the lock file behind on purpose: its
presence means a human must first confirm no worker survived.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

VERSION = "t37-acceptance-budget-1.0"
PLAN_ID = "T37"
MAX_GENERATIONS = 3
SLOT_STATES = ("unused", "reserved", "running", "completed", "failed", "unknown")


class BudgetError(Exception):
    """Budget contract violation; callers must stop without creating a job."""


class BudgetLocked(BudgetError):
    """Another process holds the acceptance lock; never steal or rebuild it."""


class BudgetExhausted(BudgetError):
    """The requested slot is not available; quota is never refunded."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_slots(max_generations=MAX_GENERATIONS) -> dict:
    return {str(index): {"state": "unused", "reserved_at": None, "run_id": None,
                         "settled_at": None, "outcome": None}
            for index in range(1, max_generations + 1)}


def lock_path(path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


def load(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise BudgetError(f"acceptance budget missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    cap = data.get("max_generations")
    if data.get("plan_id") != PLAN_ID or type(cap) is not int or not 1 <= cap <= MAX_GENERATIONS:
        raise BudgetError("acceptance budget identity mismatch")
    if set(data.get("slots", {})) != {str(i) for i in range(1, cap + 1)}:
        raise BudgetError("acceptance budget slot set mismatch")
    for key, entry in data["slots"].items():
        if entry.get("state") not in SLOT_STATES:
            raise BudgetError(f"invalid slot state: {key}")
    return data


def _atomic_write(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent),
                                         prefix=path.name + ".", suffix=".tmp", delete=False)
    try:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
        raise
    # Persist the rename itself where the platform supports it.
    try:
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, AttributeError):
        pass


@contextmanager
def budget_lock(path):
    """Exclusive process-wide section. A leftover lock is never auto-removed."""
    target = lock_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BudgetLocked(
            f"acceptance lock already held: {target}. If no worker or script is alive, "
            "remove it manually; the budget and used slots are preserved."
        ) from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass


def init_budget(path, *, max_generations: int = MAX_GENERATIONS) -> dict:
    path = Path(path)
    if type(max_generations) is not int or not 1 <= max_generations <= MAX_GENERATIONS:
        raise BudgetError("T37 authorization must allow 1..3 complete tasks")
    if path.exists():
        raise BudgetError(f"acceptance budget already exists: {path}; refusing to reset quota")
    data = {"version": VERSION, "plan_id": PLAN_ID, "max_generations": max_generations,
            "created_at": _now(), "slots": _empty_slots(max_generations)}
    with budget_lock(path):
        if path.exists():
            raise BudgetError("acceptance budget already exists; refusing reset")
        _atomic_write(path, data)
    return data


@contextmanager
def _section(path, locked: bool):
    """Reuse the caller's lock instead of nesting a second ``O_EXCL`` attempt."""
    if locked:
        yield
    else:
        with budget_lock(path):
            yield


def reserve_slot(path, slot: int, *, locked: bool = False) -> dict:
    """Persist ``reserved`` before any job exists; this consumes the quota."""
    with _section(path, locked):
        data = load(path)
        key = str(slot)
        if key not in data["slots"]:
            raise BudgetError("slot must be 1, 2 or 3")
        entry = data["slots"][key]
        if entry["state"] != "unused":
            raise BudgetExhausted(f"slot {key} is already {entry['state']}; quota is never refunded")
        entry.update(state="reserved", reserved_at=_now())
        _atomic_write(path, data)
        return data


def mark_running(path, slot: int, run_id: str, *, locked: bool = False) -> dict:
    with _section(path, locked):
        data = load(path)
        entry = data["slots"][str(slot)]
        if entry["state"] != "reserved":
            raise BudgetError(f"slot {slot} is {entry['state']}, expected reserved")
        entry.update(state="running", run_id=run_id)
        _atomic_write(path, data)
        return data


def settle_slot(path, slot: int, *, outcome: str, run_id: str | None = None,
                locked: bool = False) -> dict:
    """Outcome is completed/failed/unknown; every terminal state keeps the quota."""
    if outcome not in {"completed", "failed", "unknown"}:
        raise BudgetError("outcome must be completed, failed or unknown")
    with _section(path, locked):
        data = load(path)
        entry = data["slots"][str(slot)]
        if entry["state"] not in {"reserved", "running"}:
            raise BudgetError(f"slot {slot} is {entry['state']}; cannot settle")
        entry.update(state=outcome, settled_at=_now(), outcome=outcome,
                     run_id=run_id or entry.get("run_id"))
        _atomic_write(path, data)
        return data


def takeover_slot(path, slot: int, *, reason: str, locked: bool = False) -> dict:
    """Reopen one unsettled slot so a killed run can be completed.

    This never refunds or adds quota: the slot stays consumed. It exists because
    a process can die between ``reserved`` and ``settled`` (SIGKILL, host reset),
    which would otherwise burn one of three authorizations without producing any
    evidence. Only one takeover per slot is allowed, and the reason is recorded.
    """
    if not str(reason or "").strip():
        raise BudgetError("takeover requires a non-empty reason")
    with _section(path, locked):
        data = load(path)
        entry = data["slots"][str(slot)]
        if entry["state"] not in {"reserved", "running"}:
            raise BudgetError(
                f"slot {slot} is {entry['state']}; only an unsettled slot can be taken over")
        previous = entry.get("takeovers") or []
        if previous:
            raise BudgetError(f"slot {slot} was already taken over once; quota is never refunded")
        entry["takeovers"] = [{
            "at": _now(),
            "reason": str(reason).strip(),
            "previous_run_id": entry.get("run_id"),
            "previous_state": entry["state"],
        }]
        entry.update(state="reserved", reserved_at=_now(), run_id=None)
        _atomic_write(path, data)
        return data


def used_slots(data: dict) -> int:
    return sum(1 for entry in data["slots"].values() if entry["state"] != "unused")


def summary(data: dict) -> dict:
    return {"plan_id": data["plan_id"], "max_generations": data["max_generations"],
            "used": used_slots(data),
            "remaining": data["max_generations"] - used_slots(data),
            "slots": {key: {"state": entry["state"], "run_id": entry.get("run_id"),
                            "reserved_at": entry.get("reserved_at")}
                      for key, entry in data["slots"].items()}}


def require_slot_available(data: dict, slot: int) -> None:
    entry = data["slots"].get(str(slot))
    if entry is None:
        raise BudgetError("slot must be 1, 2 or 3")
    if entry["state"] != "unused":
        raise BudgetExhausted(f"slot {slot} is already {entry['state']}")
