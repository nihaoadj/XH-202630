"""File-only activation/replay of a verified evidence-v2 corpus candidate."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from scripts import knowledge_corpus_promotion as previous  # noqa: E402
from scripts import prepare_evidence_chunks as builder  # noqa: E402
from scripts.knowledge_corpus_cleaning import file_hashes  # noqa: E402
from scripts.knowledge_layout import KB, encoded, registry_payload, write_atomic, check_layout  # noqa: E402
from app.core.retrieval.knowledge_base import load_documents, chunk_documents  # noqa: E402

BASE = "provenance/evidence-base"
DESCRIPTOR = BASE + "/manifest.json"
SNAPSHOT = "provenance/active-evidence-snapshot.json"


@contextmanager
def reconstructed_previous(active=KB):
    with previous.reconstructed_base(active, descriptor_path=DESCRIPTOR, profile=builder.PROFILE, blob_base=BASE) as base:
        yield base


def verify_active(active=None, *, verify_upstream=False):
    active = Path(active or KB).resolve()
    check_layout(active)
    manifest = json.loads(previous.asset(active, "metadata.json").read_text(encoding="utf-8"))
    marker = manifest.get("active_evidence_chunking") or {}
    snapshot = json.loads(previous.asset(active, SNAPSHOT).read_text(encoding="utf-8"))
    if marker.get("profile") != builder.PROFILE or marker.get("snapshot_hash") != builder.sha(encoded(snapshot)):
        raise ValueError("active v2 marker/snapshot mismatch")
    with reconstructed_previous(active) as base:
        if verify_upstream:
            previous.verify_active(base, verify_upstream=True)
        old_manifest = json.loads(previous.asset(base, "metadata.json").read_text(encoding="utf-8"))
        expected = deepcopy(old_manifest)
        expected.pop("active_corpus_cleaning", None)
        expected["document_identity_revision"] += "-evidence-v2"
        expected["chunking"] = {"strategy": "recursive_v1", "chunk_size": 900, "chunk_overlap": 100}
        expected["staged_evidence_chunking"] = {"profile": builder.PROFILE, "strategy": "markdown_evidence_v2",
            "target_chars": 900, "soft_max_chars": 1200, "overlap_chars": 100, "ingested": False,
            "parent_context_runtime_enabled": False}
        auxiliary = {}
        for spec in expected["documents"]:
            text = previous.asset(base, spec["file"]).read_text(encoding="utf-8")
            value, spans, links, _ = builder.transform(spec, text)
            auxiliary[spec["id"]] = links
            spec["chunking_strategy"] = "markdown_evidence_v2"
            if value != text:
                if spec.get("document_type") == "authoritative_original":
                    spec["normalized_hash"] = builder.sha(value.encode())
                    spec["parser_version"] = spec.get("parser_version", "base") + "+auxiliary-links-v1"
                if spans:
                    spec["page_spans"] = spans
            if previous.asset(active, spec["file"]).read_text(encoding="utf-8") != value:
                raise ValueError(f"v2 body replay mismatch: {spec['id']}")
        if {key: value for key, value in manifest.items() if key != "active_evidence_chunking"} != expected:
            raise ValueError("v2 metadata does not match deterministic replay")
        actual_aux = json.loads(previous.asset(active, "provenance/auxiliary_links.json").read_text(encoding="utf-8"))
        if actual_aux["documents"] != auxiliary or actual_aux["profile"] != builder.PROFILE:
            raise ValueError("v2 auxiliary links replay mismatch")
    docs = load_documents(str(active))
    chunks = chunk_documents(docs, chunk_size=900, chunk_overlap=100)
    if (snapshot["profile"] != builder.PROFILE or snapshot["documents"] != len(docs)
            or snapshot["chunks"] != len(chunks) or snapshot["chunk_snapshot_hash"] != builder.digest_chunks(chunks)):
        raise ValueError("v2 active chunk identity mismatch")
    print(f"Active evidence-v2 verified: {len(docs)} docs / {len(chunks)} chunks; no index writes")
    return snapshot


def promote(output, receipt_dir, *, active=None):
    active = Path(active or KB).resolve()
    receipt_dir = previous.private_receipt(receipt_dir)
    if (active / DESCRIPTOR).exists():
        raise ValueError("evidence corpus already promoted")
    builder.verify(output, source=active)
    output = builder.valid_output(output)
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    before = file_hashes(active)
    if before != audit["source_hashes"]:
        raise ValueError("source drift before promotion")
    kb_id = json.loads(previous.asset(active, "metadata.json").read_text(encoding="utf-8"))["knowledge_base_id"]
    candidate = output / "corpus" / kb_id
    target_hashes = file_hashes(candidate)
    if set(before) - set(target_hashes):
        raise ValueError("candidate omitted source assets")
    writes = {name: previous.asset(candidate, name).read_bytes() for name, value in target_hashes.items()
              if value != before.get(name) and name != "provenance/registry.json"}
    overrides = {}
    for name, value in before.items():
        if value != target_hashes.get(name) or name in {"metadata.json", "README.md", "provenance/registry.json"}:
            blob = f"{BASE}/blobs/{value}.source"
            overrides[name] = blob
            writes[blob] = previous.asset(active, name).read_bytes()
    writes[DESCRIPTOR] = encoded({"schema_version": 1, "profile": builder.PROFILE, "assets": before, "overrides": overrides})
    snapshot = {"profile": builder.PROFILE, "documents": len(audit["documents"]), "chunks": audit["new"]["count"],
                "chunk_snapshot_hash": audit["candidate_snapshot_hash"], "parent_context_runtime_enabled": False}
    writes[SNAPSHOT] = encoded(snapshot)
    manifest = json.loads(previous.asset(candidate, "metadata.json").read_text(encoding="utf-8"))
    manifest["active_evidence_chunking"] = {"profile": builder.PROFILE, "base_descriptor": DESCRIPTOR,
        "snapshot_hash": builder.sha(encoded(snapshot)), "parent_context_runtime_enabled": False}
    writes["metadata.json"] = encoded(manifest)
    writes["README.md"] = ("# RAG知识库：教学单元v2（T28）\n\n"
        "当前文件为62篇/1121片（六教材44片），900目标/1200软限/100overlap。实际索引ready以维护receipt为准。\n"
        "纯辅助URL保存在provenance/auxiliary_links.json，不进正文。原文与许可不变。\n"
        "父context未启用，Evidence仍最多1200字符，长原子仅存全文、不保证完整入模。\n"
        "T26旧3177输入可由provenance/evidence-base重建，再经cleaning-base追溯T24；基线blob不入索引。\n").encode()
    receipt_dir.mkdir(parents=True, exist_ok=False)
    write_atomic(receipt_dir / ".gitignore", b"*\n")
    shutil.copytree(active, receipt_dir / "source-before")
    if file_hashes(receipt_dir / "source-before") != before or file_hashes(active) != before:
        raise ValueError("source drift during backup")
    receipt = {"status": "prepared", "source": str(active), "before_hashes": before,
        "planned_hashes": {name: builder.sha(value) for name, value in writes.items()}, "snapshot": snapshot, "ingested": False}
    write_atomic(receipt_dir / "receipt.json", encoded(receipt))
    try:
        for name, value in writes.items():
            path = previous.asset(active, name, exists=False)
            actual = builder.sha(path.read_bytes()) if path.exists() else None
            if actual != before.get(name):
                raise ValueError("source changed during promotion")
            write_atomic(path, value)
        registry = encoded(registry_payload(active))
        receipt["planned_hashes"]["provenance/registry.json"] = builder.sha(registry)
        write_atomic(receipt_dir / "receipt.json", encoded(receipt))
        if builder.sha(previous.asset(active, "provenance/registry.json").read_bytes()) != before["provenance/registry.json"]:
            raise ValueError("source registry changed during promotion")
        write_atomic(previous.asset(active, "provenance/registry.json"), registry)
        verify_active(active)
    except Exception as exc:
        try:
            previous.rollback(receipt_dir, active=active)
        except Exception as recovery:
            receipt.update(status="recovery_blocked", safe_error=type(exc).__name__, recovery_error=type(recovery).__name__)
            write_atomic(receipt_dir / "receipt.json", encoded(receipt))
            raise recovery from exc
        raise
    receipt.update(status="files_promoted", after_hashes=file_hashes(active))
    write_atomic(receipt_dir / "receipt.json", encoded(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "output/knowledge-cleaning/T27")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.check:
        verify_active(verify_upstream=True)
    elif args.receipt is None:
        parser.error("--receipt is required")
    elif args.rollback:
        previous.rollback(args.receipt, active=KB)
    else:
        promote(args.output, args.receipt)


if __name__ == "__main__":
    main()
