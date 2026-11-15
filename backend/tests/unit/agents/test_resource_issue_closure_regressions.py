"""T44 focused regressions for current-version issue closure and deterministic IDs."""
import copy
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.assessment import AssessmentAdapter, assessment_questions
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.checklist import ChecklistAdapter, checklist_comparison_projection
from app.agents.resource_agents.assessment import render_assessment_markdown
from app.agents.resource_agents.practice import render_practice_guide_markdown
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.lecture import LectureAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.practice import PracticeAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import run_program_gate, migrate_program_gate, _binding, _freeze_inputs
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.ledger import append_program_gate_observation_v1, append_model_observation_v1
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import validate_resource_review, ValidationError
from app.models.reviews.resource_review import ResourceIssueV1, ResourceReviewRecheckV1, ResourceReopenV1
from app.models.learning_documents.schemas import LearningResource
from tests.fakes.resource_reviews import case
from tests.unit.agents.test_resource_issue_engine import _resource, _state, _policy
from tests.unit.agents.test_resource_issue_adapters import _lecture_material, _binding as prose_binding, _output


def _issue(**updates):
    data = dict(issue_id="old-1", code="self_contained_gap", severity="high", blocking=True,
                blocking_rule="self_contained", dimension="self_contained", location={"kind":"root"},
                impact="impact", requirement="minimal repair", acceptance="verify", criteria_version=1,
                path="reorganize_existing", teaching_rule_id="self_contained", executability="executable", rationale="reason")
    data.update(updates)
    return ResourceIssueV1.model_validate(data)


def test_repeat_program_gate_keeps_one_stable_definition_per_id():
    resource = _resource("实操指南", content="# 实操\n内容")
    material = PracticeAdapter().build_material(resource=resource,evidence=[],spec=None,targets=["目标一"])
    state = _state(_policy(), resource)
    _, spec_id, _, frozen = _freeze_inputs(state=state,resource=resource,evidence=[])
    binding = _binding(state=state,resource=resource,spec_id=spec_id,frozen_evidence=frozen,material=material)
    gate = run_program_gate(resource=resource,material=material,binding=binding)
    first = append_program_gate_observation_v1(previous=None,binding=binding,step_id="s1",gate=gate,material=material,parent_comparison_hash=None)
    second_binding = binding.model_copy(update={"version":2,"resource_id":"res-2"})
    second_gate = migrate_program_gate(run_program_gate(resource=resource,material=material,binding=second_binding),first)
    second = append_program_gate_observation_v1(previous=first,binding=second_binding,step_id="s2",gate=second_gate,material=material,parent_comparison_hash=material.comparison_hash)
    assert len(second.observations)==2
    assert len(second.issues)==len(first.issues)
    assert [i.issue.issue_id for i in second.issues]==[i.issue.issue_id for i in first.issues]
    assert second.observations[-1].gate.still_open_program_issues


def test_checklist_projection_omits_self_hash_but_keeps_content():
    first={"payload_hash":"a"*64,"node_blocks":[{"recall_questions":[{"question_id":"q1","prompt":"text"}]}]}
    second=copy.deepcopy(first)
    second["payload_hash"]="b"*64
    second["node_blocks"][0]["recall_questions"][0]["question_id"]="q2"
    assert checklist_comparison_projection(first)==checklist_comparison_projection(second)
    assert first["payload_hash"]=="a"*64
    second["node_blocks"][0]["recall_questions"][0]["prompt"]="changed"
    assert checklist_comparison_projection(first)!=checklist_comparison_projection(second)


@pytest.mark.parametrize("quote,valid",[("parent unique",True),("current unique",False)])
def test_previous_location_validates_parent_not_current(quote,valid):
    parent=_lecture_material("parent unique")
    current=_lecture_material("current unique")
    issue=_issue()
    payload=_output(current).model_dump(mode="json")
    payload["resolutions"]=[dict(issue_id=issue.issue_id,result="false_positive",reason="prior finding was wrong",previous_location={"kind":"paragraph","paragraph_id":"p000001","quote":quote})]
    output=ResourceReviewRecheckV1.model_validate(payload)
    kwargs=dict(output=output,binding=prose_binding(current),material=current,adapter=LectureAdapter(),previous_comparison_hash=parent.comparison_hash,old_open=(issue,),parent_material=parent)
    if valid:
        assert not validate_resource_review(**kwargs).open_issues
    else:
        with pytest.raises(ValidationError,match="LOCATION_OUT_OF_BOUNDS"):
            validate_resource_review(**kwargs)


