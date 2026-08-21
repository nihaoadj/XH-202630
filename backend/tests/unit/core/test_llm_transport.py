from langchain_core.messages import AIMessage, HumanMessage

from app.config import Settings
from app.core import llm as llm_module
from app.core.llm import LangChainChatTransport, create_chat_model
from app.models.llm import StructuredOutputMode


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-transport-key",
        llm_model="test-model",
    )


def test_chat_model_disables_sdk_retry_and_applies_call_budget(monkeypatch):
    captured = {}

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm_module, "ChatOpenAI", fake_chat_openai)
    create_chat_model(
        settings=_settings(),
        timeout_seconds=7.5,
        max_output_tokens=1234,
        temperature=0.2,
    )

    assert captured["timeout"] == 7.5
    assert captured["max_retries"] == 0
    assert captured["max_tokens"] == 1234
    assert captured["temperature"] == 0.2
    assert captured["http_client"].trust_env is False


def test_chat_model_uses_only_the_explicitly_configured_proxy(monkeypatch):
    captured = {}

    monkeypatch.setattr(llm_module, "ChatOpenAI", lambda **kwargs: captured.update(kwargs))
    create_chat_model(settings=_settings().model_copy(update={
        "llm_proxy_url": "http://127.0.0.1:8123",
    }))

    transports = list(captured["http_client"]._mounts.values())
    assert transports
    assert type(transports[0]._pool).__name__ == "HTTPProxy"


def test_transport_preserves_normalized_tool_args_for_canonical_parser():
    class Runnable:
        def invoke(self, messages):
            return {
                "raw": AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "Payload",
                        "args": {"value": "ok"},
                        "id": "tool-call",
                        "type": "tool_call",
                    }],
                ),
                "parsed": None,
                "parsing_error": ValueError("must-not-leak"),
            }

    class Client:
        def with_structured_output(self, output_schema, method, include_raw):
            assert method == "function_calling"
            assert include_raw is True
            return Runnable()

    transport = LangChainChatTransport(
        _settings(),
        client_factory=lambda **kwargs: Client(),
    )
    response = transport.invoke(
        messages=[HumanMessage(content="test")],
        output_schema=dict,
        mode=StructuredOutputMode.FUNCTION_CALLING,
        timeout_seconds=5,
        temperature=0,
        max_output_tokens=100,
    )

    assert response.content == {"value": "ok"}
    assert "must-not-leak" not in str(response.response_metadata)
