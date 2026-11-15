from datetime import datetime, timezone
import pytest

from app.core.execution import execution_session
from app.models.shared.llm import LLMUsage, RawLLMResponse
from app.models.reviews.claim_extraction import digest, check_ledger_size, validate_snapshot
from app.agents.resource_workflows.learning_documents.claim_extraction.budget import ExtractionBudget
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node
from tests.fakes.claim_extraction import state_for_extraction, neutral_settings, extract_every_unit


@pytest.mark.parametrize("count", [64, 75, 128, 129])
@pytest.mark.parametrize("use_sql", [False, True])
def test_estimate_resource_capacity_persists_full_candidates(tmp_path, monkeypatch, count, use_sql):
    from app.core.execution import ExecutionFence, execution_fence
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_judge_node
    from app.models.reviews.claim_extraction import ExtractionResult
    from tests.fakes.claim_extraction import judge_all, policy
    from tests.fakes.persistence import sqlite_repository

    settings = neutral_settings(claim_extraction_resource_claims=128, claim_extraction_batch_claims=20,
                                claim_extraction_max_calls=64, claim_extraction_max_attempts=192)
    audit = sqlite_repository(tmp_path)[0] if use_sql else None
    state, _, repo, gateway, counter = state_for_extraction(
        "\n\n".join(f"Fact {i}." for i in range(count)), settings=settings, audit=audit)
    gateway.outcomes = [extract_every_unit]*64
    monkeypatch.setattr("app.agents.resource_workflows.learning_documents.claim_review_agent.get_settings", lambda: settings)
    with execution_fence(ExecutionFence(state['run_id'], 'owner')), execution_session(state['run_id'], 'owner'):
        state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                        claim_extraction_counter=counter))
        saved = repo.get(state['run_id'])
        result = next(iter(saved.state.results.values()))
        if count == 129:
            assert result.status == 'failed' and not state.get('extracted_claims')
            return
        assert len(result.final_claims) == count and result.status == 'completed'
        # A real JSON roundtrip verifies the expanded carrier, not model_copy.
        assert len(ExtractionResult.model_validate_json(result.model_dump_json()).final_claims) == count
        gateway.outcomes = [judge_all]
        state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                     claim_extraction_counter=counter))
        assert len(state['claim_judgements']) == count
        assert len({j['claim_id'] for j in state['claim_judgements']}) == count
        assert repo.get(state['run_id']).state.results == saved.state.results
        if count > 64:
            with pytest.raises(ValueError, match='frozen resource capacity'):
                check_ledger_size(saved.policy.model_copy(update={'resource_claims':64}), saved.state)
            with pytest.raises(ValueError, match='frozen resource capacity'):
                check_ledger_size(policy(), saved.state)


@pytest.mark.parametrize('legacy', [True, False])
@pytest.mark.parametrize('use_sql', [True, False])
def test_forged_over_capacity_result_rejected_on_read_and_cas(tmp_path, legacy, use_sql):
    from app.core.execution import ExecutionFence, execution_fence
    from app.db.audit.memory import MemoryAuditRepository
    from app.db.audit.base import PersistenceError
    from app.db.shared.models import ClaimExtractionRunORM
    from app.models.reviews.claims import ClaimRecord
    from app.models.reviews.claim_extraction import ExtractionResult, content_digest, result_identity_key
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from tests.fakes.claim_extraction import prepare_ledger, policy, FixtureCounter, NeutralScriptedGateway
    from tests.fakes.persistence import sqlite_repository

    if legacy:
        p = policy(resource_claims=64, profile=policy().profile.model_copy(update={'validated_judge_claim_capacity':64}))
    else:
        p = freeze_policy(neutral_settings(claim_extraction_resource_claims=64), NeutralScriptedGateway([]), FixtureCounter())
    audit = sqlite_repository(tmp_path)[0] if use_sql else MemoryAuditRepository()
    audit, repo = prepare_ledger(audit, p=p)
    saved = repo.get('run-neutral')
    claims = [ClaimRecord(claim_id='clm_'+f'{i:032x}', run_id='run-neutral', resource_id='r', resource_version=1,
                review_id='review', claim_index=i, claim_text=f'fact {i}', claim_type='factual', source_text='f',
                source_start=i, source_end=i+1, source_text_hash=content_digest('f'),
                extractor_prompt_version=p.prompt_version, claim_hash='a'*64) for i in range(65)]
    result = ExtractionResult(resource_id='r',resource_version=1,review_id='review',content_hash='a'*64,
                              evidence_hash='b'*64,generation_attempt=1,created_at=datetime.now(timezone.utc),
                              status='completed',final_claims=claims,final_result_hash=digest(claims))
    with execution_fence(ExecutionFence('run-neutral','owner')), execution_session('run-neutral','owner') as session:
        forged = saved.state.model_copy(update=dict(active_owner='owner',execution_session_id=session.session_id,
            ledger_epoch=1,results={result_identity_key(result,saved.policy_hash):result}))
        with pytest.raises(ValueError,match='frozen resource capacity'):
            repo.compare_and_swap(saved,forged,owner='owner',session_id=session.session_id)
    if use_sql:
        with audit.session_factory() as db:
            row = db.get(ClaimExtractionRunORM,'run-neutral')
            row.state_json = forged.model_dump(mode='json')
            row.state_hash = digest(forged)
            db.commit()
    else:
        audit.claim_extraction_rows['run-neutral']['state'] = forged.model_dump(mode='json')
        audit.claim_extraction_rows['run-neutral']['state_hash'] = digest(forged)
    with pytest.raises((PersistenceError, ValueError)) as error:
        repo.get('run-neutral')
    assert 'capacity' in str(error.value.__cause__ or error.value)


