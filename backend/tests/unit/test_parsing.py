from datetime import date

from app.ingestion.parsing import parse_document
from tests.files import make_docx, make_pdf, sample


def test_markdown_keeps_heading_path_and_effective_date():
    doc = parse_document(sample("acme/refund-policy-2026.md"), "markdown")
    assert doc.effective_date == date(2026, 1, 1)
    eligibility = [b for b in doc.blocks if "7 days of purchase" in b.text]
    assert eligibility and eligibility[0].headings == ("Acme Refund Policy (2026)", "Eligibility")
    assert all(b.page is None for b in doc.blocks)


def test_pdf_keeps_page_numbers_and_numbered_headings():
    pdf = make_pdf(
        [
            ["1. Eligibility", "Refunds within 14 days of purchase."],
            ["2. Exclusions", "Gift cards are not refundable."],
        ]
    )
    doc = parse_document(pdf, "pdf")
    by_text = {b.text: b for b in doc.blocks}
    gift = next(b for t, b in by_text.items() if "Gift cards" in t)
    assert gift.page == 2
    assert gift.headings == ("2. Exclusions",)
    refund = next(b for t, b in by_text.items() if "14 days" in t)
    assert refund.page == 1


def test_docx_uses_heading_styles():
    data = make_docx(
        [
            ("title", "HR Handbook"),
            ("h1", "Leave"),
            ("h2", "Annual leave"),
            ("p", "Employees get 25 days."),
            ("h1", "Expenses"),
            ("p", "Submit receipts within 30 days."),
        ]
    )
    doc = parse_document(data, "docx")
    leave = next(b for b in doc.blocks if "25 days" in b.text)
    assert leave.headings == ("HR Handbook", "Leave", "Annual leave")
    expenses = next(b for b in doc.blocks if "receipts" in b.text)
    assert expenses.headings == ("HR Handbook", "Expenses")


def test_plain_text_is_one_section():
    doc = parse_document(b"Line one.\n\nLine two.", "text")
    assert [b.text for b in doc.blocks] == ["Line one.", "Line two."]
    assert all(b.headings == () for b in doc.blocks)
