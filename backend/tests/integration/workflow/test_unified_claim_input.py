"""T66 common semantics, structured boundaries, wire budgets and old snapshots."""

import json
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.budget import (
    freeze_policy,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.contracts import (
    select_contract,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.input_context import (
    GUIDANCE,
    GUIDANCE_V1,
    GUIDANCE_V3,
    GUIDANCE_V4,
    frozen_extension,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import (
    build_source,
    source_for_claims,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import (
    build_messages,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.merge import (
    validate_output_with_diagnostics,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.batching import (
    plan_batches,
    make_batch,
)
from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import (
    scan_units,
)
from app.models.reviews.claim_extraction import (
    ExtractionBatch,
    ExtractionUnit,
    BatchOutputV2,
    LargeBatchOutputV2,
    EstimatePolicy,
    digest,
    content_digest,
    LedgerSnapshot,
    validate_snapshot,
)
from app.models.reviews.claims import ClaimCandidate, RunClaimsResponse
from app.core.execution import execution_session
from app.core.llm.counting import CharacterEstimator
from tests.fakes.claim_extraction import (
    neutral_settings,
    prepare_ledger,
    state_for_extraction,
    extract_every_unit_v2,
    NeutralScriptedGateway,
    FixtureCounter,
    judge_all,
    snapshot_for,
)
from tests.integration.workflow.test_structured_claim_sources import setup_source
from tests.integration.workflow.test_claim_evidence_retrieval import (
    storage as supplement_storage,  # noqa: F401 - pytest fixture registration
)
from tests.unit.agents.test_correction_claim_input_v4 import contextual_setup


def enable(state, gateway, counter, *, locating=True, **updates):
    settings = neutral_settings(
        claim_extraction_input_version="unified_context_v1",
        claim_extraction_target_tokens=6144,
        claim_extraction_batch_claims=30,
        claim_extraction_source_locating_mode="exact_v1" if locating else None,
        claim_extraction_resource_claims=128,
        claim_extraction_max_calls=32,
        claim_extraction_max_attempts=64,
        claim_extraction_max_tokens=1000000,
        **updates,
    )
    policy = freeze_policy(
        settings,
        gateway,
        counter,
        correction=state["generated_resources"][0].resource_type == "个性化纠错训练包",
    )
    audit, repo = prepare_ledger(p=policy)
    state.update(snapshot_for(policy))
    return policy, audit, repo


def field_batch(source, suffix):
    f = next(f for f in source.fields if f["path"].endswith(suffix))
    return ExtractionBatch(
        batch_id="one",
        units=[
            ExtractionUnit(
                unit_id="u", kind="paragraph", start=f["start"], end=f["end"]
            )
        ],
    )


def test_new_capacity_and_old_wire_schema_identity():
    state, _, _, gateway, counter = state_for_extraction()
    old = freeze_policy(
        neutral_settings(claim_extraction_source_locating_mode="exact_v1"),
        gateway,
        counter,
    )
    old_hash = digest(old)
    old_schema = select_contract(old).output_schema.model_json_schema()
    policy, _, _ = enable(state, gateway, counter)
    assert (policy.target_tokens, policy.batch_claims) == (6144, 30)
    assert policy.input_contract == frozen_extension("claim-input-context-v1")
    assert select_contract(policy).output_schema is LargeBatchOutputV2
    assert GUIDANCE_V1 in select_contract(policy).prompt
    assert select_contract(old).output_schema is BatchOutputV2
    assert digest(old) == old_hash
    assert select_contract(old).output_schema.model_json_schema() == old_schema
    no_input = old.model_dump(mode="json")
    assert "input_contract" not in no_input
    assert digest(EstimatePolicy.model_validate(no_input)) == old_hash
    with pytest.raises(ValueError):
        select_contract(
            policy.model_copy(update={"input_contract": {"version": "unknown"}})
        )


@pytest.mark.parametrize("locating", [False, True])
@pytest.mark.parametrize("count", [21, 29, 30])
def test_batch_30_threshold_accepts_large_unit_without_changing_old_schemas(
    locating, count
):
    text = "".join(f"知识断言{i}。" for i in range(count))
    state, _, _, gateway, counter = state_for_extraction(text)
    policy, _, _ = enable(state, gateway, counter, locating=locating)
    r = state["generated_resources"][0]
    b = ExtractionBatch(
        batch_id="b",
        units=[ExtractionUnit(unit_id="u", kind="paragraph", start=0, end=len(text))],
    )
    claims = []
    offset = 0
    for i in range(count):
        raw = f"知识断言{i}。"
        entry = dict(claim_text=raw, source_text=raw, claim_type="factual")
        if not locating:
            entry.update(source_start=offset, source_end=offset + len(raw))
        offset += len(raw)
        claims.append(entry)
    schema = select_contract(policy).output_schema
    output = schema.model_validate(
        dict(
            resource_id=r.resource_id,
            resource_version=r.version,
            content_hash=content_digest(text),
            batch_id=b.batch_id,
            units=[
                dict(unit_id="u", status="claims", reason="独立知识", claims=claims)
            ],
        )
    )
    if count == 30:
        with pytest.raises(ValueError, match="cap reached"):
            validate_output_with_diagnostics(
                text, b, output, resource=r, policy=policy, allowed_nodes={"k"}
            )
    else:
        candidates, _ = validate_output_with_diagnostics(
            text, b, output, resource=r, policy=policy, allowed_nodes={"k"}
        )
        assert len(candidates) == count
    if locating:
        with pytest.raises(ValueError):
            BatchOutputV2.model_validate(output.model_dump(mode="json"))


@pytest.mark.parametrize(
    "kind", ["分阶测试题", "复习清单", "个性化纠错训练包", "实操指南"]
)
def test_sources_filter_nonknowledge_keep_exact_positions_and_rebuild(kind):
    if kind == "个性化纠错训练包":
        state, _, _, gateway, counter = contextual_setup()
    else:
        state, _, _, gateway, counter = setup_source(
            "分阶测试题" if kind == "分阶测试题" else "复习清单", locating=True
        )
    r = state["generated_resources"][0]
    if kind == "实操指南":
        from tests.unit.agents.test_practice_guide_v2 import _package
        from app.agents.resource_agents.practice import (
            render_practice_guide_markdown,
            _canonical_hash,
        )

        r.resource_type = kind
        p = _package()
        p["payload_hash"] = _canonical_hash(p)
        r.practice_guide_payload = p
        r.practice_guide_payload_hash = p["payload_hash"]
        r.content_text = render_practice_guide_markdown(p)
    policy, _, _ = enable(state, gateway, counter)
    source = build_source(r, policy)
    assert source.related_fields is not None
    assert (
        source_for_claims(
            r, [SimpleNamespace(extractor_prompt_version=source.prompt_version)]
        ).snapshot
        == source.snapshot
    )
    assert source.snapshot["payload_hash"]
    assert all(source.text[f["start"] : f["end"]] for f in source.fields)
    assert all(
        ".rubric[" not in f["path"] and not f["path"].endswith(".pass_criteria")
        for f in source.fields
    )
    if kind == "分阶测试题":
        assert all(f["role"] in {"answer", "answer_option"} for f in source.fields)
        assert "私有答案" in source.text and "私有答案" not in r.content_text
    if kind == "个性化纠错训练包":
        assert all(
            "learning_status" not in f["path"] and ".scenario" not in f["path"]
            for f in source.fields
        )
    # Instruction roles are not deterministically excluded: factual clauses remain auditable.
    f = source.fields[0]
    raw = source.text[f["start"] : f["end"]]
    candidate = ClaimCandidate(
        claim_text=raw,
        source_text=raw,
        source_start=f["start"],
        source_end=f["end"],
        claim_type="factual",
    )
    assert source.classify([candidate])[0].claim_type.value == "factual"
    with pytest.raises(ValueError):
        source.classify([candidate.model_copy(update={"source_start": f["start"] - 1})])


def test_explanation_carries_answer_as_readonly_and_context_cannot_be_cited():
    state, _, _, gateway, counter = contextual_setup()
    policy, _, _ = enable(state, gateway, counter)
    r = state["generated_resources"][0]
    s = build_source(r, policy)
    b = field_batch(s, "transfer.explanation")
    msg = build_messages(s.text, r, b, policy, {"k"})
    p = json.loads(msg[-1].content)
    related = p["structured_context"]["read_only_related_fields"]
    assert {x["path"].rsplit(".", 1)[1] for x in related} == {
        "scenario",
        "question",
        "reference_answer",
    }
    assert len({x["path"] for x in related}) == len(related)
    raw = next(x["text"] for x in related if x["path"].endswith(".scenario"))
    output = select_contract(policy).output_schema.model_validate(
        dict(
            resource_id=r.resource_id,
            resource_version=r.version,
            content_hash=content_digest(s.text),
            batch_id=b.batch_id,
            units=[
                dict(
                    unit_id="u",
                    status="claims",
                    reason="bad context quote",
                    claims=[
                        dict(claim_text=raw, source_text=raw, claim_type="factual")
                    ],
                )
            ],
        )
    )
    with pytest.raises(ValueError):
        validate_output_with_diagnostics(
            s.text, b, output, resource=r, policy=policy, allowed_nodes={"k"}
        )
    counter = CharacterEstimator(policy.estimator_parameters)
    full = counter.request_bound(
        msg, select_contract(policy).output_schema, policy.extractor_options
    )
    p["structured_context"]["read_only_related_fields"] = []
    msg[-1].content = json.dumps(p, ensure_ascii=False)
    assert (
        counter.request_bound(
            msg, select_contract(policy).output_schema, policy.extractor_options
        )
        < full
    )


def test_markdown_keeps_subject_error_premise_and_split_paragraph_context():
    text = (
        "# 技术说明\n\n本节讨论RAG。\n\n以下是错误观点：\n\n它能够保证所有答案正确。\n"
    )
    state, _, _, gateway, counter = state_for_extraction(text)
    policy, _, _ = enable(state, gateway, counter)
    r = state["generated_resources"][0]
    u = next(u for u in scan_units(text) if "它能够" in text[u.start : u.end])
    b = make_batch(text, [u], policy, counter)
    p = json.loads(build_messages(text, r, b, policy, {"k"})[-1].content)
    background = "".join(p["read_only_context"])
    assert "本节讨论RAG" in background and "以下是错误观点" in background
    assert "它能够" not in background
    assert text[u.start : u.end] == p["target_units"][0]["text"]
    # A forced split retains its own leading premise.
    first = u.start + len("它能够")
    b = ExtractionBatch(
        batch_id="split",
        units=[
            ExtractionUnit(unit_id="tail", kind="paragraph", start=first, end=u.end)
        ],
    )
    p = json.loads(build_messages(text, r, b, policy, {"k"})[-1].content)
    assert "它能够" in "".join(p["read_only_context"])


def test_scripted_full_extraction_judge_and_durable_restore_with_new_markers():
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
        claim_judge_node,
    )

    state, _, _, gateway, counter = setup_source("分阶测试题", locating=True)
    policy, _, repo = enable(state, gateway, counter)
    gateway.outcomes = [extract_every_unit_v2] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(
            claim_extract_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
        assert state["claim_failed_resource_ids"] == []
        saved = repo.get(state["run_id"])
        rebuilt = LedgerSnapshot.model_validate(saved.model_dump(mode="json"))
        validate_snapshot(policy.strategy, state, rebuilt)
        gateway.outcomes = [judge_all]
        state.update(
            claim_judge_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
    assert state["claim_metrics"]["r"]["metric_status"] == "complete"
    from app.services.reviews.assessment_privacy import public_claims
    from app.models.reviews.claims import ClaimRecord, ClaimJudgement

    resp = RunClaimsResponse(
        run_id=state["run_id"],
        claims=[ClaimRecord.model_validate(x) for x in state["extracted_claims"]],
        judgements=[
            ClaimJudgement.model_validate(x) for x in state["claim_judgements"]
        ],
    )
    assert public_claims(resp).claims == [] and public_claims(resp).judgements == []


def test_capacity30_density_changes_but_old_frozen_packing_is_stable():
    from tests.unit.agents.test_claim_density_batching import with_policy, plan

    old = with_policy(density={}, batch_claims=20)
    old_hash = digest(old)
    new = old.model_copy(update={"target_tokens": 6144, "batch_claims": 30})
    text = "甲" * 399 + "\n\n" + "乙" * 400
    assert len(plan(text, old)) == 2
    assert len(plan(text, new)) == 1
    assert digest(old) == old_hash and len(plan(text, old)) == 2


@pytest.mark.parametrize("count", [21, 29])
def test_large_output_survives_serialization_and_actual_judge(count):
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
        claim_judge_node,
    )

    text = "".join(f"知识{i}。" for i in range(count))
    state, _, _, gateway, counter = state_for_extraction(text)
    policy, _, repo = enable(state, gateway, counter)

    def extractor(call):
        p = json.loads(call["messages"][-1].content)
        units = []
        for u in p["target_units"]:
            if u["kind"] == "paragraph":
                claims = [
                    dict(
                        claim_text=f"知识{i}。",
                        source_text=f"知识{i}。",
                        claim_type="factual",
                    )
                    for i in range(count)
                ]
                units.append(
                    dict(
                        unit_id=u["unit_id"],
                        status="claims",
                        reason="独立断言",
                        claims=claims,
                    )
                )
            else:
                units.append(
                    dict(
                        unit_id=u["unit_id"],
                        status="structure",
                        reason="结构",
                        claims=[],
                    )
                )
        return {
            k: p[k]
            for k in ("resource_id", "resource_version", "content_hash", "batch_id")
        } | {"units": units}

    gateway.outcomes = [extractor] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(
            claim_extract_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
        assert len(state.get("extracted_claims", [])) == count, state.get("errors")
        saved = repo.get(state["run_id"])
        rebuilt = LedgerSnapshot.model_validate_json(saved.model_dump_json())
        validate_snapshot(policy.strategy, state, rebuilt)
        # Persisted response content is immutable even across carrier classes.
        result = next(iter(rebuilt.state.results.values()))
        output = next(iter(result.outputs.values()))
        assert len(output.units[0].claims) == count
        gateway.outcomes = [judge_all]
        state.update(
            claim_judge_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
    assert state["claim_metrics"]["r"]["supported_claim_total"] == count


@pytest.mark.parametrize(
    "kind", ["分阶测试题", "复习清单", "个性化纠错训练包", "实操指南"]
)
def test_common_rules_cannot_drop_contradicted_actual_knowledge(kind, monkeypatch):
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
        claim_judge_node,
        claim_decide_node,
    )
    from app.agents.resource_workflows.learning_documents.workflow import decide_node

    if kind == "个性化纠错训练包":
        state, _, _, gateway, counter = contextual_setup()
    else:
        state, _, _, gateway, counter = setup_source(
            "分阶测试题" if kind == "分阶测试题" else "复习清单", locating=True
        )
    r = state["generated_resources"][0]
    if kind == "实操指南":
        from tests.unit.agents.test_practice_guide_v2 import _package
        from app.agents.resource_agents.practice import (
            render_practice_guide_markdown,
            _canonical_hash,
        )

        r.resource_type = kind
        p = json.loads(json.dumps(_package(1)).replace("ev-practice", "ev"))
        p["payload_hash"] = _canonical_hash(p)
        r.practice_guide_payload = p
        r.practice_guide_payload_hash = p["payload_hash"]
        r.content_text = render_practice_guide_markdown(p)
    policy, _, repo = enable(state, gateway, counter)
    gateway.outcomes = [extract_every_unit_v2] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(
            claim_extract_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
        assert state.get("extracted_claims"), state.get("errors")

        def contradicted(call):
            out = judge_all(call)
            chosen = next(j for j in out["judgements"] if j["verdict"] == "supported")
            chosen["verdict"] = "contradicted"
            return out

        gateway.outcomes = [contradicted]
        state.update(
            claim_judge_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
    assert state["claim_metrics"]["r"]["contradicted_claim_total"] == 1
    state["claim_max_iterations"] = 0
    state.update(claim_decide_node(state))
    assert (
        decide_node(state)["generated_resources"][0].publication_status == "unpublished"
    )


def test_plain_context_budget_is_bounded_and_missing_context_is_explicit():
    text = "# 说明\n\n" + "甲" * 200 + "\n\n它描述了某个机制。"
    state, _, _, gateway, counter = state_for_extraction(text)
    policy, _, _ = enable(state, gateway, counter)
    policy = policy.model_copy(update={"context_tokens": 20})
    u = next(u for u in scan_units(text) if "它描述" in text[u.start : u.end])
    batch = ExtractionBatch(batch_id="b", units=[u])
    p = json.loads(
        build_messages(text, state["generated_resources"][0], batch, policy, {"k"})[
            -1
        ].content
    )
    assert p["context_status"] == "budget_limited"
    assert (
        sum(
            CharacterEstimator(policy.estimator_parameters).count_text(v)
            for v in p["read_only_context"]
        )
        <= 20
    )
    assert p["target_units"][0]["text"] == text[u.start : u.end]


def test_split_json_summary_keeps_its_own_subject_without_copying_target():
    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    policy, _, _ = enable(state, gateway, counter)
    r = state["generated_resources"][0]
    source = build_source(r, policy)
    field = next(f for f in source.fields if f["path"].endswith(".knowledge_summary"))
    start = source.text.index("每次作答", field["start"])
    batch = ExtractionBatch(
        batch_id="split",
        units=[
            ExtractionUnit(
                unit_id="tail", kind="paragraph", start=start, end=field["end"]
            )
        ],
    )
    payload = json.loads(
        build_messages(source.text, r, batch, policy, {"k"})[-1].content
    )
    context = payload["structured_context"]["read_only_field_context"]
    assert len(context) == 1 and context[0]["path"] == field["path"]
    assert "节点 A" in context[0]["text"]
    assert "每次作答" not in context[0]["text"]
    assert payload["target_units"][0]["text"] == source.text[start : field["end"]]


@pytest.mark.parametrize("kind", ["复习清单", "实操指南", "个性化纠错训练包"])
def test_new_policy_keeps_historical_markdown_only_resources(kind):
    state, _, _, gateway, counter = state_for_extraction("RAG不能保证所有答案正确。")
    resource = state["generated_resources"][0]
    resource.resource_type = kind
    policy, _, _ = enable(state, gateway, counter)
    source = build_source(resource, policy)
    assert source.snapshot is None and source.text == resource.content_text


@pytest.mark.parametrize(
    "marker",
    [
        "structured-checklist-context-v99",
        "structured-assessment-context-v99",
        "structured-correction-context-v99",
        "structured-practice-context-v99",
    ],
)
def test_unknown_source_markers_cannot_silently_use_plain_markdown(marker):
    state, _, _, _, _ = state_for_extraction()
    with pytest.raises(ValueError, match="unknown (structured|checklist)"):
        source_for_claims(
            state["generated_resources"][0],
            [SimpleNamespace(extractor_prompt_version=marker)],
        )


def test_new_prompt_removes_ambiguous_historical_shortcut_without_changing_old_prompt():
    state, _, _, gateway, counter = state_for_extraction()
    policy, _, _ = enable(state, gateway, counter)
    text = select_contract(policy).prompt
    assert "主观意见、假设、过渡语和题干/干扰项用 non_factual" not in text
    assert "answer_proposition" in text and "claim_text写明否定关系" in text
    old = freeze_policy(neutral_settings(), gateway, counter)
    assert (
        "主观意见、假设、过渡语和题干/干扰项用 non_factual"
        in select_contract(old).prompt
    )


def test_v2_prompt_clarifies_local_examples_and_independent_claims_without_changing_v1():
    _, _, _, gateway, counter = state_for_extraction()
    v1 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v1", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    v2 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v2", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    assert v1.input_contract == frozen_extension("claim-input-context-v1")
    assert v2.input_contract == frozen_extension("claim-input-context-v2")
    old_prompt = select_contract(v1).prompt
    new_prompt = select_contract(v2).prompt
    assert GUIDANCE_V1 in old_prompt and GUIDANCE not in old_prompt
    assert GUIDANCE in new_prompt
    assert "问题二没有答案" in new_prompt
    assert "可独立判断对错的知识断言" in new_prompt
    assert "source_text仍逐字引用目标原文" in new_prompt
    assert v1.source_locating.extractor_prompt_hash == digest(old_prompt)
    assert v2.source_locating.extractor_prompt_hash == digest(new_prompt)


def test_v3_uses_shared_local_artifact_rule_and_keeps_v2_prompt():
    _, _, _, gateway, counter = state_for_extraction()
    v2 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v2", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    v3 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v3", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    assert v2.input_contract == frozen_extension("claim-input-context-v2")
    assert v3.input_contract == frozen_extension("claim-input-context-v3")
    assert GUIDANCE in select_contract(v2).prompt
    assert GUIDANCE_V3 not in select_contract(v2).prompt
    assert GUIDANCE_V3 in select_contract(v3).prompt
    assert "当前资源自身的参数选择" in select_contract(v3).prompt
    assert v2.source_locating.extractor_prompt_hash == digest(select_contract(v2).prompt)


def test_v4_separates_synthetic_case_from_independent_technical_knowledge():
    _, _, _, gateway, counter = state_for_extraction()
    v3 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v3", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    v4 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v4", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    assert v3.input_contract == frozen_extension("claim-input-context-v3")
    assert v4.input_contract == frozen_extension("claim-input-context-v4")
    assert GUIDANCE_V3 in select_contract(v3).prompt
    assert GUIDANCE_V4 not in select_contract(v3).prompt
    prompt = select_contract(v4).prompt
    assert "合成/虚构案例的文档" in prompt
    assert "只将能够脱离案例编号" in prompt
    assert "只负责" in prompt
    assert "source_text仍须是目标字段中的连续逐字原文" in prompt
    assert v3.source_locating.extractor_prompt_hash == digest(select_contract(v3).prompt)
    assert v4.source_locating.extractor_prompt_hash == digest(prompt)


def test_v3_practice_code_is_read_only_and_v2_practice_restores_old_source():
    from app.agents.resource_workflows.learning_documents.claim_extraction.unified_sources import build_source as unified_source
    from app.models.reviews.claims import UNIFIED_PRACTICE_SOURCE, UNIFIED_PRACTICE_SOURCE_V2

    from tests.unit.agents.test_practice_guide_v2 import _package
    from app.agents.resource_agents.practice import render_practice_guide_markdown, _canonical_hash

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package()
    package["practice"]["steps"][0]["code_blocks"] = [{
        "language": "python", "code": "chunk_size = 50\nprint(chunk_size)",
        "purpose": "演示本次代码的切分参数。", "evidence_ids": ["ev-practice"],
    }]
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    v2 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v2", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    v3 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v3", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    old = build_source(resource, v2)
    new = build_source(resource, v3)
    assert old.prompt_version == UNIFIED_PRACTICE_SOURCE
    assert new.prompt_version == UNIFIED_PRACTICE_SOURCE_V2
    assert any(f["role"] == "code" for f in old.fields)
    assert not any(f["role"] == "code" for f in new.fields)
    assert any(f["role"] == "code" for f in new.related_fields)
    assert any(f["role"] == "verification_requirement" for f in new.fields)
    payload = json.loads(build_messages(new.text, resource, field_batch(new, ".purpose"), v3, {"k"})[-1].content)
    related = payload["structured_context"]["read_only_related_fields"]
    assert any(f["role"] == "code" and "chunk_size = 50" in f["text"] for f in related)
    assert all("chunk_size = 50" not in unit["text"] for unit in payload["target_units"])
    assert unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE).text == old.text
    assert unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE_V2).text == new.text
    assert source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=UNIFIED_PRACTICE_SOURCE)]).text == old.text
    assert source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=UNIFIED_PRACTICE_SOURCE_V2)]).text == new.text


def test_v4_practice_keeps_mixed_targets_and_binds_synthetic_scenario():
    from app.agents.resource_workflows.learning_documents.claim_extraction.unified_sources import build_source as unified_source
    from app.models.reviews.claims import UNIFIED_PRACTICE_SOURCE_V3
    from tests.unit.agents.test_practice_guide_v2 import _package
    from app.agents.resource_agents.practice import render_practice_guide_markdown, _canonical_hash

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package()
    package["preparation"]["goal"] = "准备一个虚构问答场景。"
    package["preparation"]["items"][0] = "lab-C 讲关键词和向量召回，RRF 按排名融合。"
    package["practice"]["steps"][0]["instruction_text"] = "若换成截止日期问题，检索仍可能返回 lab-B；向量库超时属于依赖故障。"
    package["reflection"]["summary"] = "本次 lab-B 已被选中；检索只负责找到资料。"
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    v4 = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v4", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    source = build_source(resource, v4)
    assert source.prompt_version == UNIFIED_PRACTICE_SOURCE_V3
    assert any(f["path"] == "preparation.items[0]" and f["role"] == "instruction" for f in source.fields)
    assert "RRF 按排名融合" in source.text
    assert "检索只负责找到资料" in source.text
    assert not any(f["role"] == "code" for f in source.fields)
    for suffix in ("preparation.items[0]", "practice.steps[0].instruction_text", "reflection.summary"):
        payload = json.loads(build_messages(source.text, resource, field_batch(source, suffix), v4, {"k"})[-1].content)
        assert any("虚构问答场景" in f["text"] for f in payload["structured_context"]["read_only_related_fields"])
    assert unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE_V3).text == source.text
    assert source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=UNIFIED_PRACTICE_SOURCE_V3)]).snapshot == source.snapshot


