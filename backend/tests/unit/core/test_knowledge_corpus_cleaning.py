"""File-only corpus builds: cleaning boundaries, reproducibility and isolation."""
from collections import Counter
import json
from pathlib import Path

import pytest

from scripts import knowledge_corpus_cleaning as cleaner
from scripts.knowledge_layout import encoded, registry_payload
from app.core.retrieval.knowledge_paths import LAYOUT_VERSION


def _spec(**values):
    return {"id": "example", "source_type": "markdown", **values}


def test_badges_are_removed_but_papers_and_runnable_examples_keep_their_targets():
    text = ("# Guide\n\n[![stars](https://img.shields.io/github/stars/example)](https://github.com/example)\n"
            "[![Paper](https://img.shields.io/badge/arxiv-red)](https://arxiv.org/abs/1234.1234)\n"
            "[![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/demo.ipynb)\n"
            "Useful [model](https://huggingface.co/models/example).\n")
    value, _, counts, _, _ = cleaner.clean_document(_spec(), text, set(), set())
    assert "shields.io" not in value
    assert "https://arxiv.org/abs/1234.1234" in value
    assert "https://colab.research.google.com/demo.ipynb" in value
    assert "[model](https://huggingface.co/models/example)" in value
    assert counts["badge_links_removed"] == 1 and counts["technical_badges_to_links"] == 2


@pytest.mark.parametrize("marker", ["```", "~~~~", "````"])
def test_code_table_inline_math_and_hard_breaks_are_not_cleaned_as_display_noise(marker):
    block = f'{marker}python\nvalue = "data:image/png;base64,A"\n\n\n\nprint("<img src=logo.png>")\n{marker}\n'
    table = "| Meaning | Example |\n| --- | --- |\n| badge | ![raw](https://img.shields.io/raw) |\n"
    inline = '`literal\n\n\n[ ](https://example.org)`'
    math = "$$\nx_i = 1\n\n\n-x_j\n$$\n"
    text = "# Guide\n\n" + block + "\n" + table + "\n" + inline + "\n\n" + math + "\nTwo spaces  \nnext line\n"
    value = cleaner.clean_document(_spec(), text, set(), set())[0]
    for protected in (block, table, inline, math, "Two spaces  \nnext line"):
        assert protected in value


def test_code_fences_inside_html_details_remain_exact():
    block = '```python\nvalue = "![status](https://img.shields.io/raw)"\n\n\nprint(value)\n```\n'
    value = cleaner.clean_document(_spec(), "<details>\n<summary>Usage</summary>\n" + block + "</details>\n", set(), set())[0]
    assert block in value and "Usage" in value and "<details>" not in value


def test_only_presentation_html_is_unwrapped_and_relative_images_resolve_to_pinned_source():
    text = ('<div align="center"><img src="logo.png" alt="Logo"/></div>\n'
            '<p><a href="guide.md">Technical guide</a></p>\n'
            '<details>\n<summary>Pipeline</summary>\n    <img src="figure.png" alt="Architecture"/>\n</details>\n'
            '<p>👋 join us on <a href="https://discord.gg/test">Discord</a></p>\n'
            '## Agent Contract\nDo Not upload private documents.\n## License\nCopyright retained.\n')
    spec = _spec(source_urls=["https://raw.githubusercontent.com/owner/repo/pin/README.md"])
    value = cleaner.clean_document(spec, text, set(), set())[0]
    assert "logo.png" not in value and "discord.gg" not in value
    assert "[Technical guide](https://raw.githubusercontent.com/owner/repo/pin/guide.md)" in value
    assert "![Architecture](https://raw.githubusercontent.com/owner/repo/pin/figure.png)" in value
    assert "Agent Contract" in value and "Do Not upload private documents." in value
    assert "Copyright retained." in value


