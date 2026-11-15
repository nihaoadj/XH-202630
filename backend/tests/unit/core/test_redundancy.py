from dataclasses import replace

import pytest

from app.core.retrieval.redundancy import RedundancyCandidate, filter_redundant


TEXT = (
    "Retrieval assembles evidence from trusted documents before generation. "
    "Chunk boundaries preserve headings and meaningful context for readers. "
    "Ranking compares the question against every candidate passage independently. "
    "The published answer must retain citations and preserve source identity."
)


def item(key, text=TEXT, **kwargs):
    return RedundancyCandidate(key, text, "doc", "v1", **kwargs)


def test_exact_cross_document_normalizes_whitespace_and_keeps_order():
    first = item("a")
    second = replace(item("b", TEXT.replace(" ", "  \n")), document_id="other")
    ids, profile = filter_redundant([first, second])
    assert ids == ["a"]
    assert profile["dropped"] == [{"chunk_id": "b", "retained_chunk_id": "a", "reason": "exact", "similarity": 1.0}]


def test_near_same_section_is_filtered_without_merging_ids():
    ids, profile = filter_redundant([item("a"), item("b", TEXT + " Note.")])
    assert ids == ["a"]
    assert profile["dropped"][0]["reason"] == "near"


@pytest.mark.parametrize("change", [{"document_id": "other"}, {"document_version": "v2"}, {"section": "other"}])
def test_near_other_document_version_or_section_remains(change):
    ids, _ = filter_redundant([item("a"), replace(item("b", TEXT + " Note."), **change)])
    assert ids == ["a", "b"]


@pytest.mark.parametrize("left,right", [
    (" Use 100 tokens.", " Use 200 tokens."),
    (" It is supported.", " It is not supported."),
    (" 支持该操作。", " 不支持该操作。"),
    (" x > 0", " x < 0"),
])
def test_changed_fact_or_negation_is_not_removed(left, right):
    ids, _ = filter_redundant([item("a", TEXT + left), item("b", TEXT + right)])
    assert ids == ["a", "b"]


@pytest.mark.parametrize("suffix", ["\n```python\nx = True\n```", "\n| key | value |"])
def test_code_and_tables_only_allow_exact_matches(suffix):
    ids, _ = filter_redundant([item("a", TEXT + suffix), item("b", TEXT + suffix + " Note.")])
    assert ids == ["a", "b"]
    ids, _ = filter_redundant([item("a", TEXT + suffix), item("b", TEXT + suffix)])
    assert ids == ["a"]


def test_code_indentation_is_not_normalized_away():
    code = TEXT + "\n```python\nif ready:\n    publish()\nlog()\n```"
    ids, _ = filter_redundant([item("a", code), item("b", code.replace("\nlog()", "\n    log()"))])
    assert ids == ["a", "b"]


@pytest.mark.parametrize("prefix,suffix", [("    ", ""), ("\t", ""), ("", "~~~\n")])
def test_indented_and_tilde_code_preserves_whitespace(prefix, suffix):
    first = TEXT + "\n" + suffix + prefix + "if ready:\n" + prefix + "    publish()\n" + prefix + "log()\n" + suffix
    second = first.replace(prefix + "log()", prefix + "    log()")
    assert filter_redundant([item("a", first), item("b", second)])[0] == ["a", "b"]


def test_short_definitions_and_case_differences_remain():
    assert filter_redundant([item("a", "RAG定义"), item("b", "RAG定义")])[0] == ["a", "b"]
    # Case may name a different identifier; exact matching never lowercases.
    assert filter_redundant([item("a"), replace(item("b", TEXT.upper()), document_id="other")])[0] == ["a", "b"]


def test_unique_responsibility_is_protected_but_shared_one_can_deduplicate():
    public = frozenset({("n1", None)})
    specific = frozenset({("n1", "讲义")})
    ids, profile = filter_redundant([
        item("a", responsibilities=public), item("b", responsibilities=specific),
        item("c", responsibilities=public),
    ])
    assert ids == ["a", "b"]
    assert profile["coverage_protected_count"] == 1
    assert profile["dropped"][0]["chunk_id"] == "c"


def test_responsibilities_cannot_be_combined_across_different_representatives():
    first, second = ("n1", None), ("n2", None)
    ids, _ = filter_redundant([item("a", responsibilities=frozenset({first})),
                               item("b", responsibilities=frozenset({second})),
                               item("c", responsibilities=frozenset({first, second}))])
    assert ids == ["a", "b", "c"]


def test_bounded_audit_and_exact_only_threshold():
    ids, profile = filter_redundant([item(str(i)) for i in range(25)])
    assert ids == ["0"]
    assert profile["dropped_count"] == 24
    assert len(profile["dropped"]) == 20 and profile["audit_truncated"]
    assert filter_redundant([item("a"), item("b", TEXT + " Note.")], threshold=1.0)[0] == ["a", "b"]
    # Repeating the same paragraphs can leave the shingle set unchanged,
    # but threshold=1 still means full-text equality, not Jaccard equality.
    assert filter_redundant([item("a", TEXT * 9), item("b", TEXT * 10)], threshold=1.0)[0] == ["a", "b"]
