"""Minimal, repair-first admission for derived HTML practice guides.

The model is not a trusted HTML author.  This module accepts only a bounded
fragment, removes executable/browser-escape primitives, and returns a stable
fragment for the sandboxed frontend viewer.  It deliberately does not judge
teaching quality or text/HTML semantic parity in the first implementation.
"""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from typing import Iterable

from pydantic import BaseModel, Field

from app.config import get_settings


BLOCKED_WITH_CONTENT = frozenset({"script", "style", "iframe", "object", "embed", "template"})
VOID_TAGS = frozenset({"br", "hr", "input"})
ALLOWED_TAGS = frozenset({
    "a",
    "article",
    "aside",
    "b",
    "blockquote",
    "br",
    "button",
    "code",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "fieldset",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "input",
    "kbd",
    "label",
    "legend",
    "li",
    "main",
    "nav",
    "ol",
    "output",
    "p",
    "pre",
    "progress",
    "samp",
    "section",
    "small",
    "span",
    "strong",
    "summary",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
})
ALLOWED_ATTRIBUTES = frozenset({
    "alt",
    "aria-describedby",
    "aria-expanded",
    "aria-hidden",
    "aria-label",
    "aria-labelledby",
    "aria-live",
    "checked",
    "class",
    "disabled",
    "for",
    "href",
    "id",
    "lang",
    "max",
    "name",
    "open",
    "role",
    "tabindex",
    "title",
    "type",
    "value",
})


class HtmlPracticeAdmissionError(ValueError):
    """Raised only for the small set of blocking technical admission errors."""


class SanitizedHtmlPracticeGuide(BaseModel):
    html_fragment: str = Field(min_length=1)
    byte_size: int = Field(ge=1)
    validation_status: str = "passed_with_repairs"
    warnings: list[str] = Field(default_factory=list)


def _attribute_is_allowed(name: str, value: str) -> bool:
    if name.startswith("data-practice-") or name.startswith("data-source-"):
        return True
    if name not in ALLOWED_ATTRIBUTES:
        return False
    if name == "href":
        # The generated fragment cannot navigate or load any external target.
        return not value or value.startswith("#")
    return True


class _RepairingFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.blocked_depth = 0
        self.warnings: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.blocked_depth:
            if tag in BLOCKED_WITH_CONTENT:
                self.blocked_depth += 1
            return
        if tag in BLOCKED_WITH_CONTENT:
            self.blocked_depth = 1
            self.warnings.add("blocked_tag_removed")
            return
        if tag not in ALLOWED_TAGS:
            self.warnings.add("unsupported_tag_removed")
            return

        rendered_attrs: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""
            if name.startswith("on"):
                self.warnings.add("event_attribute_removed")
                continue
            if not _attribute_is_allowed(name, value):
                self.warnings.add(
                    "unsafe_url_removed" if name in {"href", "src"} else "unsupported_attribute_removed"
                )
                continue
            rendered_attrs.append(f' {name}="{escape(value, quote=True)}"')
        self.parts.append(f"<{tag}{''.join(rendered_attrs)}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.blocked_depth:
            if tag in BLOCKED_WITH_CONTENT:
                self.blocked_depth -= 1
            return
        if tag not in self.stack:
            if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
                self.warnings.add("unmatched_end_tag_removed")
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break
            self.warnings.add("unclosed_tag_repaired")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        # Comments are not required at preview time; source IDs are represented
        # by explicit data-source-* attributes in the derived fragment.
        if not self.blocked_depth:
            self.warnings.add("comment_removed")

    def repaired_fragment(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
            self.warnings.add("unclosed_tag_repaired")
        return "".join(self.parts).strip()


def sanitize_html_practice_fragment(
    fragment: str,
    *,
    max_bytes: int | None = None,
) -> SanitizedHtmlPracticeGuide:
    """Repair and admit a model-generated HTML fragment.

    Empty input, an oversized input, malformed parser input, or an empty result
    are the only blocking conditions.  Content coverage and component quality
    remain prompt-enforced, matching the first-stage product decision.
    """

    if not isinstance(fragment, str) or not fragment.strip():
        raise HtmlPracticeAdmissionError("html_fragment_empty")
    byte_limit = max_bytes or get_settings().html_practice_guide_max_bytes
    raw_size = len(fragment.encode("utf-8"))
    if raw_size > byte_limit:
        raise HtmlPracticeAdmissionError("html_fragment_too_large")

    parser = _RepairingFragmentParser()
    try:
        parser.feed(fragment)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise HtmlPracticeAdmissionError("html_fragment_unparseable") from exc
    repaired = parser.repaired_fragment()
    if not repaired:
        raise HtmlPracticeAdmissionError("html_fragment_empty_after_repair")
    repaired_size = len(repaired.encode("utf-8"))
    if repaired_size > byte_limit:
        raise HtmlPracticeAdmissionError("html_fragment_too_large_after_repair")
    warnings = sorted(parser.warnings)
    return SanitizedHtmlPracticeGuide(
        html_fragment=repaired,
        byte_size=repaired_size,
        validation_status="passed_with_repairs" if warnings else "passed",
        warnings=warnings,
    )


def has_forbidden_html_constructs(fragment: str, needles: Iterable[str] | None = None) -> bool:
    """Small defense-in-depth helper used by persistence/API tests."""

    lowered = fragment.lower()
    forbidden = needles or ("<script", "<iframe", "javascript:", " onload=", " onclick=")
    return any(item in lowered for item in forbidden)
