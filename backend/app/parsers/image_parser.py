import base64
import re
from functools import lru_cache
import httpx
from app.parsers import ParseError
from app.parsers.pdf_parser import ParseResult

MIN_TEXT_CHARS = 50
GARBLED_MAX_RATIO = 0.30
# 可读字符：中文、英文、数字、常见中英文标点与空白
_READABLE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\s，。、；：""''（）【】《》,.:;()·/&%+-]")


def ocr_confidence(lines: list[dict]) -> float:
    if not lines:
        return 0.0
    return sum(l.get("confidence", 0.0) for l in lines) / len(lines)


def looks_garbled(text: str) -> bool:
    if not text:
        return True
    readable = len(_READABLE.findall(text))
    return (readable / len(text)) < (1 - GARBLED_MAX_RATIO)


class OCRClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def recognize(self, image: bytes) -> list[dict]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.base_url, files={"file": image})
            resp.raise_for_status()
            return resp.json().get("lines", [])


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


async def _vlm_transcribe(image: bytes, model: str, prompt: str) -> str:
    """VLM 图片转录。真实实现走 LLMClient 的 OpenAI 兼容接口（chat.completions，image_url 传入 base64）。

    为便于测试，此函数可被 monkeypatch 替换；生产实现见 Task 8 装配。
    """
    raise NotImplementedError


async def _correct(llm, text: str) -> str:
    from app.schemas import TextCorrection
    result = await llm.chat_json(
        role="text_corrector",
        system_prompt=_load_prompt("text_corrector"),
        user_prompt=f"OCR 文本：\n{text}",
        schema=TextCorrection,
    )
    return result.corrected


def _ocr_ok(lines: list[dict], settings) -> bool:
    text = "\n".join(l.get("text", "") for l in lines)
    return (ocr_confidence(lines) >= settings.ocr_confidence_threshold
            and len(text.strip()) >= MIN_TEXT_CHARS
            and not looks_garbled(text))


async def parse_image(filename: str, data: bytes, llm, settings, vlm_transcribe=None) -> ParseResult:
    """双通道：OCR 主通道 → VLM 兜底 → LLM 校正。

    `vlm_transcribe` 是可选的 async 可调用对象 ``(image, model, prompt) -> str``。
    - 生产路径：runner 显式注入一个绑定到当前协程 llm 的闭包。
    - 测试路径：不传入，回退到模块级 ``_vlm_transcribe``（可被 monkeypatch）。
    """
    ocr_lines: list[dict] = []
    ocr_error = None
    try:
        ocr_lines = await OCRClient(settings.ocr_base_url).recognize(data)
    except Exception as e:
        ocr_error = str(e)

    ocr_text = "\n".join(l.get("text", "") for l in ocr_lines)
    confidence = ocr_confidence(ocr_lines)

    if _ocr_ok(ocr_lines, settings):
        corrected = await _correct(llm, ocr_text)
        return ParseResult(
            text=corrected,
            parse_meta={"channel": "paddleocr", "ocr_confidence": confidence,
                        "ocr_raw_text": ocr_text},
        )

    # 兜底通道
    if not settings.llm_vlm_model:
        raise ParseError(f"OCR 质量不合格且未配置 VLM 兜底（confidence={confidence:.2f}，"
                         f"ocr_error={ocr_error}）")
    import app.parsers.image_parser as _self
    transcriber = vlm_transcribe or _self._vlm_transcribe
    try:
        vlm_text = await transcriber(data, settings.llm_vlm_model,
                                     _load_prompt("ocr_fallback"))
        if not vlm_text.strip():
            raise ParseError("VLM 返回空文本")
        corrected = await _correct(llm, vlm_text)
        return ParseResult(
            text=corrected,
            parse_meta={"channel": "vlm_fallback", "ocr_confidence": confidence,
                        "ocr_raw_text": vlm_text},
        )
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"VLM 兜底失败：{e}") from e
