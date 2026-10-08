import pytest
import requests

from app.generation.llm import (LLMError, OllamaProvider, OpenRouterProvider, RateLimitError,
                                create_llm)
from app.generation.prompts import build_answer_messages, clean_rewritten_query


class FakeResponse:
    def __init__(self, status, body=None, headers=None, text=""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def openrouter(monkeypatch, response, **kwargs):
    provider = OpenRouterProvider("google/gemma-4-31b-it:free", api_key="k",
                                  base_url="https://openrouter.ai/api/v1", **kwargs)
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(provider.session, "post", post)
    return provider, sent


def ok(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_openrouter_success_and_payload(monkeypatch):
    provider, sent = openrouter(monkeypatch, ok("Answer [1]"),
                                fallback_models=["nvidia/nemotron-3-super-120b-a12b:free"])
    assert provider.chat([{"role": "user", "content": "q"}]) == "Answer [1]"
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer k"
    assert sent["json"]["models"] == ["google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free"]


def test_openrouter_rate_limit_per_minute(monkeypatch):
    provider, _ = openrouter(monkeypatch, FakeResponse(429, {"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-min."}}))
    with pytest.raises(RateLimitError) as info:
        provider.chat([])
    assert "wait a minute" in info.value.user_message


def test_openrouter_daily_limit_mentions_reset_time(monkeypatch):
    body = {"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day.",
                      "metadata": {"headers": {"X-RateLimit-Reset": "1791417600000"}}}}
    provider, _ = openrouter(monkeypatch, FakeResponse(429, body))
    with pytest.raises(RateLimitError) as info:
        provider.chat([])
    assert "daily request limit" in info.value.user_message
    assert "00:00 UTC" in info.value.user_message


def test_openrouter_error_inside_200_body(monkeypatch):
    provider, _ = openrouter(monkeypatch, FakeResponse(200, {"error": {"code": 429, "message": "upstream rate-limited"}}))
    with pytest.raises(RateLimitError):
        provider.chat([])
    provider, _ = openrouter(monkeypatch, FakeResponse(200, {"error": {"code": 502, "message": "bad gateway"}}))
    with pytest.raises(LLMError, match="502"):
        provider.chat([])


@pytest.mark.parametrize("status,fragment", [(401, "API key"), (402, "negative balance"),
                                             (404, "CHAT_MODEL"), (503, "having trouble")])
def test_openrouter_http_errors_have_friendly_messages(monkeypatch, status, fragment):
    provider, _ = openrouter(monkeypatch, FakeResponse(status, {"error": {"message": "x"}}))
    with pytest.raises(LLMError) as info:
        provider.chat([])
    assert not isinstance(info.value, RateLimitError)
    assert fragment in info.value.user_message


def test_openrouter_missing_key_timeout_and_empty(monkeypatch):
    provider = OpenRouterProvider("m", api_key="", base_url="https://x")
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        provider.chat([])
    provider, _ = openrouter(monkeypatch, requests.Timeout("slow"))
    with pytest.raises(LLMError) as info:
        provider.chat([])
    assert "too long" in info.value.user_message
    provider, _ = openrouter(monkeypatch, ok("<think>hmm</think>  "))
    with pytest.raises(LLMError, match="empty"):
        provider.chat([])


def test_ollama(monkeypatch):
    provider = OllamaProvider("llama3.1:8b", base_url="http://localhost:11434/")
    responses = iter([
        FakeResponse(200, {"message": {"content": "<think>x</think>Local answer"}}),
        FakeResponse(404, {"error": "model not found"}),
        requests.ConnectionError("refused"),
    ])

    def post(url, json, timeout):
        assert url == "http://localhost:11434/api/chat" and json["stream"] is False
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(provider.session, "post", post)
    assert provider.chat([{"role": "user", "content": "q"}]) == "Local answer"
    with pytest.raises(LLMError) as info:
        provider.chat([])
    assert "ollama pull llama3.1:8b" in info.value.user_message
    with pytest.raises(LLMError) as info:
        provider.chat([])
    assert "ollama serve" in info.value.user_message


def test_provider_is_chosen_by_config(app):
    config = dict(app.config)
    assert create_llm(config).describe() == "openrouter:google/gemma-4-31b-it:free"
    config.update(LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen2.5:7b")
    assert create_llm(config).describe() == "ollama:qwen2.5:7b"
    config["LLM_PROVIDER"] = "nope"
    with pytest.raises(ValueError):
        create_llm(config)


def test_prompts():
    chunks = [{"title": "Handbook", "page": 4, "text": "Vacation is 15 days."}]
    messages = build_answer_messages("How much vacation?", [{"role": "user", "content": "hi"},
                                                            {"role": "assistant", "content": "hello"}], chunks)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "[1] Handbook, page 4\nVacation is 15 days." in messages[-1]["content"]
    assert messages[-1]["content"].endswith("Question: How much vacation?")
    assert clean_rewritten_query('Query: "vacation days for new hires"\n', "x") == "vacation days for new hires"
    assert clean_rewritten_query("   ", "fallback") == "fallback"
