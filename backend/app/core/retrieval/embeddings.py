from functools import lru_cache
from threading import Lock

from langchain_community.embeddings import HuggingFaceEmbeddings
from app.config import get_settings


_EMBEDDINGS_LOAD_LOCK = Lock()


@lru_cache(maxsize=1)
def _load_embeddings(model_name: str, local_files_only: bool, batch_size: int = 4):
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={
            "device": "cpu",
            "local_files_only": local_files_only,
        },
        encode_kwargs={"normalize_embeddings": True, "batch_size": batch_size},
    )


def get_embeddings():
    """复用进程内模型，避免并发生成重复初始化 Transformer 权重。"""
    settings = get_settings()
    # lru_cache 允许多个并发 miss 同时运行工厂，因此锁必须包住缓存调用。
    # 初始化失败不会进入缓存，后续请求仍可重试；编码推理不持有此锁。
    with _EMBEDDINGS_LOAD_LOCK:
        return _load_embeddings(settings.embedding_model, settings.embedding_local_files_only,
                                getattr(settings, "embedding_batch_size", 4))
