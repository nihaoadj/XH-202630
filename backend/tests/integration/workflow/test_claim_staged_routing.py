"""Business bounds for contradiction-first Claim routing; no model calls."""
import pytest
from hashlib import sha256

from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_decide_node
from app.agents.resource_workflows.learning_documents.workflow import (
    route_after_initial_claim_judge, route_after_claim_decide, prepare_claim_revision_node,
)
from app.models.learning_documents.schemas import LearningResource


def staged_state(verdicts, *, post_budget=0, total=0, post=0, after_retrieval=False):
    resource = LearningResource(resource_id="r", resource_spec_id="spec", resource_type="讲义",
                                content_text="Frozen text.", difficulty="初级", version=1,
                                knowledge_points=["skill"], source_refs=[], run_id="run")
    claims = [dict(claim_id=f"clm_{i:032x}", resource_id="r", claim_type="factual", run_id="run",
                   resource_version=1, review_id="review", claim_index=i, claim_text="Frozen text.",
                   source_text="Frozen text.", source_start=0, source_end=12,
                   source_text_hash=sha256(b"Frozen text.").hexdigest(),
                   extractor_prompt_version="test", claim_hash="a"*64) for i, _ in enumerate(verdicts)]
    judgements = [dict(claim_id=c["claim_id"], judgement_id=f"jdg_{i:032x}", resource_id="r",
                      resource_version=1, review_id="review", run_id="run", status="completed",
                      verdict=v, reason="test", judge_type="llm", judge_prompt_version="test")
                  for i, (c, v) in enumerate(zip(claims, verdicts))]
    return dict(run_id="run", generated_resources=[resource], include_claim_check=True,
                include_claim_evidence_retrieval=True, claim_workflow_version="contradiction_first_v1",
                claim_evidence_retrieval_policy={"frozen": True}, claim_check_status="completed",
                generation_attempt=total + 1, revision_count=0, claim_revision_count=total,
                claim_post_retrieval_revision_count=post, claim_max_iterations=1,
                claim_post_retrieval_max_iterations=post_budget,
                claim_post_retrieval_resource_keys=["spec"] if after_retrieval else [],
                extracted_claims=claims, claim_judgements=judgements,
                claim_metrics={"r": dict(metric_status="complete", factual_claim_total=len(verdicts),
                    contradicted_claim_total=verdicts.count("contradicted"),
                    not_in_evidence_claim_total=verdicts.count("not_in_evidence"))},
                review_result=dict(decision="approve", review_ids={"r":"review"}, issues=[], revision_instructions=[]))


def test_contradictions_are_revised_before_gaps_without_spending_post_budget():
    state = staged_state(["contradicted", "not_in_evidence"], post_budget=2)
    assert route_after_initial_claim_judge(state) == "claim_decide"
    state.update(claim_decide_node(state))
    assert state["claim_revision_phase"] == "contradiction"
    assert [i["target_claim_ids"] for i in state["review_result"]["revision_instructions"]] == [[state["extracted_claims"][0]["claim_id"]]]
    assert route_after_claim_decide(state) == "prepare_claim_revision"
    prepared = prepare_claim_revision_node(state)
    assert prepared["claim_revision_count"] == 1
    assert prepared["claim_post_retrieval_revision_count"] == 0
    assert prepared["constraints"]["revision_feedback"]["issues"][0]["code"] == "factual_risk"
    envelope = prepared["constraints"]["generation_revision_inputs"]["spec"]
    assert [p["verdict"] for p in envelope["input"]["problems"]] == ["contradicted"]


def test_exhausted_contradiction_budget_never_enters_supplements_or_borrows_post_budget():
    state = staged_state(["contradicted", "not_in_evidence"], total=1, post_budget=3)
    assert route_after_initial_claim_judge(state) == "claim_decide"
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == "finalize"


@pytest.mark.parametrize("post_budget,used,route", [(0,0,"finalize"), (1,0,"prepare_claim_revision"),
                                                   (1,1,"finalize"), (2,1,"prepare_claim_revision")])
