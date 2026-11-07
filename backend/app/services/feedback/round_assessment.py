"""Freeze stage-specific node question groups and prepare scores outside write locks."""

from copy import deepcopy
from datetime import datetime, timezone

from app.core.security.errors import ErrorCode
from app.models.feedback.rounds import RoundEvaluationSessionV1
from app.models.learning_documents.schemas import ResourceEvaluationQuestion, RunAttemptSubmitRequest
from app.models.shared.persistence import canonical_hash
from app.services.feedback import attempt_evidence
from app.services.feedback.round_learning import invalid
from app.services.feedback.round_plans import round_identity


def resource_fingerprint(resource):
    return canonical_hash({"resource_id": resource.resource_id, "version": resource.version,
                           "content": resource.content_text, "assessment": resource.assessment_payload,
                           "publication": resource.publication_status})


class RoundAssessment:
    def __init__(self, service):
        self.service = service

    def session(self, profile, round_id, stage_id):
        service = self.service
        service._round(profile.learner_id, round_id)
        with service.repository.transaction() as tx:
            stage = tx.one("learning_round_stages", stage_id=stage_id)
            if not stage or stage["round_id"] != round_id:
                raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 404)
            saved = tx.one("learning_round_evaluation_sessions", stage_id=stage_id)
            if saved:
                if saved["manifest"].get("legacy_import"):
                    raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID, 409)
                return self.public_session(saved)
            session_id = round_identity("session", stage_id)
            groups, sources, answer_key = [], [], {}
            original_questions = {}
            stage_nodes = tx.find("learning_round_stage_nodes", stage_id=stage_id)
            for stage_node in stage_nodes:
                member = tx.one("learning_round_nodes", round_node_id=stage_node["round_node_id"])
                resources = sorted(service.stage_resources(stage_node, tx), key=lambda r: (r.resource_id, r.version))
                if not resources or not set(stage_node["resource_types"]) <= {r.resource_type for r in resources}:
                    raise invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
                if stage["kind"] == "correction" and not any(
                    resource.resource_type == "分阶测试题" and resource.assessment_payload is not None for resource in resources
                ):
                    raise invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
                questions, keys = service.feedback._build_run_question_specs(
                    profile, resources, service.feedback.mastery_service.knowledge_service,
                )
                questions = [question for question in questions if question.skill_node_id == member["skill_node_id"]]
                if not questions or (stage["kind"] == "correction" and len(questions) != 6):
                    raise invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
                group_questions = []
                anchor = resources[0]
                for question in questions:
                    source = next((resource for resource in resources if question.question_id.startswith(resource.resource_id + ":")
                                   or (resource.assessment_payload and any(
                                       row["question_id"] == question.question_id
                                       for row in service.feedback._structured_assessment_questions(resource)))), anchor)
                    identity = round_identity("rq", session_id, stage_node["stage_node_id"], source.resource_id,
                                              source.version, question.question_id)
                    group_questions.append(question.model_copy(update={"question_id": identity}).model_dump(mode="json"))
                    answer_key[identity] = deepcopy(keys[question.question_id])
                    original_questions[identity] = {"source_question_id": question.question_id, "resource_id": source.resource_id,
                                                    "resource_version": source.version, "source_hash": resource_fingerprint(source)}
                groups.append({"member_id": member["round_node_id"], "node_id": member["skill_node_id"],
                               "role": member["role"], "questions": group_questions})
                sources.append({"member_id": member["round_node_id"], "node_id": member["skill_node_id"],
                                "role": member["role"], "resources": [{"resource_id": r.resource_id, "version": r.version,
                                    "hash": resource_fingerprint(r)} for r in resources],
                                "anchor_resource_id": anchor.resource_id, "anchor_run_id": anchor.run_id})
            groups.sort(key=lambda group: (group["role"] != "primary", group["node_id"]))
            sources.sort(key=lambda source: (source["role"] != "primary", source["node_id"]))
            manifest = {"groups": groups, "sources": sources, "answer_key": answer_key,
                        "round_id": round_id, "stage_id": stage_id, "schema_version": "1.0",
                        "original_questions": original_questions}
            manifest_hash = canonical_hash(manifest)
            row = tx.insert("learning_round_evaluation_sessions", dict(
                session_id=session_id, stage_id=stage_id, manifest_hash=manifest_hash, manifest=manifest,
                created_at=datetime.now(timezone.utc),
            ))
            tx.compare_and_set("learning_round_stages", stage_id, stage["row_version"], {"state": "awaiting_assessment"})
            public = self.public_session(row)
            public.require_members({item["round_node_id"] for item in stage_nodes})
            return public

    @staticmethod
    def public_session(row):
        manifest = row["manifest"]
        return RoundEvaluationSessionV1(session_id=row["session_id"], round_id=manifest["round_id"],
                                        stage_id=row["stage_id"], manifest_hash=row["manifest_hash"], groups=manifest["groups"])

    def prepare(self, profile, session, payload):
        manifest = session["manifest"]
        expected = {question["question_id"] for group in manifest["groups"] for question in group["questions"]}
        if payload.manifest_hash != session["manifest_hash"] or {answer.question_id for answer in payload.answers} != expected:
            raise invalid(ErrorCode.ROUND_ASSESSMENT_INVALID)
        sources = manifest["sources"]
        for source in sources:
            for snapshot in source["resources"]:
                resource = self.service.feedback.resource_repo.get(snapshot["resource_id"])
                if resource is None or resource.version != snapshot["version"] or resource_fingerprint(resource) != snapshot["hash"]:
                    raise invalid(ErrorCode.ROUND_STAGE_NOT_READY, 409)
        anchor = self.service.feedback.resource_repo.get(sources[0]["anchor_resource_id"])
        questions = [ResourceEvaluationQuestion.model_validate(question) for group in manifest["groups"] for question in group["questions"]]
        run_payload = RunAttemptSubmitRequest(
            learner_id=profile.learner_id, run_id=anchor.run_id, source_resource_id=anchor.resource_id,
            idempotency_key=payload.idempotency_key, expected_profile_version=payload.expected_profile_version,
            submitted_at=payload.submitted_at, duration_ms=payload.duration_ms,
            answers=[answer.model_dump() for answer in payload.answers],
            metadata={"learning_reflection": payload.learning_reflection.model_dump(mode="json") if payload.learning_reflection else {}},
        )
        hints = {}
        if self.service.feedback.tutor_repo is not None:
            stage_nodes = self.service.repository.find("learning_round_stage_nodes", stage_id=session["stage_id"])
            for group in manifest["groups"]:
                member_stage = next(row for row in stage_nodes if row["round_node_id"] == group["member_id"])
                for question in group["questions"]:
                    hints[question["question_id"]] = self.service.feedback.tutor_repo.count_turns(
                        profile.learner_id, source_batch_id=member_stage["batch_id"], context_type="question_help",
                        question_id=question["question_id"], created_before=payload.submitted_at,
                    )
        prepared = attempt_evidence.prepare_attempt_evidence(
            run_id=anchor.run_id, questions=questions, answer_key=manifest["answer_key"], payload=run_payload,
            selected_resource=anchor, tutor_hint_count=sum(hints.values()), tutor_hints_by_question=hints,
            score_answer=self.service.feedback._answer_score, tutor_batch_id=session["session_id"],
        )
        prepared.metadata["round_context"] = {"round_id": manifest["round_id"], "stage_id": session["stage_id"],
                                              "session_id": session["session_id"], "manifest_hash": session["manifest_hash"],
                                              "roles": {group["node_id"]: group["role"] for group in manifest["groups"]}}
        return prepared, anchor