def test_actual_usage_overrun_preserves_valid_result_and_blocks_next_call():
    from app.models.shared.llm import LLMCallResult,LLMAttemptSummary
    state,audit,repo,gateway,counter=state_for_extraction(settings=neutral_settings(claim_extraction_max_tokens=10000))
    def overrun(call):
        usage=LLMUsage(input_tokens=14995,output_tokens=5,total_tokens=15000)
        return LLMCallResult(output=call['output_schema'].model_validate(extract_every_unit(call)),
            call_id=call['context'].call_id,model_name='fake-model',structured_output_mode='text',
            attempt_count=1,retry_count=0,latency_ms=2,usage=usage,
            attempts=[LLMAttemptSummary(attempt=1,status='success',latency_ms=2,structured_output_mode='text',usage=usage)])
    gateway.outcomes=[overrun]
    with execution_session(state['run_id'],'owner'):
        result=claim_extract_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter)
        assert result['extracted_claims']
        saved=repo.get(state['run_id'])
        assert saved.state.tokens==15000 and saved.state.overrun_tokens==5000 and saved.state.budget_exhausted
        # A second resource cannot consume more budget; the first valid result stays auditable.
        state['generated_resources']=[state['generated_resources'][0].model_copy(update={'resource_id':'second'})]
        state['review_result']['review_ids']={'second':'second-review'}
        blocked=claim_extract_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter)
        assert blocked['claim_check_status']=='failed' and len(gateway.calls)==1
        assert any(r.final_claims for r in repo.get(state['run_id']).state.results.values())
        with pytest.raises(ValueError,match='flags'):
            check_ledger_size(saved.policy,saved.state.model_copy(update={'budget_exhausted':False,'overrun_tokens':0}))


def prepared_budget(*, settings=None, gateway=None):
    from app.agents.resource_workflows.learning_documents.claim_extraction.executor import ExtractionResult
    from app.models.reviews.claim_extraction import result_identity_key
    from app.agents.resource_workflows.learning_documents.claim_extraction.batching import plan_batches
    state,audit,repo,gateway,counter=state_for_extraction(settings=settings, gateway=gateway)
    budget=ExtractionBudget(state,repo,gateway,counter)
    resource=state['generated_resources'][0]
    result=ExtractionResult(resource_id='r',resource_version=1,review_id='review',content_hash='a'*64,
        evidence_hash='b'*64,generation_attempt=1,created_at=datetime.now(timezone.utc))
    key=result_identity_key(result,budget.current.policy_hash)
    budget.commit(budget.current.state.model_copy(update={'results':{key:result}}))
    batch=plan_batches(resource.content_text,budget.policy,counter)[0]
    return budget,budget.observer(budget.begin(key,batch))


def test_180_second_attempt_is_reserved_and_settled():
    from langchain_core.messages import HumanMessage
    from app.models.shared.llm import LLMCallContext
    from app.models.reviews.claim_extraction import BatchOutput, AttemptTicket
    from tests.fakes.claim_extraction import NeutralScriptedGateway

    class LongTimeoutGateway(NeutralScriptedGateway):
        def options_for(self, node_name, *, temperature=0.0):
            return super().options_for(node_name, temperature=temperature).model_copy(
                update={'request_timeout_seconds': 240, 'retry_request_timeout_seconds': 300})

    with execution_session('run-neutral', 'owner'):
        budget, observer = prepared_budget(settings=neutral_settings(claim_extraction_attempt_timeout_seconds=180),
                                           gateway=LongTimeoutGateway([]))
        context = LLMCallContext(run_id='run-neutral', step_id='s', node_name='claim_extractor',
                                 schema_name='BatchOutput', call_id=observer.call_id)
        ticket = observer.before_attempt(context, 1, [HumanMessage(content='data')], BatchOutput, 'text', 8192, 180)
        assert ticket.timeout_seconds == 180
        assert budget.current.state.tickets[ticket.key].time_ms == 180000
        with pytest.raises(ValueError):
            AttemptTicket.model_validate({**ticket.model_dump(), 'timeout_seconds': 181})
        assert observer.after_attempt(ticket, RawLLMResponse(content={}, usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)), 3)


