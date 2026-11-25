"""Upload validation: size, extension and content sniffing (never trust the
client's filename or Content-Type alone)."""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath


class UploadError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class FileKind:
    extension: str
    mime_type: str
    parser: str  # pdf | docx | text | markdown


_KINDS = {
    ".pdf": FileKind(".pdf", "application/pdf", "pdf"),
    ".docx": FileKind(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    ".txt": FileKind(".txt", "text/plain", "text"),
    ".md": FileKind(".md", "text/markdown", "markdown"),
    ".markdown": FileKind(".markdown", "text/markdown", "markdown"),
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """Basename only, conservative charset, bounded length."""
    base = PureWindowsPath(PurePosixPath(name.replace("\x00", "")).name).name
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = _UNSAFE.sub("_", stem).strip("._")[:200]
    ext = _UNSAFE.sub("", ext)[:10]
    if not stem:
        return "file"
    return f"{stem}.{ext}" if ext else stem


def _looks_like_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "word/document.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def validate_upload(filename: str, data: bytes, max_bytes: int) -> FileKind:
    if len(data) > max_bytes:
        raise UploadError(413, f"file exceeds the {max_bytes} byte limit")
    if not data:
        raise UploadError(400, "file is empty")
    ext = PurePosixPath(safe_filename(filename)).suffix.lower()
    kind = _KINDS.get(ext)
    if kind is None:
        raise UploadError(415, "unsupported file type; use PDF, DOCX, TXT or MD")
    ok = {
        "pdf": lambda: data.startswith(b"%PDF-"),
        "docx": lambda: _looks_like_docx(data),
        "text": lambda: _is_text(data),
        "markdown": lambda: _is_text(data),
    }[kind.parser]()
    if not ok:
        raise UploadError(415, f"file content does not match {ext}")
    return kind
