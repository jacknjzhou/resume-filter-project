"""生成端到端验收样例简历。运行：python make_samples.py"""
import io
import fitz
from docx import Document
from pathlib import Path

OUT = Path(__file__).parent
TEXT_OK = ("张三，本科，5 年后端开发经验，精通 Go 与 Python，"
           "负责过日活百万的微服务系统，稳定性高。") * 15
TEXT_SHORT = "王五，大专学历，1 年前端经验。"


def make_pdf(name, text):
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in text.split("。"):
        if line.strip():
            page.insert_text((72, y), line + "。", fontname="china-s")
            y += 20
    doc.save(OUT / name)


def make_docx(name, text):
    d = Document()
    d.add_paragraph(text)
    d.save(OUT / name)


make_pdf("张三_后端.pdf", TEXT_OK)
make_docx("李四_后端.docx", TEXT_OK.replace("张三", "李四"))
(OUT / "王五_前端.txt").write_text(TEXT_SHORT, encoding="utf-8")
print("样例已生成到 samples/")