def test_attempt_settlement_idempotent_and_cas_cannot_reset_budget():
    from app.models.shared.llm import LLMCallContext
    from app.models.reviews.claim_extraction import BatchOutput
    from langchain_core.messages import HumanMessage
    with execution_session('run-neutral','owner'):
        b,observer=prepared_budget()
        context=LLMCallContext(run_id='run-neutral',step_id='s',node_name='claim_extractor',schema_name='BatchOutput',call_id=observer.call_id)
        ticket=observer.before_attempt(context,1,[HumanMessage(content='data')],BatchOutput,'text',8192,60)
        raw=RawLLMResponse(content={},usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15))
        assert observer.after_attempt(ticket,raw,3)
        before=b.current
        assert observer.after_attempt(ticket,raw,3) and b.current==before
        with pytest.raises(ValueError):
            b.commit(b.current.state.model_copy(update={'tokens':0}))
        with pytest.raises(ValueError,match='order|resent'):
            observer.before_attempt(context,1,[HumanMessage(content='data')],BatchOutput,'text',8192,60)


def test_independent_mode_and_state_versions_must_match():
    state,audit,repo,_,_=state_for_extraction()
    row=repo.get(state['run_id'])
    with pytest.raises(ValueError,match='mode'):
        validate_snapshot('neutral_batch_v1',state,row)
    audit.runs[state['run_id']]['claim_extraction_mode']='neutral_batch_v1'
    from app.db.audit.base import PersistenceError
    with pytest.raises((ValueError,PersistenceError)):
        repo.get(state['run_id'])


def test_gateway_that_ignores_observer_cannot_create_free_success():
    from tests.fakes.llm import ScriptedLLMGateway
    state,_,repo,_,counter=state_for_extraction()
    gateway=ScriptedLLMGateway([extract_every_unit])
    with execution_session(state['run_id'],'owner'):
        result=claim_extract_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter)
    assert result['claim_check_status']=='failed' and not result.get('extracted_claims')
    assert repo.get(state['run_id']).state.attempts==0


def test_failed_physical_receipt_cannot_be_forged_into_valid_output():
    from tests.fakes.llm import ScriptedLLMGateway
    from app.core.llm.gateway import LLMGateway
    class ForgedGateway(ScriptedLLMGateway):
        def invoke_structured(self,**kw):
            observer=kw['attempt_observer']
            prepared=LLMGateway._text_messages(kw['messages'],kw['output_schema'])
            ticket=observer.before_attempt(kw['context'],1,prepared,kw['output_schema'],'text',kw['options'].max_output_tokens,30)
            observer.on_attempt_error(ticket,TimeoutError(),1)
            return super().invoke_structured(**kw)
    state,_,repo,_,counter=state_for_extraction()
    with execution_session(state['run_id'],'owner'):
        result=claim_extract_node(state,llm_gateway=ForgedGateway([extract_every_unit]),claim_extraction_repository=repo,claim_extraction_counter=counter)
    assert result['claim_check_status']=='failed' and not result.get('extracted_claims')
    assert next(iter(repo.get(state['run_id']).state.tickets.values())).usage_status=='unknown'


def test_sql_row_version_cannot_disagree_with_json(tmp_path):
    from tests.fakes.persistence import sqlite_repository
    from tests.fakes.claim_extraction import prepare_ledger
    from app.db.shared.models import ClaimExtractionRunORM
    from app.db.audit.base import PersistenceError
    state,_,memory,_,_=state_for_extraction()
    audit,engine=sqlite_repository(tmp_path)
    _,repo=prepare_ledger(audit,p=memory.get(state['run_id']).policy)
    with audit.session_factory() as db:
        db.get(ClaimExtractionRunORM,state['run_id']).schema_version='1.0';db.commit()
    with pytest.raises(PersistenceError,match='schema'):
        repo.get(state['run_id'])


