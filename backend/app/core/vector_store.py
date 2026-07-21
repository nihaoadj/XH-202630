import os
from langchain_community.vectorstores import Chroma
from app.config import get_settings, resolve_backend_path
from app.core.embeddings import get_embeddings


def get_vector_store():
    """获取 ChromaDB 向量存储实例"""
    settings = get_settings()
    vector_store_dir = resolve_backend_path(settings.vector_store_dir)
    os.makedirs(vector_store_dir, exist_ok=True)
    embeddings = get_embeddings()
    return Chroma(
        persist_directory=str(vector_store_dir),
        embedding_function=embeddings,
    )


def add_documents(documents, ids=None):
    """向向量库中添加文档"""
    store = get_vector_store()
    store.add_documents(documents, ids=ids)


def similarity_search(query: str, top_k: int = 5):
    """语义检索"""
    store = get_vector_store()
    return store.similarity_search_with_score(query, k=top_k)
