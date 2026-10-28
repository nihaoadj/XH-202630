#!/usr/bin/env python3
"""Fetch and verify the fixed authoritative-source pilot snapshots.

The generated files are source artifacts, not application code. This script
never follows redirects, executes source examples, or fetches linked content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PARSER_VERSION = "passthrough-v1"
REGISTRY_SCHEMA_VERSION = 1
MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT_SECONDS = 20.0
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.core.retrieval.knowledge_paths import resolve_knowledge_file  # noqa: E402
from scripts.knowledge_layout import license_destination, reference_paths  # noqa: E402

KB_ROOT = ROOT / "knowledge_base" / "rag_engineering_training"
REGISTRY_RELATIVE_PATH = "provenance/import_batches/pilot.json"
REGISTRY_PATH = resolve_knowledge_file(KB_ROOT, REGISTRY_RELATIVE_PATH, must_exist=False)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    repository: str
    commit: str
    upstream_path: str
    sha256: str
    license_id: str

    @property
    def url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repository}/{self.commit}/{self.upstream_path}"

    @property
    def snapshot_path(self) -> str:
        return reference_paths(self.source_id, Path(self.upstream_path).suffix.lstrip("."))[0]

    @property
    def normalized_path(self) -> str:
        return reference_paths(self.source_id, Path(self.upstream_path).suffix.lstrip("."))[1]

    @property
    def license_path(self) -> str:
        return license_destination(f"sources/licenses/{self.license_id}/LICENSE")


@dataclass(frozen=True)
class LicenseSpec:
    license_id: str
    repository: str
    commit: str
    sha256: str

    @property
    def url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repository}/{self.commit}/LICENSE"

    @property
    def local_path(self) -> str:
        return license_destination(f"sources/licenses/{self.license_id}/LICENSE")


LANGCHAIN_REPOSITORY = "langchain-ai/docs"
SENTENCE_TRANSFORMERS_REPOSITORY = "huggingface/sentence-transformers"
LANGCHAIN_COMMIT = "4506df5fb4105a39b84c2b7390d21bed89e28668"
SENTENCE_TRANSFORMERS_COMMIT = "33f9bd81610560e48ff5eac80e910496b49ae193"

SOURCES = (
    SourceSpec(
        source_id="source_langchain_markdown_splitter",
        repository=LANGCHAIN_REPOSITORY,
        commit=LANGCHAIN_COMMIT,
        upstream_path="src/oss/python/integrations/splitters/markdown_header_metadata_splitter.mdx",
        sha256="9e74b44f9fe42bfb6f527b0cc261d234dd4b5858501caa508403f60e0c718d07",
        license_id="langchain",
    ),
    SourceSpec(
        source_id="source_sbert_semantic_search",
        repository=SENTENCE_TRANSFORMERS_REPOSITORY,
        commit=SENTENCE_TRANSFORMERS_COMMIT,
        upstream_path="examples/sentence_transformer/applications/semantic-search/README.md",
        sha256="b6cac22cf354b8094980df9b9ae917153426ef08ccab72753c82d66a43d8aba2",
        license_id="sentence-transformers",
    ),
    SourceSpec(
        source_id="source_sbert_retrieve_rerank",
        repository=SENTENCE_TRANSFORMERS_REPOSITORY,
        commit=SENTENCE_TRANSFORMERS_COMMIT,
        upstream_path="examples/sentence_transformer/applications/retrieve_rerank/README.md",
        sha256="09b06f45ace03283345462a5a317f988b28d4cf95990ac61d4e51612eca4be9a",
        license_id="sentence-transformers",
    ),
)

LICENSES = (
    LicenseSpec(
        license_id="langchain",
        repository=LANGCHAIN_REPOSITORY,
        commit=LANGCHAIN_COMMIT,
        sha256="98af1351ea856e008c835bc89a312905960a318072f950732bf346c741027c7d",
    ),
    LicenseSpec(
        license_id="sentence-transformers",
        repository=SENTENCE_TRANSFORMERS_REPOSITORY,
        commit=SENTENCE_TRANSFORMERS_COMMIT,
        sha256="624b030fd62b8b989dd502d5bb6322cbc0dbb524ab9c9708f32efe33d7275735",
    ),
)


class PreparationError(RuntimeError):
    """An expected source, registry, or filesystem validation failed."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_utf8(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PreparationError(f"{label} is not valid UTF-8: {exc}") from exc


