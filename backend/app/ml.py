import threading

import click
from flask import current_app
from werkzeug.serving import is_running_from_reloader

_lock = threading.Lock()


def get_embedder(app=None):
    return _get(app, "embedder", _load_embedder)


def get_reranker(app=None):
    return _get(app, "reranker", _load_reranker)


def preload(app):
    if app.config["PRELOAD_MODELS"] and _serves_requests(app):
        get_embedder(app)
        get_reranker(app)


def _get(app, key, loader):
    app = app or current_app._get_current_object()
    model = app.extensions.get(key)
    if model is None:
        with _lock:
            model = app.extensions.get(key)
            if model is None:
                model = loader(app.config)
                app.extensions[key] = model
    return model


def _load_embedder(config):
    from .retrieval.embeddings import Embedder

    return Embedder(
        config["EMBEDDING_MODEL"],
        dim=config["EMBEDDING_DIM"],
        query_prefix=config["EMBEDDING_QUERY_PREFIX"],
        device=config["MODEL_DEVICE"],
    )


def _load_reranker(config):
    from .retrieval.reranker import Reranker

    return Reranker(config["RERANK_MODEL"], device=config["MODEL_DEVICE"])


def _serves_requests(app):
    # skip the reloader parent and other flask commands
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return True
    if ctx.info_name != "run":
        return False
    reload = ctx.params.get("reload")
    if reload is None:
        reload = app.debug
    return not reload or is_running_from_reloader()
