"""Small deterministic course checks; never load an embedding or LLM."""
import hashlib
import json
import math
from pathlib import Path
import re

import pytest

from app.core.retrieval.knowledge_base import chunk_documents, load_documents
from app.core.retrieval.knowledge_ids import canonical_json
from tests.paths import BACKEND_ROOT, KNOWLEDGE_BASE_ROOT
from tests.fakes.knowledge_versions import without_identity_revision, pre_evidence_corpus

KB = KNOWLEDGE_BASE_ROOT / 'rag_engineering_training'
REVISION = 'teaching-2026-10-v2'
OFFICIAL_DIGEST = '9536518d3ad3456ef63f15d59a0eaaca85a5e0884655edbec330075a136a071d'


def test_all_official_3096_bodies_and_historical_identity_projection_are_unchanged():
    with pre_evidence_corpus() as base:
        metadata = json.loads((base/'metadata.json').read_text(encoding='utf-8'))
        baseline_docs = load_documents(str(base))
    if metadata.get('active_corpus_cleaning'):
        # Cleaning is an intentional source revision, not a reason to overwrite
        # the retained pre-T24 fixture. Check the new full metadata epoch.
        fixture = json.loads((BACKEND_ROOT/'tests/fixtures/knowledge_pilot/corpus_clean_v1.json').read_text(encoding='utf-8'))
        assert metadata['active_corpus_cleaning']['profile'] == fixture['profile'] == 'corpus-clean-v1'
        docs = [d for d in baseline_docs if d.metadata.get('document_type') == 'authoritative_original']
        chunks = chunk_documents(docs)
        assert len(docs) == 56 and len(chunks) == fixture['official_chunk_count'] == 3051
        data = sorted([(c.metadata['chunk_id'], c.page_content, c.metadata) for c in chunks], key=lambda x: x[0])
        assert hashlib.sha256(canonical_json(data).encode()).hexdigest() == fixture['official_snapshot_sha256']
        return
    docs = without_identity_revision([d for d in baseline_docs if d.metadata.get('document_type') == 'authoritative_original'])
    chunks = chunk_documents(docs)
    assert len(docs) == 56 and len(chunks) == 3096
    data = sorted([(c.metadata['chunk_id'], c.page_content, c.metadata) for c in chunks], key=lambda x: x[0])
    assert hashlib.sha256(canonical_json(data).encode()).hexdigest() == OFFICIAL_DIGEST


@pytest.mark.parametrize('number', range(1, 7))
def test_six_modules_are_versioned_locally_cited_and_self_contained(number):
    metadata = json.loads((KB/'metadata.json').read_text(encoding='utf-8'))
    spec = next(d for d in metadata['documents'] if d.get('module_number') == number)
    assert spec['version'] == REVISION
    path = KB/spec['file']
    text = path.read_text(encoding='utf-8')
    for marker in ('rag-lab-v2', '合成', '## 学习目标与分层阅读', '## 贯穿实验', '## 诊断与练习', '### 参考答案与评分要点', '## 来源映射与延伸阅读'):
        assert marker in text, (number, marker)
    for ident in ('lab-A', 'lab-B', 'lab-C', 'lab-D', 'Q1', 'Q2', 'Q3', 'Q4'):
        assert ident in text, (number, ident)
    assert '2.2.0' not in text and '"source_path": "modules/' not in text
    headings = re.findall(r'^## (\d+)\.', text, re.M)
    assert len(headings) == len(set(headings))
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match and fence is None:
            fence = match[1]
        elif match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
            fence = None
    assert fence is None, (number, 'unclosed fence')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if re.match(r'^[a-z]+:', target) or target.startswith('#'):
            continue
        local = (path.parent/target.split('#')[0]).resolve()
        assert local.is_relative_to(KB.parents[1]) and local.is_file(), (number, target)
    sources = text.split('## 来源映射与延伸阅读', 1)[1]
    ids = set(re.findall(r'\bsource_(?!id\b)[a-z0-9_]+\b', sources))
    assert len(ids) >= 2
    assert ids <= {s['id'] for s in metadata['documents']}


