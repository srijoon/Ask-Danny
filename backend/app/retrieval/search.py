_FIELDS = {"_id": 1, "doc_id": 1, "title": 1, "filename": 1, "page": 1, "chunk_index": 1,
           "text": 1, "access": 1}


def vector_search(collection, query_vector, principals, *, index, num_candidates, limit):
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
