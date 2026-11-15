"""Checklist dependencies, source identity and shared Judge regression; no live LLM."""
import json
from types import SimpleNamespace

import pytest

from app.agents.resource_agents.checklist import _canonical_hash, render_review_practice_markdown
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import (
    build_source, source_for_claims, legacy_extension, CHECKLIST_CONTEXT_PROMPT_VERSION,
    CHECKLIST_GUIDANCE,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import build_messages
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_judge_node
from app.core.execution import execution_session
from app.models.reviews.claim_extraction import ExtractionBatch, ExtractionUnit, Span, digest
from app.models.reviews.claims import ClaimCandidate
from tests.integration.workflow.test_structured_claim_sources import setup_source, extract_and_judge
from tests.fakes.claim_extraction import judge_all, extract_every_unit_v2


def prepare(*, truth=True, locating=True, statement='RAG在生成前检索外部知识。'):
    state, audit, repo, gateway, counter = setup_source('复习清单', locating=locating)
    r = state['generated_resources'][0]
    p = r.review_practice_payload
    q = p['node_blocks'][0]['distinction_questions'][0]
    q.update(statement=statement, truth_value=truth,
             correction='无需纠正。' if truth else 'RAG不能保证事实正确。',
             explanation='与 Evidence 中 RAG 核心矛盾的描述一致。')
    p['payload_hash'] = _canonical_hash({k:v for k,v in p.items() if k != 'payload_hash'})
    r.content_text = render_review_practice_markdown(p)
    policy = repo.get(state['run_id']).policy
    return state, audit, repo, gateway, counter, build_source(r, policy), policy


def one_field(source, suffix, *, context=False):
    f = next(f for f in source.fields if f['path'].endswith(suffix))
    return ExtractionBatch(batch_id='focused', units=[ExtractionUnit(
        unit_id='u', kind='paragraph', start=f['start'], end=f['end'])],
        context=[Span(start=0,end=len(source.text))] if context else [])


@pytest.mark.parametrize('locating', [False, True])
def test_split_explanation_carries_statement_once_and_counts_wire_input(locating):
    state, _, _, _, _, source, policy = prepare(locating=locating)
    batch = one_field(source, 'distinction_questions[0].explanation', context=True)
    messages = build_messages(source.text, state['generated_resources'][0], batch, policy, {'k'})
    payload = json.loads(messages[-1].content)
    related = payload['structured_context']['read_only_related_fields']
    assert len(related) == 1
    assert related[0]['role'] == 'answer_proposition'
    assert related[0]['text'] == 'RAG在生成前检索外部知识。'
    assert messages[-1].content.count(related[0]['text']) == 1
    assert payload['structured_context']['read_only_answer_keys'] == {
        'node_blocks[0].distinction_questions[0]': {'truth_value': True}}
    assert CHECKLIST_GUIDANCE in messages[0].content
    from app.core.llm.counting import CharacterEstimator
    from app.models.reviews.claim_extraction import BatchOutputV2, BatchOutput
    counter = CharacterEstimator()
    schema = BatchOutputV2 if locating else BatchOutput
    full = counter.estimate_prepared(messages, schema, 'text')
    payload['structured_context']['read_only_related_fields'] = []
    messages[-1].content = json.dumps(payload, ensure_ascii=False)
    assert counter.estimate_prepared(messages, schema, 'text') < full


def test_true_statement_is_target_but_false_statement_remains_exercise():
    for truth, expected in [(True,'answer_proposition'),(False,'exercise_proposition')]:
        *_, source, policy = prepare(truth=truth)
        f = next(f for f in source.fields if f['path'].endswith('.statement'))
        raw = source.text[f['start']:f['end']]
        claim = ClaimCandidate(claim_text=raw,source_text=raw,source_start=f['start'],
                               source_end=f['end'],claim_type='factual')
        assert f['role'] == expected
        assert source.classify([claim])[0].claim_type.value == ('factual' if truth else 'non_factual')


def test_exact_quote_stays_original_when_claim_resolves_subject():
    state, _, _, _, _, _, policy = prepare()
    r=state['generated_resources'][0];p=r.review_practice_payload
    q=p['node_blocks'][0]['recall_questions'][0]
    q.update(prompt='RAG在生成前做什么？',reference_answer='它在生成前检索外部知识。')
    p['payload_hash']=_canonical_hash({k:v for k,v in p.items() if k!='payload_hash'})
    r.content_text=render_review_practice_markdown(p)
    source=build_source(r,policy)
    f=next(f for f in source.fields if f['path'].endswith('recall_questions[0].reference_answer'))
    raw=source.text[f['start']:f['end']]
    batch=one_field(source,'recall_questions[0].reference_answer')
    from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output_with_diagnostics
    from app.models.reviews.claim_extraction import BatchOutputV2, content_digest
    output=BatchOutputV2.model_validate(dict(resource_id=r.resource_id,resource_version=r.version,
        content_hash=content_digest(source.text),batch_id=batch.batch_id,units=[dict(
        unit_id='u',status='claims',reason='主体由关联题干消歧',claims=[dict(
        claim_text='RAG在生成前检索外部知识。',source_text=raw,claim_type='factual')])]))
    candidates,_=validate_output_with_diagnostics(source.text,batch,output,resource=r,policy=policy,allowed_nodes={'k'})
    claim=source.classify(candidates)[0]
    assert claim.source_text=='它在生成前检索外部知识。'
    assert claim.claim_text=='RAG在生成前检索外部知识。'
    assert source.text[claim.source_start:claim.source_end]==claim.source_text
    with pytest.raises(ValueError, match='exactly one'):
        source.classify([claim.model_copy(update={'source_start':f['start']-1})])


def test_old_policy_rebuild_and_new_marker_are_distinct():
    state, _, _, _, _, new, policy = prepare()
    old_policy = policy.model_copy(update={'structured_sources':legacy_extension()})
    before = digest(old_policy)
    r = state['generated_resources'][0]
    old = build_source(r, old_policy)
    assert old.prompt_version == 'structured-checklist-v1'
    assert new.prompt_version == CHECKLIST_CONTEXT_PROMPT_VERSION
    assert old.text != new.text  # author-endorsed target has a versioned role
    assert source_for_claims(r,[SimpleNamespace(extractor_prompt_version=old.prompt_version)]).snapshot == old.snapshot
    assert source_for_claims(r,[SimpleNamespace(extractor_prompt_version=new.prompt_version)]).snapshot == new.snapshot
    assert digest(old_policy) == before
    with pytest.raises(ValueError,match='mixed'):
        source_for_claims(r,[SimpleNamespace(extractor_prompt_version=old.prompt_version),
                             SimpleNamespace(extractor_prompt_version=new.prompt_version)])


def test_wrong_endorsed_knowledge_is_audited_and_not_auto_published():
    state, _, repo, gateway, counter, _, _ = prepare(statement='RAG能够保证所有答案事实正确。')
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_decide_node
    from app.agents.resource_workflows.learning_documents.workflow import decide_node
    gateway.outcomes=[extract_every_unit_v2]*32
    with execution_session(state['run_id'],'owner'):
        state.update(claim_extract_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter))
        chosen=next(c for c in state['extracted_claims'] if c['source_text']=='RAG能够保证所有答案事实正确。')
        assert chosen['claim_type']=='factual'
        def reject(call):
            output=judge_all(call)
            for j in output['judgements']:
                if j['claim_id']==chosen['claim_id']: j['verdict']='contradicted'
            return output
        gateway.outcomes=[reject]
        state.update(claim_judge_node(state,llm_gateway=gateway,claim_extraction_repository=repo,claim_extraction_counter=counter))
    assert state['claim_metrics']['r']['contradicted_claim_total']==1
    state.update(claim_decide_node(state))
    assert decide_node(state)['generated_resources'][0].publication_status=='unpublished'


