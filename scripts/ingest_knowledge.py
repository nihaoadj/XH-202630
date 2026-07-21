"""将知识库文档切片并写入向量数据库"""
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

from app.core.knowledge_base import load_documents, chunk_documents
from app.core.vector_store import add_documents


def main():
    print("正在加载知识库文档...")
    docs = load_documents()
    print(f"共加载 {len(docs)} 篇原始文档")

    print("正在进行文档切片...")
    chunks = chunk_documents(docs)
    print(f"共生成 {len(chunks)} 个片段")

    print("正在写入向量数据库...")
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    add_documents(chunks, ids=ids)
    print("向量数据库写入完成")


if __name__ == "__main__":
    main()