def test_v4_practice_keeps_real_procedure_knowledge_as_target():
    from tests.unit.agents.test_practice_guide_v2 import _package
    from app.agents.resource_agents.practice import render_practice_guide_markdown, _canonical_hash

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package()
    package["preparation"]["goal"] = "准备真实运行环境并检查检索配置。"
    package["preparation"]["items"][0] = "RRF 按候选排名融合，不直接相加原始分数。"
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    policy = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v4", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    source = build_source(resource, policy)
    payload = json.loads(build_messages(source.text, resource, field_batch(source, "preparation.items[0]"), policy, {"k"})[-1].content)
    assert any("RRF 按候选排名融合" in unit["text"] for unit in payload["target_units"])
    assert any("真实运行环境" in field["text"] for field in payload["structured_context"]["read_only_related_fields"])


def test_executable_practice_package_keeps_code_out_of_claim_targets():
    from tests.unit.agents.test_practice_guide_v2 import _package
    from app.agents.resource_agents.practice import render_practice_guide_markdown, _canonical_hash

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package(1, version="4.0")
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    policy = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v4", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    source = build_source(resource, policy)
    assert any(field["role"] == "code" for field in source.related_fields)
    assert all(field["role"] != "code" for field in source.fields)
    assert any(field["path"].endswith(".verification") for field in source.fields)


