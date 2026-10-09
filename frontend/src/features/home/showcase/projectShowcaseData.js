// Public showcase projection of knowledge_base/rag_engineering_training/metadata.json (v2.3.0).
// Browser acceptance compares names, tiers and prerequisites with the authoritative seed.
export const projectSkillNodes = [
  {
    "id": "rag_basics",
    "name": "RAG 基础概念",
    "tier": 1,
    "prerequisites": []
  },
  {
    "id": "document_parsing",
    "name": "文档解析",
    "tier": 1,
    "prerequisites": [
      "rag_basics"
    ]
  },
  {
    "id": "chunking",
    "name": "Chunk 切分",
    "tier": 2,
    "prerequisites": [
      "document_parsing"
    ]
  },
  {
    "id": "embedding",
    "name": "Embedding",
    "tier": 1,
    "prerequisites": [
      "rag_basics"
    ]
  },
  {
    "id": "vector_store",
    "name": "向量数据库",
    "tier": 2,
    "prerequisites": [
      "embedding"
    ]
  },
  {
    "id": "similarity_retrieval",
    "name": "相似度检索",
    "tier": 2,
    "prerequisites": [
      "vector_store",
      "chunking"
    ]
  },
  {
    "id": "hybrid_retrieval",
    "name": "混合检索",
    "tier": 3,
    "prerequisites": [
      "similarity_retrieval"
    ]
  },
  {
    "id": "rerank",
    "name": "Rerank",
    "tier": 3,
    "prerequisites": [
      "similarity_retrieval"
    ]
  },
  {
    "id": "prompt_assembly",
    "name": "Prompt 组装",
    "tier": 2,
    "prerequisites": [
      "similarity_retrieval"
    ]
  },
  {
    "id": "citation",
    "name": "引用溯源",
    "tier": 2,
    "prerequisites": [
      "prompt_assembly"
    ]
  },
  {
    "id": "hallucination_control",
    "name": "幻觉控制",
    "tier": 3,
    "prerequisites": [
      "citation"
    ]
  },
  {
    "id": "rag_evaluation",
    "name": "RAG 评测",
    "tier": 3,
    "prerequisites": [
      "hallucination_control"
    ]
  },
  {
    "id": "rag_tuning",
    "name": "RAG 调优",
    "tier": 3,
    "prerequisites": [
      "rag_evaluation",
      "hybrid_retrieval",
      "rerank"
    ]
  }
]
