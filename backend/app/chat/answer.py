import logging
import time
from dataclasses import dataclass, field

from flask import current_app

from ..generation.llm import LLMError, RateLimitError, get_llm
from ..generation.prompts import build_answer_messages, build_rewrite_messages, clean_rewritten_query
from ..retrieval.pipeline import retrieve

log = logging.getLogger(__name__)

NO_RESULTS_MESSAGE = (
    "I couldn't find anything relevant to that in the documents you have access to. "
    "Try rephrasing, or ask an admin whether the document has been uploaded and shared with you."
)


@dataclass
class Answer:
    text: str
    status: str
    sources: list = field(default_factory=list)
    search_query: str = ""
    llm_calls: int = 0
    retrieval_mode: str = ""


def answer_question(question, history, principals):
    cfg = current_app.config
    llm = get_llm()
    started = time.perf_counter()
    llm_calls = 0

    search_query = question
    if history and cfg["QUERY_REWRITE_ENABLED"]:
        llm_calls += 1
        try:
            rewritten = llm.chat(build_rewrite_messages(question, history), temperature=0,
                                 max_tokens=100)
            search_query = clean_rewritten_query(rewritten, question)
        except RateLimitError as exc:
            return Answer(exc.user_message, "rate_limited", search_query=question, llm_calls=llm_calls)
        except LLMError as exc:
            log.warning("Query rewrite failed (%s); searching with the original question.", exc)

    result = retrieve(search_query, principals)
    sources = [_source(number, chunk) for number, chunk in enumerate(result.chunks, start=1)]
    if not result.chunks:
        log.info("No chunk passed the threshold (top score %s) for %r", result.top_score, search_query)
        return Answer(NO_RESULTS_MESSAGE, "no_results", search_query=search_query,
                      llm_calls=llm_calls, retrieval_mode=result.mode)

    llm_calls += 1
    try:
        text = llm.chat(build_answer_messages(question, history, result.chunks))
        status = "ok"
    except RateLimitError as exc:
        text, status = exc.user_message, "rate_limited"
    except LLMError as exc:
        log.error("Answer generation failed: %s", exc)
        text, status = exc.user_message, "error"

    log.info(
        "Answered in %.1fs: status=%s mode=%s candidates=%d kept=%d llm_calls=%d llm=%s",
        time.perf_counter() - started, status, result.mode, result.candidates,
        len(result.chunks), llm_calls, llm.describe(),
    )
    return Answer(text, status, sources, search_query, llm_calls, result.mode)


def _source(number, chunk):
    return {
        "n": number,
        "doc_id": str(chunk["doc_id"]),
        "title": chunk["title"],
        "filename": chunk.get("filename"),
        "page": chunk.get("page"),
        "score": round(chunk["rerank_score"], 3),
        "text": chunk["text"],
    }