@pytest.mark.parametrize("verdict", ["not_in_evidence", "contradicted"])
def test_post_stage_uses_only_its_own_remaining_budget(post_budget, used, route, verdict):
    state = staged_state([verdict], total=used, post=used,
                         post_budget=post_budget, after_retrieval=True)
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == route
    if route == "prepare_claim_revision":
        prepared = prepare_claim_revision_node(state)
        assert prepared["claim_revision_count"] == used+1
        assert prepared["claim_post_retrieval_revision_count"] == used+1
        # The marker follows stable specs to child versions and cannot reset.
        assert state["claim_post_retrieval_resource_keys"] == ["spec"]


def test_new_contradiction_after_post_revision_cannot_reclaim_unused_pre_budget():
    state = staged_state(["contradicted", "not_in_evidence"], total=1, post=1,
                         post_budget=1, after_retrieval=True)
    assert route_after_initial_claim_judge(state) == "claim_decide"
    state.update(claim_decide_node(state))
    assert state["claim_revision_phase"] == "exhausted"
    assert route_after_claim_decide(state) == "finalize"


def test_manual_single_revision_cap_still_applies_across_both_stages():
    state = staged_state(["not_in_evidence"], total=1, post=1,
                         post_budget=3, after_retrieval=True)
    state["resource_retry_context"] = {"request": {"constraints": {
        "resource_retry_single_pass": True, "resource_retry_action": "recheck"}}}
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == "finalize"


def test_missing_only_routes_to_supplement_without_pre_revision():
    state = staged_state(["not_in_evidence"])
    assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"


@pytest.mark.parametrize("legacy", [True, False])
def test_disabled_supplements_and_legacy_tasks_keep_the_original_budget(legacy):
    state = staged_state(["not_in_evidence"])
    if legacy:
        state["claim_workflow_version"] = "legacy_v1"
    else:
        state["include_claim_evidence_retrieval"] = False
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == "prepare_claim_revision"


@pytest.mark.parametrize("gap_count", [0, 8, 9, 16])
@pytest.mark.parametrize("version", ["contradiction_first_v1", "contradiction_first_v2"])
def test_large_gaps_join_only_the_contradicted_resource_revision(gap_count, version):
    state = staged_state(["contradicted"] + ["not_in_evidence"]*gap_count)
    state["claim_workflow_version"] = version
    assert route_after_initial_claim_judge(state) == "claim_decide"
    state.update(claim_decide_node(state))
    prepared = prepare_claim_revision_node(state)
    problems = prepared["constraints"]["generation_revision_inputs"]["spec"]["input"]["problems"]
    included_gaps = gap_count if version == "contradiction_first_v2" and gap_count > 8 else 0
    assert len(problems) == 1 + included_gaps
    assert [p["verdict"] for p in problems].count("not_in_evidence") == included_gaps
    assert prepared["claim_revision_count"] == 1
    assert prepared["claim_post_retrieval_revision_count"] == 0


@pytest.mark.parametrize("gap_count", [8, 9, 30])
def test_large_gaps_without_contradictions_still_go_directly_to_retrieval(gap_count):
    state = staged_state(["not_in_evidence"]*gap_count)
    state["claim_workflow_version"] = "contradiction_first_v2"
    assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"


def test_large_gaps_never_add_budget_and_do_not_change_post_stage():
    state = staged_state(["contradicted"] + ["not_in_evidence"]*9, total=1, post_budget=3)
    state["claim_workflow_version"] = "contradiction_first_v2"
    state.update(claim_decide_node(state))
    assert state["claim_revision_phase"] == "exhausted"
    assert route_after_claim_decide(state) == "finalize"
    state = staged_state(["contradicted"] + ["not_in_evidence"]*9,
                         after_retrieval=True, post_budget=0)
    state["claim_workflow_version"] = "contradiction_first_v2"
    state.update(claim_decide_node(state))
    assert route_after_claim_decide(state) == "finalize"


