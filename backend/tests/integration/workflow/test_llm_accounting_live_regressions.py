"""T41 real-run B1/B2 counterexamples; offline real Gateway and domain models."""
from app.agents.resource_workflows.learning_documents.claim_extraction import executor as neutral_executor
from app.core.execution import execution_session
from app.core.llm import accounting as a
from app.models.shared.llm import LLMUsage, RawLLMResponse
from app.models.shared.llm_accounting import build_task_response
from tests.integration.workflow.test_llm_accounting_equivalence import paired, gateway, clean
from tests.fakes.claim_extraction import state_for_extraction, extract_every_unit, judge_all
from tests.integration.workflow.test_claim_extraction_v2 import extract, judge
from tests.unit.models.test_llm_accounting import _observation


def test_neutral_extract_and_judge_real_gateway_equivalence(monkeypatch):
    def execute(m):
        def respond(call):
            fn = extract_every_unit if call["output_schema"].__name__ == "BatchOutput" else judge_all
            original = next(msg for msg in call["messages"] if '"target_units"' in str(msg.content) or '"allowed_evidence"' in str(msg.content))
            return RawLLMResponse(content=fn({"messages": [original]}),
                usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        from tests.fakes import claim_extraction as fixtures
        from tests.integration.workflow.test_llm_accounting_equivalence import Frozen
        m.setattr(fixtures, "datetime", Frozen)
        m.setattr(neutral_executor, "datetime", Frozen)
        g = gateway([])
        g.transport.outcomes = [respond, respond]
        state, audit, repo, _, counter = state_for_extraction(gateway=g)
        with execution_session(state["run_id"], "owner"):
            with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, state["run_id"]) as segment:
                state.update(extract(state, repo, g, counter))
                assert len(state.get("extracted_claims", [])) == 1, (state.get("trace"), state.get("errors"))
                state.update(judge(state, repo, g, counter))
                assert len(state.get("claim_judgements", [])) == 1, (state.get("trace"), state.get("errors"))
                if a.is_enabled():
                    assert [c.stage for c in segment.calls] == ["claim_extract", "claim_judge"]
                    assert all(c.resource_labels[0] == "r" for c in segment.calls)
        assert len(g.transport.calls) == 2 and not g.transport.outcomes
        return clean(state), clean(repo.get(state["run_id"]).state), clean(g.transport.calls), clean(g.options_trace)
    paired(monkeypatch, execute)


def test_exclusive_secondary_tags_do_not_multiply_partitions():
    observations = [_observation(observation_id=1, attribution="resource", resource_labels=["r", "讲义"]),
        _observation(observation_id=2, attribution="resource", resource_labels=["r", "batch"]),
        _observation(observation_id=3, attribution="resource_set", resource_labels=["r", "s"]),
        _observation(observation_id=4, attribution="task")]
    response = build_task_response(domain="learning_documents", run_id="run-1", observations=observations,
        segments=[], availability="available", coverage_complete=True)
    for field in ("observed_calls", "known_input_tokens", "known_output_tokens", "known_total_tokens"):
        assert sum(getattr(p.usage, field) for p in response.resource_partition_summaries) == getattr(response.task_summary, field)
    exclusive = [p for p in response.resource_partition_summaries if p.partition == "exclusive"]
    assert [p.label for p in exclusive] == ["r"]



def test_binding_only_resolves_current_generate_spec_and_keeps_revisions(monkeypatch):
    monkeypatch.setattr(a, "_enabled", True)
    with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "run-1") as segment:
        first = _observation(attribution="resource", resource_labels=["spec", "讲义"])
        unrelated = _observation(observation_id=2, stage="review", attribution="resource", resource_labels=["spec"])
        segment.calls = [first, unrelated]
        a.bind_generated_resource("spec", "r1")
        segment.calls.append(_observation(observation_id=3, attribution="resource", resource_labels=["spec", "讲义"]))
        a.bind_generated_resource("spec", "r2")
        a.bind_generated_resource("spec", "r3")
        assert [c.resource_labels for c in segment.calls] == [["r1", "讲义"], ["spec"], ["r2", "讲义"]]
        assert first.resource_labels == ["spec", "讲义"]  # copies, not mutation
        assert not segment.reasons


def test_binding_fault_isolated_and_marked_incomplete(monkeypatch):
    monkeypatch.setattr(a, "_enabled", True)
    class Broken:
        def __str__(self):
            raise RuntimeError("synthetic label failure")
    with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "run-1") as segment:
        a.bind_generated_resource(Broken(), "r")
        assert "resource_binding_failed" in segment.reasons
    monkeypatch.setattr(a, "_enabled", False)
    a.bind_generated_resource(Broken(), Broken())  # disabled passthrough


def test_parallel_generation_bindings_are_isolated(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    monkeypatch.setattr(a, "_enabled", True)
    with a.segment_scope(a.AccountingDomain.LEARNING_DOCUMENTS, "run-1") as segment:
        segment.calls = [_observation(observation_id=i+1, attribution="resource", resource_labels=[f"s{i}", "讲义"]) for i in range(4)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, a.bind_generated_resource, f"s{i}", f"r{i}") for i in range(4)]
            for future in futures:
                future.result()
        assert [c.resource_labels[0] for c in segment.calls] == [f"r{i}" for i in range(4)]
