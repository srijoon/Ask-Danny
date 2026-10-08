import io
import os
import re
from dataclasses import dataclass


@dataclass
class Section:
    text: str
    page: int | None = None


class ParseError(Exception):
    pass


_PARSERS = {}


def register(*extensions):
    def decorator(func):
        for ext in extensions:
            _PARSERS[ext.lower()] = func
        return func

    return decorator


def supported_extensions():
    return sorted(_PARSERS)


def parse(filename, data):
    ext = os.path.splitext(filename)[1].lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ParseError(
            f"Unsupported file type '{ext or filename}'. Supported: {', '.join(supported_extensions())}."
        )
    try:
        sections = parser(data)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Couldn't read {filename}: {exc}") from exc
    return [s for s in sections if s.text.strip()]


def _clean(text):
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@register(".pdf")
def parse_pdf(data):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ParseError("This PDF is password-protected.")
    return [Section(_clean(page.extract_text() or ""), page=number)
            for number, page in enumerate(reader.pages, start=1)]


@register(".docx")
def parse_docx(data):
    from docx import Document
    from docx.table import Table

    blocks = []
    for item in Document(io.BytesIO(data)).iter_inner_content():
        if isinstance(item, Table):
            rows = []
            for row in item.rows:
                cells = []
                for cell in row.cells:
                    value = cell.text.strip()
                    if value and (not cells or cells[-1] != value):  # merged cells repeat
                        cells.append(value)
                if cells:
                    rows.append(" | ".join(cells))
            blocks.append("\n".join(rows))
        else:
            blocks.append(item.text)
    return [Section(_clean("\n\n".join(b for b in blocks if b.strip())))]


@register(".txt", ".md", ".markdown")
def parse_text(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return [Section(_clean(data.decode(encoding)))]
        except UnicodeDecodeError:
            continue
    return [Section(_clean(data.decode("latin-1")))]
