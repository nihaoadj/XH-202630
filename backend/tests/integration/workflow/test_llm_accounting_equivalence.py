"""Current-code controlled equivalence, never a reconstructed historical baseline."""
import ast
import copy
import itertools
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr

from app.core.llm import accounting as a
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import LLMCallOptions, LLMUsage, RawLLMResponse
from tests.fakes.llm import ScriptedLLMTransport


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, tzinfo=timezone.utc) if tz else cls(2026, 1, 1)


def clean(value):
    if isinstance(value, BaseModel):
        return clean(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, type):
        return value.__module__ + "." + value.__name__
    return value


def gateway(outputs):
    transport = ScriptedLLMTransport([o if isinstance(o, Exception) else RawLLMResponse(
        content=o, usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)) for o in outputs])
    g = LLMGateway(transport, default_options=LLMCallOptions(max_attempts=1, structured_output_mode="text"),
        monotonic=lambda: 100.0, wall_clock=lambda: Frozen.now(timezone.utc), sleep=lambda _: None)
    return audit_options(g)


def audit_options(g):
    g.options_trace = []
    for name in ("invoke_structured", "invoke_plain_text"):
        original = getattr(g, name)
        def invoke(_original=original, **kwargs):
            observer = kwargs.get("attempt_observer")
            g.options_trace.append({"options": clean(kwargs["options"]),
                "context": clean(kwargs["context"]), "observer": type(observer).__name__})
            return _original(**kwargs)
        setattr(g, name, invoke)
    return g


def paired(monkeypatch, execute, *, fault=False):
    projections = []
    for enabled in (False, True):
        with monkeypatch.context() as m:
            counter = itertools.count(1)
            original_uuid4 = uuid.uuid4
            m.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter)))
            # Freeze only app business clocks; never delete timing/identity from projections.
            for module in list(sys.modules.values()):
                if module and getattr(module, "__name__", "").startswith("app."):
                    if getattr(module, "uuid4", None) is original_uuid4:
                        m.setattr(module, "uuid4", uuid.uuid4)
                    if getattr(module, "datetime", None) is datetime:
                        m.setattr(module, "datetime", Frozen)
                    if callable(getattr(module, "monotonic", None)):
                        m.setattr(module, "monotonic", lambda: 100.0)
            m.setattr(a, "_enabled", enabled)
            observations = []
            class Publisher:
                def submit(self, submission):
                    observations.extend(submission.segment.calls)
                    if fault:
                        raise RuntimeError("synthetic storage failure")
                    return True
            m.setattr(a, "_publisher", Publisher())
            projections.append(execute(m))
            assert bool(observations) is enabled
    def differences(left, right, path="root"):
        if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
            return [d for key in left for d in differences(left[key], right[key], f"{path}.{key}")]
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)) and len(left) == len(right):
            return [d for i, (x, y) in enumerate(zip(left, right)) for d in differences(x, y, f"{path}[{i}]")]
        return [] if left == right else [(path, left, right)]
    assert projections[0] == projections[1], f"business/request projections differ: {differences(*projections)}"