def test_empty_links_layout_blanks_navigation_and_orphan_bullets_are_normalized():
    text = "# Guide\n\n\n\n[\n ](https://example.org)\n[A](#a) |\n[B](#b) |\n[C](#c)\n\n- \n\nImportant concept.\n"
    value, _, counts, _, _ = cleaner.clean_document(_spec(), text, set(), set())
    assert "https://example.org" not in value and "[A]" not in value
    assert "- Important concept." in value
    assert counts["navigation_menus_removed"] == 1 and counts["orphan_list_markers_rejoined"] == 1
    assert cleaner.clean_document(_spec(), value, set(), set())[0] == value


def test_restored_notebook_urls_come_only_from_frozen_original_and_are_idempotent():
    raw = ('<a href="https://colab.research.google.com/demo.ipynb"><img alt="Colab"/></a>'
           '<a href="https://github.com/owner/repo/blob/pin/demo.ipynb">Source</a>'
           '<a href="https://github.com/owner/repo/issues">Issues</a>'
           '<a href="https://unrelated.test/demo.ipynb">No</a>')
    spec = _spec(parser_version="official-zh-structure-v2")
    value, _, counts, _, _ = cleaner.clean_document(spec, "# Guide\n\nKnowledge.\n", set(), set(), original=raw)
    assert counts["original_notebook_links_restored"] == 2
    assert "https://colab.research.google.com/demo.ipynb" in value
    assert "/issues" not in value and "unrelated.test" not in value
    assert cleaner.clean_document(spec, value, set(), set(), original=raw)[0] == value


def _pdf_pages(bodies):
    lines, spans = [], []
    for page, body in enumerate(bodies, 1):
        start = len(lines) + 1
        lines.append(f"## PDF page {page}\n")
        lines.extend(body.splitlines(keepends=True))
        spans.append({"page": page, "line_start": start, "line_end": len(lines)})
    return "".join(lines), spans


def test_pdf_repairs_supported_spelling_but_keeps_compound_hyphens_urls_and_uncertain_words():
    text, spans = _pdf_pages(["We exam-\nine contexts in a dual-\nencoder and state-of-\nthe-art system.\n"
                             "Look https://example.org/long-\npath\nUncertain zzzz-\nyyyy text.\n"])
    words = {"examine", "longpath"}
    value, new_spans, counts, _, unresolved = cleaner.clean_pdf(text, spans, words, {"dual-encoder"})
    assert "examine contexts" in value and "dual-encoder" in value and "state-of-the-art" in value
    assert "https://example.org/long-\npath" in value
    assert "zzzz-\nyyyy" in value and unresolved
    assert counts["supported_word_splits_joined"] == 1
    assert new_spans[-1]["line_end"] == len(value.splitlines())


def test_pdf_page_numbers_need_multi_page_evidence_and_math_is_preserved():
    text, spans = _pdf_pages([f"Page text.\nC = {{p1,p2,pM}}\n{100 + page}\n" for page in range(1, 4)])
    value, new_spans, counts, _, _ = cleaner.clean_pdf(text, spans, set(), set())
    assert counts["verified_page_numbers_removed"] == 3
    assert value.count("## PDF page") == 3 and value.count("C = {p1,p2,pM}") == 3
    assert new_spans[1]["line_start"] == new_spans[0]["line_end"] + 1
    short, short_spans = _pdf_pages(["Legitimate number.\n101\n", "Legitimate number.\n102\n"])
    assert "101" in cleaner.clean_pdf(short, short_spans, set(), set())[0]


def test_pdf_ligature_repair_does_not_fold_greek_or_change_code():
    text, spans = _pdf_pages(["A ﬁne-\ntuned model has β².\n`ﬁ` is literal code.\n"])
    value = cleaner.clean_pdf(text, spans, {"finetuned"}, {"fine-tuned"})[0]
    assert "fine-tuned" in value and "β²" in value and "`ﬁ`" in value


def test_pdf_never_joins_across_physical_pages_or_changes_protected_code():
    text, spans = _pdf_pages(["We exam-\n", "ine text.\n```text\nexam-\nine\n```\n"])
    value = cleaner.clean_pdf(text, spans, {"examine"}, set())[0]
    assert "exam-\n" in value and "```text\nexam-\nine\n```" in value


