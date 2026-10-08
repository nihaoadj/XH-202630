"""Source admission, ownership validation, and immutable snapshot construction."""

import hashlib
import json
import re
from typing import Any

from app.core.storage import file_storage
from app.db.audit.base import BaseAuditRepository
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import PracticeGuidePackageV3
from app.services.learning_documents.resources import ResourceService


ROLE_BY_TYPE = {
    "实操指南": "practice", "复习清单": "checklist",
}


class CoursewareAdmissionError(ValueError):
    code = "COURSEWARE_SOURCE_ADMISSION_REJECTED"


def content_hash(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _clip(value: str, maximum: int = 12000) -> str:
    normalized = "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n"))
    return normalized[:maximum].strip()


def _knowledge_base_id(source: LearningResource, audit_repo: BaseAuditRepository) -> str | None:
    if source.run_id:
        run = audit_repo.get_run(source.run_id)
        if run and run.knowledge_base_id:
            return str(run.knowledge_base_id)
    ids = {ref.knowledge_base_id for ref in source.source_refs if ref.knowledge_base_id}
    return next(iter(ids)) if len(ids) == 1 else None


def _practice_source_blocks(content: str, resource_id: str) -> list[dict[str, str]]:
    """Preserve Markdown semantics for LLM step-boundary extraction.

    Code fences and paragraph runs are atomic.  Splitting every physical line
    erased the document structure and made a code line or checklist item look
    indistinguishable from an operation step.
    """
    rows = content.split("\n")
    values: list[tuple[str, str]] = []
    current: list[str] = []
    in_code = False

    def flush(kind: str = "paragraph") -> None:
        nonlocal current
        text = "\n".join(current).strip()
        if text:
            values.append((kind, text))
        current = []

    for raw in rows:
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_code:
                current.append(raw)
                in_code = False
                flush("code")
            else:
                flush()
                current = [raw]
                in_code = True
            continue
        if in_code:
            current.append(raw)
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            flush()
            values.append(("heading", stripped))
        elif not stripped:
            flush()
        else:
            current.append(raw)
    flush("code" if in_code else "paragraph")
    return [
        {"block_id": f"b{index + 1}_{content_hash(f'{resource_id}:semantic:{kind}:{text}')[:10]}", "text": text, "kind": kind}
        for index, (kind, text) in enumerate(values)
    ]


def _structured_practice_source_blocks(package: dict[str, Any], resource_id: str) -> list[dict[str, Any]]:
    """Expose each fixed guide phase and its steps as immutable source blocks."""
    blocks: list[dict[str, Any]] = []
    def append_phase(phase_id: str, title: str, goal: str, items: list[str]) -> None:
        blocks.append({
            "block_id": f"practice_{phase_id}_{content_hash(f'{resource_id}:{phase_id}')[:16]}",
            "text": "\n".join([f"## {title}", f"目标：{goal}", *(f"- {item}" for item in items)]),
            "kind": "practice_phase", "practice_phase_id": phase_id,
        })
    append_phase("prepare", "准备阶段", package["preparation"]["goal"], package["preparation"]["items"])
    for step in package["practice"].get("steps") or []:
        if not isinstance(step, dict) or not step.get("step_id"):
            continue
        step_id = str(step["step_id"])
        text = "\n".join(filter(None, [
            f"### 步骤 {step_id.removeprefix('step-')}：{step.get('title') or ''}",
            str(step.get("instruction_text") or ""),
            f"完成验证：{step.get('verification') or ''}",
        ])).strip()
        blocks.append({
            "block_id": f"practice_{content_hash(f'{resource_id}:{step_id}')[:16]}",
            "text": text, "kind": "practice_step", "practice_phase_id": "practice", "practice_step_id": step_id,
            "instruction_text": str(step.get("instruction_text") or ""),
            "code_blocks": list(step.get("code_blocks") or []),
        })
    append_phase("verify", "验证阶段", package["verification"]["goal"], package["verification"]["checklist"])
    append_phase("reflect", "复盘阶段", package["reflection"]["goal"], [package["reflection"]["summary"]])
    return blocks


