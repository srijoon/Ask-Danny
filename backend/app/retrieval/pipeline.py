import logging
from dataclasses import dataclass, field

from flask import current_app
from pymongo.errors import OperationFailure

from ..db import CHUNKS, get_db
from ..ml import get_embedder, get_reranker
from .embeddings import passage_text
from .search import keyword_search, reciprocal_rank_fusion, vector_search

log = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    chunks: list = field(default_factory=list)
    mode: str = "vector"
    candidates: int = 0
    top_score: float | None = None


def retrieve(query, principals):
    cfg = current_app.config
    chunks = get_db()[CHUNKS]

    result_lists = [
        vector_search(
            chunks,
            get_embedder().embed_query(query),
            principals,
            index=cfg["VECTOR_INDEX_NAME"],
            num_candidates=cfg["VECTOR_NUM_CANDIDATES"],
            limit=cfg["VECTOR_LIMIT"],
        )
    ]
    mode = "vector"
    if cfg["KEYWORD_SEARCH_ENABLED"]:
        try:
            result_lists.append(
                keyword_search(
                    chunks, query, principals, index=cfg["TEXT_INDEX_NAME"], limit=cfg["KEYWORD_LIMIT"]
                )
            )
            mode = "hybrid"
        except OperationFailure as exc:
            log.warning("Keyword search failed (%s); continuing with vector search only.", exc)

    merged = reciprocal_rank_fusion(result_lists, k=cfg["RRF_K"])
    # double check access in case an index is misconfigured
    allowed = set(principals)
    merged = [hit for hit in merged if allowed.intersection(hit.get("access", []))]

    candidates = merged[: cfg["RERANK_CANDIDATES"]]
    scores = get_reranker().score(query, [passage_text(h["title"], h["text"]) for h in candidates])
    for hit, score in zip(candidates, scores):
        hit["rerank_score"] = score
    ranked = sorted(candidates, key=lambda hit: hit["rerank_score"], reverse=True)

    passing = [hit for hit in ranked if hit["rerank_score"] >= cfg["RERANK_MIN_SCORE"]]
    return RetrievalResult(
        chunks=passing[: cfg["FINAL_TOP_K"]],
        mode=mode,
        candidates=len(merged),
        top_score=ranked[0]["rerank_score"] if ranked else None,
    )
