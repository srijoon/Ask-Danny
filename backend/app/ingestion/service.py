import hashlib
import logging
import os
from datetime import datetime, timezone

from bson import ObjectId
from flask import current_app
from pymongo.errors import PyMongoError

from ..db import CHUNKS, DOCUMENTS, get_db
from ..ml import get_embedder
from ..retrieval.embeddings import passage_text, to_bson_vector
from .chunker import chunk_text
from .parsers import ParseError, parse

log = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


def ingest_document(filename, data, *, access, uploaded_by, title=None):
    cfg = current_app.config
    db = get_db()
    if not access:
        raise IngestionError("Choose at least one group (or Everyone) who can see this document.")

    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = db[DOCUMENTS].find_one({"sha256": sha256}, {"title": 1})
    if duplicate:
        raise IngestionError(f"{filename} was already uploaded as '{duplicate['title']}'.")

    try:
        sections = parse(filename, data)
    except ParseError as exc:
        raise IngestionError(str(exc)) from exc

    title = (title or "").strip() or os.path.splitext(os.path.basename(filename))[0]
    embedder = get_embedder()
    pieces = []
    for section in sections:
        for text in chunk_text(
            section.text,
            embedder.count_tokens,
            max_tokens=cfg["CHUNK_TOKENS"],
            overlap_tokens=cfg["CHUNK_OVERLAP_TOKENS"],
        ):
            pieces.append((section.page, text))
    if not pieces:
        raise IngestionError(
            f"No text could be extracted from {filename}. Scanned PDFs need OCR first."
        )

    vectors = embedder.embed_documents([passage_text(title, text) for _, text in pieces])

    doc_id = ObjectId()
    document = {
        "_id": doc_id,
        "title": title,
        "filename": filename,
        "file_type": os.path.splitext(filename)[1].lower().lstrip("."),
        "size_bytes": len(data),
        "sha256": sha256,
        "access": access,
        "uploaded_by": uploaded_by,
        "created_at": datetime.now(timezone.utc),
        "chunk_count": len(pieces),
    }
    chunks = [
        {
            "doc_id": doc_id,
            "title": title,
            "filename": filename,
            "page": page,
            "chunk_index": index,
            "text": text,
            "access": access,
            "embedding": to_bson_vector(vector),
        }
        for index, ((page, text), vector) in enumerate(zip(pieces, vectors))
    ]

    try:
        db[CHUNKS].insert_many(chunks, ordered=False)
        db[DOCUMENTS].insert_one(document)
    except PyMongoError as exc:
        db[CHUNKS].delete_many({"doc_id": doc_id})
        raise IngestionError(f"Couldn't save {filename}: {exc}") from exc
    log.info("Ingested %s: %d chunks, access=%s", filename, len(chunks), access)
    return document


def set_document_access(doc_id, access):
    if not access:
        raise IngestionError("Choose at least one group (or Everyone) who can see this document.")
    db = get_db()
    result = db[DOCUMENTS].update_one({"_id": doc_id}, {"$set": {"access": access}})
    if not result.matched_count:
        raise IngestionError("Document not found.")
    db[CHUNKS].update_many({"doc_id": doc_id}, {"$set": {"access": access}})


def delete_document(doc_id):
    db = get_db()
    db[CHUNKS].delete_many({"doc_id": doc_id})
    db[DOCUMENTS].delete_one({"_id": doc_id})