def test_example_background_is_complete_across_batch_and_stays_read_only():
    state, _, _, _, _, _, policy=prepare()
    r=state['generated_resources'][0];p=r.review_practice_payload;b=p['node_blocks'][0]
    b['example_recognition_questions']=[dict(local_id='example-1',
        candidate_a='Q3没有日期时，系统明确说明缺少资料或拒答。',
        candidate_b='Q3没有日期时，系统凭模型记忆补出一个报名截止日期。',
        positive_candidate='A',decisive_boundary='无证据时不得编造日期。',
        explanation='Evidence明确要求无答案时不得编造，正例为如实说明缺少资料。',
        evidence_ids=['ev'],pass_criteria='判断正反例。')]
    b['omitted_slots']=[x for x in b['omitted_slots'] if x['local_id']!='example-1']
    p['payload_hash']=_canonical_hash({k:v for k,v in p.items() if k!='payload_hash'})
    r.content_text=render_review_practice_markdown(p)
    source=build_source(r,policy)
    batch=one_field(source,'example_recognition_questions[0].explanation')
    payload=json.loads(build_messages(source.text,r,batch,policy,{'k'})[-1].content)
    related=payload['structured_context']['read_only_related_fields']
    assert {f['path'].rsplit('.',1)[1] for f in related}=={'candidate_a','candidate_b'}
    assert all(f['role']=='exercise_option' for f in related)
    assert payload['structured_context']['read_only_answer_keys']=={
        'node_blocks[0].example_recognition_questions[0]':{'positive_candidate':'A'}}
    # A model cannot cite the background as if it belonged to this target.
    from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output_with_diagnostics
    from app.models.reviews.claim_extraction import BatchOutputV2, content_digest
    output=BatchOutputV2.model_validate(dict(resource_id=r.resource_id,resource_version=r.version,
        content_hash=content_digest(source.text),batch_id=batch.batch_id,units=[dict(
        unit_id='u',status='claims',reason='bad source',claims=[dict(claim_text=related[0]['text'],
        source_text=related[0]['text'],claim_type='factual')])]))
    with pytest.raises(ValueError):
        validate_output_with_diagnostics(source.text,batch,output,resource=r,policy=policy,allowed_nodes={'k'})


