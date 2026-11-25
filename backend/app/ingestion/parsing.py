"""Parse PDF/DOCX/TXT/MD into text blocks that keep page numbers and the
heading path. Document text is untrusted data: it is only ever stored,
chunked and embedded, never interpreted."""

import io
import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Block:
    text: str
    page: int | None
    headings: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDocument:
    blocks: list[Block]
    effective_date: date | None


_EFFECTIVE = re.compile(
    r"effective(?:\s+date|\s+from|\s+as\s+of)?\s*[:\-]?\s*(\d{4})-(\d{2})-(\d{2})", re.IGNORECASE
)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# Conservative PDF heading heuristic: "1.", "2.3", "Section 4" style lines.
_PDF_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|section\s+\d+[.:]?)\s+\S.{0,80}$", re.IGNORECASE)


def _effective_date(text: str) -> date | None:
    m = _EFFECTIVE.search(text[:5000])
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _set_heading(stack: list[str], level: int, title: str) -> list[str]:
    return [*stack[: level - 1], title]


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    headings: list[str] = []
    buf: list[str] = []
    in_code = False

    def flush() -> None:
        for para in _paragraphs("\n".join(buf)):
            blocks.append(Block(para, None, tuple(headings)))
        buf.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _MD_HEADING.match(line)
        if m:
            flush()
            headings = _set_heading(headings, len(m.group(1)), m.group(2).strip())
        else:
            buf.append(line)
    flush()
    return blocks


def parse_text(text: str) -> list[Block]:
    return [Block(p, None, ()) for p in _paragraphs(text)]


def parse_pdf(data: bytes) -> list[Block]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    blocks: list[Block] = []
    headings: tuple[str, ...] = ()
    for page_no, page in enumerate(reader.pages, start=1):
        buf: list[str] = []
        for line in (page.extract_text() or "").splitlines():
            stripped = line.strip()
            is_heading = (
                bool(stripped) and _PDF_HEADING.match(stripped) and not stripped.endswith(".")
            )
            if is_heading:  # closes the paragraphs collected under the previous heading
                blocks += [Block(p, page_no, headings) for p in _paragraphs("\n".join(buf))]
                buf = []
                headings = (stripped,)
            else:
                buf.append(line)
        blocks += [Block(p, page_no, headings) for p in _paragraphs("\n".join(buf))]
    return blocks


def parse_docx(data: bytes) -> list[Block]:
    from docx import Document

    doc = Document(io.BytesIO(data))
    blocks: list[Block] = []
    headings: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "") if para.style is not None else ""
        if style == "Title":
            headings = [text]
        elif style.startswith("Heading ") and style[8:].isdigit():
            # Title (if any) stays as level 0 above Heading 1.
            offset = 1 if headings and _has_title(doc, headings[0]) else 0
            headings = _set_heading(headings, int(style[8:]) + offset, text)
        else:
            blocks.append(Block(text, None, tuple(headings)))
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(Block(" | ".join(cells), None, tuple(headings)))
    return blocks


def _has_title(doc, text: str) -> bool:
    return any(
        p.style is not None and p.style.name == "Title" and p.text.strip() == text
        for p in doc.paragraphs
    )


def parse_document(data: bytes, parser: str) -> ParsedDocument:
    if parser == "pdf":
        blocks = parse_pdf(data)
    elif parser == "docx":
        blocks = parse_docx(data)
    elif parser == "markdown":
        blocks = parse_markdown(data.decode("utf-8"))
    elif parser == "text":
        blocks = parse_text(data.decode("utf-8"))
    else:
        raise ValueError(f"unknown parser {parser!r}")
    head = "\n".join(b.text for b in blocks[:20])
    return ParsedDocument(blocks=blocks, effective_date=_effective_date(head))
