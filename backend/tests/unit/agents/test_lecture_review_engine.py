"""Production lecture request/ledger tests with a scripted gateway; no model claims."""
import json
from uuid import uuid4

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine import review_lecture
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import canonical_hash
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for


def lecture_state():
    state = state_for()
    resource = state['generated_resources'][0].model_copy(update={
        'resource_type': '讲义', 'resource_spec_id': str(uuid4()), 'resource_family_id': str(uuid4()),
        'content_text': '题目：给定两个名次，计算融合结果。', 'practice_guide_payload': None,
        'practice_guide_payload_hash': None})
    policy = LectureReviewPolicyV1(context_tokens=1000000, max_output_tokens=12000).model_dump(mode='json')
    state.update(generated_resources=[resource], lecture_review_policy=policy,
                 lecture_review_policy_hash=canonical_hash(policy), lecture_ledgers={}, max_iterations=2)
    state['resource_specs']=[{'resource_spec_id':resource.resource_spec_id,'resource_family_id':resource.resource_family_id,'knowledge_points':resource.knowledge_points,'difficulty':resource.difficulty}]
    return state, resource


def response(call, *, blocking=False, resolutions=None):
    payload = json.loads(call['messages'][1].content)
    issues=[]
    if blocking:
        issues=[{'issue_id':'temporary-1','code':'other','severity':'high','blocking':True,
            'blocking_rule':'required_input','dimension':'self_contained',
            'location':{'paragraph_id':'p000001','heading_path':[],'quote':'题目'},
            'impact':'无法计算','requirement':'补充两路名次','acceptance':'列出两路名次',
            'criteria_version':1,'path':'reorganize_existing','evidence_refs':[],
            'teaching_rule_id':'self_contained','executability':'executable','rationale':'整理已有名次'}]
    return {'binding':payload['binding'],'dimensions':{'factual_evidence':'pass','coverage':'pass',
        'difficulty':'pass','self_contained':'fail' if blocking else 'pass'},
        'targets':[{'target':target,'status':'covered'} for target in payload['targets']],
        'hallucination_score':0,'issues':issues,'resolutions':resolutions or [],'reopen':[],
        'omitted_blocking_issues':False}


def invoke(state, resource, gateway, step='review-1'):
    collector=ReviewCallCollector()
    value=review_lecture(state=state,resource=resource,evidence=state['retrieved_evidence'],step_id=step,
        context=LLMCallContext(run_id=state['run_id'],step_id=step,node_name='reviewer',schema_name='LectureInitialReviewV1'),
        gateway=gateway,collector=collector,review_id='rid')
    return value,collector


def test_initial_production_call_and_frozen_window():
    state, resource=lecture_state()
    gateway=ScriptedLLMGateway([response])
    (raw, ledger, _, reason), collector=invoke(state,resource,gateway)
    assert raw['decision']=='approve' and reason is None
    assert len(gateway.calls)==len(collector.calls)==1
    assert ledger.binding.resource_spec_id==resource.resource_spec_id
    assert gateway.calls[0]['options'].max_output_tokens==12000
    assert collector.calls[0].phase=='lecture_initial_v1'


def test_recheck_same_content_false_positive_and_fixed_rejection():
    state, resource=lecture_state()
    (raw, ledger, _, _),_=invoke(state,resource,ScriptedLLMGateway([lambda c:response(c,blocking=True)]))
    assert raw['decision']=='revise'
    old_id=ledger.issues[0].issue.issue_id
    state['lecture_ledgers']={resource.resource_spec_id:ledger.model_dump(mode='json')}
    state['lecture_revision']={resource.resource_spec_id:{'previous_content':resource.content_text}}
    revised=resource.model_copy(update={'version':resource.version+1,'resource_id':'version2','parent_resource_id':resource.resource_id})
    def resolved(call, result):
        return response(call,resolutions=[{'issue_id':old_id,'result':result,'reason':'原文已包含材料',
            'previous_location':{'paragraph_id':'p000001','quote':'题目'},
            'current_location':{'paragraph_id':'p000001','quote':'题目'},'evidence_refs':[]}])
    (raw, ledger2, _, _), collector=invoke(state,revised,ScriptedLLMGateway([lambda c:resolved(c,'false_positive')]),step='review-2')
    assert raw['decision']=='approve' and ledger2.observations[-1].unchanged
    assert collector.calls[0].phase=='lecture_recheck_v1'
    with pytest.raises(ValueError,match='unchanged'):
        invoke(state,revised,ScriptedLLMGateway([lambda c:resolved(c,'fixed')]),step='review-2')


def test_input_window_fails_before_call():
    state, resource=lecture_state()
    policy=LectureReviewPolicyV1(context_tokens=12001,max_output_tokens=12000).model_dump(mode='json')
    state.update(lecture_review_policy=policy,lecture_review_policy_hash=canonical_hash(policy))
    gateway=ScriptedLLMGateway([])
    with pytest.raises(ValueError,match='window'):
        invoke(state,resource,gateway)
    assert not gateway.calls
