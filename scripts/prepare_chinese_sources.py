#!/usr/bin/env python3
"""Prepare fixed official Chinese sources; never execute notebooks or examples."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import expand_authoritative_sources as common  # noqa: E402
from scripts.knowledge_layout import (  # noqa: E402
    license_destination, reference_paths, check_layout, registry_payload, write_atomic,
)

KB = common.KB_ROOT
CATALOG = common.local_path("provenance/catalogs/chinese.json")
REGISTRY = "provenance/import_batches/chinese.json"
PARSER = "official-zh-structure-v2"
LEGACY_PARSER = "official-zh-structure-v1"
PINS = {
    "flag": ("FlagOpen/FlagEmbedding", "fd1a2bdf69488ffebe0327999d4400d8c8058a0b", "587a673933425dbc36ec61268d3b954051b2d3ef3c9b322ede357976055ffdd5"),
    "mineru": ("opendatalab/MinerU", "b7f3dd0c5f6e6d66a298239ffd02b328b873918e", "2d9aeb5d15159329a20dd804f251c64860ba954fbd26ec02f802220e6d71cf5c"),
    "milvus": ("milvus-io/web-content", "ef5f830cf84804a2cd317f3e7ca9940ba436f8c3", "1ca3cba938dffe5efeb13d44bf5482f318342f78a636eeca69779214bbae6d4c"),
    "hf": ("huggingface/cookbook", "b23df069425fe24cd9a38f8a86c5cb9e163917a0", "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def clean(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def compact_layout_blanks(text):
    """Keep one paragraph separator outside fences; code bytes are untouched."""
    result, marker, blanks, removed = [], None, 0, 0
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if marker is not None:
            result.append(line)
            if match and match[1][0] == marker[0] and len(match[1]) >= len(marker) and not match[2].strip():
                marker = None
            continue
        if match:
            marker, blanks = match[1], 0
        elif not line.strip():
            blanks += 1
            if blanks > 1:
                removed += 1
                continue
        else:
            blanks = 0
        result.append(line)
    if marker is not None:
        raise common.SourceError("unclosed code fence during layout cleaning")
    return "".join(result), removed


def fence(code, language="python"):
    longest = max((len(m[0]) for m in re.finditer(r"`+", code)), default=0)
    marker = "`" * max(3, longest + 1)
    return f"{marker}{language}\n{code.rstrip(chr(10))}\n{marker}"


def official_link(value, base):
    if not value or value.startswith("#"):
        return value
    scheme = urlsplit(value).scheme.lower()
    if scheme and scheme not in {"https", "http", "mailto"}:
        raise common.SourceError(f"unsupported source link scheme: {scheme}")
    return value if scheme else urljoin(base, value)


def markdown_links(text, base):
    """Resolve relative Markdown destinations outside fenced/inline code."""
    inline = re.compile(r"(?<!\\)(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^\s()]+)(\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?(\))")
    reference = re.compile(r"^( {0,3}\[[^\]\n]+\]:\s*)(<[^>\n]+>|\S+)(.*)$")

    def destination(value):
        angled = value.startswith("<") and value.endswith(">")
        target = value[1:-1] if angled else value
        # Notebook embedded attachments stay references to the untouched raw
        # notebook, not fetched assets or invented external URLs.
        if target.startswith("attachment:"):
            return value
        if target.startswith("data:image/"):
            # Binary diagram bytes are preserved in the original notebook, not
            # embedded as thousands of meaningless base64 tokens in retrieval.
            return "#embedded-image-see-original"
        resolved = official_link(target, base)
        return f"<{resolved}>" if angled else resolved

    def rewrite(segment):
        segment = inline.sub(lambda m: m[1] + destination(m[2]) + (m[3] or "") + m[4], segment)
        return reference.sub(lambda m: m[1] + destination(m[2]) + m[3], segment)

    output, marker = [], None
    for line in text.splitlines(keepends=True):
        match = common.FENCE_RE.match(line)
        if marker is not None:
            output.append(line)
            if match and match[1][0] == marker[0] and len(match[1]) >= len(marker) and not match[2].strip():
                marker = None
            continue
        if match:
            marker = match[1]
            output.append(line)
            continue
        parts, position = [], 0
        for code in re.finditer(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", line):
            parts.extend([rewrite(line[position:code.start()]), code[0]])
            position = code.end()
        parts.append(rewrite(line[position:]))
        output.append("".join(parts))
    return "".join(output)


class OfficialHTML(HTMLParser):
    """Small non-rendering converter for the pinned Milvus HTML documents."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    UI = {"button", "svg", "script", "style"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts = []
        self.skip = []
        self.pre = None
        self.language = "text"
        self.codes = []
        self.table = None
        self.row = None
        self.cell = None
        self.links = []
        self.lists = []
        self.table_count = 0
        self.empty_links_removed = 0
        self.blank_lines_removed = 0

    def emit(self, text):
        if self.pre is not None:
            self.pre.append(text)
        elif self.cell is not None:
            self.cell.append(text)
        else:
            self.parts.append(text)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            if tag not in self.VOID:
                self.skip.append(tag)
            return
        if tag in self.UI:
            self.skip.append(tag)
            return
        if tag == "pre":
            if self.pre is not None:
                raise common.SourceError("nested pre blocks")
            self.pre, self.language = [], "text"
        elif tag == "code" and self.pre is not None:
            match = re.search(r"(?:^|\s)language-([\w+-]+)", attrs.get("class", ""))
            self.language = match[1] if match else "text"
        elif self.pre is not None:
            if tag == "br":
                self.emit("\n")
        elif tag == "table":
            if self.table is not None:
                raise common.SourceError("nested tables are not supported")
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
        elif tag in {"ol", "ul"}:
            self.lists.append([tag, int(attrs.get("start", "1"))])
            self.emit("\n")
        elif tag == "li":
            current = self.lists[-1] if self.lists else ["ul", 1]
            number = int(attrs.get("value", str(current[1])))
            self.emit("\n" + "  " * max(0, len(self.lists) - 1) + (f"{number}. " if current[0] == "ol" else "- "))
            current[1] = number + 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "section", "details", "summary", "blockquote", "dt", "dd"}:
            self.emit("\n\n")
        elif tag == "br":
            self.emit("\n")
        elif tag == "hr":
            self.emit("\n\n---\n\n")
        elif tag == "a":
            href = official_link(attrs.get("href", ""), self.base)
            buffer = self.cell if self.cell is not None else self.parts
            self.links.append((href, buffer, len(buffer)))
            self.emit("[" if href else "")
        elif tag == "img":
            alt = attrs.get("alt", "")
            src = attrs.get("src", "")
            if alt and not any(x in src for x in ("badge", "shields.io")):
                self.emit(f"[图：{alt}]({official_link(src, self.base)})")
        elif tag == "code":
            self.emit("`")

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self.skip:
                del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag):]
            return
        if tag == "pre":
            if self.pre is None:
                raise common.SourceError("unexpected pre closing tag")
            code = "".join(self.pre)
            self.pre = None
            self.codes.append(code)
            self.emit("\n\n" + fence(code, self.language) + "\n\n")
        elif self.pre is not None:
            return
        elif tag in {"td", "th"}:
            if self.cell is None or self.row is None:
                raise common.SourceError("incomplete HTML table cell")
            self.row.append(" ".join("".join(self.cell).split()).replace("|", r"\|"))
            self.cell = None
        elif tag == "tr":
            if self.table is None or self.row is None:
                raise common.SourceError("incomplete HTML table row")
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            if not self.table or self.row is not None or self.cell is not None:
                raise common.SourceError("empty or incomplete HTML table")
            width = max(map(len, self.table))
            rows = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in self.table]
            rows.insert(1, "| " + " | ".join(["---"] * width) + " |")
            self.table = None
            self.table_count += 1
            self.emit("\n\n" + "\n".join(rows) + "\n\n")
        elif tag in {"ul", "ol"}:
            if self.lists:
                self.lists.pop()
            self.emit("\n")
        elif tag == "a":
            if not self.links:
                raise common.SourceError("unbalanced HTML link")
            href, buffer, start = self.links.pop()
            if href:
                if "".join(buffer[start + 1:]).strip():
                    self.emit(f"]({href})")
                else:
                    del buffer[start:]
                    self.empty_links_removed += 1
        elif tag == "code":
            self.emit("`")
        elif tag in {"p", "div", "section", "blockquote", "li", "summary", "details"} or re.fullmatch(r"h[1-6]", tag):
            self.emit("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.emit(data)

    def result(self):
        if self.pre is not None or self.table is not None or self.links or self.skip:
            raise common.SourceError("unclosed HTML content")
        text = "".join(self.parts)
        text, self.blank_lines_removed = compact_layout_blanks(text.strip() + "\n")
        return text


def normalize_notebook(raw):
    notebook = json.loads(raw.decode("utf-8", errors="strict"))
    if notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        raise common.SourceError("expected v4 notebook cells")
    language = notebook.get("metadata", {}).get("language_info", {}).get("name", "python")
    if not re.fullmatch(r"[\w+-]+", language):
        raise common.SourceError("invalid notebook language")
    blocks, cells, omitted_outputs = [], [], 0
    for number, cell in enumerate(notebook["cells"], 1):
        source = cell.get("source")
        if isinstance(source, list) and all(isinstance(line, str) for line in source):
            source = "".join(source)
        if not isinstance(source, str):
            raise common.SourceError("invalid notebook cell source")
        kind = cell.get("cell_type")
        if kind not in {"markdown", "code", "raw"}:
            raise common.SourceError("unknown notebook cell type")
        source = clean(source)
        block = fence(source, language if kind == "code" else "text") if kind != "markdown" else source
        blocks.append(block)
        cells.append({"cell": number, "kind": kind, "source_sha256": digest(source.encode()), "source_characters": len(source)})
        omitted_outputs += len(cell.get("outputs", []))
    return "\n\n".join(blocks), {"cells": cells, "omitted_output_count": omitted_outputs}


def normalize(item, raw, repo):
    base = f"https://github.com/{repo['repository']}/blob/{repo['commit']}/{item['upstream_path']}"
    review = {}
    if item["kind"] == "notebook":
        text, review = normalize_notebook(raw)
    else:
        text, _ = common.frontmatter(clean(raw.decode("utf-8", errors="strict")), item["id"])
        if item["kind"] == "html_markdown":
            parser = OfficialHTML(base)
            parser.feed(text)
            parser.close()
            text = parser.result()
            review = {"code_blocks": len(parser.codes), "tables": parser.table_count,
                      "empty_links_removed": parser.empty_links_removed,
                      "blank_lines_removed": parser.blank_lines_removed}
            if any(code.strip("\n") not in text for code in parser.codes if code.strip("\n")):
                raise common.SourceError("HTML conversion lost code content")
    review["embedded_image_references"] = len(re.findall(r"data:image/", text))
    text = markdown_links(clean(text), base)
    if not re.match(r"\s*#\s+", text):
        text = f"# {item['title']}\n\n{text}"
    if len(re.findall(r"[\u3400-\u9fff]", text)) < 20:
        raise common.SourceError(f"{item['id']}: no substantive Chinese text")
    mapping, warnings = common.build_section_map(text, item["default_points"])
    if warnings:
        raise common.SourceError(f"{item['id']}: {warnings}")
    # Fixed upstream base documents all relative-link format transformations.
    review["relative_link_base"] = base
    return text.encode("utf-8"), mapping, review


def source_url(repo, path):
    common.safe_relative(path, "upstream path")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", path):
        raise common.SourceError("unsupported upstream path characters")
    return f"https://raw.githubusercontent.com/{repo['repository']}/{repo['commit']}/{path}"


def read_catalog():
    raw = common.safe_file(CATALOG, required=True)
    catalog = json.loads(raw.decode("utf-8", errors="strict"))
    if catalog.get("schema_version") != 1 or set(catalog.get("repositories", {})) != set(PINS):
        raise common.SourceError("invalid fixed Chinese catalog")
    for key, repo in catalog["repositories"].items():
        if (repo.get("repository"), repo.get("commit"), repo.get("license_sha256")) != PINS[key]:
            raise common.SourceError("repository or license pin changed")
        if repo.get("notice_paths") != []:
            raise common.SourceError("unreviewed NOTICE asset")
        source_url(repo, repo["license_path"])
    sources = catalog.get("sources", [])
    if len(sources) != 35:
        raise common.SourceError("expected 35 fixed Chinese sources")
    seen, hashes = set(), set()
    for item in sources:
        ident = item.get("id", "")
        if not re.fullmatch(r"source_zh_[a-z0-9_]+", ident) or ident in seen:
            raise common.SourceError("invalid or duplicate Chinese source id")
        if not common.SHA256_RE.fullmatch(item.get("sha256", "")) or item["sha256"] in hashes:
            raise common.SourceError("invalid or duplicate content hash")
        if item.get("kind") not in {"markdown", "html_markdown", "notebook"}:
            raise common.SourceError("unsupported source kind")
        if item.get("language_origin") not in {"official_chinese", "official_translation"}:
            raise common.SourceError("unreviewed language origin")
        if not item.get("default_points") or not set(item["default_points"]) <= common.KNOWN_POINTS:
            raise common.SourceError("invalid knowledge points")
        source_url(catalog["repositories"][item["repo"]], item["upstream_path"])
        seen.add(ident)
        hashes.add(item["sha256"])
    expected_supplement = [{"id": "Apache-2.0-full-text", "reuse_repository_license": "hf", "sha256": PINS["hf"][2], "used_by": ["mineru"], "local_path": "licenses/Apache-2.0"}]
    if catalog.get("supplemental_licenses") != expected_supplement:
        raise common.SourceError("MinerU requires the fixed supplemental Apache license")
    return catalog, raw


def obtain(relative, url, expected, offline):
    data = common.safe_file(common.local_path(relative))
    if data is None:
        if offline:
            raise common.SourceError(f"missing offline asset {relative}")
        cache = common.cache_path(expected)
        data = common.safe_file(cache)
        if data is None:
            data = common.fetch_source({"id": relative, "url": url, "sha256": expected, "kind": "markdown"})
            # Verified download cache is operational evidence, not canonical KB
            # output. It survives a later source failing the all-assets preflight.
            cache.parent.mkdir(parents=True, exist_ok=True)
            with cache.open("xb") as stream:
                stream.write(data)
    if digest(data) != expected:
        raise common.SourceError(f"source SHA-256 mismatch: {relative}")
    data.decode("utf-8", errors="strict")
    return data


def refresh_derived_assets(assets, previous, receipt_dir):
    """Explicit, backed-up refresh of derived assets, never upstream snapshots."""
    check_layout(KB)
    manifest_path = common.local_path("metadata.json")
    manifest = json.loads(common.safe_file(manifest_path, required=True))
    derived = {item["normalized_path"] for item in previous["sources"]}
    before, changes = {}, {}
    for path, data in assets.items():
        existing = common.safe_file(common.local_path(path), required=True)
        if path != REGISTRY and digest(existing) != previous["asset_hashes"].get(path):
            raise common.SourceError(f"asset changed since recorded import: {path}")
        if existing != data:
            if path not in derived | {REGISTRY}:
                raise common.SourceError(f"refresh cannot alter upstream/license asset: {path}")
            before[path], changes[path] = existing, data
    replacement = {item["id"]: item for item in json.loads(assets[REGISTRY])["manifest_documents"]}
    for item in manifest["documents"]:
        if item["id"] in replacement:
            item.update(replacement[item["id"]])
    encoded_manifest = canonical(manifest)
    existing_manifest = common.safe_file(manifest_path, required=True)
    if existing_manifest != encoded_manifest:
        before["metadata.json"], changes["metadata.json"] = existing_manifest, encoded_manifest
    registry_path = "provenance/registry.json"
    before[registry_path] = common.safe_file(common.local_path(registry_path), required=True)
    if not changes:
        return {"status": "unchanged", "changed_files": []}
    receipt_dir = Path(receipt_dir).resolve()
    if receipt_dir == KB.resolve() or KB.resolve() in receipt_dir.parents:
        raise common.SourceError("backup must be outside the knowledge tree")
    receipt_dir.mkdir(parents=True, exist_ok=False)
    record = {"status": "prepared", "files": {name: digest(data) for name, data in before.items()},
              "changed_files": sorted(changes)}
    for name, data in before.items():
        write_atomic(receipt_dir / "before" / name, data)
    write_atomic(receipt_dir / "receipt.json", canonical(record))
    try:
        for name, data in changes.items():
            if common.safe_file(common.local_path(name), required=True) != before[name]:
                raise common.SourceError(f"target changed during refresh: {name}")
            write_atomic(common.local_path(name), data)
        write_atomic(common.local_path(registry_path), canonical(registry_payload(KB)))
        check_layout(KB)
    except Exception:
        for name, data in before.items():
            write_atomic(common.local_path(name), data)
        record["status"] = "rolled_back"
        write_atomic(receipt_dir / "receipt.json", canonical(record))
        raise
    record["status"] = "complete"
    write_atomic(receipt_dir / "receipt.json", canonical(record))
    print(f"Refreshed {len(changes)} derived assets; backup: {receipt_dir}", flush=True)
    return record


def prepare(*, offline=False, refresh_derived=False, receipt_dir=None):
    if refresh_derived and (not offline or receipt_dir is None):
        raise common.SourceError("derived refresh requires offline assets and an explicit backup receipt")
    catalog, catalog_raw = read_catalog()
    assets = {}
    for key, repo in catalog["repositories"].items():
        path = license_destination(f"sources/chinese/licenses/{key}/LICENSE")
        assets[path] = obtain(path, source_url(repo, repo["license_path"]), repo["license_sha256"], offline)
        if key != "flag" and key != "mineru" and b"TERMS AND CONDITIONS" not in assets[path]:
            raise common.SourceError("incomplete Apache license")
        attribution = (f"Source: {repo['repository']} @ {repo['commit']}\nLicense: {repo['license_id']}\n"
                       "Original authorship/copyright is retained in the original snapshots.\n"
                       "Derived Markdown changes format only; not an endorsement or software integration.\n")
        if key == "mineru":
            attribution += "MinerU documentation is used as a teaching source. The additional service attribution and commercial thresholds remain applicable; see LICENSE and ../Apache-2.0. MinerU software is NOT installed or integrated.\n"
        assets[license_destination(f"sources/chinese/licenses/{key}/ATTRIBUTION")] = attribution.encode()
    supplemental_license = license_destination("sources/chinese/licenses/Apache-2.0")
    assets[supplemental_license] = assets[license_destination("sources/chinese/licenses/hf/LICENSE")]
    previous_raw = common.safe_file(common.local_path(REGISTRY))
    previous = json.loads(previous_raw) if previous_raw else {}
    previous_specs = {item["id"]: item for item in previous.get("manifest_documents", [])}
    fetched_at = previous.get("fetched_at") or common.timestamp_now()
    records, specs = [], []
    for item in catalog["sources"]:
        repo = catalog["repositories"][item["repo"]]
        url = source_url(repo, item["upstream_path"])
        original, target = reference_paths(item["id"], item["kind"])
        raw = obtain(original, url, item["sha256"], offline)
        normalized, mapping, review = normalize(item, raw, repo)
        old = previous_specs.get(item["id"], {})
        changed_body = digest(normalized) != old.get("normalized_hash")
        if refresh_derived and changed_body:
            old_body = common.safe_file(common.local_path(target), required=True).decode("utf-8")
            canonical_body = lambda text: "\n".join(line.rstrip() for line in clean(text).splitlines()).strip()
            if canonical_body(old_body) == canonical_body(normalized.decode("utf-8")):
                raise common.SourceError("metadata-only change requires an explicit document identity revision")
        assets[original], assets[target] = raw, normalized
        spec = {
            "id": item["id"], "title": item["title"], "file": target,
            "version": repo["commit"], "source_version": repo["commit"],
            "source_type": "markdown", "document_type": "authoritative_original",
            "authority": repo["repository"], "knowledge_points": item["default_points"],
            "source_urls": [url], "source_snapshot": original,
            "source_hash": item["sha256"], "normalized_hash": digest(normalized),
            "parser_version": (PARSER if item["kind"] == "html_markdown" and changed_body
                               else old.get("parser_version", LEGACY_PARSER)),
            "license": license_destination(f"sources/chinese/licenses/{item['repo']}/LICENSE"),
            "chunking_strategy": "markdown_structure_v1", "section_knowledge_points": mapping,
        }
        specs.append(spec)
        records.append({**item, "url": url, "commit": repo["commit"], "original_path": original,
                        "normalized_path": target, "normalized_sha256": digest(normalized),
                        "license_path": spec["license"], "review": review,
                        "chinese_characters": len(re.findall(r"[\u3400-\u9fff]", normalized.decode())),
                        "non_whitespace_characters": len(re.sub(r"\s", "", normalized.decode()))})
    registry = {"schema_version": 1, "parser_version": PARSER, "catalog_sha256": digest(catalog_raw),
                "fetched_at": fetched_at, "sources": records, "manifest_documents": specs,
                "asset_hashes": {path: digest(data) for path, data in sorted(assets.items())}}
    assets[REGISTRY] = canonical(registry)
    if refresh_derived:
        refresh_derived_assets(assets, previous, receipt_dir)
        return registry
    # Validate every target before creating any canonical output.
    for path, data in assets.items():
        exists = common.check_target(path, data, json_semantic=(path == REGISTRY))
        if offline and not exists:
            raise common.SourceError(f"missing offline asset {path}")
    if not offline:
        for path, data in assets.items():
            common.write_if_absent(path, data, json_semantic=(path == REGISTRY))
    print(f"{'Verified' if offline else 'Prepared'} {len(records)} complete Chinese sources; "
          f"Chinese characters={sum(r['chinese_characters'] for r in records)}, "
          f"non-whitespace characters={sum(r['non_whitespace_characters'] for r in records)}", flush=True)
    return registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify all local assets offline without writes")
    parser.add_argument("--refresh-derived", action="store_true", help="explicit offline refresh with hash-checked backups")
    parser.add_argument("--receipt", type=Path, help="new backup/receipt directory outside knowledge tree")
    args = parser.parse_args()
    try:
        if args.check and args.refresh_derived:
            raise common.SourceError("--check and --refresh-derived are mutually exclusive")
        prepare(offline=args.check or args.refresh_derived,
                refresh_derived=args.refresh_derived, receipt_dir=args.receipt)
    except (common.SourceError, ValueError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
