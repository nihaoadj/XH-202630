"""知识库与关系目录的核心回归测试。"""
import inspect
import json
from pathlib import Path

from langchain.schema import Document
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import retriever
from app.config import Settings
from app.core import vector_store
from app.core.knowledge_base import (
    chunk_documents,
    load_documents,
    load_knowledge_base_manifest,
)
from app.core.vector_store import _restore_retrieved_metadata, _to_chroma_document
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.diagnosis.sql_repository import SQLDiagnosisRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.db.learner.sql_repository import SQLLearnerRepository
from app.db.models import (
    AgentRunORM,
    AgentStepORM,
    Base,
    DiagnosticQuestionORM,
    DiagnosticAnswerORM,
    GeneratedResourceORM,
    KnowledgeChunkORM,
    KnowledgeDocumentORM,
    KnowledgeStateORM,
    LearnerProfileORM,
    ResourceClaimORM,
    ResourceReviewORM,
)
from app.models.schemas import (
    DiagnosticAnswerSubmission,
    DiagnosticQuestion,
    DiagnosticSubmitRequest,
    LearnerProfile,
)
from app.services.diagnosis_service import DiagnosisService
from app.services.knowledge_service import KnowledgeService


def test_default_chunking_configuration_uses_100_character_overlap():
    parameters = inspect.signature(chunk_documents).parameters

    assert parameters["chunk_size"].default == 500
    assert parameters["chunk_overlap"].default == 100


def test_chunks_have_stable_complete_provenance():
    documents = load_documents()
    first = chunk_documents(documents)
    second = chunk_documents(documents)

    assert first
    assert [chunk.metadata["chunk_id"] for chunk in first] == [
        chunk.metadata["chunk_id"] for chunk in second
    ]
    for chunk in first:
        assert chunk.metadata["knowledge_base_id"] == "rag_engineering_training"
        assert chunk.metadata["document_id"]
        assert chunk.metadata["source_path"]
        assert chunk.metadata["content_hash"]
        assert isinstance(chunk.metadata["chunk_index"], int)


def test_chroma_metadata_serialization_preserves_list_provenance():
    chunk = chunk_documents(load_documents())[0]
    stored = _to_chroma_document(chunk)

    assert all(isinstance(value, (str, int, float, bool)) for value in stored.metadata.values())
    restored = _restore_retrieved_metadata(stored)
    assert restored.metadata["knowledge_points"] == chunk.metadata["knowledge_points"]
    assert restored.metadata["learner_levels"] == chunk.metadata["learner_levels"]
    assert restored.metadata["source_urls"] == chunk.metadata["source_urls"]


def test_bm25_search_prioritizes_exact_technical_identifier():
    exact = Document(
        page_content="系统出现错误码 ERR-42 时，需要检查 collection 的向量维度。",
        metadata={"chunk_id": "exact"},
    )
    semantic_only = Document(
        page_content="向量数据库发生异常时可以检查索引配置。",
        metadata={"chunk_id": "semantic"},
    )

    results = vector_store._bm25_search("ERR-42 如何处理", [semantic_only, exact], top_k=2)

    assert results
    assert results[0][0].metadata["chunk_id"] == "exact"
    assert results[0][1] > 0


