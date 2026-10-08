"""Candidate release construction and atomic publication coordination.

The coordinator deliberately contains no renderer or model calls.  It freezes
the hashes used by a candidate, gives artifacts an immutable release path, and
delegates the final pointer switch to the repository's transaction boundary.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CandidateReleaseCoordinator:
    """Build candidate records and commit them without mutating old releases."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def next_candidate_no(self, run_id: str) -> int:
        method = getattr(self.repository, "next_candidate_no", None)
        return int(method(run_id)) if method else 1

    def freeze(self, *, run_id: str, resource_id: str, release_policy: str,
               snapshots: list[dict[str, Any]], scenes: list[dict[str, Any]],
               provenance: dict[str, Any] | None = None,
               idempotency_key: str | None = None) -> dict[str, Any]:
        """Persist a candidate after freezing all inputs that define it."""
        scene_set = [{"scene_id": row.get("scene_id"),
                      "content_hash": row.get("content_hash"),
                      "revision_no": row.get("revision_no", row.get("attempt", 0))}
                     for row in sorted(scenes, key=lambda item: (item.get("scene_order", 0), item.get("scene_id", "")))]
        snapshot_set = [{"resource_id": row.get("resource_id"),
                         "version": row.get("version"),
                         "content_hash": row.get("content_hash")} for row in sorted(
                             snapshots, key=lambda item: item.get("resource_id", ""))]
        if idempotency_key:
            # The schema intentionally keeps the candidate key compact.  A
            # stable key-derived candidate number makes concurrent retries
            # converge on the same unique (run_id, candidate_no) row without
            # requiring a second mutable idempotency table.
            key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            candidate_no = int(key_hash[:12], 16)
            release_id = f"cwr_{run_id}_{key_hash[:16]}"
        else:
            candidate_no = self.next_candidate_no(run_id)
            release_id = f"cwr_{run_id}_{candidate_no}"
        row = {
            "release_id": release_id,
            "run_id": run_id,
            "resource_id": resource_id,
            "candidate_no": candidate_no,
            "status": "building",
            "release_policy": release_policy,
            "scene_set_hash": _hash(scene_set),
            "snapshot_set_hash": _hash(snapshot_set),
            "manifest_json": {"scene_set": scene_set, "snapshot_set": snapshot_set},
            "manifest_sha256": _hash({"scene_set": scene_set, "snapshot_set": snapshot_set}),
            "provenance_json": provenance or {},
        }
        if idempotency_key:
            row["manifest_json"]["idempotency_key_hash"] = _hash(idempotency_key)
        return self.repository.create_candidate_release_once(row)

    def commit(self, candidate: dict[str, Any], *, resource_id: str,
               resource_projection: dict[str, Any], job_status: str,
               warnings: list[dict[str, Any]], event_payload: dict[str, Any],
               manifest: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.repository.commit_release_once(
            candidate["release_id"], resource_id=resource_id,
            resource_projection=resource_projection, job_status=job_status,
            warnings=warnings, manifest=manifest, event_payload=event_payload,
        )

    def block(self, candidate: dict[str, Any], *, code: str, message: str) -> dict[str, Any] | None:
        method = getattr(self.repository, "block_release_once", None)
        if method:
            return method(candidate["release_id"], error_code=code, error_message=message)
        return None


__all__ = ["CandidateReleaseCoordinator"]
