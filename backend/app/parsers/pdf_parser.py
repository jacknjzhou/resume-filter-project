from dataclasses import dataclass, field
import fitz
from app.parsers import ParseError


@dataclass
class ParseResult:
    text: str
    parse_meta: dict = field(default_factory=dict)
    needs_image_channel: bool = False


SCANNED_MIN_CHARS = 200


def parse_pdf(data: bytes) -> ParseResult:
    try:
        # with 上下文：解析中途抛异常也能保证文档关闭，避免资源泄漏
        with fitz.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as e:
        raise ParseError(f"PDF 无法解析：{e}") from e
    meta = {"channel": "pymupdf", "char_count": len(text)}
    if len(text.strip()) < SCANNED_MIN_CHARS:
        return ParseResult(text=text.strip(), parse_meta=meta, needs_image_channel=True)
    return ParseResult(text=text.strip(), parse_meta=meta)
