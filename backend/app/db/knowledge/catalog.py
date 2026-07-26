"""知识库目录与关系数据库之间的同步仓库。"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Iterable, List

from sqlalchemy.orm import Session

from app.db.models import (
    DiagnosticQuestionORM,
    KnowledgeBaseORM,
    KnowledgeChunkORM,
    KnowledgeDocumentORM,
    LearningDomainORM,
    LearningTrackORM,
    RagSkillNodeORM,
    SkillNodeRelationORM,
)
from app.models.schemas import DiagnosticQuestion, SkillNode


def _stable_id(prefix: str, *parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


class KnowledgeCatalogRepository:
    """维护知识库元数据、文档切片、能力图谱和诊断题的 SQL 投影。

    Chroma 用于语义召回；本仓库保存 Chroma 之外不可缺少的可查询、可审计数据。
    所有写入均为 upsert，因此初始化可以安全地重复执行。
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def upsert_knowledge_base(self, manifest: Dict[str, Any]) -> None:
        kb_id = manifest["knowledge_base_id"]
        with self.session_factory() as db:
            row = db.get(KnowledgeBaseORM, kb_id)
            values = {
                "name": manifest["name"],
                "version": manifest["version"],
                "domain": manifest.get("domain"),
                "description": manifest.get("description"),
                "learner_levels": manifest.get("learner_levels", []),
                "extra_metadata": manifest.get("raw_metadata", {}),
            }
            if row is None:
                db.add(KnowledgeBaseORM(knowledge_base_id=kb_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.commit()

    def upsert_learning_catalog(self, domain: Dict[str, Any], track: Dict[str, Any]) -> None:
        """同步面向用户展示的领域/方向层级。"""
        with self.session_factory() as db:
            domain_id = domain["domain_id"]
            domain_values = {
                "name": domain["name"],
                "description": domain.get("description"),
                "sort_order": domain.get("sort_order", 100),
                "enabled": domain.get("enabled", True),
                "extra_metadata": domain.get("metadata", {}),
            }
            domain_row = db.get(LearningDomainORM, domain_id)
            if domain_row is None:
                db.add(LearningDomainORM(domain_id=domain_id, **domain_values))
            else:
                for key, value in domain_values.items():
                    setattr(domain_row, key, value)

            track_id = track["track_id"]
            track_values = {
                "domain_id": domain_id,
                "knowledge_base_id": track["knowledge_base_id"],
                "name": track["name"],
                "description": track.get("description"),
                "target_audience": track.get("target_audience", []),
                "difficulty_levels": track.get("difficulty_levels", []),
                "sort_order": track.get("sort_order", 100),
                "enabled": track.get("enabled", True),
                "extra_metadata": track.get("metadata", {}),
            }
            track_row = db.get(LearningTrackORM, track_id)
            if track_row is None:
                db.add(LearningTrackORM(track_id=track_id, **track_values))
            else:
                for key, value in track_values.items():
                    setattr(track_row, key, value)
            db.commit()

    def list_learning_domains(self) -> List[Dict[str, Any]]:
        """读取启用中的领域/方向展示树。"""
        with self.session_factory() as db:
            domains = (
                db.query(LearningDomainORM)
                .filter_by(enabled=True)
                .order_by(LearningDomainORM.sort_order, LearningDomainORM.name)
                .all()
            )
            domain_ids = [domain.domain_id for domain in domains]
            tracks = []
            if domain_ids:
                tracks = (
                    db.query(LearningTrackORM)
                    .filter(LearningTrackORM.enabled.is_(True), LearningTrackORM.domain_id.in_(domain_ids))
                    .order_by(LearningTrackORM.sort_order, LearningTrackORM.name)
                    .all()
                )

        grouped: Dict[str, List[Dict[str, Any]]] = {domain.domain_id: [] for domain in domains}
        for track in tracks:
            grouped.setdefault(track.domain_id, []).append(self._track_payload(track))
        return [
            {
                "domain_id": domain.domain_id,
                "name": domain.name,
                "description": domain.description,
                "sort_order": domain.sort_order,
                "enabled": domain.enabled,
                "metadata": domain.extra_metadata or {},
                "tracks": grouped.get(domain.domain_id, []),
            }
            for domain in domains
        ]

    def get_learning_track(self, track_id: str) -> Dict[str, Any] | None:
        """按方向 ID 查询方向配置。"""
        with self.session_factory() as db:
            row = db.get(LearningTrackORM, track_id)
            if row is None or not row.enabled:
                return None
            return self._track_payload(row)

    def get_knowledge_base(self, knowledge_base_id: str) -> Dict[str, Any] | None:
        """按知识库 ID 查询知识库元数据。"""
        with self.session_factory() as db:
            row = db.get(KnowledgeBaseORM, knowledge_base_id)
            if row is None:
                return None
            return {
                "knowledge_base_id": row.knowledge_base_id,
                "name": row.name,
                "version": row.version,
                "domain": row.domain,
                "description": row.description,
                "learner_levels": row.learner_levels or [],
                "raw_metadata": row.extra_metadata or {},
            }

    def default_knowledge_base_id(self) -> str | None:
        """返回第一个已开放学习方向绑定的知识库 ID。"""
        with self.session_factory() as db:
            rows = (
                db.query(LearningTrackORM)
                .filter(LearningTrackORM.enabled.is_(True))
                .order_by(LearningTrackORM.sort_order, LearningTrackORM.name)
                .all()
            )
        for row in rows:
            metadata = row.extra_metadata or {}
            if metadata.get("available") is not False:
                return row.knowledge_base_id
        return rows[0].knowledge_base_id if rows else None

    @staticmethod
    def _track_payload(row: LearningTrackORM) -> Dict[str, Any]:
        return {
            "track_id": row.track_id,
            "learning_direction_id": row.track_id,
            "domain_id": row.domain_id,
            "knowledge_base_id": row.knowledge_base_id,
            "name": row.name,
            "description": row.description,
            "target_audience": row.target_audience or [],
            "difficulty_levels": row.difficulty_levels or [],
            "sort_order": row.sort_order,
            "enabled": row.enabled,
            "metadata": row.extra_metadata or {},
        }

    def sync_documents(self, documents: Iterable, chunks: Iterable) -> None:
        """把已加载文档和已切片内容同步到关系库，保留稳定的 Chroma 对照 ID。"""
        documents = list(documents)
        chunks = list(chunks)
        if not documents:
            return
        kb_ids = {document.metadata.get("knowledge_base_id") for document in documents}
        if None in kb_ids or len(kb_ids) != 1:
            raise ValueError("同步的文档必须属于同一知识库")

        with self.session_factory() as db:
            knowledge_base_id = next(iter(kb_ids))
            document_ids = {document.metadata["document_id"] for document in documents}
            chunk_ids = {chunk.metadata["chunk_id"] for chunk in chunks}

            # 将目录视为该知识库的受版本控制快照：文件被移除或重切片后，
            # 不能让旧记录继续参与审计或展示。先删切片以满足外键约束，再删文档。
            stale_chunks = db.query(KnowledgeChunkORM).filter_by(knowledge_base_id=knowledge_base_id)
            if chunk_ids:
                stale_chunks = stale_chunks.filter(~KnowledgeChunkORM.chunk_id.in_(chunk_ids))
            stale_chunks.delete(synchronize_session=False)
            stale_documents = db.query(KnowledgeDocumentORM).filter_by(knowledge_base_id=knowledge_base_id)
            if document_ids:
                stale_documents = stale_documents.filter(~KnowledgeDocumentORM.document_id.in_(document_ids))
            stale_documents.delete(synchronize_session=False)

            for document in documents:
                metadata = document.metadata
                document_id = metadata["document_id"]
                values = {
                    "knowledge_base_id": metadata["knowledge_base_id"],
                    "title": metadata["title"],
                    "source_path": metadata["source_path"],
                    "content_hash": hashlib.sha256(document.page_content.encode("utf-8")).hexdigest(),
                    "knowledge_points": metadata.get("knowledge_points", []),
                    "learner_levels": metadata.get("learner_levels", []),
                    "document_version": metadata.get("document_version"),
                    "extra_metadata": dict(metadata),
                }
                row = db.get(KnowledgeDocumentORM, document_id)
                if row is None:
                    db.add(KnowledgeDocumentORM(document_id=document_id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)

            for chunk in chunks:
                metadata = chunk.metadata
                chunk_id = metadata["chunk_id"]
                values = {
                    "knowledge_base_id": metadata["knowledge_base_id"],
                    "document_id": metadata["document_id"],
                    "chunk_index": metadata["chunk_index"],
                    "content": chunk.page_content,
                    "content_hash": metadata["content_hash"],
                    "extra_metadata": dict(metadata),
                }
                row = db.get(KnowledgeChunkORM, chunk_id)
                if row is None:
                    db.add(KnowledgeChunkORM(chunk_id=chunk_id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            db.commit()

    def upsert_skill_nodes(self, nodes: Iterable[SkillNode | Dict[str, Any] | str], knowledge_base_id: str) -> List[str]:
        """写入节点和 prerequisite 边；字符串节点兼容旧 metadata.json。"""
        normalised: List[SkillNode] = []
        for item in nodes:
            if isinstance(item, SkillNode):
                normalised.append(item)
            elif isinstance(item, str):
                normalised.append(
                    SkillNode(
                        node_id=_stable_id("skill", knowledge_base_id, item),
                        knowledge_base_id=knowledge_base_id,
                        name=item,
                    )
                )
            elif isinstance(item, dict):
                payload = dict(item)
                payload.setdefault("knowledge_base_id", knowledge_base_id)
                payload.setdefault("node_id", _stable_id("skill", knowledge_base_id, payload.get("name", "unknown")))
                normalised.append(SkillNode(**payload))
            else:
                raise TypeError("能力节点必须是 SkillNode、dict 或 str")

        name_to_id = {node.name: node.node_id for node in normalised}
        with self.session_factory() as db:
            for node in normalised:
                if node.knowledge_base_id != knowledge_base_id:
                    raise ValueError("能力节点所属 knowledge_base_id 不一致")
                values = {
                    "knowledge_base_id": knowledge_base_id,
                    "name": node.name,
                    "description": node.description,
                    "level": node.level,
                    "knowledge_points": node.knowledge_points,
                    "assessment_methods": node.assessment_methods,
                    "extra_metadata": node.metadata,
                }
                row = db.get(RagSkillNodeORM, node.node_id)
                if row is None:
                    db.add(RagSkillNodeORM(node_id=node.node_id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)

            db.flush()
            for node in normalised:
                for prerequisite in node.prerequisites:
                    parent_id = name_to_id.get(prerequisite, prerequisite)
                    exists = (
                        db.query(SkillNodeRelationORM)
                        .filter_by(
                            knowledge_base_id=knowledge_base_id,
                            parent_node_id=parent_id,
                            child_node_id=node.node_id,
                        )
                        .first()
                    )
                    if exists is None:
                        db.add(
                            SkillNodeRelationORM(
                                knowledge_base_id=knowledge_base_id,
                                parent_node_id=parent_id,
                                child_node_id=node.node_id,
                            )
                        )
            db.commit()
        return [node.node_id for node in normalised]

    def upsert_diagnostic_questions(self, questions: Iterable[DiagnosticQuestion]) -> None:
        with self.session_factory() as db:
            for question in questions:
                values = {
                    "knowledge_base_id": question.knowledge_base_id,
                    "skill_node_id": question.skill_node_id,
                    "knowledge_point": question.knowledge_point,
                    "question_type": question.question_type,
                    "difficulty": question.difficulty,
                    "question": question.question,
                    "options": question.options,
                    "answer": question.answer,
                    "explanation": question.explanation,
                    "extra_metadata": question.metadata,
                }
                row = db.get(DiagnosticQuestionORM, question.question_id)
                if row is None:
                    db.add(DiagnosticQuestionORM(question_id=question.question_id, **values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            db.commit()

    def list_skill_nodes(self, knowledge_base_id: str) -> List[SkillNode]:
        with self.session_factory() as db:
            rows = (
                db.query(RagSkillNodeORM)
                .filter_by(knowledge_base_id=knowledge_base_id)
                .order_by(RagSkillNodeORM.name)
                .all()
            )
            edges = db.query(SkillNodeRelationORM).filter_by(knowledge_base_id=knowledge_base_id).all()
        prerequisites: Dict[str, List[str]] = {row.node_id: [] for row in rows}
        names = {row.node_id: row.name for row in rows}
        for edge in edges:
            if edge.child_node_id in prerequisites:
                prerequisites[edge.child_node_id].append(names.get(edge.parent_node_id, edge.parent_node_id))
        return [
            SkillNode(
                node_id=row.node_id,
                knowledge_base_id=row.knowledge_base_id,
                name=row.name,
                description=row.description,
                level=row.level,
                prerequisites=prerequisites[row.node_id],
                knowledge_points=row.knowledge_points or [],
                assessment_methods=row.assessment_methods or [],
                metadata=row.extra_metadata or {},
            )
            for row in rows
        ]

    def list_skill_edges(self, knowledge_base_id: str) -> List[Dict[str, str]]:
        with self.session_factory() as db:
            edges = db.query(SkillNodeRelationORM).filter_by(knowledge_base_id=knowledge_base_id).all()
        return [
            {
                "source": edge.parent_node_id,
                "target": edge.child_node_id,
                "relation": edge.relation_type,
            }
            for edge in edges
        ]

    def list_diagnostic_questions(self, knowledge_base_id: str) -> List[DiagnosticQuestion]:
        with self.session_factory() as db:
            rows = (
                db.query(DiagnosticQuestionORM)
                .filter_by(knowledge_base_id=knowledge_base_id)
                .order_by(DiagnosticQuestionORM.skill_node_id, DiagnosticQuestionORM.question_id)
                .all()
            )
        return [
            DiagnosticQuestion(
                question_id=row.question_id,
                knowledge_base_id=row.knowledge_base_id,
                skill_node_id=row.skill_node_id,
                knowledge_point=row.knowledge_point,
                question_type=row.question_type,
                difficulty=row.difficulty,
                question=row.question,
                options=row.options or [],
                answer=row.answer,
                explanation=row.explanation,
                metadata=row.extra_metadata or {},
            )
            for row in rows
        ]

    def knowledge_base_counts(self, knowledge_base_id: str) -> Dict[str, int]:
        with self.session_factory() as db:
            return {
                "document_count": db.query(KnowledgeDocumentORM).filter_by(knowledge_base_id=knowledge_base_id).count(),
                "chunk_count": db.query(KnowledgeChunkORM).filter_by(knowledge_base_id=knowledge_base_id).count(),
                "skill_node_count": db.query(RagSkillNodeORM).filter_by(knowledge_base_id=knowledge_base_id).count(),
                "diagnostic_question_count": db.query(DiagnosticQuestionORM).filter_by(knowledge_base_id=knowledge_base_id).count(),
            }
