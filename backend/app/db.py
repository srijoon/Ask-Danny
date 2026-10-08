import logging

from flask import current_app
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

log = logging.getLogger(__name__)

USERS = "users"
DOCUMENTS = "documents"
CHUNKS = "chunks"
CONVERSATIONS = "conversations"


def init_app(app):
    uri = app.config["MONGODB_URI"]
    if not uri:
        log.warning("MONGODB_URI is not set; database features are unavailable.")
        app.extensions["mongo_db"] = None
        return
    client = MongoClient(uri, appname="ask-danny", serverSelectionTimeoutMS=10_000)
    app.extensions["mongo_db"] = client[app.config["MONGODB_DB"]]


def get_db():
    db = current_app.extensions.get("mongo_db")
    if db is None:
        raise RuntimeError("MONGODB_URI is not configured. Set it in backend/.env.")
    return db


def vector_index_definition(config):
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": config["EMBEDDING_DIM"],
                "similarity": "cosine",
            },
            {"type": "filter", "path": "access"},
        ]
    }


def text_index_definition():
    # `in` filters need the token type
    return {
        "mappings": {
            "dynamic": False,
            "fields": {
                "text": {"type": "string", "analyzer": "lucene.english"},
                "title": {"type": "string", "analyzer": "lucene.english"},
                "access": {"type": "token"},
            },
        }
    }


def search_index_models(config):
    models = [
        SearchIndexModel(
            definition=vector_index_definition(config),
            name=config["VECTOR_INDEX_NAME"],
            type="vectorSearch",
        )
    ]
    if config["KEYWORD_SEARCH_ENABLED"]:
        models.append(
            SearchIndexModel(
                definition=text_index_definition(),
                name=config["TEXT_INDEX_NAME"],
                type="search",
            )
        )
    return models


def ensure_indexes(db, config, echo=print):
    for name in (USERS, DOCUMENTS, CHUNKS, CONVERSATIONS):
        if name not in db.list_collection_names():
            db.create_collection(name)

    db[USERS].create_index("username", unique=True)
    db[DOCUMENTS].create_index([("created_at", DESCENDING)])
    db[DOCUMENTS].create_index("sha256")
    db[CHUNKS].create_index([("doc_id", ASCENDING), ("chunk_index", ASCENDING)])
    db[CONVERSATIONS].create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    echo("Regular indexes are in place.")

    existing = {ix["name"] for ix in db[CHUNKS].list_search_indexes()}
    for model in search_index_models(config):
        name = model.document["name"]
        if name in existing:
            echo(f"Search index '{name}' already exists.")
            continue
        try:
            db[CHUNKS].create_search_index(model)
            echo(f"Created search index '{name}' (Atlas builds it in the background).")
        except OperationFailure as exc:
            echo(f"Could not create search index '{name}': {exc.details or exc}")
            echo("Create it in the Atlas UI instead (JSON editor, collection 'chunks'):")
            echo(model.document)


def search_index_status(db, config):
    try:
        indexes = db[CHUNKS].list_search_indexes()
        return {ix["name"]: ix.get("status", "UNKNOWN") for ix in indexes}
    except OperationFailure as exc:
        log.warning("Could not list search indexes: %s", exc)
        return {}
