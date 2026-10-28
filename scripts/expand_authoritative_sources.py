#!/usr/bin/env python3
"""Prepare the fixed bulk source catalog as immutable, auditable KB assets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import re
import sys
from time import monotonic
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.core.retrieval.knowledge_paths import resolve_knowledge_file  # noqa: E402
from scripts.knowledge_layout import reference_paths  # noqa: E402

KB_ROOT = ROOT / "knowledge_base" / "rag_engineering_training"
CATALOG_RELATIVE_PATH = "provenance/catalogs/bulk.json"
REGISTRY_RELATIVE_PATH = "provenance/import_batches/bulk.json"
CATALOG_PATH = resolve_knowledge_file(KB_ROOT, CATALOG_RELATIVE_PATH, must_exist=False)
REGISTRY_PATH = resolve_knowledge_file(KB_ROOT, REGISTRY_RELATIVE_PATH, must_exist=False)
CACHE_ROOT = ROOT / "output" / "test-runs" / "kb-bulk" / "download-cache"
MAX_DOWNLOAD_BYTES = 16 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30.0
EXPECTED_SOURCE_COUNT = 18
PARSER_VERSION = "bulk-authoritative-v1"
PDF_PARSER_VERSION = "pypdf-5.1.0-pages-v1"
MARKDOWN_PARSER_VERSION = "passthrough-frontmatter-h1-v1"
FIXED_COMMITS = {
    "langchain-ai/docs": "4506df5fb4105a39b84c2b7390d21bed89e28668",
    "huggingface/sentence-transformers": "33f9bd81610560e48ff5eac80e910496b49ae193",
}
LICENSE_URLS = {
    "ACL-CC-BY-4.0": "https://aclanthology.org/faq/copyright/",
    "langchain": "https://opensource.org/license/mit",
    "sentence-transformers": "https://www.apache.org/licenses/LICENSE-2.0",
}
KNOWN_POINTS = {
    "RAG 基础概念", "文档解析", "Chunk 切分", "Embedding", "向量数据库",
    "相似度检索", "混合检索", "Rerank", "Prompt 组装", "引用溯源",
    "幻觉控制", "RAG 评测", "RAG 调优",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9_-]+$")
ANTHOLOGY_RE = re.compile(r"^\d{4}\.[a-z0-9-]+\.\d+$")
ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
REFERENCE_MARKER_RE = re.compile(
    r"(?:\b(?:19|20)\d{2}[a-z]?\b|\bdoi\s*:|\bhttps?://|\barxiv\b|^\s*\[?\d+\]?\s*[.)])",
    re.IGNORECASE,
)
EVALUATION_RE = re.compile(
    r"\b(experiment(?:s)?|evaluation|results?|ablation|benchmark|metric|recall@|precision@|mrr|ndcg|faithfulness)\b|评测|实验|结果|指标",
    re.IGNORECASE,
)


class SourceError(RuntimeError):
    """Catalog, source, extraction, or conflict validation failed."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SourceError(f"{label} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise SourceError(f"{label} is not a safe relative path: {value!r}")
    return value


def license_id_for_path(relative: str) -> str:
    if relative == "licenses/acl/CC-BY-4.0":
        return "ACL-CC-BY-4.0"
    path = PurePosixPath(relative)
    return path.parent.name if path.name == "LICENSE" else path.name


def local_path(relative: str) -> Path:
    safe_relative(relative, "local path")
    try:
        return resolve_knowledge_file(KB_ROOT, relative, must_exist=False)
    except ValueError as exc:
        raise SourceError(str(exc)) from exc


def cache_path(digest: str) -> Path:
    if not SHA256_RE.fullmatch(digest):
        raise SourceError("invalid source hash for download cache")
    candidate = CACHE_ROOT / f"{digest}.source"
    current = ROOT
    for part in candidate.relative_to(ROOT).parts:
        current = current / part
        if current.is_symlink():
            raise SourceError(f"refusing symlink cache path: {current}")
    try:
        candidate.resolve(strict=False).relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SourceError("download cache path escapes workspace root") from exc
    return candidate


