"""Profile local hybrid retrieval without invoking an LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.core.vector_store import ChromaVectorSearchBackend  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    if args.repeat <= 0 or args.top_k <= 0:
        parser.error("--repeat and --top-k must be positive")

    backend = ChromaVectorSearchBackend(get_settings())
    runs = []
    for run_index in range(args.repeat):
        started = perf_counter()
        candidates = backend.search_many(
            queries=args.query,
            top_k=args.top_k,
            knowledge_base_id=args.knowledge_base_id,
        )
        runs.append(
            {
                "run": "cold" if run_index == 0 else f"warm_{run_index}",
                "total_retrieval_ms": round((perf_counter() - started) * 1000, 3),
                "query_count": len(args.query),
                "candidate_count": len(candidates),
                **backend.last_profile,
            }
        )
    print(json.dumps({"knowledge_base_id": args.knowledge_base_id, "runs": runs}, indent=2))


if __name__ == "__main__":
    main()
