from __future__ import annotations


class ParseError(Exception):
    """简历文件损坏/加密/无法解析。"""


def parse_text(text: str) -> ParseResult:
    from app.parsers.pdf_parser import ParseResult
    return ParseResult(text=text, parse_meta={"channel": "plain_text"})


def parse_resume_sync(filename: str, data: bytes):
    """按文件类型分发，返回 ParseResult。图片类型由异步管线单独处理。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        from app.parsers.pdf_parser import parse_pdf
        return parse_pdf(data)
    if lower.endswith(".docx"):
        from app.parsers.docx_parser import parse_docx
        return parse_docx(data)
    # 其他一律按 utf-8 文本兜底
    return parse_text(data.decode("utf-8", errors="replace"))