def normalize_source(spec: SourceSpec, original: bytes) -> bytes:
    """Apply only the agreed MDX frontmatter/title normalization."""
    text = validate_utf8(original, spec.source_id)
    if not spec.upstream_path.endswith(".mdx"):
        return original

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise PreparationError(f"{spec.source_id} is expected to start with YAML frontmatter")

    closing_index = next(
        (index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") in {"---", "..."}),
        None,
    )
    if closing_index is None:
        raise PreparationError(f"{spec.source_id} has unterminated YAML frontmatter")

    title = None
    for line in lines[1:closing_index]:
        match = re.match(r"^title:\s*(.*?)\s*(?:\r?\n)?$", line)
        if match:
            title = match.group(1).strip()
            if len(title) >= 2 and title[0] == title[-1] and title[0] in {'"', "'"}:
                title = title[1:-1]
            break
    if not title:
        raise PreparationError(f"{spec.source_id} frontmatter is missing a non-empty title")

    body = "".join(lines[closing_index + 1 :])
    separator = "\n" if body.startswith(("\n", "\r")) else "\n\n"
    normalized = f"# {title}{separator}{body}"
    return normalized.encode("utf-8")


def fetch_https(url: str, expected_sha256: str, label: str) -> bytes:
    """Fetch one bounded, non-redirecting HTTPS response and verify its pin."""
    try:
        import httpx
    except ImportError as exc:
        raise PreparationError("httpx is required for downloads; offline --check does not need it") from exc

    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    chunks: list[bytes] = []
    size = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise PreparationError(f"{label}: expected HTTP 200, received {response.status_code}")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > MAX_RESPONSE_BYTES:
                            raise PreparationError(f"{label}: response exceeds {MAX_RESPONSE_BYTES} bytes")
                    except ValueError:
                        pass
                for chunk in response.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise PreparationError(f"{label}: response exceeds {MAX_RESPONSE_BYTES} bytes")
                    chunks.append(chunk)
    except PreparationError:
        raise
    except httpx.HTTPError as exc:
        raise PreparationError(f"{label}: HTTPS request failed: {exc}") from exc

    data = b"".join(chunks)
    validate_utf8(data, label)
    actual_sha256 = sha256_hex(data)
    if actual_sha256 != expected_sha256:
        raise PreparationError(
            f"{label}: SHA-256 mismatch; expected {expected_sha256}, received {actual_sha256}"
        )
    return data


def relative_path(path: str) -> Path:
    try:
        return resolve_knowledge_file(KB_ROOT, path, must_exist=False)
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc


def read_existing_registry() -> dict[str, Any] | None:
    if not REGISTRY_PATH.exists():
        return None
    if REGISTRY_PATH.is_symlink() or not REGISTRY_PATH.is_file():
        raise PreparationError(f"registry target is not a regular file: {REGISTRY_PATH}")
    try:
        content = REGISTRY_PATH.read_bytes()
        registry = json.loads(validate_utf8(content, str(REGISTRY_PATH)))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"cannot read registry {REGISTRY_PATH}: {exc}") from exc
    if not isinstance(registry, dict):
        raise PreparationError("registry root must be a JSON object")
    if registry.get("schema_version") not in (None, REGISTRY_SCHEMA_VERSION):
        raise PreparationError("existing registry schema_version conflicts with this script")
    if registry.get("parser_version") not in (None, PARSER_VERSION):
        raise PreparationError("existing registry parser_version conflicts with this script")
    return registry


