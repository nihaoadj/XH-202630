"""Synthetic-only Claim fixtures. No provider clients, credentials or .env."""
from datetime import datetime, timedelta, timezone

from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.extraction import extraction_repository
from app.models.reviews.claim_extraction import CountingProfile, ExtractionPolicy, ESTIMATE, digest
from app.core.llm.counting import CharacterEstimator
from app.models.shared.llm import LLMCallOptions
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.models.reviews.claim_extraction import OfflineClaimGateway, OfflineClaimTransport, OfflineClaimCounter, encoded
from tests.fakes.llm import ScriptedLLMGateway, ScriptedLLMTransport


class NeutralScriptedGateway(OfflineClaimGateway, ScriptedLLMGateway):
    def invoke_structured(self, **kwargs):
        from app.core.llm.gateway import LLMGateway, LLMGatewayError
        from app.models.shared.llm import RawLLMResponse, LLMUsage, LLMAttemptSummary
        from app.core.llm.structured_output import StructuredOutputError
        from app.models.shared.agent_contracts import make_error_info
        observer=kwargs.get("attempt_observer")
        if observer is None:
            return super().invoke_structured(**kwargs)
        options=kwargs["options"]
        prepared=LLMGateway._text_messages(kwargs["messages"],kwargs["output_schema"])
        ticket=observer.before_attempt(kwargs["context"],1,prepared,kwargs["output_schema"],"text",options.max_output_tokens,options.request_timeout_seconds)
        try:
            result=super().invoke_structured(**kwargs)
        except LLMGatewayError as exc:
            usage=exc.attempts[0].usage if len(exc.attempts)==1 else LLMUsage()
            observer.after_attempt(ticket,RawLLMResponse(content=None,usage=usage),exc.latency_ms)
            raise
        except StructuredOutputError as exc:
            usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15)
            observer.after_attempt(ticket,RawLLMResponse(content=None,usage=usage),2)
            raise LLMGatewayError(error=make_error_info(exc.code,source="claim_extractor"),call_id=kwargs["context"].call_id,
                retry_count=0,latency_ms=2,attempts=[LLMAttemptSummary(attempt=1,status="failed",latency_ms=2,structured_output_mode="text",usage=usage)]) from exc
        except Exception as exc:
            observer.on_attempt_error(ticket,exc,2)
            raise
        result=result.model_copy(update={"call_id":kwargs["context"].call_id})
        observer.after_attempt(ticket,RawLLMResponse(content=result.output,usage=result.usage),result.latency_ms)
        return result


class NeutralScriptedTransport(OfflineClaimTransport, ScriptedLLMTransport):
    pass


class FixtureCounter(OfflineClaimCounter, CharacterEstimator):
    """UTF-8 byte accounting for synthetic protocol tests; never a real tokenizer."""
    def __init__(self, **updates):
        super().__init__()
        self.profile = policy().profile.model_copy(update=updates)

    def count_text(self, text):
        return len(text.encode("utf-8"))

    def request_bound(self, messages, schema, options):
        return self.estimate_prepared(messages, schema, "text")

    def estimate_prepared(self, messages, schema, mode):
        # Synthetic byte units preserve frozen small-budget fixtures. Production
        # wrapper/margin tests use CharacterEstimator and the actual gateway.
        import json
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            return sum(self.count_text(str(m.content)) for m in messages)
        if "target_units" in payload:
            return max(1, sum(self.count_text(u["text"]) for u in payload["target_units"]))
        return max(1, self.count_text(encoded(payload)))


def neutral_settings(**updates):
    from app.config import Settings
    updates.setdefault("claim_extraction_output_tokens", 8192)
    updates.setdefault("claim_extraction_attempt_timeout_seconds", 60)
    # Existing estimate fixtures freeze the historical v1 prompt (no source
    # locating). New v2 tests pass claim_extraction_source_locating_mode
    # explicitly ("exact_v1"/"tolerant_v1").
    updates.setdefault("claim_extraction_source_locating_mode", None)
    return Settings(_env_file=None, claim_extraction_strategy=ESTIMATE,
                    claim_extraction_profile_id="fixture-claim-v1", **updates)


def policy(**updates):
    options = LLMCallOptions(max_attempts=1, schema_repair_attempts=0, max_output_tokens=8192,
        truncated_retry_output_tokens=8192, request_timeout_seconds=60, retry_request_timeout_seconds=60)
    values = dict(profile=CountingProfile(profile_id="fixture-claim-v1", model_name="fake-model",
        tokenizer_version="synthetic-utf8-v1", wire_version="synthetic-chat-v1", context_tokens=262144,
        validated_judge_claim_capacity=48, calibration_hash="a" * 64, fixture_only=True),
        judge_options=LLMCallOptions(), judge_prompt_hash="b" * 64, judge_schema_hash="c" * 64,
        judge_reserve_seconds=60, extractor_options=options, backoff_seconds=0)
    values.update(updates)
    return ExtractionPolicy(**values)


