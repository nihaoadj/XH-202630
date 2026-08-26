"""比赛评测结果的真实聚合服务。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.db.shared.models import ContestEvalResultORM
from app.models.reports.contracts import EvaluationSummary


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4)


class EvaluationService:
    def __init__(self, db_type: str, session_factory: Callable[[], Session]):
        self.db_type = db_type
        self.session_factory = session_factory

    @staticmethod
    def _metrics(rows: list[ContestEvalResultORM]) -> dict[str, float]:
        values: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.retrieval_hit is not None:
                values["retrieval_hit_rate"].append(float(row.retrieval_hit))
            if row.coverage_rate is not None:
                values["coverage_rate"].append(float(row.coverage_rate))
            if row.hallucination_rate is not None:
                values["hallucination_rate"].append(float(row.hallucination_rate))
            if row.difficulty_match is not None:
                values["difficulty_match_rate"].append(float(row.difficulty_match))
            for name, value in (row.metrics or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[name].append(float(value))
        return {name: _average(metric_values) for name, metric_values in sorted(values.items()) if metric_values}

    def get_summary(self) -> EvaluationSummary:
        if self.db_type == "memory":
            return EvaluationSummary(sample_count=0, metrics={}, ablation=[], created_at=datetime.now(timezone.utc))
        with self.session_factory() as db:
            rows = db.query(ContestEvalResultORM).all()
        experiments: dict[str, list[ContestEvalResultORM]] = defaultdict(list)
        for row in rows:
            experiments[row.experiment_name].append(row)
        ablation = [
            {
                "method": experiment_name,
                "sample_count": len({row.case_id for row in experiment_rows}),
                **self._metrics(experiment_rows),
            }
            for experiment_name, experiment_rows in sorted(experiments.items())
        ]
        return EvaluationSummary(
            sample_count=len({row.case_id for row in rows}),
            metrics=self._metrics(rows),
            ablation=ablation,
            created_at=datetime.now(timezone.utc),
        )