def test_v5_practice_claim_targets_exclude_local_verification_but_keep_knowledge():
    from app.agents.resource_workflows.learning_documents.claim_extraction.unified_sources import build_source as unified_source
    from app.models.reviews.claims import UNIFIED_PRACTICE_SOURCE_V3, UNIFIED_PRACTICE_SOURCE_V4
    from tests.unit.agents.test_practice_guide_v2 import _package
    from app.agents.resource_agents.practice import render_practice_guide_markdown, _canonical_hash

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package(1, version="4.0")
    package["preparation"]["items"][0] = "RRF 按候选排名融合。"
    package["practice"]["steps"][0]["instruction_text"] = "本次集合字段包括 id 和 text；RRF 按排名融合。"
    package["practice"]["steps"][0]["verification"] = "运行后应生成 rag_demo.db。"
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    old = unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE_V3)
    policy = freeze_policy(neutral_settings(claim_extraction_input_version="unified_context_v5", claim_extraction_source_locating_mode="exact_v1"), gateway, counter)
    source = build_source(resource, policy)
    assert source.prompt_version == UNIFIED_PRACTICE_SOURCE_V4
    assert any(f["path"] == "preparation.items[0]" for f in source.fields)
    assert any(f["path"] == "practice.steps[0].instruction_text" for f in source.fields)
    assert not any(f["path"].endswith(".verification") for f in source.fields)
    assert any(f["path"].endswith(".verification") for f in source.related_fields)
    assert any(f["path"].endswith(".verification") for f in old.fields)
    messages = build_messages(source.text, resource, field_batch(source, "practice.steps[0].instruction_text"), policy, {"k"})
    payload = json.loads(messages[-1].content)
    assert "RRF 按排名融合" in str(payload["target_units"])
    assert "本次实现" in messages[0].content
    assert unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE_V4).snapshot == source.snapshot