def test_gap_threshold_is_unique_completed_factual_claims_in_current_review():
    from copy import deepcopy
    from app.agents.resource_workflows.learning_documents.claim_routing import select_revision_bad
    state = staged_state(["contradicted"] + ["not_in_evidence"]*9)
    state["claim_workflow_version"] = "contradiction_first_v2"
    current = deepcopy(state["claim_judgements"])
    for field, value in [("status", "failed"), ("resource_version", 2),
                         ("review_id", "old-review"), ("run_id", "old-run"), ("resource_id", "sibling")]:
        changed = deepcopy(current)
        changed[-1][field] = value
        chosen, phase = select_revision_bad(state, changed + changed[:2]*5)
        assert phase == "contradiction"
        assert [j["verdict"] for j in chosen] == ["contradicted"]
    chosen, _ = select_revision_bad(state, current + current*2)
    assert len(chosen) == 10  # no duplicate instructions
    state["extracted_claims"][-1]["claim_type"] = "instructional"
    chosen, _ = select_revision_bad(state, current)
    assert [j["verdict"] for j in chosen] == ["contradicted"]


def test_gaps_of_an_uncontradicted_sibling_are_never_pulled_into_revision():
    from app.agents.resource_workflows.learning_documents.claim_routing import select_revision_bad
    state = staged_state(["contradicted"] + ["not_in_evidence"]*9)
    state["claim_workflow_version"] = "contradiction_first_v2"
    sibling = state["generated_resources"][0].model_copy(update={"resource_id": "sibling", "resource_spec_id": "other"})
    state["generated_resources"].append(sibling)
    state["review_result"]["review_ids"]["sibling"] = "other-review"
    for claim, judgement in zip(state["extracted_claims"][1:], state["claim_judgements"][1:]):
        claim.update(resource_id="sibling", review_id="other-review")
        judgement.update(resource_id="sibling", review_id="other-review")
    chosen, phase = select_revision_bad(state, state["claim_judgements"])
    assert phase == "contradiction"
    assert len(chosen) == 1 and chosen[0]["resource_id"] == "r"


def test_gap_counts_are_not_combined_between_two_contradicted_resources():
    from app.agents.resource_workflows.learning_documents.claim_routing import select_revision_bad
    state = staged_state(["contradicted"] + ["not_in_evidence"]*5)
    other = staged_state(["contradicted"] + ["not_in_evidence"]*5)
    state["claim_workflow_version"] = "contradiction_first_v2"
    state["generated_resources"].append(other["generated_resources"][0].model_copy(
        update={"resource_id":"other", "resource_spec_id":"other-spec"}))
    state["review_result"]["review_ids"]["other"] = "other-review"
    for index, (claim, judgement) in enumerate(zip(other["extracted_claims"], other["claim_judgements"])):
        claim.update(claim_id=f"clm_{index+100:032x}", resource_id="other", review_id="other-review")
        judgement.update(claim_id=claim["claim_id"], resource_id="other", review_id="other-review")
    state["extracted_claims"].extend(other["extracted_claims"])
    state["claim_judgements"].extend(other["claim_judgements"])
    chosen, phase = select_revision_bad(state, state["claim_judgements"])
    assert phase == "contradiction"
    assert len(chosen) == 2
    assert all(j["verdict"] == "contradicted" for j in chosen)


def test_gap_claim_and_judgement_bound_to_an_old_review_are_not_counted():
    from app.agents.resource_workflows.learning_documents.claim_routing import select_revision_bad
    state = staged_state(["contradicted"] + ["not_in_evidence"]*9)
    state["claim_workflow_version"] = "contradiction_first_v2"
    state["extracted_claims"][-1]["review_id"] = "old-review"
    state["claim_judgements"][-1]["review_id"] = "old-review"
    chosen, _ = select_revision_bad(state, state["claim_judgements"])
    assert [j["verdict"] for j in chosen] == ["contradicted"]