def _required_practice_package(source: LearningResource) -> dict[str, Any]:
    """Return a validated canonical practice package or reject courseware admission.

    Practice-guide Markdown is a public projection, not an authoritative
    source for interactive steps.  Permitting a Markdown fallback here loses
    step boundaries and can produce malformed courseware pages.
    """
    package = source.practice_guide_payload
    if not isinstance(package, dict) or package.get("schema_version") != "3.0":
        raise CoursewareAdmissionError("实操指南缺少 V3 固定阶段 JSON，需重新生成后才能创建互动课件")
    try:
        validated = PracticeGuidePackageV3.model_validate(
            {key: value for key, value in package.items() if key != "payload_hash"}
        )
    except ValueError as exc:
        raise CoursewareAdmissionError("实操指南固定阶段 JSON 无效，需重新生成后才能创建互动课件") from exc
    canonical_payload = validated.model_dump(mode="json")
    payload_hash = content_hash(
        json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if package.get("payload_hash") != payload_hash or source.practice_guide_payload_hash != payload_hash:
        raise CoursewareAdmissionError("实操指南结构化 JSON 校验摘要不匹配，需重新生成后才能创建互动课件")
    return {**canonical_payload, "payload_hash": payload_hash}


def _snapshot(source: LearningResource) -> dict[str, Any]:
    content = source.content_text or ""
    if not content and source.file_path:
        try:
            content = file_storage.load_resource_file(source.file_path).decode("utf-8", errors="replace")
        except (OSError, ValueError):
            content = ""
    clipped = _clip(content)
    practice_package = _required_practice_package(source) if source.resource_type == "实操指南" else None
    blocks = (
        _structured_practice_source_blocks(practice_package, source.resource_id)
        if source.resource_type == "实操指南"
        else [
            {"block_id": f"b{index + 1}_{content_hash(f'{source.resource_id}:{index}:{value}')[:10]}", "text": value}
            for index, value in enumerate(line.strip() for line in clipped.split("\n") if line.strip())
        ]
    )
    for exercise in source.exercise_items:
        question = exercise.question.strip()
        if question:
            blocks.append({
                "block_id": f"q{len(blocks) + 1}_{content_hash(f'{source.resource_id}:q:{question}')[:10]}",
                "text": question,
            })
    # A V2 review checklist is a structured learning source, not merely a
    # Markdown document.  Preserve stable question boundaries in the frozen
    # snapshot so the courseware renderer can bind each interaction to the
    # already-reviewed question without asking a second model to recreate it.
    review_package = source.review_practice_payload if source.resource_type == "复习清单" else None
    if isinstance(review_package, dict) and review_package.get("schema_version") == "2.0":
        for node in review_package.get("node_blocks") or []:
            if not isinstance(node, dict):
                continue
            for question in [*(node.get("recall_questions") or []), *(node.get("distinction_questions") or []), node.get("example_recognition")]:
                if not isinstance(question, dict) or not question.get("question_id"):
                    continue
                question_id = str(question["question_id"])
                blocks.append({
                    "block_id": f"review_{content_hash(f'{source.resource_id}:{question_id}')[:16]}",
                    "text": str(question.get("prompt") or question.get("statement") or question.get("candidate_a") or question_id),
                    "kind": "review_question", "review_question_id": question_id,
                    "skill_node_id": str(node.get("skill_node_id") or ""),
                })
            summary = str(node.get("knowledge_summary") or "").strip()
            if summary:
                node_id = str(node.get("skill_node_id") or "")
                blocks.append({
                    "block_id": f"review_summary_{content_hash(f'{source.resource_id}:{node_id}')[:16]}",
                    "text": summary,
                    "kind": "review_summary",
                    "skill_node_id": node_id,
                })
    # Convert source references into a small, versioned graph.  The graph is
    # deliberately metadata-only: snippets and learner prose never enter the
    # courseware contract, while every source/block edge remains auditable.
    source_nodes = [{
        "node_id": f"resource:{source.resource_id}",
        "node_type": "resource",
        "resource_id": source.resource_id,
        "version": source.version,
    }]
    source_edges: list[dict[str, Any]] = []
    for ref in sorted(source.source_refs, key=lambda item: (str(item.doc_id), str(item.chunk_id or ""))):
        ref_id = str(ref.evidence_id or ref.chunk_id or ref.doc_id)
        node_id = f"evidence:{content_hash(ref_id)[:16]}"
        source_nodes.append({
            "node_id": node_id, "node_type": "evidence",
            "document_id": str(ref.doc_id), "document_version": ref.document_version,
            "chunk_id": ref.chunk_id, "evidence_id": ref.evidence_id,
        })
        source_edges.append({"from": f"resource:{source.resource_id}", "to": node_id, "relation": "derived_from"})
    for block in blocks:
        node_id = f"block:{block['block_id']}"
        source_nodes.append({"node_id": node_id, "node_type": "block", "block_id": block["block_id"]})
        source_edges.append({"from": f"resource:{source.resource_id}", "to": node_id, "relation": "contains"})
    return {
        "resource_id": source.resource_id, "resource_type": source.resource_type,
        "resource_family_id": source.resource_family_id or source.resource_id,
        "role": ROLE_BY_TYPE[source.resource_type], "run_id": source.run_id, "batch_id": source.batch_id,
        "version": source.version, "topic": source.topic or "学习主题",
        "knowledge_points": source.knowledge_points, "content": clipped, "blocks": blocks,
        "content_hash": content_hash(content),
        "exercise_items": [item.model_dump(mode="json") for item in source.exercise_items],
        "review_practice_payload": review_package if isinstance(review_package, dict) else None,
        "review_practice_payload_hash": source.review_practice_payload_hash,
        "practice_guide_payload": practice_package if isinstance(practice_package, dict) else None,
        "practice_guide_payload_hash": source.practice_guide_payload_hash,
        "source_graph": {"schema_version": "1.0", "nodes": source_nodes, "edges": source_edges},
    }


def admit_and_snapshot(
    resource_service: ResourceService, audit_repo: BaseAuditRepository, job: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    sources: list[LearningResource] = []
    knowledge_base_ids: set[str] = set()
    for resource_id in job["source_resource_ids"]:
        source = resource_service.get(resource_id)
        if source is None or source.learner_id != job["learner_id"]:
            raise CoursewareAdmissionError("源资源不存在或无权访问")
        if source.publication_status != "published":
            raise CoursewareAdmissionError("课件只能使用已发布资源")
        if source.resource_type not in ROLE_BY_TYPE:
            raise CoursewareAdmissionError("源资源类型不受课件工作流支持")
        knowledge_base_id = _knowledge_base_id(source, audit_repo)
        if not knowledge_base_id:
            raise CoursewareAdmissionError("源资源缺少可审计的知识库归属")
        knowledge_base_ids.add(knowledge_base_id)
        sources.append(source)
    if len(knowledge_base_ids) != 1:
        raise CoursewareAdmissionError("源资源必须来自同一知识库")
    if len(sources) != 1:
        raise CoursewareAdmissionError("每份互动课件只能对应一份源学习资源")
    snapshots = [_snapshot(source) for source in sources]
    if not snapshots[0]["content"] and not snapshots[0]["exercise_items"]:
        raise CoursewareAdmissionError("源资源正文或题目不可读取，无法生成互动课件")
    return snapshots, next(iter(knowledge_base_ids))


def frozen_source_batch_id(resource_service: ResourceService, source_resource_ids: list[str]) -> str | None:
    """Return a batch only when every requested source proves one same batch."""
    values: list[str] = []
    for resource_id in source_resource_ids:
        source = resource_service.get(resource_id)
        batch_id = str(source.batch_id).strip() if source and source.batch_id else ""
        if not batch_id:
            return None
        values.append(batch_id)
    return values[0] if values and len(set(values)) == 1 else None