def test_hybrid_search_fuses_vector_and_bm25_with_rrf(monkeypatch):
    semantic = Document(
        page_content="向量数据库异常排查方法。",
        metadata={"chunk_id": "semantic", "knowledge_base_id": "kb-hybrid"},
    )
    exact = Document(
        page_content="错误码 ERR-42 表示 collection 向量维度不一致。",
        metadata={"chunk_id": "exact", "knowledge_base_id": "kb-hybrid"},
    )

    class FakeStore:
        def similarity_search_with_score(self, query, k):
            return [(semantic, 0.1), (exact, 0.2)]

        def get(self, include):
            return {
                "ids": ["semantic", "exact"],
                "documents": [semantic.page_content, exact.page_content],
                "metadatas": [semantic.metadata, exact.metadata],
            }

    vector_store._LEXICAL_DOCUMENT_CACHE.clear()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda knowledge_base_id: FakeStore())

    results = vector_store.hybrid_search("ERR-42", top_k=2, knowledge_base_id="kb-hybrid")

    assert [document.metadata["chunk_id"] for document, _ in results] == ["exact", "semantic"]
    exact_result, exact_score = results[0]
    assert exact_result.metadata["retrieval_method"] == "hybrid_rrf"
    assert exact_result.metadata["retrieval_channels"] == ["vector", "bm25"]
    assert exact_result.metadata["vector_rank"] == 2
    assert exact_result.metadata["lexical_rank"] == 1
    assert 0 < results[1][1] < exact_score <= 1


def test_collection_name_is_kb_scoped_and_uses_compatible_prefix():
    settings = Settings(
        _env_file=None,
        chroma_collection_prefix="training prefix",
    )

    first = vector_store._collection_name("kb_one", settings)
    second = vector_store._collection_name("kb_two", settings)

    assert first.startswith("training_prefix_")
    assert second.startswith("training_prefix_")
    assert first != second


def test_create_write_query_and_delete_use_one_collection_resolver(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        vector_store_dir=str(tmp_path / "chroma"),
        chroma_collection_prefix="kbtest",
    )
    created_names = []

    class FakeStore:
        def __init__(self, collection_name, **kwargs):
            self.collection_name = collection_name
            created_names.append(collection_name)

        def add_documents(self, documents, ids):
            return ids

        def similarity_search_with_score(self, query, k):
            return []

        def delete_collection(self):
            return None

    monkeypatch.setattr(vector_store, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store, "get_embeddings", lambda: object())
    monkeypatch.setattr(vector_store, "Chroma", FakeStore)
    chunk = Document(
        page_content="测试片段",
        metadata={"knowledge_base_id": "kb_one", "chunk_id": "chunk_one"},
    )

    vector_store.get_vector_store("kb_one")
    vector_store.add_documents([chunk], knowledge_base_id="kb_one")
    vector_store.similarity_search("测试", knowledge_base_id="kb_one")
    vector_store.reset_vector_store("kb_one")

    assert created_names == [vector_store._collection_name("kb_one", settings)] * 4


