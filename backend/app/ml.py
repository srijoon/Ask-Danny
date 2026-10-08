# Lazy process-wide singletons for the heavy local models (embedder + reranker).
# Loaded once, shared across requests, and pre-warmed at boot when the process
# actually serves HTTP. Callers go through get_embedder()/get_reranker().
import threading

import click
from flask import current_app
from werkzeug.serving import is_running_from_reloader

# both models are loaded lazily and cached on app.extensions; the lock keeps two
# concurrent first-requests from loading multi-hundred-MB models twice
_lock = threading.Lock()


def get_embedder(app=None):
    """The shared Embedder — loaded on first use or pre-warmed by preload()."""
    return _get(app, "embedder", _load_embedder)


def get_reranker(app=None):
    """The shared Reranker — loaded on first use or pre-warmed by preload()."""
    return _get(app, "reranker", _load_reranker)


def preload(app):
    """Warm both models at boot when this process will serve HTTP."""
    # warmup only makes sense for the process that serves HTTP; `flask init-db`
    # and friends shouldn't pay the startup cost
    if app.config["PRELOAD_MODELS"] and _serves_requests(app):
        get_embedder(app)
        get_reranker(app)


def _get(app, key, loader):
    """Load-once/cache helper behind get_embedder() and get_reranker()."""
    app = app or current_app._get_current_object()
    model = app.extensions.get(key)
    if model is None:
        # double-checked: the common path (model loaded) never takes the lock
        with _lock:
            model = app.extensions.get(key)
            if model is None:
                model = loader(app.config)
                app.extensions[key] = model
    return model


def _load_embedder(config):
    """Build the Embedder from config (invoked once, by _get)."""
    from .retrieval.embeddings import Embedder

    return Embedder(
        config["EMBEDDING_MODEL"],
        dim=config["EMBEDDING_DIM"],
        query_prefix=config["EMBEDDING_QUERY_PREFIX"],
        device=config["MODEL_DEVICE"],
    )


def _load_reranker(config):
    """Build the Reranker from config (invoked once, by _get)."""
    from .retrieval.reranker import Reranker

    return Reranker(config["RERANK_MODEL"], device=config["MODEL_DEVICE"])


def _serves_requests(app):
    """True only for the process that answers HTTP — skips CLI runs and the reloader parent."""
    # skip the reloader parent and other flask commands
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return True
    if ctx.info_name != "run":
        return False
    reload = ctx.params.get("reload")
    if reload is None:
        reload = app.debug
    # with the reloader on, flask spawns a parent that never serves requests;
    # only the child process should burn memory on the models
    return not reload or is_running_from_reloader()
