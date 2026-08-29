import json
import pytest
from types import SimpleNamespace
from app.parsers.image_parser import OCRClient, ocr_confidence, looks_garbled, parse_image
from app.llm import LLMError
from app.parsers import ParseError


# ---- 纯函数 ----

def test_ocr_confidence():
    lines = [{"text": "a", "confidence": 0.9}, {"text": "b", "confidence": 0.8}]
    assert ocr_confidence(lines) == pytest.approx(0.85)
    assert ocr_confidence([]) == 0.0


def test_looks_garbled():
    assert not looks_garbled("张三，后端工程师，5年经验 Go/Python。")
    assert looks_garbled("¥§ÆØ¥§ÆØ¥§ÆØ¥§ÆØ")


# ---- OCRClient ----

class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload
    def raise_for_status(self):
        pass


async def test_ocr_client_recognize(monkeypatch):
    captured = {}

    class FakeHTTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return None
        async def post(self, url, files=None, **kw):
            captured["url"] = url
            return FakeResp({"lines": [{"text": "你好", "confidence": 0.95}]})

    monkeypatch.setattr("app.parsers.image_parser.httpx.AsyncClient", lambda **kw: FakeHTTP())
    client = OCRClient("http://fake-ocr")
    lines = await client.recognize(b"imgbytes")
    assert lines[0]["text"] == "你好"
    assert captured["url"] == "http://fake-ocr"


# ---- parse_image 双通道 ----

class SettingsFake:
    ocr_confidence_threshold = 0.85
    llm_vlm_model = ""
    ocr_base_url = "http://fake-ocr"


class LLMFake:
    """模拟 chat_json：记录 role，返回带 corrected 字段的对象。"""
    def __init__(self, fallback_raises=False):
        self.roles = []
        self.fallback_raises = fallback_raises

    async def chat_json(self, role, system_prompt, user_prompt, schema, **kw):
        self.roles.append(role)
        if role == "ocr_fallback" and self.fallback_raises:
            raise LLMError("vlm down", attempts=3)
        # 返回满足 schema 的对象：text_corrector 输出 {"corrected": ...}
        return schema.model_validate({"corrected": "校正后的文本内容"})


async def _noop_vlm_factory(monkeypatch, impl):
    """替换 VLM 图片转录函数。"""
    monkeypatch.setattr("app.parsers.image_parser._vlm_transcribe", impl)


async def test_parse_image_good_ocr_uses_correction_only(monkeypatch):
    async def fake_recognize(self, image):
        return [{"text": "张三 后端工程师 " * 10, "confidence": 0.95}]
    monkeypatch.setattr(OCRClient, "recognize", fake_recognize)
    llm = LLMFake()
    result = await parse_image("a.png", b"img", llm, SettingsFake())
    assert result.parse_meta["channel"] == "paddleocr"
    assert llm.roles == ["text_corrector"]  # 不触发 VLM
    assert result.text == "校正后的文本内容"
    assert "ocr_raw_text" in result.parse_meta


async def test_parse_image_low_confidence_falls_back_to_vlm(monkeypatch):
    async def fake_recognize(self, image):
        return [{"text": "乱", "confidence": 0.3}]
    monkeypatch.setattr(OCRClient, "recognize", fake_recognize)
    SettingsFake.llm_vlm_model = "qwen-vl"

    async def fake_vlm(image, model, prompt):
        return "VLM 转录的完整简历文本内容"
    await _noop_vlm_factory(monkeypatch, fake_vlm)

    llm = LLMFake()
    result = await parse_image("a.png", b"img", llm, SettingsFake())
    assert result.parse_meta["channel"] == "vlm_fallback"
    assert result.parse_meta["ocr_confidence"] == pytest.approx(0.3)
    SettingsFake.llm_vlm_model = ""  # 还原，避免污染其他测试


async def test_parse_image_no_vlm_configured_raises(monkeypatch):
    async def fake_recognize(self, image):
        return [{"text": "乱", "confidence": 0.3}]
    monkeypatch.setattr(OCRClient, "recognize", fake_recognize)
    llm = LLMFake()
    with pytest.raises(ParseError):
        await parse_image("a.png", b"img", llm, SettingsFake())


async def test_parse_image_vlm_fails_raises(monkeypatch):
    async def fake_recognize(self, image):
        return [{"text": "乱", "confidence": 0.3}]
    monkeypatch.setattr(OCRClient, "recognize", fake_recognize)
    SettingsFake.llm_vlm_model = "qwen-vl"

    async def fake_vlm(image, model, prompt):
        raise RuntimeError("vlm down")
    await _noop_vlm_factory(monkeypatch, fake_vlm)
    llm = LLMFake(fallback_raises=True)
    with pytest.raises(ParseError):
        await parse_image("a.png", b"img", llm, SettingsFake())
    SettingsFake.llm_vlm_model = ""
