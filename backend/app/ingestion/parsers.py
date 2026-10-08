# File bytes -> list[Section] (text + optional page number). One registered
# function per extension (.pdf, .docx, .txt/.md, .csv); unknown types raise
# ParseError. Called by ingestion/service.py at the start of every upload.
import csv
import io
import os
import re
import zipfile
from dataclasses import dataclass

# zipfile never inflates past the declared sizes, so their sum bounds what python-docx will load
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024


@dataclass
class Section:
    # parsers return whole pages/blocks; chunking happens later in the service
    text: str
    page: int | None = None


class ParseError(Exception):
    # one error type across all formats, so callers don't need per-parser excepts
    pass


_PARSERS = {}


def register(*extensions):
    """Decorator: add a parser function to _PARSERS for the given extensions."""
    # parsers self-register by extension; supporting a new format is one decorator
    def decorator(func):
        """Map each extension to the decorated parser and return it unchanged."""
        for ext in extensions:
            _PARSERS[ext.lower()] = func
        return func

    return decorator


def supported_extensions():
    """The extensions uploads accept (shown in error messages and the admin page)."""
    return sorted(_PARSERS)


def parse(filename, data):
    """Dispatch to the right parser by extension; ParseError on unsupported/failed."""
    ext = os.path.splitext(filename)[1].lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ParseError(
            f"Unsupported file type '{ext or filename}'. Supported: {', '.join(supported_extensions())}."
        )
    try:
        sections = parser(data)
    except ParseError:
        raise  # our own errors already carry a user-safe message
    except Exception as exc:
        raise ParseError(f"Couldn't read {filename}: {exc}") from exc
    # parsers can yield empty sections (a blank PDF page); drop them
    return [s for s in sections if s.text.strip()]


def _clean(text):
    """Normalize the whitespace mess extraction produces, before chunking."""
    # normalise the whitespace mess PDF/DOCX extraction produces: nulls, CRLF,
    # words hyphenated across line breaks, runs of spaces, and page-break blank lines
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@register(".pdf")
def parse_pdf(data):
    """Extract one Section per page — the page numbers power citation labels."""
    # lazy import: the PDF dependency is only loaded when a PDF actually arrives
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    # many "encrypted" PDFs just have an empty owner password — try that before failing
    if reader.is_encrypted and not reader.decrypt(""):
        raise ParseError("This PDF is password-protected.")
    # page numbers are kept so answers can cite "Holiday Policy, page 3"
    return [Section(_clean(page.extract_text() or ""), page=number)
            for number, page in enumerate(reader.pages, start=1)]


@register(".docx")
def parse_docx(data):
    """Extract a docx into one Section; tables become 'cell | cell' lines."""
    from docx import Document
    from docx.table import Table

    # a docx is a zip; a tiny upload can unpack to gigabytes, so check before parsing
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
            raise ParseError("This DOCX expands to more than 50 MB, so it was not processed.")

    blocks = []
    # iter_inner_content walks paragraphs and tables in document order, so the
    # text comes out in the order a reader would see it
    for item in Document(io.BytesIO(data)).iter_inner_content():
        if isinstance(item, Table):
            # tables become "cell | cell" lines, which chunk and embed far better
            # than python-docx's raw cell order
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


def _decode(data):
    """Best-effort text decode shared by the text and CSV parsers."""
    # shared by text and CSV: UTF-8 first (BOM stripped), then Windows exports;
    # latin-1 accepts any byte, so it's the last resort
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


@register(".txt", ".md", ".markdown")
def parse_text(data):
    """Plain text and Markdown decode into a single Section."""
    return [Section(_clean(_decode(data)))]


@register(".csv")
def parse_csv(data):
    """Turn each CSV row into a 'Header: value' paragraph the chunker won't split."""
    # rows become "Header: value; Header: value" so each chunk carries its column names and
    # still makes sense to the embedder and the LLM on its own
    rows = csv.reader(io.StringIO(_decode(data)))
    header = [name.strip() for name in next(rows, [])]
    lines = []
    for row in rows:
        # blank cells and unnamed columns add tokens without meaning
        cells = [f"{name}: {value.strip()}" for name, value in zip(header, row)
                 if name and value.strip()]
        if cells:
            lines.append("; ".join(cells))
    # one row per paragraph so the chunker never splits a record
    return [Section(_clean("\n\n".join(lines)))]
