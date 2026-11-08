from copy import deepcopy
import json
import pytest
from app.models.courseware.contracts import CoursewareJobCreateRequest
from app.models.courseware.content_review import ContentReviewBlocked, json_hash
from app.agents.resource_workflows.interactive_courseware.content_review.lifecycle import verify_run_content
from tests.fakes.courseware_content_review import fixture_environment, fixture_settings, make_workflow, ContentReviewGateway, candidate
from scripts.courseware_content_review_fixtures import artifact_path


def run_case(tmp_path, group="review", **gateway_options):
    gateway = ContentReviewGateway(group, **gateway_options)
    wf, source = make_workflow(tmp_path, group, gateway=gateway)
    job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
    result = wf.run(job.run_id)
    return wf, job.run_id, result


@pytest.mark.parametrize("fault", ["missing_question_id", "duplicate_question_id", "foreign_evidence", "unknown_field"])
@pytest.mark.parametrize("reused_snapshot", [False, True])
def test_invalid_frozen_review_source_is_blocked_before_any_model_call(tmp_path, fault, reused_snapshot):
    from app.agents.resource_workflows.interactive_courseware.source import _snapshot
    with fixture_environment(tmp_path):
        wf, source = make_workflow(tmp_path)
        snapshot = _snapshot(source, content_review=True)
        payload = snapshot["review_practice_payload"] if reused_snapshot else source.review_practice_payload
        questions = payload["node_blocks"][0]["recall_questions"]
        if fault == "missing_question_id":
            questions[0]["question_id"] = None
        elif fault == "duplicate_question_id":
            questions[1]["question_id"] = questions[0]["question_id"]
        elif fault == "foreign_evidence":
            questions[0]["evidence_ids"] = ["unbound-evidence"]
        else:
            questions[0]["unknown_prose"] = "unclassified source text"
        digest = json_hash({k: v for k, v in payload.items() if k != "payload_hash"})
        payload["payload_hash"] = digest
        if reused_snapshot:
            snapshot["review_practice_payload_hash"] = digest
        else:
            source.review_practice_payload_hash = digest
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
        if reused_snapshot:
            wf.repo.update_job(job.run_id, source_snapshots=[snapshot], knowledge_base_id="content-kb")
        result = wf.run(job.run_id)
        expected = ("rejected_admission", "COURSEWARE_SOURCE_ADMISSION_REJECTED") if fault == "unknown_field" and not reused_snapshot else ("quarantined", "COURSEWARE_CONTENT_REVIEW_BLOCKED")
        assert (result.status, result.error_code) == expected
        assert not wf.llm_gateway.calls
        assert not wf.content_review.state(job.run_id).ledger
        assert wf.repo.get_resource_by_run(job.run_id) is None


@pytest.mark.parametrize("group", ["review", "practice_code", "practice_noncode"])
def test_real_workflow_approves_all_fields_and_keeps_private_evidence_out_of_public_projections(tmp_path, group):
    with fixture_environment(tmp_path):
        wf, run_id, result = run_case(tmp_path, group)
        assert result.status == "published" and not result.error_code
        state = wf.content_review.state(run_id)
        assert state.record.status == "approved" and state.record.manifest and state.record.document_hash
        assert len({t.ticket_id for t in state.ledger}) == len(wf.llm_gateway.calls) == 4
        assert all(t.status == "completed" for t in state.ledger[1::2])
        public = json.dumps({"detail": wf.get_job_detail(run_id).model_dump(mode="json"), "events": wf.events(run_id)}, ensure_ascii=False, default=str)
        for private in ("content_review_binding", "approved_values", "original_values", "frozen_readable_evidence", "先确认输入版本与适用条件，再核对实际结果并记录证据。"):
            assert private not in public
        resource = wf.repo.get_resource_by_run(run_id)
        release_id = resource["released_release_id"]
        before_calls = len(wf.llm_gateway.calls)
        assert wf.run(run_id).status == result.status
        assert wf.publish(run_id).status == result.status
        spec = wf.repo.get_spec_by_run(run_id)
        wf.retry_scene(run_id, wf.repo.list_scenes(spec["spec_id"])[0]["scene_id"])
        assert len(wf.llm_gateway.calls) == before_calls
        assert wf.repo.get_resource_by_run(run_id)["released_release_id"] == release_id
        verify_run_content(wf.repo, run_id)


