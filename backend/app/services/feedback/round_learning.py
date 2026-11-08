"""Learning-round creation and read facade; each member owns its production."""

from datetime import datetime, timezone

from app.core.security.errors import ApplicationError, ErrorCode
from app.db.feedback.round_base import RoundConflict
from app.models.feedback.rounds import (
    LearningRoundDetailV1, LearningRoundListV1, LearningRoundSummaryV1, RoundCandidatesV1,
    RoundCreationResponseV1, RoundMemberJobsV1, RoundMemberSummaryV1, RoundStageSummaryV1,
)
from app.models.learners.mastery import NextGenerationCandidateV1
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_plans import plan_member, round_identity
from app.services.feedback.round_uow import RoundUnitOfWork
from app.services.learners.remediation import advance_wait, ranked_needs
from app.services.learners.review_eligibility import eligible_review_ids


def invalid(code=ErrorCode.ROUND_SELECTION_INVALID, status=422):
    return ApplicationError(code, status_code=status)


class RoundLearningService:
    def __init__(self, repository, feedback_service, learner_repository, settings):
        self.repository = repository
        self.feedback = feedback_service
        self.learners = learner_repository
        self.settings = settings

    def learner_id_for_round(self, identity):
        row = self.repository.one("learning_rounds", round_id=identity)
        if row is None:
            raise invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
        return row["learner_id"]

    def _round(self, learner_id, identity, repository=None):
        row = (repository or self.repository).one("learning_rounds", round_id=identity)
        if row is None or row["learner_id"] != learner_id:
            raise invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
        return row

    def _nodes(self, profile, feedback=None):
        return {node.node_id: node for node in (feedback or self.feedback).mastery_service.knowledge_service.list_skill_nodes(profile.knowledge_base_id)}

    def create(self, profile, payload):
        if not self.settings.learning_round_creation_enabled:
            raise invalid(ErrorCode.ROUND_CREATION_DISABLED, 409)
        ids = payload.target_skill_nodes
        if not ids:
            ids = self.feedback.generation_job_service._initial_generation_target(profile)
        if not ids:
            ids = self.feedback.mastery_service.next_generation_options(profile).recommended_node_ids[:1]
        if len(ids or []) != 1:
            raise invalid(ErrorCode.GENERATION_TARGET_INVALID)
        self.feedback.mastery_service.validate_generation_targets(profile, ids)
        return self._create_round(profile, payload.selection_key, payload.model_dump(mode="json"),
                                  ids[0], payload.resource_types, payload.include_claim_check,
                                  include_claim_evidence_retrieval=payload.include_claim_evidence_retrieval)

    def next(self, profile, payload):
        if not self.settings.learning_round_creation_enabled:
            raise invalid(ErrorCode.ROUND_CREATION_DISABLED, 409)
        source = self.feedback.feedback_loop_repo.get_attempt(profile.learner_id, payload.source_attempt_id)
        if source is None:
            raise invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
        intent = payload.primary_learning_intent
        if intent.value == "learn_new_and_reinforce":
            raise invalid()
        try:
            self.feedback.mastery_service.confirm_next_generation_intent(
                profile, intent=intent, selected_node_ids=[payload.primary_node_id],
                downgrade_source_node_ids=[point.knowledge_point_id for point in source.knowledge_point_results],
            )
        except ValueError as error:
            raise invalid() from error
        qualified = eligible_review_ids(profile, self.feedback.resource_repo,
                                        self.feedback.feedback_loop_repo, self.feedback.generation_job_service.job_repo)
        if payload.review_node_id and payload.review_node_id not in qualified:
            raise invalid()
        context = source.metadata.get("round_context", {})
        return self._create_round(profile, payload.selection_key, payload.model_dump(mode="json"),
                                  payload.primary_node_id, payload.primary_resource_types, payload.include_claim_check,
                                  review_node_id=payload.review_node_id, source_attempt_id=source.attempt_id,
                                  parent_round_id=context.get("round_id"), intent=intent,
                                  include_claim_evidence_retrieval=payload.include_claim_evidence_retrieval)

    def _create_round(self, profile, key, selection, primary_node_id, resource_types, claim,
                      review_node_id=None, source_attempt_id=None, parent_round_id=None, intent=None,
                      include_claim_evidence_retrieval=False):
        request_hash = canonical_hash(selection)
        round_id = round_identity("round", profile.learner_id, key)
        stage_id = round_identity("stage", round_id, "initial")
        try:
            with RoundUnitOfWork(self.repository, self.feedback, self.learners) as uow:
                existing = uow.rounds.one("learning_rounds", learner_id=profile.learner_id, selection_key=key)
                if existing:
                    if existing["selection_hash"] != request_hash:
                        raise invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
                    return self.creation_response(profile.learner_id, existing["round_id"], stage_id, uow.rounds)
                current = uow.learners.get(profile.learner_id)
                nodes = self._nodes(current, uow.feedback)
                if primary_node_id not in nodes or (review_node_id and (review_node_id not in nodes or review_node_id == primary_node_id)):
                    raise invalid()
                if review_node_id and review_node_id not in eligible_review_ids(
                    current, uow.feedback.resource_repo, uow.feedback.feedback_loop_repo, uow.jobs.job_repo,
                ):
                    raise invalid()
                if intent is None:
                    uow.feedback.mastery_service.validate_generation_targets(current, [primary_node_id])
                else:
                    uow.feedback.mastery_service.confirm_next_generation_intent(
                        current, intent=intent, selected_node_ids=[primary_node_id],
                        downgrade_source_node_ids=[point.knowledge_point_id for point in uow.feedback.feedback_loop_repo.get_attempt(
                            current.learner_id, source_attempt_id).knowledge_point_results],
                    )
                budget = self.budget_snapshot()
                now = datetime.now(timezone.utc)
                uow.rounds.insert("learning_rounds", dict(
                    round_id=round_id, learner_id=current.learner_id, knowledge_base_id=current.knowledge_base_id,
                    learning_direction_id=getattr(current.learning_preferences, "metadata", {}).get("onboarding", {}).get("learning_direction_id"), protocol_version="learning-round/v1",
                    source_attempt_id=source_attempt_id, parent_round_id=parent_round_id, selection_key=key,
                    selection_hash=request_hash, budget_snapshot=budget, created_at=now,
                ))
                plans = [plan_member(round_id=round_id, stage_id=stage_id, learner_id=current.learner_id,
                                     knowledge_base_id=current.knowledge_base_id, node=nodes[primary_node_id], role="primary",
                                     primary_resource_types=resource_types, include_claim_check=claim,
                                     include_claim_evidence_retrieval=include_claim_evidence_retrieval)]
                if review_node_id:
                    plans.append(plan_member(round_id=round_id, stage_id=stage_id, learner_id=current.learner_id,
                                             knowledge_base_id=current.knowledge_base_id, node=nodes[review_node_id], role="review",
                                             primary_resource_types=[], include_claim_check=claim,
                                             include_claim_evidence_retrieval=include_claim_evidence_retrieval))
                for plan in plans:
                    uow.rounds.insert("learning_round_nodes", dict(
                        round_node_id=plan.member_id, round_id=round_id, skill_node_id=plan.node_id,
                        role=plan.role, tier=plan.tier, name=plan.name,
                    ))
                self.persist_stage(uow, current, stage_id, round_id, plans, key, request_hash, budget, now)
                advance_wait(uow.rounds, current.learner_id, current.knowledge_base_id, primary_node_id)
                # Curriculum scheduling happens once for the primary, never once
                # per Claim-split task or per review node.
                first_run = round_identity("run", plans[0].stage_node_id, 0)
                if uow.feedback.mastery_service.curriculum_repo is not None:
                    selection_type = ("lower_tier_selection" if intent and intent.value == "downgrade_learning" else "same_tier")
                    uow.feedback.mastery_service.schedule_generation(
                        current, run_id=first_run, selected_node_ids=[primary_node_id], selection_type=selection_type,
                    )
        except (RoundConflict, ValueError) as error:
            raise invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409) from error
        return self.creation_response(profile.learner_id, round_id, stage_id)

    def budget_snapshot(self):
        return {"L": self.settings.learning_round_correction_stage_limit,
                "H": self.settings.learning_round_resource_recovery_limit,
                "resource_tokens": self.settings.learning_round_resource_token_limit,
                "workflow_seconds": self.settings.llm_workflow_timeout_seconds,
                "input_capacity": self.settings.llm_resource_generator_max_input_tokens}

    def persist_stage(self, uow, profile, stage_id, round_id, plans, key, request_hash, budget, now,
                      ordinal=0, sources=None):
        session_id = round_identity("session", stage_id)
        scopes = {plan.stage_node_id: len(plan.resource_types) * budget["resource_tokens"] for plan in plans}
        scopes[session_id] = len(plans) * 262144
        runtime_scopes = {plan.stage_node_id: len(plan.resource_types) * (1 + budget["H"]) * budget["workflow_seconds"] for plan in plans}
        runtime_scopes[session_id] = len(plans) * budget["workflow_seconds"]
        stage_budget = {**budget, "scopes": scopes, "runtime_scopes": runtime_scopes}
        uow.rounds.insert("learning_round_stages", dict(
            stage_id=stage_id, round_id=round_id, kind="initial" if ordinal == 0 else "correction",
            ordinal=ordinal, selection_key=key, selection_hash=request_hash,
            state="producing", budget_snapshot=stage_budget, created_at=now,
        ))
        for plan in plans:
            uow.rounds.insert("learning_round_stage_nodes", dict(
                stage_node_id=plan.stage_node_id, stage_id=stage_id, round_node_id=plan.member_id,
                source_attempt_id=(sources or {}).get(plan.node_id), batch_id=plan.batch_id,
                request_snapshot={"requests": [request.model_dump(mode="json") for request in plan.requests]},
                resource_types=list(plan.resource_types), difficulty=plan.difficulty, config_hash=canonical_hash(stage_budget),
            ))
            for index, request in enumerate(plan.requests):
                run_id = round_identity("run", plan.stage_node_id, index)
                uow.jobs.create_round_job(profile, request, uow.rounds, plan.stage_node_id, run_id=run_id)
                uow.rounds.insert("learning_round_job_bindings", dict(
                    run_id=run_id, stage_node_id=plan.stage_node_id, relation_kind="production", created_at=now,
                ))

    def stage_resources(self, stage_node, repository=None):
        repository = repository or self.repository
        bindings = repository.find("learning_round_job_bindings", stage_node_id=stage_node["stage_node_id"])
        resources = []
        for binding in bindings:
            resources.extend(self.feedback.resource_repo.list_by_run(binding["run_id"]))
        return [item for item in resources if item.publication_status == "published"]

    def member_jobs(self, stage_node, repository=None):
        repository = repository or self.repository
        member = repository.one("learning_round_nodes", round_node_id=stage_node["round_node_id"])
        stage = repository.one("learning_round_stages", stage_id=stage_node["stage_id"])
        bindings = repository.find("learning_round_job_bindings", stage_node_id=stage_node["stage_node_id"])
        jobs = {row["run_id"]: self.feedback.generation_job_service.job_repo.get(row["run_id"]) for row in bindings}
        resources = self.stage_resources(stage_node, repository)
        published = {resource.resource_type for resource in resources}
        missing = set(stage_node["resource_types"]) - published
        requested = {run_id: set(job.request_payload.get("resource_types", stage_node["resource_types"]))
                     if job is not None else set(stage_node["resource_types"]) for run_id, job in jobs.items()}
        replaced_types = {}
        for row in bindings:
            if row["relation_kind"] == "retry":
                replaced_types.setdefault(row["source_run_id"], set()).update(requested[row["run_id"]])
        # A retry replaces only its requested types, not every responsibility
        # of a partially failed source. Published types need no further work.
        effective = {run_id: (types & missing) - replaced_types.get(run_id, set())
                     for run_id, types in requested.items()}
        running_types = set().union(*(effective[run_id] for run_id, job in jobs.items()
                                      if job is not None and job.job_status in {"queued", "running"}))
        failed = sum(bool(effective[run_id] - running_types) for run_id, job in jobs.items()
                     if job is None or job.job_status == "failed")
        # Continue polling while any missing type is being recovered, even if
        # another type still has an unresolved failure (shown in the count).
        state = ("completed" if stage["state"] == "completed" else
                 "awaiting_assessment" if not missing else "producing" if running_types else
                 "failed" if failed else "producing")
        return RoundMemberJobsV1(member_id=member["round_node_id"], node_id=member["skill_node_id"], role=member["role"],
                                 stage_node_id=stage_node["stage_node_id"], batch_id=stage_node["batch_id"],
                                 job_ids=[row["run_id"] for row in bindings], resource_types=stage_node["resource_types"],
                                 difficulty=stage_node["difficulty"], resource_ids=[item.resource_id for item in resources],
                                 state=state, failed_job_count=failed)

    def creation_response(self, learner_id, round_id, stage_id, repository=None):
        repository = repository or self.repository
        self._round(learner_id, round_id, repository)
        stage = repository.one("learning_round_stages", stage_id=stage_id)
        if stage is None or stage["round_id"] != round_id:
            raise invalid(ErrorCode.ROUND_SELECTION_INVALID, 404)
        members = [self.member_jobs(row, repository) for row in repository.find("learning_round_stage_nodes", stage_id=stage_id)]
        members.sort(key=lambda row: (row.role != "primary", row.node_id))
        # The round keeps its frozen primary even when this stage only
        # re-tests the review member; a normal round response must never
        # report "no primary" just because the stage has no primary task.
        round_primary = next((row for row in repository.find("learning_round_nodes", round_id=round_id)
                              if row["role"] == "primary"), None)
        staged_primary = next((row for row in members if row.role == "primary"), None)
        return RoundCreationResponseV1(
            round_id=round_id, stage_id=stage_id,
            primary_node_id=round_primary["skill_node_id"] if round_primary else None, members=members,
            state=stage["state"],
            # A default run only exists when this stage really produced the
            # primary; otherwise the caller must switch by member/stage.
            primary_default_run_id=(staged_primary.job_ids[0]
                                    if staged_primary and staged_primary.job_ids else None),
        )

    def detail(self, learner_id, round_id):
        row = self._round(learner_id, round_id)
        stages = sorted(self.repository.find("learning_round_stages", round_id=round_id), key=lambda item: item["ordinal"])
        stage_summaries = []
        latest = {}
        for stage in stages:
            members = [self.member_jobs(item) for item in self.repository.find("learning_round_stage_nodes", stage_id=stage["stage_id"])]
            stage_summaries.append(RoundStageSummaryV1(stage_id=stage["stage_id"], kind=stage["kind"],
                                                       ordinal=stage["ordinal"], state=stage["state"], members=members))
            latest.update({member.member_id: member for member in members})
        summaries = []
        for member in self.repository.find("learning_round_nodes", round_id=round_id):
            state = latest.get(member["round_node_id"])
            need = self.repository.one("learner_remediation_needs", learner_id=learner_id,
                                       knowledge_base_id=row["knowledge_base_id"], skill_node_id=member["skill_node_id"])
            summaries.append(RoundMemberSummaryV1(member_id=member["round_node_id"], node_id=member["skill_node_id"],
                                                  role=member["role"], node_name=member["name"], tier=member["tier"],
                                                  state=state.state if state else "completed", failed_job_count=state.failed_job_count if state else 0,
                                                  resource_ids=state.resource_ids if state else [], remediation_status=need["status"] if need else None))
        return LearningRoundDetailV1(round_id=round_id, protocol_version=row["protocol_version"], created_at=row["created_at"],
                                      learner_id=learner_id, members=summaries, stages=stage_summaries,
                                      available_actions=["evaluate", "correct", "next", "retry"] + (["append_primary"] if any(m.role == "primary" for m in summaries) else []))

    def list(self, learner_id, offset=0, limit=20):
        rows, total = self.repository.list_rounds(learner_id, offset, limit)
        return LearningRoundListV1(learner_id=learner_id, offset=offset, limit=limit, total=total, items=[
            LearningRoundSummaryV1(**{key: value for key, value in self.detail(learner_id, row["round_id"]).model_dump().items()
                                      if key in LearningRoundSummaryV1.model_fields}) for row in rows
        ])

    def candidates(self, profile, round_id):
        self._round(profile.learner_id, round_id)
        nodes = self._nodes(profile)
        eligible = eligible_review_ids(profile, self.feedback.resource_repo, self.feedback.feedback_loop_repo,
                                       self.feedback.generation_job_service.job_repo)
        review = [NextGenerationCandidateV1(skill_node_id=node.node_id, name=node.name, priority_group="learned",
                                             rank=index+1, reason_codes=["FORMAL_LEARNING_ASSESSED"], confidence="none",
                                             tier=node.tier, tier_label=str(node.tier), prerequisite_ids=node.prerequisites)
                  for index, node in enumerate(sorted((nodes[key] for key in eligible if key in nodes), key=lambda n: n.node_id))]
        targets = []
        for member in self.repository.find("learning_round_nodes", round_id=round_id):
            decisions = self.repository.find("feedback_node_decisions", round_node_id=member["round_node_id"])
            decisions.sort(key=lambda d: (d["created_at"], d["node_decision_id"]))
            if decisions and decisions[-1]["correction_eligible"] and not self.repository.find(
                "learning_round_stage_nodes", round_node_id=member["round_node_id"], source_attempt_id=decisions[-1]["attempt_id"],
            ):
                targets.append({"node_id": member["skill_node_id"], "source_attempt_id": decisions[-1]["attempt_id"]})
        options = self.feedback.mastery_service.next_generation_options(profile)
        needs = ranked_needs(self.repository.find("learner_remediation_needs", learner_id=profile.learner_id,
                                                  knowledge_base_id=profile.knowledge_base_id))
        priority = {need["skill_node_id"]: index for index, need in enumerate(needs)}
        reinforced = sorted(options.reinforce_weakness,
                            key=lambda item: (priority.get(item.skill_node_id, len(priority)), item.rank, item.skill_node_id))
        reinforced = [item.model_copy(update={"rank": index+1}) for index, item in enumerate(reinforced)]
        preferred = [item.skill_node_id for item in reinforced if item.skill_node_id in priority
                     and item.eligibility_status == "available"]
        options = options.model_copy(update={"reinforce_weakness": reinforced,
                                              **({"recommended_node_ids": preferred[:1]} if preferred else {})})
        return RoundCandidatesV1(generation_options=options,
                                  eligible_review_nodes=review, correction_targets=targets, profile_version=profile.profile_version)