def snapshot_for(p):
    return dict(include_claim_check=True, claim_extraction_mode=p.strategy,
                claim_extraction_policy=p.model_dump(mode="json"), claim_extraction_policy_hash=digest(p))


def prepare_ledger(audit=None, p=None, run_id="run-neutral", seconds=1200, owner="owner"):
    audit = audit or MemoryAuditRepository()
    p = p or policy()
    now = datetime.now(timezone.utc)
    snapshot = snapshot_for(p)
    audit.create_run(CreateRunCommand(run_id=run_id, request_snapshot=snapshot, request_hash=canonical_hash(snapshot),
        owner_instance_id=owner, lease_expires_at=now + timedelta(seconds=seconds)))
    audit.start_run(run_id, occurred_at=now, lease_expires_at=now + timedelta(seconds=seconds))
    return audit, extraction_repository(audit)


def state_for_extraction(text="A fact.", *, settings=None, gateway=None, audit=None):
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from app.models.learning_documents.schemas import LearningResource
    from tests.fakes.evidence import make_evidence
    gateway = gateway or NeutralScriptedGateway([])
    from app.core.llm.gateway import LLMGateway
    counter = CharacterEstimator() if isinstance(gateway, LLMGateway) else FixtureCounter()
    p = freeze_policy(settings or neutral_settings(), gateway, counter)
    audit, repo = prepare_ledger(audit, p)
    resource = LearningResource(resource_id="r", resource_type="讲义", difficulty="初级", content_text=text,
        knowledge_points=["k"], source_refs=[], version=1, run_id="run-neutral")
    state = dict(run_id="run-neutral", generation_attempt=1, revision_count=0, claim_revision_count=0,
        target_skill_nodes=["k"], generated_resources=[resource], retrieved_evidence=[make_evidence(evidence_id="ev")],
        review_result=dict(decision="approve", status="approve", review_ids={"r": "review"}),
        include_review=True, claim_check_status="pending", trace=[], errors=[],
        max_iterations=1, claim_max_iterations=0, workflow_deadline_at=datetime.now(timezone.utc)+timedelta(seconds=1200),
        **snapshot_for(p))
    return state, audit, repo, gateway, counter


def extract_every_unit(call):
    import json
    payload = json.loads(call["messages"][-1].content)
    units = []
    for u in payload["target_units"]:
        source = u["text"]
        if not source.strip() or u["kind"] == "heading":
            units.append(dict(unit_id=u["unit_id"], status="whitespace" if not source.strip() else "structure", reason="synthetic", claims=[]))
        else:
            units.append(dict(unit_id=u["unit_id"], status="claims", reason="synthetic", claims=[dict(
                claim_text=source.strip(), source_text=source, source_start=0, source_end=len(source),
                claim_type="factual", knowledge_point_id=None)]))
    return {k: payload[k] for k in ("resource_id", "resource_version", "content_hash", "batch_id")} | {"units": units}


def extract_every_unit_v2(call):
    """Offset-free v2 extraction: verbatim unit copy, no source_start/source_end."""
    import json
    payload = json.loads(call["messages"][-1].content)
    units = []
    for u in payload["target_units"]:
        source = u["text"]
        if not source.strip() or u["kind"] == "heading":
            units.append(dict(unit_id=u["unit_id"],
                              status="whitespace" if not source.strip() else "structure",
                              reason="synthetic", claims=[]))
        else:
            units.append(dict(unit_id=u["unit_id"], status="claims", reason="synthetic",
                              claims=[dict(claim_text=source.strip(), source_text=source,
                                           claim_type="factual", knowledge_point_id=None)]))
    return {k: payload[k] for k in ("resource_id", "resource_version", "content_hash", "batch_id")} | {"units": units}


def judge_all(call):
    import json
    payload = json.loads(call["messages"][-1].content)
    return dict(judgements=[dict(claim_id=c["claim_id"], verdict="supported" if c["claim_type"] == "factual" else "non_factual",
        evidence_ids=[payload["allowed_evidence"][0]["evidence_id"]] if c["claim_type"] == "factual" else [],
        reason="synthetic frozen evidence", confidence=1) for c in payload["claims"]])


