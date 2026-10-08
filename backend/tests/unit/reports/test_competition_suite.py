"""比赛金标套件的结构与标注协议校验（纯文件读取，不触库、不调模型）。"""

from __future__ import annotations

import copy

import pytest

from app.core.learning_tiers import TIER_DIFFICULTIES
from app.services.reports.competition_suite import (
    build_live_plan,
    evaluate_competition_metrics,
    is_live_ready,
    load_suite,
    validate_suite,
)


def _loaded() -> dict:
    return load_suite()


def test_suite_meets_competition_structure_requirements():
    suite = _loaded()
    profiles = suite["profiles_payload"]
    cases = suite["cases_payload"]

    # 比赛硬性要求：至少 50 组用例、至少 3 组不同背景画像。
    assert len(cases["cases"]) >= 50
    assert len({item["background_id"] for item in profiles["backgrounds"]}) >= 3
    # 本套件实际结构：3 背景 × 3 水平 × 2 目标节点 = 18 画像，× 3 资源类型 = 54 用例。
    assert len(profiles["learners"]) == 18
    assert len({item["resource_type"] for item in cases["cases"]}) == 3
    assert len(cases["cases"]) == 18 * 3
    case_ids = [item["case_id"] for item in cases["cases"]]
    assert len(case_ids) == len(set(case_ids))


def test_difficulty_annotation_protocol_is_consistent():
    suite = _loaded()
    profiles = suite["profiles_payload"]
    cases = suite["cases_payload"]
    learners = {item["learner_id"]: item for item in profiles["learners"]}

    upgraded = 0
    for case in cases["cases"]:
        learner = learners[case["learner_id"]]
        if learner["background_id"] == "data" and learner["tier"] == 1:
            # 规则 A：ml_basics 背景 + tier1 目标 -> 期望中级。
            assert case["expected_difficulty"] == "中级"
            upgraded += 1
        else:
            # 规则 B：其余画像保持 tier 基准难度。
            assert case["expected_difficulty"] == TIER_DIFFICULTIES[learner["tier"]]
    assert upgraded == 6


def test_gold_claims_cover_every_target_node_and_keep_negative_cases():
    suite = _loaded()
    claims = suite["claims_payload"]["claims"]
    supported_nodes = {
        item["knowledge_point_id"]
        for item in claims
        if item["verdict"] == "supported" and item["knowledge_point_id"]
    }
    assert supported_nodes == set(suite["claims_payload"]["target_skill_nodes"])

    verdicts = {item["verdict"] for item in claims}
    assert {"supported", "contradicted", "not_in_evidence", "non_factual"} <= verdicts
    # 负例必须遵守 claim 领域契约的证据约束。
    for item in claims:
        if item["verdict"] in {"supported", "contradicted"}:
            assert item["evidence_ids"]
        else:
            assert not item["evidence_ids"]


def test_validate_rejects_suite_with_insufficient_cases():
    suite = _loaded()
    broken = copy.deepcopy(suite)
    # 削减到 50 组以下，应被加载期校验拒绝。
    broken["cases_payload"]["cases"] = broken["cases_payload"]["cases"][:49]
    with pytest.raises(ValueError, match="at least 50 cases"):
        validate_suite(broken)


def test_validate_rejects_suite_with_uncovered_target_nodes():
    suite = _loaded()
    broken = copy.deepcopy(suite)
    # 制造一个没有任何 supported claim 覆盖的目标节点。
    broken["claims_payload"]["target_skill_nodes"] = sorted(
        set(broken["claims_payload"]["target_skill_nodes"]) | {"nonexistent_node"}
    )
    with pytest.raises(ValueError, match="not fully covered"):
        validate_suite(broken)


def test_validate_rejects_learner_tier_drift():
    suite = _loaded()
    broken = copy.deepcopy(suite)
    for learner in broken["profiles_payload"]["learners"]:
        if learner["learner_id"] == "gold-student-t2-chunking":
            learner["target_skill_nodes"] = ["rag_basics"]
    with pytest.raises(ValueError, match="tier must match target node tier"):
        validate_suite(broken)


