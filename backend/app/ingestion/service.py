# The ingest pipeline shared by the admin page, POST /api/files and
# `flask ingest`: dedup -> parse -> chunk -> embed -> store document + chunks.
# Also owns access changes and deletion, which must update both collections.
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


def clean_filename(name):
    """Safe display name from a raw upload filename — keeps non-ASCII characters."""
    # metadata only, never a path, so non-ASCII names stay intact (secure_filename turned
    # "日本.pdf" into "pdf"). old browsers send "C:\fakepath\x.pdf", hence the backslashes
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    if len(name) <= 255:
        return name
    # trim the stem, not the extension, so the parser can still recognise the type
    stem, ext = os.path.splitext(name)
    return stem[: 255 - len(ext)] + ext if len(ext) <= 16 else name[:255]


def ingest_document(filename, data, *, access, uploaded_by, title=None):
    """Full upload pipeline: dedup -> parse -> chunk -> embed -> store doc + chunks."""
    cfg = current_app.config
    db = get_db()
    if not access:
        # a document with an empty access list would be invisible to everyone
        raise IngestionError("Choose at least one group (or Everyone) who can see this document.")

    # content-hash dedup: re-uploading the same bytes stores nothing twice
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
    # count_tokens comes from the embedder's tokenizer, so chunk sizes are
    # measured in the same units the embedding model actually sees
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
    # refuse before embedding: a huge file would pin the CPU for minutes and eat M0 storage
    if len(pieces) > cfg["MAX_CHUNKS_PER_DOCUMENT"]:
        raise IngestionError(
            f"{filename} is too long ({len(pieces)} chunks; the limit is "
            f"{cfg['MAX_CHUNKS_PER_DOCUMENT']}). Split it into smaller files."
        )

    # the title is embedded into every passage, so a question about "holiday policy"
    # can match a chunk from a file named "Holiday Policy" even when the chunk
    # text never repeats those words
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
    # chunks denormalise title/filename/access so search results are self-contained
    # and the Atlas indexes can filter on access without a $lookup join
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
        # unordered: one bad chunk aborts only itself, not the whole batch
        db[CHUNKS].insert_many(chunks, ordered=False)
        db[DOCUMENTS].insert_one(document)
    except PyMongoError as exc:
        # no transactions on M0, so clean up manually rather than leave orphaned chunks
        db[CHUNKS].delete_many({"doc_id": doc_id})
        raise IngestionError(f"Couldn't save {filename}: {exc}") from exc
    log.info("Ingested %s: %d chunks, access=%s", filename, len(chunks), access)
    return document


def set_document_access(doc_id, access):
    """Rewrite a document's access list on both the documents and chunks rows."""
    if not access:
        raise IngestionError("Choose at least one group (or Everyone) who can see this document.")
    db = get_db()
    result = db[DOCUMENTS].update_one({"_id": doc_id}, {"$set": {"access": access}})
    if not result.matched_count:
        raise IngestionError("Document not found.")
    # chunks carry their own copy of access (the search indexes filter on it),
    # so it has to be updated in both places
    db[CHUNKS].update_many({"doc_id": doc_id}, {"$set": {"access": access}})


def delete_document(doc_id):
    """Remove a document and all of its chunks (admin page + DELETE /api/files)."""
    db = get_db()
    # chunks first: they hold the embeddings and are the bulk of the storage
    db[CHUNKS].delete_many({"doc_id": doc_id})
    db[DOCUMENTS].delete_one({"_id": doc_id})
