import pytest

from app.documents.validation import UploadError, safe_filename, validate_upload
from tests.files import make_docx, make_pdf

MAX = 1024 * 1024


@pytest.mark.parametrize(
    "name,data,parser",
    [
        ("policy.pdf", make_pdf([["Hello"]]), "pdf"),
        ("policy.docx", make_docx([("p", "Hello")]), "docx"),
        ("notes.txt", b"plain text", "text"),
        ("README.MD", "# Título\n".encode(), "markdown"),
    ],
)
def test_accepts_supported_types(name, data, parser):
    assert validate_upload(name, data, MAX).parser == parser


@pytest.mark.parametrize(
    "name,data,status",
    [
        ("tool.exe", b"MZ\x90\x00", 415),
        ("fake.pdf", b"not a pdf at all", 415),
        ("fake.docx", b"PK\x03\x04 but not a docx", 415),
        ("binary.txt", b"abc\x00def", 415),
        ("latin1.txt", "caf\xe9".encode("latin-1"), 415),
        ("noext", b"hello", 415),
        ("empty.txt", b"", 400),
        ("big.txt", b"x" * (MAX + 1), 413),
    ],
)
def test_rejects_bad_uploads(name, data, status):
    with pytest.raises(UploadError) as exc:
        validate_upload(name, data, MAX)
    assert exc.value.status_code == status


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\Refund Policy.pdf", "Refund_Policy.pdf"),
        ("a" * 300 + ".md", "a" * 200 + ".md"),
        ("..", "file"),
        ("\x00evil.txt", "evil.txt"),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected
