import pymupdf
import pytest

from sbcx.domain.parse.layout import clean_markdown
from sbcx.domain.parse.pdf_guard import check_pdf
from sbcx.errors import AppError


def make_pdf(text: str = "", pages: int = 1, password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(36, 36, 560, 800), text, fontsize=9)
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    return doc.tobytes(**kw)


SBC_TEXT = (
    "Summary of Benefits and Coverage: What this Plan Covers & What You Pay For Covered Services\n"
    "Important Questions Answers Why This Matters\n"
    "Common Medical Event Services You May Need What You Will Pay\n"
    "Primary care visit to treat an injury or illness $25 copay. Specialist visit $50 copay.\n" * 3
)


def code(data: bytes, **kw) -> str:
    with pytest.raises(AppError) as e:
        check_pdf(data, **kw)
    return e.value.code


def test_accepts_sbc():
    assert check_pdf(make_pdf(SBC_TEXT, pages=2)) == 2


def test_rejects_non_pdf():
    assert code(b"hello world") == "E_NOT_PDF"


def test_rejects_large():
    assert code(make_pdf(SBC_TEXT, pages=3), max_pages=2) == "E_TOO_LARGE"
    assert code(b"%PDF" + b"0" * (2 * 1024 * 1024), max_mb=1) == "E_TOO_LARGE"


def test_rejects_encrypted():
    assert code(make_pdf(SBC_TEXT, password="x")) == "E_ENCRYPTED"


def test_rejects_textless():
    assert code(make_pdf("")) == "E_NO_TEXT_LAYER"


def test_rejects_non_sbc():
    assert code(make_pdf("Quarterly sales report. " * 40)) == "E_NOT_SBC"


def test_clean_markdown_splits_run_together_tokens():
    md, fixes = clean_markdown(
        "|$25 copay,deductibledoes not apply|~~x~~", "$25 copay, deductible does not apply x"
    )
    assert "deductible does" in md and "~~" not in md and fixes == 1
