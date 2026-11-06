"""Estimate wiring and actual gateway attempts: all provider I/O is replaced."""
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.config import Settings
from app.core.llm.counting import CharacterEstimator, EstimateParameters
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.core.llm.transport import LangChainChatTransport
from app.models.shared.llm import LLMCallContext, LLMCallOptions, LLMUsage, RawLLMResponse, StructuredOutputMode
from app.models.reviews.claim_extraction import BatchOutput, ESTIMATE


@pytest.mark.parametrize('text,expected', [('a'*10,3),('中文测试字',3),('🙂🙂',2),('',0),('x=1\n',2),('| a | 1 |',3)])
def test_character_weights(text,expected):
    assert CharacterEstimator().count_text(text)==expected


def test_one_margin_on_prepared_request_and_no_giant_repair_reservation():
    counter=CharacterEstimator()
    messages=[HumanMessage(content='a'*100)]
    assert counter.estimate_prepared(messages,BatchOutput,StructuredOutputMode.TEXT)==math.ceil((30+8+128)*1.15)
    base=LLMCallOptions(structured_output_mode=StructuredOutputMode.JSON_MODE,max_attempts=1)
    assert counter.request_bound(messages,BatchOutput,base)==counter.request_bound(messages,BatchOutput,base.model_copy(update={'max_attempts':3}))
    assert counter.request_bound(messages,BatchOutput,base)<10000


@pytest.mark.parametrize('field,value',[('ascii_weight',0),('margin',float('nan')),('unicode_weight',float('inf')),('message_overhead',0)])
def test_invalid_estimates_rejected(field,value):
    with pytest.raises(ValueError):
        EstimateParameters(**{field:value})


def test_factory_needs_no_assets_and_service_graph_share_provider():
    from app.agents.resource_workflows.learning_documents.claim_extraction.profiles import load_counter
    from app.containers import Container
    counter=load_counter(Settings(_env_file=None,claim_extraction_profile_path='does-not-exist',claim_extraction_profile_id='ignored'))
    assert isinstance(counter,CharacterEstimator)
    container=Container()
    assert container.workflow.kwargs['claim_extraction_counter'] is container.claim_extraction_counter
    assert container.generation_service.kwargs['claim_extraction_counter'] is container.claim_extraction_counter


def test_policy_has_model_endpoint_thinking_and_no_calibration_fields():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from tests.fakes.claim_extraction import neutral_settings,NeutralScriptedGateway
    p=freeze_policy(neutral_settings(),NeutralScriptedGateway([]),CharacterEstimator())
    assert p.strategy==ESTIMATE and p.schema_version=='2.0'
    assert not {'profile','calibration_hash','validated_judge_claim_capacity'} & p.model_dump().keys()
    assert p.estimator_parameters.margin==0.15


@pytest.mark.parametrize('thinking',['auto','enabled'])
def test_freeze_policy_rejects_non_disabled_thinking(thinking):
    # Thinking tokens are outside the frozen character estimator; the 11-01
    # neutral run failed with thinking_mode=auto freezing an unusable output
    # budget (T36). Anything but an explicit disabled contract is rejected.
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from tests.fakes.claim_extraction import neutral_settings,NeutralScriptedGateway
    gateway=NeutralScriptedGateway([])
    gateway.transport.settings.llm_thinking_mode=thinking
    with pytest.raises(ValueError,match='disabled'):
        freeze_policy(neutral_settings(),gateway,CharacterEstimator())


def test_resource_capacity_allows_calibrated_ceiling_and_rejects_beyond():
    # T36 live run 15fd3620 produced 87 claims for a 2.8k-char lecture, above the
    # old 64 ceiling. The calibration ceiling is 128; the default stays 48.
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from tests.fakes.claim_extraction import neutral_settings,NeutralScriptedGateway
    p=freeze_policy(neutral_settings(claim_extraction_resource_claims=128),NeutralScriptedGateway([]),CharacterEstimator())
    assert p.resource_claims==128
    assert Settings(_env_file=None).claim_extraction_resource_claims==48
    with pytest.raises(ValueError):
        Settings(_env_file=None,claim_extraction_resource_claims=129)


