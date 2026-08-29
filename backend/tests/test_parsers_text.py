import io
import fitz  # PyMuPDF，测试里用它生成样例 PDF
from docx import Document
import pytest
from app.parsers import parse_resume_sync, parse_text, ParseError
from app.parsers.pdf_parser import parse_pdf
from app.parsers.docx_parser import parse_docx


def _make_pdf(words: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 520, 800), words, fontname="china-s")
    return doc.tobytes()


def _make_docx(text: str) -> bytes:
    d = Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_parse_pdf_text():
    data = _make_pdf("张三 后端工程师 Go 微服务 经验丰富 " * 20)
    r = parse_pdf(data)
    assert not r.needs_image_channel
    assert "张三" in r.text
    assert r.parse_meta["channel"] == "pymupdf"


def test_parse_pdf_scanned_detection():
    r = parse_pdf(_make_pdf("短文本"))  # < 200 字符
    assert r.needs_image_channel
    assert r.text == "短文本"


def test_parse_pdf_corrupted():
    with pytest.raises(ParseError):
        parse_pdf(b"%PDF-not-a-real-pdf")


def test_parse_docx():
    r = parse_docx(_make_docx("李四 Python 工程师"))
    assert "李四" in r.text


def test_parse_text():
    r = parse_text("纯文本简历")
    assert r.text == "纯文本简历"
    assert r.parse_meta["channel"] == "plain_text"


def test_dispatch_by_filename():
    r = parse_resume_sync("resume.docx", _make_docx("内容"))
    assert "内容" in r.text
    r2 = parse_resume_sync("notes.txt", "纯文本简历".encode("utf-8"))
    assert "纯文本简历" in r2.text
