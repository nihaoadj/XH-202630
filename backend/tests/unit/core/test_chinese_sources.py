"""Official Chinese source integrity and pre-expansion compatibility."""
import hashlib
import importlib.util
import json
from app.core.retrieval.knowledge_paths import resolve_knowledge_file
import re

import httpx
import pytest

from app.core.retrieval.knowledge_base import chunk_documents, load_documents
from app.core.retrieval.knowledge_ids import canonical_json
from app.core.retrieval.markdown_structure import structural_chunks
from langchain.schema import Document
from tests.paths import PROJECT_ROOT
from tests.fakes.knowledge_versions import without_identity_revision, source_baseline


def preparer():
    spec = importlib.util.spec_from_file_location("chinese_preparer", PROJECT_ROOT / "scripts/prepare_chinese_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_english_1626_official_chunk_identities_and_metadata_are_frozen():
    with source_baseline() as base:
        docs = [doc for doc in load_documents(str(base)) if doc.metadata.get("document_type") == "authoritative_original" and not doc.metadata["document_id"].startswith("source_zh_")]
    chunks = chunk_documents(without_identity_revision(docs))
    assert len(docs) == 21 and len(chunks) == 1626
    value = sorted([(c.metadata["chunk_id"], c.page_content, c.metadata) for c in chunks], key=lambda c: c[0])
    assert hashlib.sha256(canonical_json(value).encode()).hexdigest() == "0710ccf155e57db063e0fcdd08deaa75de4e923dfe3142a391e5c429132b9752"


def test_offline_sources_licenses_cells_and_locators_are_complete():
    from scripts.knowledge_corpus_promotion import prep_roots
    with source_baseline() as base, prep_roots(base):
        _assert_offline_sources(base)


def _assert_offline_sources(base):
    tool = preparer()
    registry = tool.prepare(offline=True)
    docs = {d.metadata["document_id"]: d for d in load_documents(str(base)) if d.metadata["document_id"].startswith("source_zh_")}
    assert len(docs) == len(registry["sources"]) == 35
    for source in registry["sources"]:
        doc = docs[source["id"]]
        raw = resolve_knowledge_file(tool.KB, source["original_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        assert source["chinese_characters"] >= 20
        assert source["language_origin"] in {"official_chinese", "official_translation"}
        if source["kind"] == "notebook":
            notebook = json.loads(raw)
            assert len(source["review"]["cells"]) == len(notebook["cells"])
            for cell in notebook["cells"]:
                body = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
                expected = tool.clean(body)
                if cell['cell_type'] == 'markdown':
                    expected = tool.markdown_links(expected, source['review']['relative_link_base'])
                from app.core.retrieval.knowledge_ids import normalize_text
                assert normalize_text(expected) in doc.page_content
        for chunk in chunk_documents([doc]):
            start, end = chunk.metadata["line_start"], chunk.metadata["line_end"]
            assert chunk.page_content in "\n".join(doc.page_content.splitlines()[start - 1:end])
            assert chunk.metadata["knowledge_points"]
    apache = resolve_knowledge_file(tool.KB, "licenses/Apache-2.0").read_text(encoding="utf-8")
    custom = resolve_knowledge_file(tool.KB, "licenses/mineru/LICENSE").read_text(encoding="utf-8")
    assert "TERMS AND CONDITIONS" in apache and "END OF TERMS AND CONDITIONS" in apache
    assert "100 million" in custom and "Attribution" in custom


def test_html_preserves_headings_all_code_table_values_and_single_entity_decode():
    tool = preparer()
    parser = tool.OfficialHTML("https://github.com/example/docs/blob/abcdef/chapter/page.md")
    body = '<h1>混合检索<button>复制<svg><path/></svg></button></h1><p>召回率不能直接视为准确率。</p>'
    body += '<pre><code class="language-python">if a &lt; b:\n    value = "&amp;lt;"\n<button>复制代码</button></code></pre>'
    body += '<table><tr><th>方法</th><th>召回率</th></tr><tr><td>BM25</td><td>0.87</td></tr></table>'
    body += '<ol start="3"><li>保留第三步</li><li>保留第四步</li></ol><a href="../other.md">原文</a>'
    parser.feed(body)
    parser.close()
    text = parser.result()
    assert "# 混合检索" in text and "复制" not in text and "<svg" not in text
    assert 'if a < b:\n    value = "&lt;"' in text
    assert "| BM25 | 0.87 |" in text
    assert "3. 保留第三步" in text and "4. 保留第四步" in text
    assert "https://github.com/example/docs/blob/abcdef/other.md" in text
    assert parser.table_count == 1 and len(parser.codes) == 1
    assert structural_chunks(Document(page_content=text), chunk_size=500, chunk_overlap=100)


@pytest.mark.parametrize("body", ['<pre><code>unfinished', '<table><tr><td>unfinished', '<script>unfinished'])
def test_html_incomplete_structures_fail_closed(body):
    tool = preparer()
    parser = tool.OfficialHTML("https://example.org/")
    parser.feed(body)
    with pytest.raises(tool.common.SourceError):
        parser.result()


def test_notebook_keeps_every_source_but_never_uses_outputs():
    tool = preparer()
    notebook = {"nbformat": 4, "cells": [
        {"cell_type": "markdown", "source": ["# 权威资料\n", "完整说明。"]},
        {"cell_type": "code", "source": ["raise RuntimeError('never execute')\n", "print('```')"], "outputs": [{"text": "SECRET_OUTPUT"}]},
        {"cell_type": "raw", "source": "原始说明保留"},
    ]}
    text, review = tool.normalize_notebook(json.dumps(notebook).encode())
    assert len(review["cells"]) == 3 and review["omitted_output_count"] == 1
    assert "SECRET_OUTPUT" not in text and "raise RuntimeError('never execute')" in text
    assert "````python" in text and "原始说明保留" in text
    assert structural_chunks(Document(page_content=text), chunk_size=500, chunk_overlap=100)


def test_relative_markdown_links_resolve_without_rewriting_code():
    tool = preparer()
    base = 'https://github.com/official/docs/blob/' + 'a' * 40 + '/guide/page.md'
    text = '[原文](../chapter.md#part)\n[id]: other.md "标题"\n`[code](keep.md)`\n```python\nprint("[code](keep.md)")\n```\n'
    result = tool.markdown_links(text, base)
    assert '/chapter.md#part)' in result and '/guide/other.md "标题"' in result
    assert '`[code](keep.md)`' in result and 'print("[code](keep.md)")' in result
    assert tool.markdown_links('![流程图](data:image/png;base64,AAAA)', base) == '![流程图](#embedded-image-see-original)'
    with pytest.raises(tool.common.SourceError):
        tool.markdown_links('[危险](javascript:alert)', base)


@pytest.mark.parametrize("cell", [{"cell_type": "unknown", "source": "内容"}, {"cell_type": "code", "source": [123]}])
def test_invalid_notebook_cells_rejected(cell):
    tool = preparer()
    with pytest.raises(tool.common.SourceError):
        tool.normalize_notebook(json.dumps({"nbformat": 4, "cells": [cell]}).encode())


@pytest.mark.parametrize("path", ["../escape", "C:/escape", "x%2Fy.md", "/escape"])
def test_upstream_path_traversal_and_encoded_paths_rejected(path):
    tool = preparer()
    with pytest.raises(tool.common.SourceError):
        tool.source_url({"repository": "FlagOpen/FlagEmbedding", "commit": "a" * 40}, path)


@pytest.mark.parametrize("status,body", [(302, b"redirect"), (200, b"tampered")])
def test_download_redirect_and_hash_mismatch_rejected(monkeypatch, status, body):
    tool = preparer()
    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    with pytest.raises(tool.common.SourceError):
        tool.common.fetch_source({"id": "fixture", "url": "https://raw.githubusercontent.com/test/file", "sha256": "0" * 64, "kind": "markdown"})


def test_download_timeout_rejected(monkeypatch):
    tool = preparer()
    original_client = httpx.Client

    def timeout(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(timeout), **kwargs))
    with pytest.raises(tool.common.SourceError, match="failed after one retry"):
        tool.common.fetch_source({"id": "fixture", "url": "https://raw.githubusercontent.com/test/file", "sha256": "0" * 64, "kind": "markdown"})


def test_catalog_is_fixed_unique_and_known_points_only():
    tool = preparer()
    catalog, _ = tool.read_catalog()
    assert len(catalog["sources"]) == 35
    assert all(re.fullmatch(r"[0-9a-f]{64}", s["sha256"]) for s in catalog["sources"])
