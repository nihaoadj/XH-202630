"""T60 source adapter; T59 assets and frozen hashes remain unchanged."""
from app.core.learning_documents.correction_package import (
    CORRECTION_AUDIT_GUIDANCE, correction_audit_source, validated_correction_package,
)
from app.models.reviews.claim_extraction import content_digest, digest

VERSION = "correction-content-sources-v1"
PROMPT_VERSION = "structured-correction-v1"
GUIDANCE = CORRECTION_AUDIT_GUIDANCE + "\nsource_text必须逐字复制当前字段原文，保留条件与否定；不可跨字段拼接。"


def frozen_extension():
    return {"version": VERSION, "guidance_hash": digest(GUIDANCE)}


def build_source(resource, policy=None, *, force=False, prompt_version=None):
    from .filtered_correction_sources import (
        PROMPT_VERSION as filtered_marker, frozen_extension as filtered_extension,
        build_source as filtered_source,
    )
    extension = getattr(policy, "correction_sources", None)
    from .contextual_correction_sources import (
        PROMPT_VERSION as contextual_marker, frozen_extension as contextual_extension,
        build_source as contextual_source,
    )
    from .compact_correction_sources import (
        PROMPT_VERSION as compact_marker, frozen_extension as compact_extension,
        build_source as compact_source,
    )
    if prompt_version is not None:
        if not force or prompt_version not in {PROMPT_VERSION, filtered_marker, compact_marker, contextual_marker}:
            raise ValueError("unknown or unfrozen correction source marker")
        if prompt_version == contextual_marker:
            return contextual_source(resource)
        if prompt_version == compact_marker:
            return compact_source(resource)
        if prompt_version == filtered_marker:
            return filtered_source(resource)
    elif extension == contextual_extension():
        return contextual_source(resource)
    elif extension == compact_extension():
        return compact_source(resource)
    elif extension == filtered_extension():
        return filtered_source(resource)
    elif force and policy is None and resource.correction_package_payload.get("schema_version") == "correction-package-v2":
        return compact_source(resource)
    from .resource_sources import AuditSource
    from app.models.reviews.claims import ClaimType

    class CorrectionSource(AuditSource):
        def classify(self, candidates):
            result = []
            for candidate in candidates:
                matches = [f for f in self.fields if f["start"] <= candidate.source_start
                           and candidate.source_end <= f["end"]]
                if len(matches) != 1 or self.text[candidate.source_start:candidate.source_end] != candidate.source_text:
                    raise ValueError("correction Claim must quote exactly one field")
                if (matches[0]["role"] == "exercise_proposition"
                        and candidate.source_start == matches[0]["start"]
                        and candidate.source_end == matches[0]["end"]):
                    candidate = candidate.model_copy(update={"claim_type": ClaimType.NON_FACTUAL})
                # Mixed scenarios/questions/instructions are never exempted.
                result.append(candidate)
            return result
    if not force and extension != frozen_extension():
        raise ValueError("correction source adapter missing or drifted")
    package = validated_correction_package(resource)
    if package.schema_version != "correction-package-v1":
        raise ValueError("legacy correction source cannot read compact package")
    audit = correction_audit_source(package)
    fields = [dict(path=f.path, role=f.role, start=f.start, end=f.end) for f in audit.fields]
    snapshot = {"version": VERSION, "prompt_version": PROMPT_VERSION,
                "resource_id": resource.resource_id, "resource_version": resource.version,
                "public_content_hash": content_digest(resource.content_text or ""),
                "payload_hash": package.payload_hash, "audit_content_hash": content_digest(audit.text),
                "fields": fields, "question_bindings": {}}
    return CorrectionSource(audit.text, fields, snapshot, PROMPT_VERSION)
