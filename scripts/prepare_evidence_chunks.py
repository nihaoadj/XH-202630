"""Build a v2 teaching-unit candidate and offline parent previews; never ingest."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts.knowledge_layout import KB, check_layout, encoded, registry_payload, write_atomic  # noqa: E402
from scripts.knowledge_corpus_cleaning import file_hashes, protected_lines, protected_blocks  # noqa: E402
from app.core.retrieval.knowledge_base import load_documents, chunk_documents  # noqa: E402
from app.core.retrieval.knowledge_ids import canonical_json  # noqa: E402
from app.core.retrieval.evidence_chunking import EVIDENCE_STRATEGY, protected_ranges  # noqa: E402

PROFILE = "evidence-units-v2"
_LINK = re.compile(r"!?\[([^]\n]*)\]\((https?://[^)\s]+)\)")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def separate_auxiliary(text):
    """Only whole standalone link/menu lines; narrative links remain intact."""
    lines = text.splitlines(keepends=True)
    mask = protected_lines(text)
    result, removed, entries, pending = [], Counter(), [], []
    for number, (line, protected) in enumerate(zip(lines, mask, strict=True), 1):
        if protected:
            result.append(line)
            continue
        display_note = (re.fullmatch(r"\s*#{1,6}\s*贡献者\s*[:：]?\s*", line)
                        or re.fullmatch(r"\s*十分感谢所有参与FlagEmbedding社区成员的贡献，也欢迎新的成员加入！\s*", line)
                        or re.fullmatch(r"\s*🚀\s*让我们运行一下测试和评估一下答案!👇\s*", line))
        if display_note:
            entries.append({"line": number, "text": line.strip(), "kind": "display_note"})
            removed["display_note_lines"] += 1
            continue
        matches = list(_LINK.finditer(line))
        residual = _LINK.sub("", line).strip()
        residual = re.sub(r"^(?:配套示例|参考链接|延伸阅读|相关链接|参考资料|Sources?|References?|Further reading)\s*[:：]?", "", residual, flags=re.I)
        pure = matches and not re.sub(r"[\s\-*+\d.、：:；;，,|()（）]+", "", residual)
        reference_definition = re.match(r"^ {0,3}\[([^]]+)\]:\s*(https?://\S+)(?:\s+.*)?$", line.strip())
        if pure:
            entries.extend({"line": number, "label": match[1], "url": match[2], "kind": "standalone_link"}
                           for match in matches)
            removed["auxiliary_link_lines"] += 1
            continue
        # Definitions may be needed by reference-style links; retain them.
        if reference_definition:
            pending.append(number)
        if re.fullmatch(r"\s*(?:::|:::(?:js|python|typescript)?|---|\*\*\*|。|；|;)\s*", line):
            entries.append({"line": number, "text": line.strip(), "kind": "format_only"})
            removed["format_only_lines"] += 1
            continue
        result.append(line)
    value = "".join(result)
    # Normalize only extra layout separators introduced by removed link lines.
    lines, mask = value.splitlines(keepends=True), protected_lines(value)
    result, blank = [], 0
    for line, protected in zip(lines, mask, strict=True):
        if protected or line.strip():
            blank = 0
            result.append(line)
        else:
            blank += 1
            if blank <= 1:
                result.append(line)
            else:
                removed["empty_separator_lines"] += 1
    return "".join(result), entries, dict(removed)


def transform(spec, text):
    if not spec.get("page_spans"):
        value, entries, counts = separate_auxiliary(text)
        return value, None, entries, counts
    # Preserve page assignment even when link-only lines occur inside a PDF.
    from scripts.knowledge_corpus_cleaning import split_pdf
    blocks, spans, entries, counts, length = [], [], [], Counter(), 0
    for page, lines in split_pdf(text, spec["page_spans"]):
        value, links, rules = separate_auxiliary("".join(lines))
        body = f"## PDF page {page}\n" + value
        if not body.endswith("\n"):
            body += "\n"
        spans.append({"page": page, "line_start": length + 1, "line_end": length + len(body.splitlines())})
        length = spans[-1]["line_end"]
        blocks.append(body)
        entries.extend({**item, "page": page} for item in links)
        counts.update(rules)
    return "".join(blocks), spans, entries, dict(counts)


def digest_chunks(chunks):
    values = sorted([(c.metadata["chunk_id"], c.page_content, c.metadata) for c in chunks], key=lambda x: x[0])
    return sha(canonical_json(values).encode())


def stats(chunks):
    lengths = sorted(len(c.page_content) for c in chunks)
    if not lengths:
        raise ValueError("empty chunk set")
    return {"count": len(chunks), "min": lengths[0], "median": lengths[len(lengths) // 2],
            "p90": lengths[int((len(lengths) - 1) * .9)], "max": lengths[-1],
            "under50": sum(n < 50 for n in lengths), "under200": sum(n < 200 for n in lengths),
            "oversized": sum(c.metadata.get("oversized_block", False) for c in chunks),
            "pure_noise": sum(not re.search(r"[\w\u3400-\u9fff]", c.page_content) for c in chunks)}


def parent_previews(documents, chunks):
    by_id = {doc.metadata["document_id"]: doc for doc in documents}
    by_doc = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.metadata["document_id"], []).append(chunk)
    result = []
    for doc_id, group in by_doc.items():
        source = by_id[doc_id].page_content
        for index, chunk in enumerate(group):
            chosen = [chunk]
            size = len(chunk.page_content)
            for neighbor in (group[index - 1:index] + group[index + 1:index + 2]):
                if (neighbor.metadata.get("page") != chunk.metadata.get("page")
                        or set(neighbor.metadata["knowledge_points"]) != set(chunk.metadata["knowledge_points"])):
                    continue
                tentative = sorted([*chosen, neighbor], key=lambda c: c.metadata["chunk_ordinal"])
                start = min(c.metadata["source_start_index"] for c in tentative)
                end = max(c.metadata["source_end_index"] for c in tentative)
                text = source[start:end]
                if len(text) <= 2400 and size < 1600:
                    chosen, size = tentative, len(text)
            first = min(c.metadata["line_start"] for c in chosen)
            last = max(c.metadata["line_end"] for c in chosen)
            start = min(c.metadata["source_start_index"] for c in chosen)
            end = max(c.metadata["source_end_index"] for c in chosen)
            text = source[start:end]
            result.append({"child_chunk_id": chunk.metadata["chunk_id"], "document_id": doc_id,
                "line_start": first, "line_end": last, "page": chunk.metadata.get("page"),
                "source_start_index": start, "source_end_index": end,
                "knowledge_points": chunk.metadata["knowledge_points"], "child_ids": [c.metadata["chunk_id"] for c in chosen],
                "text": text, "oversized": len(text) > 2400, "runtime_enabled": False})
    return result


def valid_output(output):
    output = Path(output).resolve()
    allowed = (ROOT / "output/knowledge-cleaning").resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError("output must be a new knowledge-cleaning child")
    return output


def build(output, *, source=None):
    if source is None and (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        with reconstructed_previous(KB) as base:
            return build(output, source=base)
    source = Path(source or KB)
    output = valid_output(output)
    if output.exists():
        raise ValueError("output already exists; refusing overwrite")
    check_layout(source)
    baseline = file_hashes(source)
    original_manifest = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    old = chunk_documents(load_documents(str(source)))
    original_fixture = json.loads((ROOT / "backend/tests/fixtures/knowledge_pilot/corpus_clean_v1.json").read_text(encoding="utf-8"))
    if len(old) != 3177 or digest_chunks(old) != original_fixture["full_snapshot_sha256"]:
        raise ValueError("active source snapshot drift; do not stage against the wrong corpus")
    output.mkdir(parents=True, exist_ok=False)
    write_atomic(output / "status.json", encoded({"status": "building", "ingested": False}))
    candidate = output / "corpus" / original_manifest["knowledge_base_id"]
    shutil.copytree(source, candidate)
    manifest = deepcopy(original_manifest)
    prior_activation = manifest.pop("active_corpus_cleaning", None)
    manifest["document_identity_revision"] = original_manifest["document_identity_revision"] + "-evidence-v2"
    manifest["chunking"] = {"strategy": "recursive_v1", "chunk_size": 900, "chunk_overlap": 100}
    manifest["staged_evidence_chunking"] = {"profile": PROFILE, "strategy": EVIDENCE_STRATEGY,
        "target_chars": 900, "soft_max_chars": 1200, "overlap_chars": 100, "ingested": False,
        "parent_context_runtime_enabled": False}
    auxiliary, audit = {}, []
    for spec in manifest["documents"]:
        text = (source / spec["file"]).read_text(encoding="utf-8")
        value, spans, links, counts = transform(spec, text)
        spec["chunking_strategy"] = EVIDENCE_STRATEGY
        if value != text:
            write_atomic(candidate / spec["file"], value.encode())
            if spec.get("document_type") == "authoritative_original":
                spec["normalized_hash"] = sha(value.encode())
                spec["parser_version"] = spec.get("parser_version", "base") + "+auxiliary-links-v1"
            if spans:
                spec["page_spans"] = spans
        auxiliary[spec["id"]] = links
        audit.append({"id": spec["id"], "source_file": spec["file"], "body_changed": text != value,
                      "rules": counts, "auxiliary_entries": len(links), "strategy": EVIDENCE_STRATEGY})
    write_atomic(candidate / "metadata.json", encoded(manifest))
    specs = {spec["id"]: spec for spec in manifest["documents"]}
    for batch in ("pilot", "bulk", "chinese"):
        path = candidate / f"provenance/import_batches/{batch}.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["manifest_documents"] = [deepcopy(specs[spec["id"]]) for spec in registry.get("manifest_documents", [])]
        for source in registry.get("sources", []):
            spec = specs[source["id"]]
            source["normalized_sha256"] = spec["normalized_hash"]
            if "parser_version" in source:
                source["parser_version"] = spec["parser_version"]
            if spec.get("page_spans"):
                source["page_spans"] = spec["page_spans"]
            source["staged_chunk_profile"] = PROFILE
        if "asset_hashes" in registry:
            registry["asset_hashes"] = {name: sha((candidate / name).read_bytes()) for name in registry["asset_hashes"]}
        write_atomic(path, encoded(registry))
    write_atomic(candidate / "provenance/auxiliary_links.json", encoded({"profile": PROFILE, "documents": auxiliary,
        "note": "Auxiliary URLs remain traceable here; not text for embedding or frozen evidence."}))
    write_atomic(candidate / "README.md", ("# T27教学单元切片候选（未入库）\n\n"
        "全部62篇与六教材启用markdown_evidence_v2，900字符目标/1200软限/100 overlap上限。\n"
        "纯辅助链接见provenance/auxiliary_links.json；current runtime仍T26的3177片。\n"
        "parent-context是离线预览，运行时尚不读取它。\n").encode())
    write_atomic(candidate / "provenance/registry.json", encoded(registry_payload(candidate)))
    documents = load_documents(str(candidate))
    chunks = chunk_documents(documents, chunk_size=900, chunk_overlap=100)
    parents = parent_previews(documents, chunks)
    snapshot = {"profile": PROFILE, "strategy": EVIDENCE_STRATEGY, "source_hashes": baseline,
                "old_snapshot_hash": digest_chunks(old), "candidate_snapshot_hash": digest_chunks(chunks),
                "candidate_file_hashes": file_hashes(candidate), "old": stats(old), "new": stats(chunks),
                "modules": {doc.metadata["document_id"]: {"old": stats([c for c in old if c.metadata["document_id"] == doc.metadata["document_id"]]),
                    "new": stats([c for c in chunks if c.metadata["document_id"] == doc.metadata["document_id"]])}
                    for doc in documents if doc.metadata["document_id"].startswith("module_")},
                "documents": audit, "prior_activation": prior_activation, "ingested": False,
                "parent_context_runtime_enabled": False}
    write_atomic(output / "audit.json", encoded(snapshot))
    write_atomic(output / "chunks.jsonl", "".join(json.dumps({"text": c.page_content, "metadata": c.metadata}, ensure_ascii=False) + "\n" for c in chunks).encode())
    write_atomic(output / "parent-contexts.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in parents).encode())
    write_atomic(output / "status.json", encoded({"status": "candidate_ready", "profile": PROFILE,
        "documents": len(documents), "chunks": len(chunks), "ingested": False, "parent_context_runtime_enabled": False}))
    verify(output, source=source)
    print(json.dumps({"old": snapshot["old"], "new": snapshot["new"], "modules": snapshot["modules"]}, ensure_ascii=False, indent=2))
    return snapshot


def verify(output, *, source=None):
    if source is None and (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        with reconstructed_previous(KB) as base:
            return verify(output, source=base)
    source = Path(source or KB)
    output = valid_output(output)
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    if audit["profile"] != PROFILE or file_hashes(source) != audit["source_hashes"]:
        raise ValueError("source snapshot changed")
    source_manifest = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    candidate = output / "corpus" / source_manifest["knowledge_base_id"]
    if file_hashes(candidate) != audit["candidate_file_hashes"]:
        raise ValueError("candidate file drift")
    check_layout(candidate)
    documents = load_documents(str(candidate))
    chunks = chunk_documents(documents, chunk_size=900, chunk_overlap=100)
    if len(documents) != 62 or digest_chunks(chunks) != audit["candidate_snapshot_hash"]:
        raise ValueError("candidate chunk snapshot differs")
    if any(c.metadata.get("chunking_strategy") != EVIDENCE_STRATEGY for c in chunks):
        raise ValueError("not every document adopted v2")
    sources = {d.metadata["document_id"]: d for d in documents}
    original_docs = {d.metadata["document_id"]: d for d in load_documents(str(source))}
    for chunk in chunks:
        lines = sources[chunk.metadata["document_id"]].page_content.splitlines()
        start, end = chunk.metadata["line_start"], chunk.metadata["line_end"]
        if chunk.page_content not in "\n".join(lines[start - 1:end]):
            raise ValueError("chunk locator does not contain its text")
    for ident, doc in sources.items():
        group = [c for c in chunks if c.metadata["document_id"] == ident]
        text = doc.page_content
        for block in protected_blocks(original_docs[ident].page_content):
            if block not in text:
                raise ValueError("protected source block was removed")
        for start, end in protected_ranges(text, pdf=bool(doc.metadata.get("page_spans"))):
            value = text[start:end].strip()
            if value and not any(value in c.page_content for c in group):
                raise ValueError("protected code/table/math was split or omitted")
        position = 0
        spans = sorted((c.metadata["source_start_index"], c.metadata["source_end_index"]) for c in group)
        for start, end in [*spans, (len(text), len(text))]:
            if start > position:
                gap = text[position:start]
                if any(line.strip() and not re.fullmatch(r"\s*#{1,6}[^\n]*", line)
                       and re.search(r"[\w\u3400-\u9fff]", line) for line in gap.splitlines()):
                    raise ValueError("meaningful source text missing from chunk coverage")
            position = max(position, end)
    for name, fingerprint in audit["source_hashes"].items():
        if "/original." in name or name.startswith("licenses/"):
            if sha((candidate / name).read_bytes()) != fingerprint:
                raise ValueError("raw/permission source changed")
    expected_chunks = "".join(json.dumps({"text": c.page_content, "metadata": c.metadata}, ensure_ascii=False) + "\n" for c in chunks).encode()
    expected_parents = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in parent_previews(documents, chunks)).encode()
    if (output / "chunks.jsonl").read_bytes() != expected_chunks or (output / "parent-contexts.jsonl").read_bytes() != expected_parents:
        raise ValueError("chunk/context export differs")
    print(f"V2 candidate verified: {len(documents)} docs / {len(chunks)} chunks; six modules included; NOT ingested")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "output/knowledge-cleaning/T27")
    args = parser.parse_args()
    verify(args.output) if args.check else build(args.output)


if __name__ == "__main__":
    main()