def test_default_output_limit_is_frozen_at_32768_and_larger_values_rejected():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from app.models.reviews.claim_extraction import EstimatePolicy
    from tests.fakes.claim_extraction import NeutralScriptedGateway
    settings = Settings(_env_file=None)
    assert settings.claim_extraction_output_tokens == 32768
    policy = freeze_policy(settings, NeutralScriptedGateway([]), CharacterEstimator())
    assert policy.output_tokens == policy.extractor_options.max_output_tokens == 32768
    assert policy.extractor_options.truncated_retry_output_tokens == 32768
    assert EstimatePolicy.model_validate(policy.model_dump()).output_tokens == 32768
    with pytest.raises(ValueError):
        Settings(_env_file=None, claim_extraction_output_tokens=32769)
    with pytest.raises(ValueError):
        EstimatePolicy.model_validate({**policy.model_dump(), 'output_tokens': 32769})


def test_estimate_attempt_timeout_180_freezes_and_181_rejected():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from app.models.reviews.claim_extraction import EstimatePolicy
    from tests.fakes.llm import ScriptedLLMTransport
    settings = Settings(_env_file=None)
    gateway = LLMGateway(ScriptedLLMTransport([]), claim_request_timeout_seconds=240,
                         claim_retry_request_timeout_seconds=300)
    policy = freeze_policy(settings, gateway, CharacterEstimator())
    assert policy.attempt_timeout_seconds == 180
    assert policy.extractor_options.request_timeout_seconds == 180
    assert policy.extractor_options.retry_request_timeout_seconds == 180
    assert EstimatePolicy.model_validate(policy.model_dump()).attempt_timeout_seconds == 180
    with pytest.raises(ValueError):
        Settings(_env_file=None, claim_extraction_attempt_timeout_seconds=181)
    with pytest.raises(ValueError):
        EstimatePolicy.model_validate({**policy.model_dump(), 'attempt_timeout_seconds': 181})


def test_synthetic_estimator_cannot_masquerade_as_production():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import validate_counter
    from tests.fakes.claim_extraction import FixtureCounter
    settings=Settings(_env_file=None,llm_api_key='not-real')
    with pytest.raises(ValueError,match='synthetic'):
        validate_counter(FixtureCounter(),LLMGateway(LangChainChatTransport(settings)))


def test_offline_preflight_reports_candidate_and_configured_mode_without_assets(monkeypatch,capsys):
    from backend.scripts import claim_counting_profile as cli
    from tests.fakes.claim_extraction import NeutralScriptedGateway
    monkeypatch.setattr(cli,'Settings',lambda:Settings(_env_file=None))
    monkeypatch.setattr(cli,'default_llm_gateway',lambda:NeutralScriptedGateway([]))
    monkeypatch.setattr('sys.argv',['claim_counting_profile.py'])
    assert cli.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['configured_strategy']=='legacy_v3' and result['strategy']==ESTIMATE
    assert not result['live_executed'] and result['max_attempts']==24


def gateway_with(*responses):
    from tests.fakes.llm import ScriptedLLMTransport
    return LLMGateway(ScriptedLLMTransport(list(responses)),sleep=lambda _:None)


class Observer:
    def __init__(self,fail=None,allowed=True):
        self.events=[];self.fail=fail;self.allowed=allowed

    def before_attempt(self,*args):
        self.events.append(('before',args))
        if self.fail=='before':
            raise ValueError('no budget')
        return len(self.events)

    def after_attempt(self,*args):
        self.events.append(('after',args))
        if self.fail=='after':
            raise ValueError('CAS failed')
        return self.allowed

    def on_attempt_error(self,*args):
        self.events.append(('error',args))
        if self.fail=='error':
            raise ValueError('CAS failed')
        return self.allowed


def invoke(g,observer,mode=StructuredOutputMode.TEXT):
    return g.invoke_structured(messages=[HumanMessage(content='test JSON')],output_schema=BatchOutput,
        context=LLMCallContext(run_id='r',step_id='s',node_name='claim_extractor',schema_name='BatchOutput'),
        options=LLMCallOptions(structured_output_mode=mode,max_attempts=3),attempt_observer=observer)


def raw(content,**kw):
    return RawLLMResponse(content=content,usage=LLMUsage(input_tokens=10,output_tokens=5,total_tokens=15),**kw)


