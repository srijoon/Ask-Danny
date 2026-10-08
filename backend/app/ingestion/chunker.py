# Splits extracted text into token-bounded chunks: whole paragraphs first, then
# sentences, then sliding word windows, with a carried tail for overlap. Called
# by ingestion/service.py with the embedder's tokenizer as the counter.
import re

# split after sentence-ending punctuation, but only where a new sentence plausibly
# starts — this avoids cutting "U.S. Army" or "etc., however" in half
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def chunk_text(text, count_tokens, max_tokens=300, overlap_tokens=50):
    """Split text into token-bounded chunks, carrying an overlap tail across cuts."""
    # greedy packing: keep adding pieces until the next one would overflow, then
    # carry a small tail into the new chunk so context survives the boundary
    chunks, current, size = [], [], 0
    for piece, n, starts_paragraph in _pieces(text, count_tokens, max_tokens):
        if current and size + n > max_tokens:
            chunks.append(_join(current))
            current, size = _tail(current, overlap_tokens, max_tokens - n)
        current.append((piece, n, starts_paragraph))
        size += n
    if current:
        chunks.append(_join(current))
    return chunks


def _pieces(text, count_tokens, max_tokens):
    """Yield (text, tokens, starts_paragraph) pieces at the finest level that fits."""
    # fallback ladder: prefer whole paragraphs, then sentences, then sliding word
    # windows — each level only runs when the one above still doesn't fit
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        n = count_tokens(paragraph)
        if n <= max_tokens:
            yield paragraph, n, True
            continue
        first = True
        for sentence in _SENTENCE_RE.split(paragraph):
            n = count_tokens(sentence)
            if n <= max_tokens:
                yield sentence, n, first
            else:
                # a single sentence over the limit (tables, OCR junk) gets chopped
                for window in _word_windows(sentence, count_tokens, max_tokens):
                    yield window, count_tokens(window), first
                    first = False
            first = False


def _word_windows(text, count_tokens, max_tokens):
    """Last-resort splitter: chop an oversized sentence into fitting word windows."""
    # calling the tokenizer per word would be far too slow, so estimate the
    # window size from tokens-per-word and shrink until it fits
    words = text.split()
    start = 0
    while start < len(words):
        per_word = count_tokens(" ".join(words[start:start + 200])) / min(200, len(words) - start)
        end = start + max(1, int(max_tokens / max(per_word, 1e-6)))
        while end - start > 1 and count_tokens(" ".join(words[start:end])) > max_tokens:
            end = start + max(1, int((end - start) * 0.9))
        yield " ".join(words[start:end])
        start = end


def _tail(pieces, overlap_tokens, room):
    """Pick whole trailing pieces to carry into the next chunk as overlap."""
    # take whole trailing pieces while they fit; `room` keeps the carried tail
    # from leaving no space for the piece that caused the split
    kept, size = [], 0
    for piece in reversed(pieces):
        if size + piece[1] > min(overlap_tokens, room):
            break
        kept.insert(0, piece)
        size += piece[1]
    return kept, size


def _join(pieces):
    """Reassemble pieces into one chunk, restoring paragraph vs sentence separators."""
    # re-sew the pieces with the separator each originally had: blank lines
    # between paragraphs, a single space between sentences
    out = []
    for i, (piece, _, starts_paragraph) in enumerate(pieces):
        if i:
            out.append("\n\n" if starts_paragraph else " ")
        out.append(piece)
    return "".join(out)
