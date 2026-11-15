from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from app.agents.resource_workflows.interactive_courseware.content_review import review_content
from app.agents.resource_workflows.interactive_courseware.content_review.persistence import freeze_policy
from app.agents.resource_workflows.interactive_courseware.content_review.batching import plan_batches, TokenEstimatorProfile
from app.agents.resource_workflows.interactive_courseware.content_review.profiles import REVIEW_PROFILE
from app.models.courseware.content_review import ContentReviewBlocked, json_hash
from tests.fakes.courseware_content_review import ContentReviewGateway, fixture_settings
from tests.unit.core.test_courseware_content_review import prepared


def review(group="review", *, values=None, gateway=None, settings=None, revise=True):
    source, adapter, design, candidate, _ = prepared(group, values)
    gateway = gateway or ContentReviewGateway(group)
    policy = freeze_policy(settings or fixture_settings(), gateway, datetime.now(timezone.utc)+timedelta(minutes=10))
    record = review_content(run_id="run", snapshot=source, design=design, candidate=candidate, adapter=adapter,
        policy=policy, gateway=gateway, revision_gateway=gateway if revise else None)
    return record, gateway


@pytest.mark.parametrize("fault", ["missing", "duplicate", "evidence", "hash", "rules", "batch", "identity", "extra"])
def test_incomplete_or_mixed_model_results_never_partially_approve(fault):
    def corrupt(raw, payload):
        raw = deepcopy(raw)
        if fault == "missing": raw["results"].pop()
        elif fault == "duplicate": raw["results"].append(raw["results"][0])
        elif fault == "evidence": raw["results"][0]["rules"][0]["evidence_ids"] = ["unknown"]
        elif fault == "hash": raw["results"][0]["value_hash"] = "0"*64
        elif fault == "rules": raw["results"][0]["rules"].pop()
        elif fault == "batch": raw["batch_id"] = "different"
        elif fault == "identity": raw["identity"] = "0"*64
        else: raw["unexpected"] = "unsafe"
        return raw
    record, _ = review(gateway=ContentReviewGateway(fault=corrupt))
    assert record.status == "degraded" and record.approved_values == {} and record.reason


def test_small_candidate_batched_once_and_large_output_splits_without_truncating():
    _, gateway = review("practice_noncode")
    calls = [c for c in gateway.calls if c["output_schema"].__name__ == "BatchResultV1"]
    assert len(calls) == 2
    sent = [item for c in calls for item in __import__("json").loads(c["messages"][-1].content)["items"]]
    assert len(sent) == 6 and len({i["item_id"] for i in sent}) == 6
    assert all(c["options"].max_attempts == 1 and not c["options"].allow_schema_repair for c in calls)
    assert all("code_constraints@" not in c["messages"][0].content for c in calls)
    record, gateway = review(values={})
    assert record.status == "not_applicable" and gateway.calls == []


def test_one_revision_and_recheck_changes_only_ai_fields():
    _, _, _, values, _ = prepared(); values["learning_scope"] = "错误候选：虚构范围"
    record, gateway = review(values=values)
    assert record.status == "approved" and record.revision_rounds == 1
    assert record.approved_values["learning_scope"] != values["learning_scope"]
    assert sum(c["output_schema"].__name__ == "RevisionPatchV1" for c in gateway.calls) == 1
    assert record.original_values == values


def test_patch_outside_whitelist_has_no_partial_application():
    _, _, _, values, _ = prepared(); values["learning_scope"] = "错误候选"
    record, _ = review(values=values, gateway=ContentReviewGateway(fault="patch_outside"))
    assert record.status == "degraded" and not record.approved_values


def test_dependency_group_that_cannot_fit_stops_before_any_model_call():
    source, adapter, design, values, _ = prepared()
    p = adapter.prepare("run", source, design, values)
    from dataclasses import replace
    items = tuple(i.model_copy(update={"dependency_ids": [j.item_id for j in p.items]}) for i in p.items)
    p = replace(p, items=items)
    gateway = ContentReviewGateway(); policy = freeze_policy(fixture_settings(), gateway, datetime.now(timezone.utc)+timedelta(minutes=10))
    with pytest.raises(ContentReviewBlocked, match="dependency group"):
        plan_batches(p, "a"*64, policy, REVIEW_PROFILE, TokenEstimatorProfile())
    assert gateway.calls == []


