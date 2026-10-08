"""Canonical, content-addressed identifiers for knowledge provenance."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping


ID_SCHEME_VERSION = "1"
KNOWLEDGE_SCHEMA_VERSION = "1.0"
QUERY_STRATEGY_VERSION = "deterministic-v1"
RANKING_STRATEGY_VERSION = "normalized-score-v1"


def normalize_text(value: str) -> str:
    """Normalize text without changing its semantic line structure."""

    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip()


def normalize_source_path(value: str) -> str:
    """Return one KB-relative POSIX path and reject path traversal."""

    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    windows_path = PureWindowsPath(raw)
    if (
        not raw
        or path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in path.parts
    ):
        raise ValueError("source_path must be a knowledge-base-relative path")
    normalized = path.as_posix()
    if normalized in {".", ""}:
        raise ValueError("source_path must identify a file")
    return normalized


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identifier(prefix: str, *parts: object) -> str:
    material = "|".join([ID_SCHEME_VERSION, *(str(part) for part in parts)])
    return f"{prefix}_{sha256_hex(material)[:24]}"


def document_id(knowledge_base_id: str, source_path: str) -> str:
    return _identifier("doc", knowledge_base_id, normalize_source_path(source_path))


def document_version_id(
    knowledge_base_id: str,
    logical_document_id: str,
    normalized_content_hash: str,
) -> str:
    return _identifier(
        "dv",
        knowledge_base_id,
        logical_document_id,
        normalized_content_hash,
    )


def chunking_config_hash(config: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(config)))


def chunk_id(
    *,
    knowledge_base_id: str,
    logical_document_id: str,
    document_version: str,
    chunking_hash: str,
    ordinal: int,
    text_hash: str,
) -> str:
    return _identifier(
        "chk",
        knowledge_base_id,
        logical_document_id,
        document_version,
        chunking_hash,
        ordinal,
        text_hash,
    )


def query_hash(query: str) -> str:
    return sha256_hex(normalize_text(query))


def retrieval_config_hash(config: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(config)))


def evidence_id(
    *,
    run_id: str,
    step_id: str,
    knowledge_base_id: str,
    retrieval_query_hash: str,
    knowledge_chunk_id: str,
    config_hash: str,
) -> str:
    return _identifier(
        "ev",
        KNOWLEDGE_SCHEMA_VERSION,
        run_id,
        step_id,
        knowledge_base_id,
        retrieval_query_hash,
        knowledge_chunk_id,
        config_hash,
    )