def index_records(registry: dict[str, Any] | None, key: str, identity_key: str) -> dict[str, dict[str, Any]]:
    if registry is None:
        return {}
    records = registry.get(key, [])
    if not isinstance(records, list):
        raise PreparationError(f"registry field {key!r} must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get(identity_key), str):
            raise PreparationError(f"registry field {key!r} contains an invalid record")
        identity = record[identity_key]
        if identity in indexed:
            raise PreparationError(f"registry field {key!r} contains duplicate identity {identity!r}")
        indexed[identity] = record
    return indexed


def validate_immutable_record(
    existing: dict[str, Any] | None,
    expected: dict[str, Any],
    identity: str,
) -> str | None:
    if existing is None:
        return None
    for field, value in expected.items():
        if field == "fetched_at":
            continue
        if existing.get(field) != value:
            raise PreparationError(f"registry record {identity!r} conflicts on field {field!r}")
    fetched_at = existing.get("fetched_at")
    if not isinstance(fetched_at, str) or not fetched_at:
        raise PreparationError(f"registry record {identity!r} has no fetched_at timestamp")
    try:
        timestamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError(f"registry record {identity!r} has an invalid fetched_at timestamp") from exc
    if timestamp.tzinfo is None:
        raise PreparationError(f"registry record {identity!r} fetched_at must include a timezone")
    return fetched_at


def check_existing_target(relative: str, expected: bytes) -> bool:
    path = relative_path(relative)
    if path.is_symlink():
        raise PreparationError(f"refusing to use symlink target: {path}")
    if not path.exists():
        return False
    if not path.is_file():
        raise PreparationError(f"target is not a regular file: {path}")
    existing = path.read_bytes()
    if existing != expected and not (
        relative == REGISTRY_RELATIVE_PATH and _same_json(existing, expected)
    ):
        expected_hash = sha256_hex(expected)
        actual_hash = sha256_hex(existing)
        raise PreparationError(
            f"existing target differs; refusing to overwrite {path} "
            f"(expected SHA-256 {expected_hash}, found {actual_hash})"
        )
    return True


def _same_json(existing: bytes, expected: bytes) -> bool:
    try:
        return json.loads(existing.decode("utf-8")) == json.loads(expected.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def write_if_absent(relative: str, data: bytes) -> bool:
    path = relative_path(relative)
    if path.is_symlink():
        raise PreparationError(f"refusing to use symlink target: {path}")
    if path.exists():
        if not path.is_file() or (
            path.read_bytes() != data
            and not (relative == REGISTRY_RELATIVE_PATH and _same_json(path.read_bytes(), data))
        ):
            raise PreparationError(f"target changed after preflight; refusing to overwrite {path}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except OSError:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return True


def timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_records(
    previous: dict[str, Any] | None,
    normalized_data: dict[str, bytes],
) -> dict[str, Any]:
    old_sources = index_records(previous, "sources", "id")
    old_licenses = index_records(previous, "licenses", "id")
    now = timestamp_now()

    source_records: list[dict[str, Any]] = []
    for spec in SOURCES:
        normalized_hash = sha256_hex(normalized_data[spec.source_id])
        record: dict[str, Any] = {
            "id": spec.source_id,
            "repository": spec.repository,
            "commit": spec.commit,
            "upstream_path": spec.upstream_path,
            "url": spec.url,
            "snapshot_path": spec.snapshot_path,
            "sha256": spec.sha256,
            "normalized_path": spec.normalized_path,
            "normalized_sha256": normalized_hash,
            "license_path": spec.license_path,
            "parser_version": PARSER_VERSION,
            "document_type": "authoritative_original",
            "fetched_at": now,
        }
        previous_timestamp = validate_immutable_record(old_sources.get(spec.source_id), record, spec.source_id)
        if previous_timestamp:
            record["fetched_at"] = previous_timestamp
        source_records.append(record)

    license_records: list[dict[str, Any]] = []
    for spec in LICENSES:
        record = {
            "id": spec.license_id,
            "repository": spec.repository,
            "commit": spec.commit,
            "upstream_path": "LICENSE",
            "url": spec.url,
            "path": spec.local_path,
            "sha256": spec.sha256,
            "fetched_at": now,
        }
        previous_timestamp = validate_immutable_record(old_licenses.get(spec.license_id), record, spec.license_id)
        if previous_timestamp:
            record["fetched_at"] = previous_timestamp
        license_records.append(record)

    registry = dict(previous or {})
    # Preserve any future records in an existing registry; current pilot entries
    # are replaced only after their immutable metadata has been validated above.
    for record in (previous or {}).get("sources", []):
        if record.get("id") not in {spec.source_id for spec in SOURCES}:
            source_records.append(record)
    for record in (previous or {}).get("licenses", []):
        if record.get("id") not in {spec.license_id for spec in LICENSES}:
            license_records.append(record)

    registry.update(
        {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "sources": source_records,
            "licenses": license_records,
        }
    )
    return registry


def registry_bytes(registry: dict[str, Any]) -> bytes:
    return (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def download() -> int:
    original_data: dict[str, bytes] = {}
    normalized_data: dict[str, bytes] = {}
    license_data: dict[str, bytes] = {}

    for spec in SOURCES:
        original = fetch_https(spec.url, spec.sha256, spec.source_id)
        original_data[spec.source_id] = original
        normalized_data[spec.source_id] = normalize_source(spec, original)
    for spec in LICENSES:
        license_data[spec.license_id] = fetch_https(spec.url, spec.sha256, f"{spec.license_id} LICENSE")

    previous = read_existing_registry()
    # Complete every conflict check before the first filesystem write.
    for spec in SOURCES:
        check_existing_target(spec.snapshot_path, original_data[spec.source_id])
        check_existing_target(spec.normalized_path, normalized_data[spec.source_id])
    for spec in LICENSES:
        check_existing_target(spec.local_path, license_data[spec.license_id])
    registry_content = registry_bytes(build_records(previous, normalized_data))
    check_existing_target(REGISTRY_RELATIVE_PATH, registry_content)

    created = 0
    for spec in SOURCES:
        created += write_if_absent(spec.snapshot_path, original_data[spec.source_id])
        created += write_if_absent(spec.normalized_path, normalized_data[spec.source_id])
    for spec in LICENSES:
        created += write_if_absent(spec.local_path, license_data[spec.license_id])
    created += write_if_absent(REGISTRY_RELATIVE_PATH, registry_content)
    print(f"Prepared and verified {len(SOURCES)} source snapshots and {len(LICENSES)} licenses; created {created} files.")
    return 0


def check_offline() -> int:
    registry = read_existing_registry()
    if registry is None:
        raise PreparationError(f"missing registry: {REGISTRY_PATH}")
    source_records = index_records(registry, "sources", "id")
    license_records = index_records(registry, "licenses", "id")

    for spec in SOURCES:
        record = source_records.get(spec.source_id)
        if record is None:
            raise PreparationError(f"registry is missing source {spec.source_id!r}")
        original_path = relative_path(spec.snapshot_path)
        normalized_path = relative_path(spec.normalized_path)
        if not original_path.is_file() or original_path.is_symlink():
            raise PreparationError(f"missing or invalid original source file: {original_path}")
        if not normalized_path.is_file() or normalized_path.is_symlink():
            raise PreparationError(f"missing or invalid normalized source file: {normalized_path}")
        original = original_path.read_bytes()
        normalized = normalized_path.read_bytes()
        validate_utf8(original, spec.source_id)
        validate_utf8(normalized, spec.source_id + " normalized")
        if sha256_hex(original) != spec.sha256:
            raise PreparationError(f"original SHA-256 mismatch: {original_path}")
        expected_normalized = normalize_source(spec, original)
        if normalized != expected_normalized:
            raise PreparationError(f"normalized content does not match the approved transformation: {normalized_path}")

        expected_record = {
            "id": spec.source_id,
            "repository": spec.repository,
            "commit": spec.commit,
            "upstream_path": spec.upstream_path,
            "url": spec.url,
            "snapshot_path": spec.snapshot_path,
            "sha256": spec.sha256,
            "normalized_path": spec.normalized_path,
            "normalized_sha256": sha256_hex(expected_normalized),
            "license_path": spec.license_path,
            "parser_version": PARSER_VERSION,
            "document_type": "authoritative_original",
        }
        validate_immutable_record(record, {**expected_record, "fetched_at": record.get("fetched_at")}, spec.source_id)
        if record.get("normalized_sha256") != sha256_hex(normalized):
            raise PreparationError(f"registry normalized SHA-256 mismatch for {spec.source_id}")

    for spec in LICENSES:
        record = license_records.get(spec.license_id)
        if record is None:
            raise PreparationError(f"registry is missing license {spec.license_id!r}")
        path = relative_path(spec.local_path)
        if not path.is_file() or path.is_symlink():
            raise PreparationError(f"missing or invalid license file: {path}")
        content = path.read_bytes()
        validate_utf8(content, f"{spec.license_id} LICENSE")
        if sha256_hex(content) != spec.sha256:
            raise PreparationError(f"license SHA-256 mismatch: {path}")
        expected_record = {
            "id": spec.license_id,
            "repository": spec.repository,
            "commit": spec.commit,
            "upstream_path": "LICENSE",
            "url": spec.url,
            "path": spec.local_path,
            "sha256": spec.sha256,
        }
        validate_immutable_record(record, {**expected_record, "fetched_at": record.get("fetched_at")}, spec.license_id)

    print(f"Offline check passed: {len(SOURCES)} source snapshots and {len(LICENSES)} licenses are complete and verified.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify the prepared files and registry offline without writing",
    )
    args = parser.parse_args(argv)
    try:
        return check_offline() if args.check else download()
    except PreparationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: filesystem operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