@pytest.mark.parametrize("kind", ["讲义", "案例分析", "复习清单", "分阶测试题", "实操指南", "个性化纠错训练包"])
@pytest.mark.parametrize("fault", [False, True])
def test_six_generators_have_identical_requests_and_full_artifacts(monkeypatch, kind, fault):
    from app.agents.resource_agents import get_resource_agent
    from tests.unit.agents.test_resource_type_agents import _inputs, CHECKLIST_PAYLOAD, CASE_STUDY_MARKDOWN
    from tests.unit.agents.test_practice_guide_v2 import _inputs as practice_inputs, _package
    from tests.unit.agents.test_structured_assessment import _block
    def execute(m):
        spec, ctx, _ = _inputs("讲义" if kind == "个性化纠错训练包" else kind)
        output = "# 合成讲义\n\n## 学习目标\n\n核对冻结证据。"
        if kind == "案例分析": output = CASE_STUDY_MARKDOWN
        if kind == "复习清单": output = CHECKLIST_PAYLOAD
        if kind == "分阶测试题": output = _block(spec.knowledge_points[0], spec.evidence_ids[0])
        if kind == "实操指南":
            spec, ctx = practice_inputs()
            output = _package()
        if kind == "个性化纠错训练包":
            focus = {"focus_snapshot_hash": "a" * 64, "difficulty": "中级", "scaffolding_level": "high",
                "ordered_target_nodes": [{"skill_node_id": "skill-search", "name": "检索能力", "reason_codes": ["LEARNED_OBJECTIVELY_NOT_MASTERED"]}]}
            ctx = ctx.model_copy(update={"constraints": {"correction_focus_snapshot": focus}})
            from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
            spec = build_resource_specs(run_id=ctx.run_id, resource_types=[kind], topic=ctx.topic,
                difficulty="中级", learning_plan={"correction_focus_snapshot": focus}, evidence=ctx.evidence,
                target_skill_nodes=["skill-search"])[0]
            source = Path("backend/tests/unit/agents/test_resource_type_agents.py").read_text(encoding="utf-8")
            fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "test_correction_package_requires_frozen_focus_and_complete_units")
            output = next(ast.literal_eval(n.value) for n in fn.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "content" for t in n.targets))
        g = gateway([output])
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, ctx.run_id):
            artifact = get_resource_agent(kind).generate(spec, ctx, llm_gateway=g)
        assert len(g.transport.calls) == 1 and not g.transport.outcomes
        return clean(artifact), clean(g.transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute, fault=fault)


@pytest.mark.parametrize("kind", ["复习清单", "分阶测试题"])
@pytest.mark.parametrize("terminal", [False, True])
def test_local_validation_retry_and_failure_equivalence(monkeypatch, kind, terminal):
    from app.agents.resource_agents import get_resource_agent
    from tests.unit.agents.test_resource_type_agents import _inputs, CHECKLIST_PAYLOAD
    from tests.unit.agents.test_structured_assessment import _block
    def execute(m):
        spec, ctx, _ = _inputs(kind)
        good = copy.deepcopy(CHECKLIST_PAYLOAD) if kind == "复习清单" else _block(spec.knowledge_points[0], spec.evidence_ids[0])
        bad = {**good, "skill_node_id": "wrong-node"}
        g = gateway([bad, bad if terminal else good])
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, ctx.run_id):
            try:
                result = clean(get_resource_agent(kind).generate(spec, ctx, llm_gateway=g))
                assert not terminal
            except Exception as exc:
                assert terminal
                result = (type(exc).__name__, str(getattr(exc, "code", "")), type(exc.__cause__).__name__)
        assert len(g.transport.calls) == 2 and not g.transport.outcomes
        return result, clean(g.transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute)


@pytest.mark.parametrize("stage", ["diagnose", "plan", "review", "claim"])
def test_text_stages_equivalence(monkeypatch, stage):
    from tests.integration.workflow.test_resource_aware_workflow import state_fixture
    from tests.fakes.resource_reviews import state_for, approve
    from tests.integration.workflow.test_llm_accounting_text import _state, _EXTRACT_OUTCOME
    from app.agents.learning_agents.diagnosis_agent import diagnose_node
    from app.agents.resource_workflows.learning_documents.planner_agent import plan_node
    from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node, claim_decide_node
    def execute(m):
        state = state_fixture()
        if stage == "diagnose":
            g = gateway([dict(ability_tags=[], weak_points=[], recommended_difficulty="初级", suggestion="合成建议")])
            fn = diagnose_node
        elif stage == "plan":
            from app.agents.resource_workflows.learning_documents import planner_agent
            from app.config import get_settings
            settings = get_settings().model_copy(update={"resource_aware_planner_context_tokens": 262144,
                "resource_aware_planner_input_budget_tokens": 200000})
            m.setattr(planner_agent, "get_settings", lambda: settings)
            g = gateway([dict(learning_path=[dict(order=1, topic="node", reason="合成路径")], decision_reason="冻结证据")])
            fn = plan_node
        elif stage == "review":
            state = state_for()
            g = gateway([approve()])
            fn = review_node
        else:
            state = _state()
            g = gateway([_EXTRACT_OUTCOME])
            fn = claim_extract_node
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, state["run_id"]):
            result = fn(state, llm_gateway=g)
            if stage == "claim":
                state.update(result)
                assert state["extracted_claims"]
                claim_id = state["extracted_claims"][0]["claim_id"]
                g.transport.outcomes.append(RawLLMResponse(content={"judgements": [{"claim_id": claim_id, "verdict": "supported", "evidence_ids": ["ev-claim"], "reason": "冻结依据", "confidence": 0.95}]}))
                state.update(claim_judge_node(state, llm_gateway=g))
                result = {"judge": state["claim_judgements"], "decision": claim_decide_node(state)}
        assert g.transport.calls and not g.transport.outcomes
        return clean(result), clean(g.transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute)


