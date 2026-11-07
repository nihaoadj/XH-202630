"""评测汇总服务和 API 测试。"""
from types import SimpleNamespace

import pytest

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



def test_typed_evaluation_api_reconstructs_cases_and_resolves_manifest_reference(tmp_path):
    import runpy
    from pathlib import Path
    helpers = runpy.run_path(str(Path(__file__).parents[2] / "unit/reports/test_resource_quality_evaluation_v2.py"))
    manifest, cases = helpers["_typed_records"]()
    engine = create_engine(f"sqlite:///{tmp_path / 'typed-evaluation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for index, record in enumerate(cases):
            payload = {"case": record.model_dump(mode="json")}
            if index == 0:
                payload["manifest"] = manifest.model_dump(mode="json")
            db.add(ContestEvalResultORM(result_id=f"typed-{index}", case_id=record.case_id,
                experiment_name="main", metrics={"resource_quality_case_v2": payload}))
        db.commit()
    app = FastAPI()
    app.container = SimpleNamespace(evaluation_service=lambda: EvaluationService("sqlite", factory))
    app.include_router(evaluation.router, prefix="/api/evaluation")
    response = TestClient(app).get("/api/evaluation/summary")
    assert response.status_code == 200
    group = response.json()["resource_quality_evaluations"][0]
    assert group["coverage"]["denominator"] == 3
    assert group["hallucination"]["denominator"] == 20
    assert group["difficulty"]["value"] == 1
    assert group["manifest"]["evidence_mode"] == "offline_gold"
    engine.dispose()



def test_invalid_quality_row_is_isolated_without_breaking_legacy_summary(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'invalid-evaluation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(ContestEvalResultORM(result_id="bad", case_id="bad", experiment_name="legacy",
            coverage_rate=.7, metrics={"resource_quality_case_v2": {"case": {"manifest_hash": ["invalid"]}}}))
        db.commit()
    app = FastAPI()
    app.container = SimpleNamespace(evaluation_service=lambda: EvaluationService("sqlite", factory))
    app.include_router(evaluation.router, prefix="/api/evaluation")
    response = TestClient(app).get("/api/evaluation/summary")
    assert response.status_code == 200
    assert response.json()["metrics"]["coverage_rate"] == .7
    assert response.json()["resource_quality_invalid_row_total"] == 1
    assert response.json()["resource_quality_evaluations"] == []
    engine.dispose()



@pytest.mark.parametrize("field", ["expected_difficulty", "predicted_difficulty"])
@pytest.mark.parametrize("invalid_label", ["", "x" * 33])
def test_invalid_difficulty_label_is_isolated_by_sql_summary_api(tmp_path, field, invalid_label):
    import runpy
    from pathlib import Path
    from app.services.reviews.quality_evaluation import manifest_hash

    helpers = runpy.run_path(str(Path(__file__).parents[2] / "unit/reports/test_resource_quality_evaluation_v2.py"))
    manifest, cases = helpers["_typed_records"]()
    other_manifest = manifest.model_copy(update={
        "evaluation_id": "independent-valid-group", "experiment_name": "independent",
    })
    other_cases = [record.model_copy(update={"manifest_hash": manifest_hash(other_manifest)}) for record in cases]
    engine = create_engine(f"sqlite:///{tmp_path / 'difficulty-label.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        for group_id, frozen, records in [("bad", manifest, cases), ("valid", other_manifest, other_cases)]:
            for index, record in enumerate(records):
                payload = record.model_dump(mode="json")
                if group_id == "bad" and index == 0:
                    payload[field] = invalid_label
                db.add(ContestEvalResultORM(
                    result_id=f"{group_id}-{index}", case_id=record.case_id, experiment_name=frozen.experiment_name,
                    coverage_rate=.7,
                    metrics={"resource_quality_case_v2": {"manifest": frozen.model_dump(mode="json"), "case": payload}},
                ))
        db.commit()
    try:
        app = FastAPI()
        app.container = SimpleNamespace(evaluation_service=lambda: EvaluationService("sqlite", factory))
        app.include_router(evaluation.router, prefix="/api/evaluation")
        response = TestClient(app).get("/api/evaluation/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"]["coverage_rate"] == .7
        assert data["resource_quality_invalid_row_total"] == 1
        groups = {group["manifest"]["evaluation_id"]: group for group in data["resource_quality_evaluations"]}
        assert groups[manifest.evaluation_id]["status"] == "invalid"
        assert groups[manifest.evaluation_id]["coverage"]["value"] is None
        assert groups[manifest.evaluation_id]["difficulty"]["value"] is None
        assert groups[other_manifest.evaluation_id]["status"] == "complete"
        assert groups[other_manifest.evaluation_id]["difficulty"]["value"] == 1
    finally:
        engine.dispose()