@pytest.mark.parametrize("damage", ["gap", "marker", "incomplete"])
def test_invalid_pdf_locator_fails_closed(damage):
    text, spans = _pdf_pages(["one\n", "two\n"])
    if damage == "gap":
        spans[1]["line_start"] += 1
    elif damage == "marker":
        text = text.replace("## PDF page 2", "## PDF page 7")
    else:
        spans.pop()
    with pytest.raises(ValueError):
        cleaner.clean_pdf(text, spans, set(), set())


def _source(tmp_path, monkeypatch):
    root = tmp_path / "canonical"
    root.mkdir()
    specs = []
    for number in range(62):
        name = f"teaching/zh/{number:02}.md"
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Lesson {number}\n\n\n\nKnowledge.\n", encoding="utf-8")
        specs.append({"id": f"module_{number}", "title": f"Lesson {number}", "file": name})
    manifest = {"knowledge_base_id": "synthetic", "version": "1", "storage_layout": {"version": LAYOUT_VERSION,
                "loading": "manifest_only", "registry": "provenance/registry.json"}, "documents": specs}
    (root / "metadata.json").write_bytes(encoded(manifest))
    (root / "README.md").write_text("Source documentation.\n", encoding="utf-8")
    for batch in ("pilot", "bulk", "chinese"):
        path = root / f"provenance/import_batches/{batch}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded({"sources": [], "manifest_documents": []}))
    (root / "provenance/registry.json").write_bytes(encoded(registry_payload(root)))
    monkeypatch.setattr(cleaner, "ROOT", tmp_path)
    monkeypatch.setattr(cleaner, "KB", root)
    return root, tmp_path / "output/knowledge-cleaning/test"


def test_file_only_build_preserves_canonical_and_is_reproducible(tmp_path, monkeypatch):
    root, output = _source(tmp_path, monkeypatch)
    before = cleaner.file_hashes(root)
    cleaner.build(output, apply=True)
    assert cleaner.file_hashes(root) == before
    assert cleaner.verify(output)["documents"] == 62
    assert json.loads((output / "status.json").read_text())["ingested"] is False
    with pytest.raises(ValueError, match="already exists"):
        cleaner.build(output, apply=True)


def test_check_is_read_only_and_rejects_candidate_or_source_drift(tmp_path, monkeypatch):
    root, output = _source(tmp_path, monkeypatch)
    cleaner.build(output, apply=True)
    before = cleaner.file_hashes(output)
    cleaner.verify(output)
    assert cleaner.file_hashes(output) == before
    fixture = output / "candidate-snapshot.json"
    fixture.unlink()
    with pytest.raises(ValueError, match="snapshot missing"):
        cleaner.verify(output)
    assert not fixture.exists()
    (root / "README.md").write_text("edited source", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical input drift"):
        cleaner.verify(output)


@pytest.mark.parametrize("path", ["canonical", "output/knowledge-cleaning", "../outside"])
def test_output_path_rejects_canonical_roots_and_escape(tmp_path, monkeypatch, path):
    monkeypatch.setattr(cleaner, "ROOT", tmp_path)
    monkeypatch.setattr(cleaner, "KB", tmp_path / "canonical")
    with pytest.raises(ValueError):
        cleaner.safe_output(tmp_path / path)


def test_script_has_no_ingestion_database_model_network_or_process_imports():
    import ast
    tree = ast.parse(Path(cleaner.__file__).read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    forbidden = ("sqlite3", "sqlalchemy", "chromadb", "app.db", "app.services", "app.core.retrieval.embeddings",
                 "requests", "httpx", "subprocess", "socket")
    assert not any(name == prefix or name.startswith(prefix + ".") for name in imports for prefix in forbidden)


def test_known_canonical_corpus_is_assessed_but_never_rewritten():
    before = cleaner.file_hashes(cleaner.KB)
    manifest, baseline, _, rows = cleaner.analyze()
    assert len(manifest["documents"]) == len(rows) == 62
    assert all(row["protection_verified"] for row in rows)
    assert cleaner.file_hashes(cleaner.KB) == baseline == before
