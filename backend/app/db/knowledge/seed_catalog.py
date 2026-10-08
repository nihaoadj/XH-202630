"""学习领域与方向的初始化种子读取工具。

运行时接口不导入本模块；它只服务于数据库初始化脚本。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SEED_PATH = PROJECT_ROOT / "knowledge_base" / "learning_catalog_seed.json"


def load_learning_catalog_seed(path: Path = SEED_PATH) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """读取领域/方向 seed，展开为 repository 可 upsert 的结构。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for domain in data.get("domains", []):
        domain_payload = {
            "domain_id": domain["domain_id"],
            "name": domain["name"],
            "description": domain.get("description"),
            "sort_order": domain.get("sort_order", 100),
            "enabled": domain.get("enabled", True),
            "metadata": domain.get("metadata", {}),
        }
        for track in domain.get("tracks", []):
            available = track.get("available", False)
            track_payload = {
                "track_id": track["track_id"],
                "domain_id": domain["domain_id"],
                "knowledge_base_id": track.get("knowledge_base_id", track["track_id"]),
                "name": track["name"],
                "description": track.get("description"),
                "target_audience": track.get("target_audience", []),
                "difficulty_levels": track.get("difficulty_levels", []),
                "sort_order": track.get("sort_order", 100),
                "enabled": track.get("enabled", True),
                "metadata": {
                    **track.get("metadata", {}),
                    "available": available,
                    "status": "ready" if available else "coming_soon",
                    "version": track.get("version"),
                    "document_count": track.get("document_count", 0),
                    "skill_node_count": track.get("skill_node_count", 0),
                    "learner_levels": track.get("learner_levels", []),
                },
            }
            entries.append((domain_payload, track_payload))
    return entries


def index_seed_by_knowledge_base(
    entries: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    return {track["knowledge_base_id"]: (domain, track) for domain, track in entries}
