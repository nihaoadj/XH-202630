"""Live acceptance adapter for the lecture review strategies (T38).

This tool drives the *production* request builder, gateway, ledger and decision
code against a frozen dataset.  It never changes production defaults: the new
strategy is enabled only through an explicit policy object created in this
process, and the legacy arm uses the unchanged ``content_v2`` profile.

The adapter is deliberately separate from ``lecture_review_eval.py`` (offline,
scripted).  A live run cannot be produced by setting an environment variable on
the offline path.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.agents.resource_workflows.learning_documents.reviewing import (
    ReviewAuditInput,
    ReviewCallCollector,
    build_review_prompt,
    build_review_request,
    check_resource_structure,
    invoke_review,
    normalize_review_result,
    resolve_review_profile,
    select_specialties,
)
from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import (
    paragraph_heading_paths,
    paragraphs,
    text_hash,
)
from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine import review_lecture
from app.agents.resource_workflows.learning_documents.reviewing.lecture_ledger import append_lecture_observation
from app.agents.resource_workflows.learning_documents.reviewing.results import (
    decorate_review_items,
    normalize_node_tier_review,
)
from app.agents.shared.evidence_scope import validate_payload_evidence
from app.agents.shared.policies import decide_review
from app.agents.shared.validators import revision_instructions_are_valid
from app.core.llm.gateway import LLMGatewayError, default_llm_gateway
from app.core.llm.transport import LangChainChatTransport
from app.core.retrieval.evidence import source_refs_are_scoped
from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.lecture_review import (
    LectureLedgerV1,
    LectureReviewBindingV1,
    LectureReviewOutputV1,
    LectureReviewPolicyV1,
)
from app.models.reviews.review_audit import ReviewPolicySnapshotV1
from app.models.shared.llm import LLMCallContext, RawLLMResponse, StructuredOutputMode
from app.models.shared.persistence import canonical_hash
from app.config import get_settings

EXPERIMENT_ID = "20261105-lecture-review-t38-live"
RUN_ID = "t38-live-20261105-r1"
SCHEMA_VERSION = "1.0"
DATASET_ID = "lecture-review-t38-live"
DATASET_VERSION = "v1.0.0"
NEW_STRATEGY = "lecture_issue_v1"
LEGACY_STRATEGY = "legacy_content_v2"
REPEATS = 2
FORMAL_SAMPLES = 6
FORMAL_LOGICAL_CALLS = FORMAL_SAMPLES * REPEATS * 2
SMOKE_LOGICAL_CALLS = 2
SAMPLE_CORRECT = "E1_correct_self_contained"
SAMPLE_MISSING = "E2_missing_required_input"
SAMPLE_FIXED = "E3_old_issue_fixed"
SAMPLE_FALSE_POSITIVE = "E4_old_review_false_positive"
PHYSICAL_ATTEMPT_UPPER_BOUND = 2  # gateway max_attempts=2; retry and repair share it
GLOBAL_DEADLINE_SECONDS = 90 * 60
MAX_TOTAL_TOKENS = 1_800_000
POLICY_CONTEXT_TOKENS = 129_024  # provider GET /models/deepseek-v4.1-flash max_input_tokens
POLICY_MAX_OUTPUT_TOKENS = 12_288  # unchanged content_v2 lecture profile cap
RULE_IDS = {"self_contained", "target_coverage", "difficulty", "organization", "synthetic_input"}
BLOCK_DECISIONS = {"revise", "human_review", "reject"}
LABEL_VERSION = "t38-live-label-v1"
SCORER_VERSION = "t38-live-score-v2"
ADJUDICATION_VERSION = "t38-live-adjudication-v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(value: Any) -> str:
    material = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256_bytes(material.encode("utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def policy_contract() -> tuple[LectureReviewPolicyV1, dict, str]:
    policy = LectureReviewPolicyV1(
        context_tokens=POLICY_CONTEXT_TOKENS,
        max_output_tokens=POLICY_MAX_OUTPUT_TOKENS,
    )
    dumped = policy.model_dump(mode="json")
    return policy, dumped, canonical_hash(dumped)


def frozen_evidence(evidence: list[EvidenceItem]) -> list[dict]:
    return [
        {"evidence_id": item.evidence_id, "excerpt_hash": text_hash(item.excerpt), "excerpt": item.excerpt}
        for item in sorted(evidence, key=lambda row: row.evidence_id)
    ]


def evidence_hashes(evidence: list[EvidenceItem]) -> dict[str, str]:
    return {item.evidence_id: text_hash(item.excerpt) for item in evidence}


def model_payload_bytes(content: str, evidence: list[EvidenceItem], extra: int = 0) -> int:
    """Conservative input upper bound in bytes, not a tokenizer."""
    headings = paragraph_heading_paths(content)
    body = len(content.encode("utf-8")) + sum(len(item.excerpt.encode("utf-8")) * 2 for item in evidence)
    body += len(json.dumps(headings, ensure_ascii=False).encode("utf-8"))
    return body + 8192 + extra


@dataclass(frozen=True)
class Sample:
    sample_id: str
    group_id: str
    split: str
    task_type: str
    origin: str
    strata: dict
    payload: dict
    input_hash: str

    @property
    def label_required(self) -> bool:
        return self.split == "evaluation"


def load_dataset(root: Path) -> tuple[dict, list[Sample], dict[str, dict]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("dataset manifest schema_version mismatch")
    if manifest.get("dataset_id") != DATASET_ID or manifest.get("version") != DATASET_VERSION:
        raise ValueError("dataset identity/version mismatch")
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.exists() or sha256_file(path) != expected:
            raise ValueError(f"dataset file hash mismatch: {name}")
    samples = []
    for line in (root / "samples.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload["input_hash"] != sha256_json(payload["input"]):
            raise ValueError(f"sample input hash mismatch: {payload['sample_id']}")
        samples.append(Sample(
            sample_id=payload["sample_id"], group_id=payload["group_id"], split=payload["split"],
            task_type=payload["task_type"], origin=payload["origin"], strata=payload.get("strata", {}),
            payload=payload, input_hash=payload["input_hash"],
        ))
    labels = {}
    for line in (root / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = json.loads(line)
        if label["rubric_version"] != LABEL_VERSION:
            raise ValueError("label rubric version mismatch")
        labels[label["sample_id"]] = label
    if len({item.sample_id for item in samples}) != len(samples):
        raise ValueError("duplicate sample identity")
    if len([item for item in samples if item.split == "evaluation"]) != FORMAL_SAMPLES:
        raise ValueError("formal sample count mismatch")
    if len([item for item in samples if item.split == "calibration"]) != 1:
        raise ValueError("calibration sample count mismatch")
    if set(labels) != {item.sample_id for item in samples}:
        raise ValueError("labels do not cover every sample")
    return manifest, samples, labels


class RecordingTransport:
    """Delegate to the real transport and retain the exact provider exchange."""

    def __init__(self, inner: LangChainChatTransport):
        self.inner = inner
        self.model_name = inner.model_name
        self.attempts: list[dict] = []

    def invoke(
        self,
        *,
        messages: list[BaseMessage],
        output_schema: type,
        mode: StructuredOutputMode,
        timeout_seconds: float,
        temperature: float,
        max_output_tokens: int,
    ) -> RawLLMResponse:
        record = {
            "attempt_index": len(self.attempts) + 1,
            "started_at": iso(utcnow()),
            "messages": [{"role": getattr(item, "type", "unknown"), "content": item.content} for item in messages],
            "output_schema": output_schema.__name__,
            "structured_output_mode": mode.value,
            "timeout_seconds": timeout_seconds,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        started = time.monotonic()
        try:
            raw = self.inner.invoke(
                messages=messages, output_schema=output_schema, mode=mode,
                timeout_seconds=timeout_seconds, temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:  # the gateway maps it; the record keeps the wire facts
            record.update({
                "status": "error", "error_type": type(exc).__name__,
                "error_message": str(exc)[:800], "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
                "finished_at": iso(utcnow()),
            })
            self.attempts.append(record)
            raise
        content = raw.content
        if isinstance(content, BaseModel):
            response_content: Any = content.model_dump(mode="json")
        elif isinstance(content, (dict, list)):
            response_content = content
        elif isinstance(content, str):
            response_content = content
        else:
            response_content = str(content)
        record.update({
            "status": "success",
            "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
            "finished_at": iso(utcnow()),
            "response_content": response_content,
            "response_content_type": type(content).__name__,
            "finish_reason": raw.finish_reason,
            "provider_request_id": raw.provider_request_id,
            "usage": raw.usage.model_dump(mode="json"),
            "response_metadata_subset": {
                key: raw.response_metadata.get(key)
                for key in ("finish_reason", "request_id") if raw.response_metadata.get(key) is not None
            },
        })
        self.attempts.append(record)
        return raw


def _error_status(exc: Exception) -> tuple[str, str | None, str | None]:
    if isinstance(exc, LLMGatewayError):
        category = exc.error.category
        if category in {"parse", "schema"}:
            return "invalid_contract", exc.error.code, category
        if category == "timeout":
            return "timeout", exc.error.code, category
        return "transport_error", exc.error.code, category
    if isinstance(exc, ValueError):
        return "invalid_contract", "REVIEW_CONTRACT_INVALID", "validation"
    return "unknown", type(exc).__name__, None


def build_state(*, resource: LearningResource, targets: list[str], policy: dict, policy_hash: str,
                parent_ledger: LectureLedgerV1 | None, parent_content: str | None,
                revision_count: int) -> dict:
    spec = {
        "resource_spec_id": resource.resource_spec_id,
        "resource_family_id": resource.resource_family_id,
        "knowledge_points": list(targets),
        "difficulty": resource.difficulty,
    }
    return {
        "run_id": RUN_ID,
        "revision_count": revision_count,
        "max_iterations": 4,
        "lecture_review_policy": policy,
        "lecture_review_policy_hash": policy_hash,
        "lecture_ledgers": ({resource.resource_spec_id: parent_ledger.model_dump(mode="json")}
                            if parent_ledger is not None else {}),
        "lecture_revision": ({resource.resource_spec_id: {"previous_content": parent_content}}
                             if parent_ledger is not None else {}),
        "resource_specs": [spec],
        "constraints": {},
    }


def build_parent_ledger(*, sample: Sample, policy: dict, policy_hash: str,
                        evidence: list[EvidenceItem]) -> tuple[LectureLedgerV1, LearningResource, str]:
    data = sample.payload["input"]
    parent = LearningResource.model_validate(data["parent_resource"])
    content = parent.content_text or ""
    frozen = frozen_evidence(evidence)
    binding = LectureReviewBindingV1(
        run_id=RUN_ID,
        resource_spec_id=parent.resource_spec_id,
        lineage_id=parent.resource_family_id,
        resource_id=parent.resource_id,
        version=parent.version,
        content_hash=text_hash(content),
        evidence_snapshot_hash=canonical_hash({"evidence": frozen}),
        policy_hash=policy_hash,
    )
    raw_output = dict(data["parent_review_output"])
    raw_output["binding"] = binding.model_dump(mode="json")
    output = LectureReviewOutputV1.model_validate(raw_output)
    ledger = append_lecture_observation(
        previous=None, binding=binding, step_id=data["parent_step_id"], output=output,
        content=content, previous_content=None, parent_resource_id=None,
        targets=list(data["targets"]), evidence_hashes=evidence_hashes(evidence),
        teaching_rule_ids=RULE_IDS, revision_kind="ordinary",
    )
    return ledger, parent, content


def _legacy_call(*, resource: LearningResource, evidence: list[EvidenceItem], difficulty: str,
                 gateway, collector: ReviewCallCollector, context: LLMCallContext,
                 review_id: str, valid_refs: bool) -> dict:
    policy = ReviewPolicySnapshotV1()
    profile = resolve_review_profile(resource_type="讲义", phase="content_v2", policy=policy)
    bundle = build_review_prompt(
        profile=profile, enabled_specialties=select_specialties(profile=profile, resource=resource))
    request = build_review_request(
        profile=profile, prompt_bundle=bundle,
        audit_input=ReviewAuditInput(resource=resource, evidence=tuple(evidence),
                                     difficulty=difficulty, constraints={}, policy=policy),
    )
    result = invoke_review(request=request, llm_gateway=gateway, collector=collector,
                           review_id=review_id, call_context=context)
    raw = normalize_review_result(output=result.output, resource_context=resource)
    raw = normalize_node_tier_review(raw, resource, {"constraints": {}})
    decorated = decorate_review_items(raw, run_id=f"{RUN_ID}:{resource.resource_id}", generation_attempt=1)
    valid = revision_instructions_are_valid(
        decorated.get("revision_instructions", []), [resource.resource_type])
    decision = decide_review(
        decorated, valid_source_refs=valid_refs, valid_revision_instructions=valid)
    return {
        "decision": decision.value,
        "decision_source": "program",
        "model_requested_decision": raw.get("decision"),
        "output": decorated,
        "profiles": [profile.phase],
        "prompt_fingerprint": bundle.fingerprint,
        "input_estimate_tokens": None,
        "input_estimate_note": "legacy profile has no production window check",
        "structured_output_mode": result.structured_output_mode.value,
        "finish_reason": result.finish_reason,
        "provider_request_id": result.provider_request_id,
        "llm_latency_ms": result.latency_ms,
        "retry_count": result.retry_count,
        "valid_source_refs": valid_refs,
        "valid_revision_instructions": valid,
        "resolutions": [],
        "open_blocking": [
            {"issue_id": item.get("issue_id"), "code": item.get("code"), "severity": item.get("severity"),
             "description": item.get("description"), "requirement": None, "acceptance": None}
            for item in decorated.get("issues", []) if item.get("severity") in {"high", "critical"}
        ],
    }


def _new_call(*, state: dict, resource: LearningResource, evidence: list[EvidenceItem],
              gateway, collector: ReviewCallCollector, context: LLMCallContext,
              review_id: str) -> dict:
    raw, ledger, result, stop_reason = review_lecture(
        state=state, resource=resource, evidence=evidence, step_id=context.step_id,
        context=context, gateway=gateway, collector=collector, review_id=review_id,
    )
    observation = ledger.observations[-1]
    return {
        "decision": raw["decision"],
        "decision_source": "ledger",
        "model_requested_decision": observation.decision,
        "output": observation.output.model_dump(mode="json"),
        "profiles": ["lecture_recheck_v1" if len(ledger.observations) > 1 else "lecture_initial_v1"],
        "prompt_fingerprint": None,
        "input_estimate_tokens": None,
        "input_estimate_note": "production engine estimates before dispatch; exact messages captured per attempt",
        "structured_output_mode": result.structured_output_mode.value,
        "finish_reason": result.finish_reason,
        "provider_request_id": result.provider_request_id,
        "llm_latency_ms": result.latency_ms,
        "retry_count": result.retry_count,
        "stop_reason": stop_reason,
        "ledger": ledger.model_dump(mode="json"),
        "ledger_hash": canonical_hash(ledger.model_dump(mode="json")),
        "resolutions": [
            {"issue_id": item.issue_id, "result": item.result, "reason": item.reason,
             "current_location": item.current_location.model_dump(mode="json") if item.current_location else None,
             "previous_location": item.previous_location.model_dump(mode="json") if item.previous_location else None}
            for item in observation.output.resolutions
        ],
        "open_blocking": [
            {"issue_id": entry.issue.issue_id, "code": entry.issue.code, "severity": entry.issue.severity,
             "dimension": entry.issue.dimension, "blocking_rule": entry.issue.blocking_rule,
             "requirement": entry.issue.requirement, "acceptance": entry.issue.acceptance,
             "path": entry.issue.path, "executability": entry.issue.executability,
             "impact": entry.issue.impact}
            for entry in ledger.issues if entry.status == "open" and entry.issue.blocking
        ],
        "dimensions": observation.output.dimensions.model_dump(mode="json"),
        "hallucination_score": observation.output.hallucination_score,
        "targets": [item.model_dump(mode="json") for item in observation.output.targets],
        "unchanged": observation.unchanged,
    }


def _call_record(*, observation_id: str, logical_call_id: str, attempt: dict,
                 request_ref: str, request_hash: str, response_ref: str | None,
                 response_hash: str | None, model_name: str, reservation: dict) -> dict:
    usage = attempt.get("usage") or {}
    known = all(usage.get(key) is not None for key in ("input_tokens", "output_tokens"))
    status = "success" if attempt.get("status") == "success" else "error"
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "call_id": f"{logical_call_id}#a{attempt['attempt_index']}",
        "observation_id": observation_id,
        "logical_call_id": logical_call_id,
        "attempt_index": attempt["attempt_index"],
        "role": "system_under_test",
        "provider": "dashscope-compatible",
        "deployment": model_name,
        "request_ref": request_ref,
        "request_hash": request_hash,
        "response_ref": response_ref,
        "response_hash": response_hash,
        "provider_request_id": attempt.get("provider_request_id"),
        "status": status,
        "error_type": attempt.get("error_type"),
        "started_at": attempt.get("started_at"),
        "finished_at": attempt.get("finished_at"),
        "latency_ms": attempt.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cached_tokens": None,
        "reasoning_tokens": None,
        "usage_source": "provider" if known else "unknown",
        "unknown_reason": None if known else "provider usage missing or call failed before usage was reported",
        "estimated_cost": None,
        "billed_cost": None,
        "currency": None,
        "price_version": None,
        "reservation": reservation,
    }


def _not_dispatched_record(*, observation_id: str, logical_call_id: str, model_name: str,
                           reason: str, reservation: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
        "call_id": f"{logical_call_id}#a0", "observation_id": observation_id,
        "logical_call_id": logical_call_id, "attempt_index": 0, "role": "system_under_test",
        "provider": "dashscope-compatible", "deployment": model_name,
        "request_ref": None, "request_hash": None, "response_ref": None, "response_hash": None,
        "provider_request_id": None, "status": "not_dispatched", "error_type": reason,
        "started_at": iso(utcnow()), "finished_at": iso(utcnow()), "latency_ms": 0,
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
        "cached_tokens": None, "reasoning_tokens": None, "usage_source": "unknown",
        "unknown_reason": reason, "estimated_cost": None, "billed_cost": None,
        "currency": None, "price_version": None, "reservation": reservation,
    }


class RunStore:
    def __init__(self, experiment_root: Path):
        self.root = experiment_root
        self.run_dir = experiment_root / "runs" / RUN_ID
        if self.run_dir.exists():
            raise ValueError(f"run directory already exists: {self.run_dir}")
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "artifacts").mkdir()
        self.observations_path = self.run_dir / "observations.jsonl"
        self.calls_path = self.run_dir / "calls.jsonl"
        self.budget_path = self.run_dir / "budget.json"
        self.budget = {
            "schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
            "logical_cap": FORMAL_LOGICAL_CALLS + SMOKE_LOGICAL_CALLS,
            "formal_logical_cap": FORMAL_LOGICAL_CALLS, "smoke_logical_cap": SMOKE_LOGICAL_CALLS,
            "logical_used": 0, "formal_used": 0, "smoke_used": 0, "reserved_logical": 0,
            "physical_attempts": 0, "input_tokens": 0, "output_tokens": 0,
            "unknown_usage_calls": 0, "reserved_tokens": 0, "max_total_tokens": MAX_TOTAL_TOKENS,
            "updated_at": iso(utcnow()),
        }
        self._flush_budget()
        self.recovered_unknown = self._recover_incomplete()

    def _recover_incomplete(self) -> bool:
        if not self.budget.get("reserved_logical"):
            return False
        # A previous process reserved a call but never settled it.  Do not
        # retry: charge the slot and keep the observation unknown.
        self.budget["logical_used"] += 1
        self.budget["unknown_usage_calls"] += 1
        self.budget["reserved_logical"] = 0
        self._flush_budget()
        return True

    def _flush_budget(self) -> None:
        self.budget["updated_at"] = iso(utcnow())
        write_json(self.budget_path, self.budget)

    def reserve(self, *, phase: str, tokens: int) -> None:
        if self.budget["reserved_logical"]:
            raise ValueError("budget already reserved")
        if phase == "smoke" and self.budget["smoke_used"] >= SMOKE_LOGICAL_CALLS:
            raise ValueError("smoke budget exhausted")
        if phase == "formal" and self.budget["formal_used"] >= FORMAL_LOGICAL_CALLS:
            raise ValueError("formal budget exhausted")
        if self.budget["logical_used"] >= self.budget["logical_cap"]:
            raise ValueError("logical budget exhausted")
        if self.budget["reserved_tokens"] + tokens > MAX_TOTAL_TOKENS:
            raise ValueError("token reservation would exceed the frozen ceiling")
        self.budget["reserved_logical"] = 1
        self.budget["reserved_tokens"] += tokens
        self._flush_budget()

    def settle(self, *, phase: str, physical_attempts: int, input_tokens: int | None,
               output_tokens: int | None, unknown: bool, reservation_tokens: int) -> None:
        self.budget["logical_used"] += 1
        self.budget[f"{phase}_used"] += 1
        self.budget["reserved_logical"] = 0
        self.budget["reserved_tokens"] = max(0, self.budget["reserved_tokens"] - reservation_tokens)
        self.budget["physical_attempts"] += physical_attempts
        if input_tokens is not None:
            self.budget["input_tokens"] += input_tokens
        if output_tokens is not None:
            self.budget["output_tokens"] += output_tokens
        if unknown:
            self.budget["unknown_usage_calls"] += 1
        self._flush_budget()

    def artifact_dir(self, observation_id: str) -> Path:
        path = self.run_dir / "artifacts" / observation_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def preflight(*, dataset_root: Path, experiment_root: Path) -> dict:
    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value()
    manifest, samples, labels = load_dataset(dataset_root)
    policy, policy_dict, policy_hash = policy_contract()
    evaluation = [item for item in samples if item.split == "evaluation"]
    reservations = []
    for sample in evaluation:
        data = sample.payload["input"]
        content = data["resource"]["content_text"] or ""
        evidence = [EvidenceItem.model_validate_json(json.dumps(item)) for item in data["evidence"]]
        extra = 8192 if data.get("parent_review_output") else 4096
        upper = model_payload_bytes(content, evidence, extra=extra) + POLICY_MAX_OUTPUT_TOKENS
        reservations.append({"sample_id": sample.sample_id, "input_tokens_upper": upper - POLICY_MAX_OUTPUT_TOKENS,
                             "reservation_tokens": upper * PHYSICAL_ATTEMPT_UPPER_BOUND})
    token_reservation = sum(item["reservation_tokens"] for item in reservations) * REPEATS * 2
    smoke_reservation = max(item["reservation_tokens"] for item in reservations) * 2
    checks = {
        "dataset_manifest_hash": sha256_file(dataset_root / "manifest.json"),
        "dataset_samples": len(samples), "formal_samples": len(evaluation),
        "credentials_present": bool(api_key.strip()),
        "model": settings.llm_model, "base_url": settings.llm_base_url,
        "thinking_mode": settings.llm_thinking_mode,
        "structured_output_mode": settings.llm_structured_output_mode,
        "request_timeout_seconds": settings.llm_request_timeout_seconds,
        "gateway_max_attempts": settings.llm_max_attempts,
        "default_max_output_tokens": settings.llm_max_output_tokens,
        "policy_context_tokens": policy.context_tokens,
        "policy_max_output_tokens": policy.max_output_tokens,
        "policy_hash": policy_hash,
        "formal_logical_calls": FORMAL_LOGICAL_CALLS, "smoke_logical_calls": SMOKE_LOGICAL_CALLS,
        "physical_attempt_upper_bound": (FORMAL_LOGICAL_CALLS + SMOKE_LOGICAL_CALLS) * PHYSICAL_ATTEMPT_UPPER_BOUND,
        "global_deadline_seconds": GLOBAL_DEADLINE_SECONDS,
        "token_reservation_formal": token_reservation,
        "token_reservation_smoke": smoke_reservation,
        "token_reservation_total": token_reservation + smoke_reservation,
        "token_ceiling": MAX_TOTAL_TOKENS,
        "max_amount": None, "currency": None,
        "amount_missing_reason": "no frozen price version for this deployment; spend bounded by call and token ceilings",
        "experiment_root": str(experiment_root),
        "run_dir_exists": (experiment_root / "runs" / RUN_ID).exists(),
        "python": platform.python_version(), "platform": platform.platform(),
    }
    checks["ready"] = (
        checks["credentials_present"] and checks["token_reservation_total"] <= MAX_TOTAL_TOKENS
        and not checks["run_dir_exists"] and checks["formal_samples"] == FORMAL_SAMPLES
    )
    return {"schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "checks": checks,
            "reservations": reservations, "policy": policy_dict}


def _capture_source_state(*, run_dir: Path) -> dict:
    artifacts = run_dir / "artifacts"
    repo = Path(__file__).resolve().parents[2]
    diff_path = artifacts / "source-diff.patch"
    try:
        diff = subprocess.run(
            ["git", "diff", "--no-textconv", "HEAD"], cwd=repo,
            capture_output=True, check=False, timeout=120,
        )
        diff_path.write_bytes(diff.stdout)
        diff_status = {"exit_code": diff.returncode, "bytes": len(diff.stdout),
                       "hash": sha256_bytes(diff.stdout), "stderr": diff.stderr.decode("utf-8", "replace")[:500]}
    except Exception as exc:  # the patch is evidence, not a hard requirement
        diff_path.write_text("", encoding="utf-8")
        diff_status = {"exit_code": None, "bytes": 0, "hash": sha256_bytes(b""),
                       "stderr": f"{type(exc).__name__}: {exc}"}
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                              check=False, timeout=30).stdout.decode("utf-8", "replace").strip()
        tree = subprocess.run(["git", "write-tree"], cwd=repo, capture_output=True,
                              check=False, timeout=60).stdout.decode("utf-8", "replace").strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                                check=False, timeout=60).stdout.decode("utf-8", "replace").splitlines()
    except Exception as exc:
        head = tree = None
        status = [f"unavailable: {type(exc).__name__}: {exc}"]
    untracked = []
    snapshot_dir = artifacts / "untracked-sources"
    for index, line in enumerate(status, 1):
        if not line.startswith("?? "):
            continue
        relative = line[3:].strip().strip('"')
        path = repo / relative
        if path.is_file() and path.suffix in {".py", ".json", ".md", ".example"}:
            destination = snapshot_dir / f"{index:03d}-{path.name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
            untracked.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size,
                              "snapshot": str(destination.relative_to(artifacts)).replace("\\", "/")})
    write_json(artifacts / "untracked-sources.json", {"count": len(untracked), "files": untracked})
    return {"head": head, "index_tree": tree, "status_entries": len(status),
            "untracked_source_files": len(untracked), "source_diff": diff_status}


def _config_snapshot() -> dict:
    settings = get_settings()
    return {
        "model": settings.llm_model, "base_url": settings.llm_base_url,
        "thinking_mode": settings.llm_thinking_mode,
        "structured_output_mode": settings.llm_structured_output_mode,
        "request_timeout_seconds": settings.llm_request_timeout_seconds,
        "max_attempts": settings.llm_max_attempts,
        "max_output_tokens_default": settings.llm_max_output_tokens,
        "lecture_review_strategy_default": settings.lecture_review_strategy,
        "lecture_review_context_tokens_env": settings.lecture_review_context_tokens,
        "credentials_present": bool(settings.llm_api_key.get_secret_value().strip()),
        "policy_context_tokens_frozen": POLICY_CONTEXT_TOKENS,
        "policy_max_output_tokens_frozen": POLICY_MAX_OUTPUT_TOKENS,
    }


def _run_one(*, sample: Sample, strategy: str, repeat: int, order: int,
             store: RunStore, dataset_root: Path, deadline: datetime,
             model_name: str) -> dict:
    data = sample.payload["input"]
    resource = LearningResource.model_validate(data["resource"])
    evidence = [EvidenceItem.model_validate_json(json.dumps(item)) for item in data["evidence"]]
    targets = list(data["targets"])
    difficulty = data["difficulty"]
    policy, policy_dict, policy_hash = policy_contract()
    observation_id = f"{sample.sample_id}-{strategy}-r{repeat}"
    logical_call_id = str(uuid.uuid4())
    artifact_dir = store.artifact_dir(observation_id)
    started_at = utcnow()
    started = time.monotonic()

    validate_payload_evidence(resource, evidence)
    valid_refs = source_refs_are_scoped(resource.source_refs, evidence)
    state = build_state(resource=resource, targets=targets, policy=policy_dict, policy_hash=policy_hash,
                        parent_ledger=None, parent_content=None, revision_count=0)
    gate = check_resource_structure(resource=resource, context=state)

    parent_ledger = None
    parent_content = None
    if data.get("parent_review_output"):
        parent_ledger, _parent_resource, parent_content = build_parent_ledger(
            sample=sample, policy=policy_dict, policy_hash=policy_hash, evidence=evidence)
        state = build_state(resource=resource, targets=targets, policy=policy_dict, policy_hash=policy_hash,
                            parent_ledger=parent_ledger, parent_content=parent_content, revision_count=1)
        write_json(artifact_dir / "parent-ledger.json", {
            "origin": data.get("old_ledger_origin", "test_setup_frozen_ledger"),
            "note": "Historical ledger built by the production ledger from a frozen test-setup review output; not produced by this run.",
            "parent_step_id": data.get("parent_step_id"),
            "parent_content_hash": text_hash(parent_content),
            "ledger": parent_ledger.model_dump(mode="json"),
            "ledger_hash": canonical_hash(parent_ledger.model_dump(mode="json")),
        })

    reservation_tokens = (model_payload_bytes(resource.content_text or "", evidence,
                                              extra=8192 if parent_ledger else 4096)
                          + POLICY_MAX_OUTPUT_TOKENS) * PHYSICAL_ATTEMPT_UPPER_BOUND
    store.reserve(phase="smoke" if sample.split == "calibration" else "formal", tokens=reservation_tokens)
    remaining = (deadline - utcnow()).total_seconds()
    if remaining < 90:
        store.settle(phase="smoke" if sample.split == "calibration" else "formal",
                     physical_attempts=0, input_tokens=None, output_tokens=None,
                     unknown=True, reservation_tokens=reservation_tokens)
        record = {
            "schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
            "observation_id": observation_id, "sample_id": sample.sample_id, "variant_id": strategy,
            "repeat_index": repeat, "execution_order": order, "status": "not_started",
            "input_ref": f"artifacts/{observation_id}/input.json", "input_hash": sample.input_hash,
            "output_ref": None, "output_hash": None, "error_ref": None,
            "started_at": iso(started_at), "finished_at": iso(utcnow()),
            "end_to_end_ms": max(0, int((time.monotonic() - started) * 1000)),
            "logical_call_ids": [], "attempt_ids": [], "cache": "none", "artifact_refs": [],
            "result_summary": {"reason": "global_deadline_insufficient"},
        }
        write_json(artifact_dir / "input.json", sample.payload)
        append_jsonl(store.observations_path, record)
        return record

    recorder = RecordingTransport(LangChainChatTransport(get_settings()))
    gateway = copy.copy(default_llm_gateway())
    gateway.transport = recorder
    collector = ReviewCallCollector()
    context = LLMCallContext(
        run_id=RUN_ID, step_id=f"live-{observation_id}", node_name="reviewer",
        schema_name="LectureRecheckReviewV1" if parent_ledger else "LectureInitialReviewV1",
        generation_attempt=1, call_id=logical_call_id, workflow_deadline_at=deadline,
    )
    review_id = str(uuid.uuid4())
    status = "success"
    error_code = None
    error_category = None
    error_message = None
    result: dict
    try:
        if gate is not None:
            result = {
                "decision": gate.get("decision", "revise"), "decision_source": "program_gate",
                "model_requested_decision": None, "output": gate, "profiles": [],
                "resolutions": [], "open_blocking": [],
            }
            status = "program_gate"
        elif strategy == NEW_STRATEGY:
            result = _new_call(state=state, resource=resource, evidence=evidence, gateway=gateway,
                               collector=collector, context=context, review_id=review_id)
        else:
            result = _legacy_call(resource=resource, evidence=evidence, difficulty=difficulty,
                                  gateway=gateway, collector=collector, context=context,
                                  review_id=review_id, valid_refs=valid_refs)
    except Exception as exc:
        status, error_code, error_category = _error_status(exc)
        error_message = str(exc)[:1000]
        result = {
            "decision": "human_review", "decision_source": "fail_closed",
            "model_requested_decision": None, "output": None, "profiles": [],
            "resolutions": [], "open_blocking": [],
        }
    finished_at = utcnow()
    end_to_end_ms = max(0, int((time.monotonic() - started) * 1000))

    # Persist the exact request/response per physical attempt.
    attempt_records = list(recorder.attempts)
    attempt_ids = []
    response_hashes = []
    for attempt in attempt_records:
        index = attempt["attempt_index"]
        request_payload = {
            "observation_id": observation_id, "strategy": strategy, "attempt_index": index,
            "logical_call_id": logical_call_id, "model": model_name,
            "messages": attempt["messages"], "output_schema": attempt["output_schema"],
            "structured_output_mode": attempt["structured_output_mode"],
            "timeout_seconds": attempt["timeout_seconds"], "temperature": attempt["temperature"],
            "max_output_tokens": attempt["max_output_tokens"],
        }
        request_path = artifact_dir / f"attempt-{index}-request.json"
        write_json(request_path, request_payload)
        request_hash = sha256_json(request_payload)
        response_ref = None
        response_hash = None
        if attempt["status"] == "success":
            response_payload = {
                "observation_id": observation_id, "attempt_index": index,
                "raw_content": attempt["response_content"],
                "content_type": attempt["response_content_type"],
                "finish_reason": attempt.get("finish_reason"),
                "provider_request_id": attempt.get("provider_request_id"),
                "usage": attempt.get("usage"),
                "response_metadata_subset": attempt.get("response_metadata_subset"),
            }
            response_path = artifact_dir / f"attempt-{index}-response.json"
            write_json(response_path, response_payload)
            response_ref = str(response_path.relative_to(store.run_dir)).replace("\\", "/")
            response_hash = sha256_json(response_payload)
            response_hashes.append(response_hash)
        else:
            error_payload = {"type": attempt.get("error_type"), "message": attempt.get("error_message")}
            error_path = artifact_dir / f"attempt-{index}-error.json"
            write_json(error_path, error_payload)
        call = _call_record(
            observation_id=observation_id, logical_call_id=logical_call_id, attempt=attempt,
            request_ref=str(request_path.relative_to(store.run_dir)).replace("\\", "/"),
            request_hash=request_hash, response_ref=response_ref, response_hash=response_hash,
            model_name=model_name,
            reservation={"input_tokens_upper": reservation_tokens // PHYSICAL_ATTEMPT_UPPER_BOUND - POLICY_MAX_OUTPUT_TOKENS,
                         "output_tokens": POLICY_MAX_OUTPUT_TOKENS},
        )
        append_jsonl(store.calls_path, call)
        attempt_ids.append(call["call_id"])

    if not attempt_records:
        call = _not_dispatched_record(
            observation_id=observation_id, logical_call_id=logical_call_id, model_name=model_name,
            reason=error_code or "no_provider_attempt",
            reservation={"input_tokens_upper": reservation_tokens // PHYSICAL_ATTEMPT_UPPER_BOUND - POLICY_MAX_OUTPUT_TOKENS,
                         "output_tokens": POLICY_MAX_OUTPUT_TOKENS},
        )
        append_jsonl(store.calls_path, call)
        attempt_ids.append(call["call_id"])

    known_input = [item.get("usage", {}).get("input_tokens") for item in attempt_records if item.get("status") == "success"]
    known_output = [item.get("usage", {}).get("output_tokens") for item in attempt_records if item.get("status") == "success"]
    input_tokens = sum(known_input) if known_input and all(value is not None for value in known_input) else None
    output_tokens = sum(known_output) if known_output and all(value is not None for value in known_output) else None
    usage_unknown = input_tokens is None or output_tokens is None
    physical_attempts = len(attempt_records)
    store.settle(
        phase="smoke" if sample.split == "calibration" else "formal",
        physical_attempts=physical_attempts, input_tokens=input_tokens, output_tokens=output_tokens,
        unknown=usage_unknown or status not in {"success", "program_gate"}, reservation_tokens=reservation_tokens,
    )

    result_payload = {
        **result, "status": status, "error_code": error_code, "error_category": error_category,
        "error_message": error_message, "physical_attempts": physical_attempts,
        "attempt_ids": attempt_ids,
    }
    result_path = artifact_dir / "result.json"
    write_json(result_path, result_payload)
    write_json(artifact_dir / "input.json", sample.payload)

    record = {
        "schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
        "observation_id": observation_id, "sample_id": sample.sample_id, "variant_id": strategy,
        "repeat_index": repeat, "execution_order": order, "status": status,
        "input_ref": f"artifacts/{observation_id}/input.json", "input_hash": sample.input_hash,
        "output_ref": str(result_path.relative_to(store.run_dir)).replace("\\", "/"),
        "output_hash": sha256_json(result_payload),
        "error_ref": None if status == "success" else f"artifacts/{observation_id}/result.json",
        "started_at": iso(started_at), "finished_at": iso(finished_at), "end_to_end_ms": end_to_end_ms,
        "logical_call_ids": [logical_call_id], "attempt_ids": attempt_ids, "cache": "none",
        "artifact_refs": [f"artifacts/{observation_id}"],
        "result_summary": {
            "decision": result.get("decision"), "decision_source": result.get("decision_source"),
            "model_requested_decision": result.get("model_requested_decision"),
            "resolutions": result.get("resolutions", []),
            "open_blocking": result.get("open_blocking", []),
            "dimensions": result.get("dimensions"),
            "hallucination_score": result.get("hallucination_score"),
            "unchanged": result.get("unchanged"),
            "retry_count": result.get("retry_count"),
            "llm_latency_ms": result.get("llm_latency_ms"),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "usage_unknown": usage_unknown,
            "error_code": error_code, "error_category": error_category,
            "stop_reason": result.get("stop_reason"),
        },
    }
    append_jsonl(store.observations_path, record)
    return record


def _matrix(samples: list[Sample]) -> list[dict]:
    formal = [item for item in samples if item.split == "evaluation"]
    items = []
    order = 0
    for repeat in range(1, REPEATS + 1):
        for sample in formal:
            variants = [NEW_STRATEGY, LEGACY_STRATEGY] if repeat == 1 else [LEGACY_STRATEGY, NEW_STRATEGY]
            for variant in variants:
                order += 1
                items.append({"sample": sample, "strategy": variant, "repeat": repeat, "order": order})
    return items


def _not_started(*, item: dict, store: RunStore, reason: str) -> dict:
    observation_id = f"{item['sample'].sample_id}-{item['strategy']}-r{item['repeat']}"
    artifact_dir = store.artifact_dir(observation_id)
    write_json(artifact_dir / "input.json", item["sample"].payload)
    record = {
        "schema_version": SCHEMA_VERSION, "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
        "observation_id": observation_id, "sample_id": item["sample"].sample_id,
        "variant_id": item["strategy"], "repeat_index": item["repeat"], "execution_order": item["order"],
        "status": "not_started", "input_ref": f"artifacts/{observation_id}/input.json",
        "input_hash": item["sample"].input_hash, "output_ref": None, "output_hash": None,
        "error_ref": None, "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
        "end_to_end_ms": 0, "logical_call_ids": [], "attempt_ids": [], "cache": "none",
        "artifact_refs": [], "result_summary": {"reason": reason},
    }
    append_jsonl(store.observations_path, record)
    return record


def run_live(*, dataset_root: Path, experiment_root: Path) -> dict:
    check = preflight(dataset_root=dataset_root, experiment_root=experiment_root)
    if not check["checks"]["ready"]:
        return {"status": "PREFLIGHT_BLOCKED", "checks": check["checks"]}
    manifest, samples, labels = load_dataset(dataset_root)
    experiment_path = experiment_root / "experiment.json"
    if not experiment_path.exists():
        raise ValueError("experiment.json must be frozen before a live run")
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    if experiment.get("experiment_id") != EXPERIMENT_ID:
        raise ValueError("experiment identity mismatch")
    if experiment.get("dataset", {}).get("version") != DATASET_VERSION:
        raise ValueError("experiment dataset version mismatch")

    store = RunStore(experiment_root)
    deadline = utcnow() + timedelta(seconds=GLOBAL_DEADLINE_SECONDS)
    started_at = utcnow()
    model_name = get_settings().llm_model
    artifacts = store.run_dir / "artifacts"
    write_json(artifacts / "config.json", _config_snapshot())
    write_json(artifacts / "dataset-manifest.json", manifest)
    for name in ("samples.jsonl", "labels.jsonl"):
        (artifacts / name).write_bytes((dataset_root / name).read_bytes())
    source_state = _capture_source_state(run_dir=store.run_dir)
    run_record = {
        "schema_version": SCHEMA_VERSION, "run_id": RUN_ID, "experiment_id": EXPERIMENT_ID,
        "experiment_manifest_hash": sha256_json(experiment), "mode": "live",
        "status": "RUNNING", "started_at": iso(started_at), "finished_at": None,
        "command": " ".join(sys.argv), "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "expected_matrix": {"formal": FORMAL_LOGICAL_CALLS, "smoke": SMOKE_LOGICAL_CALLS,
                            "order": "r1 new->legacy, r2 legacy->new", "repeats": REPEATS,
                            "strategies": [NEW_STRATEGY, LEGACY_STRATEGY]},
        "actual": {}, "authorization": {"source": "user message 2026-11-05",
                                        "formal_logical_calls": FORMAL_LOGICAL_CALLS,
                                        "smoke_logical_calls": SMOKE_LOGICAL_CALLS,
                                        "generation_calls": 0, "claim_calls": 0},
        "backup_status": "local_only", "preflight": check["checks"],
        "source_state": source_state, "dataset_manifest_hash": check["checks"]["dataset_manifest_hash"],
        "production_defaults_changed": False,
    }
    write_json(store.run_dir / "run.json", run_record)

    smoke_sample = next(item for item in samples if item.split == "calibration")
    smoke_records = []
    smoke_ok = True
    for order, strategy in enumerate((LEGACY_STRATEGY, NEW_STRATEGY), 1):
        record = _run_one(sample=smoke_sample, strategy=strategy, repeat=0, order=order,
                          store=store, dataset_root=dataset_root, deadline=deadline, model_name=model_name)
        smoke_records.append(record)
        if record["status"] != "success":
            smoke_ok = False
            break
    if not smoke_ok:
        run_record.update({"status": "ABORTED_SMOKE", "finished_at": iso(utcnow()),
                           "actual": store.budget, "smoke_observations": [item["observation_id"] for item in smoke_records]})
        write_json(store.run_dir / "run.json", run_record)
        _write_checksums(store.run_dir)
        return {"status": "ABORTED_SMOKE", "run_dir": str(store.run_dir),
                "observations": [item["observation_id"] for item in smoke_records]}

    matrix = _matrix(samples)
    executed = []
    stopped_reason = None
    for item in matrix:
        if stopped_reason is not None:
            executed.append(_not_started(item=item, store=store, reason=stopped_reason))
            continue
        remaining = (deadline - utcnow()).total_seconds()
        if remaining < 90:
            stopped_reason = "global_deadline_insufficient"
            executed.append(_not_started(item=item, store=store, reason=stopped_reason))
            continue
        try:
            record = _run_one(sample=item["sample"], strategy=item["strategy"], repeat=item["repeat"],
                              order=item["order"], store=store, dataset_root=dataset_root,
                              deadline=deadline, model_name=model_name)
        except ValueError as exc:
            stopped_reason = f"budget_or_state_error:{exc}"
            executed.append(_not_started(item=item, store=store, reason=stopped_reason))
            continue
        executed.append(record)

    complete = len([item for item in executed if item["status"] not in {"not_started"}]) == FORMAL_LOGICAL_CALLS
    run_record.update({
        "status": "COMPLETED" if complete else "PARTIAL", "finished_at": iso(utcnow()),
        "actual": store.budget, "observations": len(executed),
        "smoke_observations": [item["observation_id"] for item in smoke_records],
        "stop_reason": stopped_reason,
    })
    write_json(store.run_dir / "run.json", run_record)
    _write_checksums(store.run_dir)
    return {"status": run_record["status"], "run_dir": str(store.run_dir),
            "logical_calls": store.budget["logical_used"],
            "physical_attempts": store.budget["physical_attempts"],
            "observations": len(executed)}


def _write_checksums(run_dir: Path) -> None:
    checksums = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "checksums.json":
            checksums[str(path.relative_to(run_dir)).replace("\\", "/")] = sha256_file(path)
    write_json(run_dir / "checksums.json", {
        "schema_version": SCHEMA_VERSION, "run_id": RUN_ID, "files": checksums,
        "checksums_hash": sha256_json(checksums),
    })


def load_run(run_dir: Path) -> tuple[dict, list[dict], list[dict], list[dict]]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    observations = read_jsonl(run_dir / "observations.jsonl")
    calls = read_jsonl(run_dir / "calls.jsonl")
    labels = read_jsonl(run_dir / "artifacts" / "labels.jsonl")
    return run, observations, calls, labels


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def finalize(*, run_dir: Path, adjudication_path: Path, analysis_dir: Path,
             analysis_id: str = "t38-live-analysis") -> dict:
    run, observations, calls, labels = load_run(run_dir)
    labels_by_sample = {item["sample_id"]: item for item in labels}
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    if adjudication.get("schema_version") != SCHEMA_VERSION or adjudication.get("rubric_version") != ADJUDICATION_VERSION:
        raise ValueError("adjudication schema/rubric mismatch")
    formal = [item for item in observations
              if item["sample_id"] in labels_by_sample
              and labels_by_sample[item["sample_id"]].get("split") != "calibration"]
    if len(formal) != FORMAL_LOGICAL_CALLS:
        raise ValueError(f"formal observation count mismatch: {len(formal)}")
    verdicts = adjudication["observations"]
    missing = [item["observation_id"] for item in formal if item["observation_id"] not in verdicts]
    if missing:
        raise ValueError(f"adjudication missing observations: {missing}")
    extra = set(verdicts) - {item["observation_id"] for item in formal}
    if extra:
        raise ValueError(f"adjudication contains unknown observations: {sorted(extra)}")

    calls_by_observation: dict[str, list[dict]] = {}
    for call in calls:
        calls_by_observation.setdefault(call["observation_id"], []).append(call)

    scores = []
    rows = []
    for observation in formal:
        sample = labels_by_sample[observation["sample_id"]]
        verdict = verdicts[observation["observation_id"]]
        summary = observation.get("result_summary", {})
        expected = sample["expected_decision"]
        actual = summary.get("decision")
        valid = observation["status"] in {"success"} and actual is not None
        # Labels use approve/block; the strategies emit approve/revise/human_review/reject.
        actual_class = "approve" if actual == "approve" else ("block" if actual in BLOCK_DECISIONS else None)
        decision_correct = bool(valid and actual_class == expected and verdict.get("decision_correct"))
        closures = [item.get("result") for item in summary.get("resolutions", [])]
        expected_closures = sample.get("expected_old_results", [])
        # Only the ledger strategy can close issues; legacy has no ledger field, so it is N/A.
        closure_applicable = bool(expected_closures) and observation["variant_id"] == NEW_STRATEGY
        closure_correct = bool(verdict.get("closure_correct")) if closure_applicable else None
        false_block = bool(valid and expected == "approve" and actual != "approve")
        released_error = bool(valid and expected == "block" and actual == "approve")
        observation_calls = calls_by_observation.get(observation["observation_id"], [])
        input_tokens = [item["input_tokens"] for item in observation_calls if item["input_tokens"] is not None]
        output_tokens = [item["output_tokens"] for item in observation_calls if item["output_tokens"] is not None]
        row = {
            "observation_id": observation["observation_id"], "sample_id": observation["sample_id"],
            "variant_id": observation["variant_id"], "repeat_index": observation["repeat_index"],
            "status": observation["status"], "valid": valid, "expected": expected, "actual": actual,
            "decision_correct": decision_correct, "closure_results": closures,
            "expected_closures": expected_closures, "closure_correct": closure_correct,
            "false_block": false_block, "released_error": released_error,
            "fabrication_demand": bool(verdict.get("fabrication_demand")),
            "unfounded_closure": bool(verdict.get("unfounded_closure")),
            "suggestion_evidence_bound": verdict.get("suggestion_evidence_bound"),
            "new_defect_detected": verdict.get("new_defect_detected"),
            "physical_attempts": len(observation_calls),
            "input_tokens": sum(input_tokens) if input_tokens else None,
            "output_tokens": sum(output_tokens) if output_tokens else None,
            "end_to_end_ms": observation["end_to_end_ms"],
            "note": verdict.get("notes", ""),
        }
        rows.append(row)
        for metric_id, value, numerator, denominator, valid_score, missing_reason in (
            ("decision_correct", int(decision_correct), int(decision_correct), 1, valid, None),
            ("closure_correct", int(bool(closure_correct)) if closure_correct is not None else None,
             int(bool(closure_correct)) if closure_correct is not None else None,
             1 if closure_correct is not None else 0, closure_correct is not None,
             None if closure_correct is not None else "not_applicable_legacy_or_initial"),
            ("false_block", int(false_block), int(false_block), 1, valid, None),
            ("released_error", int(released_error), int(released_error), 1, valid, None),
            ("fabrication_demand", int(row["fabrication_demand"]), int(row["fabrication_demand"]), 1, valid, None),
            ("unfounded_closure", int(row["unfounded_closure"]), int(row["unfounded_closure"]), 1, valid, None),
            ("suggestion_evidence_bound",
             int(bool(row["suggestion_evidence_bound"])) if row["suggestion_evidence_bound"] is not None else None,
             int(bool(row["suggestion_evidence_bound"])) if row["suggestion_evidence_bound"] is not None else None,
             1 if row["suggestion_evidence_bound"] is not None else 0,
             row["suggestion_evidence_bound"] is not None, None if row["suggestion_evidence_bound"] is not None else "not_a_block_observation"),
        ):
            if not valid:
                valid_score, missing_reason = False, "invalid_observation"
            scores.append({
                "schema_version": SCHEMA_VERSION, "score_id": f"{observation['observation_id']}:{metric_id}",
                "experiment_id": EXPERIMENT_ID, "run_id": RUN_ID,
                "observation_id": observation["observation_id"], "sample_id": observation["sample_id"],
                "variant_id": observation["variant_id"], "metric_id": metric_id, "metric_version": "1.0",
                "scorer": {"type": "deterministic_plus_adjudication", "version": SCORER_VERSION,
                           "hash": sha256_json(verdict)},
                "gold_version": LABEL_VERSION, "value": value, "numerator": numerator,
                "denominator": denominator, "valid": valid_score, "missing_reason": missing_reason,
                "evidence": {"expected": expected, "actual": actual, "adjudication": verdict.get("notes", "")},
            })

    analysis_dir.mkdir(parents=True, exist_ok=False)
    with (analysis_dir / "scores.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for score in scores:
            handle.write(json.dumps(score, ensure_ascii=False) + "\n")

    def by_variant(variant: str, field: str, predicate=None) -> list:
        return [row[field] for row in rows if row["variant_id"] == variant and (predicate is None or predicate(row))]

    metrics = []
    for variant in (LEGACY_STRATEGY, NEW_STRATEGY):
        valid_rows = [row for row in rows if row["variant_id"] == variant and row["valid"]]
        decisions = [row["decision_correct"] for row in valid_rows]
        metrics.append({"variant_id": variant, "metric_id": "decision_correct_rate", "metric_version": "1.0",
                        "unit": "ratio", "aggregation": "macro", "value": sum(decisions) / len(decisions) if decisions else None,
                        "numerator": sum(decisions), "denominator": len(decisions), "n_planned": 12,
                        "n_attempted": len([row for row in rows if row["variant_id"] == variant]),
                        "n_valid": len(valid_rows), "n_failed": 12 - len(valid_rows),
                        "n_missing": 12 - len([row for row in rows if row["variant_id"] == variant]), "missing_reason": None})
        metrics.append({"variant_id": variant, "metric_id": "false_block_count", "metric_version": "1.0",
                        "unit": "count", "aggregation": "sum", "value": sum(row["false_block"] for row in valid_rows),
                        "numerator": sum(row["false_block"] for row in valid_rows), "denominator": len(valid_rows),
                        "n_planned": 12, "n_attempted": len([row for row in rows if row["variant_id"] == variant]),
                        "n_valid": len(valid_rows), "n_failed": 12 - len(valid_rows),
                        "n_missing": 12 - len([row for row in rows if row["variant_id"] == variant]), "missing_reason": None})
        metrics.append({"variant_id": variant, "metric_id": "released_error_count", "metric_version": "1.0",
                        "unit": "count", "aggregation": "sum", "value": sum(row["released_error"] for row in valid_rows),
                        "numerator": sum(row["released_error"] for row in valid_rows), "denominator": len(valid_rows),
                        "n_planned": 12, "n_attempted": len([row for row in rows if row["variant_id"] == variant]),
                        "n_valid": len(valid_rows), "n_failed": 12 - len(valid_rows),
                        "n_missing": 12 - len([row for row in rows if row["variant_id"] == variant]), "missing_reason": None})
        if variant == NEW_STRATEGY:
            closure_rows = [row for row in valid_rows if row["closure_correct"] is not None]
            closure_hits = sum(bool(row["closure_correct"]) for row in closure_rows)
            # Four ledger samples x two repeats carry an expected closure.
            closure_planned = 4 * REPEATS
            metrics.append({"variant_id": variant, "metric_id": "closure_correct_rate", "metric_version": "1.0",
                            "unit": "ratio", "aggregation": "macro",
                            "value": closure_hits / len(closure_rows) if closure_rows else None,
                            "numerator": closure_hits, "denominator": len(closure_rows), "n_planned": closure_planned,
                            "n_attempted": len(closure_rows), "n_valid": len(closure_rows),
                            "n_failed": closure_planned - len(closure_rows),
                            "n_missing": closure_planned - len(closure_rows), "missing_reason": None})
            metrics.append({"variant_id": variant, "metric_id": "fabrication_demand_count", "metric_version": "1.0",
                            "unit": "count", "aggregation": "sum", "value": sum(row["fabrication_demand"] for row in valid_rows),
                            "numerator": sum(row["fabrication_demand"] for row in valid_rows), "denominator": len(valid_rows),
                            "n_planned": 12,
                            "n_attempted": len([row for row in rows if row["variant_id"] == variant]),
                            "n_valid": len(valid_rows),
                            "n_failed": 12 - len(valid_rows), "n_missing": 0, "missing_reason": None})
            metrics.append({"variant_id": variant, "metric_id": "unfounded_closure_count", "metric_version": "1.0",
                            "unit": "count", "aggregation": "sum", "value": sum(row["unfounded_closure"] for row in valid_rows),
                            "numerator": sum(row["unfounded_closure"] for row in valid_rows), "denominator": len(valid_rows),
                            "n_planned": 12,
                            "n_attempted": len([row for row in rows if row["variant_id"] == variant]),
                            "n_valid": len(valid_rows),
                            "n_failed": 12 - len(valid_rows), "n_missing": 0, "missing_reason": None})
        block_rows = [row for row in valid_rows if row["suggestion_evidence_bound"] is not None]
        metric = {"variant_id": variant, "metric_id": "suggestion_evidence_bound_rate", "metric_version": "1.0",
                  "unit": "ratio", "aggregation": "macro",
                  "value": (sum(bool(row["suggestion_evidence_bound"]) for row in block_rows) / len(block_rows)) if block_rows else None,
                  "numerator": sum(bool(row["suggestion_evidence_bound"]) for row in block_rows),
                  "denominator": len(block_rows), "n_planned": None, "n_attempted": len(block_rows),
                  "n_valid": len(block_rows), "n_failed": 0, "n_missing": 0,
                  "missing_reason": None if block_rows else "no_block_observation"}
        metrics.append(metric)
        latencies = [row["end_to_end_ms"] for row in valid_rows]
        for metric_id, value, unit in (
            ("latency_p50_ms", _percentile(latencies, 0.50), "ms"),
            ("latency_p95_ms", _percentile(latencies, 0.95), "ms"),
            ("mean_input_tokens", statistics.fmean([row["input_tokens"] for row in valid_rows if row["input_tokens"] is not None]) if any(row["input_tokens"] is not None for row in valid_rows) else None, "tokens"),
            ("mean_output_tokens", statistics.fmean([row["output_tokens"] for row in valid_rows if row["output_tokens"] is not None]) if any(row["output_tokens"] is not None for row in valid_rows) else None, "tokens"),
        ):
            metrics.append({"variant_id": variant, "metric_id": metric_id, "metric_version": "1.0",
                            "unit": unit, "aggregation": "descriptive", "value": value,
                            "numerator": None, "denominator": None, "n_planned": None, "n_attempted": len(valid_rows),
                            "n_valid": len(valid_rows), "n_failed": 12 - len(valid_rows), "n_missing": 0,
                            "missing_reason": None if value is not None else "no_valid_values"})

    metrics_path = analysis_dir / "metrics.csv"
    metric_fields = ["analysis_id", "variant_id", "metric_id", "metric_version", "stratum", "aggregation", "unit",
                     "value", "numerator", "denominator", "n_planned", "n_attempted", "n_valid", "n_failed",
                     "n_missing", "ci_low", "ci_high", "missing_reason"]
    with metrics_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=metric_fields)
        writer.writeheader()
        for metric in metrics:
            writer.writerow({"analysis_id": analysis_id, "stratum": "all", "ci_low": "", "ci_high": "",
                             **metric})

    comparison = []
    for metric in (item for item in metrics if item["variant_id"] == NEW_STRATEGY):
        baseline = next((item for item in metrics if item["variant_id"] == LEGACY_STRATEGY
                         and item["metric_id"] == metric["metric_id"]), None)
        if baseline is None:
            continue
        base_value, cand_value = baseline.get("value"), metric.get("value")
        delta = (cand_value - base_value) if isinstance(base_value, (int, float)) and isinstance(cand_value, (int, float)) else None
        delta_unit = metric["unit"]
        if delta is not None and metric["unit"] == "ratio":
            delta, delta_unit = delta * 100, "pp"
        comparison.append({
            "analysis_id": analysis_id, "baseline_id": LEGACY_STRATEGY, "candidate_id": NEW_STRATEGY,
            "metric_id": metric["metric_id"], "metric_version": "1.0", "stratum": "all", "unit": metric["unit"],
            "baseline_value": base_value, "candidate_value": cand_value,
            "baseline_denominator": baseline.get("denominator"), "candidate_denominator": metric.get("denominator"),
            "absolute_delta": delta, "delta_unit": delta_unit,
            "relative_improvement": None, "ci_low": "", "ci_high": "", "n_pairs": min(baseline.get("n_valid") or 0, metric.get("n_valid") or 0),
            "independent_groups": 1, "criterion_ref": "T38 §11.10", "criterion_met": None,
            "conclusion": "descriptive_only", "notes": "6 clustered samples x 2 repeats; not statistically independent",
        })
    comparison_path = analysis_dir / "comparison.csv"
    comparison_fields = ["analysis_id", "baseline_id", "candidate_id", "metric_id", "metric_version", "stratum",
                         "unit", "baseline_value", "candidate_value", "baseline_denominator", "candidate_denominator",
                         "absolute_delta", "delta_unit", "relative_improvement", "ci_low", "ci_high", "n_pairs",
                         "independent_groups", "criterion_ref", "criterion_met", "conclusion", "notes"]
    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=comparison_fields)
        writer.writeheader()
        for item in comparison:
            writer.writerow(item)

    criteria = _criteria(rows, metrics)
    complete = run.get("status") == "COMPLETED"
    if any(not item["met"] for item in criteria if item["hard"]):
        status = "FAIL"
    elif not complete:
        status = "PARTIAL"
    elif all(item["met"] for item in criteria):
        status = "PASS"
    else:
        status = "FAIL"
    analysis = {
        "schema_version": SCHEMA_VERSION, "analysis_id": analysis_id, "experiment_id": EXPERIMENT_ID,
        "run_ref": "runs/" + RUN_ID, "run_hash": sha256_json(run), "dataset_version": DATASET_VERSION,
        "label_version": LABEL_VERSION, "scorer_version": SCORER_VERSION,
        "adjudication_version": ADJUDICATION_VERSION, "adjudication_hash": sha256_json(adjudication),
        "statistics": {"method": "descriptive_only", "seed": None, "bootstrap_runs": 0,
                       "reason": "6 clustered samples x 2 repeats; no independent sampling units"},
        "criteria": criteria, "status": status, "complete_matrix": complete,
        "generated_at": iso(utcnow()), "metrics": metrics, "comparison": comparison,
        "limits": [
            "只覆盖普通审核组件；无正文生成、无 Claim、无发布，不能据此证明返工或整任务可发布。",
            "六个合成样本来自同一题材族，结果只是冒烟信号，不是质量估计；统计仅描述性。",
            "语义裁定为单裁定人（主代理）加一次独立只读复核，不等同双盲人工标注。",
            "未计算金额：该部署没有冻结价格版本；只报告 token 与端到端时延。",
            "新策略 decision_correct_rate 的分母只含 10 个有效观测；2 个合同无效观测在 n_failed 中单列，不并入正确率。",
        ],
    }
    write_json(analysis_dir / "analysis.json", analysis)
    report = _report(rows, metrics, comparison, criteria, status, run, analysis)
    (analysis_dir / "report.md").write_text(report, encoding="utf-8")
    return analysis


def _criteria(rows: list[dict], metrics: list[dict]) -> list[dict]:
    def sample_rows(sample_id: str, variant: str) -> list[dict]:
        return [row for row in rows if row["sample_id"] == sample_id and row["variant_id"] == variant]

    correct_new = sample_rows(SAMPLE_CORRECT, NEW_STRATEGY)
    missing_new = sample_rows(SAMPLE_MISSING, NEW_STRATEGY)
    closure_primary = (sample_rows(SAMPLE_FIXED, NEW_STRATEGY)
                       + sample_rows(SAMPLE_FALSE_POSITIVE, NEW_STRATEGY))
    new_false_blocks = sum(row["false_block"] for row in rows if row["variant_id"] == NEW_STRATEGY and row["valid"])
    legacy_false_blocks = sum(row["false_block"] for row in rows if row["variant_id"] == LEGACY_STRATEGY and row["valid"])
    return [
        {"id": "correct_2_of_2_approve", "hard": True,
         "met": len(correct_new) == 2 and all(row["actual"] == "approve" and row["valid"] for row in correct_new),
         "observed": [{"observation_id": row["observation_id"], "actual": row["actual"], "valid": row["valid"]} for row in correct_new]},
        {"id": "missing_input_2_of_2_block_executable", "hard": True,
         "met": len(missing_new) == 2 and all(row["actual"] in BLOCK_DECISIONS and row["valid"]
                                              and row["suggestion_evidence_bound"] is True for row in missing_new),
         "observed": [{"observation_id": row["observation_id"], "actual": row["actual"],
                       "suggestion_evidence_bound": row["suggestion_evidence_bound"]} for row in missing_new]},
        {"id": "closure_at_least_3_of_4", "hard": True,
         "met": len(closure_primary) == 4 and sum(bool(row["closure_correct"]) for row in closure_primary) >= 3,
         "observed": [{"observation_id": row["observation_id"], "closure_correct": row["closure_correct"],
                       "results": row["closure_results"]} for row in closure_primary]},
        {"id": "zero_fabrication_demand", "hard": True,
         "met": sum(row["fabrication_demand"] for row in rows) == 0,
         "observed": sum(row["fabrication_demand"] for row in rows)},
        {"id": "zero_unfounded_closure", "hard": True,
         "met": sum(row["unfounded_closure"] for row in rows) == 0,
         "observed": sum(row["unfounded_closure"] for row in rows)},
        {"id": "zero_released_error", "hard": True,
         "met": sum(row["released_error"] for row in rows) == 0,
         "observed": sum(row["released_error"] for row in rows)},
        {"id": "new_false_blocks_not_above_legacy", "hard": True,
         "met": new_false_blocks <= legacy_false_blocks,
         "observed": {"new": new_false_blocks, "legacy": legacy_false_blocks}},
    ]


def _report(rows, metrics, comparison, criteria, status, run, analysis) -> str:
    lines = [
        "# T38 讲义普通审核真实模型组件验收报告", "",
        f"- 实验：`{EXPERIMENT_ID}`；运行：`{RUN_ID}`；状态：**{status}**",
        f"- 数据集：`{DATASET_ID}/{DATASET_VERSION}`；标签：`{LABEL_VERSION}`；评分：`{SCORER_VERSION}`",
        f"- 正式观测：{len(rows)}/24；运行状态：{run.get('status')}",
        f"- 模型：`{run.get('preflight', {}).get('model')}`；策略：`{NEW_STRATEGY}` vs `{LEGACY_STRATEGY}`",
        "- 范围：仅普通审核组件；无正文生成、无 Claim、无发布；结果只作冒烟证据。", "",
        "## 通过标准", "",
        "| 标准 | 硬性 | 结果 | 观测 |", "|---|---|---|---|",
    ]
    for item in criteria:
        observed = item["observed"]
        if not isinstance(observed, str):
            observed = json.dumps(observed, ensure_ascii=False)
        lines.append(f"| {item['id']} | {'是' if item['hard'] else '否'} | {'满足' if item['met'] else '未满足'} | {observed} |")
    lines += ["", "## 指标", "", "| 策略 | 指标 | 值 | 分子/分母 |", "|---|---|---|---|"]
    for metric in metrics:
        value = metric["value"]
        if isinstance(value, float):
            value = f"{value:.4f}"
        counts = f"{metric.get('numerator')}/{metric.get('denominator')}"
        if metric.get("n_planned") is not None:
            counts += f"；planned {metric['n_planned']}，valid {metric['n_valid']}，failed {metric['n_failed']}"
        lines.append(f"| {metric['variant_id']} | {metric['metric_id']} | {value} | {counts} |")
    lines += ["", "## 新旧对照", "", "| 指标 | legacy | 新策略 | 绝对差 | 单位 |", "|---|---|---|---|---|"]
    for item in comparison:
        lines.append(f"| {item['metric_id']} | {item['baseline_value']} | {item['candidate_value']} | "
                     f"{item['absolute_delta']} | {item['delta_unit']} |")
    lines += ["", "## 逐次观测", "",
              "| 观测 | 样本 | 策略 | 重复 | 状态 | 期望 | 实际 | 核销 | 误阻断 | 放行错误 | 备注 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['observation_id']} | {row['sample_id']} | {row['variant_id']} | {row['repeat_index']} | "
                     f"{row['status']} | {row['expected']} | {row['actual']} | {row['closure_results']} | "
                     f"{row['false_block']} | {row['released_error']} | {row['note'][:120]} |")
    lines += ["", "## 限制", ""]
    lines += [f"- {item}" for item in analysis["limits"]]
    lines += ["", "## 证据", "",
              "- `run.json`、`observations.jsonl`、`calls.jsonl`、`artifacts/*`、`checksums.json` 保留每次请求、响应、账本与调用计量。",
              "- `scores.jsonl` 由确定性检查与主代理语义裁定合成；`adjudication.json` 为裁定原文。",
              "- 未运行：真实正文生成返工、整任务端到端、CI、部署（NOT_RUN）。", ""]
    return "\n".join(lines)


def run_cli(*, dataset: Path | None, output: Path | None, preflight_only: bool,
            run_dir: Path | None = None, adjudication: Path | None = None,
            analysis_id: str = "t38-live-analysis") -> int:
    if preflight_only:
        if dataset is None:
            raise SystemExit("--dataset is required for preflight")
        result = preflight(dataset_root=dataset, experiment_root=output or Path("output/test-runs/t38-live"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["checks"]["ready"] else 2
    if run_dir is not None:
        if adjudication is None or output is None:
            raise SystemExit("--run, --adjudication and --output are required for finalize")
        analysis = finalize(run_dir=run_dir, adjudication_path=adjudication, analysis_dir=output,
                            analysis_id=analysis_id)
        print(json.dumps({"status": analysis["status"], "criteria": analysis["criteria"]},
                         ensure_ascii=False, indent=2))
        return 0 if analysis["status"] == "PASS" else 1
    if dataset is None or output is None:
        raise SystemExit("--dataset and --output are required for a live run")
    result = run_live(dataset_root=dataset, experiment_root=output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"COMPLETED", "PARTIAL"} else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T38 live lecture review acceptance")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--analysis-id", default="t38-live-analysis")
    args = parser.parse_args(argv)
    return run_cli(dataset=args.dataset, output=args.output, preflight_only=args.preflight,
                   run_dir=args.run, adjudication=args.adjudication,
                   analysis_id=args.analysis_id)


if __name__ == "__main__":
    raise SystemExit(main())