@pytest.mark.parametrize("damage", ["request", "result"])
def test_comparison_detects_real_request_or_result_change(monkeypatch, damage):
    from app.models.shared.llm import LLMCallContext
    class Answer(BaseModel):
        answer: str
    def execute(m):
        changed = a.is_enabled()
        g = gateway([{"answer": "changed" if changed and damage == "result" else "ok"}])
        options = g.default_options.model_copy(update={"temperature": 0.5 if changed and damage == "request" else 0.0})
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "negative"):
            result = g.invoke_structured(messages=[], output_schema=Answer, options=options,
                context=LLMCallContext(run_id="negative", step_id="s", node_name="n", schema_name="Answer"))
        return clean(result), clean(g.transport.calls)
    with pytest.raises(AssertionError, match="business/request projections differ"):
        paired(monkeypatch, execute)


@pytest.mark.parametrize("group", ["review", "practice_code", "practice_noncode"])
@pytest.mark.parametrize("revision", [False, True])
def test_courseware_content_publish_equivalence(monkeypatch, tmp_path, group, revision):
    from tests.fakes.courseware_content_review import (
        ContentReviewGateway, candidate, fixture_environment, fixture_settings, make_workflow,
    )
    from app.agents.resource_workflows.interactive_courseware import workflow as cw  # noqa: F401
    def execute(m):
        values = candidate(group)
        if revision:
            if group == "review": values["overview_lead"] = "错误候选"
            else: values["practice_cover"]["cover_lead"] = "错误候选"
        script = ContentReviewGateway(group, candidate_values=values)
        errors = []
        def respond(kwargs):
            try:
                result = script.invoke_structured(**kwargs)
                return RawLLMResponse(content=result.output.model_dump(mode="json"),
                    usage=LLMUsage(input_tokens=128, output_tokens=128, total_tokens=256))
            except Exception as exc:
                errors.append(type(exc).__name__)
                raise
        class SchemaTransport(ScriptedLLMTransport):
            def invoke(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) > 64:
                    errors.append("unexpected request loop")
                    raise AssertionError("unexpected request loop")
                return respond(kwargs)
        transport = SchemaTransport([], model_name="fixture-content-review")
        g = audit_options(LLMGateway(transport, default_options=LLMCallOptions(max_attempts=1, structured_output_mode="json_schema"),
            monotonic=lambda: 100.0, wall_clock=lambda: Frozen.now(timezone.utc), sleep=lambda _: None))
        class OfflineAdapter:
            # Preserve the existing offline TokenEstimatorProfile admission
            # contract; actual invocations still enter the real Gateway.
            offline_content_review = True
            options_for = staticmethod(g.options_for)
            invoke_structured = staticmethod(g.invoke_structured)
        settings = fixture_settings(llm_api_key=SecretStr("offline-only"))
        with fixture_environment(tmp_path, settings):
            wf, source = make_workflow(tmp_path, group, gateway=OfflineAdapter())
            from app.models.courseware import CoursewareJobCreateRequest
            job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id,
                source_resource_ids=[source.resource_id], publish_mode="automatic"))
            result = wf.run(job.run_id)
            events = wf.repo.list_events(job.run_id, 0)
            row = wf.repo.get_job(job.run_id)
        assert not errors and len(transport.calls) < 64
        schemas = [kw["output_schema"].__name__ for kw in transport.calls]
        assert "BatchResultV1" in schemas and "CoursewareReviewDecisionV2Draft" in schemas
        if revision:
            assert "RevisionPatchV1" in schemas
        assert result.status in {"published", "published_with_warnings"}
        return clean(result), clean(row), clean(events), clean(transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute)


