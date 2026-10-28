"""Deterministic tests for bounded bilingual query aliases."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.retrieval import query_expansion


def _bind_kb(monkeypatch: pytest.MonkeyPatch, kb_dir: Path) -> None:
    def resolve(knowledge_base_id: str) -> Path:
        if knowledge_base_id != "test_kb":
            raise FileNotFoundError(knowledge_base_id)
        return kb_dir

    monkeypatch.setattr(query_expansion, "resolve_knowledge_base_dir_by_id", resolve)


def _write_config(
    kb_dir: Path,
    rules: list[dict[str, object]],
    *,
    version: str = "1.0.0",
) -> bytes:
    raw = json.dumps(
        {"version": version, "rules": rules},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    (kb_dir / query_expansion.CONFIG_FILENAME).write_bytes(raw)
    return raw


def _rule(term: str, keywords: str) -> dict[str, object]:
    return {"match_terms": [term], "english_keywords": keywords}


LEGACY_MATCH_TERMS = (
    "检索增强生成",
    "RAG 基础概念",
    "retrieval augmented generation",
    "RAG",
    "假设文档",
    "hypothetical document",
    "HyDE",
    "文档解析",
    "格式解析",
    "文本清洗",
    "document parsing",
    "text cleaning",
    "Chunk 切分",
    "chunk_size",
    "chunk_overlap",
    "文本切分",
    "chunking",
    "向量表示",
    "语义相似度",
    "Embedding",
    "非对称语义检索",
    "asymmetric semantic search",
    "encode_query",
    "encode_document",
    "向量数据库",
    "向量存储",
    "vector database",
    "vector store",
    "持久化向量",
    "相似度检索",
    "similarity search",
    "Top-K",
    "top k",
    "召回率",
    "Recall",
    "混合检索",
    "hybrid retrieval",
    "关键词检索",
    "向量检索",
    "BM25",
    "RRF",
    "reciprocal rank fusion",
    "Cross-Encoder",
    "Cross Encoder",
    "重排序",
    "精排",
    "Rerank",
    "reranking",
    "Prompt 组装",
    "上下文窗口",
    "指令约束",
    "prompt assembly",
    "context window",
    "引用溯源",
    "source_ref",
    "证据片段",
    "citation",
    "source attribution",
    "Claim 审核",
    "Claim review",
    "幻觉控制",
    "证据支持",
    "grounded answer",
    "factual evidence",
    "RAG 评测",
    "RAG评测",
    "RAG evaluation",
    "命中率",
    "覆盖率",
    "幻觉率",
    "hit rate",
    "hallucination rate",
    "MRR",
    "NDCG",
    "Mean Reciprocal Rank",
    "Normalized Discounted Cumulative Gain",
    "RAG 调优",
    "参数调优",
    "消融实验",
    "RAG tuning",
    "parameter tuning",
    "ablation study",
    "对称语义检索",
    "symmetric semantic search",
)


def _normalise_whitespace_case(value: str) -> str:
    return " ".join(value.split()).casefold()


def _shipped_kb_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "knowledge_base" / "rag_engineering_training"


def _bind_shipped_kb(monkeypatch: pytest.MonkeyPatch) -> Path:
    kb_dir = _shipped_kb_dir()
    monkeypatch.setattr(
        query_expansion,
        "resolve_knowledge_base_dir_by_id",
        lambda _knowledge_base_id: kb_dir,
    )
    return kb_dir


def test_longest_overlapping_term_wins_and_result_contains_alias_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    _write_config(
        tmp_path,
        [
            _rule("RAG", "retrieval augmented generation"),
            _rule("RAG 基础概念", "rag foundations"),
        ],
    )
    query = "RAG 基础概念在本库中的中文说明"

    aliases, profile = query_expansion.expand_query(query, "test_kb")

    assert aliases == ["rag foundations"]
    assert aliases[0] != query
    assert profile["query_expansion_status"] == "expanded"
    assert profile["query_expansion_term_count"] == 1
    assert query not in str(profile)


def test_latin_word_boundaries_do_not_match_rag_inside_storage_or_ragging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    _write_config(tmp_path, [_rule("RAG", "retrieval augmented generation")])

    aliases, profile = query_expansion.expand_query(
        "storage配置与ragging配置不应触发词界匹配",
        "test_kb",
    )

    assert aliases == []
    assert profile["query_expansion_status"] == "no_match"


def test_asymmetric_term_excludes_overlapping_symmetric_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    _write_config(
        tmp_path,
        [
            _rule("非对称语义检索", "asymmetric semantic search encode_query encode_document"),
            {
                "match_terms": ["对称语义检索"],
                "exclude_terms": ["非对称语义检索"],
                "english_keywords": "symmetric semantic search",
            },
        ],
    )

    aliases, _profile = query_expansion.expand_query(
        "非对称语义检索中encode_query与encode_document的区别",
        "test_kb",
    )

    assert aliases == ["asymmetric semantic search encode_query encode_document"]
    assert "symmetric" not in aliases[0].split()


def test_english_only_and_empty_queries_keep_configuration_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    raw = _write_config(tmp_path, [_rule("RAG", "retrieval augmented generation")])

    english_aliases, english_profile = query_expansion.expand_query(
        "RAG retrieval quality",
        "test_kb",
    )
    empty_aliases, empty_profile = query_expansion.expand_query("   ", "test_kb")
    long_aliases, long_profile = query_expansion.expand_query(
        "RAG" + "中" * (query_expansion.MAX_QUERY_CHARS + 1),
        "test_kb",
    )

    assert english_aliases == empty_aliases == []
    assert long_aliases == []
    assert english_profile["query_expansion_status"] == "english_query"
    assert empty_profile["query_expansion_status"] == "empty_query"
    assert long_profile["query_expansion_status"] == "query_too_long"
    assert english_profile["query_expansion_config_hash"] == hashlib.sha256(raw).hexdigest()
    assert english_profile["query_expansion_config_hash"] == empty_profile["query_expansion_config_hash"]
    assert english_profile["query_expansion_version"] == empty_profile["query_expansion_version"] == "1.0.0"


def test_missing_config_has_explicit_stable_status_and_safe_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)

    first = query_expansion.expand_query("中文查询", "test_kb")
    second = query_expansion.expand_query("另一个中文查询", "test_kb")

    assert first[0] == second[0] == []
    assert first[1]["query_expansion_status"] == "config_missing"
    assert first[1]["query_expansion_config_hash"] == second[1]["query_expansion_config_hash"]
    assert first[1]["query_expansion_version"] == ""


def test_unknown_kb_and_non_file_config_fail_closed(tmp_path, monkeypatch):
    _bind_kb(monkeypatch, tmp_path)
    aliases, profile = query_expansion.expand_query("RAG中文", "unknown")
    assert aliases == [] and profile["query_expansion_status"] == "kb_not_found"
    (tmp_path / query_expansion.CONFIG_FILENAME).mkdir()
    aliases, profile = query_expansion.expand_query("RAG中文", "test_kb")
    assert aliases == [] and profile["query_expansion_status"] == "config_unsafe_path"


def test_oversized_query_does_not_generate_probe(tmp_path, monkeypatch):
    _bind_kb(monkeypatch, tmp_path)
    _write_config(tmp_path, [_rule("RAG", "retrieval augmented generation")])
    aliases, profile = query_expansion.expand_query("RAG" + "中" * query_expansion.MAX_QUERY_CHARS, "test_kb")
    assert aliases == [] and profile["query_expansion_status"] == "query_too_long"
    unknown_aliases, unknown_profile = query_expansion.expand_query("RAG中文", "unknown_kb")
    assert unknown_aliases == []
    assert unknown_profile["query_expansion_status"] == "kb_not_found"
    assert isinstance(unknown_profile["query_expansion_config_hash"], str)


def test_rejects_rule_term_and_file_size_over_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    rules = [_rule(f"术语{index}", f"keyword{index}") for index in range(query_expansion.MAX_RULES + 1)]
    _write_config(tmp_path, rules)

    aliases, profile = query_expansion.expand_query("术语0 中文查询", "test_kb")

    assert aliases == []
    assert profile["query_expansion_status"] == "config_invalid"

    _write_config(tmp_path, [_rule("x" * (query_expansion.MAX_TERM_CHARS + 1), "keyword")])
    aliases, profile = query_expansion.expand_query("中文查询", "test_kb")
    assert aliases == []
    assert profile["query_expansion_status"] == "config_invalid"

    oversized = b" " * (query_expansion.MAX_CONFIG_BYTES + 1)
    (tmp_path / query_expansion.CONFIG_FILENAME).write_bytes(oversized)
    aliases, profile = query_expansion.expand_query("中文查询", "test_kb")
    assert aliases == []
    assert profile["query_expansion_status"] == "config_too_large"


def test_rejects_unbounded_or_non_keyword_alias_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    for keywords in (
        "x" * (query_expansion.MAX_ENGLISH_KEYWORDS_CHARS + 1),
        "检索 retrieval",
        "https://example.com",
    ):
        _write_config(tmp_path, [_rule("RAG", keywords)])

        aliases, profile = query_expansion.expand_query("RAG中文", "test_kb")

        assert aliases == []
        assert profile["query_expansion_status"] == "config_invalid"


def test_matching_and_probe_are_bounded_to_six_rules_and_400_characters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    rules = [_rule(f"术语{index}", f"keyword{index} {'x' * 40}") for index in range(8)]
    _write_config(tmp_path, rules)
    query = " ".join(f"术语{index}" for index in range(8))

    aliases, profile = query_expansion.expand_query(query, "test_kb")

    assert len(aliases) == 1
    assert len(aliases[0]) <= query_expansion.MAX_PROBE_CHARS
    assert profile["query_expansion_status"] == "expanded_limited"
    assert profile["query_expansion_term_count"] == query_expansion.MAX_MATCHED_RULES


def test_probe_character_budget_skips_whole_aliases_without_clipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    rules = [_rule(f"术语{index}", f"term{index} {'x' * 144}") for index in range(6)]
    _write_config(tmp_path, rules)
    query = " ".join(f"术语{index}" for index in range(6))

    aliases, profile = query_expansion.expand_query(query, "test_kb")

    assert len(aliases) == 1
    assert len(aliases[0]) <= query_expansion.MAX_PROBE_CHARS
    assert aliases[0].count("term") == 2
    assert aliases[0].endswith("x" * 144)
    assert profile["query_expansion_status"] == "expanded_limited"
    assert profile["query_expansion_term_count"] == 2


def test_config_hash_is_stable_and_changes_with_config_without_text_in_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_kb(monkeypatch, tmp_path)
    first_bytes = _write_config(tmp_path, [_rule("RAG", "retrieval augmented generation")])
    first_aliases, first_profile = query_expansion.expand_query("RAG 中文说明", "test_kb")
    _write_config(
        tmp_path,
        [_rule("RAG", "retrieval augmented generation context")],
        version="1.1.0",
    )
    second_aliases, second_profile = query_expansion.expand_query("RAG 中文说明", "test_kb")

    assert first_aliases != second_aliases
    assert first_profile["query_expansion_config_hash"] == hashlib.sha256(first_bytes).hexdigest()
    assert first_profile["query_expansion_config_hash"] != second_profile["query_expansion_config_hash"]
    assert second_profile["query_expansion_version"] == "1.1.0"
    assert "RAG 中文说明" not in str(first_profile)
    assert "retrieval augmented generation" not in str(first_profile)


def test_shipped_rag_aliases_cover_cross_language_retrieval_topics(
    monkeypatch: pytest.MonkeyPatch,
):
    repo_root = Path(__file__).resolve().parents[4]
    kb_dir = repo_root / "knowledge_base" / "rag_engineering_training"
    monkeypatch.setattr(
        query_expansion,
        "resolve_knowledge_base_dir_by_id",
        lambda _knowledge_base_id: kb_dir,
    )
    probes = [
        ("中文问题和英文资料的非对称语义检索，encode_query与encode_document有什么区别？", "asymmetric semantic search"),
        ("Cross-Encoder为什么只能重排已经召回的候选？", "cross encoder reranking"),
        ("RAG中的假设文档HyDE为什么不能当作最终事实证据？", "hypothetical document"),
        ("chunk_overlap与RRF在混合检索中有什么影响？", "text chunking"),
    ]

    for query, expected_keyword in probes:
        aliases, profile = query_expansion.expand_query(query, "rag_engineering_training")
        assert profile["query_expansion_status"].startswith("expanded")
        assert expected_keyword in " ".join(aliases).lower()


def test_shipped_alias_schema_limits_uniqueness_and_provenance_mapping():
    kb_dir = _shipped_kb_dir()
    config_path = kb_dir / query_expansion.CONFIG_FILENAME
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    provenance = json.loads(
        (kb_dir / "provenance" / "query_aliases_sources.json").read_bytes()
    )

    assert query_expansion.MAX_RULES == 128
    assert query_expansion.MAX_CONFIG_BYTES == 64 * 1024
    assert query_expansion.MAX_TERMS_PER_RULE == 16
    assert query_expansion.MAX_ENGLISH_KEYWORDS_CHARS == 160
    assert query_expansion.MAX_MATCHED_RULES == 6
    assert query_expansion.MAX_PROBE_CHARS == 400
    assert len(config_bytes) <= query_expansion.MAX_CONFIG_BYTES
    assert set(config) == {"version", "rules"}
    assert isinstance(config["version"], str) and config["version"]
    assert isinstance(config["rules"], list)
    assert 0 < len(config["rules"]) <= query_expansion.MAX_RULES

    term_owners: dict[str, int] = {}
    keywords: list[str] = []
    for rule_index, rule in enumerate(config["rules"]):
        assert set(rule) in (
            {"match_terms", "english_keywords"},
            {"match_terms", "exclude_terms", "english_keywords"},
        )
        terms = rule["match_terms"]
        assert isinstance(terms, list)
        assert 1 <= len(terms) <= query_expansion.MAX_TERMS_PER_RULE
        assert all(isinstance(term, str) and term.strip() for term in terms)
        for term in terms:
            normalized = _normalise_whitespace_case(term)
            assert normalized not in term_owners, (
                f"duplicate trigger after whitespace/casefold normalization: {term!r}; "
                f"rules {term_owners.get(normalized)} and {rule_index}"
            )
            term_owners[normalized] = rule_index

        english_keywords = rule["english_keywords"]
        assert isinstance(english_keywords, str) and english_keywords
        assert len(english_keywords) <= query_expansion.MAX_ENGLISH_KEYWORDS_CHARS
        keywords.append(_normalise_whitespace_case(english_keywords))

    assert len(keywords) == len(set(keywords)), "english_keywords must be unique"
    assert set(provenance) == {
        "schema_version",
        "alias_version",
        "purpose",
        "terminology_policy",
        "scope_note",
        "compatibility_terms",
        "entries",
    }
    assert provenance["schema_version"] == 1
    assert provenance["alias_version"] == config["version"]
    assert isinstance(provenance["entries"], list)
    assert len(provenance["entries"]) == len(config["rules"])

    entries_by_keywords: dict[str, dict[str, object]] = {}
    for entry in provenance["entries"]:
        assert set(entry) == {"concept", "category", "english_keywords", "sources"}
        key = _normalise_whitespace_case(entry["english_keywords"])
        assert key not in entries_by_keywords
        entries_by_keywords[key] = entry
    assert set(entries_by_keywords) == set(keywords), (
        "every configured alias must have exactly one provenance entry"
    )


def test_alias_provenance_matches_manifest_hashes_and_content_anchors():
    kb_dir = _shipped_kb_dir()
    manifest = json.loads((kb_dir / "metadata.json").read_bytes())
    provenance = json.loads(
        (kb_dir / "provenance" / "query_aliases_sources.json").read_bytes()
    )
    manifest_documents = {
        document["id"]: document for document in manifest["documents"]
    }
    authoritative_documents = {
        document_id: document
        for document_id, document in manifest_documents.items()
        if document.get("document_type") == "authoritative_original"
    }
    root = kb_dir.resolve()
    source_bytes_cache: dict[Path, bytes] = {}

    def read_cached(relative_path: str) -> bytes:
        relative = Path(relative_path)
        assert not relative.is_absolute()
        assert "teaching" not in {part.casefold() for part in relative.parts}
        resolved = (root / relative).resolve()
        assert resolved.is_relative_to(root)
        if resolved not in source_bytes_cache:
            source_bytes_cache[resolved] = resolved.read_bytes()
        return source_bytes_cache[resolved]

    checked_sources = 0
    for entry in provenance["entries"]:
        assert entry["sources"]
        for source in entry["sources"]:
            assert set(source) == {
                "document_id",
                "file",
                "anchor_text",
                "source_snapshot",
                "source_sha256",
                "content_sha256",
            }
            document = authoritative_documents[source["document_id"]]
            assert document["document_type"] == "authoritative_original"
            assert source["file"] == document["file"]
            assert source["source_snapshot"] == document["source_snapshot"]
            assert source["source_sha256"] == document["source_hash"]
            assert source["content_sha256"] == document["normalized_hash"]

            snapshot_bytes = read_cached(source["source_snapshot"])
            content_bytes = read_cached(source["file"])
            assert hashlib.sha256(snapshot_bytes).hexdigest() == source["source_sha256"]
            assert hashlib.sha256(content_bytes).hexdigest() == source["content_sha256"]

            content = content_bytes.decode("utf-8-sig")
            normalized_content = _normalise_whitespace_case(content)
            normalized_anchor = _normalise_whitespace_case(source["anchor_text"])
            assert normalized_anchor
            assert normalized_anchor in normalized_content, (
                f"anchor not found for {entry['concept']!r}: "
                f"{source['document_id']} / {source['anchor_text']!r}"
            )
            checked_sources += 1

    assert checked_sources > 0


def test_all_legacy_alias_terms_still_expand_with_chinese_context(
    monkeypatch: pytest.MonkeyPatch,
):
    kb_dir = _bind_shipped_kb(monkeypatch)
    provenance = json.loads(
        (kb_dir / "provenance" / "query_aliases_sources.json").read_bytes()
    )
    assert len(LEGACY_MATCH_TERMS) == 84
    assert {
        _normalise_whitespace_case(term) for term in provenance["compatibility_terms"]
    } == {_normalise_whitespace_case(term) for term in LEGACY_MATCH_TERMS}

    for term in LEGACY_MATCH_TERMS:
        aliases, profile = query_expansion.expand_query(
            f"{term} 中文说明", "rag_engineering_training"
        )
        assert aliases, f"legacy trigger no longer expands: {term!r}"
        assert profile["query_expansion_status"].startswith("expanded")


def test_fine_grained_aliases_expand_without_cross_topic_or_generic_matches(
    monkeypatch: pytest.MonkeyPatch,
):
    _bind_shipped_kb(monkeypatch)
    examples = (
        ("BM25算法", "BM25 lexical retrieval"),
        ("互惠排名融合", "RRF reciprocal rank fusion"),
        ("稠密检索", "dense retrieval dense vector search"),
        ("检索召回率", "Recall retrieval recall at k"),
        ("MRR@10", "MRR mean reciprocal rank"),
        ("NDCG@k", "NDCG normalized discounted cumulative gain"),
        ("非对称语义检索", "asymmetric semantic search"),
        ("对称语义检索", "symmetric semantic search"),
        ("扫描件识别", "OCR scanned PDF images"),
        ("词干提取", "stemming lexical analysis"),
        ("停用词过滤", "stop words stopword removal"),
        ("父子分块", "parent child chunk auto merging"),
        ("语义分块", "semantic chunking semantic chunker"),
    )
    expanded: dict[str, str] = {}
    for trigger, expected_keywords in examples:
        aliases, profile = query_expansion.expand_query(
            f"{trigger} 中文说明", "rag_engineering_training"
        )
        assert aliases == [expected_keywords], trigger
        assert profile["query_expansion_status"] == "expanded", trigger
        assert profile["query_expansion_term_count"] == 1, trigger
        expanded[trigger] = aliases[0].casefold()

    assert "rrf" not in expanded["BM25算法"]
    assert "dense retrieval" not in expanded["BM25算法"]
    assert "bm25" not in expanded["互惠排名融合"]
    recall_words = set(expanded["检索召回率"].split())
    assert not {"mrr", "ndcg"} & recall_words
    assert "symmetric" not in expanded["非对称语义检索"].split()
    assert "asymmetric" not in expanded["对称语义检索"].split()

    # Exercise one Chinese spelling for every shipped concept without creating
    # hundreds of parametrized tests or loading retrieval/LLM models.
    config = json.loads(
        (_shipped_kb_dir() / query_expansion.CONFIG_FILENAME).read_bytes()
    )
    for rule in config["rules"]:
        trigger = next(
            term for term in rule["match_terms"]
            if any("\u4e00" <= char <= "\u9fff" for char in term)
        )
        aliases, profile = query_expansion.expand_query(
            f"{trigger} 中文说明", "rag_engineering_training"
        )
        assert aliases == [rule["english_keywords"]], trigger
        assert profile["query_expansion_term_count"] == 1, trigger

    aliases, profile = query_expansion.expand_query(
        "比较对称语义检索与非对称语义检索", "rag_engineering_training"
    )
    assert profile["query_expansion_term_count"] == 2
    assert aliases == ["asymmetric semantic search symmetric semantic search"]

    for trigger, expected in (
        ("向量检索", "vector search vector retrieval"),
        ("覆盖率", "coverage evaluation"),
        ("嵌入", "embeddings vector representation semantic similarity"),
        ("切片", "text chunking text splitting"),
        ("交叉编码器", "cross encoder reranking"),
    ):
        aliases, _profile = query_expansion.expand_query(
            f"{trigger} 中文说明", "rag_engineering_training"
        )
        assert aliases == [expected], trigger

    for query in (
        "storage配置",
        "ragging配置",
        "一般重试说明",
        "召回反馈机制",
        "retrieval feedback 说明",
    ):
        aliases, profile = query_expansion.expand_query(
            query, "rag_engineering_training"
        )
        assert aliases == [], query
        assert profile["query_expansion_status"] == "no_match", query
