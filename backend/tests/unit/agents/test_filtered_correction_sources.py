"""Correction field filtering without weakening source or teaching fact checks."""

import copy
import json
from types import SimpleNamespace

import pytest

from app.core.learning_documents.correction_package import correction_audit_source
from app.models.reviews.claims import ClaimCandidate
from app.agents.resource_workflows.learning_documents.claim_extraction import correction_sources as legacy
from app.agents.resource_workflows.learning_documents.claim_extraction import filtered_correction_sources as filtered
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import build_source, source_for_claims
from app.agents.resource_workflows.learning_documents.claim_extraction.segmentation import scan_units
from app.agents.resource_workflows.learning_documents.claim_extraction.batching import make_batch
from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.builder import build_messages
from app.agents.resource_workflows.learning_documents.claim_extraction.merge import validate_output
from tests.integration.workflow.test_structured_correction_package import setup_source
from tests.fakes.claim_extraction import extract_every_unit_v2, neutral_settings


def candidate(text, start, end):
    value = text[start:end]
    return ClaimCandidate(claim_text=value, claim_type="factual", source_text=value,
                          source_start=start, source_end=end)


def test_new_freeze_selects_v2_and_v1_source_snapshot_is_unchanged():
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    state, _, repo, gateway, counter = setup_source()
    resource = state["generated_resources"][0]
    old_policy = repo.get(state["run_id"]).policy
    old_source = build_source(resource, old_policy)
    original = correction_audit_source(legacy.validated_correction_package(resource))
    assert old_source.text == original.text
    assert old_source.prompt_version == legacy.PROMPT_VERSION
    assert "excluded_fields" not in old_source.snapshot
    new_policy = freeze_policy(neutral_settings(), gateway, counter, correction=True)
    from app.agents.resource_workflows.learning_documents.claim_extraction import contextual_correction_sources as contextual
    assert new_policy.correction_sources == contextual.frozen_extension()
    # New policy is for newly generated V2 packages; the historical V1 source
    # remains readable only under its original frozen policy/marker.
    with pytest.raises(ValueError, match="compact package"):
        build_source(resource, new_policy)
    assert build_source(resource, old_policy).snapshot == old_source.snapshot
    assert old_policy.correction_sources == legacy.frozen_extension()


def test_targets_are_exactly_original_fields_minus_explicit_error_propositions():
    state, _, repo, _, _ = setup_source(filtered=True)
    resource = state["generated_resources"][0]
    source = build_source(resource, repo.get(state["run_id"]).policy)
    original = correction_audit_source(legacy.validated_correction_package(resource))
    expected = {f.path: original.text[f.start:f.end] for f in original.fields
                if f.path.rsplit(".", 1)[-1] not in filtered.EXCLUDED_LEAF_KEYS}
    assert {f["path"]: source.text[f["start"]:f["end"]] for f in source.fields} == expected
    assert source.snapshot["excluded_fields"]
    assert "learning_status" not in source.text and "concept_application" not in source.text
    for field in source.fields:
        assert source.classify([candidate(source.text, field["start"], field["end"])])[0].claim_type.value == "factual"


@pytest.mark.parametrize("path", ["content.unit.error_patterns[0].explanation",
                                   "content.unit.comparisons[0].correct_statement",
                                   "content.unit.exercises.guided.reference_answer"])
def test_only_linked_context_is_read_only_and_cannot_be_extracted(path):
    state, _, repo, _, counter = setup_source(locating=True, filtered=True)
    resource = state["generated_resources"][0]; policy = repo.get(state["run_id"]).policy
    source = build_source(resource, policy)
    field = next(f for f in source.fields if f["path"] == path)
    unit = next(u for u in scan_units(source.text) if u.start <= field["start"] < u.end)
    batch = make_batch(source.text, [unit], policy, counter)
    messages = build_messages(source.text, resource, batch, policy, {"k"})
    payload = json.loads(messages[-1].content)
    context = payload["structured_context"]["read_only_related_fields"]
    assert context
    assert {f["path"] for f in context} <= set(source.snapshot["context_bindings"][path])
    assert "learning_status" not in messages[-1].content
    foreign = context[0]["text"]
    output = extract_every_unit_v2({"messages": messages})
    output["units"][0].update(status="claims", reason="scripted context injection", claims=[
        dict(claim_text=foreign, source_text=foreign, claim_type="factual", knowledge_point_id=None)])
    with pytest.raises(ValueError):
        validate_output(source.text, batch, output, resource=resource, policy=policy, allowed_nodes={"k"})


@pytest.mark.parametrize("marker", [legacy.PROMPT_VERSION, filtered.PROMPT_VERSION])
def test_claim_source_reconstruction_uses_explicit_marker(marker):
    state, _, repo, _, _ = setup_source(filtered=marker == filtered.PROMPT_VERSION)
    resource = state["generated_resources"][0]
    source = build_source(resource, repo.get(state["run_id"]).policy)
    restored = source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=marker)])
    assert restored.snapshot == source.snapshot and restored.text == source.text
    with pytest.raises(ValueError, match="mixed"):
        source_for_claims(resource, [SimpleNamespace(extractor_prompt_version=legacy.PROMPT_VERSION),
                                    SimpleNamespace(extractor_prompt_version=filtered.PROMPT_VERSION)])
    with pytest.raises(ValueError):
        source_for_claims(resource, [SimpleNamespace(extractor_prompt_version="unknown")])


def test_filtered_spans_cannot_quote_header_or_cross_fields():
    state, _, repo, _, _ = setup_source(filtered=True)
    source = build_source(state["generated_resources"][0], repo.get(state["run_id"]).policy)
    first, second = source.fields[:2]
    for start, end in [(0, first["start"]), (first["start"], second["end"])]:
        with pytest.raises(ValueError):
            source.classify([candidate(source.text, start, end)])


@pytest.mark.parametrize("damage", ["version", "guidance_hash", "field_policy_hash"])
def test_unknown_or_drifted_filtered_contract_rejected(damage):
    state, _, repo, _, _ = setup_source(filtered=True)
    policy = repo.get(state["run_id"]).policy
    extension = copy.deepcopy(policy.correction_sources); extension[damage] = "changed"
    with pytest.raises(ValueError):
        build_source(state["generated_resources"][0], policy.model_copy(update={"correction_sources": extension}))


def test_unknown_forced_marker_rejected():
    state, _, repo, _, _ = setup_source(filtered=True)
    with pytest.raises(ValueError):
        legacy.build_source(state["generated_resources"][0], force=True, prompt_version="unknown")


def test_snapshot_cannot_mix_old_marker_with_filtered_offsets():
    from app.models.reviews.claim_extraction import validate_snapshot, digest
    from tests.integration.workflow.test_structured_correction_package import extract_and_judge
    state, _, repo, gateway, counter = setup_source(filtered=True)
    extract_and_judge(state, repo, gateway, counter)
    snapshot = repo.get(state["run_id"])
    results = dict(snapshot.state.results)
    key = next(iter(results))
    source = {**results[key].source_snapshot, "prompt_version": legacy.PROMPT_VERSION}
    results[key] = results[key].model_copy(update={"source_snapshot": source})
    ledger = snapshot.state.model_copy(update={"results": results})
    bad = snapshot.model_copy(update={"state": ledger, "state_hash": digest(ledger)})
    with pytest.raises(ValueError, match="marker/source"):
        validate_snapshot(snapshot.policy.strategy, state, bad)