@pytest.mark.parametrize("fault", ["source", "value", "rules", "evidence", "ledger", "binding", "policy", "spec", "manifest", "document_hash", "merge_proof", "adapter", "teaching_metadata"])
def test_persisted_tampering_blocks_every_release_coordinator_entry(tmp_path, fault):
    with fixture_environment(tmp_path):
        wf, run_id, _ = run_case(tmp_path)
        row = wf.repo.get_spec_by_run(run_id)
        old_release = deepcopy(wf.repo.releases)
        if fault == "source":
            wf.repo.jobs[run_id]["source_snapshots"][0]["source_graph"]["nodes"][0]["version"] += 1
        elif fault == "binding":
            wf.repo.outbox[f"cwo_{run_id}"]["payload"].pop("content_review_binding")
        elif fault == "spec":
            wf.repo.specs.pop(row["spec_id"])
        else:
            raw = wf.repo.specs[row["spec_id"]]["spec_json"]
            if fault == "value": raw["content_review"]["record"]["approved_values"]["learning_scope"] = "unapproved"
            elif fault == "rules": raw["content_review"]["record"]["results"][0]["rules"].pop()
            elif fault == "evidence": raw["content_review"]["record"]["results"][0]["rules"][0]["evidence_ids"] = ["unknown"]
            elif fault == "ledger": raw["content_review"]["ledger"][0]["charged_tokens"] = 0
            elif fault == "manifest": raw["content_review"]["record"]["manifest"] = []
            elif fault == "document_hash": raw["content_review"]["record"]["document_hash"] = None
            elif fault == "merge_proof": raw["content_review"]["record"].update(document_hash=None, manifest=[])
            elif fault == "adapter": raw["content_review"]["record"]["adapter_version"] = "unknown-v9"
            elif fault == "teaching_metadata": raw["scenes"][0]["title"] = "unapproved metadata"
            else: raw["content_review"].pop("policy")
            wf.repo.specs[row["spec_id"]]["content_hash"] = json_hash(raw)
        with pytest.raises(ValueError):
            verify_run_content(wf.repo, run_id)
        with pytest.raises(ValueError):
            wf.release_coordinator.freeze(run_id=run_id, resource_id="existing", release_policy="resilient", snapshots=[], scenes=[])
        assert wf.repo.releases == old_release


@pytest.mark.parametrize("strict", [False, True])
def test_unavailable_field_review_has_explicit_template_or_strict_block(tmp_path, strict):
    def invalid(raw, _payload):
        raw["results"].pop(); return raw
    settings = fixture_settings(courseware_release_policy="strict" if strict else "resilient")
    with fixture_environment(tmp_path, settings):
        values = candidate(); values["course_title"] = "仅供审核的AI封面标题"
        wf, run_id, result = run_case(tmp_path, fault=invalid, candidate_values=values)
        state = wf.content_review.state(run_id)
        assert state.record.status == ("blocked" if strict else "degraded")
        assert result.status == ("quarantined" if strict else "published_with_warnings")
        if not strict:
            assert state.record.approved_values == {} and state.record.reason
            html = artifact_path(tmp_path, wf.repo.get_resource_by_run(run_id)).read_text(encoding="utf-8")
            assert "仅供审核的AI封面标题" not in html
            assert "冻结来源复习" in html  # The fixed source title remains legal.


