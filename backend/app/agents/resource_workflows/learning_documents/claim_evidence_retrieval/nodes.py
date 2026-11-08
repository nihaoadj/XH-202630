"""Workflow nodes for optional Claim evidence retrieval and rejudgement.

The nodes are thin orchestration over pure planners and durable repositories.
They only run for the new frozen policy; the closed branch never enters them.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.budget import LLMBudgetUnavailable
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.budget import (
    SupplementBudget,
    SupplementBudgetExceeded,
    call_with_budget,
    compute_deadline,
    estimated_input_tokens,
    utcnow,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.policy import (
    policy_from_state,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.prompts import (
    QUERY_PROMPT,
    REJUDGE_PROMPT,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.queries import (
    QueryBatch,
    build_query_batches,
    collect_claim_queries,
    validate_query_output,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.rejudge import (
    build_rejudge_batches,
    materialize_supplements,
    target_claims,
    validate_rejudge_output,
)
from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.retrieval import (
    authorized_pool_identities,
    merge_evidence_items,
    plan_retrieval_batches,
    run_retrieval_batch,
    select_new_evidence,
)
from app.agents.resource_workflows.learning_documents.state import AgentState
from app.agents.shared.evidence_scope import evidence_for_resource
from app.core.execution import current_execution_fence, current_execution_session
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.knowledge.knowledge import EvidenceItem, ScoreKind, SourceLocator
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimEvidenceRetrievalSummaryV1,
    ClaimQueryBatchOutputV1,
    ClaimReviewEvidenceSetV1,
    ClaimSupplementJudgementLLMOutput,
    ClaimSupplementJudgementV1,
    TERMINAL_STATUSES,
    build_evidence_set,
    round_one_identity,
    session_id_for,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimMetricStatus,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
    compute_claim_metric,
)
from app.models.reviews.claim_resolution import (
    ClaimResolutionConflict,
    resolve_effective_claim_judgements,
)
from app.models.shared.agent_contracts import build_trace_item, make_error_info, start_step
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash
from app.models.shared.workflow import StepStatus


NODE_RETRIEVE = "claim_evidence_retrieve"
NODE_REJUDGE = "claim_evidence_rejudge"


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _owner_epoch() -> tuple[str, int]:
    session = current_execution_session()
    owner = session.owner if session is not None else "direct-node-call"
    fence = current_execution_fence()
    return owner, max(1, int(fence.epoch or 1) if fence is not None else 1)


def _claims(state: AgentState) -> list[ClaimRecord]:
    result = []
    for item in state.get("extracted_claims", []):
        try:
            result.append(ClaimRecord.model_validate(item))
        except ValueError:
            continue
    return result


def _round0_judgements(state: AgentState) -> list[ClaimJudgement]:
    result = []
    for item in state.get("claim_judgements", []):
        try:
            result.append(ClaimJudgement.model_validate(item))
        except ValueError:
            continue
    return result


def _base_evidence_hash(evidence: Sequence[EvidenceItem]) -> str:
    return canonical_hash({
        "evidence": sorted(
            [
                {
                    "evidence_id": item.evidence_id,
                    "document_id": item.document_id,
                    "document_version": item.document_version,
                    "chunk_id": item.chunk_id,
                    "excerpt_hash": item.excerpt_hash,
                }
                for item in evidence
            ],
            key=lambda value: value["evidence_id"],
        )
    })


def _initial_judgement_hash(
    targets: Sequence[ClaimRecord], verdicts: dict[str, ClaimVerdict],
) -> str:
    return canonical_hash({
        "judgements": [
            {"claim_id": item.claim_id, "verdict": verdicts[item.claim_id].value}
            for item in sorted(targets, key=lambda value: value.claim_id)
        ]
    })


def snapshot_to_evidence(snapshot: PersistedEvidenceSnapshot) -> EvidenceItem:
    """Rebuild the audit view from the persisted snapshot (single fact source)."""

    locator = snapshot.locator
    if not isinstance(locator, SourceLocator):
        raise ValueError("supplement evidence locator invalid")
    return EvidenceItem(
        evidence_id=snapshot.evidence_id,
        knowledge_base_id=snapshot.knowledge_base_id,
        document_id=snapshot.document_id,
        document_version=snapshot.document_version,
        chunk_id=snapshot.chunk_id,
        # The snapshot deliberately stores only the query hash; the audit view
        # exposes that hash rather than inventing query text.
        query=f"sha256:{snapshot.query_hash}",
        query_hash=snapshot.query_hash,
        query_rank=snapshot.query_rank,
        rank=snapshot.rank,
        raw_score=snapshot.raw_score,
        score_kind=ScoreKind(snapshot.score_kind),
        normalized_score=snapshot.normalized_score,
        excerpt=snapshot.excerpt,
        excerpt_hash=snapshot.excerpt_hash,
        locator=locator,
        config_hash=snapshot.config_hash,
        retrieved_at=snapshot.retrieved_at,
    )


def _snapshots_for(
    evidence: Sequence[EvidenceItem], *, step_id: str, run_id: str,
) -> list[PersistedEvidenceSnapshot]:
    return [
        PersistedEvidenceSnapshot.from_evidence(
            item, run_id=run_id, retrieval_step_id=step_id,
        )
        for item in evidence
    ]


def _session_refs(
    repository, run_id: str, *, hard_blocks: set[str] | None = None,
) -> list[dict[str, Any]]:
    sessions = repository.list_sessions([run_id])
    refs = []
    for item in sessions:
        refs.append({
            "session_id": item.session_id,
            "resource_id": item.resource_id,
            "resource_version": item.resource_version,
            "status": item.status.value,
            "reason_code": item.reason_code,
            "active": item.active,
            "hard_block": item.hard_block or item.resource_id in (hard_blocks or set()),
            "target_claim_total": len(item.target_claim_ids),
            "query_count": item.query_count,
        })
    return sorted(refs, key=lambda value: (value["resource_id"], value["resource_version"]))


def _trace(
    state: AgentState,
    *,
    node_name: str,
    action: str,
    status: StepStatus,
    input_summary: str,
    output_summary: str,
    decision_reason: str,
    step_context: dict,
    resource_ids: Sequence[str],
    evidence_refs: Sequence[str] = (),
    error=None,
) -> dict[str, Any]:
    item = build_trace_item(
        state,
        agent_name=node_name,
        action=action,
        status=status,
        input_summary=input_summary,
        output_summary=output_summary,
        decision_reason=decision_reason,
        evidence_refs=list(dict.fromkeys(evidence_refs)),
        resource_ids=list(dict.fromkeys(resource_ids)),
        review_ids=list(state.get("review_result", {}).get("review_ids", {}).values()),
        error=error,
        step_context=step_context,
    )
    return item


def _targets_by_resource(
    claims: Sequence[ClaimRecord],
    judgements: Sequence[ClaimJudgement],
) -> dict[str, list[ClaimRecord]]:
    verdicts: dict[str, ClaimVerdict] = {}
    for item in judgements:
        if item.status is ClaimJudgementStatus.COMPLETED and item.claim_id not in verdicts:
            verdicts[item.claim_id] = item.verdict
    result: dict[str, list[ClaimRecord]] = {}
    for claim in claims:
        if claim.claim_type is not ClaimType.FACTUAL:
            continue
        if verdicts.get(claim.claim_id) is not ClaimVerdict.NOT_IN_EVIDENCE:
            continue
        result.setdefault(claim.resource_id, []).append(claim)
    return result


def claim_evidence_retrieve_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
    evidence_retriever,
    supplement_repository,
    claim_repository,
    audit_repository,
) -> dict[str, Any]:
    step_context = start_step(state)
    policy = policy_from_state(state)
    if policy is None:
        return {
            "current_node": NODE_RETRIEVE,
            "trace": [],
            "errors": [],
        }
    run_id = str(state.get("run_id", "direct-node-call"))
    step_id = step_context["step_id"]
    owner, epoch = _owner_epoch()
    claims = _claims(state)
    judgements = _round0_judgements(state)
    targets = _targets_by_resource(claims, judgements)
    resources = {
        item.resource_id: item for item in state.get("generated_resources", [])
    }
    workflow_deadline = state.get("workflow_deadline_at")
    ledger = supplement_repository.get_run(run_id)
    if ledger is None:
        ledger = supplement_repository.open_run(
            run_id=run_id,
            policy=policy,
            started_at=utcnow(),
            deadline_at=compute_deadline(
                first_started_at=utcnow(),
                workflow_deadline_at=workflow_deadline,
                policy=policy,
            ),
            owner=owner,
            epoch=epoch,
        )
    budget = SupplementBudget(
        repository=supplement_repository, ledger=ledger, policy=policy,
        owner=owner, epoch=epoch,
    )
    session_ids: list[str] = []
    evidence_refs: list[str] = []
    errors: list[dict[str, Any]] = []
    failed_resources: list[str] = []
    used_excerpts = 0
    query_total = 0
    for resource_id in sorted(targets):
        resource = resources.get(resource_id)
        if resource is None or not (resource.content_text or "").strip():
            continue
        resource_claims = claims
        base_evidence = evidence_for_resource(state, resource)
        target_claims = [
            item for item in targets[resource_id]
            if item.resource_version == resource.version
        ]
        if not target_claims:
            continue
        verdicts = {
            item.claim_id: item.verdict
            for item in judgements
            if item.status is ClaimJudgementStatus.COMPLETED
        }
        review_id = (
            state.get("review_result", {}).get("review_ids", {}).get(resource_id)
            or resource.review_id
        )
        if not review_id:
            failed_resources.append(resource_id)
            continue
        content_hash = _content_hash(resource.content_text or "")
        sid = session_id_for(
            run_id=run_id,
            resource_id=resource_id,
            resource_version=resource.version,
            review_id=review_id,
            content_hash=content_hash,
            policy_hash=policy.policy_hash,
        )
        session = supplement_repository.get_session(sid)
        if session is None:
            try:
                session = supplement_repository.create_session(ClaimEvidenceRetrievalSessionV1(
                    session_id=sid,
                    run_id=run_id,
                    resource_id=resource_id,
                    resource_version=resource.version,
                    review_id=review_id,
                    content_hash=content_hash,
                    policy_hash=policy.policy_hash,
                    base_evidence_set_hash=_base_evidence_hash(base_evidence),
                    initial_judgement_hash=_initial_judgement_hash(target_claims, verdicts),
                    target_claim_ids=[item.claim_id for item in target_claims],
                    status=ClaimEvidenceRetrievalStatus.PENDING,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ))
            except Exception as exc:  # noqa: BLE001 - bounded, per-resource failure
                failed_resources.append(resource_id)
                errors.append(make_error_info(
                    "CLAIM_EVIDENCE_RETRIEVAL_INVALID",
                    source=NODE_RETRIEVE, attempt=state.get("generation_attempt", 1),
                    category="claim_audit", safe_detail=str(exc)[:200],
                ).model_dump(mode="json"))
                continue
        session_ids.append(session.session_id)
        if session.status in TERMINAL_STATUSES:
            continue
        try:
            if session.status is ClaimEvidenceRetrievalStatus.PENDING:
                session = supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.PENDING,
                    status=ClaimEvidenceRetrievalStatus.QUERYING,
                )
            if session.status is not ClaimEvidenceRetrievalStatus.QUERYING:
                continue
            plan = build_query_batches(
                target_claims, session_id=session.session_id, policy=policy,
                knowledge_base_id=str(state.get("knowledge_base_id") or ""),
            )
            outputs: dict[str, dict[str, tuple[str, ...]]] = {}
            failed_claims: list[str] = []
            for batch in plan.batches:
                try:
                    supplement_repository.save_batch(ClaimEvidenceRetrievalBatchV1(
                        batch_id=batch.batch_id, session_id=session.session_id,
                        kind=ClaimEvidenceBatchKind.QUERY, ordinal=batch.ordinal,
                        input_hash=batch.input_hash, expected_claim_ids=list(batch.claim_ids),
                    ))
                    budget.begin_logical_call()
                    result, _attempt = call_with_budget(
                        gateway=llm_gateway,
                        budget=budget,
                        batch_id=batch.batch_id,
                        logical_call_id=f"{batch.batch_id}:query",
                        messages=[
                            SystemMessage(content=QUERY_PROMPT),
                            HumanMessage(content=batch.messages_payload),
                        ],
                        output_schema=ClaimQueryBatchOutputV1,
                        output_cap=policy.query_output_cap,
                        context_factory=lambda attempt_no, batch=batch: LLMCallContext(
                            run_id=run_id, step_id=step_id,
                            node_name=NODE_RETRIEVE,
                            schema_name=ClaimQueryBatchOutputV1.__name__,
                            generation_attempt=state.get("generation_attempt", 1),
                            workflow_deadline_at=budget.deadline_at,
                            call_id=f"{batch.batch_id}:{attempt_no}",
                        ),
                        estimated_input=estimated_input_tokens(
                            [
                                SystemMessage(content=QUERY_PROMPT),
                                HumanMessage(content=batch.messages_payload),
                            ],
                            ClaimQueryBatchOutputV1,
                        ),
                        max_attempts=policy.attempts_per_call,
                    )
                    supplement_repository.save_batch(ClaimEvidenceRetrievalBatchV1(
                        batch_id=batch.batch_id,
                        session_id=session.session_id,
                        kind=ClaimEvidenceBatchKind.QUERY,
                        ordinal=batch.ordinal,
                        input_hash=batch.input_hash,
                        output_hash=canonical_hash(result.output.model_dump(mode="json")),
                        status=ClaimEvidenceBatchStatus.COMPLETED,
                        payload={
                            "claim_ids": list(batch.claim_ids),
                            "query_count": sum(
                                len(item.queries) for item in result.output.items
                            ),
                        },
                        expected_claim_ids=list(batch.claim_ids),
                        updated_at=utcnow(),
                    ))
                    outputs[batch.batch_id] = validate_query_output(
                        result.output, batch=batch, policy=policy,
                    )
                except LLMBudgetUnavailable:
                    # The enclosing production/round scope refused further
                    # sends.  The local reservation is already settled as not
                    # sent; stop issuing query calls and use the deterministic
                    # fallback for this and every remaining batch.
                    failed_claims.extend(batch.claim_ids)
                    failed_claims.extend(
                        claim_id for pending in plan.batches[plan.batches.index(batch) + 1:]
                        for claim_id in pending.claim_ids
                    )
                    break
                except (LLMGatewayError, SupplementBudgetExceeded, ValueError):
                    failed_claims.extend(batch.claim_ids)
            selected, exhausted, counts = collect_claim_queries(
                batches=plan.batches,
                outputs=outputs,
                fallback_claim_ids=list(dict.fromkeys(failed_claims)),
                claims=target_claims,
                policy=policy,
            )
            query_total += counts["selected"]
            if counts["selected"]:
                ledger = supplement_repository.record_query_count(
                    run_id=run_id, count=counts["selected"],
                )
                budget.ledger = ledger
            if not selected:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.QUERYING,
                    status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                    reason_code="no_query",
                    query_count=0,
                )
                continue
            session = supplement_repository.update_session(
                session.session_id,
                expected_status=ClaimEvidenceRetrievalStatus.QUERYING,
                status=ClaimEvidenceRetrievalStatus.RETRIEVING,
                query_count=counts["selected"],
            )
            retrieval_plans = plan_retrieval_batches(
                selected, session_id=session.session_id, policy=policy,
            )
            claim_ids_by_query: dict[str, tuple[str, ...]] = {}
            for item in retrieval_plans:
                claim_ids_by_query.update(item.claim_ids_by_query)
            base_pool = authorized_pool_identities(base_evidence)
            batches = []
            saved_evidence: list[EvidenceItem] = []
            for item in retrieval_plans:
                supplement_repository.save_batch(ClaimEvidenceRetrievalBatchV1(
                    batch_id=item.batch_id,
                    session_id=session.session_id,
                    kind=ClaimEvidenceBatchKind.RETRIEVE,
                    ordinal=item.ordinal,
                    input_hash=item.input_hash,
                    status=ClaimEvidenceBatchStatus.PLANNED,
                    payload={"queries": len(item.queries)},
                    expected_claim_ids=list(session.target_claim_ids),
                    updated_at=utcnow(),
                ))
                batch = run_retrieval_batch(
                    evidence_retriever,
                    run_id=run_id,
                    step_id=step_id,
                    knowledge_base_id=str(state.get("knowledge_base_id") or ""),
                    plan=item,
                    policy=policy,
                )
                batches.append(batch)
                selection = select_new_evidence(
                    batches,
                    claim_ids_by_query=claim_ids_by_query,
                    base_pool=base_pool,
                    claim_order=session.target_claim_ids,
                    per_resource_cap=policy.max_new_excerpts_per_resource,
                    remaining_total=max(0, policy.max_new_excerpts - used_excerpts),
                )
                snapshots = _snapshots_for(
                    selection.selected, step_id=step_id, run_id=run_id,
                )
                supplement_repository.complete_retrieval_batch(
                    batch_id=item.batch_id,
                    run_id=run_id,
                    step_id=step_id,
                    owner=owner,
                    epoch=epoch,
                    output_hash=canonical_hash({
                        "evidence_ids": [ev.evidence_id for ev in selection.selected],
                        "status": batch.status.value,
                    }),
                    payload={
                        "query_hashes": batch.query_hashes,
                        "candidate_count": batch.candidate_count,
                        "new_identity_total": selection.new_identity_total,
                        "selected_count": len(selection.selected),
                        "dropped_by_cap": selection.dropped_by_cap_total,
                        "candidates": list(selection.candidates)[:40],
                    },
                    evidence=snapshots,
                    now=utcnow(),
                )
                if selection.selected:
                    saved_evidence.extend(selection.selected)
                    evidence_refs.extend(ev.evidence_id for ev in selection.selected)
                    used_excerpts += len(selection.selected)
            if not saved_evidence:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.RETRIEVING,
                    status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                    reason_code="no_new_evidence",
                )
            else:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.RETRIEVING,
                    status=ClaimEvidenceRetrievalStatus.REJUDGING,
                    evidence_scope_ids=[
                        ev.evidence_id for ev in saved_evidence
                    ],
                )
        except SupplementBudgetExceeded as exc:
            supplement_repository.update_session(
                session.session_id,
                expected_status=session.status,
                status=ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
                reason_code="budget_exhausted",
            )
            failed_resources.append(resource_id)
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_RETRIEVAL_BUDGET_EXHAUSTED",
                source=NODE_RETRIEVE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - optional feature must not crash the run
            current = supplement_repository.get_session(session.session_id)
            if current is not None and current.status not in TERMINAL_STATUSES:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=current.status,
                    status=ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                    reason_code="retrieval_failed",
                )
            failed_resources.append(resource_id)
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_RETRIEVAL_UNAVAILABLE",
                source=NODE_RETRIEVE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
    refs = _session_refs(supplement_repository, run_id)
    status = StepStatus.DEGRADED if failed_resources else StepStatus.SUCCESS
    trace = _trace(
        state,
        node_name=NODE_RETRIEVE,
        action="Claim 缺证补检",
        status=status,
        input_summary=f"缺证事实 Claim 资源 {len(targets)} 个；会话 {len(session_ids)} 个",
        output_summary=(
            f"查询 {query_total} 条；新增摘录 {used_excerpts} 个；失败资源 {len(failed_resources)} 个"
        ),
        decision_reason="仅对首次 not_in_evidence 的事实 Claim 复用知识库检索；正文与首次判定不变。",
        step_context=step_context,
        resource_ids=sorted(targets),
        evidence_refs=evidence_refs,
        error=(make_error_info(
            "CLAIM_EVIDENCE_RETRIEVAL_UNAVAILABLE",
            source=NODE_RETRIEVE, attempt=state.get("generation_attempt", 1),
            category="claim_audit", safe_detail="supplement retrieval degraded",
        ) if failed_resources else None),
    )
    return {
        "claim_evidence_retrieval_refs": refs,
        "claim_evidence_new_evidence_ids": list(dict.fromkeys(evidence_refs)),
        "claim_evidence_hard_block_resource_ids": [],
        "current_node": NODE_RETRIEVE,
        "trace": [trace],
        "errors": errors,
    }


def _scope_for(
    *,
    session: ClaimEvidenceRetrievalSessionV1,
    base_evidence: Sequence[EvidenceItem],
    added: Sequence[EvidenceItem],
    purpose: str,
    parent_scope_id: str | None = None,
) -> ClaimReviewEvidenceSetV1:
    ordered = [*base_evidence, *added]
    manifest = [
        {
            "evidence_id": item.evidence_id,
            "document_id": item.document_id,
            "document_version": item.document_version,
            "chunk_id": item.chunk_id,
            "excerpt_hash": item.excerpt_hash,
            "order": index,
        }
        for index, item in enumerate(ordered)
    ]
    return build_evidence_set(
        run_id=session.run_id,
        resource_id=session.resource_id,
        resource_version=session.resource_version,
        review_id=session.review_id,
        purpose=purpose,
        session_id=session.session_id,
        base_evidence_ids=[item.evidence_id for item in base_evidence],
        added_evidence_ids=[item.evidence_id for item in added],
        snapshot_hashes={
            item.evidence_id: hashlib.sha256(
                canonical_json_bytes(item.model_dump(mode="json"))
            ).hexdigest()
            for item in ordered
        },
        manifest=manifest,
        parent_scope_id=parent_scope_id,
    )


def canonical_json_bytes(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _effective_state(
    *,
    state: AgentState,
    claims: Sequence[ClaimRecord],
    round0: Sequence[ClaimJudgement],
    sessions: Sequence[ClaimEvidenceRetrievalSessionV1],
    supplements: Sequence[ClaimSupplementJudgementV1],
) -> tuple[list[ClaimJudgement], dict[str, Any], list[str]]:
    resolution = resolve_effective_claim_judgements(round0, sessions, supplements)
    effective = resolution.ordered()
    metrics: dict[str, dict[str, Any]] = {}
    by_resource: dict[str, list[ClaimRecord]] = {}
    for claim in claims:
        by_resource.setdefault(claim.resource_id, []).append(claim)
    for resource_id, resource_claims in by_resource.items():
        summary = compute_claim_metric(resource_claims, effective)
        metrics[resource_id] = summary.model_dump(mode="json")
    hard_blocks = sorted({
        item.resource_id for item in sessions if item.hard_block
    })
    return effective, metrics, hard_blocks


def _record_generation_scope(
    *,
    repository,
    session: ClaimEvidenceRetrievalSessionV1,
    base_evidence: Sequence[EvidenceItem],
    added: Sequence[EvidenceItem],
    parent_scope_id: str,
    scope_state: dict[str, list[dict[str, Any]]],
    supplement_pool: list[EvidenceItem],
) -> None:
    """Persist the child generation grant for the version being revised.

    The scope is bound to this version and inherited through verified lineage.
    The same helper serves an activated round and a hard-blocked round, because
    both continue into the existing targeted revision.
    """

    if not added:
        return
    generation_scope = _scope_for(
        session=session, base_evidence=base_evidence, added=added,
        purpose="generation", parent_scope_id=parent_scope_id,
    )
    repository.save_evidence_set(generation_scope)
    scope_state.setdefault(session.resource_id, []).append(generation_scope.model_dump(mode="json"))
    known = {item.evidence_id for item in supplement_pool}
    supplement_pool.extend(item for item in added if item.evidence_id not in known)


def claim_evidence_rejudge_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
    supplement_repository,
    claim_repository,
    audit_repository,
) -> dict[str, Any]:
    step_context = start_step(state)
    policy = policy_from_state(state)
    if policy is None:
        return {"current_node": NODE_REJUDGE, "trace": [], "errors": []}
    run_id = str(state.get("run_id", "direct-node-call"))
    step_id = step_context["step_id"]
    owner, epoch = _owner_epoch()
    claims = _claims(state)
    round0 = _round0_judgements(state)
    verdicts: dict[str, ClaimVerdict] = {}
    for item in round0:
        if item.status is ClaimJudgementStatus.COMPLETED and item.claim_id not in verdicts:
            verdicts[item.claim_id] = item.verdict
    sessions = [
        item for item in supplement_repository.list_sessions([run_id])
        if item.status is ClaimEvidenceRetrievalStatus.REJUDGING
    ]
    ledger = supplement_repository.get_run(run_id)
    if ledger is None:
        raise ValueError("supplement ledger missing for rejudgement")
    budget = SupplementBudget(
        repository=supplement_repository, ledger=ledger, policy=policy,
        owner=owner, epoch=epoch,
    )
    resources = {item.resource_id: item for item in state.get("generated_resources", [])}
    errors: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    activated: list[str] = []
    supplement_pool: list[EvidenceItem] = list(state.get("supplement_retrieved_evidence") or [])
    scope_state: dict[str, list[dict[str, Any]]] = {
        ident: list(items) for ident, items in (state.get("claim_evidence_scopes") or {}).items()
    }
    for session in sessions:
        resource = resources.get(session.resource_id)
        if resource is None or resource.version != session.resource_version:
            continue
        base_evidence = evidence_for_resource(state, resource)
        base_ids = {item.evidence_id for item in base_evidence}
        snapshots = {
            item.evidence_id: item
            for item in audit_repository.list_evidence(run_id)
        }
        added = [
            snapshot_to_evidence(snapshots[evidence_id])
            for evidence_id in session.evidence_scope_ids
            if evidence_id in snapshots and evidence_id not in base_ids
        ]
        if not added:
            supplement_repository.update_session(
                session.session_id,
                expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
                status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                reason_code="evidence_snapshot_missing",
            )
            continue
        authorized = merge_evidence_items(base_evidence, added)
        scope = _scope_for(
            session=session, base_evidence=base_evidence, added=added, purpose="audit",
        )
        supplement_repository.save_evidence_set(scope)
        targets = target_claims(
            [item for item in claims if item.resource_id == session.resource_id],
            effective_verdicts=verdicts,
        )
        batches, oversize = build_rejudge_batches(
            targets,
            evidence=authorized,
            session_id=session.session_id,
            policy=policy,
        )
        if oversize:
            supplement_repository.update_session(
                session.session_id,
                expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
                status=ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                reason_code="evidence_context_oversize",
                evidence_scope_ids=[ev.evidence_id for ev in added],
            )
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_CONTEXT_OVERSIZE",
                source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail="claim/evidence pool exceeds the frozen cap",
            ).model_dump(mode="json"))
            continue
        allowed_ids = {item.evidence_id for item in authorized}
        claim_index = {item.claim_id: item for item in targets}
        hard_block_reason: str | None = None
        completed = 0
        failed = False
        budget_rejected = False
        try:
            for batch in batches:
                supplement_repository.save_batch(ClaimEvidenceRetrievalBatchV1(
                    batch_id=batch.batch_id,
                    session_id=session.session_id,
                    kind=ClaimEvidenceBatchKind.REJUDGE,
                    ordinal=batch.ordinal,
                    input_hash=batch.input_hash,
                    status=ClaimEvidenceBatchStatus.PLANNED,
                    expected_claim_ids=list(batch.claim_ids),
                    payload={"round": 1, "claim_ids": list(batch.claim_ids)},
                    updated_at=utcnow(),
                ))
                budget.begin_logical_call()
                result, _attempt_no = call_with_budget(
                    gateway=llm_gateway,
                    budget=budget,
                    batch_id=batch.batch_id,
                    logical_call_id=f"{batch.batch_id}:rejudge",
                    messages=[
                        SystemMessage(content=REJUDGE_PROMPT),
                        HumanMessage(content=batch.messages_payload),
                    ],
                    output_schema=ClaimSupplementJudgementLLMOutput,
                    output_cap=policy.rejudge_output_cap,
                    truncated_output_cap=policy.rejudge_truncated_output_cap,
                    context_factory=lambda attempt_no, batch=batch: LLMCallContext(
                        run_id=run_id, step_id=step_id,
                        node_name=NODE_REJUDGE,
                        schema_name=ClaimSupplementJudgementLLMOutput.__name__,
                        generation_attempt=state.get("generation_attempt", 1),
                        workflow_deadline_at=budget.deadline_at,
                        call_id=f"{batch.batch_id}:{attempt_no}",
                    ),
                    estimated_input=estimated_input_tokens(
                        [
                            SystemMessage(content=REJUDGE_PROMPT),
                            HumanMessage(content=batch.messages_payload),
                        ],
                        ClaimSupplementJudgementLLMOutput,
                    ),
                    max_attempts=policy.attempts_per_call,
                )
                candidates, batch_block = validate_rejudge_output(
                    result.output, batch=batch, claims=claim_index,
                    allowed_evidence_ids=allowed_ids,
                )
                hard_block_reason = hard_block_reason or batch_block
                supplements = materialize_supplements(
                    session=session,
                    batch=batch,
                    candidates=candidates,
                    claims=claim_index,
                    allowed_evidence_ids=allowed_ids,
                    scope_id=scope.scope_id,
                    scope_hash=scope.manifest_hash,
                    prompt_version=policy.rejudge_prompt_version,
                    prompt_hash=policy.rejudge_prompt_hash,
                    model_name=getattr(result, "model_name", None),
                )
                supplement_repository.save_rejudge_batch(
                    batch_id=batch.batch_id,
                    output_hash=canonical_hash(result.output.model_dump(mode="json")),
                    payload={
                        "claim_ids": list(batch.claim_ids),
                        "verdicts": {
                            item["claim_id"]: item["verdict"] for item in candidates
                        },
                        "hard_block": batch_block,
                    },
                    supplements=supplements,
                    hard_block_reason=batch_block,
                    now=utcnow(),
                )
                evidence_refs.extend(
                    evidence_id for item in supplements for evidence_id in item.evidence_ids
                )
                completed += 1
        except LLMBudgetUnavailable as exc:
            # Every local reservation before this point was settled as not sent
            # by the observer; the session cannot obtain further provider
            # capacity from the enclosing production budget.
            failed = True
            budget_rejected = True
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_BUDGET_EXHAUSTED",
                source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - bounded per-session failure
            failed = True
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_REJUDGE_UNAVAILABLE",
                source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
        current = supplement_repository.get_session(session.session_id)
        if current is None:
            continue
        if current.hard_block or hard_block_reason is not None:
            if current.status is ClaimEvidenceRetrievalStatus.REJUDGING:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
                    status=ClaimEvidenceRetrievalStatus.BLOCKED,
                    reason_code=hard_block_reason or current.hard_block_reason or "hard_block",
                    hard_block_reason=hard_block_reason,
                    evidence_scope_ids=[ev.evidence_id for ev in added],
                )
            # The version is permanently blocked, but the targeted revision must
            # still be able to cite the new counter-evidence it was asked to fix.
            _record_generation_scope(
                repository=supplement_repository,
                session=current,
                base_evidence=base_evidence,
                added=added,
                parent_scope_id=scope.scope_id,
                scope_state=scope_state,
                supplement_pool=supplement_pool,
            )
            continue
        if failed or completed != len(batches):
            if current.status is ClaimEvidenceRetrievalStatus.REJUDGING:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
                    status=(ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED if budget_rejected
                            else ClaimEvidenceRetrievalStatus.UNAVAILABLE),
                    reason_code=("upper_budget_rejected" if budget_rejected
                                 else "rejudge_incomplete"),
                    evidence_scope_ids=[ev.evidence_id for ev in added],
                )
            continue
        supplements = [
            item for item in supplement_repository.list_supplements([run_id])
            if item.session_id == session.session_id
        ]
        resource_claims = [
            item for item in claims if item.resource_id == session.resource_id
        ]
        try:
            # Resolve the round-1 view that is about to become effective.  The
            # stored session is still ``rejudging``, so resolving with it would
            # return the first-round metric; the activation summary must instead
            # describe the merged set it activates.
            prospective = current.model_copy(update={
                "status": ClaimEvidenceRetrievalStatus.COMPLETED,
                "active": True,
                "completed_at": utcnow(),
            })
            resolution = resolve_effective_claim_judgements(
                round0, [prospective], supplements,
            )
            summary = compute_claim_metric(
                resource_claims, resolution.judgements.values(),
            )
        except ClaimResolutionConflict as exc:
            if current.status is ClaimEvidenceRetrievalStatus.REJUDGING:
                supplement_repository.update_session(
                    session.session_id,
                    expected_status=ClaimEvidenceRetrievalStatus.REJUDGING,
                    status=ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                    reason_code="round_one_incomplete",
                    evidence_scope_ids=[ev.evidence_id for ev in added],
                )
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_ACTIVATION_FAILED",
                source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
            continue
        try:
            supplement_repository.activate_session(
                session_id=session.session_id,
                scope=scope,
                round_one_hash=round_one_identity(supplements),
                supported=summary.supported_claim_total,
                contradicted=summary.contradicted_claim_total,
                absent=summary.not_in_evidence_claim_total,
                factual=summary.factual_claim_total,
                claim_total=summary.claim_total,
                now=utcnow(),
            )
            activated.append(session.session_id)
            supplement_pool.extend(added)
            scope_state.setdefault(session.resource_id, []).append(scope.model_dump(mode="json"))
            remaining = [
                item for item in supplements
                if item.verdict in {ClaimVerdict.CONTRADICTED, ClaimVerdict.NOT_IN_EVIDENCE}
                or item.evidence_conflict
            ]
            if remaining:
                _record_generation_scope(
                    repository=supplement_repository,
                    session=current,
                    base_evidence=base_evidence,
                    added=added,
                    parent_scope_id=scope.scope_id,
                    scope_state=scope_state,
                    supplement_pool=supplement_pool,
                )
        except Exception as exc:  # noqa: BLE001 - bounded per-session activation failure
            errors.append(make_error_info(
                "CLAIM_EVIDENCE_ACTIVATION_FAILED",
                source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
                category="claim_audit", safe_detail=str(exc)[:200],
            ).model_dump(mode="json"))
    sessions = supplement_repository.list_sessions([run_id])
    supplements = supplement_repository.list_supplements([run_id])
    try:
        effective, metrics, hard_blocks = _effective_state(
            state=state, claims=claims, round0=round0,
            sessions=sessions, supplements=supplements,
        )
        resolution_error = None
    except ClaimResolutionConflict as exc:
        effective, metrics, hard_blocks = list(round0), dict(state.get("claim_metrics", {})), []
        resolution_error = str(exc)
        errors.append(make_error_info(
            "CLAIM_EVIDENCE_RESOLUTION_CONFLICT",
            source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
            category="claim_audit", safe_detail=resolution_error[:200],
        ).model_dump(mode="json"))
    refs = _session_refs(supplement_repository, run_id)
    trace = _trace(
        state,
        node_name=NODE_REJUDGE,
        action="补证后 Claim 重判",
        status=StepStatus.DEGRADED if errors else StepStatus.SUCCESS,
        input_summary=f"待重判会话 {len(sessions)} 个；目标事实 Claim {len(claims)} 条",
        output_summary=(
            f"激活会话 {len(activated)} 个；硬阻断资源 {len(hard_blocks)} 个"
            + (f"；错误 {len(errors)} 个" if errors else "")
        ),
        decision_reason=(
            "仅重判首次 not_in_evidence 的事实 Claim；全部批次成功后才原子激活。"
        ),
        step_context=step_context,
        resource_ids=[item.resource_id for item in sessions],
        evidence_refs=evidence_refs,
        error=(make_error_info(
            "CLAIM_EVIDENCE_REJUDGE_UNAVAILABLE",
            source=NODE_REJUDGE, attempt=state.get("generation_attempt", 1),
            category="claim_audit", safe_detail="supplement rejudge degraded",
        ) if errors else None),
    )
    return {
        "claim_judgements": [item.model_dump(mode="json") for item in effective],
        "claim_metrics": metrics,
        "claim_evidence_retrieval_refs": refs,
        "claim_evidence_hard_block_resource_ids": hard_blocks,
        "supplement_retrieved_evidence": merge_evidence_items([], supplement_pool),
        "claim_evidence_scopes": scope_state,
        "current_node": NODE_REJUDGE,
        "trace": [trace],
        "errors": errors,
    }


def claim_evidence_summary(
    *,
    run_id: str,
    claims: Sequence[ClaimRecord],
    round0: Sequence[ClaimJudgement],
    sessions: Sequence[ClaimEvidenceRetrievalSessionV1],
    supplements: Sequence[ClaimSupplementJudgementV1],
    requested: bool,
    resource_id: str | None = None,
) -> ClaimEvidenceRetrievalSummaryV1:
    """Read-only projection shared by the service and the report snapshot."""

    scoped_sessions = [
        item for item in sessions
        if resource_id is None or item.resource_id == resource_id
    ]
    scoped_claims = [
        item for item in claims
        if resource_id is None or item.resource_id == resource_id
    ]
    try:
        resolution = resolve_effective_claim_judgements(round0, sessions, supplements)
        effective = resolution.judgements
    except ClaimResolutionConflict:
        effective = {
            item.claim_id: item for item in round0
            if item.status is ClaimJudgementStatus.COMPLETED
        }
    initial_counts = {"supported": 0, "contradicted": 0, "not_in_evidence": 0}
    for item in round0:
        if item.status is not ClaimJudgementStatus.COMPLETED:
            continue
        if resource_id is not None and item.resource_id != resource_id:
            continue
        if item.verdict is ClaimVerdict.SUPPORTED:
            initial_counts["supported"] += 1
        elif item.verdict is ClaimVerdict.CONTRADICTED:
            initial_counts["contradicted"] += 1
        elif item.verdict is ClaimVerdict.NOT_IN_EVIDENCE:
            initial_counts["not_in_evidence"] += 1
    effective_counts = {"supported": 0, "contradicted": 0, "not_in_evidence": 0}
    factual = 0
    for claim in scoped_claims:
        if claim.claim_type is not ClaimType.FACTUAL:
            continue
        factual += 1
        verdict = effective.get(claim.claim_id)
        if verdict is None:
            continue
        if verdict.verdict is ClaimVerdict.SUPPORTED:
            effective_counts["supported"] += 1
        elif verdict.verdict is ClaimVerdict.CONTRADICTED:
            effective_counts["contradicted"] += 1
        elif verdict.verdict is ClaimVerdict.NOT_IN_EVIDENCE:
            effective_counts["not_in_evidence"] += 1
    status = ClaimEvidenceRetrievalStatus.NOT_REQUESTED
    reason: str | None = None
    if requested:
        status = ClaimEvidenceRetrievalStatus.NOT_APPLICABLE
        if scoped_sessions:
            latest = scoped_sessions[-1]
            status = latest.status
            reason = latest.reason_code
    session_summaries = []
    for item in scoped_sessions:
        session_summaries.append({
            "session_id": item.session_id,
            "resource_version": item.resource_version,
            "status": item.status,
            "reason_code": item.reason_code,
            "active": item.active,
            "hard_block": item.hard_block,
            "target_claim_total": len(item.target_claim_ids),
            "attempted_claim_total": len([
                value for value in supplements
                if value.session_id == item.session_id
            ]),
            "remaining_claim_total": max(
                0, len(item.target_claim_ids) - len([
                    value for value in supplements
                    if value.session_id == item.session_id
                ]),
            ),
            "query_total": item.query_count,
            "evidence_scope_ids": list(item.evidence_scope_ids),
        })
    target_total = sum(len(item.target_claim_ids) for item in scoped_sessions)
    attempted_total = sum(len([
        value for value in supplements if value.session_id == item.session_id
    ]) for item in scoped_sessions)
    return ClaimEvidenceRetrievalSummaryV1(
        run_id=run_id,
        requested=requested,
        status=status,
        reason_code=reason,
        resource_id=resource_id,
        resource_version=(
            scoped_sessions[-1].resource_version if scoped_sessions else None
        ),
        review_id=(scoped_sessions[-1].review_id if scoped_sessions else None),
        target_claim_total=target_total,
        attempted_claim_total=attempted_total,
        remaining_claim_total=max(0, target_total - attempted_total),
        query_total=sum(item.query_count for item in scoped_sessions),
        initial_supported_total=initial_counts["supported"],
        initial_contradicted_total=initial_counts["contradicted"],
        initial_not_in_evidence_total=initial_counts["not_in_evidence"],
        effective_supported_total=effective_counts["supported"],
        effective_contradicted_total=effective_counts["contradicted"],
        effective_not_in_evidence_total=effective_counts["not_in_evidence"],
        factual_claim_total=factual,
        evidence_scope_ids=[
            scope for item in scoped_sessions for scope in item.evidence_scope_ids
        ],
        sessions=session_summaries,
    )


__all__ = [
    "NODE_REJUDGE",
    "NODE_RETRIEVE",
    "claim_evidence_rejudge_node",
    "claim_evidence_retrieve_node",
    "claim_evidence_summary",
    "snapshot_to_evidence",
]
