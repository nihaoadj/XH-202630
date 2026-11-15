"""Canonical private correction data must survive persistence and stay immutable."""
import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.shared.models import Base
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.audit.base import PersistenceConflict
from app.models.learning_documents.schemas import LearningResource
from app.models.learning_documents.invariants import immutable_resource_payload
from app.models.generation.resource_retry import retry_source_snapshot


@pytest.fixture(params=["memory", "sql"])
def repo(request, tmp_path):
    if request.param == "memory":
        yield MemoryResourceRepository()
        return
    engine = create_engine(f"sqlite:///{tmp_path / 'resources.db'}")
    Base.metadata.create_all(engine)
    yield SQLResourceRepository(sessionmaker(bind=engine))
    engine.dispose()


def resource(payload=True):
    return LearningResource(resource_id="correction-test", resource_type="个性化纠错训练包",
        difficulty="中级", content_text="# 纠错包", knowledge_points=["embedding"], source_refs=[],
        correction_package_payload={"content": {"summary": "原内容"}} if payload else None,
        correction_package_payload_hash="a" * 64 if payload else None)


def test_private_package_roundtrip_and_overwrite_rejected(repo):
    value = resource()
    repo.save(value, "learner-test", "Embedding")
    loaded = repo.get(value.resource_id)
    assert loaded.correction_package_payload == value.correction_package_payload
    assert loaded.correction_package_payload_hash == value.correction_package_payload_hash
    assert "correction_package_payload" not in loaded.model_dump(mode="json")
    assert "correction_package_payload" in immutable_resource_payload(loaded)
    restored = LearningResource.model_validate(retry_source_snapshot(loaded))
    assert restored.correction_package_payload == loaded.correction_package_payload
    assert restored.correction_package_payload_hash == loaded.correction_package_payload_hash
    changed = copy.deepcopy(loaded.correction_package_payload)
    changed["content"]["summary"] = "篡改内容"
    with pytest.raises(PersistenceConflict):
        repo.save(loaded.model_copy(update={"correction_package_payload": changed}), "learner-test", "Embedding")


def test_legacy_resources_keep_absent_private_fields(repo):
    value = resource(False)
    repo.save(value, "learner-test", "Embedding")
    loaded = repo.get(value.resource_id)
    assert loaded.correction_package_payload is None
    assert "correction_package_payload" not in immutable_resource_payload(loaded)


@pytest.mark.parametrize("package_version", ["v1", "v2"])
@pytest.mark.parametrize("damage", [None, "runtime", "checkpoint", "content", "format"])
def test_recovery_validates_frozen_identity_and_canonical_resource_before_model(package_version, damage):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.db.audit.memory import MemoryAuditRepository
    from app.models.shared.persistence import CreateRunCommand, canonical_hash, build_checkpoint_projection
    from app.services.runs.durable_workflow_runner import DurableWorkflowRunner
    from app.agents.resource_agents.correction_package import structured_generation_contract
    from app.core.learning_documents.correction_package import render_correction_markdown
    from tests.unit.agents.test_structured_correction_package import package
    from tests.unit.agents.test_compact_correction_package import compact_content
    from app.models.learning_documents.correction_package import assemble_compact_correction_package
    def assemble_for_format_test():
        return assemble_compact_correction_package(content=compact_content(), title="纠错包", run_id="run-test", focus_snapshot_hash="a" * 64,
            target=dict(node_id="embedding", node_name="Embedding", mastery_status="weak", failed_dimensions=["concept_application"]))
    contract = structured_generation_contract("correction-json-generation-" + package_version)
    audit = MemoryAuditRepository()
    snapshot = {"correction_package_snapshot": contract}
    audit.create_run(CreateRunCommand(run_id="recover", request_snapshot=snapshot, request_hash=canonical_hash(snapshot)))
    audit.start_run("recover", occurred_at=datetime.now(timezone.utc))
    if package_version == "v2":
        value = assemble_for_format_test()
    else:
        value = package()
    r = LearningResource(resource_id="r", resource_type="个性化纠错训练包", difficulty="初级", knowledge_points=["embedding"], source_refs=[],
        content_text=render_correction_markdown(value).strip(), correction_package_payload=value.model_dump(mode="json"), correction_package_payload_hash=value.payload_hash)
    state = {"run_id": "recover", "correction_package_snapshot": copy.deepcopy(contract), "constraints": {}, "target_skill_nodes": ["embedding"],
        "generated_resources": [r], "trace": [], "errors": []}
    projection = build_checkpoint_projection(state)
    if damage == "checkpoint": projection["correction_package_snapshot"]["prompt_hash"] = "0" * 64
    audit.save_checkpoint(run_id="recover", step_id="generate", step_sequence=1, node_name="generate", state_projection=projection,
        state_hash=canonical_hash(projection), occurred_at=datetime.now(timezone.utc))
    if damage == "runtime": state["correction_package_snapshot"]["schema_hash"] = "0" * 64
    if damage == "content": r.content_text += "changed"
    if damage == "format":
        # A valid opposite-format artifact must not pass under this frozen identity.
        other = package() if package_version == "v2" else assemble_for_format_test()
        r.content_text = render_correction_markdown(other).strip()
        r.correction_package_payload = other.model_dump(mode="json")
        r.correction_package_payload_hash = other.payload_hash
    invoked = []
    workflow = SimpleNamespace(invoke=lambda current: invoked.append(True) or {})
    runner = DurableWorkflowRunner(workflow, audit)
    if damage:
        with pytest.raises(ValueError): runner.invoke(state)
        assert not invoked
    else:
        result = runner.invoke(state)
        assert result["constraints"]["_correction_package_contract"] == contract
        assert result["generated_resources"][0].correction_package_payload == value.model_dump(mode="json")
