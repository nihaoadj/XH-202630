"""Run four real-model V2 review-checklist release samples without persistence."""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

from app.agents.resource_workflows.learning_documents.generator_agent import generate_node
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.core.llm.gateway import default_llm_gateway
from app.models.learning_documents.schemas import LearnerProfile
from tests.fakes.evidence import make_evidence
import app.agents.resource_workflows.learning_documents.generator_agent as generator_module


def main() -> None:
    if os.getenv("RUN_LIVE_LLM") != "1":
        raise SystemExit("set RUN_LIVE_LLM=1 to authorize real-model evaluation")
    generator_module.get_settings = lambda: SimpleNamespace(resource_worker_max_concurrency=1)
    batches = [
        ("rag_basics", "检索增强生成将检索到的相关文档作为上下文，再由生成模型据此回答；回答应受给定上下文约束。"),
        ("document_parsing", "文档解析的目标是从不同格式的文档中提取可用文本和结构信息；解析质量会影响后续检索。"),
        ("chunking", "文本分块会把长文档切成片段；chunk_size 与 chunk_overlap 会影响片段上下文和检索粒度。"),
        ("embedding", "Embedding 将文本表示为向量；语义相近的文本在向量空间中通常更接近，可用于相似度检索。"),
    ]
    gateway = default_llm_gateway()
    results = []
    for index, (node_id, excerpt) in enumerate(batches, start=1):
        evidence_id = f"live-review-evidence-{index}"
        evidence = make_evidence(evidence_id=evidence_id, chunk_id=f"live-review-chunk-{index}", excerpt=excerpt, query=f"live {node_id}")
        state = {
            "schema_version": "1.0", "run_id": f"live-review-run-{index}", "batch_id": f"live-review-batch-{index}",
            "learner": LearnerProfile(learner_id=f"live-review-learner-{index}", learner_type="live_eval", education="本科", major="计算机", skill_level="中级", learning_goal="主动回忆训练"),
            "topic": "RAG 工程训练", "resource_types": ["复习清单"], "target_skill_nodes": [node_id],
            "retrieved_evidence": [evidence], "node_evidence_map": {node_id: [evidence_id]},
            "learning_plan": {"learning_path": [{"topic": node_id, "order": 1}]}, "generation_attempt": 1,
            "trace": [], "include_claim_check": False, "include_review": True, "generation_mode": "standard", "max_iterations": 0,
        }
        started = time.perf_counter()
        try:
            generated = generate_node(state, llm_gateway=gateway)
            reviewed = review_node({**state, **generated}, llm_gateway=gateway)
            resource = reviewed.get("generated_resources", [None])[0]
            results.append({"batch": index, "node_id": node_id, "review_decision": reviewed.get("review_result", {}).get("decision"), "review_status": getattr(resource, "review_status", None), "publication_status": getattr(resource, "publication_status", None), "generation_errors": [item.get("code") for item in generated.get("errors", [])], "review_issue_count": len(reviewed.get("review_result", {}).get("issues", [])), "elapsed_seconds": round(time.perf_counter() - started, 2)})
        except Exception as exc:  # report a batch failure but continue the live sample.
            results.append({"batch": index, "node_id": node_id, "exception": type(exc).__name__, "elapsed_seconds": round(time.perf_counter() - started, 2)})
    print(json.dumps({"model": gateway.transport.model_name, "total": len(results), "published": sum(item.get("publication_status") == "published" for item in results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