def _assessment_recheck(kind="still_open", *, refs=None, wrong_location=False):
    resource=LearningResource.model_validate(case("assessment.clean.01")["resource"])
    adapter=AssessmentAdapter()
    material=adapter.build_material(resource=resource,evidence=[],spec=None,targets=["目标一"])
    questions=assessment_questions(resource.assessment_payload)
    qid=questions[0]["question_id"]
    key=f"{qid}:clarity:structure_quality"
    issue=_issue(location={"kind":"structured","unit_id":qid},finding_keys=[key])
    findings=[dict(question_id=q["question_id"],scope_decision="in_scope",supported_evidence_ids=q["evidence_ids"][:1],answer_check="pass",clarity_check="fail" if q["question_id"]==qid else "pass",rubric_check="not_applicable" if q["question_type"] in {"single_choice","multiple_choice"} else "pass",reason="checked") for q in questions]
    binding=prose_binding(material).model_copy(update={"resource_type":"分阶测试题","structured_payload_hash":material.structured_payload_hash})
    payload=dict(binding=binding.model_dump(mode="json"),dimensions={"factual_evidence":"pass","difficulty":"pass","self_contained":"fail"},targets=[dict(target="目标一",status="covered",reason="covered",location={"kind":"root"})],hallucination_score=0,issues=[],findings=findings,omitted_blocking_issues=False)
    observation=dict(issue_id=issue.issue_id,reason="still fails",current_location={"kind":"structured","unit_id":questions[1]["question_id"] if wrong_location else qid},current_check_refs=[key] if refs is None else refs)
    if kind=="still_open":
        observation["result"]="still_open"
        payload["resolutions"]=[observation]
    else:
        payload["reopen"]=[observation]
    return dict(output=ResourceReviewRecheckV1.model_validate(payload),binding=binding,material=material,adapter=adapter,previous_comparison_hash=material.comparison_hash,old_open=(issue,) if kind=="still_open" else (),old_closed=(issue,) if kind=="reopen" else (),parent_material=material)


@pytest.mark.parametrize("kind",["still_open","reopen"])
def test_assessment_old_issue_owns_current_failure_without_new_duplicate(kind):
    outcome=validate_resource_review(**_assessment_recheck(kind))
    assert len(outcome.open_issues)==1


@pytest.mark.parametrize("kind",["still_open","reopen"])
@pytest.mark.parametrize("variant",["missing","wrong_location","stale_key","duplicate"])
def test_assessment_rejects_invalid_current_failure_association(kind,variant):
    kwargs=_assessment_recheck(kind,refs=[] if variant=="missing" else ["stale:clarity:structure_quality"] if variant=="stale_key" else None,wrong_location=variant=="wrong_location")
    if variant=="duplicate":
        duplicate=kwargs["old_open"] or kwargs["old_closed"]
        kwargs["output"]=kwargs["output"].model_copy(update={"issues":[duplicate[0].model_copy(update={"issue_id":"new-1"})]})
    with pytest.raises(ValidationError):
        validate_resource_review(**kwargs)


def test_old_reopen_serialization_preserves_historical_hash_shape():
    payload=dict(issue_id="old",current_location={"kind":"root"},reason="recurred")
    old=ResourceReopenV1.model_validate(payload)
    assert "current_check_refs" not in old.model_dump(mode="json")
    assert ResourceReopenV1.model_validate({**payload,"current_check_refs":["q:clarity:structure_quality"]}).model_dump(mode="json")["current_check_refs"]


@pytest.mark.parametrize("case_id,adapter,field", [
    ("assessment.clean.01", AssessmentAdapter(), "assessment_payload"),
    ("practice.clean.01", PracticeAdapter(), "practice_guide_payload"),
])
def test_projection_accepts_generated_artifact_strip_but_rejects_content_drift(case_id,adapter,field):
    resource=LearningResource.model_validate(case(case_id)["resource"])
    render=render_assessment_markdown if field=="assessment_payload" else render_practice_guide_markdown
    text=render(getattr(resource,field))
    stored=resource.model_copy(update={"content_text":text.strip()})
    assert adapter.build_material(resource=stored,evidence=[],spec=None,targets=["目标一"]).projection_consistent
    drift=stored.model_copy(update={"content_text":text.strip()+"\n额外技术断言"})
    assert not adapter.build_material(resource=drift,evidence=[],spec=None,targets=["目标一"]).projection_consistent


def test_checklist_legal_mechanical_renumber_preserves_comparison_not_exact_hash():
    from app.agents.resource_agents.checklist import _canonical_hash, render_review_practice_markdown
    from app.models.shared.agent_contracts import ReviewPracticePackageV2
    from tests.unit.agents.test_review_practice_v2 import _block
    package=ReviewPracticePackageV2(title="主题",instructions="先作答",node_blocks=[_block()]).model_dump(mode="json")
    package["node_blocks"][0]["recall_questions"][0]["question_id"]="q-001"
    package["node_blocks"][0]["distinction_questions"][0]["question_id"]="q-005"
    package["payload_hash"]=_canonical_hash(package)
    resource=_resource("复习清单",content=render_review_practice_markdown(package),review_practice_payload=package)
    adapter=ChecklistAdapter()
    first=adapter.build_material(resource=resource,evidence=[],spec=None,targets=["目标一"])
    package=copy.deepcopy(resource.review_practice_payload)
    for block in package["node_blocks"]:
        for field in ("recall_questions","distinction_questions","example_recognition_questions"):
            for index,question in enumerate(block.get(field,[])):
                question["question_id"]=f"renumber-{field}-{index}"
    package["payload_hash"]=_canonical_hash({key:value for key,value in package.items() if key!="payload_hash"})
    changed=resource.model_copy(update={"review_practice_payload":package,"content_text":render_review_practice_markdown(package)})
    second=adapter.build_material(resource=changed,evidence=[],spec=None,targets=["目标一"])
    assert second.projection_consistent
    assert first.artifact_exact_hash!=second.artifact_exact_hash
    assert first.comparison_hash==second.comparison_hash