def test_pure_teaching_note_disposition_and_uncertain_remain_distinct():
    state, _, _, _, _, source, policy=prepare()
    r=state['generated_resources'][0]
    batch=one_field(source,'distinction_questions[0].explanation')
    from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output_with_diagnostics
    from app.models.reviews.claim_extraction import BatchOutputV2, content_digest
    def output(status):
        return BatchOutputV2.model_validate(dict(resource_id=r.resource_id,resource_version=r.version,
            content_hash=content_digest(source.text),batch_id=batch.batch_id,
            units=[dict(unit_id='u',status=status,reason='纯判题关系说明',claims=[])]))
    candidates,_=validate_output_with_diagnostics(source.text,batch,output('non_factual'),resource=r,policy=policy,allowed_nodes={'k'})
    assert candidates==[]
    with pytest.raises(ValueError,match='unresolved'):
        validate_output_with_diagnostics(source.text,batch,output('uncertain'),resource=r,policy=policy,allowed_nodes={'k'})

def test_split_target_background_is_not_repeated_when_already_fully_present():
    state, _, _, _, _, source, policy=prepare()
    f=next(f for f in source.fields if f['path'].endswith('.statement'))
    middle=(f['start']+f['end'])//2
    explanation=one_field(source,'distinction_questions[0].explanation').units[0]
    batch=ExtractionBatch(batch_id='split',units=[
        ExtractionUnit(unit_id='s1',kind='paragraph',start=f['start'],end=middle),
        ExtractionUnit(unit_id='s2',kind='paragraph',start=middle,end=f['end']),explanation])
    payload=json.loads(build_messages(source.text,state['generated_resources'][0],batch,policy,{'k'})[-1].content)
    assert payload['structured_context']['read_only_related_fields']==[]
    roles=payload['structured_context']['fields']
    assert {x['unit_id'] for x in roles if x['path']==f['path']}=={'s1','s2'}


def test_explanation_meta_words_do_not_drop_real_factual_clause():
    state, _, _, _, _, _, policy=prepare()
    r=state['generated_resources'][0];p=r.review_practice_payload
    p['node_blocks'][0]['distinction_questions'][0]['explanation']='与教材一致，因为RAG能保证所有事实正确。'
    p['payload_hash']=_canonical_hash({k:v for k,v in p.items() if k!='payload_hash'})
    r.content_text=render_review_practice_markdown(p)
    source=build_source(r,policy)
    field=next(f for f in source.fields if f['path'].endswith('distinction_questions[0].explanation'))
    raw='RAG能保证所有事实正确。'
    start=source.text.index(raw,field['start'],field['end'])
    candidate=ClaimCandidate(claim_text=raw,source_text=raw,source_start=start,source_end=start+len(raw),claim_type='factual')
    assert source.classify([candidate])[0].claim_type.value=='factual'

def test_unknown_checklist_marker_cannot_fall_back_to_public_markdown():
    state, _, _, _, _, _, _=prepare()
    with pytest.raises(ValueError,match='unknown checklist'):
        source_for_claims(state['generated_resources'][0],[SimpleNamespace(extractor_prompt_version='structured-checklist-v999')])
