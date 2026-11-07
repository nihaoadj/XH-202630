"""Adapter protocol and pure value objects for the generic resource reviewer.

Adapters normalize one resource type into a review material, expose a whitelist
location index, validate type-specific findings and project a safe public
summary.  They must NOT call models, access databases, change budgets or publish
resources; those are engine/persistence responsibilities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.models.reviews.resource_review import (
    ResourceEvidenceRefV1,
    ResourceLocationV1,
    ResourceReviewOutputV1,
)


def text_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def comparison_text_hash(content: str) -> str:
    """Canonical CRLF/LF-normalized hash of a full text artifact."""
    return text_hash(content.replace("\r\n", "\n"))


def paragraphs(content: str) -> dict[str, str]:
    return {f"p{number:06d}": line for number, line in
            enumerate(content.replace("\r\n", "\n").split("\n"), 1)}


def paragraph_heading_paths(content: str) -> dict[str, list[str]]:
    headings: list[tuple[int, str]] = []
    fence = None
    paths: dict[str, list[str]] = {}
    for paragraph_id, paragraph in paragraphs(content).items():
        stripped = paragraph.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
        marker, separator, title = paragraph.partition(" ")
        if fence is None and separator and marker and len(marker) <= 6 and set(marker) == {"#"}:
            level = len(marker)
            headings = [(depth, value) for depth, value in headings if depth < level]
            headings.append((level, title.strip()))
        paths[paragraph_id] = [title for _, title in headings]
    return paths


@dataclass(frozen=True)
class LocationIndex:
    """Server-owned whitelist of locations a model may cite for one version."""

    paragraph_ids: frozenset[str] = frozenset()
    heading_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    paragraph_text: dict[str, str] = field(default_factory=dict)
    unit_ids: frozenset[str] = frozenset()
    unit_fields: dict[str, frozenset[str]] = field(default_factory=dict)
    root_allowed: bool = False

    def validate(self, location: ResourceLocationV1, *, path: str) -> None:
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
            ValidationError, require,
        )
        if location.kind == "paragraph":
            line = self.paragraph_text.get(location.paragraph_id or "")
            require(location.paragraph_id in self.paragraph_ids and line is not None,
                    "LOCATION_OUT_OF_BOUNDS", f"{path}.paragraph_id",
                    "location must belong to the bound content")
            require(location.quote is None or location.quote in line,
                    "LOCATION_OUT_OF_BOUNDS", f"{path}.quote",
                    "quote must belong to the bound paragraph")
            require(tuple(location.heading_path) == tuple(self.heading_paths.get(location.paragraph_id, ())),
                    "LOCATION_OUT_OF_BOUNDS", f"{path}.heading_path",
                    "heading path must match the bound content")
        elif location.kind == "structured":
            unit = location.unit_id
            require(unit in self.unit_ids, "LOCATION_OUT_OF_BOUNDS", f"{path}.unit_id",
                    "structured location must reference a server-indexed unit")
            allowed = self.unit_fields.get(unit, frozenset())
            unknown = [item for item in location.field_path if item not in allowed]
            require(not unknown, "LOCATION_OUT_OF_BOUNDS", f"{path}.field_path",
                    "field path must belong to the bound unit")
        elif location.kind == "root":
            require(self.root_allowed, "LOCATION_OUT_OF_BOUNDS", path,
                    "root location is not allowed for this resource")
        else:  # pragma: no cover - kind is a Literal
            raise ValidationError("LOCATION_OUT_OF_BOUNDS", path, "unknown location kind")


@dataclass(frozen=True)
class ResourceMaterial:
    """Typed, immutable review material assembled by one adapter."""

    resource_type: str
    text: str
    structured_payload: dict | None
    text_exact_hash: str
    structured_payload_hash: str | None
    artifact_exact_hash: str
    comparison_hash: str
    comparison_projection: dict | None
    presentation_comparison: str | None
    index: LocationIndex
    targets: tuple[str, ...]
    evidence_hashes: dict[str, str]
    difficulty: str
    rule_ids: tuple[str, ...] = ()
    # False when the public Markdown is not the deterministic renderer output of
    # the structured payload; the engine records it as a program-gate failure.
    projection_consistent: bool = True


@runtime_checkable
class ResourceReviewAdapter(Protocol):
    resource_type: str
    schema_version: str

    def build_material(self, *, resource, evidence, spec, targets: list[str]) -> ResourceMaterial: ...

    def build_location_index(self, *, resource, evidence, targets: list[str]) -> LocationIndex: ...

    def validate_findings(self, *, output: ResourceReviewOutputV1, material: ResourceMaterial, open_issues=None) -> None: ...

    def project_public_summary(self, *, decision: str, output: ResourceReviewOutputV1 | None,
                               material: ResourceMaterial) -> dict: ...


def validate_evidence_refs(refs: list[ResourceEvidenceRefV1], evidence_hashes: dict[str, str], *, path: str) -> None:
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
        ValidationError, require,
    )
    require(len({ref.evidence_id for ref in refs}) == len(refs), "EVIDENCE_REF_INVALID",
            f"{path}.evidence_refs", "duplicate evidence reference")
    require(all(evidence_hashes.get(ref.evidence_id) == ref.excerpt_hash for ref in refs),
            "EVIDENCE_REF_INVALID", f"{path}.evidence_refs",
            "evidence reference outside the frozen snapshot")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def evidence_hashes(evidence) -> dict[str, str]:
    """evidence_id -> excerpt hash over the frozen snapshot."""
    return {item.evidence_id: text_hash(item.excerpt) for item in evidence}


def combined_exact_hash(text: str, structured_payload: dict | None) -> str:
    """Exact identity of the persisted artifact: full text + full payload."""
    return canonical_hash({"text": text, "structured_payload": structured_payload})


def comparison_hash_material(projection: dict | str, presentation: str | None) -> str:
    """Combined no-change identity: comparison projection + presentation."""
    if isinstance(projection, str):
        return canonical_hash({"text": projection, "presentation": presentation})
    return canonical_hash({"projection": projection, "presentation": presentation})
