"""比赛金标评测套件：加载、校验与三项指标编排（离线确定性，不调用大模型）。

- 幻觉率与覆盖率复用 ``compute_competition_claim_metrics``：金标 verdict 作为判定输入，
  只统计最终发布叶子资源上的事实 Claim。
- 难度适配复用 ``evaluate_difficulty_fixtures``：predicted_difficulty 由系统策略
  ``difficulty_for_tier``（目标能力节点 tier）计算，与 GenerationJobService 的链路一致。
- MetricGate 复用 P0-09 门结构，金标回归与 official_gates 的正式质量证据分别记录。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import PROJECT_ROOT, get_settings, is_placeholder_api_key
from app.core.learning_tiers import difficulty_for_tier
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.models.learning_documents.schemas import (
    GenerateRequest,
    LearnerProfile,
    LearningResource,
)
from app.models.reviews.claims import (
    ClaimCandidate,
    ClaimJudgementCandidate,
    ClaimType,
    ClaimVerdict,
    materialize_claims,
    materialize_judgements,
)
from app.services.reports.p0_09_acceptance import MetricGate
from app.services.reports.competition_evidence import (
    confined_path, json_hash, validate_source_snapshot,
)
from app.services.reviews.claim_evaluation import (
    CompetitionClaimMetrics,
    DifficultyEvaluation,
    DifficultyFixtureResult,
    compute_competition_claim_metrics,
    evaluate_difficulty_fixtures,
    final_published_leaf_ids,
)


SUITE_ID = "rag-competition-gold-suite"
SUITE_VERSION = "v1"
GOLD_RESOURCE_ID = "gold-claims-resource"
GOLD_RUN_ID = "gold-competition-run"
GOLD_PROMPT_VERSION = "gold-v1"
OFFICIAL_MINIMUM_CASE_COUNT = 50


class CompetitionMetricReport(BaseModel):
    """离线金标评测的可序列化报告；正式比赛数值仍需真实模型评测。"""

    model_config = ConfigDict(extra="forbid")

    suite_id: str
    suite_version: str
    mode: str
    case_count: int = Field(ge=0)
    claim_metrics: CompetitionClaimMetrics
    difficulty: DifficultyEvaluation
    gates: list[MetricGate]
    evidence_scope: str = "offline_gold"
    source_snapshot_hash: str | None = None
    suite_data_hash: str | None = None
    selected_case_count: int = 0
    completed_generation_count: int = 0
    failed_case_count: int = 0
    case_results: list[dict[str, Any]] = Field(default_factory=list)
    official_gates: list[MetricGate] = Field(default_factory=list)
    independent_quality_review: str = "NOT_RUN"


def default_suite_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "competition" / "suite.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    return payload


def load_suite(
    path: str | Path | None = None,
    *,
    expected_suite_id: str | None = None,
    expected_suite_version: str | None = None,
    kb_root: str | Path | None = None,
) -> dict[str, Any]:
    """加载套件清单并聚合画像、用例与金标 Claim 三个子文件。

    默认按仓库内 RAG 套件的常量做防漂移校验；迁移到新领域时传入该领域
    套件自己的 suite_id/version 与知识库根目录，评测代码本身不依赖任何
    领域特定逻辑。
    """
    suite_path = Path(path) if path else default_suite_path()
    manifest = _read_json(suite_path)
    if manifest.get("suite_id") != (expected_suite_id or SUITE_ID):
        raise ValueError("unexpected competition suite_id")
    if manifest.get("suite_version") != (expected_suite_version or SUITE_VERSION):
        raise ValueError("unexpected competition suite_version")
    root = suite_path.parent
    files = manifest.get("files") or {}
    suite: dict[str, Any] = dict(manifest)
    for name in ("profiles", "cases", "claims"):
        suite[f"{name}_payload"] = _read_json(confined_path(root, files[name]))
    if files.get("sources"):
        suite["sources_payload"] = _read_json(confined_path(root, files["sources"]))
    validate_suite(suite, kb_root=kb_root)
    return suite


def load_skill_node_tiers(knowledge_base_id: str, kb_root: str | Path | None = None) -> dict[str, int]:
    """从权威知识库 manifest 读取能力节点 tier，作为难度预测的真实数据源。

    kb_root 默认指向仓库内 knowledge_base 目录；外部领域可注入自己的
    manifest 根目录，评测链路不绑定具体领域。
    """
    root = Path(kb_root) if kb_root else PROJECT_ROOT / "knowledge_base"
    manifest = load_knowledge_base_manifest(str(confined_path(root, knowledge_base_id)))
    return {str(node["node_id"]): int(node["tier"]) for node in manifest.get("skill_nodes", [])}


def validate_suite(suite: dict[str, Any], *, kb_root: str | Path | None = None) -> None:
    """校验金标套件的结构与一致性，问题在加载期直接失败。"""
    thresholds = suite["competition_thresholds"]
    profiles = suite["profiles_payload"]
    cases = suite["cases_payload"]
    claims = suite["claims_payload"]
    node_tiers = load_skill_node_tiers(suite["knowledge_base_id"], kb_root=kb_root)
    if suite.get("suite_id") == SUITE_ID and not suite.get("sources_payload"):
        raise ValueError("default competition suite requires frozen sources")

    if int(thresholds.get("minimum_case_count", 50)) < 50:
        raise ValueError("competition minimum_case_count cannot be below 50")
    if not 0 < float(thresholds["hallucination_rate_max"]) <= 0.05:
        raise ValueError("hallucination threshold cannot be weaker than <5%")
    if not 0.85 <= float(thresholds["difficulty_match_accuracy_min"]) <= 1:
        raise ValueError("difficulty threshold cannot be weaker than >=85%")
    if not 0.90 <= float(thresholds["knowledge_coverage_min"]) <= 1:
        raise ValueError("coverage threshold cannot be weaker than >=90%")
    for payload in (profiles, cases, claims):
        if payload.get("fixture_version") != suite.get("fixture_version"):
            raise ValueError("fixture_version drift")

    if profiles.get("knowledge_base_id") != suite["knowledge_base_id"]:
        raise ValueError("profiles knowledge_base_id drift")
    if cases.get("knowledge_base_id") != suite["knowledge_base_id"]:
        raise ValueError("cases knowledge_base_id drift")
    if claims.get("knowledge_base_id") != suite["knowledge_base_id"]:
        raise ValueError("claims knowledge_base_id drift")

    # 画像：至少 3 种不同背景，tier 与目标节点一致。
    backgrounds = profiles.get("backgrounds") or []
    learners = profiles.get("learners") or []
    if len({item["background_id"] for item in backgrounds}) < 3:
        raise ValueError("competition suite requires at least 3 distinct learner backgrounds")
    learner_ids = {item["learner_id"] for item in learners}
    if len(learner_ids) != len(learners):
        raise ValueError("learner IDs must be unique")
    for learner in learners:
        if learner["background_id"] not in {item["background_id"] for item in backgrounds}:
            raise ValueError(f"learner references unknown background: {learner['learner_id']}")
        targets = learner["target_skill_nodes"]
        if not targets or any(node not in node_tiers for node in targets):
            raise ValueError(f"learner references unknown skill node: {learner['learner_id']}")
        if {node_tiers[node] for node in targets} != {learner["tier"]}:
            raise ValueError(f"learner tier must match target node tier: {learner['learner_id']}")

    # 用例：数量 >= 比赛要求的 50 组，引用合法画像与资源类型。
    case_list = cases.get("cases") or []
    minimum = int(thresholds.get("minimum_case_count", OFFICIAL_MINIMUM_CASE_COUNT))
    if len(case_list) < minimum:
        raise ValueError(f"competition suite requires at least {minimum} cases, got {len(case_list)}")
    if cases.get("case_count") != len(case_list):
        raise ValueError("case_count drift")
    resource_types = set(cases.get("resource_types") or [])
    case_ids = set()
    for case in case_list:
        if case["case_id"] in case_ids:
            raise ValueError(f"duplicate case_id: {case['case_id']}")
        case_ids.add(case["case_id"])
        if case["learner_id"] not in learner_ids:
            raise ValueError(f"case references unknown learner: {case['case_id']}")
        if case["resource_type"] not in resource_types:
            raise ValueError(f"case references unknown resource type: {case['case_id']}")
        if case["expected_difficulty"] not in {"初级", "中级", "高级"}:
            raise ValueError(f"case expected_difficulty invalid: {case['case_id']}")
        learner = next(item for item in learners if item["learner_id"] == case["learner_id"])
        if not case.get("target_skill_nodes") or set(case["target_skill_nodes"]) != set(learner["target_skill_nodes"]):
            raise ValueError(f"case target nodes drift from learner: {case['case_id']}")
    used_learners = {case["learner_id"] for case in case_list}
    if len({item["background_id"] for item in learners if item["learner_id"] in used_learners}) < 3:
        raise ValueError("cases must use at least 3 learner backgrounds")
    if len({case["resource_type"] for case in case_list}) < 3:
        raise ValueError("cases must use at least 3 resource types")
    if not {case["resource_type"] for case in case_list} <= {"讲义", "实操指南", "分阶测试题", "案例分析", "复习清单"}:
        raise ValueError("unsupported competition resource type")

    # 金标 Claim：目标节点全覆盖，判定与证据的约束满足 claim 领域契约。
    claim_list = claims.get("claims") or []
    claim_ids = set()
    supported_nodes: set[str] = set()
    for claim in claim_list:
        if claim["claim_id"] in claim_ids:
            raise ValueError(f"duplicate claim_id: {claim['claim_id']}")
        claim_ids.add(claim["claim_id"])
        verdict = claim["verdict"]
        if verdict not in {item.value for item in ClaimVerdict} or claim["claim_type"] not in {item.value for item in ClaimType}:
            raise ValueError(f"unknown claim type/verdict: {claim['claim_id']}")
        if claim.get("knowledge_point_id") is not None and claim["knowledge_point_id"] not in node_tiers:
            raise ValueError(f"claim references unknown node: {claim['claim_id']}")
        if verdict in {"supported", "contradicted"} and not claim["evidence_ids"]:
            raise ValueError(f"supported/contradicted claim requires evidence: {claim['claim_id']}")
        if verdict in {"not_in_evidence", "non_factual"} and claim["evidence_ids"]:
            raise ValueError(f"not_in_evidence/non_factual claim forbids evidence: {claim['claim_id']}")
        if claim["claim_type"] == "factual" and verdict == "non_factual":
            raise ValueError(f"factual claim cannot be non_factual: {claim['claim_id']}")
        if claim["claim_type"] != "factual" and verdict != "non_factual":
            raise ValueError(f"non-factual claim must be non_factual: {claim['claim_id']}")
        if verdict == "supported":
            node_id = claim.get("knowledge_point_id")
            if node_id and node_id in node_tiers:
                supported_nodes.add(node_id)
    target_nodes = set(claims.get("target_skill_nodes") or [])
    if not target_nodes or not target_nodes <= supported_nodes:
        missing = target_nodes - supported_nodes
        raise ValueError(f"target skill nodes not fully covered by supported claims: {sorted(missing)}")
    if not target_nodes <= set(node_tiers):
        raise ValueError("gold references unknown target nodes")
    if not {node for case in case_list for node in case["target_skill_nodes"]} <= target_nodes:
        raise ValueError("case target nodes lack gold reference")
    if suite.get("sources_payload") is not None:
        validate_source_snapshot(suite["sources_payload"], suite["knowledge_base_id"], claims, kb_root)


def build_gold_claims(claims_payload: dict[str, Any]) -> tuple[list, list]:
    """把金标 Claim 物化为 ClaimRecord/ClaimJudgement 领域对象。

    resource_content 为全部 claim 文本的拼接，保证 source_text 是资源的精确子串；
    verdict 直接来自人工金标标注，离线模式下不调用判定模型。
    """
    claim_items = claims_payload["claims"]
    content = "\n".join(item["claim_text"] for item in claim_items)
    allowed_evidence = {evidence for item in claim_items for evidence in item["evidence_ids"]}
    allowed_nodes = set(claims_payload["target_skill_nodes"])
    candidates = [
        ClaimCandidate(
            claim_text=item["claim_text"],
            claim_type=ClaimType(item["claim_type"]),
            source_text=item["claim_text"],
            source_start=0,
            source_end=len(item["claim_text"]),
            knowledge_point_id=item.get("knowledge_point_id"),
            source_evidence_ids=list(item["evidence_ids"]),
        )
        for item in claim_items
    ]
    records = materialize_claims(
        candidates=candidates,
        resource_content=content,
        resource_id=GOLD_RESOURCE_ID,
        resource_version=1,
        review_id="gold-review",
        run_id=GOLD_RUN_ID,
        allowed_evidence_ids=allowed_evidence,
        allowed_knowledge_point_ids=allowed_nodes,
        extractor_prompt_version=GOLD_PROMPT_VERSION,
        extractor_model=None,
    )
    judgements = materialize_judgements(
        claims=records,
        candidates=[
            ClaimJudgementCandidate(
                claim_id=record.claim_id,
                verdict=ClaimVerdict(item["verdict"]),
                evidence_ids=list(item["evidence_ids"]),
                reason="gold fixture verdict",
                confidence=1.0,
            )
            for record, item in zip(records, claim_items)
        ],
        allowed_evidence_ids=allowed_evidence,
        judge_prompt_version=GOLD_PROMPT_VERSION,
        judge_model=None,
    )
    return records, judgements


def compute_difficulty_results(
    cases_payload: dict[str, Any],
    node_tiers: dict[str, int],
) -> list[DifficultyFixtureResult]:
    """按系统策略为每个用例计算预测难度：目标节点 tier -> 难度标签。"""
    results: list[DifficultyFixtureResult] = []
    for case in cases_payload["cases"]:
        target_tiers = {node_tiers[node] for node in case["target_skill_nodes"]}
        if len(target_tiers) != 1:
            raise ValueError(f"case targets must share one tier: {case['case_id']}")
        results.append(DifficultyFixtureResult(
            case_id=case["case_id"],
            fixture_version=cases_payload["fixture_version"],
            expected_difficulty=case["expected_difficulty"],
            predicted_difficulty=difficulty_for_tier(next(iter(target_tiers))),
        ))
    return results


def evaluate_competition_metrics(
    suite: dict[str, Any],
    *,
    kb_root: str | Path | None = None,
) -> CompetitionMetricReport:
    """金标/策略的计算回归；正式生成质量由 official_gates 单独表达。"""
    validate_suite(suite, kb_root=kb_root)
    claims_payload = suite["claims_payload"]
    cases_payload = suite["cases_payload"]
    thresholds = suite["competition_thresholds"]

    resource = LearningResource(
        resource_id=GOLD_RESOURCE_ID,
        resource_type="讲义",
        difficulty="中级",
        content_text="\n".join(item["claim_text"] for item in claims_payload["claims"]),
        knowledge_points=list(claims_payload["target_skill_nodes"]),
        source_refs=[],
        version=1,
        publication_status="published",
    )
    records, judgements = build_gold_claims(claims_payload)
    claim_metrics = compute_competition_claim_metrics(
        resources=[resource],
        claims=records,
        judgements=judgements,
        target_skill_node_ids=claims_payload["target_skill_nodes"],
    )

    node_tiers = load_skill_node_tiers(suite["knowledge_base_id"], kb_root=kb_root)
    difficulty = evaluate_difficulty_fixtures(
        compute_difficulty_results(cases_payload, node_tiers),
    )

    case_count = len(cases_payload["cases"])
    measurable = case_count >= int(thresholds.get("minimum_case_count", OFFICIAL_MINIMUM_CASE_COUNT))
    mode_note = "offline gold fixtures; official live-model numbers require RUN_LIVE_LLM=1 evaluation"
    hallucination = claim_metrics.claim_hallucination_rate
    coverage = claim_metrics.knowledge_coverage_rate
    accuracy = difficulty.accuracy
    gates = [
        MetricGate(
            metric_id="M-HALLUCINATION",
            official_definition="专业知识谬误率（幻觉率）",
            official_threshold="< 5%",
            formula="(contradicted + not_in_evidence) / factual_claim_total on final published leaves",
            sample_count=case_count,
            actual_value=hallucination,
            status=("PASS" if measurable and hallucination is not None and hallucination < float(thresholds["hallucination_rate_max"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"{mode_note}; factual_claims={claim_metrics.factual_claim_total}",
        ),
        MetricGate(
            metric_id="M-DIFFICULTY",
            official_definition="学习者画像-资源难度适配准确率",
            official_threshold=">= 85%",
            formula="correct expected-vs-predicted difficulty / gold cases",
            sample_count=case_count,
            actual_value=accuracy,
            status=("PASS" if measurable and accuracy is not None and accuracy >= float(thresholds["difficulty_match_accuracy_min"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"{mode_note}; correct={difficulty.correct_total}/{difficulty.case_total}",
        ),
        MetricGate(
            metric_id="M-COVERAGE",
            official_definition="核心知识点覆盖率",
            official_threshold=">= 90%",
            formula="target skill nodes covered by supported factual claims / target nodes",
            sample_count=case_count,
            actual_value=coverage,
            status=("PASS" if measurable and coverage is not None and coverage >= float(thresholds["knowledge_coverage_min"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"{mode_note}; covered={claim_metrics.covered_skill_total}/{claim_metrics.target_skill_total}",
        ),
    ]
    case_results = []
    predicted = {item.case_id: item.predicted_difficulty for item in compute_difficulty_results(cases_payload, node_tiers)}
    for plan in build_live_plan(suite):
        item = _case_reference(suite, plan)
        item.update(status="REFERENCE_ONLY", output=None, runtime_events=[],
                    policy_decisions={"strategy": "difficulty_for_tier", "predicted_difficulty": predicted[plan.case_id],
                                      "matches_expected": predicted[plan.case_id] == plan.expected_difficulty})
        case_results.append(item)
    return CompetitionMetricReport(
        suite_id=suite["suite_id"],
        suite_version=suite["suite_version"],
        mode=suite["mode"],
        case_count=case_count,
        claim_metrics=claim_metrics,
        difficulty=difficulty,
        gates=gates,
        evidence_scope="offline_gold: curated claim labels and difficulty policy; no generated cases",
        source_snapshot_hash=json_hash(suite["sources_payload"]) if suite.get("sources_payload") else None,
        suite_data_hash=json_hash(suite),
        selected_case_count=case_count,
        completed_generation_count=0,
        case_results=case_results,
        official_gates=_unmeasured_official_gates(gates, "no real generation or independent quality review", 0),
    )


def _unmeasured_official_gates(gates: list[MetricGate], reason: str, sample_count: int) -> list[MetricGate]:
    return [replace(gate, status="NOT_MEASURABLE", sample_count=sample_count, evidence=reason) for gate in gates]


def _case_reference(suite: dict[str, Any], plan: LiveCasePlan) -> dict[str, Any]:
    learner = next(item for item in suite["profiles_payload"]["learners"] if item["learner_id"] == plan.learner_id)
    background = next(item for item in suite["profiles_payload"]["backgrounds"]
                      if item["background_id"] == learner["background_id"])
    gold = [item for item in suite["claims_payload"]["claims"] if item.get("knowledge_point_id") in plan.target_skill_nodes]
    request = {"learner_id": plan.learner_id, "topic": plan.learning_goal, "knowledge_base_id": plan.knowledge_base_id,
               "resource_types": [plan.resource_type], "target_skill_nodes": plan.target_skill_nodes,
               "include_review": True, "include_claim_check": True}
    return {"case_id": plan.case_id, "background_id": background["background_id"],
            "input": {"learner": learner, "background": background, "request": request},
            "input_hash": json_hash({"learner": learner, "background": background, "request": request}),
            "expected_difficulty": plan.expected_difficulty, "gold_claim_ids": [item["claim_id"] for item in gold],
            "gold_source_evidence_ids": sorted({eid for item in gold for eid in item["evidence_ids"]})}


# ---------------------------------------------------------------------------
# Live 评测通路：兼容真实 API 测试。
# 通路完整实现（画像落库 -> 生产生成链路 -> Claim 审核判定 -> 三项指标），
# 但当前未执行真实 API 验证；调用方在 is_live_ready() 未就绪时必须显式
# SKIP，不得静默降级为离线结论。
# ---------------------------------------------------------------------------


def is_live_ready() -> tuple[bool, str]:
    """live 评测前置条件：显式开关 + 真实凭据；返回原因供调用方显式 SKIP。"""
    if os.getenv("RUN_LIVE_LLM") != "1":
        return False, "set RUN_LIVE_LLM=1 to enable live evaluation"
    settings = get_settings()
    if is_placeholder_api_key(settings.llm_api_key.get_secret_value().strip()):
        return False, "a real LLM_API_KEY is required"
    return True, "live evaluation ready"


@dataclass(frozen=True)
class LiveCasePlan:
    """单组用例的 live 执行计划：画像落库与生产生成请求的确定性映射。"""

    case_id: str
    resource_type: str
    target_skill_nodes: list[str]
    expected_difficulty: str
    learner_id: str
    education: str
    major: str
    learning_goal: str
    skill_level: str
    knowledge_base_id: str


def build_live_plan(suite: dict[str, Any]) -> list[LiveCasePlan]:
    """把金标用例映射为 live 执行计划；纯确定性转换，可离线校验。"""
    profiles = suite["profiles_payload"]
    backgrounds = {item["background_id"]: item for item in profiles["backgrounds"]}
    learners = {item["learner_id"]: item for item in profiles["learners"]}
    plans: list[LiveCasePlan] = []
    for case in suite["cases_payload"]["cases"]:
        learner = learners[case["learner_id"]]
        background = backgrounds[learner["background_id"]]
        plans.append(LiveCasePlan(
            case_id=case["case_id"],
            resource_type=case["resource_type"],
            target_skill_nodes=list(case["target_skill_nodes"]),
            expected_difficulty=case["expected_difficulty"],
            learner_id=learner["learner_id"],
            education=background.get("education") or "未填写",
            major=background.get("major") or "未填写",
            learning_goal=learner["learning_goal"],
            skill_level=learner["skill_level"],
            knowledge_base_id=suite["knowledge_base_id"],
        ))
    return plans


def _persist_learner(container: Any, plan: LiveCasePlan) -> LearnerProfile:
    """按 plan 幂等建档：已存在的画像不覆盖，避免破坏既有版本与掌握度。"""
    repository = container.learner_repository()
    existing = repository.get(plan.learner_id)
    if existing is not None:
        return existing
    profile = LearnerProfile(
        learner_id=plan.learner_id,
        learner_type="比赛金标评测",
        education=plan.education,
        major=plan.major,
        learning_goal=plan.learning_goal,
        skill_level=plan.skill_level,
        knowledge_base_id=plan.knowledge_base_id,
    )
    repository.save(profile)
    return profile


def _build_live_request(profile: LearnerProfile, plan: LiveCasePlan) -> GenerateRequest:
    """不预置 difficulty_preference：系统策略的难度决策正是被评测对象。"""
    return GenerateRequest(
        learner_id=profile.learner_id,
        topic=profile.learning_goal or "当前学习主题",
        knowledge_base_id=plan.knowledge_base_id,
        resource_types=[plan.resource_type],
        target_skill_nodes=list(plan.target_skill_nodes),
        include_review=True,
        include_claim_check=True,
        max_iterations=1,
        claim_max_iterations=1,
        profile_focus_mode="auto",
    )


def evaluate_live_metrics(
    suite: dict[str, Any],
    *,
    max_cases: int | None = None,
    container: Any = None,
) -> CompetitionMetricReport:
    """真实模型评测：生产生成链路 + Claim 审核判定 + 同一套三项指标。

    与离线模式的差别只在输入来源：资源与 Claim 判定来自真实 Run 的持久化
    投影，不使用金标标注。生成失败的用例不会静默消失——完成的用例数不足
    比赛门槛时，Gate 输出 NOT_MEASURABLE 而非虚报。
    """
    ready, reason = is_live_ready()
    if not ready:
        raise RuntimeError(f"live evaluation is not ready: {reason}")
    if max_cases is not None and (type(max_cases) is not int or max_cases < 1):
        raise ValueError("max_cases must be a positive integer")
    validate_suite(suite)
    if container is None:
        # 延迟导入：离线路径不初始化容器、模型网关或向量索引依赖。
        from app.containers import init_container
        container = init_container()

    plans = build_live_plan(suite)
    if max_cases is not None:
        plans = plans[:max_cases]

    thresholds = suite["competition_thresholds"]
    claims_payload = suite["claims_payload"]
    resources: list[LearningResource] = []
    claims: list[Any] = []
    judgements: list[Any] = []
    difficulty_results: list[DifficultyFixtureResult] = []
    case_results: list[dict[str, Any]] = []
    for plan in plans:
        result = _case_reference(suite, plan)
        result.update(status="FAILED", run_id=None, runtime_events=[], output=None)
        predicted = "NOT_GENERATED"
        stage = "profile"
        try:
            profile = _persist_learner(container, plan)
            request = _build_live_request(profile, plan)
            stage = "generation"
            job_service = container.generation_job_service()
            job = job_service.create_job(profile, request)
            result["run_id"] = job.run_id
            job_service.run_job(profile, request, job.run_id, job.batch_id)

            stage = "query"
            query_service = container.run_query_service()
            timeline = query_service.get_timeline(job.run_id, limit=500)
            run_resources = [LearningResource.model_validate(item) for item in timeline.resource_versions]
            claim_response = query_service.get_claims(job.run_id)
            resources.extend(run_resources)
            claims.extend(claim_response.claims)
            judgements.extend(claim_response.judgements)
            result["runtime_events"] = [
                {"event_id": event.event_id, "sequence": event.event_sequence, "type": event.event_type,
                 "node": event.node_name, "status": event.status, "payload_hash": event.payload_hash}
                for event in sorted(timeline.events, key=lambda event: event.event_sequence)
            ]
            result["source_snapshots"] = [
                {"evidence_id": item.evidence_id, "document_id": item.document_id,
                 "document_version": item.document_version, "chunk_id": item.chunk_id,
                 "snapshot_hash": item.snapshot_hash, "excerpt_hash": item.excerpt_hash}
                for item in timeline.evidence
            ]
            result["claims"] = [item.model_dump(mode="json") for item in claim_response.claims]
            result["judgements"] = [item.model_dump(mode="json") for item in claim_response.judgements]
            stage = "publication"
            leaf_ids = final_published_leaf_ids(run_resources)
            leaves = [item for item in run_resources if item.publication_status == "published"
                      and item.resource_id in leaf_ids and item.resource_type == plan.resource_type]
            if leaves:
                leaf = max(leaves, key=lambda item: item.version)
                predicted = leaf.difficulty
                output = leaf.model_dump(mode="json")
                result.update(status="COMPLETED", output=output, output_hash=json_hash(output))
            else:
                result["failure_stage"] = "publication"
                result["error_type"] = "NoPublishedResource"
        except Exception as error:
            result["failure_stage"] = stage
            result["error_type"] = type(error).__name__
        # Failed cases stay in the adaptation denominator; they cannot disappear.
        difficulty_results.append(DifficultyFixtureResult(
            case_id=plan.case_id, fixture_version=suite["cases_payload"]["fixture_version"],
            expected_difficulty=plan.expected_difficulty, predicted_difficulty=predicted,
        ))
        case_results.append(result)

    claim_metrics = compute_competition_claim_metrics(
        resources=resources,
        claims=claims,
        judgements=judgements,
        target_skill_node_ids=claims_payload["target_skill_nodes"],
    )
    difficulty = evaluate_difficulty_fixtures(difficulty_results)

    completed = sum(item["status"] == "COMPLETED" for item in case_results)
    minimum = int(thresholds.get("minimum_case_count", OFFICIAL_MINIMUM_CASE_COUNT))
    measurable = (completed >= minimum and completed == len(plans)
                  and len({item["background_id"] for item in case_results}) >= 3
                  and len({plan.resource_type for plan in plans}) >= 3
                  and suite.get("sources_payload") is not None
                  and claim_metrics.factual_claim_total > 0
                  and claim_metrics.metric_status.value == "complete")
    hallucination = claim_metrics.claim_hallucination_rate
    coverage = claim_metrics.knowledge_coverage_rate
    accuracy = difficulty.accuracy
    gates = [
        MetricGate(
            metric_id="M-HALLUCINATION",
            official_definition="专业知识谬误率（幻觉率）",
            official_threshold="< 5%",
            formula="(contradicted + not_in_evidence) / factual_claim_total on final published leaves",
            sample_count=completed,
            actual_value=hallucination,
            status=("PASS" if measurable and hallucination is not None and hallucination < float(thresholds["hallucination_rate_max"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"live model run; completed={completed}/{len(plans)}; factual_claims={claim_metrics.factual_claim_total}",
        ),
        MetricGate(
            metric_id="M-DIFFICULTY",
            official_definition="学习者画像-资源难度适配准确率",
            official_threshold=">= 85%",
            formula="correct expected-vs-predicted difficulty / all selected cases (failures included)",
            sample_count=completed,
            actual_value=accuracy,
            status=("PASS" if measurable and accuracy is not None and accuracy >= float(thresholds["difficulty_match_accuracy_min"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"live model run; completed={completed}/{len(plans)}; correct={difficulty.correct_total}/{difficulty.case_total}",
        ),
        MetricGate(
            metric_id="M-COVERAGE",
            official_definition="核心知识点覆盖率",
            official_threshold=">= 90%",
            formula="target skill nodes covered by supported factual claims / target nodes",
            sample_count=completed,
            actual_value=coverage,
            status=("PASS" if measurable and coverage is not None and coverage >= float(thresholds["knowledge_coverage_min"]) else "FAIL" if measurable else "NOT_MEASURABLE"),
            evidence=f"live model run; completed={completed}/{len(plans)}; covered={claim_metrics.covered_skill_total}/{claim_metrics.target_skill_total}",
        ),
    ]
    return CompetitionMetricReport(
        suite_id=suite["suite_id"],
        suite_version=suite["suite_version"],
        mode="live_model",
        case_count=completed,
        claim_metrics=claim_metrics,
        difficulty=difficulty,
        gates=gates,
        evidence_scope="live_model: generated resources with production self-review; independent quality review not run",
        source_snapshot_hash=json_hash(suite["sources_payload"]) if suite.get("sources_payload") else None,
        suite_data_hash=json_hash(suite),
        selected_case_count=len(plans),
        completed_generation_count=completed,
        failed_case_count=len(plans) - completed,
        case_results=case_results,
        official_gates=_unmeasured_official_gates(gates, "independent quality review NOT_RUN; production self-review only", completed),
    )