def test_live_plan_maps_every_case_with_background_dimensions():
    plans = build_live_plan(_loaded())
    assert len(plans) == 54
    # 背景维度的学历/专业必须来自 backgrounds 定义，而不是学习者条目。
    by_id = {plan.case_id: plan for plan in plans}
    data_case = by_id["gold-data-t1-embed-text"]
    assert data_case.education == "硕士"
    assert data_case.major == "数据科学与大数据"
    assert data_case.skill_level == "零基础"
    assert data_case.knowledge_base_id == "rag_engineering_training"
    assert data_case.resource_type == "讲义"
    backend_case = by_id["gold-backend-t2-vector-assessment"]
    assert backend_case.education == "本科"
    assert backend_case.resource_type == "分阶测试题"


def test_is_live_ready_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("RUN_LIVE_LLM", raising=False)
    ready, reason = is_live_ready()
    assert ready is False
    assert "RUN_LIVE_LLM=1" in reason


def _write_synthetic_domain(root):
    """生成一个合成第二领域的完整数据文件（知识库 manifest + 金标套件）。

    用于证明领域迁移只需新增数据文件、不需要修改评测代码：
    6 个能力节点（3 tier × 2）、3 背景 × 3 水平 × 2 节点 = 18 画像、
    54 组用例、每节点 5 条 supported Claim + 1 条 not_in_evidence 负例。
    """
    import json as _json

    kb_dir = root / "kb" / "synthetic_security_domain"
    kb_dir.mkdir(parents=True)
    nodes = [
        {"node_id": "sec_basic", "name": "安全基础", "level": "初级", "tier": 1, "knowledge_points": ["资产台账"], "assessment_methods": ["单选题"]},
        {"node_id": "sec_asset", "name": "资产识别", "level": "初级", "tier": 1, "knowledge_points": ["资产分类"], "assessment_methods": ["单选题"]},
        {"node_id": "sec_zone", "name": "分区隔离", "level": "中级", "tier": 2, "prerequisites": ["安全基础"], "knowledge_points": ["区域划分"], "assessment_methods": ["设计题"]},
        {"node_id": "sec_monitor", "name": "流量监测", "level": "中级", "tier": 2, "prerequisites": ["资产识别"], "knowledge_points": ["异常检测"], "assessment_methods": ["实操题"]},
        {"node_id": "sec_defense", "name": "纵深防御", "level": "高级", "tier": 3, "prerequisites": ["分区隔离"], "knowledge_points": ["多层防护"], "assessment_methods": ["综合题"]},
        {"node_id": "sec_response", "name": "应急响应", "level": "高级", "tier": 3, "prerequisites": ["流量监测"], "knowledge_points": ["处置流程"], "assessment_methods": ["案例分析题"]},
    ]
    (kb_dir / "metadata.json").write_text(_json.dumps({
        "knowledge_base_id": "synthetic_security_domain",
        "knowledge_base_name": "synthetic_security_domain",
        "version": "1.0.0",
        "skill_nodes": nodes,
    }, ensure_ascii=False), encoding="utf-8")

    tier_nodes = {1: ["sec_basic", "sec_asset"], 2: ["sec_zone", "sec_monitor"], 3: ["sec_defense", "sec_response"]}
    backgrounds = [
        {"background_id": f"bg{index}", "role": f"角色{index}", "education": "本科", "major": "专业", "years_of_experience": index, "prior_ai_experience": "none"}
        for index in range(3)
    ]
    learners, cases, claims = [], [], []
    tier_labels = {1: "初级", 2: "中级", 3: "高级"}
    for background in backgrounds:
        for tier in (1, 2, 3):
            for node in tier_nodes[tier]:
                learner_id = f"synth-{background['background_id']}-t{tier}-{node}"
                learners.append({
                    "learner_id": learner_id,
                    "background_id": background["background_id"],
                    "skill_level": tier_labels[tier],
                    "tier": tier,
                    "learning_goal": f"掌握{node}",
                    "target_skill_nodes": [node],
                    "expected_difficulty": TIER_DIFFICULTIES[tier],
                })
                for code, resource_type in (("text", "讲义"), ("practice", "实操指南"), ("assessment", "分阶测试题")):
                    cases.append({
                        "case_id": f"{learner_id}-{code}",
                        "learner_id": learner_id,
                        "resource_type": resource_type,
                        "target_skill_nodes": [node],
                        "expected_difficulty": TIER_DIFFICULTIES[tier],
                    })
    for node in tier_nodes[1] + tier_nodes[2] + tier_nodes[3]:
        for index in range(5):
            claims.append({
                "claim_id": f"synth-{node}-{index}",
                "claim_text": f"{node} 的第 {index} 条金标事实。",
                "claim_type": "factual",
                "verdict": "supported",
                "knowledge_point_id": node,
                "source_document_id": "synthetic_doc",
                "evidence_ids": [f"ev-synth-{node}-{index}"],
            })
    claims.append({
        "claim_id": "synth-negative-01",
        "claim_text": "合成领域不存在的断言。",
        "claim_type": "factual",
        "verdict": "not_in_evidence",
        "knowledge_point_id": None,
        "source_document_id": None,
        "evidence_ids": [],
    })

    suite_dir = root / "suite"
    suite_dir.mkdir()
    (suite_dir / "profiles.json").write_text(_json.dumps({
        "fixture_version": "v1",
        "knowledge_base_id": "synthetic_security_domain",
        "annotation_protocol": {},
        "backgrounds": backgrounds,
        "learners": learners,
    }, ensure_ascii=False), encoding="utf-8")
    (suite_dir / "cases.json").write_text(_json.dumps({
        "fixture_version": "v1",
        "knowledge_base_id": "synthetic_security_domain",
        "resource_types": ["讲义", "实操指南", "分阶测试题"],
        "case_count": len(cases),
        "cases": cases,
    }, ensure_ascii=False), encoding="utf-8")
    (suite_dir / "claims.json").write_text(_json.dumps({
        "fixture_version": "v1",
        "knowledge_base_id": "synthetic_security_domain",
        "target_skill_nodes": [node["node_id"] for node in nodes],
        "claims": claims,
    }, ensure_ascii=False), encoding="utf-8")
    (suite_dir / "suite.json").write_text(_json.dumps({
        "suite_id": "synthetic-security-gold-suite",
        "suite_version": "v1",
        "fixture_version": "v1",
        "knowledge_base_id": "synthetic_security_domain",
        "mode": "offline_gold",
        "competition_thresholds": {
            "hallucination_rate_max": 0.05,
            "difficulty_match_accuracy_min": 0.85,
            "knowledge_coverage_min": 0.90,
            "minimum_case_count": 50,
        },
        "files": {"profiles": "profiles.json", "cases": "cases.json", "claims": "claims.json"},
        "evaluation_notes": "synthetic domain",
    }, ensure_ascii=False), encoding="utf-8")
    return suite_dir / "suite.json"


def test_evaluation_pipeline_transfers_to_new_domain_without_code_changes(tmp_path):
    """领域泛化与可迁移能力的可执行证明：仅提供新领域数据文件即可复用全部评测代码。"""
    suite_path = _write_synthetic_domain(tmp_path)
    suite = load_suite(
        suite_path,
        expected_suite_id="synthetic-security-gold-suite",
        kb_root=tmp_path / "kb",
    )
    report = evaluate_competition_metrics(suite, kb_root=tmp_path / "kb")

    assert suite["knowledge_base_id"] == "synthetic_security_domain"
    assert report.case_count == 54
    # 合成套件按同一标注协议构造，三项指标应全部可测量且达标。
    assert {gate.status for gate in report.gates} == {"PASS"}
    assert report.difficulty.accuracy == 1.0
    assert report.claim_metrics.knowledge_coverage_rate == 1.0
    assert report.claim_metrics.claim_hallucination_rate == 1 / 31
