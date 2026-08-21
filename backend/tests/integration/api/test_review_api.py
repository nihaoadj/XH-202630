"""资源审核查询接口测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import reviews
from app.db.audit.memory import MemoryAuditRepository
from app.services.review_service import ReviewService


def test_review_endpoint_returns_claim_evidence_and_handles_missing_resource():
    repository = MemoryAuditRepository()
    review_id = repository.save_review(
        "resource_001",
        {
            "passed": True,
            "claims": [
                {
                    "claim_id": "claim_001",
                    "text": "RAG 在生成前检索外部证据。",
                    "supported": True,
                    "evidence_refs": [{"doc_id": "ref_001", "chunk_id": "chunk_001"}],
                }
            ],
        },
        run_id=None,
    )
    app = FastAPI()
    app.container = SimpleNamespace(review_service=lambda: ReviewService(repository))
    app.include_router(reviews.router, prefix="/api/reviews")
    client = TestClient(app)

    response = client.get("/api/reviews/resource_001")
    assert response.status_code == 200
    assert response.json()["review_id"] == review_id
    assert response.json()["claims"][0]["evidence_refs"][0]["chunk_id"] == "chunk_001"
    assert client.get("/api/reviews/missing").status_code == 404
