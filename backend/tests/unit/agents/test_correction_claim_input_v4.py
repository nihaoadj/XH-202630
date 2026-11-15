"""Correction-only target boundaries, frozen sources and request packing."""
import copy
import json

import pytest

from app.core.learning_documents.correction_package import render_correction_markdown
from app.models.learning_documents.correction_package import assemble_compact_correction_package
from app.models.reviews.claim_extraction import digest
from app.models.reviews.claims import ClaimCandidate
from app.agents.resource_workflows.learning_documents.claim_extraction import contextual_correction_sources as v4
from app.agents.resource_workflows.learning_documents.claim_extraction import compact_correction_sources as v3
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import build_source, source_for_claims
from app.agents.resource_workflows.learning_documents.claim_extraction.batching import plan_batches
from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import build_messages
from tests.fakes.claim_extraction import prepare_ledger, neutral_settings
from tests.unit.agents.test_compact_correction_package import compact_content, compact_source_setup


def contextual_setup(locating=True, body=None):
    state, _, repo, gateway, counter = compact_source_setup(locating)
    policy = repo.get(state['run_id']).policy.model_copy(update={'correction_sources': v4.frozen_extension()})
    audit, repo = prepare_ledger(p=policy)
    body = copy.deepcopy(body or compact_content())
    row = body['unit']['exercises']['transfer']
    row.update(scenario='假设系统回答：“报名截止日期是2025年6月30日。”系统日志显示向量库查询超时。',
               question='请区分依赖故障与正常无答案。',
               reference_answer='该回答编造了资料中不存在的日期。',
               explanation='向量库查询超时属于依赖故障，不代表资料没有答案。')
    pack = assemble_compact_correction_package(content=body, title='纠错包',
        target=dict(node_id='k', node_name='编码契约', mastery_status='weak', failed_dimensions=[]),
        run_id=state['run_id'], focus_snapshot_hash='a' * 64)
    resource = state['generated_resources'][0]
    resource.correction_package_payload = pack.model_dump(mode='json')
    resource.correction_package_payload_hash = pack.payload_hash
    resource.content_text = render_correction_markdown(pack).strip()
    state.update(claim_extraction_policy=policy.model_dump(mode='json'), claim_extraction_policy_hash=digest(policy))
    return state, audit, repo, gateway, counter


def test_field_roles_and_targets_preserve_knowledge_across_entire_package():
    state, _, repo, _, _ = contextual_setup()
    resource = state['generated_resources'][0]
    source = build_source(resource, repo.get(state['run_id']).policy)
    paths = {f['path']: f['role'] for f in source.fields}
    for group in ('guided', 'transfer'):
        assert {p.rsplit('.', 1)[-1] for p in paths if f'.exercises.{group}.' in p} == {'reference_answer', 'explanation'}
    assert paths['content.unit.exercises.transfer.reference_answer'] == 'answer'
    assert paths['content.unit.comparisons[0].correct_statement'] == 'correct_statement'
    for prefix in ('content.unit.error_patterns[0].explanation', 'content.unit.concept_repair[0].explanation',
                   'content.layered_feedback.foundation', 'content.summary'):
        assert prefix in paths
    assert '2025年6月30日' not in source.text
    assert all('mistaken_view' not in p and 'incorrect_statement' not in p for p in paths)
    assert '该回答编造了资料中不存在的日期。' in source.text
    assert '不代表资料没有答案' in source.text


@pytest.mark.parametrize('locating', [False, True])
def test_input_has_one_target_copy_and_one_related_path_per_batch(locating):
    state, _, repo, _, counter = contextual_setup(locating)
    resource = state['generated_resources'][0]
    policy = repo.get(state['run_id']).policy
    source = build_source(resource, policy)
    payloads = []
    for batch in plan_batches(source.text, policy, counter):
        messages = build_messages(source.text, resource, batch, policy, ['k'])
        payload = json.loads(messages[-1].content)
        payloads.append(payload)
        context = payload['structured_context']
        assert not any('text' in f for f in context['unit_fields'])
        related = context['read_only_related_fields']
        assert len({r['path'] for r in related}) == len(related)
        units = {u['unit_id']: u['text'] for u in payload['target_units']}
        for mapping in context['unit_fields']:
            assert units[mapping['unit_id']][mapping['field_start_in_unit']:mapping['field_end_in_unit']]
        assert all('2025年6月30日' not in u['text'] for u in payload['target_units'])
        if any('transfer.reference_answer' in f['path'] for f in context['unit_fields']):
            assert any('2025年6月30日' in r['text'] for r in related)
        assert '所有目标' in messages[0].content and 'uncertain' in messages[0].content
    assert payloads


