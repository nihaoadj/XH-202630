"""Frozen scripted inputs through the production generic resource reviewer (T44).

Drives ``review_resource_v1`` (the one shared closed loop for the six text
resources) against a frozen, hash-locked manifest, then round-trips every
produced ledger through the V4 audit envelope in a memory repository.  Zero
real model calls are made; real model quality and full end-to-end publication
are explicitly NOT_RUN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.resource_workflows.learning_documents.reviewing import ReviewCallCollector
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues import (
    review_resource_v1,
    build_revision_work_order,
)
from app.agents.resource_workflows.learning_documents.workflow import route_after_review
from app.db.audit.memory import MemoryAuditRepository
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.resource_review import ResourceLedgerV1
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash, execution_identity_fields
from app.models.reviews.review_audit import (
    ReviewAuditRecordV4,
    ReviewPolicySnapshotV1,
    ReviewResourceAuditV1,
    summarize_review_calls,
)
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    canonical_hash,
)
from tests.fakes.llm import ScriptedLLMGateway

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/resource_reviews/resource_issue_v1/manifest.json"
)

STRUCTURED_FIELD = {
    "实操指南": "practice_guide_payload",
    "分阶测试题": "assessment_payload",
    "复习清单": "review_practice_payload",
}

RUN_ID = "resource-frozen-eval"


def _state(policy: ResourceReviewPolicyV1, resource, case, revision_count: int) -> dict:
    return {
        "run_id": RUN_ID,
        "revision_count": revision_count,
        "max_iterations": 4,
        "resource_review_policy": policy.model_dump(mode="json"),
        "resource_review_policy_hash": policy_hash(policy),
        "resource_review_contract_version": "1.1",
        **execution_identity_fields("fake-model"),
        "resource_ledgers": {},
        "resource_revision": {},
        "resource_specs": [{
            "resource_spec_id": resource.resource_spec_id,
            "resource_family_id": resource.resource_family_id,
            "knowledge_points": case["targets"],
            "difficulty": resource.difficulty,
        }],
        "generated_resources": [resource],
    }


def _resolve_placeholders(template: dict, ledger_data: dict | None) -> None:
    if not ledger_data:
        return
    ids = [item["issue"]["issue_id"] for item in ledger_data["issues"]]
    for section in ("resolutions", "reopen"):
        for item in template.get(section, []):
            if isinstance(item.get("issue_id"), str) and item["issue_id"].startswith("$issue"):
                index = int(item["issue_id"][len("$issue"):]) - 1
                item["issue_id"] = ids[index]


def _memory_roundtrip(state, resource, ledger, raw, collector, step_id) -> bool:
    """Persist and read back the V4 audit envelope through the memory repo."""
    repo = MemoryAuditRepository()
    snapshot = {
        "resource_review_contract_version": "1.1",
        **execution_identity_fields("fake-model"),
        "resource_review_policy": state["resource_review_policy"],
        "resource_review_policy_hash": state["resource_review_policy_hash"],
        "review_policy": ReviewPolicySnapshotV1().model_dump(mode="json"),
    }
    now = datetime.now(timezone.utc)
    rid = f"{step_id}-rid"
    repo.create_run(CreateRunCommand(run_id=RUN_ID, request_snapshot=snapshot,
                                     request_hash=canonical_hash(snapshot), occurred_at=now))
    repo.start_run(RUN_ID, occurred_at=now)
    repo.begin_step(BeginStepCommand(run_id=RUN_ID, step_id=step_id, step_sequence=1,
                                     node_name="review", agent_name="reviewer",
                                     action="冻结审核", started_at=now))
    observation = ledger.observations[-1]
    structure_status = "failed" if observation.origin == "program_gate" else "passed"
    decision = raw["decision"]
    resource_audit = ReviewResourceAuditV1(
        resource_id=resource.resource_id, review_id=rid,
        resource_spec_id=resource.resource_spec_id, resource_type=resource.resource_type,
        structure_status=structure_status,
        semantic_status="passed" if decision == "approve" else "failed",
        decision=decision)
    policy = ResourceReviewPolicyV1.model_validate(state["resource_review_policy"])
    audit = ReviewAuditRecordV4(
        schema_version="4.0", run_id=RUN_ID, step_id=step_id, generation_attempt=1,
        revision_count=state["revision_count"], policy=ReviewPolicySnapshotV1(), decision=decision,
        node_wall_ms=1, resources=[resource_audit], calls=collector.calls,
        summary=summarize_review_calls(collector.calls),
        resource_review_policy=policy,
        resource_review_policy_hash=state["resource_review_policy_hash"],
        resource_ledgers=[ledger], repairs=[])
    command = CompleteStepCommand(
        run_id=RUN_ID, step_id=step_id,
        trace={"status": "success", "attempt": 1,
               "resource_ids": [resource.resource_id], "review_ids": [rid]},
        review_audit=audit.model_dump(mode="json"), ended_at=now)
    repo.complete_step(command)
    loaded = repo.get_step_review_audit(RUN_ID, step_id)
    return loaded.resource_ledgers[0].model_dump(mode="json") == ledger.model_dump(mode="json")


def evaluate_case(case: dict) -> dict:
    resource = LearningResource.model_validate(case["resource"])
    policy = ResourceReviewPolicyV1.model_validate(case["policy"])
    state = _state(policy, resource, case, 0)
    rows = []
    for number, review in enumerate(case["reviews"], 1):
        if number > 1:
            previous = resource
            update = {
                "content_text": review.get("content", previous.content_text),
                "version": previous.version + 1,
                "parent_resource_id": previous.resource_id,
                "resource_id": f"{case['case_id']}-v{number}",
            }
            field = STRUCTURED_FIELD.get(resource.resource_type)
            if field and review.get("payload") is not None:
                update[field] = review["payload"]
            resource = resource.model_copy(update=update)
            previous_ledger = ResourceLedgerV1.model_validate(
                state["resource_ledgers"][previous.resource_spec_id]
            )
            state["resource_revision"] = {
                resource.resource_spec_id: build_revision_work_order(
                    resource_spec_id=previous.resource_spec_id,
                    resource=previous, previous=previous_ledger,
                    revision_kind="ordinary", targets=tuple(case["targets"]),
                ).as_dict()}
            state["revision_count"] = number - 1
        template = copy.deepcopy(review["output"])
        ledger_data = state["resource_ledgers"].get(resource.resource_spec_id)
        _resolve_placeholders(template, ledger_data)

        def scripted(call):
            payload = json.loads(call["messages"][1].content)
            template["binding"] = payload["binding"]
            return template

        gateway = ScriptedLLMGateway([scripted])
        collector = ReviewCallCollector()
        step_id = f"{case['case_id']}-review{number}"
        error = None
        ledger = None
        blocked = False
        issue_states = []
        route = None
        actual = None
        roundtrip_ok = True
        try:
            outcome = review_resource_v1(
                state=state, resource=resource, evidence=[], step_id=step_id,
                context=LLMCallContext(run_id=RUN_ID, step_id=step_id, node_name="reviewer",
                                       schema_name="ResourceReviewInitialV1",
                                       generation_attempt=number),
                gateway=gateway, collector=collector, review_id=f"{step_id}-rid",
                step_guard=lambda **kw: None)
            actual = outcome.raw["decision"]
            ledger = outcome.ledger
            blocked = ledger is None
            if ledger is not None:
                state["resource_ledgers"][resource.resource_spec_id] = ledger.model_dump(mode="json")
                issue_states = [item.status for item in ledger.issues]
                roundtrip_ok = _memory_roundtrip(state, resource, ledger, outcome.raw, collector, step_id)
            route = route_after_review({
                **state, "include_claim_check": False,
                "generated_resources": [resource],
                "review_result": outcome.raw,
                "resource_executions": [],
            })
        except Exception as exc:  # noqa: BLE001 - record any engine failure verbatim
            actual = "invalid"
            error = f"{type(exc).__name__}: {exc}"
        calls = len(gateway.calls)
        rows.append({
            "review": number,
            "expected": review["expected"],
            "actual": actual,
            "blocked": blocked,
            "calls": calls,
            "issue_states": issue_states,
            "route": route,
            "roundtrip_ok": roundtrip_ok,
            "error": error,
            "passed": (
                actual == review["expected"]
                and blocked == review.get("expected_blocked", False)
                and calls == review["expected_calls"]
                and issue_states == review["expected_issue_states"]
                and route == review["expected_route"]
                and roundtrip_ok
                and error is None
            ),
        })
        if error is not None:
            break
    return {
        "case_id": case["case_id"],
        "resource_type": case.get("resource_type"),
        "label": case.get("label"),
        "passed": len(rows) == len(case["reviews"]) and all(row["passed"] for row in rows),
        "reviews": rows,
    }


def evaluate(manifest: Path) -> dict:
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0" or len(data["cases"]) < 60:
        raise ValueError("resource frozen manifest incomplete")
    if len({case["case_id"] for case in data["cases"]}) != len(data["cases"]):
        raise ValueError("duplicate case identity")
    results = []
    for case in data["cases"]:
        if case["input_hash"] != canonical_hash({k: v for k, v in case.items() if k != "input_hash"}):
            raise ValueError("resource fixture hash mismatch")
        results.append(evaluate_case(case))
    return {
        "schema_version": "1.0",
        "status": "PASS" if all(r["passed"] for r in results) else "FAIL",
        "evidence_type": "offline_scripted_policy",
        "real_model_quality": "NOT_RUN_LIVE",
        "end_to_end": "NOT_RUN",
        "manifest_hash": hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline"], default="offline")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode != "offline":
        parser.error("only --mode offline is supported")
    if args.output is None:
        parser.error("--output is required")
    if args.output.exists():
        parser.error("output must not already exist")
    result = evaluate(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{result['status']}: {len(result['results'])} frozen cases; real model quality NOT_RUN_LIVE")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
