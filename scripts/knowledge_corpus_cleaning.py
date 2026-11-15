"""Build a fully audited, FILE-ONLY cleaned KB candidate. Never ingests data.

The canonical KB and its fixed-source preparers are the reproducible input
layer. This separate build layer creates a new, unactivated candidate. No SQL,
vector, embedding, LLM, network or service lifecycle API is used here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import difflib
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit, urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from markdown_it import MarkdownIt  # noqa: E402
from scripts.knowledge_layout import KB, check_layout, encoded, registry_payload, write_atomic  # noqa: E402

PROFILE = "corpus-clean-v1"
_MARKDOWN = MarkdownIt("commonmark").enable("table")
_INLINE_CODE = re.compile(r"(?<![\\`])(?P<run>`+)(?!`)(?P<body>.*?)(?<!`)(?P=run)(?!`)", re.S)
_PDF_INLINE_CODE = re.compile(r"(?<![\\`])(?P<run>`+)(?!`)(?P<body>[^\n]*?)(?<!`)(?P=run)(?!`)")
_MD_IMAGE = re.compile(r"!\[([^]\n]*)\]\(([^)\n]+)\)")
_MD_BADGE_LINK = re.compile(r"\[(!\[([^]\n]*)\]\(([^)\n]+)\))\]\(([^)\n]+)\)")
_HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.I)
_HTML_ANCHOR = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.I | re.S)
_WORD = re.compile(r"(?<![A-Za-z-])[a-z]{4,}(?![A-Za-z-])")
_COMPOUND = re.compile(r"\b[A-Za-z]{2,}(?:-[A-Za-z]{2,})+\b")
# These are spelling repairs, not a synonym/translation dictionary. Every edit
# still requires an actual alphabetic line-end split within one physical page.
_KNOWN_WORDS = set("examine augmented using embeddings hallucination hallucinations languages ability techniques engines".split())
_HYPHEN_PREFIXES = {"non", "dual", "cross", "self", "zero", "few", "multi", "bi", "large"}
_LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlinks are not allowed in corpus assets")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def protected_lines(text: str) -> list[bool]:
    """CommonMark code/table spans plus explicit display-math blocks."""
    lines = text.splitlines(keepends=True)
    mask = [False] * len(lines)
    for token in _MARKDOWN.parse(text):
        if token.type in {"fence", "code_block", "table_open"} and token.map:
            for index in range(token.map[0], min(token.map[1], len(lines))):
                mask[index] = True
    # Raw HTML containers can hide Markdown from CommonMark's block parser.
    # Explicit fences must remain protected even inside <details>/<div>.
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            mask[index] = True
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker:
            fence = marker[1]
            mask[index] = True
    if fence:
        raise ValueError("unclosed code fence")
    math_end = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if mask[index]:
            continue
        if math_end is not None:
            mask[index] = True
            if stripped == math_end:
                math_end = None
        elif stripped in {"$$", r"\["}:
            math_end = "$$" if stripped == "$$" else r"\]"
            mask[index] = True
    if math_end is not None:
        raise ValueError("unclosed display math block")
    return mask


def protected_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    mask = protected_lines(text)
    blocks, current = [], []
    for line, protected in zip(lines, mask, strict=True):
        if protected:
            current.append(line)
        elif current:
            blocks.append("".join(current))
            current = []
    if current:
        blocks.append("".join(current))
    return blocks


def inline_signatures(text: str, *, pdf=False):
    signatures, pending = [], []
    pattern = _PDF_INLINE_CODE if pdf else _INLINE_CODE
    for line, protected in zip(text.splitlines(keepends=True), protected_lines(text), strict=True):
        if not protected:
            pending.append(line)
        elif pending:
            signatures.extend(pattern.findall("".join(pending)))
            pending = []
    signatures.extend(pattern.findall("".join(pending)))
    return signatures


class _Tag(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.attrs = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.attrs = dict(attrs)


def is_badge(source: str) -> bool:
    value = html.unescape(source).lower()
    return any(part in value for part in (
        "shields.io/", "pepy.tech/badge", "colab-badge", "deepwiki.com/badge",
        "trendshift.io/api/badge", "badge.fury.io/", "badge.svg", "badge.png",
    ))


def is_brand_image(source: str, alt: str) -> bool:
    path = urlsplit(html.unescape(source)).path.lower()
    return ("contrib.rocks/" in source.lower()
            or bool(re.search(r"(?:^|[/_-])logo(?:[._-]|$)", path))
            or alt.strip().lower() in {"logo", "mineru logo", "bge logo"})


def example_target(url: str) -> bool:
    parsed = urlsplit(html.unescape(url))
    return parsed.scheme == "https" and (
        parsed.hostname == "colab.research.google.com"
        or parsed.hostname == "github.com" and parsed.path.endswith(".ipynb")
    )


def technical_badge(alt: str, url: str) -> str | None:
    target = html.unescape(url)
    if example_target(target):
        return f"[配套示例：{alt.strip() or 'Notebook'}]({target})"
    if urlsplit(target).hostname in {"arxiv.org", "aclanthology.org"}:
        return f"[论文：{alt.strip() or '技术报告'}]({target})"
    return None


def clean_prose(text: str, counts: Counter, base: str | None = None) -> str:
    inline = []

    def hide(match):
        inline.append(match[0])
        return f"\ue000INLINE{len(inline) - 1}\ue001"

    if "\ue000INLINE" in text:
        raise ValueError("reserved cleaning placeholder in source")
    text = _INLINE_CODE.sub(hide, text)
    text, amount = re.subn(r"(?m)^ {4,}(?=<(?:a|img)\b)", "", text)
    counts["html_display_indents_removed"] += amount

    def badge_link(match):
        if not is_badge(match[3]):
            return match[0]
        kept = technical_badge(match[2], match[4])
        counts["technical_badges_to_links" if kept else "badge_links_removed"] += 1
        return kept or ""

    text = _MD_BADGE_LINK.sub(badge_link, text)

    def md_image(match):
        if is_badge(match[2]) or is_brand_image(match[2], match[1]):
            counts["display_images_removed"] += 1
            return ""
        return match[0]

    text = _MD_IMAGE.sub(md_image, text)

    def image(match):
        attrs = _Tag(match[0]).attrs
        source, alt = attrs.get("src", ""), attrs.get("alt", "")
        if is_badge(source) or is_brand_image(source, alt):
            counts["display_images_removed"] += 1
            return ""
        if source:
            counts["educational_images_to_markdown"] += 1
            label = html.unescape(alt).replace("[", r"\[").replace("]", r"\]") or "图示，见原文"
            target = html.unescape(source)
            if base and not target.startswith("#"):
                target = urljoin(base, target)
            return f"![{label}]({target})"
        return match[0]

    def anchor(match):
        attrs = _Tag("<a" + match["attrs"] + ">").attrs
        target = attrs.get("href", "")
        body = match["body"]
        images = list(_HTML_IMAGE.finditer(body))
        if images and any(is_badge(_Tag(item[0]).attrs.get("src", "")) for item in images):
            alt = _Tag(images[0][0]).attrs.get("alt", "")
            kept = technical_badge(alt, target)
            counts["technical_badges_to_links" if kept else "badge_links_removed"] += 1
            return kept or ""
        label = _HTML_IMAGE.sub(image, body).strip()
        if not label:
            counts["empty_links_removed"] += 1
            return ""
        if target and not target.startswith(("javascript:", "data:")):
            counts["html_links_to_markdown"] += 1
            target = html.unescape(target)
            if base and not target.startswith("#"):
                target = urljoin(base, target)
            return f"[{label}]({target})"
        return label

    # Remove only known standalone social invitation paragraphs, not prose
    # explaining an agent's technical usage/constraints or attribution sections.
    def paragraph(match):
        body = match[1]
        if (re.search(r"join us|加入.{0,8}(?:交流群|社区)", body, re.I)
                and re.search(r"discord\.gg|wechat|weixin|community-portal", body, re.I)):
            counts["social_invitation_blocks_removed"] += 1
            return "\n"
        return match[0]

    text = re.sub(r"<p\b[^>]*>(.*?)</p\s*>", paragraph, text, flags=re.I | re.S)
    text = _HTML_ANCHOR.sub(anchor, text)
    text = _HTML_IMAGE.sub(image, text)
    text, amount = re.subn(r"\[\s*\]\([^\n)]*\)", "", text)
    counts["empty_links_removed"] += amount
    # Only layout/container tags are unwrapped. Unknown HTML is kept for review.
    text, amount = re.subn(r"<!--\s*(?:logo|icon|language|join us|links?|badges?)\s*-->", "", text, flags=re.I)
    counts["layout_comments_removed"] += amount
    text, amount = re.subn(r"</?(?:div|p|details|summary)\b[^>]*>", "\n", text, flags=re.I)
    counts["layout_wrappers_unwrapped"] += amount
    # A run of in-page menu links is site navigation, not a technical reference
    # list (which has bullets, prose or external targets and is retained).
    menu = r"(?m)(?:^[ \t]*\[[^]\n]+\]\(#[^)\n]+\)[ \t]*\|?[ \t]*\n){3,}"
    text, amount = re.subn(menu, "", text)
    counts["navigation_menus_removed"] += amount
    text, amount = re.subn(r"(?m)^([ ]{0,3}[-+*])[ \t]+\n(?:[ \t]*\n){0,2}(?=[^\s#|`~+*-])", r"\1 ", text)
    counts["orphan_list_markers_rejoined"] += amount
    text, amount = re.subn(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    counts["control_characters_removed"] += amount
    for index, value in enumerate(inline):
        text = text.replace(f"\ue000INLINE{index}\ue001", value)
    return text


def compact_blanks(text: str, counts: Counter, *, pdf=False) -> str:
    lines, mask = text.splitlines(keepends=True), protected_lines(text)
    # Multiline inline code is still code. Protect its complete source span
    # before compressing paragraph separators; PDF accents are not Markdown.
    pattern = _PDF_INLINE_CODE if pdf else _INLINE_CODE
    index = 0
    while index < len(lines):
        if mask[index]:
            index += 1
            continue
        end = index
        while end < len(lines) and not mask[end]:
            end += 1
        prose = "".join(lines[index:end])
        for match in pattern.finditer(prose):
            first = index + prose[:match.start()].count("\n")
            last = index + prose[:match.end() - 1].count("\n")
            for position in range(first, last + 1):
                mask[position] = True
        index = end
    result, blanks = [], 0
    for line, protected in zip(lines, mask, strict=True):
        if protected:
            result.append(line)
            blanks = 0
        elif not line.strip():
            blanks += 1
            if blanks > 1:
                counts["blank_lines_removed"] += 1
            else:
                result.append(line)
        else:
            result.append(line)
            blanks = 0
    return "".join(result)


def clean_markdown(text: str, base: str | None = None) -> tuple[str, Counter]:
    lines, mask = text.splitlines(keepends=True), protected_lines(text)
    counts, result, pending = Counter(), [], []
    for line, protected in zip(lines, mask, strict=True):
        if protected:
            if pending:
                result.append(clean_prose("".join(pending), counts, base))
                pending = []
            result.append(line)
        else:
            pending.append(line)
    if pending:
        result.append(clean_prose("".join(pending), counts, base))
    return compact_blanks("".join(result), counts), counts


def vocabulary(texts: list[str]) -> tuple[set[str], set[str]]:
    words, compounds = set(_KNOWN_WORDS), set()
    for text in texts:
        mask = protected_lines(text)
        prose = "".join(line for line, protected in zip(text.splitlines(keepends=True), mask, strict=True) if not protected)
        prose = prose.translate(_LIGATURES)
        words.update(_WORD.findall(prose.lower()))
        compounds.update(word.lower() for word in _COMPOUND.findall(prose))
    return words, compounds


def split_pdf(text: str, spans: list[dict]) -> list[tuple[int, list[str]]]:
    lines, pages, expected = text.splitlines(keepends=True), [], 1
    for span in spans:
        page, start, end = span["page"], span["line_start"], span["line_end"]
        if start != expected or end < start or end > len(lines) or lines[start - 1].strip() != f"## PDF page {page}":
            raise ValueError("invalid source PDF page spans")
        pages.append((page, lines[start:end]))
        expected = end + 1
    if expected != len(lines) + 1:
        raise ValueError("incomplete PDF page spans")
    return pages


def page_number_positions(pages):
    groups = defaultdict(list)
    for page, lines in pages:
        nonempty = [i for i, line in enumerate(lines) if line.strip()]
        mask = protected_lines("".join(lines))
        for edge, indices in (("head", nonempty[:4]), ("tail", nonempty[-3:])):
            for index in indices:
                value = lines[index].strip()
                if not mask[index] and re.fullmatch(r"[1-9]\d{0,4}", value):
                    groups[(edge, int(value) - page)].append((page, index))
    chosen = set()
    threshold = max(3, (len(pages) + 1) // 2)
    for positions in groups.values():
        if len({page for page, _ in positions}) >= threshold:
            chosen.update(positions)
    return chosen


def clean_pdf(text: str, spans: list[dict], words, compounds):
    pages = split_pdf(text, spans)
    page_numbers = page_number_positions(pages)
    counts, repairs, unresolved, output, new_spans = Counter(), [], [], [], []
    for page, original in pages:
        lines = list(original)
        for index in range(len(lines)):
            if (page, index) in page_numbers:
                lines[index] = ""
                counts["verified_page_numbers_removed"] += 1
        # Do not touch examples/tables/math. No cross-page joins are attempted.
        mask = protected_lines("".join(original))
        for index in range(len(lines)):
            if not mask[index] and not _PDF_INLINE_CODE.search(lines[index]):
                expanded = lines[index].translate(_LIGATURES)
                if expanded != lines[index]:
                    counts["typographic_ligatures_expanded"] += sum(char in "ﬀﬁﬂﬃﬄ" for char in lines[index])
                    lines[index] = expanded
        for index in range(len(lines) - 1):
            if mask[index] or _PDF_INLINE_CODE.search(lines[index]):
                continue
            next_index = index + 1
            while next_index < len(lines) and not mask[next_index] and lines[next_index].strip():
                left = re.match(r"^(.*?)([A-Za-z][A-Za-z-]{1,})-[ \t]*(?:\n)?$", lines[index])
                right = re.match(r"^([A-Za-z][A-Za-z-]{1,})(\b.*)$", lines[next_index], re.S)
                if not left or not right or any(mark in left[1] for mark in ("://", "www.", "\\", "|")):
                    break
                a, b = left[2], right[1]
                joined, hyphenated = a + b, a + "-" + b
                if ("-" in a or "-" in b or hyphenated.lower() in compounds
                        or a.lower() in _HYPHEN_PREFIXES and b[0].isupper()):
                    replacement = hyphenated
                    rule = "compound_hyphen_wraps_joined"
                elif joined.lower() in words and (b[0].islower() or joined.lower() in {"chatgpt", "instructgpt"}):
                    replacement = joined
                    rule = "supported_word_splits_joined"
                else:
                    unresolved.append({"page": page, "line_in_page": index + 1, "left": a, "right": b,
                                       "reason": "no_unambiguous_spelling_support"})
                    break
                counts[rule] += 1
                repairs.append({"page": page, "left": a, "right": b, "replacement": replacement, "rule": rule})
                lines[index] = left[1] + replacement + right[2]
                lines[next_index] = ""
                next_index += 1
        body = compact_blanks("".join(lines), counts, pdf=True)
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        if output:
            output.append("\n")
        start = len("".join(output).splitlines()) + 1
        output.append(f"## PDF page {page}\n")
        output.append(body)
        end = len("".join(output).splitlines())
        new_spans.append({"page": page, "line_start": start, "line_end": end})
    cleaned = "".join(output)
    for index, span in enumerate(new_spans[:-1]):
        span["line_end"] = new_spans[index + 1]["line_start"] - 1
    new_spans[-1]["line_end"] = len(cleaned.splitlines())
    return cleaned, new_spans, counts, repairs, unresolved


def restore_examples(text: str, original: str, counts: Counter) -> str:
    missing = []
    for match in _HTML_ANCHOR.finditer(original):
        target = _Tag("<a" + match["attrs"] + ">").attrs.get("href", "")
        if example_target(target) and target not in text and target not in missing:
            missing.append(target)
    if missing:
        lines = text.splitlines(keepends=True)
        heading = next((i for i, line in enumerate(lines) if re.match(r"^# ", line)), -1)
        label = "配套示例：" + "；".join(f"[{'Colab Notebook' if 'colab.' in url else 'GitHub Notebook'}]({url})" for url in missing)
        lines.insert(heading + 1, "\n" + label + "\n")
        counts["original_notebook_links_restored"] += len(missing)
        return "".join(lines)
    return text


def clean_document(spec, text, words, compounds, *, original=None):
    if spec.get("source_type") == "pdf":
        cleaned, spans, counts, repairs, unresolved = clean_pdf(text, spec["page_spans"], words, compounds)
    else:
        base = next(iter(spec.get("source_urls", [])), None)
        cleaned, counts = clean_markdown(text, base)
        spans, repairs, unresolved = None, [], []
        if original and spec.get("parser_version", "").startswith("official-zh-structure-v2"):
            cleaned = restore_examples(cleaned, original, counts)
            cleaned = compact_blanks(cleaned, counts)
    if any(cleaned.count(block) < text.count(block) for block in protected_blocks(text)):
        raise ValueError(f"protected block changed: {spec['id']}")
    # Code spans can occur in prose as well as protected blocks.
    if inline_signatures(text, pdf=spec.get("source_type") == "pdf") != inline_signatures(cleaned, pdf=spec.get("source_type") == "pdf"):
        raise ValueError(f"inline code changed: {spec['id']}")
    return cleaned, spans, counts, repairs, unresolved


def safe_output(path: Path) -> Path:
    path = path.resolve()
    allowed = (ROOT / "output" / "knowledge-cleaning").resolve()
    if path == allowed or not path.is_relative_to(allowed) or path == KB.resolve() or path.is_relative_to(KB.resolve()):
        raise ValueError("candidate output must be a new child of output/knowledge-cleaning")
    return path


def analyze(source=None):
    source = Path(source or KB).resolve()
    check_layout(source)
    baseline = file_hashes(source)
    manifest = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    specs = manifest["documents"]
    if len(specs) != 62:
        raise ValueError("expected the current complete 62-document corpus")
    texts = {spec["id"]: (source / spec["file"]).read_bytes().decode("utf-8") for spec in specs}
    words, compounds = vocabulary(list(texts.values()))
    cleaned, reports = {}, []
    for spec in specs:
        text = texts[spec["id"]]
        raw_path = spec.get("source_snapshot", "")
        original = (source / raw_path).read_text(encoding="utf-8") if raw_path.endswith((".md", ".mdx")) else None
        value, spans, counts, repairs, unresolved = clean_document(spec, text, words, compounds, original=original)
        next_spec = {**spec, **({"page_spans": spans} if spans else {})}
        again = clean_document(next_spec, value, words, compounds, original=original)[0]
        if again != value:
            raise ValueError(f"cleaning is not idempotent: {spec['id']}")
        cleaned[spec["id"]] = (value, spans)
        reports.append({"id": spec["id"], "file": spec["file"], "changed": text != value,
                        "before_hash": sha(text.encode()), "after_hash": sha(value.encode()),
                        "before_characters": len(text), "after_characters": len(value),
                        "rules": dict(counts), "pdf_repairs": repairs, "unresolved": unresolved,
                        "protected_blocks": len(protected_blocks(text)), "protection_verified": True})
    if file_hashes(source) != baseline:
        raise ValueError("canonical source changed while analyzing")
    return manifest, baseline, cleaned, reports


def derive_manifest(manifest, cleaned, reports):
    """Shared exact projection for candidate construction and active replay."""
    candidate = deepcopy(manifest)
    by_id = {row["id"]: row for row in reports}
    for spec in candidate["documents"]:
        row = by_id[spec["id"]]
        if not row["changed"]:
            continue
        if spec.get("document_type") == "authoritative_original":
            spec["normalized_hash"] = row["after_hash"]
            spec["parser_version"] = spec.get("parser_version", "base") + "+" + PROFILE
        spans = cleaned[spec["id"]][1]
        if spans:
            spec["page_spans"] = spans
    return candidate


def build(output: Path, *, apply=False, source=None):
    if source is None and (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        from scripts.knowledge_corpus_promotion import reconstructed_base
        with reconstructed_previous(KB) as old, reconstructed_base(old) as base:
            return build(output, apply=apply, source=base)
    if source is None and (KB / "provenance/cleaning-base/manifest.json").is_file():
        from scripts.knowledge_corpus_promotion import reconstructed_base
        with reconstructed_base(KB) as base:
            return build(output, apply=apply, source=base)
    source = Path(source or KB)
    output = safe_output(output)
    if output.exists():
        raise ValueError("candidate output already exists; never overwrite it")
    manifest, baseline, cleaned, reports = analyze(source)
    summary = {"profile": PROFILE, "status": "dry_run", "documents": len(reports),
               "changed_documents": sum(row["changed"] for row in reports),
               "rules": dict(sum((Counter(row["rules"]) for row in reports), Counter())),
               "unresolved_candidates": sum(len(row["unresolved"]) for row in reports), "ingested": False}
    if not apply:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    summary["status"] = "file_candidate"
    output.mkdir(parents=True, exist_ok=False)
    candidate = output / "corpus" / manifest["knowledge_base_id"]
    write_atomic(output / "status.json", encoded({**summary, "status": "building"}))
    shutil.copytree(source, candidate)
    candidate_manifest = derive_manifest(manifest, cleaned, reports)
    report_by_id = {row["id"]: row for row in reports}
    diffs = []
    for spec in candidate_manifest["documents"]:
        value, spans = cleaned[spec["id"]]
        row = report_by_id[spec["id"]]
        if row["changed"]:
            old = (source / spec["file"]).read_text(encoding="utf-8")
            diffs.extend(difflib.unified_diff(old.splitlines(keepends=True), value.splitlines(keepends=True),
                                            fromfile=spec["file"], tofile=spec["file"] + " (candidate)"))
            write_atomic(candidate / spec["file"], value.encode("utf-8"))
    write_atomic(candidate / "metadata.json", encoded(candidate_manifest))
    updated_specs = {spec["id"]: spec for spec in candidate_manifest["documents"]}
    for batch in ("pilot", "bulk", "chinese"):
        path = candidate / f"provenance/import_batches/{batch}.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        for row in registry.get("sources", []):
            if row["id"] not in report_by_id or not report_by_id[row["id"]]["changed"]:
                continue
            spec = updated_specs[row["id"]]
            row["normalized_sha256"] = spec["normalized_hash"]
            if "parser_version" in row:
                row["parser_version"] = spec["parser_version"]
            if "page_spans" in spec:
                row["page_spans"] = spec["page_spans"]
            row["cleaning"] = {"profile": PROFILE, "base_normalized_sha256": report_by_id[row["id"]]["before_hash"]}
            if "chinese_characters" in row:
                body = cleaned[row["id"]][0]
                row["chinese_characters"] = len(re.findall(r"[\u3400-\u9fff]", body))
                row["non_whitespace_characters"] = len(re.sub(r"\s", "", body))
        if "manifest_documents" in registry:
            registry["manifest_documents"] = [deepcopy(updated_specs[spec["id"]]) for spec in registry["manifest_documents"]]
        if "asset_hashes" in registry:
            for name in registry["asset_hashes"]:
                registry["asset_hashes"][name] = sha((candidate / name).read_bytes())
        registry["candidate_cleaning_profile"] = PROFILE
        write_atomic(path, encoded(registry))
    provenance = {"profile": PROFILE, "activated": False, "canonical_asset_hashes": baseline,
                  "summary": summary, "documents": reports}
    write_atomic(candidate / "provenance/cleaning.json", encoded(provenance))
    readme = (candidate / "README.md").read_text(encoding="utf-8")
    write_atomic(candidate / "README.md", ("# 待入库清洗候选（T25）\n\n尚未入库；当前运行仍使用canonical资料。"
                 "本目录由独立清洗构建层生成，不能用固定采集器的base --check代替候选 --check。\n\n" + readme).encode())
    write_atomic(candidate / "provenance/registry.json", encoded(registry_payload(candidate)))
    write_atomic(output / "audit.json", encoded(provenance))
    write_atomic(output / "changes.diff", "".join(diffs).encode("utf-8"))
    fixture = verify(output, create_snapshot=True, source=source)
    write_atomic(output / "status.json", encoded({**summary, "status": "candidate_ready", "candidate": str(candidate),
                                                "candidate_chunks": fixture["chunks"]}))
    print(json.dumps({**summary, "status": "candidate_ready", "candidate": str(candidate)}, ensure_ascii=False, indent=2))
    return summary


def verify(output: Path, *, create_snapshot=False, source=None):
    if source is None and (KB / "provenance/evidence-base/manifest.json").is_file():
        from scripts.evidence_corpus_promotion import reconstructed_previous
        from scripts.knowledge_corpus_promotion import reconstructed_base
        with reconstructed_previous(KB) as old, reconstructed_base(old) as base:
            return verify(output, create_snapshot=create_snapshot, source=base)
    if source is None and (KB / "provenance/cleaning-base/manifest.json").is_file():
        from scripts.knowledge_corpus_promotion import reconstructed_base
        with reconstructed_base(KB) as base:
            return verify(output, create_snapshot=create_snapshot, source=base)
    source = Path(source or KB)
    output = safe_output(output)
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    if audit["profile"] != PROFILE or file_hashes(source) != audit["canonical_asset_hashes"]:
        raise ValueError("canonical input drift since candidate build")
    manifest, _, cleaned, reports = analyze(source)
    candidate = output / "corpus" / manifest["knowledge_base_id"]
    check_layout(candidate)
    baseline = audit["canonical_asset_hashes"]
    for name, expected in baseline.items():
        if "/original." in name or name.startswith("licenses/"):
            if sha((candidate / name).read_bytes()) != expected:
                raise ValueError("candidate changed an upstream snapshot/license")
    specs = json.loads((candidate / "metadata.json").read_text(encoding="utf-8"))["documents"]
    for spec in specs:
        text = (candidate / spec["file"]).read_bytes().decode("utf-8")
        if text != cleaned[spec["id"]][0]:
            raise ValueError(f"candidate body not reproducible: {spec['id']}")
    if reports != audit["documents"]:
        raise ValueError("cleaning audit is not reproducible")
    # Only the in-memory document/chunk parser is used, never an ingestion API.
    from app.core.retrieval.knowledge_base import load_documents, chunk_documents
    documents = load_documents(str(candidate))
    chunks = chunk_documents(documents)
    if len(documents) != 62 or not chunks:
        raise ValueError("candidate corpus incomplete")
    fixture = {"profile": PROFILE, "documents": len(documents), "chunks": len(chunks), "ingested": False,
               "identities": {d.metadata["document_id"]: {"document_version": d.metadata["document_version"],
                   "content_hash": d.metadata["document_content_hash"]} for d in documents}}
    fixture_path = output / "candidate-snapshot.json"
    if fixture_path.exists():
        if json.loads(fixture_path.read_text(encoding="utf-8")) != fixture:
            raise ValueError("candidate identity snapshot drift")
    elif create_snapshot:
        write_atomic(fixture_path, encoded(fixture))
    else:
        raise ValueError("candidate snapshot missing; --check never creates missing artifacts")
    print(f"Verified frozen candidate: {len(documents)} documents / {len(chunks)} chunks; no ingestion performed by this check")
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="build a new file-only candidate")
    mode.add_argument("--check", action="store_true", help="verify the existing candidate, no ingestion")
    parser.add_argument("--output", type=Path, default=ROOT / "output/knowledge-cleaning/T25")
    args = parser.parse_args()
    if args.check:
        verify(args.output)
    else:
        build(args.output, apply=args.apply)


if __name__ == "__main__":
    main()
