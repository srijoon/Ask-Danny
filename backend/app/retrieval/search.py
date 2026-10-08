# The two Atlas search legs — $vectorSearch on embeddings and $search keyword
# match — both pre-filtered by the caller's access principals, plus Reciprocal
# Rank Fusion to merge their rankings. Used only by retrieval/pipeline.py.
#
# everything a hit needs downstream: display fields for the answer UI, and access
# for the permission re-check — embeddings stay out of the response
_FIELDS = {"_id": 1, "doc_id": 1, "title": 1, "filename": 1, "page": 1, "chunk_index": 1,
           "text": 1, "access": 1}


def vector_search(collection, query_vector, principals, *, index, num_candidates, limit):
    """$vectorSearch leg: top chunks by embedding, pre-filtered by access principals."""
    # the access filter runs inside $vectorSearch as a pre-filter, so Atlas only
    # ranks chunks the caller could already see — not just the top `limit`
    pipeline = [
        {
            "$vectorSearch": {
                "index": index,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(num_candidates, limit),
                "limit": limit,
                "filter": {"access": {"$in": principals}},
            }
        },
        {"$project": {**_FIELDS, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(collection.aggregate(pipeline))


def keyword_search(collection, query, principals, *, index, limit):
    """$search leg: lucene text match on text+title with the same access filter."""
    # lucene text match over text+title catches exact terms the embedder misses
    # (part numbers, acronyms, names); the same access filter applies here too
    pipeline = [
        {
            "$search": {
                "index": index,
                "compound": {
                    "must": [{"text": {"query": query, "path": ["text", "title"]}}],
                    "filter": [{"in": {"path": "access", "value": principals}}],
                },
            }
        },
        {"$limit": limit},
        {"$project": {**_FIELDS, "score": {"$meta": "searchScore"}}},
    ]
    return list(collection.aggregate(pipeline))


def reciprocal_rank_fusion(result_lists, k=60):
    """Merge ranked hit lists by rank position — raw scores aren't comparable."""
    # vector and lucene scores aren't on a comparable scale, so merge by rank
    # instead of score: each hit earns 1/(k+rank) per list; k=60 is the standard value
    fused = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):
            entry = fused.get(hit["_id"])
            if entry is None:
                entry = {key: value for key, value in hit.items() if key != "score"}
                entry["rrf_score"] = 0.0
                fused[hit["_id"]] = entry
            entry["rrf_score"] += 1.0 / (k + rank)
    return sorted(fused.values(), key=lambda hit: hit["rrf_score"], reverse=True)