def test_v5_practice_material_is_read_only_context_for_the_referencing_step():
    from app.agents.resource_agents.practice import _canonical_hash, render_practice_guide_markdown
    from app.agents.resource_workflows.learning_documents.claim_extraction.unified_sources import build_source as unified_source
    from app.models.reviews.claims import UNIFIED_PRACTICE_SOURCE_V5
    from tests.unit.agents.test_practice_guide_v2 import _package

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package(1, version="5.0")
    package["preparation"]["materials"] = [{"name": "练习短文", "content": "假设回答声称截止日期为 6 月 30 日。"}]
    package["practice"]["steps"][0]["instruction_text"] = "读取练习短文；RRF 按候选排名融合。"
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    policy = freeze_policy(neutral_settings(
        claim_extraction_input_version="unified_context_v5",
        claim_extraction_source_locating_mode="exact_v1",
    ), gateway, counter)

    source = build_source(resource, policy)
    assert source.prompt_version == UNIFIED_PRACTICE_SOURCE_V5
    assert not any("preparation.materials" in field["path"] for field in source.fields)
    assert any(field["path"] == "preparation.materials[0].content" for field in source.related_fields)
    payload = json.loads(build_messages(
        source.text, resource, field_batch(source, "practice.steps[0].instruction_text"), policy, {"k"}
    )[-1].content)
    assert any("RRF 按候选排名融合" in item["text"] for item in payload["target_units"])
    assert any("截止日期" in item["text"] for item in payload["structured_context"]["read_only_related_fields"])
    assert unified_source(resource, marker=UNIFIED_PRACTICE_SOURCE_V5).snapshot == source.snapshot