@pytest.mark.parametrize("gaps,threshold,wants_revision", [(8,8,False),(9,8,True),(19,8,True),(3,3,False),(4,3,True)])
def test_v3_gap_only_revision_uses_frozen_threshold_and_shared_budget(gaps, threshold, wants_revision):
    state = staged_state(["not_in_evidence"] * gaps)
    state.update(claim_workflow_version="contradiction_first_v3", claim_gap_revision_threshold=threshold)
    assert route_after_initial_claim_judge(state) == ("claim_decide" if wants_revision else "claim_evidence_retrieve")
    if wants_revision:
        state.update(claim_decide_node(state))
        prepared = prepare_claim_revision_node(state)
        assert prepared["claim_revision_count"] == 1
        assert prepared["claim_post_retrieval_revision_count"] == 0
        problems = prepared["constraints"]["generation_revision_inputs"]["spec"]["input"]["problems"]
        assert len(problems) == gaps and all(p["verdict"] == "not_in_evidence" for p in problems)
        state["claim_revision_count"] = 1
        assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"
        state["claim_judgements"][0]["verdict"] = "contradicted"
        assert route_after_initial_claim_judge(state) == "claim_decide"
        state.update(claim_decide_node(state))
        assert route_after_claim_decide(state) == "finalize"


def test_v3_post_stage_does_not_reopen_gap_pre_budget():
    state = staged_state(["not_in_evidence"]*19, after_retrieval=True)
    state["claim_workflow_version"] = "contradiction_first_v3"
    state.update(claim_decide_node(state))
    assert state["claim_revision_phase"] == "exhausted"
    assert route_after_claim_decide(state) == "finalize"


def test_v3_does_not_pool_gap_counts_between_resources():
    from app.agents.resource_workflows.learning_documents.claim_routing import select_revision_bad
    state = staged_state(["not_in_evidence"]*10)
    state["claim_workflow_version"] = "contradiction_first_v3"
    sibling = state["generated_resources"][0].model_copy(update={"resource_id":"sibling", "resource_spec_id":"sibling-spec"})
    state["generated_resources"].append(sibling)
    state["review_result"]["review_ids"]["sibling"] = "sibling-review"
    for c,j in zip(state["extracted_claims"][5:],state["claim_judgements"][5:]):
        c.update(resource_id="sibling",review_id="sibling-review")
        j.update(resource_id="sibling",review_id="sibling-review")
    assert select_revision_bad(state,state["claim_judgements"])[1] == "exhausted"
    assert route_after_initial_claim_judge(state) == "claim_evidence_retrieve"


def test_new_default_budgets_are_consumed_and_stop_at_three_and_two():
    from app.models.learning_documents.schemas import GenerateRequest
    from app.agents.resource_workflows.learning_documents.workflow import route_after_review, prepare_revision_node
    request = GenerateRequest(learner_id="learner", topic="test")
    state = staged_state(["contradicted"])
    state.update(max_iterations=request.max_iterations, claim_max_iterations=request.claim_max_iterations,
                 include_claim_check=False)
    for used in range(3):
        state["review_result"] = dict(decision="revise", issues=[], revision_instructions=[])
        assert state["revision_count"] == used
        assert route_after_review(state) == "prepare_revision"
        state.update(prepare_revision_node(state))
    state["review_result"] = dict(decision="revise", issues=[], revision_instructions=[])
    assert route_after_review(state) == "finalize"
    for used in range(3):
        state = staged_state(["contradicted"], total=used)
        state.update(claim_workflow_version=request.claim_workflow_version, claim_max_iterations=request.claim_max_iterations)
        state.update(claim_decide_node(state))
        assert route_after_claim_decide(state) == ("prepare_claim_revision" if used < 2 else "finalize")
        if used < 2:
            assert prepare_claim_revision_node(state)["claim_revision_count"] == used + 1
    assert request.claim_post_retrieval_max_iterations == 0
