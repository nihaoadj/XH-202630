"""Build fresh messages and bind the selected schema to the same profile."""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_agents.lecture_contract import node_display_names, teaching_contract
from app.agents.resource_agents.practice import render_practice_guide_markdown

from .prompts.builder import build_review_prompt
from .types import ReviewAuditInput, ReviewProfile, ReviewPromptBundle, ReviewRequest


def internal_assessment_review_payload(resource) -> str:
    if resource.resource_type != "分阶测试题" or not resource.assessment_payload:
        return ""
    return json.dumps({"audit_scope": "internal_only_do_not_repeat_answers_in_review",
                       "assessment_package": resource.assessment_payload}, ensure_ascii=False, separators=(",", ":"))


def build_review_request(*, profile: ReviewProfile, prompt_bundle: ReviewPromptBundle, audit_input: ReviewAuditInput) -> ReviewRequest:
    specialties = tuple(f.id for f in prompt_bundle.fragments if f.id in {s.id for s in profile.allowed_specialties})
    if build_review_prompt(profile=profile, enabled_specialties=specialties) != prompt_bundle:
        raise ValueError("review prompt/profile mismatch")
    resource = audit_input.resource
    if profile.phase == "empty_resource_compat_v1":
        if resource is not None:
            raise ValueError("empty review profile received a resource")
        body = "待审核资源为空；禁止自动批准。"
    elif profile.phase in {"assessment_scope_v1", "assessment_combined_v2"}:
        if not audit_input.scope_payload:
            raise ValueError("assessment scope input missing")
        body = json.dumps(audit_input.scope_payload, ensure_ascii=False)
    else:
        context = "\n\n".join(f"[证据 {item.evidence_id}] {item.excerpt}" for item in audit_input.evidence)
        content = resource.content_text or ""
        if profile.phase == "practice_semantic_v2":
            # Canonical V3 includes all actions, code blocks, citations and checks.
            content = json.dumps(resource.practice_guide_payload, ensure_ascii=False)
            # Omit a duplicate projection only after proving exact canonical rendering.
            if (resource.content_text or "") != render_practice_guide_markdown(resource.practice_guide_payload):
                content += f"\n\n待核对的完整 Markdown 投影：\n{resource.content_text or ''}"
        body = (f"专业知识片段：\n{context}\n\n待审核的唯一资源：\n"
                f"resource_id={resource.resource_id}\nresource_type={resource.resource_type}\n"
                f"难度={resource.difficulty}\n{content}\n\n"
                f"目标难度：{audit_input.difficulty or '按画像与诊断结果'}\n"
                f"生成约束：{json.dumps(audit_input.constraints or {}, ensure_ascii=False)}")
        internal = internal_assessment_review_payload(resource)
        if internal:
            body += f"\n\n仅供内部审核的完整结构化题卷（含答案、rubric 与 evidence ID；不得在输出中复述）：\n{internal}"
        if profile.resource_type == "讲义":
            body += "\n\n讲义教学控制信息：" + json.dumps({
                "knowledge_point_display_names": node_display_names(resource.knowledge_points, audit_input.evidence),
                "teaching_contract": teaching_contract(
                    resource.difficulty, len(resource.knowledge_points),
                    target_tier=(audit_input.constraints or {}).get("target_tier"),
                ),
            }, ensure_ascii=False)
    budget, window = profile.max_output_tokens, None
    if profile.phase == "assessment_combined_v2":
        if audit_input.policy is None or audit_input.policy.assessment_strategy != "combined_v2":
            raise ValueError("combined review policy missing")
        budget = audit_input.policy.combined_max_output_tokens
        window = audit_input.policy.combined_context_tokens
    return ReviewRequest(profile, prompt_bundle, (SystemMessage(content=prompt_bundle.system_text), HumanMessage(content=body)),
                         resource.resource_id if resource is not None else None, budget, window)


def estimate_review_input(*, request: ReviewRequest) -> int:
    """UTF-8 bytes plus wrapper margin, a conservative estimate, not a tokenizer."""
    material = {"messages": [{"role": m.type, "content": m.content} for m in request.messages],
                "schema": request.profile.output_schema.model_json_schema()}
    return len(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) + 1024
