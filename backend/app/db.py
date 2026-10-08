# MongoDB plumbing: the connection lives on app.extensions, collection names are
# constants, and ensure_indexes() creates the regular + Atlas search indexes
# (`flask init-db` runs it). Every module reaches the database via get_db().
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
    """Open the Mongo connection and stash it on app.extensions for get_db()."""
    uri = app.config["MONGODB_URI"]
    if not uri:
        # tests and CLI tooling run without a database; get_db() raises if code tries anyway
        log.warning("MONGODB_URI is not set; database features are unavailable.")
        app.extensions["mongo_db"] = None
        return
    # appname shows up in Atlas connection stats; the timeout fails fast on a bad URI
    client = MongoClient(uri, appname="ask-danny", serverSelectionTimeoutMS=10_000)
    app.extensions["mongo_db"] = client[app.config["MONGODB_DB"]]


def get_db():
    """Return the database handle; raises a clear error when unconfigured."""
    # every db call goes through here, so "no database configured" surfaces as a
    # clear error at the point of use rather than an AttributeError later
    db = current_app.extensions.get("mongo_db")
    if db is None:
        raise RuntimeError("MONGODB_URI is not configured. Set it in backend/.env.")
    return db


def vector_index_definition(config):
    """Atlas $vectorSearch index definition: embedding field + access filter."""
    # "access" as a filter field lets $vectorSearch pre-filter candidates, so the
    # permission check happens inside the index, not after fetching
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
    """Atlas $search index over text/title with access as a filter token."""
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
    """The index models init-db creates — vector always, text only if keyword search is on."""
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
    """Create collections, regular indexes and search indexes (runs under `flask init-db`)."""
    # create the four collections up front so a fresh cluster is fully set up by
    # init-db instead of materialising one write at a time
    for name in (USERS, DOCUMENTS, CHUNKS, CONVERSATIONS):
        if name not in db.list_collection_names():
            db.create_collection(name)

    # the queries the app actually runs: users by name, docs newest-first and by
    # content hash for dedup, chunks by parent doc, conversations per user
    db[USERS].create_index("username", unique=True)
    db[DOCUMENTS].create_index([("created_at", DESCENDING)])
    db[DOCUMENTS].create_index("sha256")
    db[CHUNKS].create_index([("doc_id", ASCENDING), ("chunk_index", ASCENDING)])
    db[CONVERSATIONS].create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    echo("Regular indexes are in place.")

    # search indexes are Atlas-side resources; an existing name is left alone even if
    # its definition drifted (fixing that means dropping it in the Atlas UI)
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
            # some tiers/permissions reject index creation; print the definition so an
            # admin can paste it into the Atlas UI instead
            echo(f"Could not create search index '{name}': {exc.details or exc}")
            echo("Create it in the Atlas UI instead (JSON editor, collection 'chunks'):")
            echo(model.document)


def search_index_status(db, config):
    """Map each search-index name to its Atlas status (admin page + init-db output)."""
    # the admin page shows index status; a permissions failure shouldn't break it
    try:
        indexes = db[CHUNKS].list_search_indexes()
        return {ix["name"]: ix.get("status", "UNKNOWN") for ix in indexes}
    except OperationFailure as exc:
        log.warning("Could not list search indexes: %s", exc)
        return {}
