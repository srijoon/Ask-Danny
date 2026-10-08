import os

from dotenv import load_dotenv

load_dotenv()


def _str(name, default=""):
    return os.environ.get(name, default).strip()


def _bool(name, default):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    value = os.environ.get(name)
    return int(value) if value and value.strip() else default


def _float(name, default):
    value = os.environ.get(name)
    return float(value) if value and value.strip() else default


def _list(name, default=""):
    return [item.strip() for item in _str(name, default).split(",") if item.strip()]


class Config:
    SECRET_KEY = _str("FLASK_SECRET_KEY", "dev")
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 20) * 1024 * 1024

    MONGODB_URI = _str("MONGODB_URI")
    MONGODB_DB = _str("MONGODB_DB", "ask_danny")
    VECTOR_INDEX_NAME = _str("VECTOR_INDEX_NAME", "chunks_vector")
    TEXT_INDEX_NAME = _str("TEXT_INDEX_NAME", "chunks_text")

    EMBEDDING_MODEL = _str("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    EMBEDDING_DIM = _int("EMBEDDING_DIM", 384)
    # bge query instruction (passages get no prefix)
    EMBEDDING_QUERY_PREFIX = os.environ.get(
        "EMBEDDING_QUERY_PREFIX", "Represent this sentence for searching relevant passages: "
    )
    RERANK_MODEL = _str("RERANK_MODEL", "BAAI/bge-reranker-base")
    MODEL_DEVICE = _str("MODEL_DEVICE", "cpu")
    PRELOAD_MODELS = _bool("PRELOAD_MODELS", True)

    CHUNK_TOKENS = _int("CHUNK_TOKENS", 300)
    CHUNK_OVERLAP_TOKENS = _int("CHUNK_OVERLAP_TOKENS", 50)
    MAX_CHUNKS_PER_DOCUMENT = _int("MAX_CHUNKS_PER_DOCUMENT", 500)

    LLM_PROVIDER = _str("LLM_PROVIDER", "openrouter").lower()
    CHAT_MODEL = _str("CHAT_MODEL", "google/gemma-4-31b-it:free")
    OPENROUTER_API_KEY = _str("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL = _str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_FALLBACK_MODELS = _list("OPENROUTER_FALLBACK_MODELS")
    OLLAMA_URL = _str("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = _str("OLLAMA_MODEL", "llama3.1:8b")
    LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.2)
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 1500)
    LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 120)

    QUERY_REWRITE_ENABLED = _bool("QUERY_REWRITE_ENABLED", True)
    CHAT_HISTORY_TURNS = _int("CHAT_HISTORY_TURNS", 3)

    VECTOR_NUM_CANDIDATES = _int("VECTOR_NUM_CANDIDATES", 200)
    VECTOR_LIMIT = _int("VECTOR_LIMIT", 30)
    KEYWORD_SEARCH_ENABLED = _bool("KEYWORD_SEARCH_ENABLED", True)
    KEYWORD_LIMIT = _int("KEYWORD_LIMIT", 30)
    RRF_K = _int("RRF_K", 60)
    RERANK_CANDIDATES = _int("RERANK_CANDIDATES", 20)
    FINAL_TOP_K = _int("FINAL_TOP_K", 6)
    RERANK_MIN_SCORE = _float("RERANK_MIN_SCORE", 0.1)


class TestConfig(Config):
    TESTING = True
    CSRF_ENABLED = False
    MONGODB_URI = ""
    PRELOAD_MODELS = False
    LLM_PROVIDER = "openrouter"
    OPENROUTER_API_KEY = "test-key"
    OPENROUTER_FALLBACK_MODELS = []
    QUERY_REWRITE_ENABLED = True
