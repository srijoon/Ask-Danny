import pytest
from pymongo.errors import OperationFailure

from app.permissions import document_access, parse_groups, principals_for
from app.retrieval import pipeline
from app.retrieval.search import keyword_search, reciprocal_rank_fusion, vector_search


def hit(id_, text="", access=("everyone",), title="Doc"):
    return {"_id": id_, "doc_id": "d", "title": title, "text": text, "access": list(access),
            "page": None, "score": 1.0}


class RecordingCollection:
    def __init__(self):
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return []


def test_rrf_scores_and_order():
    merged = reciprocal_rank_fusion([[hit("a"), hit("b")], [hit("b"), hit("c")]], k=60)
    scores = {h["_id"]: h["rrf_score"] for h in merged}
    assert [h["_id"] for h in merged] == ["b", "a", "c"]
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == pytest.approx(1 / 61)
    assert "score" not in merged[0]


def test_both_searches_apply_the_permission_filter():
    principals = ["everyone", "user:alice", "group:hr"]
    coll = RecordingCollection()
    vector_search(coll, [0.1] * 384, principals, index="v", num_candidates=200, limit=30)
    stage = coll.pipeline[0]["$vectorSearch"]
    assert stage["filter"] == {"access": {"$in": principals}}
    assert (stage["numCandidates"], stage["limit"]) == (200, 30)

    keyword_search(coll, "vacation days", principals, index="t", limit=30)
    compound = coll.pipeline[0]["$search"]["compound"]
    assert compound["filter"] == [{"in": {"path": "access", "value": principals}}]
    assert coll.pipeline[1] == {"$limit": 30}


def test_principals_and_document_access():
    assert principals_for({"username": "alice", "groups": ["hr"]}) == ["everyone", "user:alice", "group:hr"]
    assert document_access(["HR, finance"], everyone=False, owner="admin") == [
        "group:finance", "group:hr", "user:admin"]
    assert document_access(["hr"], everyone=True, owner="admin") == ["everyone"]
    assert document_access([""], everyone=False, owner="admin") == []
    with pytest.raises(ValueError):
        parse_groups(["bad group!"])


@pytest.fixture
def fake_search(monkeypatch):
    results = {"vector": [], "keyword": [], "keyword_error": None, "calls": []}

    def fake_vector(coll, vector, principals, **kw):
        results["calls"].append(("vector", principals))
        return results["vector"]

    def fake_keyword(coll, query, principals, **kw):
        results["calls"].append(("keyword", principals))
        if results["keyword_error"]:
            raise results["keyword_error"]
        return results["keyword"]

    monkeypatch.setattr(pipeline, "vector_search", fake_vector)
    monkeypatch.setattr(pipeline, "keyword_search", fake_keyword)
    return results


def test_retrieve_reranks_thresholds_and_keeps_top_k(app, fake_search):
    app.config.update(FINAL_TOP_K=2, RERANK_MIN_SCORE=0.5)
    fake_search["vector"] = [hit("a", "nothing related"), hit("b", "vacation days policy")]
    fake_search["keyword"] = [hit("c", "vacation days for new hires"), hit("d", "vacation")]
    with app.app_context():
        result = pipeline.retrieve("vacation days", ["everyone"])
    assert result.mode == "hybrid"
    assert result.candidates == 4
    assert [h["_id"] for h in result.chunks] == ["c", "b"]
    assert all(h["rerank_score"] >= 0.5 for h in result.chunks)


def test_retrieve_drops_chunks_the_user_cannot_see(app, fake_search):
    fake_search["vector"] = [hit("secret", "vacation days", access=["group:finance"]),
                             hit("ok", "vacation days")]
    with app.app_context():
        result = pipeline.retrieve("vacation days", ["everyone", "group:hr"])
    assert [h["_id"] for h in result.chunks] == ["ok"]


def test_retrieve_falls_back_to_vector_only(app, fake_search):
    fake_search["vector"] = [hit("a", "vacation days")]
    fake_search["keyword_error"] = OperationFailure("$search is not allowed")
    with app.app_context():
        result = pipeline.retrieve("vacation days", ["everyone"])
    assert result.mode == "vector" and [h["_id"] for h in result.chunks] == ["a"]

    app.config["KEYWORD_SEARCH_ENABLED"] = False
    fake_search["calls"].clear()
    with app.app_context():
        pipeline.retrieve("vacation days", ["everyone"])
    assert [kind for kind, _ in fake_search["calls"]] == ["vector"]


def test_nothing_above_threshold(app, fake_search):
    fake_search["vector"] = [hit("a", "cafeteria hours")]
    with app.app_context():
        result = pipeline.retrieve("vacation days", ["everyone"])
    assert result.chunks == [] and result.top_score == 0.0
