"""Private neutral extraction contracts. Never expose these through HTTP/trace."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Annotated, Union

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.models.reviews.claims import ClaimRecord, ClaimType
from app.models.shared.llm import LLMCallOptions

LEGACY = "legacy_v3"
NEUTRAL = "neutral_batch_v1"
ESTIMATE = "neutral_estimate_v1"
PROMPT_VERSION = "claim-extract-neutral-v1"
PROMPT_VERSION_V2 = "claim-extract-neutral-v2"
OUTPUT_SCHEMA_VERSION_V2 = "2.0"
MAX_LEDGER_BYTES = 2 * 1024 * 1024


class OfflineClaimGateway:
    """Explicit opt-in marker for injected, credential-free test gateways."""


class OfflineClaimTransport:
    """Explicit opt-in marker for injected, credential-free test transports."""


class OfflineClaimCounter:
    """Synthetic counter implementation; changing metadata cannot make it real."""


PRIVATE_FIELDS = frozenset({"claim_extraction_policy", "claim_extraction_policy_hash",
                            "claim_extraction_refs", "claim_extraction_mode"})


def encoded(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda item: item.model_dump(mode="json") if isinstance(item, BaseModel) else item.isoformat())


def digest(value) -> str:
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def content_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class CountingProfile(PrivateModel):
    profile_id: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=256)
    tokenizer_version: str = Field(min_length=1, max_length=128)
    wire_version: str = Field(min_length=1, max_length=128)
    context_tokens: int = Field(gt=0, le=2**24)
    validated_judge_claim_capacity: int = Field(ge=1, le=64)
    calibration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_only: bool = False


class ExtractionPolicy(PrivateModel):
    schema_version: Literal["1.0"] = "1.0"
    strategy: Literal["neutral_batch_v1"] = NEUTRAL
    prompt_version: Literal["claim-extract-neutral-v1"] = PROMPT_VERSION
    segmentation_version: Literal["source-spans-v1"] = "source-spans-v1"
    profile: CountingProfile
    judge_options: LLMCallOptions
    judge_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_tokens: int = Field(default=4096, gt=0, le=8192)
    context_tokens: int = Field(default=512, gt=0, le=1024)
    batch_claims: int = Field(default=16, gt=0, le=20)
    resource_claims: int = Field(default=48, gt=0, le=64)
    output_tokens: int = Field(default=8192, gt=0, le=16384)
    max_calls: int = Field(default=8, gt=0, le=64)
    max_attempts: int = Field(default=24, gt=0, le=192)
    max_tokens: int = Field(default=196608, gt=0, le=2**24)
    attempt_timeout_seconds: float = Field(default=60, gt=0, le=60, allow_inf_nan=False)
    max_request_seconds: float = Field(default=480, gt=0, le=3600, allow_inf_nan=False)
    judge_reserve_seconds: float = Field(gt=0, allow_inf_nan=False)
    max_units: int = Field(default=128, gt=0, le=128)
    ledger_bytes: int = Field(default=MAX_LEDGER_BYTES, gt=0, le=MAX_LEDGER_BYTES)
    extractor_options: LLMCallOptions
    backoff_seconds: float = Field(ge=0, le=120, allow_inf_nan=False)

    @model_validator(mode="after")
    def limits(self):
        if self.resource_claims > self.profile.validated_judge_claim_capacity:
            raise ValueError("resource cap exceeds calibrated Judge capacity")
        if self.batch_claims > self.resource_claims:
            raise ValueError("batch cap exceeds resource cap")
        if self.extractor_options.max_attempts > self.max_attempts:
            raise ValueError("attempt budget cannot fund one extraction")
        if self.extractor_options.max_output_tokens != self.output_tokens or self.extractor_options.truncated_retry_output_tokens != self.output_tokens:
            raise ValueError("extraction output cap must stay bounded on repairs")
        if self.extractor_options.schema_repair_attempts >= self.extractor_options.max_attempts:
            raise ValueError("repair attempts exceed transport budget")
        if max(self.extractor_options.request_timeout_seconds, self.extractor_options.retry_request_timeout_seconds or 0) > self.attempt_timeout_seconds:
            raise ValueError("both extraction timeouts must respect cap")
        return self


class EstimateParameters(PrivateModel):
    version: Literal["characters-v1"] = "characters-v1"
    ascii_weight: float = Field(default=0.3, gt=0, le=16, allow_inf_nan=False)
    cjk_weight: float = Field(default=0.6, gt=0, le=16, allow_inf_nan=False)
    unicode_weight: float = Field(default=1.0, gt=0, le=16, allow_inf_nan=False)
    margin: float = Field(default=0.15, ge=0, le=1, allow_inf_nan=False)
    message_overhead: int = Field(default=8, gt=0, le=1024)
    request_overhead: int = Field(default=128, gt=0, le=65536)



class DensityBatchingPolicy(PrivateModel):
    """Frozen claim-density packing heuristic (T37).

    Private sub-contract of EstimatePolicy: it never leaves the extraction
    pipeline, so it is not exposed through HTTP/DTO/events. ``version`` pins the
    whole algorithm (risk kinds, single-unit exemption, comparison rule).
    """

    version: Literal["claim-density-v1"] = "claim-density-v1"
    enabled: bool = True
    chars_per_claim: float = Field(default=35.0, gt=0, allow_inf_nan=False)
    capacity_share: float = Field(default=0.9, gt=0, le=1, allow_inf_nan=False)


class SourceLocatingPolicy(PrivateModel):
    """Private sub-contract of EstimatePolicy (T42).

    ``None`` means the policy was frozen before programmatic source locating
    existed and must serialize byte-identically to the old contract. The mode
    pins whether B/C tolerance is active; thresholds and hard caps are frozen
    from the versioned rules asset, never read back from live environment.
    """

    version: Literal["source-locating-v1"] = "source-locating-v1"
    mode: Literal["exact_v1", "tolerant_v1"]
    prompt_version: Literal["claim-extract-neutral-v2"] = PROMPT_VERSION_V2
    extractor_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_version: Literal["2.0"] = OUTPUT_SCHEMA_VERSION_V2
    output_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator_algorithm_version: Literal["locator-v1", "locator-v2"] = "locator-v1"
    rules_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_edits: int = Field(ge=1, le=2)
    max_edit_ratio: float = Field(gt=0, le=1, allow_inf_nan=False)
    min_effective_chars: int = Field(ge=1, le=4096)
    min_score_margin: float = Field(gt=0, le=1, allow_inf_nan=False)
    max_unit_chars: int = Field(default=16000, ge=1, le=65536)
    max_candidate_chars: int = Field(default=2000, ge=1, le=2000)
    max_dp_cells_per_ref: int = Field(default=2000000, ge=1)
    max_distinct_intervals: int = Field(default=32, ge=1, le=256)
    max_work_cells_per_batch: int = Field(default=8000000, ge=1)


class EstimatePolicy(PrivateModel):
    schema_version: Literal["2.0"] = "2.0"
    strategy: Literal["neutral_estimate_v1"] = ESTIMATE
    prompt_version: Literal["claim-extract-neutral-v1", "claim-extract-neutral-v2"] = PROMPT_VERSION
    segmentation_version: Literal["source-spans-v1"] = "source-spans-v1"
    estimator_version: Literal["characters-v1"] = "characters-v1"
    estimator_parameters: EstimateParameters
    model_name: str = Field(min_length=1, max_length=256)
    endpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    thinking_mode: Literal["auto", "enabled", "disabled"]
    context_limit: int = Field(gt=0, le=2**24)
    judge_options: LLMCallOptions
    judge_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_tokens: int = Field(default=4096, gt=0, le=8192)
    context_tokens: int = Field(default=512, gt=0, le=1024)
    batch_claims: int = Field(default=16, gt=0, le=20)
    resource_claims: int = Field(default=48, gt=0, le=128)
    output_tokens: int = Field(default=32768, gt=0, le=32768)
    max_calls: int = Field(default=8, gt=0, le=64)
    max_attempts: int = Field(default=24, gt=0, le=192)
    max_tokens: int = Field(default=196608, gt=0, le=2**24)
    attempt_timeout_seconds: float = Field(default=180, gt=0, le=180, allow_inf_nan=False)
    max_request_seconds: float = Field(default=480, gt=0, le=3600, allow_inf_nan=False)
    judge_reserve_seconds: float = Field(gt=0, allow_inf_nan=False)
    max_units: int = Field(default=128, gt=0, le=128)
    ledger_bytes: int = Field(default=MAX_LEDGER_BYTES, gt=0, le=MAX_LEDGER_BYTES)
    extractor_options: LLMCallOptions
    backoff_seconds: float = Field(ge=0, le=120, allow_inf_nan=False)
    # Optional private extension (T37). ``None`` means the policy was frozen
    # before density batching existed; it must serialize byte-identically to
    # the old contract so historical policy hashes stay valid.
    density_batching: DensityBatchingPolicy | None = None
    # Optional private extension (T42). ``None`` means the policy was frozen
    # before programmatic source locating; same byte-compat contract as above.
    source_locating: SourceLocatingPolicy | None = None

    @model_serializer(mode="wrap")
    def _legacy_compatible_dump(self, handler):
        data = handler(self)
        if isinstance(data, dict):
            if self.density_batching is None:
                data.pop("density_batching", None)
            if self.source_locating is None:
                data.pop("source_locating", None)
        return data

    @model_validator(mode="after")
    def limits(self):
        if self.estimator_parameters.version != self.estimator_version:
            raise ValueError("estimator version mismatch")
        if self.source_locating is not None:
            if self.prompt_version != PROMPT_VERSION_V2:
                raise ValueError("source locating requires the neutral-v2 prompt")
            if self.source_locating.prompt_version != self.prompt_version:
                raise ValueError("source locating prompt version mismatch")
        elif self.prompt_version == PROMPT_VERSION_V2:
            raise ValueError("neutral-v2 prompt requires source locating")
        if self.batch_claims > self.resource_claims:
            raise ValueError("batch cap exceeds resource cap")
        if self.extractor_options.max_attempts > self.max_attempts:
            raise ValueError("attempt budget cannot fund one extraction")
        if self.extractor_options.max_output_tokens != self.output_tokens or self.extractor_options.truncated_retry_output_tokens != self.output_tokens:
            raise ValueError("extraction output cap must stay bounded on repairs")
        if self.extractor_options.schema_repair_attempts >= self.extractor_options.max_attempts:
            raise ValueError("repair attempts exceed transport budget")
        if max(self.extractor_options.request_timeout_seconds, self.extractor_options.retry_request_timeout_seconds or 0) > self.attempt_timeout_seconds:
            raise ValueError("both extraction timeouts must respect cap")
        return self


class Span(PrivateModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def order(self):
        if self.start >= self.end:
            raise ValueError("empty or reversed source span")
        return self


class ExtractionUnit(Span):
    unit_id: str = Field(min_length=1, max_length=80)
    kind: Literal["heading", "paragraph", "list", "table", "code", "whitespace"]
    context: list[Span] = Field(default_factory=list, max_length=16)
    required_context: list[Span] = Field(default_factory=list, max_length=2)


class ExtractionBatch(PrivateModel):
    batch_id: str = Field(min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=80)
    units: list[ExtractionUnit] = Field(min_length=1, max_length=128)
    context: list[Span] = Field(default_factory=list, max_length=32)


class NeutralCandidate(PrivateModel):
    # Intentionally preserve whitespace until exact raw span validation.
    claim_text: str = Field(min_length=1, max_length=4000)
    claim_type: ClaimType
    source_text: str = Field(min_length=1, max_length=2000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    knowledge_point_id: str | None = Field(default=None, max_length=256)


class UnitOutput(PrivateModel):
    unit_id: str = Field(min_length=1, max_length=80)
    status: Literal["claims", "non_factual", "instructional", "structure", "whitespace", "uncertain"]
    reason: str = Field(min_length=1, max_length=160)
    claims: list[NeutralCandidate] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def disposition(self):
        if (self.status == "claims") != bool(self.claims):
            raise ValueError("claims status requires candidates; empty dispositions forbid them")
        return self


class BatchOutput(PrivateModel):
    resource_id: str = Field(min_length=1, max_length=128)
    resource_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=80)
    units: list[UnitOutput] = Field(min_length=1, max_length=128)


class NeutralCandidateV2(PrivateModel):
    """Neutral-v2 candidate: the model copies verbatim but emits no offsets.

    Programmatic source locating computes the span inside the target unit and
    rewrites ``source_text`` from the frozen resource text, so no offset pair
    ever crosses the model/HTTP boundary.
    """

    claim_text: str = Field(min_length=1, max_length=4000)
    claim_type: ClaimType
    source_text: str = Field(min_length=1, max_length=2000)
    knowledge_point_id: str | None = Field(default=None, max_length=256)


class UnitOutputV2(PrivateModel):
    unit_id: str = Field(min_length=1, max_length=80)
    status: Literal["claims", "non_factual", "instructional", "structure", "whitespace", "uncertain"]
    reason: str = Field(min_length=1, max_length=160)
    claims: list[NeutralCandidateV2] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def disposition(self):
        if (self.status == "claims") != bool(self.claims):
            raise ValueError("claims status requires candidates; empty dispositions forbid them")
        return self


class BatchOutputV2(PrivateModel):
    schema_version: Literal["2.0"] = OUTPUT_SCHEMA_VERSION_V2
    resource_id: str = Field(min_length=1, max_length=128)
    resource_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=80)
    units: list[UnitOutputV2] = Field(min_length=1, max_length=128)


class LocationDiagnostic(PrivateModel):
    """Bounded private locating audit for one original output candidate.

    Keyed by batch and original unit/candidate order (never merged claim_index);
    never leaves the extraction pipeline or enters ClaimRecord/HTTP/trace.
    """

    unit_id: str = Field(min_length=1, max_length=80)
    candidate_index: int = Field(ge=0)
    ref_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    level: Literal["exact", "normalized", "approximate"]
    accepted: bool
    code: str = Field(min_length=1, max_length=80)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    edits: int = Field(default=0, ge=0)
    score: float | None = Field(default=None, ge=0, le=1)
    second_score: float | None = Field(default=None, ge=0, le=1)
    second_gap: float | None = Field(default=None, ge=0, le=1)
    edit_categories: list[str] = Field(default_factory=list, max_length=16)
    work_cells: int = Field(default=0, ge=0)


class ExtractionTicket(PrivateModel):
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=80)
    status: Literal["in_flight", "completed", "invalid", "failed"] = "in_flight"
    tokens: int = Field(ge=0)
    attempts: int = Field(ge=1, le=3)
    time_ms: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, le=60, allow_inf_nan=False)
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    usage_known: bool = False
    elapsed_known: bool = False
    attempts_known: bool = False
    charged_tokens: int | None = Field(default=None, ge=0)
    charged_attempts: int | None = Field(default=None, ge=0, le=3)
    charged_time_ms: int | None = Field(default=None, ge=0)


class ExtractionResult(PrivateModel):
    resource_id: str = Field(min_length=1, max_length=128)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_attempt: int = Field(ge=1)
    created_at: datetime
    status: Literal["running", "completed", "failed"] = "running"
    batches: list[ExtractionBatch] = Field(default_factory=list, max_length=128)
    outputs: dict[str, BatchOutput | BatchOutputV2] = Field(default_factory=dict, max_length=64)
    replaced_batches: list[str] = Field(default_factory=list, max_length=64)
    final_claims: list[ClaimRecord] = Field(default_factory=list, max_length=128)
    final_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure: str | None = Field(default=None, max_length=80)
    # Optional private locating audit (T42). ``None`` on historical results and
    # any v1 run; omitted from serialization so old hashes stay byte-identical.
    location_diagnostics: dict[str, list[LocationDiagnostic]] | None = Field(default=None, max_length=64)
    location_failures: dict[str, list[LocationDiagnostic]] | None = Field(default=None, max_length=64)

    @model_serializer(mode="wrap")
    def _legacy_compatible_dump(self, handler):
        data = handler(self)
        if self.location_diagnostics is None and isinstance(data, dict):
            data.pop("location_diagnostics", None)
        if self.location_failures is None and isinstance(data, dict):
            data.pop("location_failures", None)
        return data


class ExtractionLedger(PrivateModel):
    schema_version: Literal["1.0"] = "1.0"
    active_owner: str | None = Field(default=None, max_length=128)
    execution_session_id: str | None = Field(default=None, max_length=128)
    ledger_epoch: int = Field(default=0, ge=0)
    fence_epoch: int | None = Field(default=None, ge=0)
    owner_deadline_at: datetime | None = None
    session_closed: bool = False
    calls: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    time_ms: int = Field(default=0, ge=0)
    tickets: dict[str, ExtractionTicket] = Field(default_factory=dict, max_length=64)
    results: dict[str, ExtractionResult] = Field(default_factory=dict, max_length=128)


class AttemptTicket(PrivateModel):
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=80)
    logical_call_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_index: int = Field(ge=1, le=3)
    reserved_tokens: int = Field(gt=0)
    actual_tokens: int | None = Field(default=None, ge=0)
    usage_status: Literal["reserved", "known", "unknown", "rejected_unknown"] = "reserved"
    settled: bool = False
    status: Literal["in_flight", "completed", "failed"] = "in_flight"
    time_ms: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0, le=180, allow_inf_nan=False)
    actual_time_ms: int | None = Field(default=None, ge=0)
    response_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @property
    def tokens(self):
        return self.reserved_tokens

    @property
    def attempts(self):
        return 1

    @property
    def charged_tokens(self):
        return self.actual_tokens

    @property
    def usage_known(self):
        return self.usage_status == "known"


class LogicalExtraction(PrivateModel):
    result_key: str
    batch_id: str
    status: Literal["running", "completed", "invalid", "failed"] = "running"
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EstimateLedger(ExtractionLedger):
    schema_version: Literal["2.0"] = "2.0"
    tickets: dict[str, AttemptTicket] = Field(default_factory=dict, max_length=192)
    logical_calls: dict[str, LogicalExtraction] = Field(default_factory=dict, max_length=64)
    overrun_tokens: int = Field(default=0, ge=0)
    budget_exhausted: bool = False
    backoff_ms: int = Field(default=0, ge=0)


PolicyContract = Annotated[Union[ExtractionPolicy, EstimatePolicy], Field(discriminator="schema_version")]
LedgerContract = Annotated[Union[ExtractionLedger, EstimateLedger], Field(discriminator="schema_version")]


class LedgerSnapshot(PrivateModel):
    run_id: str
    policy: PolicyContract
    policy_hash: str
    revision: int = Field(ge=0)
    state_hash: str
    state: LedgerContract


def result_identity_key(result: ExtractionResult, policy_hash: str) -> str:
    return digest([policy_hash, result.resource_id, result.resource_version, result.review_id,
                   result.content_hash, result.evidence_hash, result.generation_attempt])


def policy_from_input(payload: dict) -> ExtractionPolicy | None:
    mode = payload.get("claim_extraction_mode", LEGACY)
    if mode == LEGACY:
        if payload.get("claim_extraction_policy") is not None or payload.get("claim_extraction_policy_hash") is not None:
            raise ValueError("legacy extraction has neutral policy")
        return None
    if mode not in {NEUTRAL, ESTIMATE} or not payload.get("include_claim_check"):
        raise ValueError("invalid extraction mode")
    cls = EstimatePolicy if mode == ESTIMATE else ExtractionPolicy
    policy = cls.model_validate(payload.get("claim_extraction_policy"))
    if digest(policy) != payload.get("claim_extraction_policy_hash"):
        raise ValueError("extraction policy hash mismatch")
    return policy


def output_matches_policy(policy: ExtractionPolicy | EstimatePolicy, output: BatchOutput | BatchOutputV2) -> bool:
    """Prove a persisted output's version matches the frozen policy.

    Explicit type check, never smart-union trial: a v2 policy must only hold
    ``BatchOutputV2`` and a v1/absent policy only ``BatchOutput``.
    """
    is_v2 = getattr(policy, "source_locating", None) is not None
    return isinstance(output, BatchOutputV2) if is_v2 else isinstance(output, BatchOutput)


def check_ledger_size(policy: ExtractionPolicy, state: ExtractionLedger) -> None:
    # The shared carrier supports estimate capacity; policy-aware checks also
    # protect historical reads and CAS updates built with unvalidated model_copy.
    capacity = min(policy.resource_claims, 64 if policy.schema_version == "1.0" else 128)
    for result_key, result in state.results.items():
        if any(not output_matches_policy(policy, out) for out in result.outputs.values()):
            raise ValueError("extraction output version does not match frozen policy")
        for batch_id, diagnostics in (result.location_diagnostics or {}).items():
            output = result.outputs.get(batch_id)
            if output is None or not isinstance(output, BatchOutputV2):
                raise ValueError("locating diagnostic lacks matching v2 output")
            units = {u.unit_id: u for u in output.units}
            for diagnostic in diagnostics:
                diagnostic = LocationDiagnostic.model_validate(diagnostic.model_dump())
                unit = units.get(diagnostic.unit_id)
                if (not diagnostic.accepted or unit is None
                        or diagnostic.candidate_index >= len(unit.claims)
                        or diagnostic.ref_hash != digest(unit.claims[diagnostic.candidate_index].source_text)):
                    raise ValueError("locating diagnostic output association mismatch")
        for call_id, diagnostics in (result.location_failures or {}).items():
            if getattr(policy, "source_locating", None) is None:
                raise ValueError("locating failure diagnostic requires v2 extraction policy")
            logical = getattr(state, "logical_calls", {}).get(call_id)
            if (logical is None or logical.result_key != result_key or logical.status != "invalid"
                    or not 0 < len(diagnostics) <= 8):
                raise ValueError("locating failure diagnostic call association mismatch")
            for diagnostic in diagnostics:
                diagnostic = LocationDiagnostic.model_validate(diagnostic.model_dump())
                if diagnostic.accepted:
                    raise ValueError("locating failure diagnostic cannot be accepted")
    if any(len(result.final_claims) > capacity for result in state.results.values()):
        raise ValueError("extraction result exceeds frozen resource capacity")
    if len(encoded(state).encode("utf-8")) + len(encoded(policy).encode("utf-8")) > policy.ledger_bytes:
        raise ValueError("extraction ledger byte budget exceeded")
    if state.calls > policy.max_calls or state.attempts > policy.max_attempts or (state.schema_version == "1.0" and (state.tokens > policy.max_tokens or state.time_ms > policy.max_request_seconds * 1000)):
        raise ValueError("extraction run budget exceeded")
    if state.schema_version == "2.0":
        exhausted = state.tokens >= policy.max_tokens or state.time_ms >= policy.max_request_seconds * 1000
        if state.overrun_tokens != max(0, state.tokens-policy.max_tokens) or state.budget_exhausted != exhausted:
            raise ValueError("extraction overrun/budget flags disagree with charges")


def validate_transition(old: ExtractionLedger, new: ExtractionLedger) -> None:
    """CAS cannot reset charges, erase unknown tickets or rewrite a final result."""
    if old.schema_version != new.schema_version:
        raise ValueError("ledger version cannot change")
    if new.schema_version == "2.0":
        validate_estimate_transition(old, new)
        return
    if not old.tickets.keys() <= new.tickets.keys() or not old.results.keys() <= new.results.keys():
        raise ValueError("extraction history cannot be deleted")
    for key, ticket in new.tickets.items():
        previous = old.tickets.get(key)
        if key != ticket.key:
            raise ValueError("ticket identity mismatch")
        if previous:
            if previous.status != "in_flight" and previous != ticket:
                raise ValueError("settled ticket is immutable")
            if previous.status == "in_flight" and ticket.status == "in_flight" and previous != ticket:
                raise ValueError("unknown in-flight ticket is immutable")
            identity = ("key", "result_key", "batch_id", "tokens", "attempts", "time_ms", "timeout_seconds")
            if any(getattr(previous, field) != getattr(ticket, field) for field in identity):
                raise ValueError("ticket reservation is immutable")
        elif ticket.status != "in_flight":
            raise ValueError("new ticket must reserve before execution")
        if ticket.status == "in_flight" and (ticket.charged_tokens is not None or ticket.charged_attempts is not None or ticket.charged_time_ms is not None):
            raise ValueError("unknown in-flight reservation cannot be released")
        if ticket.charged_tokens is not None and (not ticket.usage_known or ticket.charged_tokens > ticket.tokens):
            raise ValueError("token settlement requires reliable bounded usage")
        if ticket.charged_time_ms is not None and (not ticket.elapsed_known or ticket.charged_time_ms > ticket.time_ms):
            raise ValueError("time settlement requires reliable bounded elapsed time")
        if ticket.charged_attempts is not None and (not ticket.attempts_known or not 1 <= ticket.charged_attempts <= ticket.attempts):
            raise ValueError("attempt settlement exceeds reservation")
    totals = {
        "calls": len(new.tickets),
        "tokens": sum(t.charged_tokens if t.charged_tokens is not None else t.tokens for t in new.tickets.values()),
        "attempts": sum(t.charged_attempts if t.charged_attempts is not None else t.attempts for t in new.tickets.values()),
        "time_ms": sum(t.charged_time_ms if t.charged_time_ms is not None else t.time_ms for t in new.tickets.values()),
    }
    if any(getattr(new, key) != value for key, value in totals.items()):
        raise ValueError("ledger counters must equal ticket charges")
    for key, previous in old.results.items():
        current = new.results[key]
        identity = ("resource_id", "resource_version", "review_id", "content_hash", "evidence_hash", "generation_attempt", "created_at")
        if any(getattr(previous, field) != getattr(current, field) for field in identity):
            raise ValueError("extraction result identity is immutable")
        if previous.status != "running" and current != previous:
            raise ValueError("terminal extraction result is immutable")
        if any(previous.outputs.get(k) != current.outputs.get(k) for k in previous.outputs):
            raise ValueError("completed batch output is immutable")
    if new.session_closed and (any(t.status == "in_flight" for t in new.tickets.values()) or any(r.status == "running" for r in new.results.values())):
        raise ValueError("unknown extraction cannot close its session")


def validate_snapshot(mode: str, payload: dict, row) -> LedgerSnapshot | None:
    policy = policy_from_input(payload)
    if mode == LEGACY and policy is None and row is None:
        return None
    if mode not in {NEUTRAL, ESTIMATE} or policy is None or row is None:
        raise ValueError("extraction mode, input and ledger disagree")
    snapshot = LedgerSnapshot.model_validate(row)
    if mode != policy.strategy:
        raise ValueError("durable mode and policy strategy mismatch")
    if digest(policy) != snapshot.policy_hash or snapshot.policy != policy or digest(snapshot.state) != snapshot.state_hash:
        raise ValueError("extraction durable hash mismatch")
    if policy.schema_version != snapshot.state.schema_version:
        raise ValueError("policy and ledger version mismatch")
    check_ledger_size(policy, snapshot.state)
    validate_transition(snapshot.state, snapshot.state)
    for key, result in snapshot.state.results.items():
        if key != result_identity_key(result, snapshot.policy_hash):
            raise ValueError("extraction result key mismatch")
        for batch_id, output in result.outputs.items():
            if not output_matches_policy(policy, output):
                raise ValueError("extraction output version does not match frozen policy")
        if result.status == "completed" and (not result.final_claims or result.final_result_hash != digest(result.final_claims)):
            raise ValueError("extraction final result hash mismatch")
        if any((claim.run_id, claim.resource_id, claim.resource_version, claim.review_id, claim.extractor_prompt_version) !=
               (snapshot.run_id, result.resource_id, result.resource_version, result.review_id, policy.prompt_version)
               for claim in result.final_claims):
            raise ValueError("extraction final Claim identity mismatch")
    return snapshot


def validate_estimate_transition(old, new):
    if new.backoff_ms < old.backoff_ms:
        raise ValueError("elapsed backoff cannot be reset")
    if not old.tickets.keys() <= new.tickets.keys() or not old.results.keys() <= new.results.keys() or not old.logical_calls.keys() <= new.logical_calls.keys():
        raise ValueError("extraction history cannot be deleted")
    for key, ticket in new.tickets.items():
        expected = digest([ticket.result_key, ticket.batch_id, ticket.logical_call_id, ticket.attempt_index])
        if key != ticket.key or key != expected:
            raise ValueError("attempt identity mismatch")
        logical = new.logical_calls.get(ticket.logical_call_id)
        if logical is None or (logical.result_key, logical.batch_id) != (ticket.result_key, ticket.batch_id):
            raise ValueError("attempt logical identity mismatch")
        previous = old.tickets.get(key)
        if previous:
            if previous.settled and previous != ticket:
                raise ValueError("settled ticket is immutable")
            identity = ("key", "result_key", "batch_id", "logical_call_id", "attempt_index", "reserved_tokens", "time_ms", "timeout_seconds")
            if any(getattr(previous, name) != getattr(ticket, name) for name in identity):
                raise ValueError("attempt reservation immutable")
        elif ticket.settled or ticket.status != "in_flight":
            raise ValueError("reserve attempt before settling")
        if ticket.settled != (ticket.status != "in_flight"):
            raise ValueError("attempt settlement state mismatch")
        if ticket.status=="completed" and ticket.response_hash is None:
            raise ValueError("completed physical attempt requires response hash")
        if (ticket.actual_tokens is not None) != (ticket.usage_status == "known"):
            raise ValueError("reliable usage required")
        if not ticket.settled and (ticket.actual_tokens is not None or ticket.actual_time_ms is not None or ticket.usage_status != "reserved" or ticket.response_hash is not None):
            raise ValueError("unknown reservation cannot be released")
    for key, logical in new.logical_calls.items():
        physical=sorted((t for t in new.tickets.values() if t.logical_call_id==key),key=lambda t:t.attempt_index)
        if [t.attempt_index for t in physical]!=list(range(1,len(physical)+1)):
            raise ValueError("physical attempt indices must be consecutive")
        if logical.status=="completed":
            result=new.results.get(logical.result_key)
            output=result.outputs.get(logical.batch_id) if result is not None else None
            if (not physical or any(not t.settled for t in physical) or physical[-1].status!="completed"
                    or output is None or logical.output_hash!=digest(output)):
                raise ValueError("logical completion requires matching settled response/output")
        if key in old.logical_calls:
            prev = old.logical_calls[key]
            if (prev.result_key, prev.batch_id) != (logical.result_key, logical.batch_id) or (prev.status != "running" and prev != logical):
                raise ValueError("logical call identity/terminal state immutable")
        elif logical.status != "running":
            raise ValueError("logical call must begin before completion")
    totals = dict(calls=len(new.logical_calls), attempts=len(new.tickets),
        tokens=sum(t.actual_tokens if t.actual_tokens is not None else t.reserved_tokens for t in new.tickets.values()),
        time_ms=new.backoff_ms+sum(t.actual_time_ms if t.actual_time_ms is not None else t.time_ms for t in new.tickets.values()))
    if any(getattr(new, k) != v for k,v in totals.items()):
        raise ValueError("ledger counters must equal actual or reserved charges")
    # Apply unchanged result/terminal and close-session invariants to both versions.
    for key, prev in old.results.items():
        cur = new.results[key]
        names = ("resource_id", "resource_version", "review_id", "content_hash", "evidence_hash", "generation_attempt", "created_at")
        if any(getattr(prev, n) != getattr(cur, n) for n in names) or (prev.status != "running" and cur != prev):
            raise ValueError("extraction result identity/terminal state immutable")
        if any(cur.outputs.get(k) != value for k,value in prev.outputs.items()):
            raise ValueError("completed batch output immutable")
        for field in ("location_diagnostics", "location_failures"):
            previous = getattr(prev, field) or {}
            current = getattr(cur, field) or {}
            if any(current.get(k) != value for k, value in previous.items()):
                raise ValueError("locating diagnostic history is immutable")
    if new.session_closed and (any(not t.settled for t in new.tickets.values()) or any(r.status == "running" for r in new.results.values())):
        raise ValueError("unknown extraction cannot close its session")