def test_teaching_fixture_tracks_only_new_teaching_revision():
    fixture = json.loads((BACKEND_ROOT/'tests/fixtures/knowledge_pilot/teaching_v2_m3.json').read_text(encoding='utf-8'))
    with pre_evidence_corpus() as base:
        docs = [d for d in load_documents(str(base)) if d.metadata['document_id'].startswith('module_')]
    assert len(docs) == 6
    for doc in docs:
        chunks = chunk_documents([doc])
        actual = {'source_version': doc.metadata['source_version'],
                  'content_sha256': doc.metadata['document_content_hash'],
                  'chunk_ids': [c.metadata['chunk_id'] for c in chunks]}
        assert actual == fixture['documents'][doc.metadata['document_id']]


def test_current_index_identity_and_full_metadata_are_explicitly_frozen():
    with pre_evidence_corpus() as base:
        metadata = json.loads((base/'metadata.json').read_text(encoding='utf-8'))
        docs = load_documents(str(base))
    if metadata.get('active_corpus_cleaning'):
        fixture = json.loads((BACKEND_ROOT/'tests/fixtures/knowledge_pilot/corpus_clean_v1.json').read_text(encoding='utf-8'))
        assert metadata['active_corpus_cleaning']['profile'] == fixture['profile'] == 'corpus-clean-v1'
    else:
        fixture = json.loads((BACKEND_ROOT/'tests/fixtures/knowledge_pilot/multilingual_index.json').read_text(encoding='utf-8'))
    chunks = chunk_documents(docs)
    assert len(docs) == fixture['document_count'] == 62
    assert len(chunks) == fixture['chunk_count']
    assert {d.metadata['document_identity_revision'] for d in docs} == {fixture['identity_revision']}
    data = sorted([(c.metadata['chunk_id'], c.page_content, c.metadata) for c in chunks], key=lambda x: x[0])
    assert hashlib.sha256(canonical_json(data).encode()).hexdigest() == fixture['full_snapshot_sha256']


def test_active_evidence_v2_has_separate_full_metadata_fixture():
    metadata = json.loads((KB/'metadata.json').read_text(encoding='utf-8'))
    if not metadata.get('active_evidence_chunking'):
        pytest.skip('v2 not activated in this corpus')
    fixture = json.loads((BACKEND_ROOT/'tests/fixtures/knowledge_pilot/evidence_units_v2.json').read_text(encoding='utf-8'))
    docs = load_documents()
    chunks = chunk_documents(docs, chunk_size=fixture['chunk_size'], chunk_overlap=fixture['chunk_overlap'])
    assert metadata['active_evidence_chunking']['profile'] == fixture['profile']
    assert len(docs) == fixture['document_count'] == 62
    assert len(chunks) == fixture['chunk_count'] == 1121
    assert {d.metadata['document_identity_revision'] for d in docs} == {fixture['identity_revision']}
    official = [c for c in chunks if c.metadata.get('document_type') == 'authoritative_original']
    assert len(official) == fixture['official_chunk_count'] == 1077
    assert len(chunks)-len(official) == fixture['teaching_chunk_count'] == 44
    for group, key in ((chunks, 'full_snapshot_sha256'), (official, 'official_snapshot_sha256')):
        data = sorted([(c.metadata['chunk_id'], c.page_content, c.metadata) for c in group], key=lambda x: x[0])
        assert hashlib.sha256(canonical_json(data).encode()).hexdigest() == fixture[key]


def test_shared_synthetic_case_rrf_and_metrics_are_reproducible():
    case = json.loads((KB/'teaching/lab_case.json').read_text(encoding='utf-8'))
    assert case['case_version'] == 'rag-lab-v2'
    assert len(case['documents']) == 4
    assert next(q for q in case['questions'] if q['id'] == 'Q3')['answerable'] is False
    fusion = case['fusion_example']
    scores = {}
    for channel in ('lexical', 'dense'):
        for rank, ident in enumerate(fusion[channel], 1):
            scores[ident] = scores.get(ident, 0) + 1/(fusion['rrf_k']+rank)
    assert sorted(scores, key=lambda key: (-scores[key], key)) == fusion['expected_order']
    metric = case['metric_example']
    ranked, relevant, k = metric['ranking'], set(metric['relevant']), metric['k']
    hit = [rank for rank, ident in enumerate(ranked[:k], 1) if ident in relevant]
    dcg = sum(1/math.log2(rank+1) for rank in hit)
    ideal = sum(1/math.log2(rank+1) for rank in range(1, min(len(relevant), k)+1))
    assert len(hit)/len(relevant) == metric['recall']
    assert len(hit)/k == metric['precision']
    assert 1/hit[0] == metric['reciprocal_rank']
    assert round(dcg/ideal, 4) == metric['ndcg_rounded']
