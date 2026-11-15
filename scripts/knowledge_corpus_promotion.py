"""Backed-up file promotion and portable replay for a cleaned knowledge corpus.

This module never imports SQL, vectors, models or process management. Database
maintenance remains the separate, stopped-service ingestion step.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.retrieval.knowledge_paths import resolve_knowledge_file  # noqa: E402
from scripts import knowledge_corpus_cleaning as cleaner  # noqa: E402
from scripts.knowledge_layout import check_layout, encoded, registry_payload, write_atomic  # noqa: E402

BASE = "provenance/cleaning-base"
DESCRIPTOR = BASE + "/manifest.json"
ACTIVE_SNAPSHOT = "provenance/active-cleaning-snapshot.json"


def asset(root, name, *, exists=True):
    return resolve_knowledge_file(Path(root), name, must_exist=exists)


def private_receipt(path):
    path = Path(path).resolve()
    allowed = (ROOT / "backend/data/knowledge_backups").resolve()
    if path == allowed or not path.is_relative_to(allowed):
        raise ValueError("receipt must be a new private knowledge_backups child")
    return path


@contextmanager
def reconstructed_base(active, *, descriptor_path=DESCRIPTOR, profile=cleaner.PROFILE, blob_base=BASE):
    active = Path(active).resolve()
    descriptor = json.loads(asset(active, descriptor_path).read_text(encoding="utf-8"))
    if descriptor.get("schema_version") != 1 or descriptor.get("profile") != profile:
        raise ValueError("unsupported source baseline descriptor")
    scratch = (ROOT / "output/test-runs/kb-source-replay").resolve()
    if not scratch.is_relative_to(ROOT.resolve()):
        raise ValueError("scratch directory escaped workspace")
    scratch.mkdir(parents=True, exist_ok=True)
    write_atomic(scratch / ".gitignore", b"*\n")
    with tempfile.TemporaryDirectory(prefix="base-", dir=scratch) as directory:
        base = Path(directory)
        for name, expected in descriptor["assets"].items():
            override = descriptor["overrides"].get(name)
            if override is not None:
                if not re.fullmatch(re.escape(blob_base) + r"/blobs/[0-9a-f]{64}\.source", override):
                    raise ValueError("unsafe baseline blob reference")
                data = asset(active, override).read_bytes()
            else:
                data = asset(active, name).read_bytes()
            if cleaner.sha(data) != expected:
                raise ValueError(f"source baseline drift: {name}")
            write_atomic(asset(base, name, exists=False), data)
        if cleaner.file_hashes(base) != descriptor["assets"]:
            raise ValueError("reconstructed baseline incomplete")
        yield base


@contextmanager
def prep_roots(base):
    """Bind only file preparers to the scratch base, restoring all globals."""
    from scripts import prepare_authoritative_sources as pilot
    from scripts import expand_authoritative_sources as bulk
    from scripts import prepare_chinese_sources as chinese
    bindings = [(pilot, "KB_ROOT", base), (pilot, "REGISTRY_PATH", base / pilot.REGISTRY_RELATIVE_PATH),
                (bulk, "KB_ROOT", base), (bulk, "REGISTRY_PATH", base / bulk.REGISTRY_RELATIVE_PATH),
                (bulk, "CATALOG_PATH", base / bulk.CATALOG_RELATIVE_PATH),
                (chinese, "KB", base), (chinese, "CATALOG", base / "provenance/catalogs/chinese.json")]
    original = [(module, name, getattr(module, name)) for module, name, _ in bindings]
    try:
        for module, name, value in bindings:
            setattr(module, name, value)
        yield pilot, bulk, chinese
    finally:
        for module, name, value in original:
            setattr(module, name, value)


def verify_active(active=None, *, verify_upstream=False):
    active = Path(active or cleaner.KB).resolve()
    if (active / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import verify_active as verify_evidence
        return verify_evidence(active, verify_upstream=verify_upstream)
    check_layout(active)
    active_manifest = json.loads(asset(active, "metadata.json").read_text(encoding="utf-8"))
    marker = active_manifest.get("active_corpus_cleaning") or {}
    if marker.get("profile") != cleaner.PROFILE or marker.get("base_descriptor") != DESCRIPTOR:
        raise ValueError("active cleaning marker missing or unsupported")
    audit = json.loads(asset(active, "provenance/cleaning.json").read_text(encoding="utf-8"))
    descriptor = json.loads(asset(active, DESCRIPTOR).read_text(encoding="utf-8"))
    if descriptor["assets"] != audit["canonical_asset_hashes"]:
        raise ValueError("audit baseline differs from replay descriptor")
    with reconstructed_base(active) as base:
        if verify_upstream:
            with prep_roots(base) as (pilot, bulk, chinese):
                pilot.check_offline()
                _, raw, sources = bulk.read_catalog()
                bulk.check_offline(raw, sources)
                chinese.prepare(offline=True)
        manifest, _, cleaned, reports = cleaner.analyze(base)
        expected = cleaner.derive_manifest(manifest, cleaned, reports)
        # The one explicit root activation marker is not document identity data.
        actual_base = {key: value for key, value in active_manifest.items() if key != "active_corpus_cleaning"}
        if actual_base != expected or reports != audit["documents"]:
            raise ValueError("active manifest/audit differs from deterministic replay")
        for spec in expected["documents"]:
            if asset(active, spec["file"]).read_bytes().decode("utf-8") != cleaned[spec["id"]][0]:
                raise ValueError(f"active cleaned body differs from replay: {spec['id']}")
    from app.core.retrieval.knowledge_base import load_documents, chunk_documents
    documents = load_documents(str(active))
    chunks = chunk_documents(documents)
    fixture = json.loads(asset(active, ACTIVE_SNAPSHOT).read_text(encoding="utf-8"))
    identities = {doc.metadata["document_id"]: {"document_version": doc.metadata["document_version"],
                   "content_hash": doc.metadata["document_content_hash"]} for doc in documents}
    if (fixture["identities"] != identities or fixture["documents"] != len(documents)
            or fixture["chunks"] != len(chunks) or marker["candidate_snapshot_hash"] != cleaner.sha(encoded(fixture))):
        raise ValueError("active corpus identity snapshot differs")
    print(f"Active cleaned sources verified: {len(documents)} documents / {len(chunks)} chunks; no index writes")
    return fixture


def rollback(receipt_dir, *, active=None):
    active = Path(active or cleaner.KB).resolve()
    receipt_dir = private_receipt(receipt_dir)
    receipt = json.loads((receipt_dir / "receipt.json").read_text(encoding="utf-8"))
    if Path(receipt["source"]).resolve() != active:
        raise ValueError("rollback source mismatch")
    before = receipt["before_hashes"]
    planned = receipt["planned_hashes"]
    current = cleaner.file_hashes(active)
    # Reject concurrent edits rather than overwrite another person's work.
    if set(current) - set(before) - set(planned):
        raise ValueError("unknown files appeared during promotion; manual recovery required")
    if set(before) - set(current):
        raise ValueError("concurrent source deletion prevents safe rollback")
    for name, fingerprint in current.items():
        if fingerprint not in {before.get(name), planned.get(name)}:
            raise ValueError("concurrent source edit prevents safe rollback")
    if cleaner.file_hashes(receipt_dir / "source-before") != before:
        raise ValueError("backup source hash differs; refusing rollback")
    for name in set(planned) - set(before):
        target = asset(active, name, exists=False)
        if target.is_file():
            target.unlink()
    for name in before:
        write_atomic(asset(active, name, exists=False), asset(receipt_dir / "source-before", name).read_bytes())
    if cleaner.file_hashes(active) != before:
        raise ValueError("source rollback incomplete")
    receipt["status"] = "source_rolled_back"
    write_atomic(receipt_dir / "receipt.json", encoded(receipt))
    check_layout(active)


def promote(output, receipt_dir, *, active=None):
    active = Path(active or cleaner.KB).resolve()
    receipt_dir = private_receipt(receipt_dir)
    if (active / DESCRIPTOR).exists():
        raise ValueError("a corpus is already promoted; do not overwrite its baseline")
    fixture = cleaner.verify(output)
    output = cleaner.safe_output(Path(output))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    before = cleaner.file_hashes(active)
    if before != audit["canonical_asset_hashes"]:
        raise ValueError("canonical changed since candidate build")
    manifest = json.loads(asset(active, "metadata.json").read_text(encoding="utf-8"))
    candidate = output / "corpus" / manifest["knowledge_base_id"]
    candidate_hashes = cleaner.file_hashes(candidate)
    if set(before) - set(candidate_hashes):
        raise ValueError("candidate omitted source assets")
    writes = {name: asset(candidate, name).read_bytes() for name, digest in candidate_hashes.items()
              if digest != before.get(name)}
    # Keep the old registry until the entire new source snapshot is present.
    # It is generated once below, never through an ambiguous intermediate hash.
    writes.pop("provenance/registry.json", None)
    overrides = {}
    for name, fingerprint in before.items():
        if fingerprint != candidate_hashes.get(name) or name in {"metadata.json", "README.md", "provenance/registry.json"}:
            blob = f"{BASE}/blobs/{fingerprint}.source"
            overrides[name] = blob
            writes[blob] = asset(active, name).read_bytes()
    descriptor = {"schema_version": 1, "profile": cleaner.PROFILE, "assets": before, "overrides": overrides}
    writes[DESCRIPTOR] = encoded(descriptor)
    writes[ACTIVE_SNAPSHOT] = encoded(fixture)
    active_manifest = json.loads(asset(candidate, "metadata.json").read_text(encoding="utf-8"))
    active_manifest["active_corpus_cleaning"] = {"profile": cleaner.PROFILE, "base_descriptor": DESCRIPTOR,
        "candidate_snapshot_hash": cleaner.sha(encoded(fixture)), "expected_chunk_count": fixture["chunks"]}
    writes["metadata.json"] = encoded(active_manifest)
    writes["README.md"] = ("# RAG知识库：全库清洗版（T26）\n\n"
        "当前文件使用T25核验的62篇/3177片清洗资料；实际数据库是否激活以入库receipt和health为准。\n"
        "原始快照和许可保留，105个待核查断词保留；旧资料可由provenance/cleaning-base重放。\n"
        "所有教学正文只由metadata清单载入，基线blob不入索引。\n\n"
        "以下为切换前资料说明，数字与状态属于历史记录：\n\n"
        + asset(active, "README.md").read_text(encoding="utf-8")).encode("utf-8")
    receipt_dir.mkdir(parents=True, exist_ok=False)
    write_atomic(receipt_dir / ".gitignore", b"*\n")
    shutil.copytree(active, receipt_dir / "source-before")
    if cleaner.file_hashes(receipt_dir / "source-before") != before or cleaner.file_hashes(active) != before:
        raise ValueError("source drift during backup")
    receipt = {"status": "prepared", "source": str(active), "candidate": str(candidate),
               "before_hashes": before, "planned_hashes": {name: cleaner.sha(data) for name, data in writes.items()},
               "snapshot": fixture, "ingested": False}
    write_atomic(receipt_dir / "receipt.json", encoded(receipt))
    try:
        for name, data in writes.items():
            target = asset(active, name, exists=False)
            existing = cleaner.sha(target.read_bytes()) if target.exists() else None
            if existing != before.get(name):
                raise ValueError("target changed during promotion")
            write_atomic(target, data)
        registry_data = encoded(registry_payload(active))
        # Persist the intended hash before writing, so interrupted writes remain
        # distinguishable from concurrent edits during recovery.
        receipt["planned_hashes"]["provenance/registry.json"] = cleaner.sha(registry_data)
        write_atomic(receipt_dir / "receipt.json", encoded(receipt))
        if cleaner.sha(asset(active, "provenance/registry.json").read_bytes()) != before["provenance/registry.json"]:
            raise ValueError("source registry changed during promotion")
        write_atomic(asset(active, "provenance/registry.json"), registry_data)
        verify_active(active)
    except Exception as exc:
        try:
            rollback(receipt_dir, active=active)
        except Exception as recovery:
            receipt["status"] = "recovery_blocked"
            receipt["safe_error"] = type(exc).__name__
            receipt["recovery_error"] = type(recovery).__name__
            write_atomic(receipt_dir / "receipt.json", encoded(receipt))
            raise recovery from exc
        raise
    receipt["status"] = "files_promoted"
    receipt["after_hashes"] = cleaner.file_hashes(active)
    write_atomic(receipt_dir / "receipt.json", encoded(receipt))
    print(f"Promoted source files; {len(before)} original assets backed up; index not yet changed")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "output/knowledge-cleaning/T25")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.check:
        verify_active(verify_upstream=True)
    elif args.receipt is None:
        parser.error("--receipt is required for apply/rollback")
    elif args.rollback:
        rollback(args.receipt)
    else:
        promote(args.output, args.receipt)


if __name__ == "__main__":
    main()
