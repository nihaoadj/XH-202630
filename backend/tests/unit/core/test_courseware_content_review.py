from copy import deepcopy
import pytest
from app.agents.resource_workflows.interactive_courseware.source import _snapshot
from app.agents.resource_workflows.interactive_courseware.stages import prepare_design
from app.agents.resource_workflows.interactive_courseware.composition import compose_scenes, resource_courseware_title
from app.agents.resource_workflows.interactive_courseware.planner_agent import _platform_spec
from app.core.courseware.content_review import resolve_adapter, content_identity
from app.models.courseware.snapshots import LearnerContextSnapshot
from tests.fakes.courseware_content_review import resource, candidate


def prepared(group="review", values=None):
    source = _snapshot(resource(group), content_review=True); adapter = resolve_adapter(source)
    learning = adapter.refine_design(source, prepare_design([source], LearnerContextSnapshot(), {}).design)
    design = {"learning_design": learning.model_dump(mode="json"), "source_payload": source[adapter.source_key], "user_title": None}
    values = candidate(group) if values is None else values
    plan, _, _ = _platform_spec(learning, [source])
    if values:
        setattr(plan, adapter.candidate_slot, adapter.candidate_model.model_validate(values))
    scenes, _ = compose_scenes([source], plan, learning_design=learning, plan_enrichment=plan.enrichment)
    document = {"schema_version": "2.0", "title": resource_courseware_title(values.get("course_title") or source["topic"], [source]), "scenes": scenes}
    return source, adapter, design, values, document


@pytest.mark.parametrize("group", ["review", "practice_code", "practice_noncode"])
def test_every_consumed_field_has_independent_projection_and_unknown_fields_fail(group):
    source, adapter, design, values, document = prepared(group)
    inventory = adapter.prepare("run", source, design, values)
    assert inventory.items and adapter.validate_projection(source, design, values, document)["manifest"]
    altered = deepcopy(document); altered["scenes"][0]["new_unclassified_text"] = "unsafe"
    with pytest.raises(ValueError):
        adapter.validate_projection(source, design, values, altered)
    values["unexpected"] = "unsafe"
    with pytest.raises(ValueError):
        adapter.prepare("run", source, design, values)


@pytest.mark.parametrize("mutation", ["answer", "question", "summary", "order", "component", "missing", "registered_family", "question_binding"])
def test_review_questions_answers_summaries_and_order_cannot_be_overwritten(mutation):
    source, adapter, design, values, document = prepared()
    if mutation == "answer":
        document["scenes"][1]["component_blocks"][0]["items"][0]["reference_answer"] = "other node answer"
    elif mutation == "question":
        document["scenes"][1]["component_blocks"][0]["items"].reverse()
    elif mutation == "summary":
        next(s for s in document["scenes"] if s["page_role"] == "review_node_summary")["component_blocks"][0]["text"] = "wrong node"
    elif mutation == "order":
        document["scenes"].reverse()
    elif mutation == "component":
        document["scenes"][1]["component_blocks"][0]["component"] = "callout"
    elif mutation == "registered_family":
        document["scenes"][1]["page_role"] = "review_distinction"
        document["scenes"][1]["component_blocks"][0]["component"] = "review_distinction_card"
    elif mutation == "question_binding":
        document["scenes"][1]["component_blocks"][0]["source_refs"][0]["source_block_ids"] = document["scenes"][2]["source_block_ids"]
    else:
        document["scenes"].pop(3)
    with pytest.raises(ValueError):
        adapter.validate_projection(source, design, values, document)


@pytest.mark.parametrize("mutation", ["code", "verification", "subject", "missing_phase", "component", "unknown_code_key"])
def test_practice_fixed_projection_rejects_truncation_phase_alias_and_missing_content(mutation):
    source, adapter, design, values, document = prepared("practice_code")
    step = document["scenes"][2]
    if mutation == "code":
        step["component_blocks"][1]["code"] = "value = 1"
    elif mutation == "verification":
        step["component_blocks"].pop()
    elif mutation == "subject":
        document["scenes"][3]["practice_json_subject"] = "preparation"
    elif mutation == "missing_phase":
        document["scenes"].pop(1); design["learning_design"]["storyboard"]["scenes"].pop(1)
    elif mutation == "component":
        step["component_blocks"][0]["component"] = "callout"
    else:
        step["component_blocks"][1]["extra"] = "unsafe"
    with pytest.raises(ValueError):
        adapter.validate_projection(source, design, values, document)


def test_multi_example_bindings_and_old_single_example_have_frozen_ids():
    source, adapter, design, values, _ = prepared()
    assert {"q-009", "q-010"} <= {b.get("review_question_id") for b in source["blocks"]}
    assert adapter.prepare("run", source, design, values).evidence.items
    del source["blocks"][-2]
    with pytest.raises(ValueError):
        adapter.prepare("run", source, design, values)


def test_code_rule_is_per_item_and_noncode_requires_no_code():
    source, adapter, design, values, _ = prepared("practice_code")
    values["practice_cover"]["learning_goal"] = "对照冻结 Python 代码核对结果。"
    items = adapter.prepare("run", source, design, values).items
    assert "code_constraints" in next(i for i in items if i.source.tokens[-1] == "learning_goal").rule_ids
    assert "code_constraints" not in next(i for i in items if i.source.tokens[-1] == "learning_method").rule_ids
    for command in ("pip install pandas==2.0", "npm install package@1.2.3", "value >= 2.0", "from module import value"):
        values["course_title"] = command
        assert "code_constraints" in next(i for i in adapter.prepare("run", source, design, values).items if i.source.tokens == ["course_title"]).rule_ids
    source, adapter, design, values, _ = prepared("practice_noncode")
    assert all("code_constraints" not in i.rule_ids for i in adapter.prepare("run", source, design, values).items)
    slot = next(s for s in design["learning_design"]["storyboard"]["scenes"] if ":step:" in s["scene_id"])
    assert slot["content_budget"]["min_zones"] == 3 and slot["content_budget"]["min_chars"] == 180


def test_source_identity_and_readable_evidence_do_not_borrow_parent_or_latest_versions():
    source, adapter, design, values, _ = prepared()
    from app.core.courseware.content_review.evidence import bind_evidence
    source["content_review_evidence"] = [{"evidence_id": "id-only", "text": ""}]
    evidence = bind_evidence(source, adapter.source_key)
    assert "ref:id-only" not in {e.evidence_id for e in evidence.items}
    source["content_review_evidence"] = [{"evidence_id": "id", "text": "changed", "value_hash": "0"*64}]
    with pytest.raises(ValueError):
        bind_evidence(source, adapter.source_key)
    from app.core.courseware.content_review.registry import resolve_adapter as resolve
    with pytest.raises(ValueError):
        resolve({**source, "resource_type": "new production type"})
