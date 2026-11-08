"""Freeze real legacy evidence without inventing a primary or copying an Attempt."""

from datetime import datetime, timezone

from app.core.security.errors import ErrorCode
from app.models.shared.persistence import canonical_hash
from app.services.feedback.round_assessment import resource_fingerprint
from app.services.feedback.round_learning import invalid
from app.services.feedback.round_plans import round_identity
from app.services.feedback.round_uow import RoundUnitOfWork


class LegacyRoundAdapter:
    def __init__(self, service):
        self.service = service

    def choose_correction(self, profile, selection):
        from app.models.feedback.rounds import RoundCorrectionSelectionV1
        from app.services.feedback.round_corrections import RoundCorrections

        service = self.service
        result = service.feedback.feedback_loop_repo.get_result(profile.learner_id, selection.attempt_id)
        if (result is None or result.attempt.metadata.get("round_context")
                or selection.resource_types is not None or selection.difficulty is not None
                or selection.learning_intent is None or selection.learning_intent.value != "reinforce_weakness"):
            raise invalid()
        allowed = service.feedback._correction_target_ids(result)
        try:
            _, selected = service.feedback.mastery_service.confirm_correction_targets(
                profile, selected_node_ids=selection.selected_skill_node_ids,
                snapshot_hash=selection.next_generation_snapshot_hash, allowed_target_ids=allowed)
        except ValueError as error:
            raise invalid() from error
        round_id = self.import_attempt(profile, selection.attempt_id)
        payload = RoundCorrectionSelectionV1(learner_id=profile.learner_id,
            targets=[{"node_id": node, "source_attempt_id": selection.attempt_id} for node in selected],
            selection_key=round_identity("legacy-selection", selection.model_dump(mode="json")))
        created = RoundCorrections(service).create(profile, round_id, payload)
        jobs = [run for member in created.members for run in member.job_ids]
        result = result.model_copy(update={"round_summary": service.detail(profile.learner_id, round_id).model_dump(mode="json"),
            "followup_run_ids": jobs, "followup_run_id": jobs[0], "followup_job_id": jobs[0]})
        return result, created

    def import_attempt(self, profile, attempt_id):
        service = self.service
        with RoundUnitOfWork(service.repository, service.feedback, service.learners) as uow:
            result = uow.feedback.feedback_loop_repo.get_result(profile.learner_id, attempt_id)
            if result is None or result.attempt.metadata.get("round_context"):
                raise invalid()
            existing = uow.rounds.one("learning_rounds", learner_id=profile.learner_id,
                                      protocol_version="legacy-correction/v1", source_attempt_id=attempt_id)
            if existing:
                return existing["round_id"]
            attempt = result.attempt
            nodes = service._nodes(profile, uow.feedback)
            points = sorted(attempt.knowledge_point_results, key=lambda point: point.knowledge_point_id)
            if not 1 <= len(points) <= 2 or any(point.knowledge_point_id not in nodes for point in points):
                raise invalid(ErrorCode.ROUND_LEGACY_UNAVAILABLE, 409)
            resource = uow.feedback.resource_repo.get(attempt.source_resource_id)
            job = uow.jobs.job_repo.get(attempt.source_run_id)
            if (resource is None or job is None or resource.publication_status != "published"
                    or resource.run_id != attempt.source_run_id or resource.learner_id != profile.learner_id
                    or job.learner_id != profile.learner_id or job.knowledge_base_id != profile.knowledge_base_id
                    or resource.version != attempt.source_resource_version):
                raise invalid(ErrorCode.ROUND_LEGACY_UNAVAILABLE, 409)
            traces = attempt.metadata.get("question_trace", [])
            if isinstance(traces, dict):
                traces = list(traces.values())
            if not isinstance(traces, list):
                raise invalid(ErrorCode.ROUND_LEGACY_UNAVAILABLE, 409)
            round_id = round_identity("legacy", profile.learner_id, attempt_id)
            stage_id = round_identity("stage", round_id, "initial")
            now = datetime.now(timezone.utc)
            budget = service.budget_snapshot()
            uow.rounds.insert("learning_rounds", dict(round_id=round_id, learner_id=profile.learner_id,
                knowledge_base_id=profile.knowledge_base_id, protocol_version="legacy-correction/v1",
                source_attempt_id=attempt_id, selection_key=round_id, selection_hash=canonical_hash(attempt_id),
                budget_snapshot=budget, created_at=now))
            uow.rounds.insert("learning_round_stages", dict(stage_id=stage_id, round_id=round_id, kind="initial",
                ordinal=0, selection_key=stage_id, selection_hash=canonical_hash(attempt_id), state="completed",
                budget_snapshot=budget, created_at=now, completed_at=now))
            groups, sources = [], []
            for point in points:
                node = nodes[point.knowledge_point_id]
                member_id = round_identity("rn", round_id, "legacy", node.node_id)
                node_traces = [trace for trace in traces if trace.get("skill_node_id") == node.node_id
                               and trace.get("question_id") in point.question_ids]
                if not node_traces or {trace["question_id"] for trace in node_traces} != set(point.question_ids):
                    raise invalid(ErrorCode.ROUND_LEGACY_UNAVAILABLE, 409)
                uow.rounds.insert("learning_round_nodes", dict(round_node_id=member_id, round_id=round_id,
                    skill_node_id=node.node_id, role="legacy", tier=node.tier, name=node.name))
                uow.rounds.insert("learning_round_stage_nodes", dict(stage_node_id=round_identity("sn", stage_id, member_id),
                    stage_id=stage_id, round_node_id=member_id, batch_id=None, request_snapshot={"source_run_id": job.run_id},
                    resource_types=[resource.resource_type], difficulty=resource.difficulty,
                    config_hash=canonical_hash(budget)))
                groups.append({"member_id": member_id, "node_id": node.node_id, "role": "legacy", "questions": node_traces})
                sources.append({"member_id": member_id, "node_id": node.node_id, "role": "legacy",
                    "anchor_resource_id": resource.resource_id, "anchor_run_id": resource.run_id,
                    "resources": [{"resource_id": resource.resource_id, "version": resource.version,
                                   "hash": resource_fingerprint(resource)}]})
                uow.rounds.insert("feedback_node_decisions", dict(node_decision_id=round_identity("nd", attempt_id, member_id),
                    attempt_id=attempt_id, round_node_id=member_id, score=point.score,
                    action=result.decision.action.value, reason=result.decision.decision_reason,
                    targets=[node.node_id], role="legacy", correction_eligible=point.score < 1,
                    error_summary={"score": point.score}, decision_hash=canonical_hash([attempt_id, node.node_id, point.score]),
                    created_at=now))
            manifest = {"groups": groups, "sources": sources, "round_id": round_id, "stage_id": stage_id,
                        "schema_version": "1.0", "legacy_import": True}
            uow.rounds.insert("learning_round_evaluation_sessions", dict(session_id=round_identity("session", stage_id),
                stage_id=stage_id, manifest_hash=canonical_hash(manifest), manifest=manifest, created_at=now,
                attempt_id=attempt_id, grading_state="submitted", submission_key=attempt.idempotency_key,
                submission_hash=attempt.request_hash))
        return round_id
