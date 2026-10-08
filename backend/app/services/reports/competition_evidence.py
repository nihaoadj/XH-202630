"""Frozen local knowledge sources for reproducible competition test data."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.config import PROJECT_ROOT


def confined_path(root: Path, relative: str) -> Path:
    base = root.resolve()
    target = (base / relative).resolve()
    if Path(relative).is_absolute() or not target.is_relative_to(base):
        raise ValueError("fixture/source path must remain within its root")
    return target


def text_hash(path: Path) -> str:
    # Path.read_text normalizes CRLF to LF, making Git Windows/Linux checkouts agree.
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def json_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def build_source_snapshot(knowledge_base_id: str, claims_payload: dict,
                          kb_root: str | Path | None = None) -> dict:
    root = Path(kb_root) if kb_root else PROJECT_ROOT / "knowledge_base"
    kb = confined_path(root, knowledge_base_id)
    metadata = json.loads((kb / "metadata.json").read_text(encoding="utf-8"))
    documents = {item["id"]: item for item in metadata.get("documents", [])}
    files = {"metadata.json": text_hash(kb / "metadata.json")}
    for document in documents.values():
        files[document["file"]] = text_hash(confined_path(kb, document["file"]))
    for name in ("questionnaire.json", "diagnostic_questions.json", "assessment_questions.json"):
        if (kb / name).exists():
            files[name] = text_hash(kb / name)
    evidence = {}
    for claim in claims_payload["claims"]:
        for evidence_id in claim["evidence_ids"]:
            match = re.fullmatch(r"ev-mod(\d+)-sec(\d+)", evidence_id)
            document = documents.get(claim.get("source_document_id"))
            if not match or not document or int(match[1]) != document.get("module_number"):
                raise ValueError(f"unknown source reference: {evidence_id}")
            text = confined_path(kb, document["file"]).read_text(encoding="utf-8")
            sections = list(re.finditer(r"^## .+$", text, re.MULTILINE))
            section = next((i for i, item in enumerate(sections)
                            if re.match(rf"## {int(match[2])}\.", item.group())), None)
            if section is None:
                raise ValueError(f"unknown source section: {evidence_id}")
            start = sections[section].start()
            end = sections[section + 1].start() if section + 1 < len(sections) else len(text)
            entry = {"document_id": document["id"], "file": document["file"],
                     "section": sections[section].group(), "start_line": text[:start].count("\n") + 1,
                     "end_line": text[:end].count("\n"),
                     "section_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
                     "source_urls": document.get("source_urls", [])}
            if evidence_id in evidence and evidence[evidence_id] != entry:
                raise ValueError(f"source reference conflict: {evidence_id}")
            evidence[evidence_id] = entry
    return {"schema_version": "1.0", "knowledge_base_id": knowledge_base_id,
            "knowledge_base_version": metadata.get("version"), "hash_normalization": "utf8-lf",
            "provenance": "local_curated_modules_with_primary_source_links; online/independent review not certified",
            "files": files, "evidence": evidence}


def validate_source_snapshot(snapshot: dict, knowledge_base_id: str, claims_payload: dict,
                             kb_root: str | Path | None = None) -> None:
    current = build_source_snapshot(knowledge_base_id, claims_payload, kb_root)
    if snapshot != current:
        raise ValueError("frozen knowledge/source snapshot drift; review gold annotations before re-freezing")
