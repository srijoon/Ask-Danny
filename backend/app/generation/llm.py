# LLM provider abstraction: chat() owns the shared rules (think-tag stripping,
# empty-reply handling) while OpenRouterProvider and OllamaProvider implement the
# wire call and translate provider errors into user-safe messages. create_llm()
# picks the provider from config; callers use get_llm().
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import requests
from flask import current_app

log = logging.getLogger(__name__)

# some models wrap chain-of-thought in <think>…</think>; users never want it
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    """Provider failure carrying both a log message and a user-safe message."""

    # carries a user-facing message alongside the internal one, so handlers can
    # show something friendly without leaking provider details
    default_user_message = "The AI model couldn't answer right now. Please try again in a moment."

    def __init__(self, message, user_message=None):
        """message goes to logs; user_message is what the UI may show."""
        super().__init__(message)
        self.user_message = user_message or self.default_user_message


class RateLimitError(LLMError):
    """429 from either provider — lets callers show 'wait and retry' wording."""

    # its own subclass so callers can tell "busy, try again" from "actually broken"
    default_user_message = (
        "The free AI model is busy right now (rate limit reached). "
        "Please wait a minute and try again."
    )


class LLMProvider(ABC):
    """Provider interface: chat() wraps the provider's _complete() with shared rules."""

    name = "base"

    def __init__(self, model, *, temperature=0.2, max_tokens=1024, timeout=120):
        """Store model + generation limits and create the reusable HTTP session."""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        # one session per provider: connections are reused across requests
        self.session = requests.Session()

    @abstractmethod
    def _complete(self, messages, temperature, max_tokens):
        """The provider's wire call — the only thing subclasses implement."""
        # providers only implement the wire call; chat() owns the shared rules
        ...

    def chat(self, messages, *, temperature=None, max_tokens=None):
        """Ask the model; strips think-tags and rejects empty replies."""
        text = self._complete(
            messages,
            self.temperature if temperature is None else temperature,
            self.max_tokens if max_tokens is None else max_tokens,
        )
        text = _THINK_RE.sub("", text or "").strip()
        if not text:
            # stripping think-tags can leave nothing behind; retrying usually helps
            raise LLMError(f"{self.describe()} returned an empty reply",
                           "The AI model returned an empty answer. Please try again.")
        return text

    def describe(self):
        """Short 'provider:model' label for logs and the admin page."""
        return f"{self.name}:{self.model}"


class OpenRouterProvider(LLMProvider):
    """OpenRouter /chat/completions with optional same-request model fallbacks."""

    name = "openrouter"

    def __init__(self, model, *, api_key, base_url, fallback_models=(), **kwargs):
        """Store credentials, base URL and the fallback model list."""
        super().__init__(model, **kwargs)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.fallback_models = list(fallback_models)

    def _complete(self, messages, temperature, max_tokens):
        """POST to OpenRouter and translate HTTP/embedded errors into LLMError."""
        # fail before the network call: a missing key is a config error, not a 401
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
            # openrouter walks this list in order when the primary model is down
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
            # log a snippet of the real response so provider quirks are debuggable
            raise LLMError(f"Unexpected OpenRouter response: {str(data)[:300]}") from exc


def _openrouter_rate_limit(resp, error):
    """Build a RateLimitError, adding the daily reset time when the header has it."""
    # free models have per-minute and per-day limits; the daily reset time arrives
    # in a header, so we can tell the user exactly when to come back
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
    """Render an epoch-ms rate-limit header as 'HH:MM UTC' for the user message."""
    # the header is epoch milliseconds; render it short enough for a flash message
    try:
        moment = datetime.fromtimestamp(int(reset_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None
    return moment.strftime("%H:%M UTC")


def _openrouter_error(code, error):
    """Map an OpenRouter failure code to an LLMError with an actionable message."""
    # translate the codes we actually hit on free models into something actionable;
    # anything unmapped falls back to the generic "try again" message
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
    """Local Ollama /api/chat — the offline fallback behind the same interface."""

    name = "ollama"

    def __init__(self, model, *, base_url, **kwargs):
        """Store the model name and server URL."""
        super().__init__(model, **kwargs)
        self.base_url = base_url.rstrip("/")

    def _complete(self, messages, temperature, max_tokens):
        """POST to Ollama; translates errors, including 'model not pulled'."""
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
            # a 404 from /api/chat almost always means the model isn't pulled yet
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
    """Build the provider named by config — called once, in create_app."""
    # single place that picks the provider; everything else goes through get_llm()
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
    """Fetch the shared provider created in create_app (chat/answer, admin page)."""
    return current_app.extensions["llm"]