def write_cache(item: dict, data: bytes) -> None:
    if sha256_hex(data) != item["sha256"]:
        raise SourceError(f"{item['id']}: refusing to cache bytes before SHA-256 verification")
    path = cache_path(item["sha256"])
    existing = safe_file(path)
    if existing is not None:
        if sha256_hex(existing) != item["sha256"]:
            raise SourceError(f"{item['id']}: existing download cache has a hash conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
    except FileExistsError:
        existing = safe_file(path, required=True)
        if sha256_hex(existing) != item["sha256"]:
            raise SourceError(f"{item['id']}: download cache changed during write")


def safe_file(path: Path, *, required: bool = False) -> bytes | None:
    if path.is_symlink():
        raise SourceError(f"refusing symlink: {path}")
    if not path.exists():
        if required:
            raise SourceError(f"missing required file: {path}")
        return None
    if not path.is_file():
        raise SourceError(f"expected a regular file: {path}")
    return path.read_bytes()


def read_catalog() -> tuple[dict, bytes, list[dict]]:
    raw = safe_file(CATALOG_PATH, required=True)
    try:
        catalog = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"invalid bulk catalog: {exc}") from exc
    if not isinstance(catalog, dict):
        raise SourceError("bulk catalog root must be a JSON object")
    sources = catalog.get("sources")
    if catalog.get("schema_version") != 1 or not isinstance(sources, list):
        raise SourceError("bulk catalog must have schema_version=1 and a sources list")
    if len(sources) != EXPECTED_SOURCE_COUNT:
        raise SourceError(f"expected {EXPECTED_SOURCE_COUNT} fixed catalog sources, got {len(sources)}")

    seen: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            raise SourceError("catalog source entries must be objects")
        source_id = item.get("id")
        if not isinstance(source_id, str) or not ID_RE.fullmatch(source_id) or source_id in seen:
            raise SourceError(f"invalid or duplicate source id: {source_id!r}")
        seen.add(source_id)
        if not isinstance(item.get("title"), str) or not item["title"].strip():
            raise SourceError(f"{source_id}: missing title")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise SourceError(f"{source_id}: SHA-256 must be lowercase hexadecimal")
        points = item.get("default_points")
        if not isinstance(points, list) or not points or any(p not in KNOWN_POINTS for p in points):
            raise SourceError(f"{source_id}: invalid or empty default_points")
        license_path = safe_relative(item.get("license_path"), f"{source_id} license_path")
        license_id = license_id_for_path(license_path)
        if item.get("license_url") != LICENSE_URLS.get(license_id):
            raise SourceError(f"{source_id}: license URL/path is not on the fixed allowlist")

        kind = item.get("kind")
        url = item.get("url")
        if kind == "pdf":
            anthology = item.get("anthology")
            if not isinstance(anthology, str) or not ANTHOLOGY_RE.fullmatch(anthology):
                raise SourceError(f"{source_id}: invalid ACL Anthology numeric ID")
            if url != f"https://aclanthology.org/{anthology}.pdf":
                raise SourceError(f"{source_id}: PDF URL does not match its ACL Anthology ID")
            if not isinstance(item.get("pages"), int) or item["pages"] < 1:
                raise SourceError(f"{source_id}: PDF expected page count is required")
        else:
            repo, commit = item.get("repository"), item.get("commit")
            if repo not in FIXED_COMMITS or commit != FIXED_COMMITS[repo]:
                raise SourceError(f"{source_id}: repository or commit is outside the fixed allowlist")
            prefix = f"https://raw.githubusercontent.com/{repo}/{commit}/"
            if not isinstance(url, str) or not url.startswith(prefix):
                raise SourceError(f"{source_id}: URL must be the exact raw GitHub URL for its commit")
            upstream = url[len(prefix):]
            safe_relative(upstream, f"{source_id} upstream path")
            expected_ext = {"mdx": ".mdx", "markdown": ".md", "python": ".py"}.get(kind)
            if expected_ext is None or not upstream.endswith(expected_ext):
                raise SourceError(f"{source_id}: unsupported source kind/path")
        if kind not in {"pdf", "mdx", "markdown", "python"}:
            raise SourceError(f"{source_id}: unsupported source kind {kind!r}")
    return catalog, raw, sources


