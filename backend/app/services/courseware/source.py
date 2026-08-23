"""Source admission, ownership validation, and immutable snapshot construction."""

import hashlib
from typing import Any

from app.core.storage import file_storage
from app.db.audit.base import BaseAuditRepository
from app.models.learning_documents.schemas import LearningResource
from app.services.learning_documents.resources import ResourceService


ROLE_BY_TYPE = {
    "讲义": "lecture", "实操指南": "practice", "分阶测试题": "assessment",
    "复习清单": "checklist", "案例分析": "case_study",
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


def _snapshot(source: LearningResource) -> dict[str, Any]:
    content = source.content_text or ""
    if not content and source.file_path:
        try:
            content = file_storage.load_resource_file(source.file_path).decode("utf-8", errors="replace")
        except (OSError, ValueError):
            content = ""
    clipped = _clip(content)
    blocks = [
        {"block_id": f"b{index + 1}_{content_hash(f'{source.resource_id}:{index}:{value}')[:10]}", "text": value}
        for index, value in enumerate(line.strip() for line in clipped.split("\n") if line.strip())
    ]
    for exercise in source.exercise_items:
        question = exercise.question.strip()
        if question:
            blocks.append({
                "block_id": f"q{len(blocks) + 1}_{content_hash(f'{source.resource_id}:q:{question}')[:10]}",
                "text": question,
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
    feedback_batch_ids = {str(source.batch_id).strip() for source in sources if source.batch_id}
    if len(feedback_batch_ids) != 1 or any(not source.batch_id for source in sources):
        raise CoursewareAdmissionError("互动课件源资源必须来自同一反馈批次")
    if not any(source.resource_type == "讲义" for source in sources):
        raise CoursewareAdmissionError("至少需要选择一份已发布讲义")
    snapshots = [_snapshot(source) for source in sources]
    if not any(item["role"] == "lecture" and item["content"] for item in snapshots):
        raise CoursewareAdmissionError("讲义正文不可读取，无法生成课件")
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
