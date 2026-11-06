"""P0 LLM-call accounting baseline: freeze original behaviour, then compare.

This tool exists to prove the bypass observer does not alter business
behaviour.  It reuses the real workflow entry points with a ``ScriptedLLMTransport``
through the real ``LLMGateway`` (never a fake gateway), and freezes for each
synthetic scenario:

* the transport request sequence (messages/schema/options as seen by transport),
* a stable business projection (resource/claim/job fields, no runtime ids/times),
* the bypass accounting observations (stable payloads),
* a source fingerprint of the observed gateway methods and collector module.

``--mode record`` writes these to ``--fixture-dir`` (which must not exist or be
empty).  ``--mode compare`` re-runs every scenario against the frozen fixture
and exits non-zero on any difference, proving the harness can detect a
regression (see ``tests/unit/tooling/test_llm_accounting_baseline.py``).

This script is read-only with respect to ``app``: it never mutates production
code, never writes the business database and never calls a real model.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import re
import sys
import textwrap
from enum import Enum
from pathlib import Path
from typing import Any, Callable

# Resolve repo root and backend so ``tests.fakes`` and ``app`` both import.
_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for _p in (str(_ROOT), str(_BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core.llm import accounting  # noqa: E402
from app.core.llm.gateway import LLMGateway  # noqa: E402
from app.models.shared.llm import (  # noqa: E402
    LLMCallOptions,
    RawLLMResponse,
    StructuredOutputMode,
)
from pydantic import BaseModel  # noqa: E402
from tests.fakes.llm import ScriptedLLMTransport  # noqa: E402

MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------------
# Source fingerprint: freeze the observed entry points and collector module.
# ---------------------------------------------------------------------------
def _source_text(obj: Any) -> str:
    return inspect.getsource(obj)


def _ast_fingerprint() -> dict[str, str]:
    from app.core.llm import gateway

    def dump_source(source: str) -> str:
        tree = ast.parse(textwrap.dedent(source))
        return hashlib.sha256(ast.dump(tree, include_attributes=False).encode("utf-8")).hexdigest()

    accounting_source = Path(accounting.__file__).read_text(encoding="utf-8")
    return {
        "gateway_invoke_structured": dump_source(_source_text(LLMGateway.invoke_structured.__wrapped__)),
        "gateway_invoke_plain_text": dump_source(_source_text(LLMGateway.invoke_plain_text.__wrapped__)),
        "gateway_hard_timeout": dump_source(_source_text(gateway._invoke_transport_with_hard_timeout.__wrapped__)),
        "accounting_module": dump_source(accounting_source),
    }


# ---------------------------------------------------------------------------
# Scenario helpers.
# ---------------------------------------------------------------------------
def _stable(o: Any) -> Any:
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if isinstance(o, dict):
        return {k: _stable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_stable(v) for v in o]
    if isinstance(o, type):
        return f"<class {o.__module__}.{o.__name__}>"
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    # Fallback: best-effort primitive rendering.
    if hasattr(o, "value"):
        return o.value
    return repr(o)


class _CapturingPublisher:
    def __init__(self) -> None:
        self.submissions: list[Any] = []

    def submit(self, submission: Any) -> bool:
        self.submissions.append(submission)
        return True


def _collect_submissions() -> _CapturingPublisher:
    pub = _CapturingPublisher()
    accounting.install_publisher(pub)
    accounting.set_enabled(True)
    return pub


def _cleanup_collector() -> None:
    accounting.set_enabled(False)
    accounting.uninstall_publisher()


def _gateway(outcomes: list[Any]) -> LLMGateway:
    transport = ScriptedLLMTransport([RawLLMResponse(content=o) for o in outcomes])
    return LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5.0,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Courseware job ids are ``cw_`` + 32 hex chars (no hyphens); step ids embed a
# hyphenated UUID.  Both are per-run unstable and normalised to placeholders.
_UUID_TOKEN_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}"
)


def _observations(pub: _CapturingPublisher) -> list[dict[str, Any]]:
    """Serialize observations, mapping run-unstable identity to placeholders.

    ``segment_id`` embeds a per-process nonce, ``source_call_id`` is the
    business call UUID and ``step_id`` may be an auto-allocated UUID when no
    recorded step exists.  Each is mapped one-to-one in first-appearance order
    (T41 §8.1) so the frozen projection stays comparable while every stable
    field (stage/node/schema/model/outcome/usage/attribution) is kept intact.
    """

    call_map: dict[str, str] = {}
    step_map: dict[str, str] = {}
    run_map: dict[str, str] = {}
    call_counter = 0
    step_counter = 0
    run_counter = 0
    out: list[dict[str, Any]] = []
    for observation in pub.submissions:
        segment = observation.segment
        for call in segment.calls:
            data = call.stable_payload()
            data["segment_id"] = "segment"
            source_call_id = data.get("source_call_id")
            if isinstance(source_call_id, str) and source_call_id:
                if source_call_id not in call_map:
                    call_counter += 1
                    call_map[source_call_id] = f"<call-{call_counter}>"
                data["source_call_id"] = call_map[source_call_id]
            step_id = data.get("step_id")
            if isinstance(step_id, str) and _UUID_TOKEN_RE.search(step_id):
                def _map_step(match: "re.Match[str]") -> str:
                    nonlocal step_counter
                    token = step_map.get(match.group(0))
                    if token is None:
                        step_counter += 1
                        token = f"<step-{step_counter}>"
                        step_map[match.group(0)] = token
                    return token

                data["step_id"] = _UUID_TOKEN_RE.sub(_map_step, step_id)
            # Courseware job ids embed a fresh UUID per run; map to a placeholder.
            run_id = data.get("run_id")
            if isinstance(run_id, str) and _UUID_TOKEN_RE.search(run_id):
                if run_id not in run_map:
                    run_counter += 1
                    run_map[run_id] = f"<run-{run_counter}>"
                data["run_id"] = run_map[run_id]
            # Timing is wall-clock measured and varies run to run; pin it so the
            # frozen projection compares the stable evidence only (T41 §8.1).
            data["known_llm_duration_ms"] = 0
            for attempt in data.get("attempts", []):
                if isinstance(attempt, dict):
                    attempt["latency_ms"] = 0
            out.append(data)
    return out


# ---------------------------------------------------------------------------
# Scenarios: each returns {"projection": ..., "requests": ..., "observations": ...}
# ---------------------------------------------------------------------------
_CLAIM_OUTCOME = json.dumps(
    {
        "resources": [
            {
                "resource_id": "res-baseline",
                "claims": [
                    {
                        "claim_text": "Python 使用缩进定义代码块",
                        "claim_type": "factual",
                        "source_text": "Python 使用缩进定义代码块。",
                        "source_start": 0,
                        "source_end": 17,
                        "knowledge_point_id": "skill-python",
                        "source_evidence_ids": ["ev-baseline"],
                    }
                ],
            }
        ]
    },
    ensure_ascii=False,
)


def _claim_state() -> dict[str, Any]:
    from app.models.learning_documents.schemas import LearningResource
    from tests.fakes.evidence import make_evidence

    content = "Python 使用缩进定义代码块。"
    resource = LearningResource(
        resource_id="res-baseline",
        resource_type="讲义",
        difficulty="初级",
        content_text=content,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id="run-baseline",
        version=1,
    )
    return {
        "schema_version": "1.0",
        "run_id": "run-baseline",
        "generation_attempt": 1,
        "revision_count": 0,
        "max_iterations": 1,
        "workflow_deadline_at": None,
        "target_skill_nodes": ["skill-python"],
        "retrieved_evidence": [make_evidence(evidence_id="ev-baseline")],
        "generated_resources": [resource],
        "review_result": {
            "decision": "approve",
            "status": "approve",
            "review_ids": {"res-baseline": "review-baseline"},
            "issues": [],
            "revision_instructions": [],
            "hallucination_score": 0.1,
        },
        "include_review": True,
        "include_claim_check": True,
        "claim_check_status": "pending",
        "trace": [],
        "errors": [],
    }


_CLAIM_STABLE_FIELDS = (
    "schema_version", "run_id", "resource_id", "resource_version", "review_id",
    "claim_index", "claim_text", "claim_type", "source_text", "source_start",
    "source_end", "source_text_hash", "knowledge_point_id", "source_evidence_ids",
    "extraction_method", "extractor_model", "claim_hash",
)


def scenario_text_claim_extract() -> dict[str, Any]:
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node
    from app.agents.shared.llm_accounting import text_run_segment

    pub = _collect_submissions()
    gateway = _gateway([_CLAIM_OUTCOME])
    try:
        state = _claim_state()
        with text_run_segment("run-baseline"):
            extracted = claim_extract_node(state, llm_gateway=gateway)
        claims = [
            {k: c.get(k) for k in _CLAIM_STABLE_FIELDS}
            for c in extracted.get("extracted_claims", [])
        ]
        return {
            "projection": {"claims": claims, "claim_check_status": extracted.get("claim_check_status")},
            "requests": _stable(gateway.transport.calls),
            "observations": _observations(pub),
        }
    finally:
        _cleanup_collector()


def scenario_text_checklist_generate() -> dict[str, Any]:
    from app.agents.resource_agents.checklist import ReviewChecklistAgent
    from app.agents.shared.llm_accounting import text_run_segment

    from tests.unit.agents.test_resource_type_agents import _inputs, CHECKLIST_PAYLOAD

    pub = _collect_submissions()
    spec, context, _evidence = _inputs("复习清单")
    gateway = _gateway([json.dumps(CHECKLIST_PAYLOAD, ensure_ascii=False)])
    try:
        agent = ReviewChecklistAgent()
        with text_run_segment(context.run_id):
            artifact = agent.generate(spec, context, llm_gateway=gateway)
        metadata = artifact.metadata.model_dump(mode="json") if artifact.metadata else {}
        projection = {
            "resource_type": metadata.get("resource_type"),
            "source_evidence_ids": metadata.get("source_evidence_ids"),
        }
        return {
            "projection": projection,
            "requests": _stable(gateway.transport.calls),
            "observations": _observations(pub),
        }
    finally:
        _cleanup_collector()


def scenario_courseware_planner_fallback() -> dict[str, Any]:
    """Deterministic courseware fallback: planner transport fails -> degraded.

    Proves a failed observed call is recorded and the business still degrades
    instead of publishing.
    """
    import tempfile
    from types import SimpleNamespace
    from unittest.mock import patch

    from pydantic import SecretStr

    from app.agents.resource_workflows.interactive_courseware import (
        runtime as cw_runtime,
        workflow as cw_workflow,
    )
    from app.db.courseware.repository import MemoryCoursewareRepository
    from app.models.courseware import CoursewareJobCreateRequest
    from app.models.learning_documents.schemas import LearningResource, SourceRef
    from app.models.shared.agent_contracts import PracticeGuidePackageV3

    pub = _collect_submissions()
    gateway = _gateway(["definitely-not-json"])

    practice_payload = PracticeGuidePackageV3.model_validate({
        "schema_version": "3.0", "title": "基线实操指南",
        "preparation": {"phase_id": "prepare", "goal": "准备", "items": ["确认输入"], "evidence_ids": ["ev-1"]},
        "practice": {"phase_id": "practice", "goal": "执行", "steps": [{
            "step_id": "step-1", "title": "完成验证", "instruction_text": "按来源完成检索并记录结果。",
            "code_blocks": [], "verification": "结果可复现。", "evidence_ids": ["ev-1"]}]},
        "verification": {"phase_id": "verify", "goal": "确认", "checklist": ["结果可复现"], "evidence_ids": ["ev-1"]},
        "reflection": {"phase_id": "reflect", "goal": "复盘", "summary": "记录验证链路。", "evidence_ids": ["ev-1"]},
    }).model_dump(mode="json")
    payload_hash = hashlib.sha256(
        json.dumps(practice_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    practice_payload["payload_hash"] = payload_hash

    content = "阶段一：主题。阶段二：方法。阶段三：案例。阶段四：实践。"
    resource = LearningResource(
        resource_id="res-cw-baseline", learner_id="learner-baseline", topic="主题",
        resource_type="实操指南", difficulty="初级", content_text=content,
        knowledge_points=["k"], publication_status="published", version=1,
        exercise_items=[{"question_id": "q1", "question_type": "single_choice",
                         "question": "哪项对？", "options": ["对", "错"], "answer": "对",
                         "explanation": "x"}],
        source_refs=[SourceRef(doc_id="res-cw-baseline", title="来源", snippet=content,
                               score=1.0, knowledge_base_id="kb")],
        practice_guide_payload=practice_payload,
        practice_guide_payload_hash=payload_hash,
    )

    class SourceRepo:
        def get(self, _rid: str) -> LearningResource:
            return resource

    class AuditRepo:
        def get_run(self, _rid: str) -> Any:
            return SimpleNamespace(knowledge_base_id="kb")

    from app.services.learning_documents.resources import ResourceService

    settings = SimpleNamespace(
        courseware_ai_enabled=True,
        courseware_generation_mode="ai_first",
        llm_api_key=SecretStr("offline-scripted-key"),
    )

    repo = MemoryCoursewareRepository()
    workflow = cw_workflow.InteractiveCoursewareWorkflow(
        repo, ResourceService(SourceRepo()), AuditRepo(), llm_gateway=gateway
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _store(_learner_id, _resource_id, content_bytes, extension, **kwargs):
                path = root / f"{_resource_id}.{extension}"
                data = content_bytes if isinstance(content_bytes, bytes) else str(content_bytes).encode("utf-8")
                path.write_bytes(data)
                return str(path), path.stat().st_size, hashlib.sha256(data).hexdigest()

            with patch.object(cw_runtime, "get_settings", lambda: settings), \
                 patch.object(cw_workflow, "save_courseware_html",
                              lambda learner_id, resource_id, content, **kwargs:
                              _store(learner_id, resource_id, content, "html", **kwargs)), \
                 patch.object(cw_workflow, "save_courseware_artifact",
                              lambda learner_id, resource_id, content, extension, **kwargs:
                              _store(learner_id, resource_id, content, extension, **kwargs)):
                job = workflow.create_job(CoursewareJobCreateRequest(
                    learner_id="learner-baseline", source_resource_ids=["res-cw-baseline"],
                    title="基线课件", publish_mode="automatic",
                ))
                workflow.run(job.run_id)
        row = repo.get_job(job.run_id) or {}
        projection = {
            "status": row.get("status"),
            "error_code": row.get("error_code"),
        }
        return {
            "projection": projection,
            "requests": _stable(gateway.transport.calls),
            "observations": _observations(pub),
        }
    finally:
        _cleanup_collector()


SCENARIOS: dict[str, Callable[[], dict[str, Any]]] = {
    "text_claim_extract": scenario_text_claim_extract,
    "text_checklist_generate": scenario_text_checklist_generate,
    "courseware_planner_fallback": scenario_courseware_planner_fallback,
}


# ---------------------------------------------------------------------------
# record / compare
# ---------------------------------------------------------------------------
def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_all() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, scenario in SCENARIOS.items():
        results[name] = scenario()
    return results


def record(fixture_dir: Path, output_dir: Path) -> int:
    fixture_dir = fixture_dir.resolve()
    if fixture_dir.exists() and any(fixture_dir.iterdir()):
        print(f"ERROR: fixture dir not empty: {fixture_dir}")
        return 2
    fixture_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "llm-accounting-baseline-v1",
        "source_fingerprint": _ast_fingerprint(),
        "scenarios": sorted(SCENARIOS),
    }
    _write_json(fixture_dir / MANIFEST_NAME, manifest)

    scenarios_dir = fixture_dir / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)
    for name, result in _run_all().items():
        _write_json(scenarios_dir / f"{name}.json", result)

    summary = {"recorded": sorted(SCENARIOS)}
    _write_json(output_dir / "record-summary.json", summary)
    print(f"recorded {len(SCENARIOS)} scenarios into {fixture_dir}")
    return 0


def compare(fixture_dir: Path, output_dir: Path) -> int:
    fixture_dir = fixture_dir.resolve()
    manifest_path = fixture_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"ERROR: missing manifest: {manifest_path}")
        return 2
    manifest = _load_json(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    current_fingerprint = _ast_fingerprint()
    if manifest.get("source_fingerprint") != current_fingerprint:
        failures.append("source_fingerprint: observed gateway/collector source drifted")

    scenarios_dir = fixture_dir / "scenarios"
    for name in manifest.get("scenarios", []):
        frozen_path = scenarios_dir / f"{name}.json"
        if not frozen_path.exists():
            failures.append(f"{name}: missing frozen scenario")
            continue
        frozen = _load_json(frozen_path)
        current = SCENARIOS[name]()
        if current != frozen:
            failures.append(f"{name}: projection/requests/observations diverged")

    report = {
        "manifest": str(manifest_path),
        "scenarios_compared": len(manifest.get("scenarios", [])),
        "failures": failures,
        "passed": not failures,
    }
    _write_json(output_dir / "compare-summary.json", report)
    if failures:
        print("COMPARE FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"compare OK: {len(manifest.get('scenarios', []))} scenarios identical")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=["record", "compare"])
    parser.add_argument("--fixture-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    fixture_dir = Path(args.fixture_dir)
    output_dir = Path(args.output)
    if args.mode == "record":
        return record(fixture_dir, output_dir)
    return compare(fixture_dir, output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
