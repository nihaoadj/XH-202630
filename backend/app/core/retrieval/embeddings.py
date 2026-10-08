from langchain_community.embeddings import HuggingFaceEmbeddings
from app.config import get_settings


def get_embeddings():
    """加载中文语义向量模型"""
    settings = get_settings()
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={
            "device": "cpu",
            "local_files_only": settings.embedding_local_files_only,
        },
        encode_kwargs={"normalize_embeddings": True},
    )
