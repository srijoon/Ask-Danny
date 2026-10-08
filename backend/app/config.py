# Every setting comes from the environment (backend/.env via python-dotenv) and
# lands on the Config class, which Flask exposes as app.config — the single
# source of configuration for the rest of the app. TestConfig tweaks it for tests.
import os

from dotenv import load_dotenv

load_dotenv()


def _str(name, default=""):
    """Read an env var stripped, or the default."""
    return os.environ.get(name, default).strip()


def _bool(name, default):
    """Read a boolean-ish env var ("1"/"true"/"yes"/"on"), or the default."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    """Read an int env var, or the default when unset/blank."""
    value = os.environ.get(name)
    return int(value) if value and value.strip() else default


def _float(name, default):
    """Read a float env var, or the default when unset/blank."""
    value = os.environ.get(name)
    return float(value) if value and value.strip() else default


def _list(name, default=""):
    """Read a comma-separated env var into a list of strings."""
    return [item.strip() for item in _str(name, default).split(",") if item.strip()]


class Config:
    SECRET_KEY = _str("FLASK_SECRET_KEY", "dev")
    SESSION_COOKIE_SAMESITE = "Lax"  # blocks the cookie on cross-site posts — part of CSRF defence
    CSRF_ENABLED = True
    # flask rejects bigger bodies before our handlers ever see them
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 20) * 1024 * 1024

    MONGODB_URI = _str("MONGODB_URI")
    MONGODB_DB = _str("MONGODB_DB", "ask_danny")
    # these names must match what `flask init-db` created in Atlas
    VECTOR_INDEX_NAME = _str("VECTOR_INDEX_NAME", "chunks_vector")
    TEXT_INDEX_NAME = _str("TEXT_INDEX_NAME", "chunks_text")

    # embeddings and reranking run locally — zero API cost per upload or search
    EMBEDDING_MODEL = _str("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    # must equal both the model's output size and the vector index's numDimensions
    EMBEDDING_DIM = _int("EMBEDDING_DIM", 384)
    # bge query instruction (passages get no prefix)
    EMBEDDING_QUERY_PREFIX = os.environ.get(
        "EMBEDDING_QUERY_PREFIX", "Represent this sentence for searching relevant passages: "
    )
    RERANK_MODEL = _str("RERANK_MODEL", "BAAI/bge-reranker-base")
    MODEL_DEVICE = _str("MODEL_DEVICE", "cpu")
    # warm the models at boot so the first upload/question doesn't stall
    PRELOAD_MODELS = _bool("PRELOAD_MODELS", True)

    # ~300 tokens is a couple of paragraphs: big enough to carry meaning, small
    # enough that a few chunks stay well inside the LLM's context budget
    CHUNK_TOKENS = _int("CHUNK_TOKENS", 300)
    CHUNK_OVERLAP_TOKENS = _int("CHUNK_OVERLAP_TOKENS", 50)
    # caps CPU time per upload and M0 storage per document (500 chunks is a few hundred pages)
    MAX_CHUNKS_PER_DOCUMENT = _int("MAX_CHUNKS_PER_DOCUMENT", 500)

    # generation: OpenRouter's free tier is the default; Ollama works fully offline
    LLM_PROVIDER = _str("LLM_PROVIDER", "openrouter").lower()
    CHAT_MODEL = _str("CHAT_MODEL", "google/gemma-4-31b-it:free")  # ":free" keeps spend at $0
    OPENROUTER_API_KEY = _str("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL = _str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OPENROUTER_FALLBACK_MODELS = _list("OPENROUTER_FALLBACK_MODELS")
    OLLAMA_URL = _str("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL = _str("OLLAMA_MODEL", "llama3.1:8b")
    LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.2)  # low = grounded, factual answers
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 1500)  # caps both cost and rambling
    LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 120)

    # rewriting turns follow-ups ("what about X?") into standalone search queries
    QUERY_REWRITE_ENABLED = _bool("QUERY_REWRITE_ENABLED", True)
    CHAT_HISTORY_TURNS = _int("CHAT_HISTORY_TURNS", 3)

    # the retrieval funnel: over-fetch → fuse → rerank → keep the best few;
    # the numbers step down so the cheap stages do the broad work and the
    # expensive stages only ever see a shortlist
    VECTOR_NUM_CANDIDATES = _int("VECTOR_NUM_CANDIDATES", 200)
    VECTOR_LIMIT = _int("VECTOR_LIMIT", 30)
    KEYWORD_SEARCH_ENABLED = _bool("KEYWORD_SEARCH_ENABLED", True)
    KEYWORD_LIMIT = _int("KEYWORD_LIMIT", 30)
    RRF_K = _int("RRF_K", 60)
    RERANK_CANDIDATES = _int("RERANK_CANDIDATES", 20)
    FINAL_TOP_K = _int("FINAL_TOP_K", 6)  # what the LLM actually sees — the context budget
    # below this score we'd rather say "no results" than pay for a bad answer
    RERANK_MIN_SCORE = _float("RERANK_MIN_SCORE", 0.1)


class TestConfig(Config):
    TESTING = True
    CSRF_ENABLED = False  # tests post forms without going through the token dance
    MONGODB_URI = ""  # no database in tests; anything reaching get_db() is faked
    PRELOAD_MODELS = False
    LLM_PROVIDER = "openrouter"
    OPENROUTER_API_KEY = "test-key"
    OPENROUTER_FALLBACK_MODELS = []
    QUERY_REWRITE_ENABLED = True
