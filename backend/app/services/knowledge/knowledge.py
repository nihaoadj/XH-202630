"""知识库目录、能力图谱和诊断题的只读服务。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from app.core.retrieval.knowledge_base import (
    chunk_documents,
    load_documents,
    load_knowledge_base_manifest,
    resolve_knowledge_base_dir_by_id,
)
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.learning_documents.schemas import DiagnosticQuestion, SkillNode


# Retain deprecated catalog records for existing learner histories, but do not
# offer them as choices when creating a new learning direction.
HIDDEN_LEARNING_DOMAIN_IDS = {"industrial_internet"}
HIDDEN_LEARNING_TRACK_IDS = {"model_evaluation_safety"}


class KnowledgeService:
    """从版本管理的知识库目录读取可公开的目录信息。

    题库答案只在服务端保留；对外题目列表不会返回 answer 或 explanation。
    """

    def __init__(self, catalog: KnowledgeCatalogRepository | None = None):
        self.catalog = catalog

    def _resolve_knowledge_base_id(self, learning_direction_id: str | None = None) -> str | None:
        if not learning_direction_id or self.catalog is None:
            return learning_direction_id
        track = self.catalog.get_learning_track(learning_direction_id)
        if track is None:
            return learning_direction_id
        if track.get("metadata", {}).get("available") is False:
            raise ValueError(f"学习方向尚未开放：{learning_direction_id}")
        return track["knowledge_base_id"]

    def _manifest(self, knowledge_base_id: str | None = None) -> dict[str, Any]:
        if self.catalog is not None:
            resolved_id = self._resolve_knowledge_base_id(knowledge_base_id)
            if resolved_id is None:
                resolved_id = self.catalog.default_knowledge_base_id()
            if resolved_id is None:
                raise FileNotFoundError("数据库中缺少可用学习方向")
            row = self.catalog.get_knowledge_base(resolved_id)
            if row is None:
                raise FileNotFoundError(f"数据库中缺少知识库：{resolved_id}")
            return row
        kb_dir = resolve_knowledge_base_dir_by_id(self._resolve_knowledge_base_id(knowledge_base_id))
        return load_knowledge_base_manifest(str(kb_dir))

    def _ensure_knowledge_base(self, knowledge_base_id: str | None) -> dict[str, Any]:
        try:
            return self._manifest(knowledge_base_id)
        except FileNotFoundError as exc:
            raise ValueError(f"学习方向不存在或尚未配置教学数据：{knowledge_base_id}") from exc

    def list_learning_directions(self) -> list[dict[str, Any]]:
        """返回面向用户展示的学习方向列表，隐藏“知识库”实现概念。"""
        directions = []
        default_id = self._manifest()["knowledge_base_id"]
        for domain in self.list_learning_domains():
            for track in domain["tracks"]:
                metadata = track.get("metadata", {})
                directions.append(
                    {
                        "learning_direction_id": track["track_id"],
                        "track_id": track["track_id"],
                        "domain_id": domain["domain_id"],
                        "title": track["name"],
                        "description": track.get("description"),
                        "version": metadata.get("version"),
                        "document_count": metadata.get("document_count", 0),
                        "skill_node_count": metadata.get("skill_node_count", 0),
                        "is_default": track.get("knowledge_base_id") == default_id,
                        "metadata": metadata,
                    }
                )
        return directions

    def list_learning_domains(self) -> list[dict[str, Any]]:
        """返回领域 -> 方向的两级展示树。"""
        if self.catalog is None:
            return []
        default_id = self._manifest()["knowledge_base_id"]
        domains = [
            domain
            for domain in self.catalog.list_learning_domains()
            if domain["domain_id"] not in HIDDEN_LEARNING_DOMAIN_IDS
        ]
        for domain in domains:
            domain["tracks"] = [
                track
                for track in domain["tracks"]
                if track["track_id"] not in HIDDEN_LEARNING_TRACK_IDS
            ]
            for track in domain["tracks"]:
                track["is_default"] = track.get("knowledge_base_id") == default_id
        return domains

    def list_skill_nodes(self, knowledge_base_id: str | None = None, level: str | None = None) -> list[SkillNode]:
        if self.catalog is not None:
            manifest = self._ensure_knowledge_base(knowledge_base_id)
            nodes = self.catalog.list_skill_nodes(manifest["knowledge_base_id"])
            if level:
                nodes = [node for node in nodes if node.level == level]
            children: dict[str, list[str]] = defaultdict(list)
            for edge in self.catalog.list_skill_edges(manifest["knowledge_base_id"]):
                children[edge["source"]].append(edge["target"])
            return [node.model_copy(update={"children": children.get(node.node_id, [])}) for node in nodes]

        manifest = self._ensure_knowledge_base(knowledge_base_id)
        raw_nodes = manifest.get("skill_nodes", [])
        node_ids_by_name = {node["name"]: node["node_id"] for node in raw_nodes}
        children: dict[str, list[str]] = defaultdict(list)
        for node in raw_nodes:
            for prerequisite in node.get("prerequisites", []):
                children[node_ids_by_name.get(prerequisite, prerequisite)].append(node["node_id"])

        nodes = []
        for raw in raw_nodes:
            if level and raw.get("level") != level:
                continue
            payload = dict(raw)
            payload["knowledge_base_id"] = manifest["knowledge_base_id"]
            payload["children"] = children.get(raw["node_id"], [])
            nodes.append(SkillNode(**payload))
        return nodes

    def list_edges(self, knowledge_base_id: str | None = None) -> list[dict[str, str]]:
        if self.catalog is not None:
            manifest = self._ensure_knowledge_base(knowledge_base_id)
            return self.catalog.list_skill_edges(manifest["knowledge_base_id"])

        manifest = self._ensure_knowledge_base(knowledge_base_id)
        node_ids_by_name = {node["name"]: node["node_id"] for node in manifest.get("skill_nodes", [])}
        return [
            {
                "source": node_ids_by_name.get(prerequisite, prerequisite),
                "target": node["node_id"],
                "relation": "prerequisite",
            }
            for node in manifest.get("skill_nodes", [])
            for prerequisite in node.get("prerequisites", [])
        ]

    def load_diagnostic_questions(self, knowledge_base_id: str | None = None) -> list[DiagnosticQuestion]:
        if self.catalog is not None:
            manifest = self._ensure_knowledge_base(knowledge_base_id)
            return self.catalog.list_diagnostic_questions(manifest["knowledge_base_id"])

        manifest = self._ensure_knowledge_base(knowledge_base_id)
        path = resolve_knowledge_base_dir_by_id(manifest["knowledge_base_id"]) / "diagnostic_questions.json"
        if not path.exists():
            return []
        import json

        with path.open("r", encoding="utf-8") as file:
            raw_questions = json.load(file)
        return [DiagnosticQuestion(**question) for question in raw_questions]

    def load_assessment_questions(self, knowledge_base_id: str | None = None) -> list[DiagnosticQuestion]:
        """加载学习反馈使用的分层测评题库。"""
        manifest = self._ensure_knowledge_base(knowledge_base_id)
        if self.catalog is not None:
            return self.catalog.list_assessment_questions(manifest["knowledge_base_id"])

        # 无 SQL catalog 的本地开发/离线场景保留 JSON 读取能力；生产运行时
        # 通过 catalog 构造服务，因此只会读取数据库投影。
        try:
            kb_dir = resolve_knowledge_base_dir_by_id(manifest["knowledge_base_id"])
        except FileNotFoundError:
            # 数据库中可能登记了尚未配置本地题库文件的其他学习方向。
            return []
        path = kb_dir / "assessment_questions.json"
        if not path.exists():
            return []
        import json

        with path.open("r", encoding="utf-8") as file:
            raw_questions = json.load(file)
        if not isinstance(raw_questions, list):
            raise ValueError(f"测评题库格式错误，应为 JSON 数组：{path}")
        return [DiagnosticQuestion(**question) for question in raw_questions]

    def select_assessment_questions(
        self,
        knowledge_base_id: str | None = None,
        skill_node_ids: Iterable[str] | None = None,
        level: str | None = None,
        limit: int | None = None,
    ) -> list[DiagnosticQuestion]:
        """按能力节点和难度分层选择测评题，结果顺序稳定、便于复现。"""
        requested_nodes = {item for item in (skill_node_ids or []) if item}
        nodes = {node.node_id: node for node in self.list_skill_nodes(knowledge_base_id)}
        if requested_nodes - set(nodes):
            raise ValueError(f"包含不存在的能力节点：{', '.join(sorted(requested_nodes - set(nodes)))}")

        questions = [
            question
            for question in self.load_assessment_questions(knowledge_base_id)
            if (not requested_nodes or question.skill_node_id in requested_nodes)
            and (not level or (nodes.get(question.skill_node_id) and nodes[question.skill_node_id].level == level))
        ]
        if limit is None or limit >= len(questions):
            return self._order_assessment_questions(questions)
        if limit <= 0:
            return []
        ordered = self._order_assessment_questions(questions)
        # 十题会话保持题库约定的 3/3/4 分层；更小或更大题量按同一周期扩展。
        difficulty_cycle = (
            "简单", "中等", "困难", "困难", "简单",
            "中等", "困难", "简单", "中等", "困难",
        )
        quotas = {
            difficulty: sum(
                1
                for index in range(limit)
                if difficulty_cycle[index % len(difficulty_cycle)] == difficulty
            )
            for difficulty in ("简单", "中等", "困难")
        }
        selected: list[DiagnosticQuestion] = []
        selected_nodes: set[str | None] = set()
        for difficulty in ("简单", "中等", "困难"):
            difficulty_questions = [
                question
                for question in ordered
                if question.difficulty == difficulty
            ]
            # 跨节点抽题时先覆盖尚未出现的能力节点；节点不足时再回到已选节点补题。
            difficulty_questions.sort(
                key=lambda question: question.skill_node_id in selected_nodes
            )
            chosen = difficulty_questions[:quotas[difficulty]]
            selected.extend(chosen)
            selected_nodes.update(question.skill_node_id for question in chosen)

        # 某些知识库可能没有完整的三档难度，用其余题补满而不是返回不足题量。
        selected_ids = {question.question_id for question in selected}
        selected.extend(question for question in ordered if question.question_id not in selected_ids)
        return selected[:limit]

    @staticmethod
    def _order_assessment_questions(questions: list[DiagnosticQuestion]) -> list[DiagnosticQuestion]:
        """在每个难度层内轮转节点，避免小题量被单一节点占满。"""
        difficulties = ("简单", "中等", "困难")
        node_order = list(dict.fromkeys(question.skill_node_id for question in questions))
        ordered: list[DiagnosticQuestion] = []
        seen: set[str] = set()
        for difficulty in difficulties:
            buckets = {
                node_id: [
                    question
                    for question in questions
                    if question.skill_node_id == node_id and question.difficulty == difficulty
                ]
                for node_id in node_order
            }
            while any(buckets.values()):
                for node_id in node_order:
                    if buckets[node_id]:
                        question = buckets[node_id].pop(0)
                        ordered.append(question)
                        seen.add(question.question_id)
        ordered.extend(question for question in questions if question.question_id not in seen)
        return ordered

    def select_diagnostic_questions(
        self,
        knowledge_base_id: str | None = None,
        skill_node_ids: Iterable[str] | None = None,
        level: str | None = None,
        limit: int | None = None,
    ) -> list[DiagnosticQuestion]:
        requested_nodes = {item for item in (skill_node_ids or []) if item}
        nodes = {node.node_id: node for node in self.list_skill_nodes(knowledge_base_id)}
        if requested_nodes - set(nodes):
            raise ValueError(f"包含不存在的能力节点：{', '.join(sorted(requested_nodes - set(nodes)))}")

        questions = [
            question
            for question in self.load_diagnostic_questions(knowledge_base_id)
            if (not requested_nodes or question.skill_node_id in requested_nodes)
            and (not level or (nodes.get(question.skill_node_id) and nodes[question.skill_node_id].level == level))
        ]
        if limit is None or limit >= len(questions):
            return questions
        if limit <= 0:
            return []

        # 按诊断维度轮转：小题量时优先覆盖更多节点，而不是连续返回同一节点的三道题。
        ordered: list[DiagnosticQuestion] = []
        dimensions = ("concept", "scenario", "misconception")
        for dimension in dimensions:
            ordered.extend(
                question
                for question in questions
                if question.metadata.get("diagnostic_dimension") == dimension
            )
        ordered.extend(question for question in questions if question not in ordered)
        return ordered[:limit]

    def public_question(self, question: DiagnosticQuestion) -> dict[str, Any]:
        payload = question.model_dump()
        payload.pop("answer", None)
        payload.pop("explanation", None)
        return payload

    def get_info(self, knowledge_base_id: str | None = None) -> dict[str, Any]:
        manifest = self._ensure_knowledge_base(knowledge_base_id)
        if self.catalog is not None:
            counts = self.catalog.knowledge_base_counts(manifest["knowledge_base_id"])
            index_status = self.catalog.get_index_status(manifest["knowledge_base_id"])
            return {
                "knowledge_base_id": manifest["knowledge_base_id"],
                "target_domain": manifest.get("domain"),
                "description": manifest.get("description"),
                "version": manifest.get("version"),
                **counts,
                "assessment_question_count": len(
                    self.load_assessment_questions(manifest["knowledge_base_id"])
                ),
                "index_status": index_status,
                "updated_at": None,
            }

        kb_dir = resolve_knowledge_base_dir_by_id(manifest["knowledge_base_id"])
        documents = load_documents(str(kb_dir))
        chunks = chunk_documents(documents)
        updated_at = datetime.fromtimestamp(
            max((path.stat().st_mtime for path in kb_dir.rglob("*") if path.is_file()), default=0),
            tz=timezone.utc,
        )
        return {
            "knowledge_base_id": manifest["knowledge_base_id"],
            "target_domain": manifest.get("domain"),
            "description": manifest.get("description"),
            "version": manifest.get("version"),
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "skill_node_count": len(manifest.get("skill_nodes", [])),
            "diagnostic_question_count": len(self.load_diagnostic_questions(manifest["knowledge_base_id"])),
            "assessment_question_count": len(self.load_assessment_questions(manifest["knowledge_base_id"])),
            "updated_at": updated_at.isoformat(),
        }
