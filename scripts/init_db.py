"""初始化示例学习者画像数据与数据库表结构"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.core.knowledge_base import chunk_documents, load_documents, load_knowledge_base_manifest, resolve_knowledge_base_dir
from app.db.database import init_database
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.database import get_session_factory
from app.db.learner.repository import get_learner_repository
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


def main():
    settings = get_settings()

    # 如果使用 SQL 数据库，先创建表结构
    if settings.db_type in ("sqlite", "postgresql"):
        print(f"正在初始化 {settings.db_type} 数据库表结构...")
        init_database()

        manifest = load_knowledge_base_manifest()
        documents = load_documents()
        chunks = chunk_documents(documents)
        catalog = KnowledgeCatalogRepository(get_session_factory())
        catalog.upsert_knowledge_base(manifest)
        catalog.sync_documents(documents, chunks)
        catalog.upsert_skill_nodes(manifest.get("skill_nodes", []), manifest["knowledge_base_id"])
        questions = _load_diagnostic_questions(resolve_knowledge_base_dir())
        catalog.upsert_diagnostic_questions(questions)
        print(
            f"已同步知识库目录：{manifest['knowledge_base_id']}，"
            f"{len(documents)} 篇文档、{len(chunks)} 个切片、{len(questions)} 道诊断题"
        )
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
            repo.save(profile)
            print(f"已加载学习者画像：{profile.learner_id} - {profile.education} - {profile.skill_level}")

    print("初始化完成")


if __name__ == "__main__":
    main()
