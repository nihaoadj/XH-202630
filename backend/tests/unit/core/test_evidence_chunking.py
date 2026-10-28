"""Small deterministic v2 acceptance; no indexing/model calls."""
import hashlib
import json
from pathlib import Path

import pytest
from langchain.schema import Document

from app.core.retrieval.evidence_chunking import EVIDENCE_STRATEGY, evidence_chunks, protected_ranges
from app.core.retrieval.knowledge_base import load_documents, chunk_documents
from app.core.retrieval.knowledge_ids import canonical_json
from scripts import prepare_evidence_chunks as builder
from scripts.knowledge_layout import KB


def doc(text, mapping=None, **metadata):
    return Document(page_content=text, metadata={"run": "fixture", "knowledge_points": ["node"],
        **({"section_knowledge_points": mapping} if mapping is not None else {}), **metadata})


def test_titles_explanations_code_and_output_are_grouped_as_contiguous_units():
    code = '```python\nprint("hello")\n```'
    text = "# Topic\n\nExplanation of the example.\n\n" + code + "\n\n输出:\n\nhello\n\n## Conclusion\n\nMeaningful conclusion."
    chunks = evidence_chunks(doc(text))
    assert len(chunks) == 1 and code in chunks[0].page_content and "输出:" in chunks[0].page_content
    assert chunks[0].metadata["sections"] == ["Topic", "Topic / Conclusion"]
    assert text[chunks[0].metadata["start_index"]:][:len(chunks[0].page_content)] == chunks[0].page_content


def test_distinct_node_scopes_are_not_merged_and_unmapped_sections_stay_unmapped():
    text = "# Guide\n\n## One\n\nAlpha definition.\n\n## Two\n\nBeta definition.\n\n## Unknown\n\nUnmapped definition."
    chunks = evidence_chunks(doc(text, {"Guide / One": ["a"], "Guide / Two": ["b"]}))
    assert [c.metadata["knowledge_points"] for c in chunks] == [["a"], ["b"], []]
    assert not any("Alpha" in c.page_content and "Beta" in c.page_content for c in chunks)


def test_pdf_chunks_never_cross_physical_page_even_when_short():
    text = "## PDF page 1\nFirst definition.\n\n## PDF page 2\nSecond definition."
    spans = [{"page": 1, "line_start": 1, "line_end": 3}, {"page": 2, "line_start": 4, "line_end": 5}]
    chunks = evidence_chunks(doc(text, page_spans=spans))
    assert [c.metadata["page"] for c in chunks] == [1, 2]
    assert all(not ("First" in c.page_content and "Second" in c.page_content) for c in chunks)


def test_code_tables_and_math_are_not_split_or_truncated():
    code = '```python\n' + 'print("keep me")\n' * 90 + '```'
    table = '| Item | Value |\n| --- | --- |\n' + '| example | 123 |\n' * 90
    math = '$$\n' + 'x_i = x_j + 1\n' * 90 + '$$'
    text = '# Lesson\n\n' + code + '\n\n' + table + '\n\n' + math
    chunks = evidence_chunks(doc(text))
    for block in (code, table.strip(), math):
        assert sum(block in c.page_content for c in chunks) == 1
    assert any(c.metadata['oversized_block'] for c in chunks)


def test_long_paragraph_fallback_has_bounded_overlap_and_no_missing_tail():
    text = '# Topic\n\n' + 'Definition and supporting explanation. ' * 90 + 'Unique final conclusion.'
    chunks = evidence_chunks(doc(text))
    assert len(chunks) > 1 and all(len(c.page_content) <= 1200 for c in chunks)
    assert 'Unique final conclusion.' in chunks[-1].page_content
    assert any(chunks[i].metadata['start_index'] < chunks[i - 1].metadata['start_index'] + len(chunks[i - 1].page_content)
               for i in range(1, len(chunks)))


def test_atomic_safety_bound_and_unclosed_fences_fail_closed():
    for text in ('```python\nunclosed', '```\n' + 'x' * 12001 + '\n```'):
        with pytest.raises(ValueError):
            evidence_chunks(doc(text))


def test_no_heading_only_or_punctuation_only_evidence_but_short_definition_kept():
    chunks = evidence_chunks(doc('# Root\n\n## Concept\n\nA short but complete definition.\n\n。\n\n## Empty heading'))
    assert chunks and any('complete definition' in c.page_content for c in chunks)
    assert not any(c.page_content in {'。', '# Root', '## Empty heading'} for c in chunks)


def test_auxiliary_urls_move_to_audit_but_narrative_code_and_table_links_stay():
    text = ('# Topic\n\n配套示例：[Colab](https://colab.research.google.com/example.ipynb)；[GitHub](https://github.com/demo/example.ipynb)\n'
            'Read [the API](https://example.org/api) to set the parameter.\n\n'
            '```python\nurl = "https://example.org/in-code"\n```\n\n'
            '| source | role |\n| --- | --- |\n| [Data](https://example.org/data) | input |\n'
            '\n:::js\n\n。\n')
    value, links, counts = builder.separate_auxiliary(text)
    assert 'colab.research.google.com' not in value and 'github.com/demo' not in value
    assert [item['url'] for item in links if item['kind'] == 'standalone_link'] == [
        'https://colab.research.google.com/example.ipynb', 'https://github.com/demo/example.ipynb']
    for target in ('https://example.org/api', 'https://example.org/in-code', 'https://example.org/data'):
        assert target in value
    assert ':::js' not in value and counts['format_only_lines'] == 2


