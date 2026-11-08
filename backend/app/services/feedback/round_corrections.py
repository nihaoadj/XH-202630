"""One correction stage can independently produce both current round members."""

from datetime import datetime, timezone

from app.core.security.errors import ErrorCode
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_learning import invalid
from app.services.feedback.round_plans import plan_member, round_identity
from app.services.feedback.round_uow import RoundUnitOfWork


class RoundCorrections:
    def __init__(self, service):
        self.service = service

    def create(self, profile, round_id, payload):
        service = self.service
        service._round(profile.learner_id, round_id)
        targets = sorted((target.model_dump() for target in payload.targets), key=lambda target: target["node_id"])
        selection_hash = canonical_hash({"targets": targets, "include_claim_check": payload.include_claim_check,
                                          "include_claim_evidence_retrieval": payload.include_claim_evidence_retrieval})
        stage_id = round_identity("stage", round_id, "correction", targets)
        with RoundUnitOfWork(service.repository, service.feedback, service.learners) as uow:
            parent = service._round(profile.learner_id, round_id, uow.rounds)
            existing = uow.rounds.one("learning_round_stages", round_id=round_id, selection_key=payload.selection_key)
            if existing:
                if existing["selection_hash"] != selection_hash:
                    raise invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
                return service.creation_response(profile.learner_id, round_id, existing["stage_id"], uow.rounds)
            nodes = service._nodes(profile, uow.feedback)
            members = {row["skill_node_id"]: row for row in uow.rounds.find("learning_round_nodes", round_id=round_id)}
            plans, sources = [], {}
            for target in targets:
                member = members.get(target["node_id"])
                if member is None or target["node_id"] not in nodes:
                    raise invalid()
                decisions = uow.rounds.find("feedback_node_decisions", round_node_id=member["round_node_id"])
                decisions.sort(key=lambda row: (row["created_at"], row["node_decision_id"]))
                if not decisions or decisions[-1]["attempt_id"] != target["source_attempt_id"] or not decisions[-1]["correction_eligible"]:
                    raise invalid()
                prior = uow.rounds.find("learning_round_stage_nodes", round_node_id=member["round_node_id"])
                if any(row["source_attempt_id"] == target["source_attempt_id"] for row in prior):
                    raise invalid(ErrorCode.ROUND_SELECTION_CONFLICT, 409)
                if sum(row["source_attempt_id"] is not None for row in prior) >= parent["budget_snapshot"]["L"]:
                    raise invalid(ErrorCode.ROUND_CORRECTION_BUDGET_EXHAUSTED, 409)
                result = uow.feedback.feedback_loop_repo.get_result(profile.learner_id, target["source_attempt_id"])
                if result is None:
                    raise invalid()
                options = uow.feedback.mastery_service.next_generation_options(profile)
                focus = uow.feedback._correction_focus_snapshot(profile, result, options, [target["node_id"]],
                                                                 {1: "初级", 2: "中级", 3: "高级"}[nodes[target["node_id"]].tier])
                plan = plan_member(round_id=round_id, stage_id=stage_id, learner_id=profile.learner_id,
                                   knowledge_base_id=profile.knowledge_base_id, node=nodes[target["node_id"]], role=member["role"],
                                   primary_resource_types=[], include_claim_check=payload.include_claim_check,
                                   include_claim_evidence_retrieval=payload.include_claim_evidence_retrieval,
                                   correction_focus=focus)
                # Imported legacy member IDs must retain their trusted identity.
                if plan.member_id != member["round_node_id"]:
                    raise invalid()
                plans.append(plan)
                sources[target["node_id"]] = target["source_attempt_id"]
            stages = uow.rounds.find("learning_round_stages", round_id=round_id)
            service.persist_stage(uow, profile, stage_id, round_id, plans, payload.selection_key, selection_hash,
                                  parent["budget_snapshot"], datetime.now(timezone.utc),
                                  ordinal=max(row["ordinal"] for row in stages) + 1, sources=sources)
        return service.creation_response(profile.learner_id, round_id, stage_id)