def test_invalid_user_title_cannot_be_rewritten_or_template_approved(tmp_path):
    with fixture_environment(tmp_path):
        wf, source = make_workflow(tmp_path)
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id], title="错误候选：已经掌握所有知识"))
        assert wf.run(job.run_id).status == "quarantined"
        assert wf.repo.get_job(job.run_id)["title"] == "错误候选：已经掌握所有知识"
        assert wf.repo.get_resource_by_run(job.run_id) is None


def test_semantic_revision_rechecks_values_and_rejected_text_never_reaches_artifact(tmp_path):
    values = candidate(); values["learning_scope"] = "错误候选：虚构覆盖范围"
    with fixture_environment(tmp_path):
        wf, run_id, result = run_case(tmp_path, candidate_values=values)
        assert result.status == "published"
        state = wf.content_review.state(run_id)
        assert state.record.revision_rounds == 1 and state.record.status == "approved"
        from pathlib import Path
        html = artifact_path(tmp_path, wf.repo.get_resource_by_run(run_id)).read_text(encoding="utf-8")
        assert "错误候选" not in html
        assert state.record.approved_values["learning_scope"] in html


def test_overall_quality_routes_registered_overview_ai_values_and_rechecks_once(tmp_path):
    with fixture_environment(tmp_path):
        wf, run_id, result = run_case(tmp_path, quality_fault="revise_once")
        assert result.status == "published" and wf.content_review.state(run_id).record.revision_rounds == 1
        assert sum(c["output_schema"].__name__ == "RevisionPatchV1" for c in wf.llm_gateway.calls) >= 1
        verify_run_content(wf.repo, run_id)


@pytest.mark.parametrize("scope", ["block", "scene"])
def test_overall_fixed_question_issue_is_quarantined_without_model_rewriting(tmp_path, scope):
    class FixedIssueGateway(ContentReviewGateway):
        def invoke_structured(self, **kwargs):
            result = super().invoke_structured(**kwargs)
            if kwargs["output_schema"].__name__ == "CoursewareReviewDecisionV2Draft":
                doc = json.loads(kwargs["messages"][-1].content)["document"]
                target = doc["scenes"][1] if scope == "block" else next(s for s in doc["scenes"] if s["page_role"] == "review_example")
                result.output = kwargs["output_schema"].model_validate({"status": "revise", "issues": [{"code": "FIXED_QUESTION", "dimension": "feedback_quality", "severity": "error", "scope": scope, "scene_id": target["scene_id"], "block_id": target["component_blocks"][0]["block_id"] if scope == "block" else None, "instruction": "改写原题答案"}], "rubric_scores": {k: 4 for k in result.output.rubric_scores}})
            return result
    with fixture_environment(tmp_path):
        wf, source = make_workflow(tmp_path, gateway=FixedIssueGateway())
        job = wf.create_job(CoursewareJobCreateRequest(learner_id=source.learner_id, source_resource_ids=[source.resource_id]))
        assert wf.run(job.run_id).status == "quarantined"
        assert not any(c["output_schema"].__name__ == "RevisionPatchV1" for c in wf.llm_gateway.calls)
        assert wf.repo.get_resource_by_run(job.run_id) is None


def test_degradation_clears_persisted_ai_scene_metadata_together_with_cover(tmp_path):
    values = candidate("practice_code")
    values["scenes"] = [{"scene_id": "scene:intro", "title": "经过字段审核的元数据标题", "teaching_intent": "先核对来源再进入步骤。", "preferred_component_ids": []}]
    with fixture_environment(tmp_path):
        wf, run_id, result = run_case(tmp_path, "practice_code", candidate_values=values, quality_fault="unavailable")
        assert result.status == "published_with_warnings"
        state = wf.content_review.state(run_id)
        assert state.record.status == "degraded" and state.record.approved_values == {}
        assert "经过字段审核的元数据标题" not in json.dumps(wf.repo.get_spec_by_run(run_id)["spec_json"]["scenes"], ensure_ascii=False)
        verify_run_content(wf.repo, run_id)


from pathlib import Path