def test_all_six_modules_use_v2_in_candidate_and_old_runtime_snapshot_stays_frozen():
    from tests.fakes.knowledge_versions import pre_evidence_corpus
    with pre_evidence_corpus() as base:
        docs = load_documents(str(base))
    chunks = chunk_documents(docs)
    fixture = json.loads((builder.ROOT / 'backend/tests/fixtures/knowledge_pilot/corpus_clean_v1.json').read_text(encoding='utf-8'))
    assert len(chunks) == fixture['chunk_count'] == 3177
    assert builder.digest_chunks(chunks) == fixture['full_snapshot_sha256']
    modules = [d for d in docs if d.metadata['document_id'].startswith('module_')]
    assert len(modules) == 6
    for source in modules:
        source.metadata['chunking_strategy'] = EVIDENCE_STRATEGY
    staged = chunk_documents(modules, chunk_size=900, chunk_overlap=100)
    assert staged and all(c.metadata['chunking_strategy'] == EVIDENCE_STRATEGY for c in staged)
    assert len(staged) < sum(c.metadata['document_id'].startswith('module_') for c in chunks)
    assert {c.metadata['chunking_config_hash'] for c in staged}.isdisjoint(
        {c.metadata['chunking_config_hash'] for c in chunks if c.metadata['document_id'].startswith('module_')})


def test_parent_preview_never_merges_other_page_or_nodes_and_is_not_runtime_enabled():
    source = doc('alpha\nbeta\ngamma\n', document_id='one')
    children = [Document(page_content=value, metadata={'document_id': 'one', 'chunk_id': str(i), 'chunk_ordinal': i,
                'knowledge_points': points, 'page': page, 'line_start': i + 1, 'line_end': i + 1,
                'source_start_index': sum(len(s) for s in ['alpha\n', 'beta\n', 'gamma\n'][:i]),
                'source_end_index': sum(len(s) for s in ['alpha\n', 'beta\n', 'gamma\n'][:i]) + len(value)})
                for i, (value, points, page) in enumerate([('alpha', ['a'], 1), ('beta', ['b'], 1), ('gamma', ['a'], 2)])]
    parents = builder.parent_previews([source], children)
    assert all(len(row['child_ids']) == 1 and row['runtime_enabled'] is False for row in parents)


def test_pdf_page_spans_recalculate_after_removing_auxiliary_lines():
    text = '## PDF page 1\n[Demo](https://example.org/demo)\nActual knowledge.\n## PDF page 2\nMore knowledge.\n'
    spec = {'page_spans': [{'page': 1, 'line_start': 1, 'line_end': 3}, {'page': 2, 'line_start': 4, 'line_end': 5}]}
    value, spans, _, _ = builder.transform(spec, text)
    assert 'https://example.org/demo' not in value
    assert spans[1]['line_start'] == spans[0]['line_end'] + 1
    assert value.splitlines()[spans[1]['line_start'] - 1] == '## PDF page 2'


def test_v2_chunk_identity_is_deterministic_and_complete_metadata_freezes():
    text = '# Topic\n\nComplete definition.\n\n## Example\n\n```text\nexample\n```\n'
    source = doc(text, knowledge_base_id='test', document_id='doc', document_version='v1', chunking_strategy=EVIDENCE_STRATEGY)
    one = chunk_documents([source], chunk_size=900, chunk_overlap=100)
    two = chunk_documents([source], chunk_size=900, chunk_overlap=100)
    assert builder.digest_chunks(one) == builder.digest_chunks(two)
    assert hashlib.sha256(canonical_json({'text': one[0].page_content}).encode()).hexdigest()
    for chunk in one:
        a, b = chunk.metadata['line_start'], chunk.metadata['line_end']
        assert chunk.page_content in '\n'.join(text.splitlines()[a - 1:b])


def test_protected_ranges_detect_inline_code_and_indented_code():
    text = '# Lesson\n\n    value = "keep"\n\n    return value\n\nText `inline code` here.\n'
    ranges = protected_ranges(text)
    assert any('value = "keep"' in text[a:b] and 'return value' in text[a:b] for a, b in ranges)
    assert any(text[a:b] == '`inline code`' for a, b in ranges)


def test_pdf_person_name_accents_are_not_multiline_code_spans():
    text = 'Authors named `y,\nA discussion of methods follows.\nMore text and another `i surname.\n'
    assert not protected_ranges(text, pdf=True)


def test_parent_char_spans_do_not_expand_a_child_to_an_entire_long_line():
    text = 'x' * 6000
    source = doc(text, document_id='one')
    child = Document(page_content=text[1000:1900], metadata={'document_id': 'one', 'chunk_id': 'child',
        'chunk_ordinal': 0, 'knowledge_points': ['a'], 'line_start': 1, 'line_end': 1,
        'source_start_index': 1000, 'source_end_index': 1900})
    preview = builder.parent_previews([source], [child])[0]
    assert preview['text'] == text[1000:1900] and preview['oversized'] is False


def test_candidate_builder_does_not_import_ingestion_models_database_or_network():
    import ast
    tree = ast.parse(Path(builder.__file__).read_text(encoding='utf-8'))
    names = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    forbidden = ('app.db', 'app.services', 'sqlite3', 'chromadb', 'httpx', 'requests', 'socket', 'subprocess')
    assert not any(name == part or name.startswith(part + '.') for name in names for part in forbidden)