PAYLOAD=dict(resource_id='r',resource_version=1,content_hash='a'*64,batch_id='b',
             units=[dict(unit_id='u',status='structure',reason='test',claims=[])])


@pytest.mark.parametrize('mode',list(StructuredOutputMode))
def test_gateway_observes_each_actual_mode_before_parsing(mode):
    g=gateway_with(raw('{'),raw(PAYLOAD))
    observer=Observer()
    assert invoke(g,observer,mode).attempt_count==2
    assert [e[0] for e in observer.events]==['before','after','before','after']
    assert len(observer.events[2][1][2])>len(observer.events[0][1][2])  # actual repair messages


@pytest.mark.parametrize('failure',['before','after','error'])
def test_observer_failure_is_not_provider_retry(failure):
    g=gateway_with(TimeoutError() if failure=='error' else raw(PAYLOAD),raw(PAYLOAD))
    with pytest.raises(ValueError):
        invoke(g,Observer(fail=failure))
    assert len(g.transport.calls)==(0 if failure=='before' else 1)


def test_unknown_usage_disallows_repair_but_valid_response_remains_valid():
    g=gateway_with(raw('{'),raw(PAYLOAD))
    with pytest.raises(LLMGatewayError):
        invoke(g,Observer(allowed=False))
    assert len(g.transport.calls)==1
    g=gateway_with(RawLLMResponse(content=PAYLOAD))
    assert invoke(g,Observer(allowed=False)).output.resource_id=='r'


@pytest.mark.parametrize('status,body,expected',[(400,{'error':{'code':'context_length_exceeded'}},True),
    (400,{'error':{'message':'length exceeded'}},False),(401,{'code':'context_length_exceeded'},False),
    (429,{'code':'context_length_exceeded'},False),(400,{'code':'invalid_request_error'},False)])
def test_context_error_uses_only_trusted_code(status,body,expected):
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import is_context_rejection
    gateway=SimpleNamespace(transport=SimpleNamespace(settings=SimpleNamespace(llm_base_url='https://api.deepseek.com')))
    exc=Exception('arbitrary length error');exc.status_code=status;exc.body=body
    assert is_context_rejection(exc,gateway) is expected


@pytest.mark.parametrize('long_text',[False,True])
def test_production_transport_without_assets_completes_extract_and_single_judge(long_text):
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node,claim_judge_node
    from app.core.execution import execution_session
    from tests.fakes.claim_extraction import state_for_extraction,extract_every_unit,judge_all,neutral_settings
    from langchain_core.messages import AIMessage
    settings=Settings(_env_file=None,llm_model='fake-model',llm_api_key='not-real',
                      llm_base_url='http://localhost:1/v1',llm_thinking_mode='disabled')
    gateway=LLMGateway(LangChainChatTransport(settings),claim_max_attempts=1,claim_schema_repair_attempts=0,
        default_options=LLMCallOptions(structured_output_mode=StructuredOutputMode.TEXT))
    seen=[]
    class Client:
        def invoke(self,messages):
            data=json.loads(messages[-1].content)
            fn=extract_every_unit if 'target_units' in data else judge_all
            seen.append(fn.__name__)
            return AIMessage(content=json.dumps(fn({'messages':messages})),usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15})
    gateway.transport.client_factory=lambda **kw:Client()
    text='\n\n'.join(f'Fact {i}. '+('extra context '*15) for i in range(21)) if long_text else 'A fact.'
    # T37 density packing turns this 4.6k-char low-density fixture into 11 batches
    # (504 risk chars per batch at prior=35/batch_claims=16). The assertion below
    # is about "many extractions, exactly one Judge", so grant the call budget
    # explicitly instead of silently relaxing any other bound.
    state,_,repo,_,counter=state_for_extraction(text,gateway=gateway,
        settings=neutral_settings(claim_extraction_max_calls=24 if long_text else 8))
    with execution_session(state['run_id'],'owner'):
        state.update(claim_extract_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter))
        state.update(claim_judge_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter))
    assert seen[-1]=='judge_all' and seen.count('judge_all')==1
    assert seen.count('extract_every_unit')>1 if long_text else seen==['extract_every_unit','judge_all']
    assert state['claim_check_status']=='completed'
