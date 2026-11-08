"""Persist merge-boundary checkpoints while consuming a synchronous LangGraph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.base import BaseAuditRepository, PersistenceConflict
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    canonical_hash,
    canonical_json,
    build_checkpoint_projection,
)


class DurableWorkflowRunner:
    def __init__(
        self,
        workflow: Any,
        repository: BaseAuditRepository,
        artifact_recorder: Any | None = None,
        supplement_repository: Any | None = None,
    ):
        self.workflow = workflow
        self.repository = repository
        self.artifact_recorder = artifact_recorder
        # Optional: only a run that authorised supplement excerpts needs it to
        # recompute the frozen evidence of a child version.
        self.supplement_repository = supplement_repository

    def _evidence_ids_for(
        self, run_id: str, spec, *, version: int, available: set[str], resource_id: str,
        boundary_resource_id: str | None = None,
    ) -> list[str]:
        """Frozen spec ids plus only the generation scopes granted to this child.

        Legacy runs have no scope rows and keep exactly the spec boundary.
        """

        ids = list(spec.evidence_ids)
        repository = self.supplement_repository
        if repository is None:
            return ids
        resource_repository = getattr(self.artifact_recorder, "resource_repository", None)
        scopes = repository.list_evidence_sets([run_id])
        if not scopes:
            return ids
        from app.models.reviews.evidence_lineage import resource_lineage

        resource = resource_repository.get(resource_id) if resource_repository else None
        if (resource is None or resource.version != version or resource.run_id != run_id
                or resource.resource_spec_id != spec.resource_spec_id):
            raise ValueError("recovery evidence resource missing")
        lineage = {(item.resource_id, item.version) for item in list(
            resource_lineage(resource, resource_repository.get, within_run=True,
                             boundary_resource_id=boundary_resource_id)
        )[1:]}
        for scope in scopes:
            if (
                getattr(scope, "purpose", None) != "generation"
                or (scope.resource_id, scope.resource_version) not in lineage
            ):
                continue
            if resource_repository is not None:
                parent = resource_repository.get(scope.resource_id)
                if parent is None or parent.resource_spec_id != spec.resource_spec_id:
                    continue
            for evidence_id in scope.added_evidence_ids:
                if evidence_id not in available:
                    raise ValueError("recovery supplement snapshot missing")
                if evidence_id in available and evidence_id not in ids:
                    ids.append(evidence_id)
        return ids

    def _restore_evidence_context(self, state):
        """Rebuild runtime grants from durable scopes and actual resource edges."""
        if not state.get("include_claim_evidence_retrieval"):
            return
        if self.supplement_repository is None:
            raise ValueError("supplement repository unavailable")
        from app.models.reviews.evidence_lineage import evidence_item_hash, resource_lineage
        from app.models.reviews.claim_evidence_retrieval import ClaimReviewEvidenceSetV1
        from app.models.shared.persistence import PersistedEvidenceSnapshot
        from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.nodes import snapshot_to_evidence

        run_id = state["run_id"]
        scopes = [ClaimReviewEvidenceSetV1.model_validate(item.model_dump(mode="json"))
                  for item in self.supplement_repository.list_evidence_sets([run_id])]
        resource_repo = getattr(self.artifact_recorder, "resource_repository", None)
        history = {}
        for resource in state.get("generated_resources", []):
            if resource_repo is None:
                raise ValueError("evidence lineage repository unavailable")
            boundary = (state.get("resource_retry_context") or {}).get("source_resource") or {}
            for ancestor in resource_lineage(resource, resource_repo.get, within_run=True,
                                             boundary_resource_id=boundary.get("resource_id")):
                if ancestor.run_id != run_id:
                    raise ValueError("evidence lineage run mismatch")
                history[ancestor.resource_id] = {key: getattr(ancestor, key) for key in (
                    "resource_id", "run_id", "resource_spec_id", "resource_family_id",
                    "version", "parent_resource_id",
                )}
            if boundary:
                history[boundary["resource_id"]] = {key: boundary[key] for key in (
                    "resource_id", "run_id", "resource_spec_id", "resource_family_id",
                    "version", "parent_resource_id",
                )}
        state["claim_evidence_lineage"] = history
        snapshots = {item.evidence_id: item for item in self.repository.list_evidence(run_id)}
        pool, grants = {}, {}
        for scope in scopes:
            if scope.run_id != run_id:
                raise ValueError("evidence scope run mismatch")
            owner = resource_repo.get(scope.resource_id) if resource_repo else None
            if owner is None or owner.run_id != run_id or owner.version != scope.resource_version:
                raise ValueError("evidence scope resource mismatch")
            for ident in scope.added_evidence_ids:
                if ident not in snapshots:
                    raise ValueError("supplement snapshot missing")
                snapshot = PersistedEvidenceSnapshot.model_validate(snapshots[ident].model_dump(mode="python"))
                item = snapshot_to_evidence(snapshot)
                if (item.knowledge_base_id != state.get("knowledge_base_id")
                        or evidence_item_hash(item) != scope.snapshot_hashes[ident]):
                    raise ValueError("supplement scope snapshot mismatch")
                pool[ident] = item
            grants.setdefault(scope.resource_id, []).append(scope.model_dump(mode="json"))
        state["claim_evidence_scopes"] = grants
        state["supplement_retrieved_evidence"] = list(pool.values())

    def _validate_lecture_entry(self, state):
        from app.services.generation.lecture_policy import lecture_fields
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_authority import validate_lecture_authority
        run_id = state.get("run_id")
        run = self.repository.get_run(run_id) if run_id else None
        if run is None:
            if lecture_fields(state):
                raise ValueError("lecture run authority missing")
            return
        if str(getattr(run.replay_completeness, "value", run.replay_completeness)) == "legacy_partial":
            raise ValueError("legacy partial run is read-only; execution authority unavailable")
        snapshot = self.repository.get_run_creation_snapshot(run_id)
        frozen = lecture_fields(snapshot)
        if frozen != lecture_fields(state):
            raise ValueError("lecture runtime differs from run creation snapshot")
        events = self.repository.list_events(run_id, after_sequence=0, limit=100)
        created = [event for event in events if str(getattr(event.event_type, "value", event.event_type)) == "RUN_CREATED" or str(getattr(event.event_type, "value", event.event_type)) == "run_created"]
        if len(created) != 1:
            raise ValueError("lecture run creation event missing")
        if created[0].payload_hash != canonical_hash(created[0].payload):
            raise ValueError("lecture run creation event payload hash mismatch")
        validate_lecture_authority(request_snapshot=snapshot, request_hash=run.request_hash,
            created_event_request_hash=created[0].payload.get("request_hash"),
            dispatch=state.get("lecture_dispatch_snapshot"), checkpoint=state)

    def _assert_no_unfinished_lecture_review(self, state):
        """Refuse to resume a V2 run holding an unfinished review step.

        This must run before ``workflow.stream`` (or any model call), so an old
        interrupted review round cannot silently continue with a fresh attempt
        budget.  Only contract 2.0 runs carry the review-entry guard; legacy and
        V1 runs keep their existing recovery semantics.
        """
        from app.services.generation.lecture_policy import lecture_fields
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
            LectureStepGuardError,
            assert_no_unfinished_review,
        )
        if not state.get("lecture_review_policy"):
            return
        frozen = lecture_fields(state)
        if frozen.get("lecture_review_contract_version") != "2.0":
            return
        run_id = state.get("run_id")
        try:
            assert_no_unfinished_review(repository=self.repository, run_id=run_id)
        except LectureStepGuardError as exc:
            raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT, status_code=409) from exc

    def _restore_lecture_ledgers(self, state, *, recovering=True):
        if not state.get("lecture_review_policy"):
            return
        from app.models.reviews.review_audit import review_audit_envelope
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import text_hash, comparison_hash, validate_lecture_review
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract_v2 import validate_lecture_review_v2
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine import RULE_IDS
        from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
        from app.services.generation.lecture_policy import lecture_fields
        run_id = state["run_id"]
        checkpoints = self.repository.list_checkpoints(run_id)
        if any(cp.state_hash != canonical_hash(cp.state_projection) for cp in checkpoints):
            raise ValueError("lecture checkpoint state hash mismatch")
        frozen = lecture_fields(self.repository.get_run_creation_snapshot(run_id))
        if any(lecture_fields(cp.state_projection) != frozen for cp in checkpoints):
            raise ValueError("lecture checkpoint frozen policy fields missing or changed")
        # Replay must use the validator that owns this contract version. Reading a
        # V2 ledger through V1 would have to invent a coverage verdict.
        v2 = frozen["lecture_review_contract_version"] == "2.0"
        audit_schema = "3.0" if v2 else "2.0"
        coverage_threshold = (LectureReviewPolicyV2.model_validate(frozen["lecture_review_policy"]).coverage_threshold
                              if v2 else 0.8)
        checkpoint_steps = {cp.step_id for cp in checkpoints}
        for step in self.repository.list_steps(run_id):
            if step.node_name in {"review", "reviewer"} and step.status in {"success", "degraded", "human_review"} and step.step_id not in checkpoint_steps and recovering:
                raise ValueError("observation_incomplete: committed review has no checkpoint")
        references = state.get("review_audit_refs", [])
        if checkpoints and recovering:
            latest = max(checkpoints, key=lambda cp: (cp.step_sequence, cp.event_sequence, cp.checkpoint_id))
            if references != latest.state_projection.get("review_audit_refs", []):
                raise ValueError("lecture checkpoint audit references missing or changed")
        referenced_steps = {ref.get("step_id") for ref in references}
        for step in self.repository.list_steps(run_id):
            if step.node_name in {"review", "reviewer"} and step.status in {"success", "degraded", "human_review"} and step.step_id not in referenced_steps:
                raise ValueError("lecture committed review audit reference missing")
        ledgers = {}
        resource_repo = getattr(self.artifact_recorder, "resource_repository", None)
        evidence = {item.evidence_id: item for item in self.repository.list_evidence(run_id)}
        for reference in references:
            if reference.get("schema_version") != audit_schema:
                raise ValueError("lecture checkpoint references legacy audit")
            audit = self.repository.get_step_review_audit(run_id, reference["step_id"])
            if audit is None or audit.schema_version != audit_schema:
                raise ValueError("lecture audit missing")
            envelope = review_audit_envelope(audit, run_id=run_id, step_id=reference["step_id"])
            if envelope["audit_hash"] != reference.get("audit_hash"):
                raise ValueError("lecture audit reference hash mismatch")
            expected_reference = {"step_id": audit.step_id, "audit_hash": envelope["audit_hash"],
                "review_ids": [resource.review_id for resource in audit.resources], "schema_version": audit_schema,
                "lecture_resources": [{"resource_id": ledger.binding.resource_id, "resource_spec_id": ledger.binding.resource_spec_id,
                    "version": ledger.binding.version, "content_hash": ledger.binding.content_hash,
                    "lineage_id": ledger.binding.lineage_id} for ledger in audit.lecture_ledgers]}
            if reference != expected_reference:
                raise ValueError("lecture audit reference summary mismatch")
            for ledger in audit.lecture_ledgers:
                if resource_repo is None:
                    raise ValueError("lecture resource repository unavailable")
                spec = resource_repo.get_spec(ledger.binding.resource_spec_id)
                if spec is None or spec.run_id != run_id:
                    raise ValueError("lecture frozen specification missing")
                evidence_ids = sorted(self._evidence_ids_for(
                    run_id, spec, version=ledger.binding.version, available=set(evidence),
                    resource_id=ledger.binding.resource_id,
                    boundary_resource_id=((state.get("resource_retry_context") or {}).get("source_resource") or {}).get("resource_id"),
                ))
                frozen_evidence = [{"evidence_id": ident, "excerpt_hash": text_hash(evidence[ident].excerpt), "excerpt": evidence[ident].excerpt} for ident in evidence_ids]
                if canonical_hash({"evidence": frozen_evidence}) != ledger.binding.evidence_snapshot_hash:
                    raise ValueError("lecture frozen evidence mismatch")
                previous_resource = None
                previous_content = None
                old_open, old_closed, unchanged_count = (), (), 0
                if ledger.carry_over is not None:
                    # An epoch must be validated against the immutable predecessor
                    # ledger that is still present in the audit reference chain, not
                    # against the final context of this ledger.
                    from app.models.reviews.evidence_context import validate_carry_over
                    from app.models.reviews.lecture_review import LectureIssueHistoryV1
                    from app.models.reviews.lecture_review_v2 import LectureIssueHistoryV2
                    from app.models.reviews.lecture_review import LectureLedgerV1
                    data = ledgers.get(ledger.binding.resource_spec_id)
                    if data is None:
                        raise ValueError("lecture epoch predecessor ledger missing")
                    predecessor_ledger = (LectureLedgerV2.model_validate(data) if v2
                                          else LectureLedgerV1.model_validate(data))
                    carried = validate_carry_over(
                        ledger.carry_over, binding=ledger.binding,
                        previous_ledger=predecessor_ledger,
                        history_model=LectureIssueHistoryV2 if v2 else LectureIssueHistoryV1)
                    predecessor = resource_repo.get(ledger.carry_over.previous_resource_id)
                    if (predecessor is None
                            or text_hash(predecessor.content_text or "") != ledger.carry_over.previous_content_hash):
                        raise ValueError("lecture epoch predecessor content mismatch")
                    previous_content = predecessor.content_text or ""
                    previous_resource = predecessor.resource_id
                    old_open = tuple(item.issue for item in carried)
                    old_closed = ()
                    unchanged_count = ledger.carry_over.consecutive_unchanged
                for observation in ledger.observations:
                    binding = observation.binding
                    resource = resource_repo.get(binding.resource_id)
                    if (resource is None or resource.run_id != run_id or resource.resource_spec_id != binding.resource_spec_id
                            or resource.resource_family_id != binding.lineage_id or resource.version != binding.version
                            or text_hash(resource.content_text or "") != binding.content_hash):
                        raise ValueError("lecture persisted resource version mismatch")
                    if previous_resource is not None and resource.parent_resource_id != previous_resource:
                        raise ValueError("lecture persisted parent lineage mismatch")
                    content = resource.content_text or ""
                    if observation.comparison_hash != comparison_hash(content):
                        raise ValueError("lecture persisted comparison hash mismatch")
                    validator = validate_lecture_review_v2 if v2 else validate_lecture_review
                    extra = {"coverage_threshold": coverage_threshold} if v2 else {}
                    result = validator(output=observation.output, binding=binding,
                        content=content, previous_content=previous_content, targets=spec.knowledge_points,
                        evidence_hashes={item["evidence_id"]: item["excerpt_hash"] for item in frozen_evidence},
                        teaching_rule_ids=RULE_IDS, old_open=old_open, old_closed=old_closed,
                        consecutive_unchanged=unchanged_count, count_unchanged=observation.revision_kind == "ordinary",
                        **extra)
                    if v2 and observation.coverage_rate != result.coverage_rate:
                        raise ValueError("lecture persisted coverage rate mismatch")
                    expected_count = (unchanged_count if observation.revision_kind == "claim" else
                                      unchanged_count + 1 if result.unchanged else 0)
                    if (observation.decision != result.decision or observation.unchanged != result.unchanged
                            or observation.consecutive_unchanged != expected_count):
                        raise ValueError("lecture persisted observation decision or count mismatch")
                    all_issues = {item.issue_id: item for item in (*old_open, *old_closed, *observation.output.issues)}
                    open_ids = {item.issue_id for item in result.open_issues}
                    old_open = tuple(item for ident, item in all_issues.items() if ident in open_ids)
                    old_closed = tuple(item for ident, item in all_issues.items() if ident not in open_ids)
                    unchanged_count = expected_count
                    previous_content = content
                    previous_resource = resource.resource_id
                ledgers[ledger.binding.resource_spec_id] = ledger.model_dump(mode="json")
        supplied = state.get("lecture_ledgers")
        if supplied and supplied != ledgers:
            raise ValueError("lecture runtime ledger differs from durable audit")
        state["lecture_ledgers"] = ledgers

    def _validate_resource_entry(self, state):
        from app.services.generation.resource_review_policy import resource_review_fields
        from app.agents.resource_workflows.learning_documents.reviewing.resource_authority import (
            validate_resource_authority,
        )
        run_id = state.get("run_id")
        run = self.repository.get_run(run_id) if run_id else None
        if run is None:
            if resource_review_fields(state):
                raise ValueError("resource run authority missing")
            return
        if str(getattr(run.replay_completeness, "value", run.replay_completeness)) == "legacy_partial":
            raise ValueError("legacy partial run is read-only; execution authority unavailable")
        snapshot = self.repository.get_run_creation_snapshot(run_id)
        frozen = resource_review_fields(snapshot)
        if frozen != resource_review_fields(state):
            raise ValueError("resource runtime differs from run creation snapshot")
        events = self.repository.list_events(run_id, after_sequence=0, limit=100)
        created = [event for event in events if str(getattr(event.event_type, "value", event.event_type)) in ("RUN_CREATED", "run_created")]
        if len(created) != 1:
            raise ValueError("resource run creation event missing")
        if created[0].payload_hash != canonical_hash(created[0].payload):
            raise ValueError("resource run creation event payload hash mismatch")
        validate_resource_authority(request_snapshot=snapshot, request_hash=run.request_hash,
            created_event_request_hash=created[0].payload.get("request_hash"),
            dispatch=state.get("resource_dispatch_snapshot"), checkpoint=state)

    def _assert_no_unfinished_resource_review(self, state):
        """Refuse to resume a resource-issue run holding an unfinished review step."""
        if not state.get("resource_review_policy"):
            return
        from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
            LectureStepGuardError,
            assert_no_unfinished_review,
        )
        run_id = state.get("run_id")
        try:
            assert_no_unfinished_review(repository=self.repository, run_id=run_id)
        except LectureStepGuardError as exc:
            raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT, status_code=409) from exc

    def _restore_resource_ledgers(self, state, *, recovering=True):
        if not state.get("resource_review_policy"):
            return
        from app.models.reviews.review_audit import review_audit_envelope
        from app.services.generation.resource_review_policy import resource_review_fields
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import text_hash
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.persistence import verify_binding_hashes, replay_resource_artifacts
        from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.registry import adapter_for
        run_id = state["run_id"]
        checkpoints = self.repository.list_checkpoints(run_id)
        if any(cp.state_hash != canonical_hash(cp.state_projection) for cp in checkpoints):
            raise ValueError("resource checkpoint state hash mismatch")
        frozen = resource_review_fields(self.repository.get_run_creation_snapshot(run_id))
        if any(resource_review_fields(cp.state_projection) != frozen for cp in checkpoints):
            raise ValueError("resource checkpoint frozen policy fields missing or changed")
        audit_schema = "4.0"
        checkpoint_steps = {cp.step_id for cp in checkpoints}
        for step in self.repository.list_steps(run_id):
            if step.node_name in {"review", "reviewer"} and step.status in {"success", "degraded", "human_review"} and step.step_id not in checkpoint_steps and recovering:
                raise ValueError("observation_incomplete: committed resource review has no checkpoint")
        references = state.get("review_audit_refs", [])
        if checkpoints and recovering:
            latest = max(checkpoints, key=lambda cp: (cp.step_sequence, cp.event_sequence, cp.checkpoint_id))
            if references != latest.state_projection.get("review_audit_refs", []):
                raise ValueError("resource checkpoint audit references missing or changed")
        referenced_steps = {ref.get("step_id") for ref in references}
        for step in self.repository.list_steps(run_id):
            if step.node_name in {"review", "reviewer"} and step.status in {"success", "degraded", "human_review"} and step.step_id not in referenced_steps:
                raise ValueError("resource committed review audit reference missing")
        ledgers = {}
        resource_repo = getattr(self.artifact_recorder, "resource_repository", None)
        evidence = {item.evidence_id: item for item in self.repository.list_evidence(run_id)}
        for reference in references:
            if reference.get("schema_version") != audit_schema:
                raise ValueError("resource checkpoint references legacy audit")
            audit = self.repository.get_step_review_audit(run_id, reference["step_id"])
            if audit is None or audit.schema_version != audit_schema:
                raise ValueError("resource audit missing")
            envelope = review_audit_envelope(audit, run_id=run_id, step_id=reference["step_id"])
            if envelope["audit_hash"] != reference.get("audit_hash"):
                raise ValueError("resource audit reference hash mismatch")
            expected_reference = {"step_id": audit.step_id, "audit_hash": envelope["audit_hash"],
                "review_ids": [resource.review_id for resource in audit.resources], "schema_version": audit_schema,
                "resource_ledgers": [{"resource_id": ledger.binding.resource_id, "resource_spec_id": ledger.binding.resource_spec_id,
                    "version": ledger.binding.version, "artifact_exact_hash": ledger.binding.artifact_exact_hash,
                    "lineage_id": ledger.binding.lineage_id} for ledger in audit.resource_ledgers]}
            if reference != expected_reference:
                raise ValueError("resource audit reference summary mismatch")
            for ledger in audit.resource_ledgers:
                if resource_repo is None:
                    raise ValueError("resource resource repository unavailable")
                spec = resource_repo.get_spec(ledger.binding.resource_spec_id)
                if spec is None or spec.run_id != run_id:
                    raise ValueError("resource frozen specification missing")
                evidence_ids = sorted(self._evidence_ids_for(
                    run_id, spec, version=ledger.binding.version, available=set(evidence),
                    resource_id=ledger.binding.resource_id,
                    boundary_resource_id=((state.get("resource_retry_context") or {}).get("source_resource") or {}).get("resource_id"),
                ))
                evidence_items = [evidence[ident] for ident in evidence_ids]
                frozen_evidence = [{"evidence_id": ident, "excerpt_hash": text_hash(evidence[ident].excerpt)}
                                   for ident in evidence_ids]
                if canonical_hash({"evidence": frozen_evidence}) != ledger.binding.evidence_snapshot_hash:
                    raise ValueError("resource frozen evidence mismatch")
                adapter = adapter_for(ledger.binding.resource_type)
                targets = list(spec.knowledge_points)
                previous_resource = None
                versioned_resources = []
                for observation in ledger.observations:
                    binding = observation.binding
                    resource = resource_repo.get(binding.resource_id)
                    if (resource is None or resource.run_id != run_id or resource.resource_spec_id != binding.resource_spec_id
                            or resource.resource_family_id != binding.lineage_id or resource.version != binding.version):
                        raise ValueError("resource persisted resource version mismatch")
                    if previous_resource is not None and resource.parent_resource_id != previous_resource:
                        raise ValueError("resource persisted parent lineage mismatch")
                    material = adapter.build_material(resource=resource, evidence=evidence_items,
                                                      spec=None, targets=targets)
                    verify_binding_hashes(binding=binding, material=material, evidence=evidence_items)
                    previous_resource = resource.resource_id
                    versioned_resources.append(resource)
                from app.models.reviews.resource_review import ResourceLedgerV1
                predecessor_data = ledgers.get(ledger.binding.resource_spec_id)
                predecessor = (ResourceLedgerV1.model_validate(predecessor_data)
                               if predecessor_data else None)
                predecessor_resource = None
                if ledger.carry_over is not None:
                    if predecessor is None:
                        raise ValueError("resource epoch predecessor ledger missing")
                    predecessor_resource = resource_repo.get(ledger.carry_over.previous_resource_id)
                    if predecessor_resource is None:
                        raise ValueError("resource epoch predecessor resource missing")
                verified = replay_resource_artifacts(
                    ledger=ledger, resources=versioned_resources, adapter=adapter,
                    targets=targets, evidence=evidence_items,
                    predecessor=predecessor, predecessor_resource=predecessor_resource)
                ledgers[ledger.binding.resource_spec_id] = verified.model_dump(mode="json")
        supplied = state.get("resource_ledgers")
        if supplied and supplied != ledgers:
            raise ValueError("resource runtime ledger differs from durable audit")
        state["resource_ledgers"] = ledgers

    def invoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        from app.db.claim.extraction import extraction_repository
        from app.agents.resource_workflows.learning_documents.claim_extraction.budget import validate_entry
        private_repository = extraction_repository(self.repository)
        self._restore_evidence_context(initial_state)
        self._validate_lecture_entry(initial_state)
        self._assert_no_unfinished_lecture_review(initial_state)
        self._restore_lecture_ledgers(initial_state)
        self._validate_resource_entry(initial_state)
        if initial_state.get("resource_review_policy") and initial_state.get("resource_review_contract_version") != "1.1":
            raise ValueError("historical resource review identity is read-only; create a new run")
        self._assert_no_unfinished_resource_review(initial_state)
        self._restore_resource_ledgers(initial_state)
        validate_entry(initial_state, private_repository)
        if not hasattr(self.workflow, "stream"):
            raw_result = self.workflow.invoke(initial_state)
            result = {**initial_state, **raw_result}
            self._validate_lecture_entry(result)
            self._validate_resource_entry(result)
            validate_entry(result, private_repository)
            if "workflow_status" not in raw_result:
                result["workflow_status"] = "completed"
            self._record_compatibility_trace(result)
            return result

        latest: dict[str, Any] = initial_state
        checkpointed: set[str] = set()
        for value in self.workflow.stream(initial_state, stream_mode="values"):
            if not isinstance(value, dict):
                continue
            latest = value
            self._validate_lecture_entry(latest)
            self._validate_resource_entry(latest)
            validate_entry(latest, private_repository)
            trace = latest.get("trace", [])
            if not trace:
                continue
            item = trace[-1]
            if not isinstance(item, dict) or not item.get("step_id"):
                continue
            step_id = str(item["step_id"])
            if step_id in checkpointed:
                continue
            if latest.get("lecture_review_policy") and latest.get("review_audit_refs"):
                self._restore_lecture_ledgers(latest, recovering=False)
            if latest.get("resource_review_policy"):
                self._restore_resource_ledgers(latest, recovering=False)
            if self.artifact_recorder is not None:
                try:
                    self.artifact_recorder.record(latest, item)
                except Exception as exc:
                    code = (
                        ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                        if isinstance(exc, PersistenceConflict)
                        else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                    )
                    raise ApplicationError(
                        code,
                        status_code=409 if isinstance(exc, PersistenceConflict) else 503,
                    ) from exc
            self._restore_lecture_ledgers(latest, recovering=False)
            self._restore_resource_ledgers(latest, recovering=False)
            projection = build_checkpoint_projection(latest)
            encoded = canonical_json(projection).encode("utf-8")
            if len(encoded) > get_settings().workflow_checkpoint_max_bytes:
                raise ApplicationError(ErrorCode.WORKFLOW_CHECKPOINT_INVALID, status_code=500)
            try:
                self.repository.save_checkpoint(
                    run_id=str(initial_state["run_id"]),
                    step_id=step_id,
                    step_sequence=int(item["sequence"]),
                    node_name=str(item.get("node_name") or item.get("agent_name") or "unknown"),
                    state_projection=projection,
                    state_hash=canonical_hash(projection),
                    occurred_at=datetime.now(timezone.utc),
                )
            except Exception as exc:
                code = (
                    ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                    if isinstance(exc, PersistenceConflict)
                    else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                )
                raise ApplicationError(code, status_code=409 if isinstance(exc, PersistenceConflict) else 503) from exc
            checkpointed.add(step_id)
        return latest

    def _record_compatibility_trace(self, result: dict[str, Any]) -> None:
        """Record non-LangGraph test doubles without weakening the production wrapper."""

        run_id = str(result["run_id"])
        existing_ids = {item.step_id for item in self.repository.list_steps(run_id)}
        traces = [dict(item) for item in result.get("trace", []) if isinstance(item, dict)]
        resources = [
            item for item in result.get("generated_resources", []) if hasattr(item, "resource_id")
        ]
        agents = {str(item.get("agent_name") or "") for item in traces}
        if resources and "generator" not in agents:
            traces.insert(0, {
                "step_id": f"{run_id}:compat-generator",
                "agent_name": "generator",
                "node_name": "generator",
                "action": "compatibility artifact boundary",
                "status": "success",
                "resource_ids": [item.resource_id for item in resources],
            })

        for sequence, raw in enumerate(traces, start=1):
            if not isinstance(raw, dict):
                continue
            trace = dict(raw)
            step_id = str(trace.get("step_id") or f"{run_id}:{sequence}")
            if step_id in existing_ids:
                continue
            trace.update(run_id=run_id, step_id=step_id, sequence=sequence)
            if trace.get("agent_name") == "generator" and not trace.get("resource_ids"):
                trace["resource_ids"] = [item.resource_id for item in resources]
            started_at = datetime.now(timezone.utc)
            self.repository.begin_step(
                BeginStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    step_sequence=sequence,
                    node_name=str(trace.get("node_name") or trace.get("agent_name") or "test_double"),
                    agent_name=str(trace.get("agent_name") or "test_double"),
                    action=str(trace.get("action") or "test double"),
                    generation_attempt=int(trace.get("attempt") or 1),
                    started_at=started_at,
                )
            )
            # Test doubles use invoke() rather than LangGraph streaming. They
            # still honor the production ownership rule: artifacts are durable
            # before the corresponding compatibility checkpoint is accepted.
            if self.artifact_recorder is not None:
                try:
                    self.artifact_recorder.record(result, trace)
                except Exception as exc:
                    code = (
                        ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                        if isinstance(exc, PersistenceConflict)
                        else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                    )
                    raise ApplicationError(
                        code,
                        status_code=409 if isinstance(exc, PersistenceConflict) else 503,
                    ) from exc
            self.repository.complete_step(
                CompleteStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    trace=trace,
                    review_audit=(result.get("review_audit") if (result.get("review_audit") or {}).get("step_id") == step_id else None),
                    ended_at=datetime.now(timezone.utc),
                )
            )
            projection = build_checkpoint_projection(result)
            self.repository.save_checkpoint(
                run_id=run_id,
                step_id=step_id,
                step_sequence=sequence,
                node_name=str(trace.get("node_name") or trace.get("agent_name") or "test_double"),
                state_projection=projection,
                state_hash=canonical_hash(projection),
                occurred_at=datetime.now(timezone.utc),
            )
