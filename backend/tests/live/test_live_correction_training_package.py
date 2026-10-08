"""Opt-in real-provider acceptance probes for correction training packages."""

from __future__ import annotations

import os

import pytest

from app.agents.resource_agents import CorrectionTrainingPackageAgent
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.config import get_settings, is_placeholder_api_key
from app.core.llm.gateway import default_llm_gateway
from app.models.shared.agent_contracts import ResourceGenerationContext
from tests.fakes.evidence import make_evidence


pytestmark = pytest.mark.live_llm


_TARGETS = [
    ("kp-rrf-rank", "RRF 排名融合", "weak"),
    ("kp-rrf-k", "RRF 参数 k", "learning"),
    ("kp-rrf-compare", "RRF 结果比较", "learning"),
]


def _enabled() -> bool:
    if os.getenv("RUN_LIVE_LLM") != "1" and os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        return False
    return not is_placeholder_api_key(get_settings().llm_api_key.get_secret_value().strip())


@pytest.mark.parametrize("target_count", [1, 2, 3])
def test_live_correction_package_generation_contract(target_count: int):
    """Call the configured provider with sanitized one-to-three target snapshots."""

    if not _enabled():
        pytest.skip("set RUN_LIVE_LLM=1 with a real LLM_API_KEY to enable")

    selected = _TARGETS[:target_count]
    ordered_targets = [
        {
            "skill_node_id": skill_node_id,
            "name": name,
            "status": status,
            "score_band": "low" if status == "weak" else "emerging",
            "reason_codes": ["MASTERY_BELOW_TARGET"],
            "failed_dimensions": ["concept_application"],
            "teaching_strategies": ["先进行概念辨析，再进行由提示到独立的递进练习"],
            "success_criteria": ["能说明排名倒数融合的作用，并在新情境中完成比较"],
        }
        for skill_node_id, name, status in selected
    ]
    focus = {
        "schema_version": "CorrectionFocusSnapshotV1",
        "source_attempt_id": "live-attempt-sanitized",
        "source_decision_id": "live-decision-sanitized",
        "source_run_id": "live-run-sanitized",
        "learner_id": "live-learner-sanitized",
        "knowledge_base_id": "kb-live",
        "profile_version": 1,
        "focus_snapshot_hash": f"live-focus-{target_count}",
        "ordered_target_nodes": ordered_targets,
        "difficulty": "中级",
        "scaffolding_level": "high" if target_count == 1 else "medium",
    }
    evidence = [
        make_evidence(
            evidence_id="ev-rrf-core",
            knowledge_base_id="kb-live",
            document_id="rrf-source",
            excerpt=(
                "倒数排名融合（RRF）将多个检索结果中同一候选的排名转换为倒数得分并相加；"
                "参数 k 用于平滑排名靠前结果的影响。候选按融合得分排序。"
            ),
        )
    ]
    spec = build_resource_specs(
        run_id=f"live-correction-package-{target_count}",
        resource_types=["个性化纠错训练包"],
        topic="RRF 融合薄弱点强化",
        difficulty="中级",
        learning_plan={"correction_focus_snapshot": focus},
        evidence=evidence,
    )[0]
    context = ResourceGenerationContext(
        run_id=f"live-correction-package-{target_count}",
        batch_id=f"live-correction-package-{target_count}",
        topic="RRF 融合薄弱点强化",
        evidence=evidence,
        constraints={"correction_focus_snapshot": focus},
    )

    artifact = CorrectionTrainingPackageAgent().generate(
        spec,
        context,
        llm_gateway=default_llm_gateway(),
    )

    assert artifact.content_text.startswith("# ")
    assert len(artifact.content_text) <= 14000
    assert artifact.content_text.find("## 参考答案与分层反馈") > artifact.content_text.find("### 迁移练习")
    for _, name, _ in selected:
        assert f"## 强化单元：{name}" in artifact.content_text
    if target_count > 1:
        assert "## 跨知识点综合挑战" in artifact.content_text
    # These are prohibited from the prompt input and must not appear in the artifact.
    assert "live-attempt-sanitized" not in artifact.content_text
    assert "live-learner-sanitized" not in artifact.content_text
    print(f"live correction package targets={target_count} chars={len(artifact.content_text)}")