def test_context_cannot_become_a_claim_and_original_positions_are_exact():
    state, _, repo, _, _ = contextual_setup()
    source = build_source(state['generated_resources'][0], repo.get(state['run_id']).policy)
    f = next(f for f in source.fields if f['path'].endswith('transfer.reference_answer'))
    text = source.text[f['start']:f['end']]
    good = ClaimCandidate(claim_text=text, claim_type='factual', source_text=text,
                          source_start=f['start'], source_end=f['end'])
    assert source.classify([good]) == [good]
    for changed in ({'source_text': '报名截止日期是2025年6月30日。'},
                    {'source_start': f['start'] - 1}, {'source_end': f['end'] + 1}):
        with pytest.raises(ValueError):
            source.classify([good.model_copy(update=changed)])


def test_old_source_is_unchanged_and_versions_rebuild_without_default_upgrade():
    state, _, repo, _, _ = contextual_setup()
    resource = state['generated_resources'][0]
    old = v3.build_source(resource)
    new = build_source(resource, repo.get(state['run_id']).policy)
    assert '2025年6月30日' in old.text and '2025年6月30日' not in new.text
    from types import SimpleNamespace
    for source in (old, new):
        claims = [SimpleNamespace(extractor_prompt_version=source.prompt_version)]
        assert source_for_claims(resource, claims).snapshot == source.snapshot
    with pytest.raises(ValueError, match='mixed'):
        source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=s.prompt_version) for s in (old, new)])
    broken = repo.get(state['run_id']).policy.model_copy(update={
        'correction_sources': {**v4.frozen_extension(), 'guidance_hash': '0' * 64}})
    with pytest.raises(ValueError, match='drifted'):
        build_source(resource, broken)


def test_new_freeze_selects_v4_without_changing_non_correction_policy():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    _, _, _, gateway, counter = contextual_setup()
    assert freeze_policy(neutral_settings(), gateway, counter, correction=True).correction_sources == v4.frozen_extension()
    assert freeze_policy(neutral_settings(), gateway, counter).correction_sources is None


def test_new_v1_retry_freezes_compatible_policy_without_rewriting_old_snapshot():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import for_correction_contract
    from tests.fakes.claim_extraction import snapshot_for
    state, _, repo, _, _ = contextual_setup()
    snapshot = snapshot_for(repo.get(state['run_id']).policy)
    original = copy.deepcopy(snapshot)
    adapted = for_correction_contract(snapshot, {'version': 'correction-json-generation-v1'})
    assert snapshot == original
    assert adapted['claim_extraction_policy']['correction_sources'] == v3.frozen_extension()
    assert adapted['claim_extraction_policy_hash'] == digest(adapted['claim_extraction_policy'])
    assert for_correction_contract(snapshot, {'version': 'correction-json-generation-v2'}) == original


def test_fixed_sample_serialized_input_shrinks_without_removing_knowledge():
    from app.core.llm.counting import CharacterEstimator
    from app.models.reviews.claim_extraction import BatchOutputV2
    state, _, repo, _, counter = contextual_setup()
    resource = state['generated_resources'][0]
    current = repo.get(state['run_id']).policy
    sizes = {}
    for label, extension in [('v3', v3.frozen_extension()), ('v4', v4.frozen_extension())]:
        policy = current.model_copy(update={'correction_sources': extension})
        source = build_source(resource, policy)
        requests = [build_messages(source.text, resource, b, policy, ['k'])
                    for b in plan_batches(source.text, policy, counter)]
        sizes[label] = dict(serialized_chars=sum(len(m[-1].content) for m in requests),
            estimated_input_tokens=sum(CharacterEstimator().estimate_prepared(m, BatchOutputV2, 'text') for m in requests),
            batches=len(requests))
    assert sizes['v4']['serialized_chars'] < sizes['v3']['serialized_chars']
    print('fixed synthetic sample; estimator, not supplier usage:', json.dumps(sizes))


def test_long_field_splits_keep_roles_and_same_exercise_context():
    body = compact_content()
    body['unit']['exercises']['guided']['reference_answer'] = '核验当前适用条件。' * 150
    state, _, repo, _, counter = contextual_setup(body=body)
    policy = repo.get(state['run_id']).policy.model_copy(update={'target_tokens': 600, 'max_units': 10})
    resource = state['generated_resources'][0]
    source = build_source(resource, policy)
    matches = []
    for batch in plan_batches(source.text, policy, counter):
        payload = json.loads(build_messages(source.text, resource, batch, policy, ['k'])[-1].content)
        context = payload['structured_context']
        for f in context['unit_fields']:
            if f['path'].endswith('guided.reference_answer'):
                matches.append(f)
                assert f['role'] == 'answer'
                assert {r['path'] for r in context['read_only_related_fields']} >= {
                    'content.unit.exercises.guided.scenario', 'content.unit.exercises.guided.question'}
    assert len(matches) > 1