def test_v6_practice_steps_keep_code_as_context_without_material_field():
    from app.agents.resource_agents.practice import _canonical_hash, render_practice_guide_markdown
    from app.agents.resource_workflows.learning_documents.claim_extraction.unified_sources import build_source as unified_source
    from app.models.reviews.claims import UNIFIED_PRACTICE_SOURCE_V4
    from tests.unit.agents.test_practice_guide_v2 import _package

    state, _, _, gateway, counter = setup_source("复习清单", locating=True)
    resource = state["generated_resources"][0]
    resource.resource_type = "实操指南"
    package = _package(2, version="6.0")
    package["payload_hash"] = _canonical_hash(package)
    resource.practice_guide_payload = package
    resource.practice_guide_payload_hash = package["payload_hash"]
    resource.content_text = render_practice_guide_markdown(package)
    policy = freeze_policy(neutral_settings(
        claim_extraction_input_version="unified_context_v5",
        claim_extraction_source_locating_mode="exact_v1",
    ), gateway, counter)
    source = build_source(resource, policy)
    assert source.prompt_version == UNIFIED_PRACTICE_SOURCE_V4
    assert not any("materials" in field["path"] for field in [*source.fields, *source.related_fields])
    assert any(field["path"] == "practice.steps[1].code_blocks[0].code" for field in source.related_fields)
    assert not any(field["path"].endswith(".code") for field in source.fields)


