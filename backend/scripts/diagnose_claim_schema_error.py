"""Reproduce the Claim extraction schema rejection and print the exact validator error.

Read-only diagnostic: it replays the production prompt against the stored
resource of one finished run and prints which pydantic rule the first raw
response violated.  It never writes to the database.
"""

from __future__ import annotations

import json
import sqlite3

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    extractor_prompt,
)
from app.core.llm.gateway import _invoke_transport_with_hard_timeout, default_llm_gateway
from app.core.llm.structured_output import parse_structured_output
from app.models.reviews.claims import ClaimExtractionLLMOutput


RUN = "df9bba8c-6fb0-4a1d-9b46-5819dd247b24"


def build_payload() -> dict:
    con = sqlite3.connect("data/domain_knowledge_m3.db")
    con.row_factory = sqlite3.Row
    res = dict(
        con.execute(
            "select resource_id, version, resource_type, content_text "
            "from generated_resources where run_id=? limit 1",
            (RUN,),
        ).fetchone()
    )
    evidence = [
        dict(r)
        for r in con.execute(
            "select evidence_id, excerpt from retrieval_evidence_snapshots "
            "where run_id=? order by rank",
            (RUN,),
        )
    ]
    return {
        "allowed_evidence": [
            {"evidence_id": item["evidence_id"], "excerpt": item["excerpt"]}
            for item in evidence
        ],
        "allowed_knowledge_point_ids": ["hallucination_control"],
        "resources": [
            {
                "resource_id": res["resource_id"],
                "resource_version": res["version"],
                "resource_type": res["resource_type"],
                "content_text": res["content_text"],
            }
        ],
    }


def main() -> None:
    gateway = default_llm_gateway()
    options = gateway.options_for("claim_extractor", temperature=0.0)
    messages = [
        SystemMessage(content=extractor_prompt(10)),
        HumanMessage(content=json.dumps(build_payload(), ensure_ascii=False)),
    ]
    prepared = gateway._json_mode_messages(messages, ClaimExtractionLLMOutput)

    for sample in range(1, 4):
        raw = _invoke_transport_with_hard_timeout(
            gateway.transport,
            timeout_seconds=180,
            messages=prepared,
            output_schema=ClaimExtractionLLMOutput,
            mode=options.structured_output_mode,
            temperature=0.0,
            max_output_tokens=options.max_output_tokens,
        )
        content = raw.content
        print(f"\n===== sample {sample} =====")
        print("finish", raw.finish_reason, "chars", len(content), "usage", raw.usage)
        with open(f"logs/claim-schema-raw-{sample}.txt", "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            parse_structured_output(
                content, ClaimExtractionLLMOutput, finish_reason=raw.finish_reason
            )
            print("VALID: this sample passed the strict schema")
            continue
        except Exception as exc:  # noqa: BLE001 - diagnostic
            print("REJECTED", type(exc).__name__, exc)

        try:
            value = json.loads(content)
            ClaimExtractionLLMOutput.model_validate(value)
        except ValidationError as exc:
            for item in exc.errors(include_url=False, include_context=False):
                print(
                    "  loc=",
                    ".".join(str(part) for part in item.get("loc", ())),
                    "| type=",
                    item.get("type"),
                    "| msg=",
                    item.get("msg"),
                    "| input=",
                    repr(item.get("input"))[:120],
                )
        except json.JSONDecodeError as exc:
            print("  not plain JSON:", exc)


if __name__ == "__main__":
    main()
