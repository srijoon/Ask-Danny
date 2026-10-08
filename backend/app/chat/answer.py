# Orchestrates one answer: rewrite follow-ups into a standalone search query,
# retrieve chunks the user's principals can see, and call the LLM only when
# retrieval found something relevant. Returns an Answer (status + sources) to
# chat/routes.py and `flask ask`.
import logging
import time
from dataclasses import dataclass, field

from flask import current_app

from ..generation.llm import LLMError, RateLimitError, get_llm
from ..generation.prompts import build_answer_messages, build_rewrite_messages, clean_rewritten_query
from ..retrieval.pipeline import retrieve

log = logging.getLogger(__name__)

# shown verbatim to the user; kept as a constant so the wording stays identical
# wherever a no-results answer is produced
NO_RESULTS_MESSAGE = (
    "I couldn't find anything relevant to that in the documents you have access to. "
    "Try rephrasing, or ask an admin whether the document has been uploaded and shared with you."
)


@dataclass
class Answer:
    text: str
    status: str  # "ok", "no_results", "rate_limited" or "error" — the UI colours by it
    sources: list = field(default_factory=list)
    search_query: str = ""  # what retrieval actually searched for (may be rewritten)
    llm_calls: int = 0  # counted for the usage stats — every call is latency/cost
    retrieval_mode: str = ""


def answer_question(question, history, principals):
    """Rewrite (maybe) -> retrieve -> answer; returns an Answer with status + sources."""
    cfg = current_app.config
    llm = get_llm()
    started = time.perf_counter()
    llm_calls = 0

    # step 1 (only with history): rewrite follow-ups like "what about part-timers?"
    # into a standalone query — the retriever can't see the conversation
    search_query = question
    if history and cfg["QUERY_REWRITE_ENABLED"]:
        llm_calls += 1
        try:
            # temperature 0 and a tiny cap: this is extraction, not generation
            rewritten = llm.chat(build_rewrite_messages(question, history), temperature=0,
                                 max_tokens=100)
            search_query = clean_rewritten_query(rewritten, question)
        except RateLimitError as exc:
            return Answer(exc.user_message, "rate_limited", search_query=question, llm_calls=llm_calls)
        except LLMError as exc:
            # a rewrite failure must not block the question — the original still works
            log.warning("Query rewrite failed (%s); searching with the original question.", exc)

    # step 2: retrieve only chunks whose access list intersects the user's principals
    result = retrieve(search_query, principals)
    sources = [_source(number, chunk) for number, chunk in enumerate(result.chunks, start=1)]
    if not result.chunks:
        # no LLM call here: nothing relevant retrieved means no context to ground
        # an answer in — this is the biggest single cost saver
        log.info("No chunk passed the threshold (top score %s) for %r", result.top_score, search_query)
        return Answer(NO_RESULTS_MESSAGE, "no_results", search_query=search_query,
                      llm_calls=llm_calls, retrieval_mode=result.mode)

    # step 3: answer strictly from the top chunks (see prompts.py for the rules)
    llm_calls += 1
    try:
        text = llm.chat(build_answer_messages(question, history, result.chunks))
        status = "ok"
    except RateLimitError as exc:
        # provider failures still produce an Answer so the UI shows them inline
        # instead of dropping the request on the floor
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
    """Shape a retrieved chunk into the numbered source shown in the UI."""
    # `n` matches the [n] labels in the prompt, so the model's citations and the
    # UI's numbered source list line up
    return {
        "n": number,
        "doc_id": str(chunk["doc_id"]),
        "title": chunk["title"],
        "filename": chunk.get("filename"),
        "page": chunk.get("page"),
        "score": round(chunk["rerank_score"], 3),
        "text": chunk["text"],
    }
