"""Offline estimate preflight; no assets, model request or configuration writes."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.core.llm.gateway import default_llm_gateway
from app.agents.resource_workflows.learning_documents.claim_extraction.profiles import load_counter
from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        settings = Settings()
        gateway = default_llm_gateway()
        counter = load_counter(settings, gateway)
        policy = freeze_policy(settings, gateway, counter)
        print(json.dumps({"status":"PASS_OFFLINE_PREFLIGHT", "estimator":policy.estimator_version,
                          "model":policy.model_name, "thinking":policy.thinking_mode,
                          "context_limit":policy.context_limit, "strategy":policy.strategy,
                          "configured_strategy":settings.claim_extraction_strategy,
                          "structured_output_mode":policy.extractor_options.structured_output_mode.value,
                          "output_tokens":policy.output_tokens, "max_calls":policy.max_calls,
                          "max_attempts":policy.max_attempts, "max_tokens":policy.max_tokens,
                          "parameters":policy.estimator_parameters.model_dump(), "live_executed":False}))
        return 0
    except (ValueError, OSError, RuntimeError):
        print(json.dumps({"status":"PREFLIGHT_BLOCKED", "reason":"estimate configuration invalid", "live_executed":False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
