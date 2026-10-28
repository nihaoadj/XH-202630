from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from app.core.retrieval import embeddings


@pytest.fixture(autouse=True)
def clear_embedding_cache():
    embeddings._load_embeddings.cache_clear()
    yield
    embeddings._load_embeddings.cache_clear()


def test_concurrent_cold_load_constructs_one_shared_model(monkeypatch):
    calls = []
    model = object()
    start = Barrier(6)
    loading = Event()
    release = Event()
    monkeypatch.setattr(embeddings, "get_settings", lambda: SimpleNamespace(
        embedding_model="test-model", embedding_local_files_only=True,
    ))

    def load(**kwargs):
        calls.append(kwargs)
        loading.set()
        assert release.wait(timeout=5)
        return model

    monkeypatch.setattr(embeddings, "HuggingFaceEmbeddings", load)

    def request():
        start.wait(timeout=5)
        return embeddings.get_embeddings()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(request) for _ in range(6)]
        try:
            assert loading.wait(timeout=5)
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]

    assert all(result is model for result in results)
    assert calls == [{
        "model_name": "test-model",
        "model_kwargs": {"device": "cpu", "local_files_only": True},
        "encode_kwargs": {"normalize_embeddings": True, "batch_size": 4},
    }]


def test_failed_cold_load_can_be_retried(monkeypatch):
    calls = []
    model = object()
    monkeypatch.setattr(embeddings, "get_settings", lambda: SimpleNamespace(
        embedding_model="test-model", embedding_local_files_only=True,
    ))

    def load(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("temporary model initialization failure")
        return model

    monkeypatch.setattr(embeddings, "HuggingFaceEmbeddings", load)
    with pytest.raises(RuntimeError, match="temporary model initialization failure"):
        embeddings.get_embeddings()
    assert embeddings.get_embeddings() is model
    assert embeddings.get_embeddings() is model
    assert len(calls) == 2


def test_model_configuration_change_does_not_reuse_incompatible_instance(monkeypatch):
    settings = SimpleNamespace(embedding_model="first", embedding_local_files_only=True)
    calls = []
    monkeypatch.setattr(embeddings, "get_settings", lambda: settings)

    def load(**kwargs):
        model = object()
        calls.append((kwargs, model))
        return model

    monkeypatch.setattr(embeddings, "HuggingFaceEmbeddings", load)
    first = embeddings.get_embeddings()
    settings.embedding_model = "second"
    second = embeddings.get_embeddings()
    settings.embedding_local_files_only = False
    third = embeddings.get_embeddings()

    assert first is not second and second is not third
    assert embeddings.get_embeddings() is third
    assert len(calls) == 3
