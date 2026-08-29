import io
from docx import Document
from app.parsers import ParseError
from app.parsers.pdf_parser import ParseResult


def parse_docx(data: bytes) -> ParseResult:
    try:
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise ParseError(f"docx 无法解析：{e}") from e
    return ParseResult(text=text, parse_meta={"channel": "python-docx"})