def test_catalog_sync_is_idempotent_and_preserves_graph(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    Base.metadata.create_all(engine)
    repository = KnowledgeCatalogRepository(sessionmaker(bind=engine))
    manifest = load_knowledge_base_manifest()
    documents = load_documents()
    chunks = chunk_documents(documents)

    repository.upsert_knowledge_base(manifest)
    repository.sync_documents(documents, chunks)
    repository.upsert_skill_nodes(manifest["skill_nodes"], manifest["knowledge_base_id"])
    questions_path = Path(__file__).resolve().parents[2] / "knowledge_base" / "rag_engineering_training" / "diagnostic_questions.json"
    questions = [DiagnosticQuestion(**item) for item in json.loads(questions_path.read_text(encoding="utf-8"))]
    question_counts = {}
    dimensions = set()
    for question in questions:
        question_counts[question.skill_node_id] = question_counts.get(question.skill_node_id, 0) + 1
        dimensions.add(question.metadata.get("diagnostic_dimension"))
    assert set(question_counts) == {node["node_id"] for node in manifest["skill_nodes"]}
    assert set(question_counts.values()) == {3}
    assert dimensions == {"concept", "scenario", "misconception"}
    repository.upsert_diagnostic_questions(questions)
    # 重复同步不应产生文档、切片或节点的重复行。
    repository.sync_documents(documents, chunks)
    repository.upsert_skill_nodes(manifest["skill_nodes"], manifest["knowledge_base_id"])

    with sessionmaker(bind=engine)() as db:
        assert db.query(KnowledgeDocumentORM).count() == len(documents)
        assert db.query(KnowledgeChunkORM).count() == len(chunks)
        assert db.query(DiagnosticQuestionORM).count() == 39
    nodes = repository.list_skill_nodes(manifest["knowledge_base_id"])
    assert len(nodes) == 13
    assert next(node for node in nodes if node.name == "Chunk 切分").prerequisites == ["文档解析"]


def test_catalog_sync_prunes_removed_documents_and_old_chunks(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog_prune.db'}")
    Base.metadata.create_all(engine)
    repository = KnowledgeCatalogRepository(sessionmaker(bind=engine))
    manifest = load_knowledge_base_manifest()
    documents = load_documents()
    chunks = chunk_documents(documents)
    repository.upsert_knowledge_base(manifest)
    repository.sync_documents(documents, chunks)

    retained_documents = documents[:-1]
    retained_document_ids = {document.metadata["document_id"] for document in retained_documents}
    retained_chunks = [chunk for chunk in chunks if chunk.metadata["document_id"] in retained_document_ids]
    repository.sync_documents(retained_documents, retained_chunks)

    with sessionmaker(bind=engine)() as db:
        assert db.query(KnowledgeDocumentORM).count() == len(retained_documents)
        assert db.query(KnowledgeChunkORM).count() == len(retained_chunks)


def test_retriever_passes_knowledge_base_filter_and_returns_hybrid_trace(monkeypatch):
    documents = load_documents()
    chunk = chunk_documents(documents)[0]
    calls = []

    def fake_hybrid_search(query, top_k, knowledge_base_id):
        calls.append((query, top_k, knowledge_base_id))
        chunk.metadata.update(
            {
                "retrieval_method": "hybrid_rrf",
                "retrieval_channels": ["vector", "bm25"],
                "vector_rank": 2,
                "vector_score": 0.12,
                "lexical_rank": 1,
                "lexical_score": 3.4,
            }
        )
        return [(chunk, 0.12)]

    monkeypatch.setattr(retriever, "hybrid_search", fake_hybrid_search)
    def fake_rerank(query, candidates, top_k):
        document, score = candidates[0]
        document.metadata.update(
            {
                "retrieval_method": "hybrid_rrf_cross_encoder",
                "rerank_status": "available",
                "rerank_rank": 1,
                "rerank_score": 0.95,
            }
        )
        return [(document, 0.95)]

    monkeypatch.setattr(retriever, "rerank_documents", fake_rerank)
    learner = LearnerProfile(
        learner_id="test_retriever",
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="测试检索",
    )
    result = retriever.retrieve_node(
        {
            "learner": learner,
            "topic": "RAG 基础概念",
            "knowledge_base_id": "rag_engineering_training",
            "diagnosis": {"weak_points": ["Embedding"]},
            "retrieved_chunks": [],
            "learning_plan": {},
            "generated_resources": [],
            "review_result": {},
            "final_decision": "",
            "resource_types": ["讲义"],
            "trace": [],
            "iteration": 0,
        }
    )

    assert calls and all(call[2] == "rag_engineering_training" for call in calls)
    retrieved = result["retrieved_chunks"][0]
    assert retrieved["document_id"] == chunk.metadata["document_id"]
    assert retrieved["chunk_id"] == chunk.metadata["chunk_id"]
    assert retrieved["retrieval_method"] == "hybrid_rrf_cross_encoder"
    assert retrieved["retrieval_channels"] == ["vector", "bm25"]
    assert retrieved["lexical_rank"] == 1
    assert retrieved["rerank_status"] == "available"
    assert retrieved["rerank_score"] == 0.95


def test_audit_repository_persists_agent_steps_and_claim_evidence(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            LearnerProfileORM(
                learner_id="audit_learner",
                learner_type="测试",
                education="本科",
                major="计算机",
                learning_goal="验证审计持久化",
            )
        )
        db.add(
            GeneratedResourceORM(
                resource_id="audit_resource",
                learner_id="audit_learner",
                topic="RAG",
                resource_type="讲义",
                difficulty="初级",
                storage_type="text",
            )
        )
        db.commit()

    repository = SQLAuditRepository(factory)
    run_id = repository.save_run(
        learner_id="audit_learner",
        knowledge_base_id=None,
        topic="RAG",
        trace=[{"agent_name": "retriever", "action": "知识库检索", "evidence_refs": ["chunk_001"]}],
        input_payload={"topic": "RAG"},
        output_payload={"final_decision": "通过"},
        status="completed",
    )
    review_id = repository.save_review(
        "audit_resource",
        {
            "passed": True,
            "claims": [
                {
                    "claim_id": "claim_001",
                    "text": "Embedding 将文本映射为向量。",
                    "supported": True,
                    "evidence_refs": [{"doc_id": "doc_001", "chunk_id": "chunk_001"}],
                }
            ],
        },
        run_id,
    )

    with factory() as db:
        assert db.get(AgentRunORM, run_id) is not None
        assert db.query(AgentStepORM).filter_by(run_id=run_id).count() == 1
        assert db.get(ResourceReviewORM, review_id).claim_supported == 1
        assert db.query(ResourceClaimORM).filter_by(review_id=review_id).one().supported is True

    review = repository.get_review_by_resource("audit_resource")
    assert review is not None
    assert review.review_id == review_id
    assert review.claims[0].evidence_refs[0].chunk_id == "chunk_001"


def test_diagnosis_submission_scores_on_server_and_updates_profile():
    learner_repo = MemoryLearnerRepository()
    learner = LearnerProfile(
        learner_id="diagnosis_learner",
        learner_type="测试",
        education="本科",
        major="计算机",
        learning_goal="验证诊断闭环",
    )
    learner_repo.save(learner)
    knowledge_service = KnowledgeService()
    questions = knowledge_service.select_diagnostic_questions(
        skill_node_ids=["rag_basics"],
    )

    # 对外题目不应携带标准答案或解析；真实判分只发生在服务端。
    public_question = knowledge_service.public_question(questions[0])
    assert "answer" not in public_question
    assert "explanation" not in public_question

    result = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
    ).submit(
        DiagnosticSubmitRequest(
            learner_id=learner.learner_id,
            answers=[
                DiagnosticAnswerSubmission(question_id=questions[0].question_id, answer=questions[0].answer),
                DiagnosticAnswerSubmission(question_id=questions[1].question_id, answer="错误答案"),
                DiagnosticAnswerSubmission(question_id=questions[2].question_id, answer=questions[2].answer),
            ],
        )
    )

    assert result.knowledge_states["RAG 基础概念"].score == 2 / 3
    assert result.knowledge_states["RAG 基础概念"].status == "learning"
    updated = learner_repo.get(learner.learner_id)
    assert updated is not None
    assert updated.theory_scores["RAG 基础概念"] == round(200 / 3, 1)


def test_diagnosis_submission_persists_answers_and_states_in_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnosis.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    learner_repo = SQLLearnerRepository(factory)
    learner_repo.save(
        LearnerProfile(
            learner_id="sql_diagnosis_learner",
            learner_type="测试",
            education="本科",
            major="计算机",
            learning_goal="验证 SQLite 诊断持久化",
        )
    )
    knowledge_service = KnowledgeService()
    questions = knowledge_service.select_diagnostic_questions(limit=3)
    service = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=SQLDiagnosisRepository(factory),
    )
    service.submit(
        DiagnosticSubmitRequest(
            learner_id="sql_diagnosis_learner",
            answers=[
                DiagnosticAnswerSubmission(question_id=question.question_id, answer=question.answer)
                for question in questions
            ],
        )
    )

    with factory() as db:
        assert db.query(DiagnosticAnswerORM).count() == 3
        assert db.query(KnowledgeStateORM).count() == 3
