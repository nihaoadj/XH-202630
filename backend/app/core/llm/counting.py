"""Asset-free heuristics; estimates are not exact tokens or billing guarantees."""
from __future__ import annotations
import json
import math
from app.models.reviews.claim_extraction import EstimateParameters
from app.models.shared.llm import StructuredOutputMode


class CharacterEstimator:
    def __init__(self, parameters=None):
        self.parameters = EstimateParameters.model_validate(parameters or {})
        if self.parameters.version != "characters-v1":
            raise ValueError("unknown character estimator version")

    def text_weight(self, text):
        p = self.parameters
        ascii_total=sum(ord(c)<128 for c in text)
        cjk_total=sum(0x3400<=ord(c)<=0x9FFF or 0x20000<=ord(c)<=0x323AF for c in text)
        return ascii_total*p.ascii_weight+cjk_total*p.cjk_weight+(len(text)-ascii_total-cjk_total)*p.unicode_weight

    def count_text(self, text):
        return math.ceil(self.text_weight(text))

    def estimate_prepared(self, messages, schema, mode):
        if any(not isinstance(m.content, str) for m in messages):
            raise ValueError("Claim estimation accepts text messages only")
        p = self.parameters
        weight = sum(self.text_weight(m.content) + p.message_overhead for m in messages)
        if mode == StructuredOutputMode.FUNCTION_CALLING:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            weight += self.text_weight(json.dumps(convert_to_openai_tool(schema), ensure_ascii=False))
        elif mode == StructuredOutputMode.JSON_SCHEMA:
            weight += self.text_weight(json.dumps(schema.model_json_schema(), ensure_ascii=False))
        # TEXT/JSON_MODE already contain their schema. Margin applies once.
        return math.ceil((weight + p.request_overhead) * (1 + p.margin))

    def request_bound(self, messages, schema, options):
        from app.core.llm.gateway import LLMGateway
        mode = options.structured_output_mode
        if mode == StructuredOutputMode.AUTO:
            mode = StructuredOutputMode.FUNCTION_CALLING
        if mode == StructuredOutputMode.TEXT:
            messages = LLMGateway._text_messages(messages, schema)
        elif mode == StructuredOutputMode.JSON_MODE:
            messages = LLMGateway._json_mode_messages(messages, schema)
        return self.estimate_prepared(messages, schema, mode)