def require_pypdf():
    try:
        version = importlib.metadata.version("pypdf")
        if version != "5.1.0":
            raise SourceError(f"pypdf==5.1.0 is required, found {version}")
        from pypdf import PdfReader
    except importlib.metadata.PackageNotFoundError as exc:
        raise SourceError("pypdf==5.1.0 is required for PDF extraction") from exc
    except ImportError as exc:
        raise SourceError(f"cannot import pypdf: {exc}") from exc
    return PdfReader


def fetch_source(item: dict) -> bytes:
    try:
        import httpx
    except ImportError as exc:
        raise SourceError("httpx is required to download missing sources") from exc
    url, expected = item["url"], item["sha256"]
    last_error = "unknown download error"
    for attempt in range(1, 3):
        print(f"download {item['id']} attempt {attempt}/2", flush=True)
        chunks: list[bytes] = []
        size = 0
        started = monotonic()
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
                with client.stream("GET", url) as response:
                    if 300 <= response.status_code < 400:
                        raise SourceError(f"redirect rejected (HTTP {response.status_code})")
                    if response.status_code != 200:
                        raise SourceError(f"expected HTTP 200, got {response.status_code}")
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > MAX_DOWNLOAD_BYTES:
                        raise SourceError(f"response exceeds {MAX_DOWNLOAD_BYTES} bytes")
                    for chunk in response.iter_bytes(64 * 1024):
                        if monotonic() - started > 180:
                            raise SourceError("download exceeded the 180-second wall-clock budget")
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise SourceError(f"response exceeds {MAX_DOWNLOAD_BYTES} bytes")
                        chunks.append(chunk)
            data = b"".join(chunks)
            if item["kind"] == "pdf" and not data.startswith(b"%PDF-"):
                raise SourceError("ACL Anthology response is not a PDF")
            actual = sha256_hex(data)
            if actual != expected:
                raise SourceError(f"SHA-256 mismatch: expected {expected}, got {actual}")
            return data
        except SourceError as exc:
            last_error = str(exc)
        except httpx.HTTPError as exc:
            last_error = f"HTTPS request failed: {exc}"
        if attempt < 2:
            print(f"retry {item['id']}: {last_error}", flush=True)
    raise SourceError(f"{item['id']}: failed after one retry: {last_error}")