def test_parallel_resources_equivalence(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from langchain_core.messages import HumanMessage
    from app.models.shared.llm import LLMCallContext
    class Answer(BaseModel):
        answer: str
    def execute(m):
        g = gateway([{"answer": "合成结果"}] * 4)
        def work(index):
            with a.resource_scope([f"resource-{index}"]):
                return g.invoke_structured(messages=[HumanMessage(content=f"resource-{index}")], output_schema=Answer,
                    options=g.default_options, context=LLMCallContext(run_id="parallel", step_id=f"s-{index}",
                        call_id=f"c-{index}", node_name="generator", schema_name="Answer"))
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "parallel"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(copy_context().run, work, i) for i in range(4)]
                result = [clean(f.result()) for f in futures]
        assert len(g.transport.calls) == 4 and not g.transport.outcomes
        requests = sorted(clean(g.transport.calls), key=lambda r: r["messages"][0]["content"])
        options = sorted(clean(g.options_trace), key=lambda r: r["context"]["step_id"])
        return result, requests, options
    paired(monkeypatch, execute)


def test_text_graph_to_publication_equivalence(monkeypatch):
    from app.agents.resource_workflows.learning_documents.workflow import build_workflow
    from app.services.generation.generation import build_workflow_state
    from app.models.learning_documents.schemas import GenerateRequest
    from tests.integration.workflow.test_workflow_controls import _learner
    from tests.fakes.evidence import ScriptedEvidenceRetriever, make_available_batch, make_evidence
    from tests.fakes.resource_reviews import approve
    from tests.unit.agents.test_resource_type_agents import CHECKLIST_PAYLOAD
    def execute(m):
        req = GenerateRequest(learner_id=_learner().learner_id, topic="受控检索", resource_types=["复习清单"],
            target_skill_nodes=["skill-search"], include_claim_check=False)
        state = build_workflow_state(_learner(), req, run_id="graph", lecture_review_snapshot={}, claim_extraction_snapshot={})
        g = gateway([dict(ability_tags=[], weak_points=[], recommended_difficulty="初级", suggestion="冻结建议"),
            dict(learning_path=[dict(order=1, topic="skill-search", reason="冻结路径")], decision_reason="冻结依据"),
            CHECKLIST_PAYLOAD, approve()])
        evidence = make_evidence(evidence_id="ev-new-resource-type")
        from app.agents.resource_workflows.learning_documents import workflow as module
        from tests.integration.workflow.test_workflow_controls import _trace
        def frozen_retrieve(current):
            # Isolate the non-LLM index/catalog boundary, keeping all model
            # nodes, graph routing, review and publication production code.
            return {"knowledge_base_id": evidence.knowledge_base_id, "retrieved_evidence": [evidence],
                "node_evidence_map": {"skill-search": [evidence.evidence_id]}, "retrieval_status": "available",
                "trace": [_trace(current, "retriever")], "errors": []}
        m.setattr(module, "retrieve_node", frozen_retrieve)
        graph = build_workflow(llm_gateway=g, evidence_retriever=ScriptedEvidenceRetriever([make_available_batch([evidence])]))
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "graph") as segment:
            result = graph.invoke(state)
        assert not g.transport.outcomes and len(g.transport.calls) == 4
        assert result["generated_resources"][0].publication_status == "published"
        if a.is_enabled():
            attributed = [c for c in segment.calls if c.attribution == "resource"]
            assert len(attributed) == 2
            assert all(c.resource_labels[0] == result["generated_resources"][0].resource_id for c in attributed)
        return clean(result), clean(g.transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute)


