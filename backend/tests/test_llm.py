import json
import pytest
from pydantic import BaseModel
from app.llm import LLMClient, LLMError


class Out(BaseModel):
    ok: bool


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content, prompt_tokens=10, completion_tokens=5):
        self.choices = [FakeChoice(content)]
        self.usage = type("U", (), {"prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens})()


class FakeCompletions:
    """按预设脚本依次返回内容。"""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def create(self, model, messages, **kw):
        self.calls.append(messages)
        content = self.script.pop(0)
        if isinstance(content, Exception):
            raise content
        return FakeResponse(content)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeModels:
    """health_check 用的 models.list()，可注入异常。"""
    def __init__(self):
        self._error = None

    def set_error(self, err):
        self._error = err

    async def list(self):
        if self._error is not None:
            raise self._error
        return [{"id": "test-model"}]


class FakeAsyncOpenAI:
    def __init__(self, script, base_url=None, api_key=None, timeout=None):
        self.chat = FakeChat(FakeCompletions(script))
        self.base_url = base_url
        self.timeout = timeout
        self.models = FakeModels()


@pytest.fixture
def patch_openai(monkeypatch):
    def _patch(script):
        fake_cls = lambda **kw: FakeAsyncOpenAI(script, **kw)
        monkeypatch.setattr("app.llm.AsyncOpenAI", fake_cls)
        return fake_cls
    return _patch


async def test_chat_json_success_first_try(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    result = await client.chat_json("tester", "sys", "user", Out, task_id=None)
    assert result.ok is True


async def test_chat_json_retry_on_invalid_json(db_session, patch_openai):
    patch_openai(["不是JSON", json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    result = await client.chat_json("tester", "sys", "user", Out)
    assert result.ok is True
    # 第二次调用应附带上次 ValidationError 信息
    calls = client._client.chat.completions.calls
    assert len(calls) == 2
    second_user = calls[1][1]["content"]
    assert "上次输出未通过校验" in second_user
    assert "Invalid JSON" in second_user  # ValidationError 信息被拼进 prompt
    assert "user" in second_user  # 原始 prompt 保留


async def test_chat_json_exhausted_raises(db_session, patch_openai):
    patch_openai(["bad", "bad", "bad"])
    client = LLMClient(settings=None, db=db_session)
    with pytest.raises(LLMError) as exc_info:
        await client.chat_json("tester", "sys", "user", Out)
    assert exc_info.value.attempts == 3


async def test_writes_llm_log(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    await client.chat_json("jd_analyst", "sys", "user", Out, task_id=1)
    from app.models import LLMLog
    logs = db_session.query(LLMLog).all()
    assert len(logs) == 1
    assert logs[0].role == "jd_analyst"
    assert logs[0].prompt_tokens == 10


async def test_logs_each_attempt_on_exhaustion(db_session, patch_openai):
    patch_openai(["bad", "bad", "bad"])
    client = LLMClient(settings=None, db=db_session)
    with pytest.raises(LLMError):
        await client.chat_json("tester", "sys", "user", Out)
    from app.models import LLMLog
    logs = db_session.query(LLMLog).all()
    assert len(logs) == 3  # 每次尝试都写一条日志


async def test_network_error_counts_as_attempt_and_retries(db_session, patch_openai):
    patch_openai([RuntimeError("network"), json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    result = await client.chat_json("tester", "sys", "user", Out)
    assert result.ok is True
    assert len(client._client.chat.completions.calls) == 2  # 网络异常计入一次尝试


async def test_health_check_ok(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    assert await client.health_check() is True


async def test_health_check_false_on_error(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    client._client.models.set_error(RuntimeError("boom"))
    assert await client.health_check() is False


async def test_writes_llm_log_with_resume_id(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    await client.chat_json("extractor", "sys", "user", Out, task_id=1, resume_id=42)
    from app.models import LLMLog
    log = db_session.query(LLMLog).one()
    assert log.resume_id == 42


async def test_writes_llm_log_resume_id_defaults_none(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    await client.chat_json("jd_analyst", "sys", "user", Out, task_id=1)
    from app.models import LLMLog
    assert db_session.query(LLMLog).one().resume_id is None