@pytest.mark.parametrize('run_state',[None,'created','running','completed','foreign_running'])
def test_retired_worker_dispatch_fails_owned_run_and_preserves_terminal(tmp_path,run_state):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.shared.models import Base,LearnerProfileORM,GenerationJobORM,AgentRunORM
    from app.db.audit.sql_repository import SQLAuditRepository
    from app.db.generation.sql_repository import SQLGenerationJobRepository
    from app.services.generation.jobs import GenerationJobService
    from app.models.learning_documents.schemas import LearnerProfile,GenerateRequest
    from app.models.shared.persistence import CreateRunCommand,canonical_hash
    from app.models.generation.dispatch import NEUTRAL_TEXT_WORKFLOW_VERSION
    from tests.fakes.claim_extraction import policy,snapshot_for
    from types import SimpleNamespace
    engine=create_engine(f"sqlite:///{tmp_path/'retired.db'}")
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(learner_id='l',learner_type='test',education='本科',major='test',learning_goal='test'));db.commit()
    audit=SQLAuditRepository(factory);jobs=SQLGenerationJobRepository(factory)
    old=snapshot_for(policy())
    service=SimpleNamespace(freeze_claim_extraction=lambda req:old)
    dispatch=GenerationJobService(jobs,service,dispatch_mode='worker')
    learner=LearnerProfile(learner_id='l',learner_type='test',education='本科',major='test',learning_goal='test')
    request=GenerateRequest(learner_id='l',topic='test',resource_types=['讲义'],include_claim_check=True)
    job=dispatch.create_job(learner,request,run_id='retired')
    with factory() as db:
        row=db.get(GenerationJobORM,job.run_id)
        row.dispatch_snapshot={**row.dispatch_snapshot,'workflow_version':NEUTRAL_TEXT_WORKFLOW_VERSION}
        db.commit()
    if run_state:
        audit.create_run(CreateRunCommand(run_id=job.run_id,request_snapshot=old,request_hash=canonical_hash(old)))
    claim=jobs.claim_next('owner',1200)
    if run_state in {'running','completed','foreign_running'}:
        with factory() as db:
            row=db.get(AgentRunORM,job.run_id);row.status='running' if run_state=='foreign_running' else run_state
            if run_state=='foreign_running':
                row.owner_instance_id='other-owner'
            db.commit()
    released=[]
    dispatch.mastery_service=SimpleNamespace(release_failed_generation=lambda learner,**kw:released.append((learner.learner_id,kw['run_id'])))
    assert dispatch.run_claim(claim)
    with factory() as db:
        row=db.get(AgentRunORM,job.run_id)
        expected='running' if run_state=='foreign_running' else 'completed' if run_state=='completed' else 'failed'
        assert row is None if run_state is None else row.status==expected
        if row and row.status=='failed':
            assert row.lease_expires_at is None
    assert jobs.get(job.run_id).job_status==('completed' if run_state=='completed' else 'failed')
    if run_state!='completed':
        assert released==[('l',job.run_id)]
    else:
        assert released==[]
    if run_state=='foreign_running':
        from datetime import timedelta
        assert jobs.reconcile()['failed_run_ids']==[]  # Preserve the live lease.
        with factory() as db:
            row=db.get(AgentRunORM,job.run_id);row.lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        assert jobs.reconcile()['failed_run_ids']==[job.run_id]
        assert audit.get_run(job.run_id).status.value=='interrupted'


@pytest.mark.parametrize("use_sql", [False, True])
def test_policy_snapshot_roundtrip_preserves_legacy_and_density_contracts(tmp_path, use_sql):
    """T37: an old 2.0 snapshot must not gain the density key after a roundtrip."""
    import json
    from pathlib import Path
    from app.db.audit.memory import MemoryAuditRepository
    from tests.fakes.claim_extraction import (FixtureCounter, NeutralScriptedGateway, neutral_settings,
                                              prepare_ledger)
    from tests.fakes.persistence import sqlite_repository
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from app.models.reviews.claim_extraction import EstimatePolicy

    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "claim_extraction" / "density_v1" / "policies"
    legacy = EstimatePolicy.model_validate(
        json.loads((fixtures / "estimate_2_0_baseline.json").read_text(encoding="utf-8")))
    modern = freeze_policy(neutral_settings(), NeutralScriptedGateway([]), FixtureCounter())

    audit = sqlite_repository(tmp_path)[0] if use_sql else MemoryAuditRepository()
    for index, policy in enumerate((legacy, modern)):
        run_id = f"t37-policy-{'sql' if use_sql else 'mem'}-{index}"
        _, repo = prepare_ledger(audit, p=policy, run_id=run_id)
        saved = repo.get(run_id)
        assert digest(saved.policy) == digest(policy)
        assert saved.policy.model_dump(mode="json") == policy.model_dump(mode="json")
    # Legacy snapshot stays byte-identical: no materialized key, original hash.
    assert digest(repo.get("t37-policy-" + ("sql" if use_sql else "mem") + "-0").policy) == digest(legacy)
    assert "density_batching" not in repo.get("t37-policy-" + ("sql" if use_sql else "mem") + "-0").policy.model_dump(mode="json")
    # New snapshot keeps the frozen sub-contract, including its values.
    frozen = repo.get("t37-policy-" + ("sql" if use_sql else "mem") + "-1").policy
    assert frozen.density_batching is not None
    assert frozen.model_dump(mode="json")["density_batching"]["chars_per_claim"] == 35.0
