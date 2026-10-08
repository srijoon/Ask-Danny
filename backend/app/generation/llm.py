import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests
from flask import current_app

log = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    default_user_message = "The AI model couldn't answer right now. Please try again in a moment."

    def __init__(self, message, user_message=None):
        super().__init__(message)
        self.user_message = user_message or self.default_user_message


class RateLimitError(LLMError):
    default_user_message = (
        "The free AI model is busy right now (rate limit reached). "
        "Please wait a minute and try again."
    )


class LLMProvider(ABC):
    name = "base"

    def __init__(self, model, *, temperature=0.2, max_tokens=1024, timeout=120):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.session = requests.Session()

    @abstractmethod
    def _complete(self, messages, temperature, max_tokens):
        ...

    def chat(self, messages, *, temperature=None, max_tokens=None):
        text = self._complete(
            messages,
            self.temperature if temperature is None else temperature,
            self.max_tokens if max_tokens is None else max_tokens,
        )
        text = _THINK_RE.sub("", text or "").strip()
        if not text:
            raise LLMError(f"{self.describe()} returned an empty reply",
                           "The AI model returned an empty answer. Please try again.")
        return text

    def describe(self):
        return f"{self.name}:{self.model}"


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def __init__(self, model, *, api_key, base_url, fallback_models=(), **kwargs):
        super().__init__(model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.fallback_models = list(fallback_models)

    def _complete(self, messages, temperature, max_tokens):
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY is not set",
                           "The AI model isn't configured yet (missing OpenRouter API key).")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.fallback_models:
            payload["models"] = [self.model, *self.fallback_models]
        try:
            resp = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}", "X-Title": "Ask-Danny"},
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise LLMError(f"OpenRouter timed out: {exc}",
                           "The AI model took too long to respond. Please try again.") from exc
        except requests.RequestException as exc:
            raise LLMError(f"OpenRouter request failed: {exc}",
                           "Couldn't reach the AI service. Please try again shortly.") from exc

        try:
            data = resp.json()
        except ValueError:
            data = {}
        # openrouter sometimes sends errors with a 200
        error = data.get("error") if isinstance(data, dict) else None
        code = resp.status_code if resp.status_code >= 400 else (error or {}).get("code")
        if code == 429:
            raise _openrouter_rate_limit(resp, error or {})
        if code or error:
            raise _openrouter_error(code, error or {})

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected OpenRouter response: {str(data)[:300]}") from exc


def _openrouter_rate_limit(resp, error):
    message = str(error.get("message", ""))
    headers = (error.get("metadata") or {}).get("headers") or {}
    reset = resp.headers.get("X-RateLimit-Reset") or headers.get("X-RateLimit-Reset")
    log.warning("OpenRouter rate limit: %s (reset=%s)", message, reset)
    if "per-day" in message or "per day" in message.lower():
        when = _format_reset(reset)
        return RateLimitError(
            f"OpenRouter daily free limit: {message}",
            "The free AI model's daily request limit has been reached"
            + (f"; it resets at {when}." if when else ". Please try again later."),
        )
    return RateLimitError(f"OpenRouter rate limit: {message}")


def _format_reset(reset_ms):
    try:
        moment = datetime.fromtimestamp(int(reset_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    return moment.strftime("%H:%M UTC")


def _openrouter_error(code, error):
    message = str(error.get("message") or f"HTTP {code}")
    log.error("OpenRouter error %s: %s", code, message)
    if code == 401:
        user = "The AI service rejected the API key. Ask an admin to check OPENROUTER_API_KEY."
    elif code == 402:
        user = ("The OpenRouter account has a negative balance, which blocks free models too. "
                "Ask an admin to check the account.")
    elif code == 404:
        user = ("The configured AI model isn't available. Ask an admin to check CHAT_MODEL and the "
                "OpenRouter privacy settings for free models.")
    elif isinstance(code, int) and code >= 500:
        user = "The AI provider is having trouble right now. Please try again shortly."
    else:
        user = None
    return LLMError(f"OpenRouter error {code}: {message}", user)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model, *, base_url, **kwargs):
        super().__init__(model, **kwargs)
        self.base_url = base_url.rstrip("/")

    def _complete(self, messages, temperature, max_tokens):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            resp = self.session.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        except requests.Timeout as exc:
            raise LLMError(f"Ollama timed out: {exc}",
                           "The local AI model took too long to respond. Please try again.") from exc
        except requests.RequestException as exc:
            raise LLMError(
                f"Ollama unreachable at {self.base_url}: {exc}",
                f"Can't reach the local Ollama server at {self.base_url}. Is `ollama serve` running?",
            ) from exc

        if resp.status_code == 404:
            raise LLMError(f"Ollama model {self.model!r} not found",
                           f"The local model '{self.model}' isn't installed. Run `ollama pull {self.model}`.")
        if resp.status_code == 429:
            raise RateLimitError("Ollama is overloaded (429)",
                                 "The local AI model is busy. Please try again in a moment.")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError(f"Unexpected Ollama response: {resp.text[:300]}") from exc


def create_llm(config):
    common = {
        "temperature": config["LLM_TEMPERATURE"],
        "max_tokens": config["LLM_MAX_TOKENS"],
        "timeout": config["LLM_TIMEOUT_SECONDS"],
    }
    provider = config["LLM_PROVIDER"]
    if provider == "openrouter":
        return OpenRouterProvider(
            config["CHAT_MODEL"],
            api_key=config["OPENROUTER_API_KEY"],
            base_url=config["OPENROUTER_BASE_URL"],
            fallback_models=config["OPENROUTER_FALLBACK_MODELS"],
            **common,
        )
    if provider == "ollama":
        return OllamaProvider(config["OLLAMA_MODEL"], base_url=config["OLLAMA_URL"], **common)
    raise ValueError(f"Unknown LLM_PROVIDER {provider!r}; use 'openrouter' or 'ollama'.")


def get_llm():
    return current_app.extensions["llm"]
