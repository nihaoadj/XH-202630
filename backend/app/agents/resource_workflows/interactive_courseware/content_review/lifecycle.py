"""Workflow-owned orchestration for private approval, recovery and release gates."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import local
from uuid import uuid4

from app.core.courseware.content_review import resolve_adapter, design_projection, content_identity
from app.models.courseware.content_review import ContentReviewBlocked, ContentReviewBusy, ContentReviewRecordV1, json_hash
from app.core.courseware.content_review.identity import approval_identity
from .persistence import read_state, mutate_spec, guard_owner
from .engine import review_content
from .profiles import REVIEW_PROFILE, REVISION_PROFILE
from .prompts.builder import fingerprint


class ContentReviewLifecycle:
    def __init__(self, workflow=None, *, repository=None):
        self.workflow = workflow
        self.repo = workflow.repo if workflow is not None else repository
        self.local = local()

    def state(self, run_id):
        return read_state(self.repo, run_id)[0]

    def claim(self, run_id):
        owner = f"content:{uuid4().hex}"
        def update(spec):
            state = spec["content_review"]
            if state.get("execution_owner") and state.get("lease_until") and datetime.fromisoformat(state["lease_until"]) > datetime.now(timezone.utc):
                raise ContentReviewBusy("content execution already active")
            state.update(execution_owner=owner, lease_until=(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat())
        mutate_spec(self.repo, run_id, update, lambda: self.workflow._control_guard(run_id))
        self.local.owner = owner

    def guard(self, run_id):
        self.workflow._control_guard(run_id)
        state = self.state(run_id)
        guard_owner(state, getattr(self.local, "owner", None))

    def release(self, run_id):
        owner = getattr(self.local, "owner", None)
        if not owner:
            return
        def update(spec):
            state = spec["content_review"]
            if state["execution_owner"] == owner:
                state.update(execution_owner=None, lease_until=None)
        try:
            mutate_spec(self.repo, run_id, update)
        except (ValueError, KeyError):
            pass
        self.local.owner = None

    def gateway(self, run_id, stage, phase):
        # The runtime guard unwraps and rechecks the real gateway; this wrapper
        # does not turn an unauthenticated provider into an offline fixture.
        def guard():
            self.guard(run_id)
            def renew(spec):
                if spec["content_review"]["execution_owner"] != self.local.owner:
                    raise ContentReviewBusy("lease lost before model")
                spec["content_review"]["lease_until"] = (datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()
            mutate_spec(self.repo, run_id, renew, lambda: self.workflow._control_guard(run_id))
        return self.workflow.budget.bind_gateway(run_id, self.workflow.llm_gateway, stage, phase, guard)

    def context(self, run_id, spec=None):
        job = self.repo.get_job(run_id)
        state, row = read_state(self.repo, run_id)
        row = spec or row
        snapshots = job.get("source_snapshots") or []
        if len(snapshots) != 1:
            raise ContentReviewBlocked("one frozen source required")
        source = snapshots[0]; adapter = resolve_adapter(source)
        try:
            adapter.validate_source(source)
        except (ValueError, KeyError, TypeError) as exc:
            raise ContentReviewBlocked("invalid frozen content source") from exc
        design = {**design_projection(row["spec_json"]), "source_payload": source[adapter.source_key], "user_title": job.get("title")}
        return state, row, source, adapter, design

    def _plan(self, snapshots, learning_design, adapter, values):
        from ..planner_agent import _platform_spec, merge_plan_enrichment
        plan, scene_ids, objective_ids = _platform_spec(learning_design, snapshots)
        if values:
            parsed = adapter.candidate_model.model_validate(values)
            setattr(plan, adapter.candidate_slot, parsed)
            plan.title = parsed.course_title
            if hasattr(parsed, "scenes"):
                plan = merge_plan_enrichment(plan, parsed, scene_ids=scene_ids, objective_ids=objective_ids)
        return plan

    def prepare(self, run_id, job, snapshots, resource_bundle, learner_context, learning_design):
        from ..planner_agent import build_courseware_spec
        from ..composition import default_title, resource_courseware_title
        state, spec = read_state(self.repo, run_id)
        if state.phase == "policy_only":
            def design_save(raw):
                raw.update(schema_version="1.0", learning_design=learning_design.model_dump(mode="json"),
                    storyboard=learning_design.storyboard.model_dump(mode="json"), resource_bundle_snapshot=resource_bundle,
                    learner_context_snapshot=learner_context.model_dump(mode="json"))
                from app.models.courseware.design import CoursewareDesign
                raw["design"] = CoursewareDesign().model_dump(mode="json")
            mutate_spec(self.repo, run_id, design_save, lambda: self.guard(run_id))
        state, spec, source, adapter, design = self.context(run_id)
        warning = None
        if state.record:
            self.verify(run_id)
            values = state.record.approved_values
        else:
            candidate = state.candidate
            if candidate is None:
                from .telemetry import latest_tickets
                unfinished = latest_tickets([t.model_dump(mode="json") for t in state.ledger])
                if unfinished:
                    candidate = {}
                    warning = {"code": "COURSEWARE_CONTENT_REVIEW_INTERRUPTED", "message": "中断调用保持预算占用，候选未复用"}
                else:
                    gateway = self.gateway(run_id, "planner", "planner") if self.workflow.llm_gateway else None
                    options = gateway.options_for("generator", temperature=0.0).model_copy(update={"max_attempts": 3}) if gateway else None
                    plan, warning = build_courseware_spec(gateway, run_id, snapshots, allowance=options,
                        learning_design=learning_design, request_options=job.get("request_options") or {}, content_review=True)
                    warning = self.workflow._record_agent_trace(run_id, warning, "courseware_spec_builder")
                    if warning:
                        warning = {"code": "AI_PLAN_ENRICHMENT_REJECTED" if warning.get("code") == "AI_PLAN_ENRICHMENT_REJECTED" else "AI_PLAN_FALLBACK", "message": "规划候选不可用，按冻结内容策略处理"}
                    enrichment = getattr(plan, adapter.candidate_slot, None) if plan else None
                    candidate = enrichment.model_dump(mode="json") if enrichment else {}
                def candidate_save(raw):
                    raw["content_review"].update(phase="candidate", candidate=candidate)
                mutate_spec(self.repo, run_id, candidate_save, lambda: self.guard(run_id))
            state = self.state(run_id)
            from .telemetry import latest_tickets
            interrupted_review = any(t["phase"] in {"content_review", "content_revision", "content_recheck"} for t in latest_tickets([t.model_dump(mode="json") for t in state.ledger]))
            record = review_content(run_id=run_id, snapshot=source, design=design, candidate={} if interrupted_review else candidate, adapter=adapter,
                policy=state.policy, gateway=None if interrupted_review else self.gateway(run_id, "scene", "content_review"),
                revision_gateway=None if interrupted_review else self.gateway(run_id, "revision", "content_revision"))
            if interrupted_review:
                candidate = {}
                warning = {"code": "COURSEWARE_CONTENT_REVIEW_INTERRUPTED", "message": "未提交审核结果不重复调用，按冻结策略处理"}
            if warning and not candidate:
                status = "degraded" if state.policy.release_policy == "resilient" and not design.get("user_title") else "blocked"
                empty = adapter.prepare(run_id, source, design, {})
                base = content_identity(run_id, source, design, empty.inventory, empty.evidence, state.policy, record.prompt_fingerprint)
                record = record.model_copy(update={"status": status, "reason": "review_interrupted" if interrupted_review else "planner_unavailable", "identity": approval_identity(base, record.results, status)})
            self.save_record(run_id, record)
            if record.status == "blocked":
                raise ContentReviewBlocked("content review blocked")
            values = record.approved_values
            state = self.state(run_id)
        plan = self._plan(snapshots, learning_design, adapter, values)
        title = resource_courseware_title(job.get("title") or (plan.title if values else default_title(snapshots)), snapshots)
        def finish(raw):
            raw.update(title=title, scenes=[s.model_dump(mode="json") for s in plan.scenes])
            raw[adapter.candidate_slot] = values or None
        mutate_spec(self.repo, run_id, finish, lambda: self.guard(run_id))
        if state.record and state.record.status == "degraded":
            warning = {"code": "COURSEWARE_CONTENT_REVIEW_DEGRADED", "message": "新增文字审核不可用或未通过，已清除并采用版本化模板", "fallback_version": "courseware-templates-v1"}
        return plan, warning, spec["spec_id"], plan.enrichment, title

    def save_record(self, run_id, record):
        def update(spec):
            spec["content_review"].update(phase="reviewed", record=record.model_dump(mode="json"))
        mutate_spec(self.repo, run_id, update, lambda: self.guard(run_id))

    def verify(self, run_id, document=None, *, persist_manifest=False, require_manifest=False):
        state, spec, source, adapter, design = self.context(run_id)
        if self.workflow is not None:
            from .persistence import model_configuration_fingerprint
            if state.policy.model_fingerprint != model_configuration_fingerprint(self.workflow.budget.settings_provider()):
                raise ContentReviewBlocked("approved model configuration changed")
        record = state.record
        if not record or record.status not in {"approved", "degraded", "not_applicable"}:
            raise ContentReviewBlocked("no complete content approval")
        if require_manifest and (not record.document_hash or not record.manifest):
            raise ContentReviewBlocked("completed merge proof missing")
        prepared = adapter.prepare(run_id, source, design, record.approved_values)
        prompt_hash = json_hash([fingerprint(REVIEW_PROFILE), fingerprint(REVISION_PROFILE)])
        expected = approval_identity(content_identity(run_id, source, design, prepared.inventory, prepared.evidence, state.policy, prompt_hash), record.results, record.status)
        if expected != record.identity or record.value_hash != json_hash(prepared.candidate) or record.source_hash != json_hash(source) or record.model_fingerprint != state.policy.model_fingerprint:
            raise ContentReviewBlocked("content approval identity mismatch")
        versions = {f.id: f.version for f in (*REVIEW_PROFILE.fragments, *REVISION_PROFILE.fragments)}
        if record.adapter_version != adapter.version or record.candidate_schema != adapter.candidate_model.__name__ or record.prompt_fingerprint != prompt_hash or record.fragment_versions != versions:
            raise ContentReviewBlocked("unknown approval schema/prompt/adapter version")
        if record.inventory_hash != json_hash(prepared.inventory.model_dump(mode="json")) or record.evidence_hash != json_hash(prepared.evidence.model_dump(mode="json")) or record.design_hash != json_hash(design):
            raise ContentReviewBlocked("approval inventory/evidence/design digest mismatch")
        if record.status == "approved":
            from .results import passed, validate_results
            from .types import ReviewBatch
            from app.models.courseware.content_review import BatchResultV1
            by_id = {r.item_id: r for r in record.results}
            if len(by_id) != len(record.results) or set(by_id) != {i.item_id for i in prepared.items} or not passed(record.results):
                raise ContentReviewBlocked("incomplete stored approval")
            if any(by_id[i.item_id].value_hash != i.value_hash for i in prepared.items):
                raise ContentReviewBlocked("stored result/value mismatch")
            batch = ReviewBatch("stored-final", record.identity, record.value_hash, prepared.items, tuple(prepared.evidence.items), (), 0, 0)
            validate_results(BatchResultV1(batch_id=batch.batch_id, identity=batch.identity, value_hash=batch.value_hash, results=record.results), batch)
            if any(not any(r == result for batch in record.batches for r in batch.results) for result in record.results):
                raise ContentReviewBlocked("stored result not backed by batch")
        elif any(i.origin == "user" and not any(r.item_id == i.item_id and r.value_hash == i.value_hash and all(x.verdict == "pass" for x in r.rules) for r in record.results) for i in prepared.items):
            raise ContentReviewBlocked("unapproved user input")
        if spec["spec_json"].get(adapter.candidate_slot) not in (None, record.approved_values):
            raise ContentReviewBlocked("persisted enrichment changed")
        if spec["spec_json"].get("scenes") is not None:
            from app.models.courseware.learning_design import CoursewareLearningDesign
            plan = self._plan([source], CoursewareLearningDesign.model_validate(design["learning_design"]), adapter, record.approved_values)
            if spec["spec_json"]["scenes"] != [s.model_dump(mode="json") for s in plan.scenes]:
                raise ContentReviewBlocked("stored teaching metadata changed")
        if document is not None:
            projection = adapter.validate_projection(source, design, prepared.candidate, document)
            # Validate content independently before freezing the complete output
            # digest. Every subsequent lifecycle entry checks that same output.
            if record.document_hash and record.document_hash != projection["document_hash"]:
                raise ContentReviewBlocked("approved output changed")
            if record.document_hash and [i.model_dump(mode="json") for i in record.manifest] != [i.model_dump(mode="json") for i in projection["manifest"]]:
                raise ContentReviewBlocked("approved display manifest changed")
            if persist_manifest and not record.document_hash:
                self.save_record(run_id, record.model_copy(update=projection))
        return record

    def document(self, run_id):
        state, spec, source, adapter, design = self.context(run_id)
        from app.models.courseware.learning_design import CoursewareLearningDesign
        from ..composition import compose_scenes
        plan = self._plan([source], CoursewareLearningDesign.model_validate(design["learning_design"]), adapter, state.record.approved_values)
        scenes, _ = compose_scenes([source], plan, learning_design=CoursewareLearningDesign.model_validate(design["learning_design"]), plan_enrichment=plan.enrichment)
        return {"schema_version": "2.0", "title": spec["spec_json"]["title"], "scenes": scenes, "design": spec["spec_json"]["design"]}

    def degrade(self, run_id, reason):
        state, _, source, adapter, design = self.context(run_id)
        if state.policy.release_policy == "strict":
            return None
        # Templates retain the user's input; a rejected user title cannot be
        # silently changed by a model or given an unreviewed template approval.
        if design.get("user_title") and any(r.item_id.startswith("user:") and any(x.verdict != "pass" for x in r.rules) for r in state.record.results):
            return None
        empty = adapter.prepare(run_id, source, design, {})
        record = state.record.model_copy(update={"status": "degraded", "approved_values": {}, "value_hash": json_hash({}),
            "identity": approval_identity(content_identity(run_id, source, design, empty.inventory, empty.evidence, state.policy, state.record.prompt_fingerprint), state.record.results, "degraded"),
            "inventory_hash": json_hash(empty.inventory.model_dump(mode="json")), "reason": reason, "manifest": [], "document_hash": None})
        self.save_record(run_id, record)
        from ..composition import default_title, resource_courseware_title
        def clear(raw):
            raw[adapter.candidate_slot] = None
            raw["title"] = resource_courseware_title(design.get("user_title") or default_title([source]), [source])
            from app.models.courseware.learning_design import CoursewareLearningDesign
            plan = self._plan([source], CoursewareLearningDesign.model_validate(design["learning_design"]), adapter, {})
            raw["scenes"] = [s.model_dump(mode="json") for s in plan.scenes]
        mutate_spec(self.repo, run_id, clear, lambda: self.guard(run_id))
        document = self.document(run_id)
        self.verify(run_id, document, persist_manifest=True)
        self.workflow._persist_deterministic_scenes(run_id, document)
        return document

    def quality(self, run_id, job, document):
        from ..quality_reviewer_agent import review_courseware_quality_decision
        self.verify(run_id, document, persist_manifest=True, require_manifest=True)
        state, _, source, adapter, design = self.context(run_id)
        prepared = adapter.prepare(run_id, source, design, state.record.approved_values)
        gateway = self.gateway(run_id, "quality_review", "quality_review") if self.workflow.llm_gateway else None
        options = gateway.options_for("generator", temperature=0.0).model_copy(update={"max_attempts": 3}) if gateway else None
        decision, warning = review_courseware_quality_decision(gateway, run_id, document, allowance=options, content_review=True,
            evidence=[e.model_dump(mode="json") for e in prepared.evidence.items])
        self.guard(run_id)
        self.workflow._record_llm_trace(run_id, "courseware_quality_reviewer", decision.trace_metadata, budget_stage="quality_review")
        # Public issues carry only a category, never model-generated snippets.
        self.workflow._save_review(run_id, "ai_teaching_quality", decision.decision,
            [{"code": "CONTENT_QUALITY_FINDING", "severity": "error", "instruction": "冻结课件需复核"} for _ in decision.issues], rubric_scores=decision.rubric_scores)
        if decision.decision == "approved" and not decision.issues:
            return document, warning
        ids = set()
        for issue in decision.issues:
            issue_ids = set()
            targets = set(issue.affected_scene_ids or []) | ({issue.scene_id} if issue.scene_id else set())
            if issue.severity == "error" and issue.scope in {"scene", "scenes", "course"}:
                scoped = [s for s in document["scenes"] if issue.scope == "course" or s["scene_id"] in targets]
                critical = {"review_recall_card", "review_distinction_card", "review_example_card", "review_node_summary", "code_block"}
                if any(s.get("practice_json_subject") or any(b.get("component") in critical for b in s.get("component_blocks", [])) for s in scoped):
                    return None, {"code": "AI_QUALITY_REVIEW_FIXED_CONTENT", "message": "固定题目或操作与AI文案混合，反馈无法安全归属，课件隔离"}
            for item in state.record.manifest:
                if item.origin != "ai":
                    continue
                for target in item.targets:
                    if target.tokens[:1] != ["scenes"]:
                        continue
                    scene = document["scenes"][target.tokens[1]]
                    matches = issue.scope == "course" or scene["scene_id"] in targets
                    if issue.scope == "block":
                        block_index = next((i for i, b in enumerate(scene.get("component_blocks", [])) if b.get("block_id") == issue.block_id), None)
                        matches = matches and block_index is not None and len(target.tokens) >= 4 and target.tokens[2:4] == ["component_blocks", block_index]
                    if matches:
                        issue_ids.update(i.item_id for i in prepared.items if i.origin == "ai" and (i.item_id in item.dependency_ids or i.value_hash == item.value_hash))
            if issue.severity == "error" and issue.scope in {"scene", "scenes", "block"} and not issue_ids:
                return None, {"code": "AI_QUALITY_REVIEW_FIXED_CONTENT", "message": "固定内容的问题不能通过自由改写或模板掩盖"}
            ids.update(issue_ids)
        if decision.decision == "revision_required" and state.record.revision_rounds < state.policy.max_revision_rounds:
            # Frozen components cannot be rewritten. Route only visible AI
            # values on the located page(s), using the frozen display manifest.
            if ids:
                record = review_content(run_id=run_id, snapshot=source, design=design, candidate=state.record.approved_values,
                    adapter=adapter, policy=state.policy, gateway=self.gateway(run_id, "revision", "content_recheck"),
                    revision_gateway=self.gateway(run_id, "revision", "content_revision"), revision_rounds=state.record.revision_rounds,
                    forced_ids=ids, prior_results=state.record.results, prior_batches=state.record.batches)
                self.save_record(run_id, record)
                if record.status == "approved":
                    def update(raw):
                        raw[adapter.candidate_slot] = record.approved_values
                        from app.models.courseware.learning_design import CoursewareLearningDesign
                        from ..composition import resource_courseware_title
                        plan = self._plan([source], CoursewareLearningDesign.model_validate(design["learning_design"]), adapter, record.approved_values)
                        raw["scenes"] = [s.model_dump(mode="json") for s in plan.scenes]
                        raw["title"] = resource_courseware_title(design.get("user_title") or plan.title, [source])
                    mutate_spec(self.repo, run_id, update, lambda: self.guard(run_id))
                    revised = self.document(run_id)
                    self.verify(run_id, revised, persist_manifest=True)
                    self.workflow._persist_deterministic_scenes(run_id, revised)
                    # A second overall review remains budgeted by its own call.
                    return self.quality(run_id, job, revised)
        fallback = self.degrade(run_id, "overall_quality_unavailable_or_rejected")
        return fallback, {"code": "AI_QUALITY_REVIEW_CONTENT_FALLBACK", "message": "整体审核未通过或不可用，执行受控模板策略", "discarded_candidate": True, "fallback_version": "courseware-templates-v1"}


def verify_run_content(repo, run_id, document=None):
    state, spec = read_state(repo, run_id)
    if state is None:
        return None
    if document is None:
        raw = spec["spec_json"]
        document = {"schema_version": "2.0", "title": raw.get("title"), "design": raw.get("design"),
                    "scenes": [r["scene_json"] for r in repo.list_scenes(spec["spec_id"])]}
    return ContentReviewLifecycle(repository=repo).verify(run_id, document, require_manifest=True)
