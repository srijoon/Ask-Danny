import pytest

from app.chat import answer as answer_module
from app.chat.answer import NO_RESULTS_MESSAGE, answer_question
from app.generation.llm import LLMError, RateLimitError
from app.retrieval.pipeline import RetrievalResult

CHUNK = {"_id": "c1", "doc_id": "d1", "title": "Handbook", "filename": "handbook.pdf", "page": 3,
         "text": "New hires get 15 vacation days.", "rerank_score": 0.93}
HISTORY = [{"role": "user", "content": "What is the vacation policy?"},
           {"role": "assistant", "content": "It is in the handbook [1]."}]


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def describe(self):
        return "fake:model"


@pytest.fixture
def run(app, monkeypatch):
    searched = []

    def fake_retrieve(query, principals):
        searched.append(query)
        return RetrievalResult(chunks=list(run.chunks), mode="hybrid", candidates=len(run.chunks),
                               top_score=run.chunks[0]["rerank_score"] if run.chunks else 0.0)

    monkeypatch.setattr(answer_module, "retrieve", fake_retrieve)

    def run(llm, history=()):
        app.extensions["llm"] = llm
        with app.app_context():
            return answer_question("How many days do new hires get?", list(history), ["everyone"]), searched

    run.chunks = [CHUNK]
    return run


def test_first_question_uses_exactly_one_llm_call(run):
    llm = FakeLLM("New hires get 15 days [1].")
    answer, searched = run(llm)
    assert (answer.status, answer.llm_calls, len(llm.calls)) == ("ok", 1, 1)
    assert searched == ["How many days do new hires get?"]
    assert answer.sources[0]["title"] == "Handbook" and answer.sources[0]["n"] == 1


def test_follow_up_is_rewritten_before_search(run):
    llm = FakeLLM("vacation days for new hires", "15 days [1].")
    answer, searched = run(llm, HISTORY)
    assert searched == ["vacation days for new hires"]
    assert answer.llm_calls == 2 and answer.search_query == "vacation days for new hires"


def test_rewrite_can_be_switched_off(app, run):
    app.config["QUERY_REWRITE_ENABLED"] = False
    llm = FakeLLM("15 days [1].")
    answer, searched = run(llm, HISTORY)
    assert answer.llm_calls == 1 and searched == ["How many days do new hires get?"]


def test_failed_rewrite_falls_back_to_original_question(run):
    llm = FakeLLM(LLMError("boom"), "15 days [1].")
    answer, searched = run(llm, HISTORY)
    assert answer.status == "ok" and searched == ["How many days do new hires get?"]


def test_rate_limited_rewrite_stops_before_spending_another_call(run):
    llm = FakeLLM(RateLimitError("429"))
    answer, searched = run(llm, HISTORY)
    assert answer.status == "rate_limited" and len(llm.calls) == 1 and searched == []


def test_no_relevant_chunks_means_no_llm_call(run):
    run.chunks = []
    llm = FakeLLM()
    answer, _ = run(llm)
    assert (answer.status, answer.text, llm.calls) == ("no_results", NO_RESULTS_MESSAGE, [])


def test_rate_limited_answer_is_friendly_and_keeps_sources(run):
    llm = FakeLLM(RateLimitError("429"))
    answer, _ = run(llm)
    assert answer.status == "rate_limited"
    assert "rate limit" in answer.text
    assert answer.sources
