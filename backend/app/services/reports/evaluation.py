"""比赛评测结果的真实聚合服务。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.db.shared.models import ContestEvalResultORM
from app.models.reports.contracts import EvaluationSummary
from app.models.reviews.quality_metrics import EvaluationQualityManifestV2, EvaluationQualityCaseV2
from app.services.reviews.quality_evaluation import aggregate_evaluation, manifest_hash


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4)


class EvaluationService:
    def __init__(self, db_type: str, session_factory: Callable[[], Session]):
        self.db_type = db_type
        self.session_factory = session_factory

    @staticmethod
    def _resource_quality(rows):
        groups = {}
        manifests = {}
        payloads = []
        invalid_hashes = set()
        invalid_row_total = 0
        for row in rows:
            payload = (row.metrics or {}).get("resource_quality_case_v2")
            if payload is None:
                continue
            try:
                if not isinstance(payload, dict):
                    raise ValueError("invalid quality metadata")
                if payload.get("manifest") is not None:
                    manifest = EvaluationQualityManifestV2.model_validate(payload["manifest"])
                    manifests[manifest_hash(manifest)] = manifest
                payloads.append((row, payload))
            except (ValueError, TypeError, KeyError):
                invalid_row_total += 1
                case = payload.get("case") if isinstance(payload, dict) else None
                if isinstance(case, dict):
                    candidate_hash = case.get("manifest_hash")
                    if isinstance(candidate_hash, str):
                        invalid_hashes.add(candidate_hash)
        for row, payload in payloads:
            try:
                record = EvaluationQualityCaseV2.model_validate(payload["case"])
                manifest = manifests.get(record.manifest_hash)
                if manifest is None or manifest.experiment_name != row.experiment_name or record.case_id != row.case_id:
                    raise ValueError("unresolved or conflicting evaluation identity")
            except (ValueError, TypeError, KeyError):
                invalid_row_total += 1
                case = payload.get("case")
                if isinstance(case, dict):
                    candidate_hash = case.get("manifest_hash")
                    if isinstance(candidate_hash, str):
                        invalid_hashes.add(candidate_hash)
                continue
            identity = (manifest.evaluation_id, manifest.experiment_name, manifest.suite_id,
                        manifest.suite_version, manifest.metric_definition_version, manifest.evidence_mode)
            key = (*identity, record.manifest_hash)
            if key not in groups:
                groups[key] = (manifest, [])
            groups[key][1].append(record)
        identities = defaultdict(set)
        for key in groups:
            identities[key[:-1]].add(key[-1])
        for hashes in identities.values():
            if len(hashes) > 1:
                invalid_hashes.update(hashes)
        results = [aggregate_evaluation(manifest, records, record_conflict=key[-1] in invalid_hashes)
                   for key, (manifest, records) in sorted(groups.items())]
        return results, invalid_row_total

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
        quality_groups, invalid_rows = self._resource_quality(rows)
        return EvaluationSummary(
            sample_count=len({row.case_id for row in rows}),
            metrics=self._metrics(rows),
            ablation=ablation,
            created_at=datetime.now(timezone.utc),
            resource_quality_evaluations=quality_groups,
            resource_quality_invalid_row_total=invalid_rows,
        )
