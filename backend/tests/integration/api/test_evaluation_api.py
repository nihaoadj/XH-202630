"""评测汇总服务和 API 测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.reports import evaluation
from app.db.shared.models import Base, ContestEvalResultORM
from app.services.reports.evaluation import EvaluationService


def test_evaluation_summary_aggregates_real_results_by_experiment(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'evaluation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all(
            [
                ContestEvalResultORM(
                    result_id="eval_001",
                    case_id="case_001",
                    experiment_name="baseline",
                    retrieval_hit=True,
                    coverage_rate=0.6,
                    hallucination_rate=0.2,
                    difficulty_match=True,
                    metrics={"latency_ms": 100},
                ),
                ContestEvalResultORM(
                    result_id="eval_002",
                    case_id="case_002",
                    experiment_name="baseline",
                    retrieval_hit=False,
                    coverage_rate=0.8,
                    hallucination_rate=0.1,
                    difficulty_match=False,
                    metrics={"latency_ms": 140},
                ),
                ContestEvalResultORM(
                    result_id="eval_003",
                    case_id="case_001",
                    experiment_name="rerank",
                    retrieval_hit=True,
                    coverage_rate=0.9,
                    hallucination_rate=0.05,
                    difficulty_match=True,
                    metrics={"latency_ms": 160},
                ),
            ]
        )
        db.commit()

    service = EvaluationService("sqlite", factory)
    summary = service.get_summary()
    assert summary.sample_count == 2
    assert summary.metrics["retrieval_hit_rate"] == round(2 / 3, 4)
    assert summary.metrics["coverage_rate"] == round((0.6 + 0.8 + 0.9) / 3, 4)
    assert {item["method"] for item in summary.ablation} == {"baseline", "rerank"}

    app = FastAPI()
    app.container = SimpleNamespace(evaluation_service=lambda: service)
    app.include_router(evaluation.router, prefix="/api/evaluation")
    response = TestClient(app).get("/api/evaluation/summary")
    assert response.status_code == 200
    assert response.json()["sample_count"] == 2