def test_third_adapter_uses_same_engine_and_persistable_contract_without_type_branch():
    from dataclasses import replace
    from pydantic import BaseModel, ConfigDict, Field
    from app.core.courseware.content_review.inventory import PreparedContent
    from app.core.courseware.content_review.registry import resolve_adapter, ADAPTERS
    from app.models.courseware.content_review import ContentInventoryV1, ReviewItemV1, FieldLocatorV1, EvidenceBundleV1, EvidenceV1, ContentItemV1, ContentReviewStateV1
    class Candidate(BaseModel):
        model_config = ConfigDict(extra="forbid")
        headline: str = Field(min_length=1, max_length=80)
        hint: str = Field(min_length=1, max_length=120)
    class ThirdAdapter:
        version = "test-third-v1"
        candidate_model = Candidate
        def prepare(self, run_id, snapshot, design, candidate):
            values = Candidate.model_validate(candidate).model_dump()
            evidence = EvidenceV1(evidence_id="third-source", kind="source_content", text=snapshot["lesson_payload"]["body"],
                source=FieldLocatorV1(space="source", owner_id="lesson", tokens=["body"]), value_hash=json_hash(snapshot["lesson_payload"]["body"]))
            items = tuple(ReviewItemV1(item_id=f"new:{key}", owner_id="lesson", origin="ai", source=FieldLocatorV1(space="candidate", owner_id="lesson", tokens=[key]),
                targets=[FieldLocatorV1(space="document", owner_id="lesson", tokens=["new_panel", key])], value_hash=json_hash(value),
                rule_ids=["factual_support", "scope_alignment"] if key == "headline" else ["learning_guidance"], evidence_ids=["third-source"],
                value=value, max_chars=80 if key == "headline" else 120) for key, value in values.items())
            inventory = ContentInventoryV1(run_id=run_id, source_id="third-source", source_schema="9.0", adapter_version=self.version,
                items=[ContentItemV1.model_validate(i.model_dump(exclude={"value", "max_chars"})) for i in items])
            return PreparedContent(values, inventory, items, EvidenceBundleV1(items=[evidence]))
        def validate_projection(self, snapshot, design, candidate, document):
            assert document["new_panel"] == candidate
            p = self.prepare("third-run", snapshot, design, candidate)
            return {"manifest": list(p.inventory.items), "document_hash": json_hash(document)}
    source = {"resource_type": "test-third", "lesson_payload": {"schema_version": "9.0", "body": "根据冻结来源核对输入与结果。"}}
    third = resolve_adapter(source, {("test-third", "9.0"): ThirdAdapter()})
    assert ("test-third", "9.0") not in ADAPTERS
    design = {}; values = {"headline": "错误候选：夸大事实", "hint": "先核对冻结来源。"}; gateway = ContentReviewGateway()
    policy = freeze_policy(fixture_settings(), gateway, datetime.now(timezone.utc)+timedelta(minutes=10))
    from app.db.courseware.repository import MemoryCoursewareRepository
    from tests.integration.courseware.test_content_review_persistence import create
    repo = MemoryCoursewareRepository(); create(repo, run_id="third-run")
    from app.agents.resource_workflows.interactive_courseware.content_review.persistence import read_state
    policy = read_state(repo, "third-run")[0].policy
    record = review_content(run_id="third-run", snapshot=source, design=design, candidate=values, adapter=third, policy=policy, gateway=gateway, revision_gateway=gateway)
    assert record.status == "approved" and record.adapter_version == "test-third-v1"
    assert record.revision_rounds == 1
    assert type(record).model_validate_json(record.model_dump_json()) == record
    assert json_hash(record.approved_values) == record.value_hash
    projection = third.validate_projection(source, design, record.approved_values, {"new_panel": record.approved_values})
    row = repo.get_spec_by_run("third-run"); old_hash = row["content_hash"]
    row["spec_json"]["content_review"].update(phase="reviewed", candidate=values, record=record.model_copy(update=projection).model_dump(mode="json"))
    row["content_hash"] = json_hash(row["spec_json"])
    repo.save_content_review_spec_once("third-run", row["spec_id"], old_hash, row)
    assert repo.get_spec_by_run("third-run")["spec_json"]["content_review"]["record"]["adapter_version"] == third.version
