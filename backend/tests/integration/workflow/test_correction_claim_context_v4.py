"""Scripted semantic outcomes through the real extraction/Judge/ledger flow.

These fixtures verify transport and policy boundaries, not live model accuracy.
"""
import json
from types import SimpleNamespace

import pytest

from app.core.execution import execution_session
from app.models.reviews.claim_extraction import validate_snapshot
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node, claim_judge_node, claim_decide_node,
)
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from tests.fakes.claim_extraction import extract_every_unit, extract_every_unit_v2, judge_all
from tests.unit.agents.test_correction_claim_input_v4 import contextual_setup
from tests.unit.agents.test_compact_correction_package import compact_content


@pytest.mark.parametrize('locating', [False, True])
@pytest.mark.parametrize('bad_answer', [False, True])
def test_e23_context_not_judged_but_actual_answer_error_blocks(locating, bad_answer, monkeypatch):
    body = compact_content()
    if bad_answer:
        body['summary'] = '向量库超时说明资料没有答案。'
    state, audit, repo, gateway, counter = contextual_setup(locating, body)
    def extract(call):
        result = (extract_every_unit_v2 if locating else extract_every_unit)(call)
        payload = json.loads(call['messages'][-1].content)
        assert '2025年6月30日' not in ''.join(u['text'] for u in payload['target_units'])
        return result
    gateway.outcomes = [extract] * 40
    with execution_session(state['run_id'], 'owner'):
        state.update(claim_extract_node(state, llm_gateway=gateway,
            claim_extraction_repository=repo, claim_extraction_counter=counter))
        assert not state['claim_failed_resource_ids'], state['errors']
        assert all('2025年6月30日' not in c['source_text'] for c in state['extracted_claims'])
        count = len(gateway.calls)
        restored = claim_extract_node(state, llm_gateway=gateway,
            claim_extraction_repository=repo, claim_extraction_counter=counter)
        assert len(gateway.calls) == count
        assert restored['extracted_claims'] == state['extracted_claims']
        def judge(call):
            payload = json.loads(call['messages'][-1].content)
            assert set(payload) == {'claims', 'allowed_evidence'}
            assert '2025年6月30日' not in json.dumps(payload, ensure_ascii=False)
            result = judge_all(call)
            if bad_answer:
                bad_ids = {c['claim_id'] for c in payload['claims']
                           if c['claim_text'] == '向量库超时说明资料没有答案。'}
                assert bad_ids
                for row in result['judgements']:
                    if row['claim_id'] in bad_ids:
                        row.update(verdict='contradicted', reason='scripted actual knowledge error')
            return result
        gateway.outcomes = [judge]
        state.update(claim_judge_node(state, llm_gateway=gateway,
            claim_extraction_repository=repo, claim_extraction_counter=counter))
    snapshot = repo.get(state['run_id'])
    assert validate_snapshot(snapshot.policy.strategy, state, snapshot) is not None
    state.update(claim_decide_node(state))
    import app.agents.resource_workflows.learning_documents.workflow as workflow
    monkeypatch.setattr(workflow, 'get_settings', lambda: SimpleNamespace(claim_partial_publish=False))
    result = decide_node(state)['generated_resources'][0]
    assert (result.publication_status == 'published') is (not bad_answer)


@pytest.mark.parametrize('path', ['error_patterns', 'concept_repair', 'comparisons', 'feedback', 'summary'])
def test_scripted_negation_classification_is_preserved_across_sections(path):
    body = compact_content()
    sentence = '“维度相同即可混用”是错误观点，不能据此判断兼容。'
    if path in {'error_patterns', 'concept_repair', 'comparisons'}:
        body['unit'][path][0]['explanation'] = sentence
    elif path == 'feedback':
        body['layered_feedback']['foundation'] = sentence
    else:
        body['summary'] = sentence
    state, _, repo, gateway, counter = contextual_setup(True, body)
    def extract(call):
        result = extract_every_unit_v2(call)
        for unit in result['units']:
            for candidate in unit['claims']:
                if candidate['source_text'] == sentence:
                    # The model's semantic response is scripted; source is exact.
                    candidate['claim_text'] = sentence
                    candidate['claim_type'] = 'factual'
        return result
    gateway.outcomes = [extract] * 40
    with execution_session(state['run_id'], 'owner'):
        state.update(claim_extract_node(state, llm_gateway=gateway,
            claim_extraction_repository=repo, claim_extraction_counter=counter))
    assert not state['claim_failed_resource_ids'], state['errors']
    records = [c for c in state['extracted_claims'] if c['source_text'] == sentence]
    assert len(records) == 1 and records[0]['claim_text'] == sentence
    assert all(c['claim_text'] != '维度相同即可混用' for c in state['extracted_claims'])


@pytest.mark.parametrize('defect', ['context_quote', 'uncertain'])
def test_context_only_quote_and_uncertainty_cannot_silently_pass(defect):
    state, _, repo, gateway, counter = contextual_setup()
    def extract(call):
        result = extract_every_unit_v2(call)
        for unit in result['units']:
            if defect == 'uncertain':
                unit.update(status='uncertain', claims=[])
            for claim in unit['claims']:
                claim.update(source_text='报名截止日期是2025年6月30日。')
        return result
    gateway.outcomes = [extract] * 50
    with execution_session(state['run_id'], 'owner'):
        state.update(claim_extract_node(state, llm_gateway=gateway,
            claim_extraction_repository=repo, claim_extraction_counter=counter))
    # All-resource failure uses the shared failure envelope, without a partial
    # success result's claim_failed_resource_ids/extracted_claims fields.
    assert state['claim_check_status'] == 'failed'
    assert not state.get('extracted_claims')
    assert state['errors']
