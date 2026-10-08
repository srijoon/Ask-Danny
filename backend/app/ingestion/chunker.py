import re

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def chunk_text(text, count_tokens, max_tokens=300, overlap_tokens=50):
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
                for window in _word_windows(sentence, count_tokens, max_tokens):
                    yield window, count_tokens(window), first
                    first = False
            first = False


def _word_windows(text, count_tokens, max_tokens):
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
    kept, size = [], 0
    for piece in reversed(pieces):
        if size + piece[1] > min(overlap_tokens, room):
            break
        kept.insert(0, piece)
        size += piece[1]
    return kept, size


def _join(pieces):
    out = []
    for i, (piece, _, starts_paragraph) in enumerate(pieces):
        if i:
            out.append("\n\n" if starts_paragraph else " ")
        out.append(piece)
    return "".join(out)
