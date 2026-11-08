"""Injected repository boundary and authoritative-chain verification (T44).

The engine never touches a database directly: recovery I/O lives only behind
this boundary.  A replay must re-derive every hash from the actual persisted
artifact, structured package, spec targets and frozen evidence, then rebuild the
ledger from the V4 audit rather than trusting an in-memory ``closed`` state or a
policy-less checkpoint.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models.reviews.resource_review import (
    ResourceLedgerV1,
    ResourceReviewBindingV1,
)
from app.models.shared.persistence import canonical_hash

from .adapters.base import evidence_hashes


@runtime_checkable
class ResourceReviewRepository(Protocol):
    """Minimal durable store the engine depends on; no business rules here."""

    def get_resource_ledger(self, run_id: str, resource_spec_id: str) -> dict | None: ...

    def save_resource_ledger(self, run_id: str, resource_spec_id: str, ledger: dict) -> None: ...

    def get_resource_revision(self, run_id: str, resource_spec_id: str) -> dict | None: ...

    def save_resource_revision(self, run_id: str, resource_spec_id: str, revision: dict) -> None: ...


def verify_binding_hashes(*, binding: ResourceReviewBindingV1, material, evidence) -> None:
    """Re-derive every frozen hash from the actual artifacts and evidence.

    A mismatch means the authoritative chain was tampered with or the wrong
    material was bound; it must fail closed, never be "corrected" as model output.
    """
    if binding.artifact_exact_hash != material.artifact_exact_hash:
        raise ValueError("resource binding artifact hash mismatch")
    if binding.text_exact_hash != material.text_exact_hash:
        raise ValueError("resource binding text hash mismatch")
    if binding.structured_payload_hash != material.structured_payload_hash:
        raise ValueError("resource binding payload hash mismatch")
    if binding.comparison_hash != material.comparison_hash:
        raise ValueError("resource binding comparison hash mismatch")
    expected_evidence = canonical_hash({"evidence": sorted(
        ({"evidence_id": item.evidence_id, "excerpt_hash": item.excerpt_hash}
         for item in evidence), key=lambda item: item["evidence_id"])})
    if binding.evidence_snapshot_hash != expected_evidence:
        raise ValueError("resource binding evidence snapshot hash mismatch")


def replay_ledger(payload: dict) -> ResourceLedgerV1:
    """Rebuild and re-validate a ledger from its persisted payload."""
    return ResourceLedgerV1.model_validate(payload)


def replay_resource_artifacts(*, ledger: ResourceLedgerV1, resources: list,
                              adapter, targets: list[str], evidence,
                              predecessor: ResourceLedgerV1 | None = None,
                              predecessor_resource=None) -> ResourceLedgerV1:
    """Rebuild observations through the production gate and validators, without LLM calls.

    Hash-valid self-consistent JSON is insufficient: decisions and gate migration
    must agree with the actual versioned artifacts before publication.  A ledger
    that starts a new evidence epoch is replayed against its immutable
    predecessor and that predecessor's actual artifact.
    """
    from .engine import run_program_gate, migrate_program_gate
    from .ledger import append_model_observation_v1, append_program_gate_observation_v1
    if len(resources) != len(ledger.observations):
        raise ValueError("resource recovery artifact count mismatch")
    rebuilt = None
    parent_material = None
    carry_over = ledger.carry_over
    if carry_over is not None:
        if predecessor is None or predecessor_resource is None:
            raise ValueError("resource epoch replay requires its predecessor")
        rebuilt = predecessor
        parent_material = adapter.build_material(
            resource=predecessor_resource, evidence=evidence, spec=None, targets=targets)
        if parent_material.artifact_exact_hash != carry_over.previous_content_hash:
            raise ValueError("resource epoch predecessor artifact mismatch")
    parent_text = parent_material.text if parent_material is not None else None
    for index, (resource, observation) in enumerate(zip(resources, ledger.observations)):
        material = adapter.build_material(resource=resource, evidence=evidence, spec=None, targets=targets)
        verify_binding_hashes(binding=observation.binding, material=material, evidence=evidence)
        gate = migrate_program_gate(run_program_gate(resource=resource, material=material,
                                                     binding=observation.binding), rebuilt)
        kwargs = dict(previous=rebuilt, binding=observation.binding, step_id=observation.step_id,
                      material=material,
                      parent_comparison_hash=parent_material.comparison_hash if parent_material else None,
                      carry_over=carry_over if index == 0 else None)
        if observation.origin == "program_gate":
            rebuilt = append_program_gate_observation_v1(**kwargs, gate=gate)
        else:
            if not gate.passed:
                raise ValueError("resource recovery semantic observation bypasses program gate")
            rebuilt = append_model_observation_v1(**kwargs, output=observation.output,
                adapter=adapter, parent_text=parent_text,
                parent_material=parent_material, revision_kind=observation.revision_kind, gate=gate)
        if rebuilt.observations[-1] != observation:
            raise ValueError("resource persisted observation differs from gate/decision replay")
        parent_material = material
        parent_text = material.text
    if rebuilt != ledger:
        raise ValueError("resource persisted ledger differs from replay")
    return rebuilt