def decode_utf8(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceError(f"{label} is not valid UTF-8: {exc}") from exc


def fence_state(lines: list[str]) -> tuple[list[tuple[int, int, str]], list[str]]:
    """Return ATX heading candidates outside fences and any unclosed fence warnings."""
    headings: list[tuple[int, int, str]] = []
    fence: tuple[str, int, int] | None = None
    warnings: list[str] = []
    for number, line in enumerate(lines, 1):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = (match.group(1)[0], len(match.group(1)), number)
                continue
            heading = ATX_RE.match(line)
            if heading:
                headings.append((number, len(heading.group(1)), heading.group(2).strip()))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
            fence = None
    if fence is not None:
        warnings.append(f"unclosed_code_fence: opening_line={fence[2]}")
    return headings, warnings


def topic_overrides(heading: str) -> list[str]:
    value = heading.casefold()
    points: list[str] = []
    rules = (
        (("embedding",), ["Embedding"]),
        (("chunk", "split"), ["Chunk 切分"]),
        (("parse", "load", "pdf"), ["文档解析"]),
        (("bm25", "hybrid", "sparse"), ["混合检索"]),
        (("rerank", "crossencoder", "cross-encoder", "cross encoder"), ["Rerank"]),
        (("prompt", "context"), ["Prompt 组装"]),
        (("citation", "cite"), ["引用溯源"]),
        (("evaluation", "eval", "metric"), ["RAG 评测"]),
        (("training", "finetun"), ["Embedding", "RAG 调优"]),
    )
    for keywords, additions in rules:
        if any(word in value for word in keywords):
            for point in additions:
                if point not in points:
                    points.append(point)
    return points


def build_section_map(text: str, default_points: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    lines = text.splitlines()
    headings, warnings = fence_state(lines)
    mapping: dict[str, list[str]] = {}
    levels: dict[int, str] = {}
    by_line = {line_number: (level, title) for line_number, level, title in headings}
    # Re-scan lines so headings inside code fences are ignored in the same pass.
    fence: tuple[str, int, int] | None = None
    for line_number, line in enumerate(lines, 1):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = (match.group(1)[0], len(match.group(1)), line_number)
                continue
            entry = by_line.get(line_number)
            if not entry:
                continue
            level, title = entry
            for previous_level in [value for value in levels if value >= level]:
                del levels[previous_level]
            levels[level] = title
            key = " / ".join(levels[value] for value in sorted(levels))
            lower = title.casefold()
            if any(word in lower for word in ("references", "bibliography", "works cited", "参考文献")):
                mapping[key] = []
                continue
            points = list(default_points)
            for point in topic_overrides(title):
                if point not in points:
                    points.append(point)
            mapping[key] = points
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
            fence = None
    return mapping, warnings


def frontmatter(text: str, source_id: str) -> tuple[str, str | None]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return text, None
    closing = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") in {"---", "..."}), None)
    if closing is None:
        raise SourceError(f"{source_id}: unterminated YAML frontmatter")
    title = None
    for line in lines[1:closing]:
        match = re.match(r"^title:\s*(.*?)\s*(?:\r?\n)?$", line)
        if match:
            title = match.group(1).strip().strip("\"'")
            break
    return "".join(lines[closing + 1:]), title or None


def normalize_markdown(item: dict, raw: bytes) -> tuple[bytes, dict[str, list[str]], list[str], str]:
    text = decode_utf8(raw, item["id"])
    title = item["title"]
    if item["kind"] == "mdx":
        text, source_title = frontmatter(text, item["id"])
        title = source_title or title
    lines = text.splitlines()
    first = next((line for line in lines if line.strip()), "")
    # Existing authored H1 is retained; otherwise add the catalog/frontmatter title.
    if not re.match(r"^ {0,3}#\s+", first):
        text = f"# {title}\n\n{text}"
    text, container_warnings = split_rst_tabs(text)
    mapping, warnings = build_section_map(text, item["default_points"])
    warnings.extend(container_warnings)
    if item["kind"] == "mdx":
        body, _ = frontmatter(decode_utf8(raw, item["id"]), item["id"])
        imported = mdx_snippet_imports(body)
        if imported:
            warnings.append("unexpanded_mdx_imports: " + ", ".join(imported))
    if not mapping:
        mapping = {title: list(item["default_points"])}
    return text.encode("utf-8"), mapping, warnings, title


def split_rst_tabs(text: str) -> tuple[str, list[str]]:
    """Split oversized documentation containers only at their original tabs.

    Keep each complete architecture example together, rather than truncating
    source or slicing through Python examples. The raw snapshot is unchanged.
    """
    warnings = []

    def replace(match):
        if len(match.group(0)) <= 12000:
            return match.group(0)
        fence, body = match.group(1), match.group(2)
        boundaries = [0, *[entry.start() for entry in re.finditer(r"(?m)^\.\. tab:: ", body)], len(body)]
        parts = [body[start:end] for start, end in zip(boundaries, boundaries[1:]) if body[start:end].strip()]
        if len(parts) < 2 or any(len(part) + len(fence) * 2 + 20 > 12000 for part in parts):
            raise SourceError("Oversized eval-rst container has no safe tab boundaries")
        warnings.append(f"split_eval_rst_container_at_original_tabs: {len(parts)}")
        return "\n\n".join(f"{fence}{{eval-rst}}\n{part}" + ("" if part.endswith("\n") else "\n") + fence for part in parts)

    return re.sub(r"(?ms)^(`{3,})\{eval-rst\}\n(.*?)^\1[ \t]*$", replace, text), warnings


def mdx_snippet_imports(body: str) -> list[str]:
    lines = body.splitlines()
    found: list[str] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = (match.group(1)[0], len(match.group(1)))
                continue
            if re.match(r"^\s*import\s+", line):
                found.extend(re.findall(r"['\"](/snippets/[^'\"]+)['\"]", line))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
            fence = None
    return list(dict.fromkeys(found))


def clean_pdf_page(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n ")


def is_reference_page(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    if lines[0].casefold().strip(" :") in {"references", "bibliography", "works cited", "参考文献"}:
        candidates = lines[1:]
    else:
        candidates = lines
    if len(candidates) < 3:
        return False
    return sum(bool(REFERENCE_MARKER_RE.search(line)) for line in candidates) / len(candidates) >= 0.6


def require_pdf_reader():
    return require_pypdf()


def normalize_pdf(item: dict, raw: bytes) -> tuple[bytes, dict, list[dict], list[dict], int]:
    if not raw.startswith(b"%PDF-"):
        raise SourceError(f"{item['id']}: original bytes do not have a PDF signature")
    PdfReader = require_pdf_reader()
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise SourceError(f"{item['id']}: encrypted PDF is not supported")
        page_texts = [clean_pdf_page(page.extract_text() or "") for page in reader.pages]
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f"{item['id']}: PDF extraction failed: {exc}") from exc
    if len(page_texts) != item["pages"]:
        raise SourceError(f"{item['id']}: expected {item['pages']} pages, extracted {len(page_texts)}")
    for number, page_text in enumerate(page_texts, 1):
        if not page_text.strip():
            raise SourceError(f"{item['id']}: PDF page {number} is empty after normalization")
        malformed = page_text.count("\ufffd") + len(re.findall(r"\(cid:\d+\)", page_text))
        if malformed > max(10, len(page_text) // 100):
            raise SourceError(f"{item['id']}: PDF page {number} has excessive extraction artifacts")
    char_count = sum(len(page) for page in page_texts)
    if char_count < 1000:
        raise SourceError(f"{item['id']}: only {char_count} extracted characters; minimum is 1000")

    lines: list[str] = []
    spans: list[dict] = []
    page_review: list[dict] = []
    section_points: dict[str, list[str]] = {}
    for number, page_text in enumerate(page_texts, 1):
        if lines:
            lines.append("")
        line_start = len(lines) + 1
        lines.append(f"## PDF page {number}")
        body_lines = page_text.split("\n")
        lines.extend(body_lines)
        title_line = next((line.strip() for line in body_lines if line.strip()), f"PDF page {number}")
        page_review.append(
            {
                "page": number,
                "title": title_line[:120],
                "review_excerpt": page_text[:240],
                "note": "verbatim excerpt only; no generated summary",
            }
        )
        points = [] if is_reference_page(page_text) else list(item["default_points"])
        if points and EVALUATION_RE.search(page_text) and "RAG 评测" not in points:
            points.append("RAG 评测")
        section_points[f"PDF page {number}"] = points
        spans.append({"page": number, "line_start": line_start, "line_end": 0})

    for index in range(len(spans) - 1):
        spans[index]["line_end"] = spans[index + 1]["line_start"] - 1
    spans[-1]["line_end"] = len(lines)
    normalized_text = unicodedata.normalize("NFC", "\n".join(lines)).strip()
    normalized_text = "\n".join(line.rstrip() for line in normalized_text.splitlines())
    normalized = normalized_text.encode("utf-8")
    normalized_lines = normalized_text.splitlines()
    if not spans or spans[0]["line_start"] != 1 or spans[-1]["line_end"] != len(normalized_lines):
        raise SourceError(f"{item['id']}: generated page spans do not cover normalized text")
    for index, span in enumerate(spans):
        if span["line_start"] != (1 if index == 0 else spans[index - 1]["line_end"] + 1):
            raise SourceError(f"{item['id']}: generated page spans have a gap")
        if normalized_lines[span["line_start"] - 1] != f"## PDF page {span['page']}":
            raise SourceError(f"{item['id']}: page span does not start at its exact page heading")
    return normalized, section_points, spans, page_review, char_count


def normalize_python(item: dict, raw: bytes) -> tuple[bytes, dict[str, list[str]], list[str], str]:
    if len(raw) > 12000:
        raise SourceError(f"{item['id']}: Python source exceeds the 12000-byte fenced-source limit")
    code = decode_utf8(raw, item["id"])
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", code)), default=0)
    fence = "`" * max(3, longest + 1)
    title = item["title"]
    normalized = f"# {title}\n\n{fence}python\n{code}"
    if not code.endswith(("\n", "\r")):
        normalized += "\n"
    normalized += f"{fence}\n"
    mapping = {title: list(item["default_points"])}
    return normalized.encode("utf-8"), mapping, [], title


def normalize_source(item: dict, raw: bytes) -> tuple[bytes, dict, list, list, list, int, str]:
    if item["kind"] == "pdf":
        normalized, sections, spans, review, chars = normalize_pdf(item, raw)
        return normalized, sections, [], spans, review, chars, item["title"]
    if item["kind"] == "python":
        normalized, sections, warnings, title = normalize_python(item, raw)
    else:
        normalized, sections, warnings, title = normalize_markdown(item, raw)
    return normalized, sections, warnings, [], [], len(normalized.decode("utf-8")), title


def output_paths(item: dict) -> tuple[str, str]:
    return reference_paths(item["id"], item["kind"])


def get_license(item: dict, cache: dict[str, dict]) -> dict:
    relative = safe_relative(item["license_path"], f"{item['id']} license_path")
    license_id = license_id_for_path(relative)
    path = local_path(relative)
    data = safe_file(path, required=True)
    text = decode_utf8(data, f"license {license_id}")
    checks = {
        "ACL-CC-BY-4.0": "Creative Commons Attribution 4.0 International",
        "langchain": "MIT License",
        "sentence-transformers": "Apache License",
    }
    if checks.get(license_id) not in text:
        raise SourceError(f"{item['id']}: local license text does not match {license_id}")
    if license_id not in cache:
        cache[license_id] = {
            "id": license_id,
            "path": relative,
            "url": item["license_url"],
            "sha256": sha256_hex(data),
            "used_by": [],
        }
    elif cache[license_id]["path"] != relative or cache[license_id]["url"] != item["license_url"]:
        raise SourceError(f"conflicting license metadata for {license_id}")
    cache[license_id]["used_by"].append(item["id"])
    return cache[license_id]


def source_version(item: dict) -> str:
    return item["sha256"] if item["kind"] == "pdf" else item["commit"]


def assemble(item: dict, raw: bytes, license_cache: dict[str, dict], fetched_at: str | None = None) -> dict:
    if sha256_hex(raw) != item["sha256"]:
        raise SourceError(f"{item['id']}: raw snapshot SHA-256 mismatch")
    if item["kind"] != "pdf":
        decode_utf8(raw, item["id"])
    normalized, sections, warnings, spans, page_review, chars, normalized_title = normalize_source(item, raw)
    raw_path, normalized_path = output_paths(item)
    version = source_version(item)
    license_record = get_license(item, license_cache)
    normalized_hash = sha256_hex(normalized)
    manifest = {
        "id": item["id"],
        "title": item["title"],
        "file": normalized_path,
        "version": version,
        "source_version": version,
        "source_type": "pdf" if item["kind"] == "pdf" else "markdown",
        "document_type": "authoritative_original",
        "authority": "ACL Anthology" if item["kind"] == "pdf" else item["repository"],
        "knowledge_points": item["default_points"],
        "source_urls": [item["url"]],
        "source_snapshot": raw_path,
        "source_hash": item["sha256"],
        "normalized_hash": normalized_hash,
        "parser_version": (
            PDF_PARSER_VERSION if item["kind"] == "pdf" else MARKDOWN_PARSER_VERSION
            + ("-rst-tabs" if any(warning.startswith("split_eval_rst_container") for warning in warnings) else "")
        ),
        "license": item["license_path"],
        "chunking_strategy": "markdown_structure_v1",
        "section_knowledge_points": sections,
    }
    if item["kind"] == "pdf":
        manifest["page_spans"] = spans
    record = {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "url": item["url"],
        "original_path": raw_path,
        "original_sha256": item["sha256"],
        "normalized_path": normalized_path,
        "normalized_sha256": normalized_hash,
        "parser_version": manifest["parser_version"],
        "license_path": item["license_path"],
        "license_url": item["license_url"],
        "license_sha256": license_record["sha256"],
        "fetched_at": fetched_at or timestamp_now(),
        "extracted_characters": chars,
        "section_knowledge_points": sections,
        "normalization_warnings": warnings,
    }
    if item["kind"] == "pdf":
        record.update({"page_count": item["pages"], "page_spans": spans, "page_review": page_review})
    else:
        record["repository"] = item["repository"]
        record["commit"] = item["commit"]
        record["source_title"] = normalized_title
    return {"item": item, "raw": raw, "normalized": normalized, "record": record, "manifest": manifest}


def read_existing_registry() -> dict | None:
    data = safe_file(REGISTRY_PATH)
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"invalid existing bulk registry: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceError("existing bulk registry must be a JSON object")
    return value


def timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def prior_timestamps(registry: dict | None, *, offline: bool) -> dict[str, str]:
    if registry is None:
        if offline:
            raise SourceError("--check: missing bulk registry")
        return {}
    records = registry.get("sources", [])
    if not isinstance(records, list):
        raise SourceError("existing bulk registry sources must be a list")
    result: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise SourceError("existing bulk registry contains an invalid source record")
        source_id = record["id"]
        if source_id in result:
            raise SourceError(f"existing bulk registry contains duplicate source {source_id}")
        timestamp = record.get("fetched_at")
        if timestamp is None and not offline:
            continue
        if not isinstance(timestamp, str) or not timestamp:
            raise SourceError(f"existing source {source_id} has no fetched_at timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceError(f"existing source {source_id} has invalid fetched_at") from exc
        if parsed.tzinfo is None:
            raise SourceError(f"existing source {source_id} fetched_at must include a timezone")
        result[source_id] = timestamp
    return result


def registry_document(catalog_raw: bytes, sources: list[dict], licenses: dict[str, dict]) -> dict:
    return {
        "schema_version": 1,
        "parser_version": PARSER_VERSION,
        "catalog_path": CATALOG_RELATIVE_PATH,
        "catalog_sha256": sha256_hex(catalog_raw),
        "licenses": list(licenses.values()),
        "sources": [entry["record"] for entry in sources],
        "manifest_documents": [entry["manifest"] for entry in sources],
    }


def _same_json(existing: bytes, expected: bytes) -> bool:
    try:
        return json.loads(existing.decode("utf-8")) == json.loads(expected.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def check_target(relative: str, expected: bytes, *, json_semantic: bool = False) -> bool:
    path = local_path(relative)
    existing = safe_file(path)
    if existing is None:
        return False
    if existing != expected and not (json_semantic and _same_json(existing, expected)):
        raise SourceError(f"existing target conflicts; refusing overwrite: {path}")
    return True


def write_if_absent(relative: str, data: bytes, *, json_semantic: bool = False) -> bool:
    path = local_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SourceError(f"refusing symlink target: {path}")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
    except FileExistsError:
        existing = safe_file(path, required=True)
        if existing != data and not (json_semantic and _same_json(existing, data)):
            raise SourceError(f"target changed after preflight; refusing overwrite: {path}")
        return False
    return True


def print_review(entries: list[dict]) -> None:
    for entry in entries:
        for page in entry["record"].get("page_review", []):
            excerpt = page["review_excerpt"].replace("\n", " ")[:160]
            print(f"review {entry['item']['id']} page={page['page']} title={page['title']!r} excerpt={excerpt!r}", flush=True)
        for warning in entry["record"].get("normalization_warnings", []):
            print(f"warning {entry['item']['id']}: {warning}", flush=True)


def load_entries(
    sources: list[dict], *, offline: bool, previous: dict | None
) -> tuple[list[dict], dict[str, dict]]:
    entries: list[dict] = []
    licenses: dict[str, dict] = {}
    timestamps = prior_timestamps(previous, offline=offline)
    for item in sources:
        raw_path, normalized_path = output_paths(item)
        raw_file = local_path(raw_path)
        raw = safe_file(raw_file)
        if raw is not None:
            actual = sha256_hex(raw)
            if actual != item["sha256"]:
                raise SourceError(f"{item['id']}: existing snapshot SHA-256 mismatch; refusing reuse")
            print(f"reuse verified snapshot {item['id']} sha256={actual}", flush=True)
        elif offline:
            raise SourceError(f"--check: missing source snapshot {raw_file}")
        else:
            cached = safe_file(cache_path(item["sha256"]))
            if cached is not None:
                actual = sha256_hex(cached)
                if actual != item["sha256"]:
                    raise SourceError(f"{item['id']}: download cache SHA-256 mismatch; refusing reuse")
                raw = cached
                print(f"reuse verified download cache {item['id']} sha256={actual}", flush=True)
            else:
                raw = fetch_source(item)
                write_cache(item, raw)
        entry = assemble(item, raw, licenses, timestamps.get(item["id"]))
        check_target(normalized_path, entry["normalized"])
        entries.append(entry)
    return entries, licenses


def prepare(catalog_raw: bytes, sources: list[dict]) -> int:
    existing_registry = read_existing_registry()
    entries, licenses = load_entries(sources, offline=False, previous=existing_registry)
    registry = registry_document(catalog_raw, entries, licenses)
    registry_bytes = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if existing_registry is not None and existing_registry != registry:
        raise SourceError(f"existing bulk registry conflicts; refusing overwrite: {REGISTRY_PATH}")
    # Validate every destination before writing any source asset.
    for entry in entries:
        raw_path, normalized_path = output_paths(entry["item"])
        check_target(raw_path, entry["raw"])
        check_target(normalized_path, entry["normalized"])
    check_target(REGISTRY_RELATIVE_PATH, registry_bytes, json_semantic=True)
    created = 0
    for entry in entries:
        raw_path, normalized_path = output_paths(entry["item"])
        created += write_if_absent(raw_path, entry["raw"])
        created += write_if_absent(normalized_path, entry["normalized"])
    created += write_if_absent(REGISTRY_RELATIVE_PATH, registry_bytes, json_semantic=True)
    print_review(entries)
    pdfs = [entry for entry in entries if entry["item"]["kind"] == "pdf"]
    print(
        f"Prepared {len(entries)} fixed sources ({len(pdfs)} PDFs, "
        f"{sum(e['record'].get('page_count', 0) for e in pdfs)} pages, "
        f"{sum(e['record']['extracted_characters'] for e in pdfs)} PDF characters); created {created} files.",
        flush=True,
    )
    return 0


def check_offline(catalog_raw: bytes, sources: list[dict]) -> int:
    existing_registry = read_existing_registry()
    entries, licenses = load_entries(sources, offline=True, previous=existing_registry)
    registry = registry_document(catalog_raw, entries, licenses)
    if existing_registry is None:
        raise SourceError(f"--check: missing registry {REGISTRY_PATH}")
    if existing_registry != registry:
        raise SourceError("--check: bulk registry does not match catalog and verified local assets")
    for entry in entries:
        _, normalized_path = output_paths(entry["item"])
        existing = safe_file(local_path(normalized_path), required=True)
        if existing != entry["normalized"]:
            raise SourceError(f"--check: normalized content mismatch: {normalized_path}")
    print_review(entries)
    print(f"Offline check passed: {len(entries)} fixed source snapshots, normalized files, licenses and registry verified.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing assets offline without downloading or writing")
    args = parser.parse_args(argv)
    try:
        _, catalog_raw, sources = read_catalog()
        return check_offline(catalog_raw, sources) if args.check else prepare(catalog_raw, sources)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    except OSError as exc:
        print(f"error: filesystem operation failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
