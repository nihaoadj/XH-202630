"""初始化示例学习者画像数据与数据库表结构"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.db.database import init_database
from app.db.learner.repository import get_learner_repository
from app.models.schemas import LearnerProfile


def main():
    settings = get_settings()

    # 如果使用 SQL 数据库，先创建表结构
    if settings.db_type in ("sqlite", "postgresql"):
        print(f"正在初始化 {settings.db_type} 数据库表结构...")
        init_database()

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
