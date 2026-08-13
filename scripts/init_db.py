"""初始化示例学习者画像数据与数据库表结构"""
import json
import os
import sys
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.core.knowledge_base import chunk_documents, list_knowledge_base_dirs, load_documents, load_knowledge_base_manifest
from app.db.database import init_database
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.knowledge.seed_catalog import index_seed_by_knowledge_base, load_learning_catalog_seed
from app.db.database import get_session_factory
from app.db.learner.repository import get_learner_repository
from app.db.questionnaire.repository import create_questionnaire_repository
from app.models.schemas import DiagnosticQuestion, LearnerProfile


def _load_diagnostic_questions(kb_dir: Path) -> list[DiagnosticQuestion]:
    """读取可版本管理的诊断题数据；缺少文件时允许只初始化目录和图谱。"""
    questions_path = kb_dir / "diagnostic_questions.json"
    if not questions_path.exists():
        return []
    with questions_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"诊断题文件必须是 JSON 数组：{questions_path}")
    return [DiagnosticQuestion(**item) for item in data]


def _load_questionnaire_template(path: Path) -> dict | None:
    """读取问卷源文件；缺少文件时允许跳过。"""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"问卷文件必须是 JSON 对象：{path}")
    if not isinstance(data.get("questions"), list):
        raise ValueError(f"问卷文件必须包含 questions 数组：{path}")
    return data


def _relative_source_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _enrich_real_track(track: dict, manifest: dict, documents: list, questions: list[DiagnosticQuestion]) -> dict:
    metadata = {
        **track.get("metadata", {}),
        "available": True,
        "status": "ready",
        "version": manifest.get("version"),
        "document_count": len(documents),
        "skill_node_count": len(manifest.get("skill_nodes", [])),
        "diagnostic_question_count": len(questions),
        "domain": manifest.get("domain"),
        "learner_levels": manifest.get("learner_levels", []),
    }
    return {
        **track,
        "description": track.get("description") or manifest.get("description"),
        "difficulty_levels": track.get("difficulty_levels") or manifest.get("learner_levels", []),
        "metadata": metadata,
    }


def _placeholder_manifest(domain: dict, track: dict) -> dict:
    return {
        "knowledge_base_id": track["knowledge_base_id"],
        "name": track["name"],
        "version": "display-only",
        "domain": domain["name"],
        "description": track.get("description"),
        "learner_levels": [],
        "raw_metadata": {
            "display_only": True,
            "available": False,
            "domain_id": domain["domain_id"],
            "track_id": track["track_id"],
        },
    }


def main():
    settings = get_settings()

    if settings.db_type == "memory":
        print("*** EPHEMERAL WARNING: DB_TYPE=memory，当前进程退出后导入数据将全部丢失。***")

    # 如果使用 SQL 数据库，先创建表结构
    if settings.db_type in ("sqlite", "postgresql"):
        print(f"正在初始化 {settings.db_type} 数据库表结构...")
        init_database()

        catalog = KnowledgeCatalogRepository(get_session_factory())
        questionnaire_repo = create_questionnaire_repository(settings.db_type, get_session_factory())
        common_questionnaire_path = PROJECT_ROOT / "knowledge_base" / "questionnaire_common.json"
        common_questionnaire = _load_questionnaire_template(common_questionnaire_path)
        if common_questionnaire is not None:
            questionnaire_repo.upsert_questionnaire_template(
                common_questionnaire,
                source_path=_relative_source_path(common_questionnaire_path),
            )
            print(
                f"已同步通用问卷：{common_questionnaire['questionnaire_id']}，"
                f"{len(common_questionnaire.get('questions', []))} 道题"
            )

        seed_entries = load_learning_catalog_seed()
        seed_by_kb = index_seed_by_knowledge_base(seed_entries)
        synced_kb_ids = set()
        for kb_dir in list_knowledge_base_dirs():
            manifest = load_knowledge_base_manifest(str(kb_dir))
            documents = load_documents(str(kb_dir))
            chunks = chunk_documents(documents)
            questions = _load_diagnostic_questions(kb_dir)
            domain, track = seed_by_kb.get(
                manifest["knowledge_base_id"],
                (
                    {
                        "domain_id": manifest["knowledge_base_id"],
                        "name": manifest.get("domain") or manifest["name"],
                        "description": manifest.get("description"),
                        "sort_order": 100,
                        "enabled": True,
                        "metadata": {"source": "manifest_fallback"},
                    },
                    {
                        "track_id": manifest["knowledge_base_id"],
                        "domain_id": manifest["knowledge_base_id"],
                        "knowledge_base_id": manifest["knowledge_base_id"],
                        "name": manifest["name"],
                        "description": manifest.get("description"),
                        "target_audience": [],
                        "difficulty_levels": manifest.get("learner_levels", []),
                        "sort_order": 100,
                        "enabled": True,
                        "metadata": {},
                    },
                ),
            )
            track = _enrich_real_track(track, manifest, documents, questions)
            catalog.upsert_knowledge_base(manifest)
            catalog.upsert_learning_catalog(domain, track)
            # 只预写不可变目录；正式 active 状态由 ingest_knowledge.py 在
            # SQL/Chroma/count/smoke 全部对账成功后统一激活。
            catalog.sync_documents(
                documents,
                chunks,
                knowledge_base_id=manifest["knowledge_base_id"],
                activate=False,
            )
            catalog.upsert_skill_nodes(manifest.get("skill_nodes", []), manifest["knowledge_base_id"])
            catalog.upsert_diagnostic_questions(questions)
            questionnaire_path = kb_dir / "questionnaire.json"
            questionnaire = _load_questionnaire_template(questionnaire_path)
            if questionnaire is not None:
                questionnaire_repo.upsert_questionnaire_template(
                    questionnaire,
                    source_path=_relative_source_path(questionnaire_path),
                )
            synced_kb_ids.add(manifest["knowledge_base_id"])
            print(
                f"已同步学习方向：{domain['name']} / {track['name']} -> {manifest['knowledge_base_id']}，"
                f"{len(documents)} 篇文档、{len(chunks)} 个切片、{len(questions)} 道诊断题、"
                f"{len(questionnaire.get('questions', [])) if questionnaire else 0} 道方向问卷题"
            )
        for domain, track in seed_entries:
            if track["knowledge_base_id"] in synced_kb_ids:
                continue
            catalog.upsert_knowledge_base(_placeholder_manifest(domain, track))
            catalog.upsert_learning_catalog(domain, track)
        print("已同步展示用领域与方向目录（未绑定教学资料的方向标记为待建设）")
    else:
        print("DB_TYPE=memory：跳过知识库关系数据同步；演示环境建议使用 DB_TYPE=sqlite。")

    repo = get_learner_repository()
    profile_dir = PROJECT_ROOT / "examples" / "learner_profiles"

    for filename in os.listdir(profile_dir):
        if filename.endswith(".json"):
            path = profile_dir / filename
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = LearnerProfile(**data)
            try:
                repo.save(profile)
                print(f"已加载学习者画像：{profile.learner_id} - {profile.education} - {profile.skill_level}")
            except SQLAlchemyError as exc:
                print(f"跳过示例学习者画像 {profile.learner_id}：当前数据库画像表结构较旧，需要重建或迁移 learner_profiles。{exc.__class__.__name__}")

    print("初始化完成")


if __name__ == "__main__":
    main()