@pytest.mark.parametrize("failure", ["retry", "observer"])
def test_attempt_observer_protocol_equivalence(monkeypatch, failure):
    from app.models.shared.llm import LLMCallContext
    class Answer(BaseModel):
        answer: str
    def execute(m):
        g = gateway([TimeoutError("synthetic timeout"), {"answer": "ok"}] if failure == "retry" else [{"answer": "ok"}])
        callbacks = []
        original = ValueError("synthetic observer failure")
        class Observer:
            def before_attempt(self, context, attempt, messages, schema, mode, cap, timeout):
                callbacks.append(["before", clean(context), attempt, clean(messages), clean(schema), mode, cap, timeout])
                return SimpleNamespace(timeout_seconds=timeout, attempt=attempt)
            def after_attempt(self, ticket, raw, elapsed):
                callbacks.append(["after", ticket.attempt, clean(raw), elapsed])
                if failure == "observer":
                    raise original
                return True
            def on_attempt_error(self, ticket, error, elapsed):
                callbacks.append(["error", ticket.attempt, type(error).__name__, str(error), elapsed])
                return True
        options = g.default_options.model_copy(update={"max_attempts": 2})
        with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "observer"):
            try:
                result = clean(g.invoke_structured(messages=[], output_schema=Answer, options=options,
                    context=LLMCallContext(run_id="observer", step_id="s", node_name="n", schema_name="Answer"),
                    attempt_observer=Observer()))
                assert failure == "retry"
            except ValueError as exc:
                assert failure == "observer" and exc is original
                result = {"exception": type(exc).__name__, "message": str(exc)}
        assert [c[0] for c in callbacks] == (["before", "error", "before", "after"] if failure == "retry" else ["before", "after"])
        assert len(g.transport.calls) == (2 if failure == "retry" else 1) and not g.transport.outcomes
        return result, clean(g.transport.calls), clean(g.options_trace), callbacks
    paired(monkeypatch, execute)


def test_courseware_planner_failure_fallback_equivalence(monkeypatch, tmp_path):
    import hashlib
    from tests.integration.courseware.test_llm_accounting import _build_workflow
    from app.agents.resource_workflows.interactive_courseware import workflow as module
    def execute(m):
        settings = SimpleNamespace(courseware_ai_enabled=True, courseware_generation_mode="ai_first",
            llm_api_key=SecretStr("offline-only"))
        m.setattr("app.agents.resource_workflows.interactive_courseware.runtime.get_settings", lambda: settings)
        artifacts = []
        def store(learner, resource, content, extension, **kwargs):
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            path = tmp_path / f"{resource}.{extension}"
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            artifacts.append([resource, extension, digest, len(data)])
            return str(path), len(data), digest
        m.setattr(module, "save_courseware_html", lambda learner, resource, content, **kw: store(learner, resource, content, "html", **kw))
        m.setattr(module, "save_courseware_artifact", store)
        class FailingTransport(ScriptedLLMTransport):
            def invoke(self, **kwargs):
                self.calls.append(kwargs)
                raise RuntimeError("synthetic model unavailable")
        transport = FailingTransport([])
        g = audit_options(LLMGateway(transport, default_options=LLMCallOptions(max_attempts=1),
            monotonic=lambda: 100.0, wall_clock=lambda: Frozen.now(timezone.utc), sleep=lambda _: None))
        wf, repo, job = _build_workflow(g, str(tmp_path))
        result = wf.run(job.run_id)
        row = repo.get_job(job.run_id)
        assert result is not None and row["status"] == "release_blocked"
        assert any(w["code"] == "AI_PLAN_FALLBACK" for w in result.warnings)
        assert not artifacts
        assert transport.calls and len(transport.calls) < 20
        assert any(call["context"]["node_name"] == "courseware_spec_builder" for call in g.options_trace)
        return clean(result), clean(row), clean(repo.list_events(job.run_id, 0)), clean(transport.calls), clean(g.options_trace), artifacts
    paired(monkeypatch, execute)
