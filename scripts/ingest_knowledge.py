"""将单个知识库以稳定 ID、独立 collection 写入向量数据库。"""
import argparse
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.core.knowledge_base import chunk_documents, load_documents, load_knowledge_base_manifest
from app.core.vector_store import add_documents, reset_vector_store


def main(kb_dir: str | None = None, rebuild: bool = False):
    manifest = load_knowledge_base_manifest(kb_dir)
    knowledge_base_id = manifest["knowledge_base_id"]
    print(f"知识库：{knowledge_base_id}（版本 {manifest['version']}）")
    print("正在加载知识库文档...")
    docs = load_documents(kb_dir)
    print(f"共加载 {len(docs)} 篇原始文档")

    print("正在进行文档切片...")
    chunks = chunk_documents(docs)
    print(f"共生成 {len(chunks)} 个片段")

    if rebuild:
        print("正在清理该知识库的旧向量集合...")
        reset_vector_store(knowledge_base_id)

    print("正在写入向量数据库...")
    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    add_documents(chunks, ids=ids, knowledge_base_id=knowledge_base_id)
    print("向量数据库写入完成（可重复执行，不会新增重复片段）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建指定知识库的 Chroma 向量索引")
    parser.add_argument("--kb-dir", help="知识库目录；默认读取 KNOWLEDGE_BASE_DIR")
    parser.add_argument("--rebuild", action="store_true", help="先删除该知识库旧索引，再全量重建")
    args = parser.parse_args()
    main(kb_dir=args.kb_dir, rebuild=args.rebuild)
