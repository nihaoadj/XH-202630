"""One formal submission, independently decided nodes and one atomic profile update."""

from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import uuid4

from app.agents.learning_agents.feedback_policy_agent import FeedbackPolicyDecision, build_mastery_mutations, decide_attempt
from app.core.llm.budget import round_call_scope
from app.core.security.errors import ErrorCode
from app.models.feedback.feedback_loop import (
    FeedbackAction, FeedbackDecision, LearningAttempt, ProfileVersionRecord,
    LearningPathNode, PathNodeStatus, PathNodeType,
)
from app.models.feedback.rounds import RoundAttemptProcessingV1, RoundFeedbackResultV1, RoundNodeFeedbackV1, RoundResultNotSubmittedV1
from app.models.shared.llm import LLMBudgetScope
from app.models.shared.persistence import canonical_hash
from app.services.feedback.learning_path_policy import mutate_learning_path
from app.services.feedback.round_assessment import RoundAssessment, resource_fingerprint
from app.services.feedback.round_budget import RoundBudgetGuard
from app.services.feedback.round_learning import invalid
from app.services.feedback.round_plans import round_identity
from app.services.feedback.round_uow import RoundUnitOfWork
from app.services.learners.remediation import update_need


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class RoundFeedback:
    def __init__(self, service):
        self.service = service

    def result(self, profile, round_id, stage_id):
        service = self.service
        service._round(profile.learner_id, round_id)
        stage = service.repository.one("learning_round_stages", stage_id=stage_id)
        if stage is None or stage["round_id"] != round_id:
            raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 404)
        session = service.repository.one("learning_round_evaluation_sessions", stage_id=stage_id)
        if not session or not session["attempt_id"]:
            # An abandoned owner cannot finish after its lease expires. Keep
            # the frozen submission intact so its caller can resume with the
            # same payload; only an active owner warrants continued polling.
            if (session and session["grading_state"] == "grading"
                    and session["grading_lease_expires_at"] is not None
                    and utc(session["grading_lease_expires_at"]) > datetime.now(timezone.utc)):
                return RoundAttemptProcessingV1(session_id=session["session_id"])
            return RoundResultNotSubmittedV1(round_id=round_id, stage_id=stage_id)
        stored = service.feedback.feedback_loop_repo.get_result(profile.learner_id, session["attempt_id"])
        rows = service.repository.find("feedback_node_decisions", attempt_id=stored.attempt.attempt_id)
        nodes = []
        for row in rows:
            member = service.repository.one("learning_round_nodes", round_node_id=row["round_node_id"])
            need = service.repository.one("learner_remediation_needs", learner_id=profile.learner_id,
                                          knowledge_base_id=profile.knowledge_base_id, skill_node_id=member["skill_node_id"])
            nodes.append(RoundNodeFeedbackV1(member_id=member["round_node_id"], node_id=member["skill_node_id"],
                                             role=member["role"], score=row["score"], action=row["action"], reason=row["reason"],
                                             correction_eligible=row["correction_eligible"], remediation_status=need["status"] if need else None,
                                             source_attempt_id=stored.attempt.attempt_id))
        return RoundFeedbackResultV1(round_id=round_id, stage_id=stage_id, session_id=session["session_id"],
                                      attempt_id=stored.attempt.attempt_id, profile_version=stored.profile_version,
                                      primary_path_action=stored.decision.action, nodes=nodes)

    def submit(self, profile, round_id, stage_id, payload):
        service = self.service
        service._round(profile.learner_id, round_id)
        if payload.learner_id != profile.learner_id:
            raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 404)
        submission_hash = canonical_hash(payload.model_dump(mode="json"))
        owner = uuid4().hex
        replay = False
        with service.repository.transaction() as tx:
            session = tx.one("learning_round_evaluation_sessions", session_id=payload.session_id)
            stage = tx.one("learning_round_stages", stage_id=stage_id)
            if not session or not stage or stage["round_id"] != round_id or session["stage_id"] != stage_id:
                raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 404)
            if session["attempt_id"]:
                if session["submission_key"] != payload.idempotency_key or session["submission_hash"] != submission_hash:
                    raise invalid(ErrorCode.ROUND_ATTEMPT_CONFLICT, 409)
                replay = True
            else:
                if session["grading_state"] == "grading":
                    if session["submission_key"] != payload.idempotency_key or session["submission_hash"] != submission_hash:
                        raise invalid(ErrorCode.ROUND_ATTEMPT_CONFLICT, 409)
                    if utc(session["grading_lease_expires_at"]) > datetime.now(timezone.utc):
                        return RoundAttemptProcessingV1(session_id=session["session_id"])
                expected_ids = {q["question_id"] for g in session["manifest"]["groups"] for q in g["questions"]}
                if payload.manifest_hash != session["manifest_hash"] or {a.question_id for a in payload.answers} != expected_ids:
                    raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID)
                session = tx.compare_and_set("learning_round_evaluation_sessions", session["session_id"], session["row_version"], {
                    "grading_state": "grading", "submission_key": payload.idempotency_key, "submission_hash": submission_hash,
                    "grading_owner": owner, "grading_generation": session["grading_generation"] + 1,
                    "grading_lease_expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
                })
        if replay:
            return self.result(profile, round_id, stage_id)
        stop = Event()

        def heartbeat():
            while not stop.wait(10):
                with service.repository.transaction() as tx:
                    row = tx.one("learning_round_evaluation_sessions", session_id=payload.session_id)
                    if row["grading_owner"] != owner or row["grading_state"] != "grading":
                        return
                    tx.compare_and_set("learning_round_evaluation_sessions", row["session_id"], row["row_version"], {
                        "grading_lease_expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
                    })

        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            budget = stage["budget_snapshot"]
            with round_call_scope(LLMBudgetScope(scope_id=session["session_id"], stage_id=stage_id, kind="assessment"),
                                  input_cap=budget["input_capacity"], guard=RoundBudgetGuard(service.repository)):
                prepared, anchor = RoundAssessment(service).prepare(profile, session, payload)
            stop.set()
            thread.join()
            self._commit(profile, round_id, stage_id, session, prepared, anchor, owner, submission_hash)
        except BaseException:
            stop.set()
            thread.join()
            with service.repository.transaction() as tx:
                row = tx.one("learning_round_evaluation_sessions", session_id=payload.session_id)
                if row and row["grading_owner"] == owner and row["grading_state"] == "grading":
                    tx.compare_and_set("learning_round_evaluation_sessions", row["session_id"], row["row_version"], {
                        "grading_state": "idle", "grading_owner": None, "grading_lease_expires_at": None,
                    })
            raise
        return self.result(profile, round_id, stage_id)

    def _commit(self, profile, round_id, stage_id, session, prepared, anchor, owner, submission_hash):
        service = self.service
        with RoundUnitOfWork(service.repository, service.feedback, service.learners) as uow:
            current = uow.learners.get(profile.learner_id)
            row = uow.rounds.one("learning_round_evaluation_sessions", session_id=session["session_id"])
            if row["grading_owner"] != owner or row["grading_generation"] != session["grading_generation"] or row["attempt_id"]:
                raise invalid(ErrorCode.ROUND_ATTEMPT_CONFLICT, 409)
            if utc(row["grading_lease_expires_at"]) <= datetime.now(timezone.utc) or row["manifest_hash"] != session["manifest_hash"]:
                raise invalid(ErrorCode.ROUND_ATTEMPT_CONFLICT, 409)
            for source in row["manifest"]["sources"]:
                for frozen in source["resources"]:
                    resource = uow.feedback.resource_repo.get(frozen["resource_id"])
                    if resource is None or resource_fingerprint(resource) != frozen["hash"]:
                        raise invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
            if current is None or current.learner_id != prepared.learner_id or current.knowledge_base_id != profile.knowledge_base_id:
                raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 404)
            if current.profile_version != prepared.expected_profile_version:
                raise invalid(ErrorCode.LEARNER_PROFILE_VERSION_CONFLICT, 409)
            attempt_id = round_identity("att", current.learner_id, prepared.idempotency_key)
            attempt = LearningAttempt(attempt_id=attempt_id, request_hash=canonical_hash(prepared.model_dump(mode="json")),
                                      **prepared.model_dump())
            point_ids = [point.knowledge_point_id for point in attempt.knowledge_point_results]
            context = uow.feedback.feedback_loop_repo.get_context(current.learner_id, point_ids)
            roles = {group["node_id"]: group for group in session["manifest"]["groups"]}
            policies = {}
            for point in attempt.knowledge_point_results:
                projection = attempt.model_copy(update={"knowledge_point_results": [point], "overall_score": point.score})
                policies[point.knowledge_point_id] = decide_attempt(projection, context)
            primary = next((node for node in point_ids if roles[node]["role"] == "primary"), None)
            newest = sorted((item for item in uow.rounds.find("learning_rounds", learner_id=current.learner_id)
                             if item["protocol_version"] == "learning-round/v1"),
                            key=lambda item: (item["created_at"], item["round_id"]), reverse=True)
            active = bool(newest and newest[0]["round_id"] == round_id)
            # Bind to the selected primary's path identity, not whichever
            # older core node happens to be in progress.
            selected_path_id = None
            if primary and active and context.learning_path is not None:
                path = context.learning_path.model_copy(deep=True)
                selected = next((node for node in path.nodes if node.knowledge_point_id == primary
                                 and node.node_type == PathNodeType.CORE), None)
                if selected is None:
                    selected = LearningPathNode(node_id=round_identity("path-node", path.path_id, primary),
                        path_id=path.path_id, knowledge_point_id=primary, node_type=PathNodeType.CORE,
                        sequence=max((node.sequence for node in path.nodes), default=0)+1,
                        status=PathNodeStatus.IN_PROGRESS, source="feedback")
                    path.nodes.append(selected)
                selected_path_id = selected.node_id
                context = context.model_copy(update={"learning_path": path})
            attempt = attempt.model_copy(update={"path_node_id": selected_path_id})
            policy = policies[primary] if primary and active else FeedbackPolicyDecision(
                FeedbackAction.HOLD, ("round_review_or_historical",), (), "仅更新本次节点证据，保持当前主路径。", False,
            )
            decision_id = round_identity("decision", attempt_id)
            decision_data = dict(decision_id=decision_id, learner_id=current.learner_id, attempt_id=attempt_id,
                                 action=policy.action, reason_codes=list(policy.reason_codes), decision_reason=policy.decision_reason,
                                 target_knowledge_point_ids=list(policy.target_knowledge_point_ids))
            decision = FeedbackDecision(**decision_data, decision_hash=canonical_hash(decision_data))
            eligibility = uow.feedback.mastery_service.assessment_eligibility(current, point_ids=point_ids, metadata=attempt.metadata)
            dimensions = uow.feedback.mastery_service.assessment_dimension_ready(current, point_ids=point_ids, metadata=attempt.metadata)
            mutations = build_mastery_mutations(attempt, context, evidence_eligibility=eligibility, dimension_ready=dimensions)
            path_attempt = attempt.model_copy(update={"knowledge_point_results": [point for point in attempt.knowledge_point_results
                                                                                    if point.knowledge_point_id == primary]}) if primary else attempt
            path, path_mutation = mutate_learning_path(attempt=path_attempt, decision_id=decision_id, policy=policy,
                                                       existing=context.learning_path,
                                                       advance_knowledge_point_id=uow.feedback._next_path_node_id(current, [primary], context.learning_path)
                                                       if primary and policy.action == FeedbackAction.ADVANCE else None)
            version = context.profile_version + 1
            patch = uow.feedback._profile_patch(current, attempt, decision, mutations)
            version_record = ProfileVersionRecord(learner_id=current.learner_id, profile_version=version,
                                                   source_attempt_id=attempt_id, source_decision_id=decision_id,
                                                   change_summary={"round_id": round_id, "stage_id": stage_id, "knowledge_point_ids": point_ids})
            result = uow.feedback.feedback_loop_repo.apply_feedback(attempt=attempt, decision=decision,
                state_mutations=mutations, learning_path=path, path_mutation=path_mutation,
                profile_version=version_record, profile_patch=patch)
            uow.feedback._apply_profile_copy(current, patch, mutations, version)
            for point in attempt.knowledge_point_results:
                node = point.knowledge_point_id
                group = roles[node]
                node_policy = policies[node]
                values = dict(node_decision_id=round_identity("nd", attempt_id, group["member_id"]), attempt_id=attempt_id,
                              round_node_id=group["member_id"], score=point.score, action=node_policy.action.value,
                              reason=node_policy.decision_reason, targets=list(node_policy.target_knowledge_point_ids), role=group["role"],
                              correction_eligible=point.score < 1, error_summary={"score": point.score},
                              decision_hash=canonical_hash([attempt_id, node, point.score]), created_at=datetime.now(timezone.utc))
                uow.rounds.insert("feedback_node_decisions", values)
                update_need(uow.rounds, current.learner_id, current.knowledge_base_id, node, attempt_id, point.score, eligibility.get(node, False))
            uow.feedback.mastery_service.record_curriculum_verification(current, attempt_id=attempt_id,
                point_scores={point.knowledge_point_id: point.score for point in attempt.knowledge_point_results}, occurred_at=attempt.submitted_at)
            # Non-primary evidence can invalidate a real prerequisite, but it
            # must never promote/downgrade the active tier or replace the path.
            uow.feedback.mastery_service.require_feedback_prerequisites(current, point_scores={
                point.knowledge_point_id: point.score for point in attempt.knowledge_point_results
                if point.knowledge_point_id != primary or not active
            })
            if primary and active:
                uow.feedback.mastery_service.apply_tier_feedback(current, point_scores={primary: next(p.score for p in attempt.knowledge_point_results if p.knowledge_point_id == primary)})
            # Re-read after bound repository commits/flushes, preserving budget
            # and heartbeat changes to the session row version.
            row = uow.rounds.one("learning_round_evaluation_sessions", session_id=session["session_id"])
            uow.rounds.compare_and_set("learning_round_evaluation_sessions", row["session_id"], row["row_version"], {
                "attempt_id": attempt_id, "grading_state": "submitted", "grading_owner": None, "grading_lease_expires_at": None,
                "submission_hash": submission_hash,
            })
            stage = uow.rounds.one("learning_round_stages", stage_id=stage_id)
            uow.rounds.compare_and_set("learning_round_stages", stage_id, stage["row_version"], {"state": "completed", "completed_at": datetime.now(timezone.utc)})
            uow.feedback._record_feedback_events(result)
