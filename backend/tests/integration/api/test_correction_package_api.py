"""Published Markdown, ownership and private T60 envelope HTTP contracts."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learning_documents import documents
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.learning_documents.resources import ResourceService
from tests.unit.agents.test_structured_correction_package import package
from app.core.learning_documents.correction_package import render_correction_markdown


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("owner", [False, True])
@pytest.mark.parametrize("compact", [False, True])
def test_markdown_read_download_owner_and_private_package(monkeypatch, published, owner, compact):
    from tests.unit.agents.test_compact_correction_package import compact_package
    value = compact_package() if compact else package()
    text = render_correction_markdown(value).strip()
    resource = LearningResource(resource_id="r", learner_id="learner", topic="纠错", resource_type="个性化纠错训练包",
        difficulty="初级", knowledge_points=["embedding"], source_refs=[], content_text=text,
        publication_status="published" if published else "unpublished", file_path="synthetic.md",
        mime_type="text/markdown", correction_package_payload=value.model_dump(mode="json"),
        correction_package_payload_hash=value.payload_hash)
    repo = MemoryResourceRepository(); repo.save(resource, "learner", "纠错")
    learner = LearnerProfile(learner_id="learner", user_id="owner", learner_type="test", education="本科", major="软件", learning_goal="验证")
    app = FastAPI()
    @app.middleware("http")
    async def user(request, call_next):
        request.state.current_user = SimpleNamespace(user_id="owner" if owner else "another")
        return await call_next(request)
    app.container = SimpleNamespace(resource_service=lambda: ResourceService(repo), profile_service=lambda: SimpleNamespace(get=lambda _: learner))
    app.include_router(documents.router, prefix="/api/resources")
    monkeypatch.setattr(documents, "load_resource_file", lambda _: text.encode())
    client = TestClient(app)
    read = client.get("/api/resources/items/r")
    download = client.get("/api/resources/file/r")
    if published and owner:
        assert read.status_code == download.status_code == 200
        assert read.json()["resource"]["content_text"] == text
        assert download.content.decode() == text
        assert "correction_package_payload" not in read.text and "provenance" not in read.text
        assert "当前状态：薄弱" in read.json()["resource"]["content_text"]
    else:
        assert read.status_code == download.status_code == 404


def test_public_schema_and_events_do_not_expose_private_package():
    import json
    from datetime import datetime, timezone
    from app.models.shared.persistence import WorkflowEvent, WorkflowEventType, canonical_hash
    from app.services.runs.events import to_public_event
    value = package().model_dump(mode="json")
    schema = LearningResource.model_json_schema(mode="serialization")
    assert "correction_package_payload" not in schema["properties"]
    payload = {"resource_id": "r", "correction_package_payload": value, "correction_package_snapshot": {"secret": True}, "provenance": value["provenance"]}
    event = WorkflowEvent(event_id="e", run_id="run", event_sequence=1, event_type=WorkflowEventType.RESOURCE_GENERATED,
        payload=payload, payload_hash=canonical_hash(payload), occurred_at=datetime.now(timezone.utc))
    public = to_public_event(event).model_dump_json()
    assert "provenance" not in public and "correction_package" not in public