def test_real_estimator_packs_complete_new_requests_under_6k():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import (
        check_window,
    )

    state, _, _, gateway, _ = state_for_extraction(
        "本节讨论RAG。\n\n" + ("它在生成前检索外部知识。\n\n" * 40)
    )
    counter = CharacterEstimator()
    policy, _, _ = enable(state, gateway, counter)
    resource = state["generated_resources"][0]
    text = resource.content_text
    schema = select_contract(policy).output_schema

    def request_count(batch):
        return check_window(
            policy,
            counter,
            build_messages(text, resource, batch, policy, {"k"}),
            schema,
            policy.extractor_options,
        )

    batches = plan_batches(
        text,
        policy,
        counter,
        fits=lambda batch: request_count(batch) <= policy.target_tokens,
    )
    assert batches
    assert all(request_count(b) <= 6144 for b in batches)
    assert "".join(text[u.start : u.end] for b in batches for u in b.units) == text


def test_expanded_output_remains_immutable_after_persisted_roundtrip():
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
    )
    from app.models.reviews.claim_extraction import validate_estimate_transition

    state, _, _, gateway, counter = setup_source("分阶测试题", locating=True)
    _, _, repo = enable(state, gateway, counter)
    gateway.outcomes = [extract_every_unit_v2] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(
            claim_extract_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
    saved = repo.get(state["run_id"]).state
    restored = type(saved).model_validate_json(saved.model_dump_json())
    validate_estimate_transition(saved, restored)
    tampered = restored.model_copy(deep=True)
    result = next(iter(tampered.results.values()))
    output = next(iter(result.outputs.values()))
    unit = next(unit for unit in output.units if unit.claims)
    unit.claims[0] = unit.claims[0].model_copy(
        update={"claim_text": "篡改已经完成的输出。"}
    )
    with pytest.raises(ValueError):
        validate_estimate_transition(saved, tampered)


@pytest.mark.parametrize("strategy", ["compat", "resource_issue_v1"])
def test_new_claim_input_dispatch_coexists_with_both_ordinary_review_strategies(
    strategy, monkeypatch
):
    from app.services.generation import generation, jobs
    from app.services.generation.generation import GenerationService
    from app.services.generation.jobs import GenerationJobService
    from app.db.audit.memory import MemoryAuditRepository
    from app.models.learning_documents.schemas import LearnerProfile, GenerateRequest

    settings = neutral_settings(
        resource_review_strategy=strategy,
        resource_review_context_tokens=129024,
        claim_extraction_input_version="unified_context_v1",
        claim_extraction_batch_claims=30,
        claim_extraction_target_tokens=6144,
    )
    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    gateway, counter = NeutralScriptedGateway([]), FixtureCounter()
    service = GenerationService(
        SimpleNamespace(),
        SimpleNamespace(),
        audit_repo=MemoryAuditRepository(),
        claim_extraction_gateway=gateway,
        claim_extraction_counter=counter,
    )
    learner = LearnerProfile(
        learner_id="l",
        learner_type="test",
        education="本科",
        major="软件",
        learning_goal="Python",
    )
    request = GenerateRequest(
        learner_id="l",
        topic="Python",
        resource_types=["讲义"],
        include_claim_check=True,
    )
    dispatch = GenerationJobService(SimpleNamespace(), service)._dispatch_snapshot(
        learner, request
    )
    policy = EstimatePolicy.model_validate(dispatch["claim_extraction_policy"])
    assert policy.input_contract == frozen_extension("claim-input-context-v1") and policy.batch_claims == 30
    assert dispatch["claim_extraction_policy_hash"] == digest(policy)
    assert ("resource_issue" in dispatch["workflow_version"]) == (
        strategy == "resource_issue_v1"
    )


def test_new_source_roundtrips_sql_and_public_api_hides_private_answers(tmp_path):
    from tests.fakes.persistence import sqlite_repository
    from app.core.execution import ExecutionFence, execution_fence
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
        claim_judge_node,
    )
    from app.api.runs.run_queries import get_run_claims
    from starlette.requests import Request

    state, _, _, gateway, counter = setup_source("分阶测试题", locating=True)
    policy, _, _ = enable(state, gateway, counter)
    audit, engine = sqlite_repository(tmp_path)
    try:
        with (
            execution_fence(ExecutionFence(state["run_id"], "owner")),
            execution_session(state["run_id"], "owner"),
        ):
            _, repo = prepare_ledger(audit, p=policy)
            gateway.outcomes = [extract_every_unit_v2] * 32
            state.update(
                claim_extract_node(
                    state,
                    llm_gateway=gateway,
                    claim_extraction_repository=repo,
                    claim_extraction_counter=counter,
                )
            )
            restored = repo.get(state["run_id"])
            validate_snapshot(policy.strategy, state, restored)
            assert (
                next(iter(restored.state.results.values())).source_snapshot[
                    "prompt_version"
                ]
                == "structured-assessment-context-v2"
            )
            gateway.outcomes = [judge_all]
            state.update(
                claim_judge_node(
                    state,
                    llm_gateway=gateway,
                    claim_extraction_repository=repo,
                    claim_extraction_counter=counter,
                )
            )
        response = RunClaimsResponse(
            run_id=state["run_id"],
            claims=state["extracted_claims"],
            judgements=state["claim_judgements"],
            resource_metrics=state["claim_metrics"],
        )
        assert response.claims
        container = SimpleNamespace(
            run_query_service=lambda: SimpleNamespace(get_claims=lambda _: response)
        )
        request = Request(
            {"type": "http", "app": SimpleNamespace(container=container), "state": {}}
        )
        public = get_run_claims(state["run_id"], request)
        assert (
            public.claims == []
            and public.judgements == []
            and public.resource_metrics == response.resource_metrics
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["分阶测试题", "复习清单"])
def test_new_source_missing_claim_supplement_rejudge_can_publish(
    kind, supplement_storage, monkeypatch
):
    from app.agents.resource_workflows.learning_documents.claim_review_agent import (
        claim_extract_node,
        claim_judge_node,
        claim_decide_node,
    )
    from app.agents.resource_workflows.learning_documents.workflow import decide_node
    from tests.integration.workflow.test_claim_evidence_retrieval import (
        _call_retrieve,
        _call_rejudge,
        _new_evidence,
        ObserverGateway,
        policy as retrieval_policy,
        query_hash,
    )
    from tests.fakes.evidence import ScriptedEvidenceRetriever
    from app.models.knowledge.knowledge import EvidenceBatch, RetrievalStatus

    state, _, _, gateway, counter = setup_source(kind, locating=True)
    _, _, repo = enable(state, gateway, counter)
    gateway.outcomes = [extract_every_unit_v2] * 32
    with execution_session(state["run_id"], "owner"):
        state.update(
            claim_extract_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )

        def judge_missing(call):
            result = judge_all(call)
            target = next(
                j for j in result["judgements"] if j["verdict"] == "supported"
            )
            target.update(verdict="not_in_evidence", evidence_ids=[])
            return result

        gateway.outcomes = [judge_missing]
        state.update(
            claim_judge_node(
                state,
                llm_gateway=gateway,
                claim_extraction_repository=repo,
                claim_extraction_counter=counter,
            )
        )
    # Bind to the isolated supplement repository, never a user's live run.
    state["run_id"] = state["generated_resources"][0].run_id = "run-claim"
    for row in state["extracted_claims"] + state["claim_judgements"]:
        row["run_id"] = "run-claim"
    frozen = retrieval_policy()
    state.update(
        knowledge_base_id="kb-fixture",
        include_claim_evidence_retrieval=True,
        claim_evidence_retrieval_policy=frozen.model_dump(mode="json"),
        claim_evidence_retrieval_policy_hash=frozen.policy_hash,
        claim_workflow_version="contradiction_first_v3",
    )
    target = next(
        j["claim_id"]
        for j in state["claim_judgements"]
        if j["verdict"] == "not_in_evidence"
    )

    def query(call):
        payload = json.loads(call["messages"][-1].content)
        return {
            "batch_id": payload["batch_id"],
            "input_hash": payload["input_hash"],
            "items": [{"claim_id": target, "queries": [{"text": "RAG知识核验"}]}],
        }

    supplement_gateway = ObserverGateway([query])
    item = _new_evidence("chunk-unified", "冻结的补充事实证据。", "RAG知识核验")
    retriever = ScriptedEvidenceRetriever(
        [
            EvidenceBatch(
                status=RetrievalStatus.AVAILABLE,
                knowledge_base_id="kb-fixture",
                evidence=[item],
                query_hashes=[query_hash("RAG知识核验")],
                query_count=1,
                candidate_count=1,
                dropped_candidate_count=0,
                config_hash="9" * 64,
            )
        ]
    )
    state.update(
        _call_retrieve(state, supplement_storage, supplement_gateway, retriever)
    )
    assert state["claim_evidence_retrieval_refs"][0]["status"] == "rejudging"
    supplement_gateway.outcomes = [
        {
            "judgements": [
                {
                    "claim_id": target,
                    "verdict": "supported",
                    "evidence_ids": [item.evidence_id],
                    "reason": "新增冻结证据支持",
                    "confidence": 0.9,
                }
            ]
        }
    ]
    state.update(_call_rejudge(state, supplement_storage, supplement_gateway))
    assert state["claim_metrics"]["r"]["not_in_evidence_claim_total"] == 0
    state.update(claim_decide_node(state))
    monkeypatch.setattr(
        "app.agents.resource_workflows.learning_documents.workflow.get_settings",
        lambda: SimpleNamespace(claim_partial_publish=False),
    )
    assert (
        decide_node(state)["generated_resources"][0].publication_status == "published"
    )