def graph_service(patch, audit, resources, claims, *, settings=None, gateway=None, counter=None,
                  content="A fact.", fail_first_judge=False, service_counter_only=False, output_path="synthetic.md"):
    """Real text graph and service; only non-Claim Agents/readiness are scripted."""
    from types import SimpleNamespace
    from app.agents.resource_workflows.learning_documents import workflow as graph_module
    from app.models.shared.agent_contracts import build_trace_item
    from app.models.shared.workflow import StepStatus
    from app.models.learning_documents.schemas import LearningResource
    from app.services.generation import generation as service_module
    from app.services.generation import jobs as jobs_module
    from app.services.generation.generation import GenerationService
    from tests.fakes.evidence import make_evidence
    settings = settings or neutral_settings(resource_aware_retrieval_enabled=False)
    counter = counter or FixtureCounter()
    def route(call):
        if call["context"].node_name == "claim_extractor":
            return extract_every_unit(call)
        result = judge_all(call)
        if fail_first_judge and call["context"].generation_attempt == 1:
            for j in result["judgements"]:
                j.update(verdict="not_in_evidence", evidence_ids=[])
        return result
    gateway = gateway or NeutralScriptedGateway([route]*64)
    patch.setattr(service_module, "get_settings", lambda: settings)
    patch.setattr(graph_module, "get_settings", lambda: settings)
    # jobs._dispatch_snapshot freezes the lecture review policy with its own
    # get_settings import; isolate it too so the frozen claim workflow version
    # is not overwritten by a real .env lecture strategy.
    patch.setattr(jobs_module, "get_settings", lambda: settings)
    patch.setattr(service_module, "ensure_generation_ready", lambda **_: SimpleNamespace(status="ready", error_codes=[]))
    patch.setattr(service_module, "save_text_resource", lambda **kw: (str(output_path), len(kw["text"].encode()), "text/markdown"))
    def trace(state, name, ids=()):
        item = build_trace_item(state, agent_name=name, action=name, status=StepStatus.SUCCESS,
            input_summary="synthetic prerequisite", output_summary="synthetic prerequisite", decision_reason="fixture",
            resource_ids=list(ids))
        # The real generator persists resources through its immediate recorder.
        # This prerequisite fake uses the recorder's legacy merge boundary.
        if name == "generator":
            item["node_name"] = "generator"
        return item
    patch.setattr(graph_module, "diagnose_node", lambda state: dict(diagnosis={}, trace=[trace(state, "diagnosis")], errors=[]))
    def retrieve(state):
        evidence = make_evidence(evidence_id="ev-"+state["run_id"], knowledge_base_id="kb-fixture")
        return dict(retrieved_evidence=[evidence], retrieval_status="available", retrieval_config_hash=evidence.config_hash,
            retrieval_query_hashes=[evidence.query_hash], retrieval_candidate_count=1,
            trace=[trace(state, "retriever")], errors=[])
    patch.setattr(graph_module, "retrieve_node", retrieve)
    patch.setattr(graph_module, "plan_node", lambda state: dict(learning_plan={}, trace=[trace(state, "planner")], errors=[]))
    def generate(state):
        attempt = state["generation_attempt"]
        prior = state.get("generated_resources", [])
        source = state.get("regeneration_source")
        specs = state.get("resource_specs", [])
        spec = specs[0] if specs else {}
        resource = LearningResource(resource_id=f"r-{state['run_id']}-{attempt}", resource_type=state["resource_types"][0],
            difficulty="初级", content_text=content, knowledge_points=["k"], source_refs=[], version=(source.version if source else 0)+attempt,
            resource_spec_id=spec.get("resource_spec_id"), resource_family_id=spec.get("resource_family_id"),
            run_id=state["run_id"], parent_resource_id=prior[0].resource_id if prior else source.resource_id if source else None)
        return dict(generated_resources=[resource], trace=[trace(state, "generator", [resource.resource_id])], errors=[])
    patch.setattr(graph_module, "generate_node", generate)
    def review(state):
        ids = {r.resource_id: f"review-{r.resource_id}" for r in state["generated_resources"]}
        return dict(review_result=dict(decision="approve", status="approve", passed=True, review_ids=ids,
            issues=[], revision_instructions=[], hallucination_score=0), resource_review_results={},
            trace=[trace(state, "reviewer", ids)], errors=[])
    patch.setattr(graph_module, "review_node", review)
    graph = graph_module.build_workflow(llm_gateway=gateway, lifecycle_repository=audit,
        claim_extraction_counter=None if service_counter_only else counter)
    service = GenerationService(resources, graph, audit, claim_repo=claims,
        claim_extraction_gateway=gateway, claim_extraction_counter=counter)
    return service, gateway, counter
