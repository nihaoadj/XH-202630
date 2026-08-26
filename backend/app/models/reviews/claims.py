"""P0-06 Claim/Evidence contracts and deterministic audit rules."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


CLAIM_SCHEMA_VERSION = "2.0"


class ClaimType(str, Enum):
    FACTUAL = "factual"
    NON_FACTUAL = "non_factual"
    INSTRUCTIONAL = "instructional"


class ClaimVerdict(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_IN_EVIDENCE = "not_in_evidence"
    NON_FACTUAL = "non_factual"


class ClaimJudgementStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"


class ClaimJudgeType(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HUMAN = "human"


class ClaimMetricStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NOT_APPLICABLE = "not_applicable"
    LEGACY_UNAVAILABLE = "legacy_unavailable"


class StrictClaimModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClaimCandidate(StrictClaimModel):
    claim_text: str = Field(min_length=1, max_length=4000)
    claim_type: ClaimType
    source_text: str = Field(min_length=1, max_length=4000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    knowledge_point_id: Optional[str] = Field(default=None, max_length=256)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_span(self) -> "ClaimCandidate":
        if self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("source_evidence_ids must be unique")
        return self


class ResourceClaimCandidates(StrictClaimModel):
    resource_id: str = Field(min_length=1)
    claims: list[ClaimCandidate] = Field(default_factory=list, max_length=200)


class ClaimExtractionLLMOutput(StrictClaimModel):
    resources: list[ResourceClaimCandidates] = Field(min_length=1, max_length=20)


class ClaimRecord(StrictClaimModel):
    schema_version: Literal["2.0"] = CLAIM_SCHEMA_VERSION
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    run_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1)
    claim_index: int = Field(ge=0)
    claim_text: str = Field(min_length=1, max_length=4000)
    claim_type: ClaimType
    source_text: str = Field(min_length=1, max_length=4000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    source_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_point_id: Optional[str] = Field(default=None, max_length=256)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    extraction_method: Literal["llm", "deterministic", "human"] = "llm"
    extractor_model: Optional[str] = Field(default=None, max_length=256)
    extractor_prompt_version: str = Field(min_length=1, max_length=64)
    claim_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClaimJudgementCandidate(StrictClaimModel):
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    verdict: ClaimVerdict
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_verdict_evidence(self) -> "ClaimJudgementCandidate":
        # Keep the LLM envelope permissive enough for the workflow layer to
        # apply deterministic, claim-type-aware normalization. The final
        # materializer remains fail-closed for factual claims and evidence
        # allowlists; rejecting here would turn a recoverable provider shape
        # mismatch into an avoidable whole-resource failure.
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        if not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite")
        return self


class ClaimJudgementLLMOutput(StrictClaimModel):
    judgements: list[ClaimJudgementCandidate] = Field(default_factory=list, max_length=1000)


class ClaimJudgement(StrictClaimModel):
    judgement_id: str = Field(pattern=r"^jdg_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    run_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1)
    status: ClaimJudgementStatus
    verdict: Optional[ClaimVerdict] = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str = Field(min_length=1, max_length=4000)
    judge_type: ClaimJudgeType
    judge_model: Optional[str] = Field(default=None, max_length=256)
    judge_prompt_version: str = Field(min_length=1, max_length=64)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_completed(self) -> "ClaimJudgement":
        if self.status == ClaimJudgementStatus.COMPLETED and self.verdict is None:
            raise ValueError("completed judgement requires verdict")
        if self.status != ClaimJudgementStatus.COMPLETED and self.verdict is not None:
            raise ValueError("non-completed judgement forbids verdict")
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite")
        return self


class ClaimMetricSummary(StrictClaimModel):
    metric_status: ClaimMetricStatus
    claim_hallucination_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    claim_total: int = Field(ge=0)
    factual_claim_total: int = Field(ge=0)
    supported_claim_total: int = Field(ge=0)
    contradicted_claim_total: int = Field(ge=0)
    not_in_evidence_claim_total: int = Field(ge=0)
    non_factual_claim_total: int = Field(ge=0)
    incomplete_claim_total: int = Field(ge=0)


class RunClaimsResponse(StrictClaimModel):
    run_id: str
    audit_status: ClaimMetricStatus = ClaimMetricStatus.LEGACY_UNAVAILABLE
    claims: list[ClaimRecord] = Field(default_factory=list)
    judgements: list[ClaimJudgement] = Field(default_factory=list)
    resource_metrics: dict[str, ClaimMetricSummary] = Field(default_factory=dict)


def normalize_claim_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_claim_id(
    resource_id: str,
    resource_version: int,
    claim_index: int,
    claim_text: str,
    prompt_version: str,
) -> str:
    material = "\x1f".join(
        [resource_id, str(resource_version), str(claim_index), normalize_claim_text(claim_text), prompt_version]
    )
    return f"clm_{_sha256(material)[:32]}"


def stable_judgement_id(claim_id: str, judge_prompt_version: str) -> str:
    material = "\x1f".join([claim_id, judge_prompt_version])
    return f"jdg_{_sha256(material)[:32]}"


def claim_payload_hash(candidate: ClaimCandidate) -> str:
    return _sha256(candidate.model_dump_json(exclude_none=False))


def source_text_hash(source_text: str) -> str:
    return _sha256(source_text)


def materialize_claims(
    *,
    candidates: list[ClaimCandidate],
    resource_content: str,
    resource_id: str,
    resource_version: int,
    review_id: str,
    run_id: str,
    allowed_evidence_ids: set[str],
    allowed_knowledge_point_ids: set[str],
    extractor_prompt_version: str,
    extractor_model: str | None,
) -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    for index, candidate in enumerate(candidates):
        if resource_content[candidate.source_start:candidate.source_end] != candidate.source_text:
            # Models reliably return an exact source substring more often than
            # a Python character offset (especially for Chinese punctuation
            # and Markdown). The server remains the authority for offsets:
            # accept only an exact substring and deterministically rebase it
            # to the occurrence nearest the requested position.
            positions: list[int] = []
            search_from = 0
            while True:
                position = resource_content.find(candidate.source_text, search_from)
                if position < 0:
                    break
                positions.append(position)
                search_from = position + 1
            if not positions:
                raise ValueError(f"claim source text is not an exact resource substring at index {index}")
            source_start = min(positions, key=lambda value: abs(value - candidate.source_start))
            candidate = candidate.model_copy(update={
                "source_start": source_start,
                "source_end": source_start + len(candidate.source_text),
            })
        unknown_evidence = set(candidate.source_evidence_ids) - allowed_evidence_ids
        if unknown_evidence:
            raise ValueError(f"claim references unknown evidence: {sorted(unknown_evidence)}")
        if candidate.knowledge_point_id is not None and candidate.knowledge_point_id not in allowed_knowledge_point_ids:
            raise ValueError("claim references unknown knowledge_point_id")
        records.append(
            ClaimRecord(
                claim_id=stable_claim_id(
                    resource_id,
                    resource_version,
                    index,
                    candidate.claim_text,
                    extractor_prompt_version,
                ),
                run_id=run_id,
                resource_id=resource_id,
                resource_version=resource_version,
                review_id=review_id,
                claim_index=index,
                claim_text=candidate.claim_text,
                claim_type=candidate.claim_type,
                source_text=candidate.source_text,
                source_start=candidate.source_start,
                source_end=candidate.source_end,
                source_text_hash=source_text_hash(candidate.source_text),
                knowledge_point_id=candidate.knowledge_point_id,
                source_evidence_ids=candidate.source_evidence_ids,
                extractor_model=extractor_model,
                extractor_prompt_version=extractor_prompt_version,
                claim_hash=claim_payload_hash(candidate),
            )
        )
    return records


def materialize_judgements(
    *,
    claims: list[ClaimRecord],
    candidates: list[ClaimJudgementCandidate],
    allowed_evidence_ids: set[str],
    judge_prompt_version: str,
    judge_model: str | None,
) -> list[ClaimJudgement]:
    claims_by_id = {claim.claim_id: claim for claim in claims}
    if len(claims_by_id) != len(claims):
        raise ValueError("duplicate claim_id")
    candidate_ids = [item.claim_id for item in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate judgement for claim")
    if set(candidate_ids) != set(claims_by_id):
        raise ValueError("every claim requires exactly one judgement")
    results: list[ClaimJudgement] = []
    for candidate in candidates:
        claim = claims_by_id[candidate.claim_id]
        unknown_evidence = set(candidate.evidence_ids) - allowed_evidence_ids
        if unknown_evidence:
            raise ValueError(f"judgement references unknown evidence: {sorted(unknown_evidence)}")
        if candidate.verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} and not candidate.evidence_ids:
            raise ValueError("supported/contradicted verdict requires evidence_ids")
        if candidate.verdict in {ClaimVerdict.NOT_IN_EVIDENCE, ClaimVerdict.NON_FACTUAL} and candidate.evidence_ids:
            raise ValueError("not_in_evidence/non_factual verdict forbids evidence_ids")
        if claim.claim_type == ClaimType.FACTUAL and candidate.verdict == ClaimVerdict.NON_FACTUAL:
            raise ValueError("factual claim cannot receive non_factual verdict")
        if claim.claim_type != ClaimType.FACTUAL and candidate.verdict != ClaimVerdict.NON_FACTUAL:
            raise ValueError("non-factual/instructional claim must receive non_factual verdict")
        results.append(
            ClaimJudgement(
                judgement_id=stable_judgement_id(claim.claim_id, judge_prompt_version),
                claim_id=claim.claim_id,
                run_id=claim.run_id,
                resource_id=claim.resource_id,
                resource_version=claim.resource_version,
                review_id=claim.review_id,
                status=ClaimJudgementStatus.COMPLETED,
                verdict=candidate.verdict,
                evidence_ids=candidate.evidence_ids,
                reason=candidate.reason,
                judge_type=ClaimJudgeType.LLM,
                judge_model=judge_model,
                judge_prompt_version=judge_prompt_version,
                confidence=candidate.confidence,
            )
        )
    return results


def compute_claim_metric(
    claims: Iterable[ClaimRecord],
    judgements: Iterable[ClaimJudgement],
) -> ClaimMetricSummary:
    claim_list = list(claims)
    judgement_by_claim = {
        item.claim_id: item
        for item in judgements
        if item.status == ClaimJudgementStatus.COMPLETED
    }
    factual = [item for item in claim_list if item.claim_type == ClaimType.FACTUAL]
    verdicts = [judgement_by_claim.get(item.claim_id) for item in factual]
    incomplete = sum(item is None for item in verdicts)
    supported = sum(item is not None and item.verdict == ClaimVerdict.SUPPORTED for item in verdicts)
    contradicted = sum(item is not None and item.verdict == ClaimVerdict.CONTRADICTED for item in verdicts)
    absent = sum(item is not None and item.verdict == ClaimVerdict.NOT_IN_EVIDENCE for item in verdicts)
    non_factual = len(claim_list) - len(factual)
    if incomplete:
        status = ClaimMetricStatus.INCOMPLETE
        rate = None
    elif not factual:
        status = ClaimMetricStatus.NOT_APPLICABLE
        rate = 0.0
    else:
        status = ClaimMetricStatus.COMPLETE
        rate = (contradicted + absent) / len(factual)
    return ClaimMetricSummary(
        metric_status=status,
        claim_hallucination_rate=rate,
        claim_total=len(claim_list),
        factual_claim_total=len(factual),
        supported_claim_total=supported,
        contradicted_claim_total=contradicted,
        not_in_evidence_claim_total=absent,
        non_factual_claim_total=non_factual,
        incomplete_claim_total=incomplete,
    )