@pytest.mark.parametrize(
    "kind", ["分阶测试题", "复习清单", "个性化纠错训练包", "实操指南"]
)
def test_new_source_targets_rebuild_exact_revision_spans(kind):
    from app.agents.resource_workflows.learning_documents.revision_inputs import (
        build_claim_review_revision_input,
    )
    from app.models.reviews.claims import ClaimJudgementCandidate, materialize_judgements

    if kind == "个性化纠错训练包":
        state, _, _, gateway, counter = contextual_setup()
    else:
        state, _, _, gateway, counter = setup_source(
            "分阶测试题" if kind == "分阶测试题" else "复习清单", locating=True
        )
    resource = state["generated_resources"][0]
    if kind == "实操指南":
        from tests.unit.agents.test_practice_guide_v2 import _package
        from app.agents.resource_agents.practice import (
            render_practice_guide_markdown,
            _canonical_hash,
        )

        resource.resource_type = kind
        package = json.loads(json.dumps(_package(1)).replace("ev-practice", "ev"))
        package["payload_hash"] = _canonical_hash(package)
        resource.practice_guide_payload = package
        resource.practice_guide_payload_hash = package["payload_hash"]
        resource.content_text = render_practice_guide_markdown(package)
    policy, _, _ = enable(state, gateway, counter)
    source = build_source(resource, policy)
    field = source.fields[0]
    raw = source.text[field["start"] : field["end"]]
    from app.models.reviews.claims import materialize_claims

    claims = materialize_claims(
        candidates=[
            ClaimCandidate(
                claim_text=raw,
                source_text=raw,
                source_start=field["start"],
                source_end=field["end"],
                claim_type="factual",
            )
        ],
        resource_content=source.text,
        resource_id=resource.resource_id,
        resource_version=resource.version,
        run_id=state["run_id"],
        review_id="review",
        extractor_prompt_version=source.prompt_version,
        extractor_model="fake-model",
        allowed_evidence_ids={"ev"},
        allowed_knowledge_point_ids={"k"},
    )
    judgements = materialize_judgements(
        claims=claims,
        candidates=[
            ClaimJudgementCandidate(
                claim_id=claims[0].claim_id,
                verdict="contradicted",
                evidence_ids=["ev"],
                reason="冻结证据反驳该知识",
                confidence=0.9,
            )
        ],
        allowed_evidence_ids={"ev"},
        judge_prompt_version="synthetic",
        judge_model="fake-model",
    )
    revision = build_claim_review_revision_input(
        resource_spec_id="spec",
        resource=resource,
        targets=["k"],
        claims=claims,
        judgements=judgements,
        evidence=state["retrieved_evidence"],
    )
    assert revision.problems and revision.previous_structured_payload
    assert revision.previous_text == source.text
    assert all(
        revision.previous_text[s.source_start : s.source_end] == s.source_text
        for s in revision.spans
    )
