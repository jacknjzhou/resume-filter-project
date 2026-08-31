import io
import json
from unittest.mock import patch, AsyncMock, Mock
from fastapi.testclient import TestClient
from app.models import Task, Resume, LLMLog


def _client():
    from app.main import app
    from app.db import get_db
    from tests.conftest import _testing_session  # 见 Step 3 说明
    app.dependency_overrides[get_db] = _testing_session
    return TestClient(app)


def _fake_llm_cls():
    fake = AsyncMock()
    async def health(self): return True
    return fake


def test_health_ok():
    with patch("app.routers.tasks.LLMClient") as MockLLM:
        MockLLM.return_value.health_check = AsyncMock(return_value=True)
        resp = _client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"llm": True}


def test_create_task_rejects_no_resume():
    c = _client()
    resp = c.post("/api/tasks", data={"jd_text": "JD"})
    assert resp.status_code == 422


def test_create_task_and_start_pipeline(tmp_path):
    c = _client()
    with patch("app.routers.tasks.LLMClient") as MockLLM, \
         patch("app.routers.tasks.run_task", new_callable=AsyncMock) as mock_run:
        MockLLM.return_value.health_check = AsyncMock(return_value=True)
        resp = c.post("/api/tasks",
                      data={"jd_text": "资深后端 JD", "pasted_texts": "张三 Go 工程师"},
                      )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    mock_run.assert_called_once_with(task_id)


def test_create_task_with_docx_jd_file_stores_extracted_text(db_session):
    """JD 上传 docx 时应提取文本入库，而不是存原始二进制（PG text 禁止 NUL 字节）。"""
    from docx import Document
    from app.models import Task

    doc = Document()
    doc.add_paragraph("资深 Go 后端工程师 JD")
    buf = io.BytesIO()
    doc.save(buf)

    c = _client()
    with patch("app.routers.tasks.LLMClient") as MockLLM, \
         patch("app.routers.tasks.run_task", new_callable=AsyncMock):
        MockLLM.return_value.health_check = AsyncMock(return_value=True)
        resp = c.post(
            "/api/tasks",
            data={"pasted_texts": "张三 Go 工程师"},
            files={"jd_file": ("jd.docx", buf.getvalue(),
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 200, resp.text
    task = db_session.get(Task, resp.json()["task_id"])
    assert "资深 Go 后端工程师 JD" in task.jd_raw
    assert "\x00" not in task.jd_raw


def test_create_task_with_scanned_jd_file_rejected(db_session):
    """扫描件/图片型 PDF 的 JD 无法同步提取文本，应返回 422 提示改用文本。"""
    from app.parsers.pdf_parser import ParseResult

    c = _client()
    with patch("app.routers.tasks.LLMClient") as MockLLM, \
         patch("app.routers.tasks.parse_resume_sync",
               return_value=ParseResult(text="", needs_image_channel=True)):
        MockLLM.return_value.health_check = AsyncMock(return_value=True)
        resp = c.post(
            "/api/tasks",
            data={"pasted_texts": "张三 Go 工程师"},
            files={"jd_file": ("jd.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert resp.status_code == 422


def test_create_task_with_corrupt_jd_file_rejected(db_session):
    """损坏的 JD 文件解析失败应返回 422，而不是 500。"""
    from app.parsers import ParseError

    c = _client()
    with patch("app.routers.tasks.LLMClient") as MockLLM, \
         patch("app.routers.tasks.parse_resume_sync",
               side_effect=ParseError("docx 无法解析")):
        MockLLM.return_value.health_check = AsyncMock(return_value=True)
        resp = c.post(
            "/api/tasks",
            data={"pasted_texts": "张三 Go 工程师"},
            files={"jd_file": ("jd.docx", b"not a docx",
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 422


def test_get_task_detail(db_session, seed_task):
    c = _client()
    resp = c.get(f"/api/tasks/{seed_task.id}")
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["resumes"]) == 2


def test_list_tasks_basic(db_session, seed_task):
    c = _client()
    resp = c.get("/api/tasks")
    assert resp.status_code == 200
    body = resp.json()
    item = next(i for i in body["items"] if i["task_id"] == seed_task.id)
    assert item["status"] == "pending"
    assert item["resume_count"] == 2
    assert item["created_at"]
    assert item["grades"] == {}


def test_list_tasks_pagination_and_status_filter(db_session, seed_task):
    c = _client()
    body = c.get("/api/tasks?page=1&page_size=1").json()
    assert len(body["items"]) == 1 and body["page_size"] == 1
    body = c.get("/api/tasks?status=done").json()
    assert all(i["status"] == "done" for i in body["items"]) and body["items"] == []


def test_list_tasks_llm_and_grade_stats(db_session, seed_task):
    r1 = seed_task.resumes[0]
    db_session.add_all([
        LLMLog(task_id=seed_task.id, role="jd_analyst",
               prompt_tokens=100, completion_tokens=50, duration_ms=1000),
        LLMLog(task_id=seed_task.id, resume_id=r1.id, role="extractor",
               prompt_tokens=200, completion_tokens=80, duration_ms=2000),
    ])
    r1.final_grade = "A"
    db_session.commit()
    c = _client()
    item = next(i for i in c.get("/api/tasks").json()["items"]
                if i["task_id"] == seed_task.id)
    assert item["llm"] == {"prompt_tokens": 300, "completion_tokens": 130,
                           "duration_ms": 3000}
    assert item["grades"] == {"A": 1}


def test_get_task_detail_with_stage_and_llm_info(db_session, seed_task):
    r1 = seed_task.resumes[0]
    db_session.add_all([
        LLMLog(task_id=seed_task.id, role="jd_analyst",
               prompt_tokens=100, completion_tokens=50, duration_ms=1000),
        LLMLog(task_id=seed_task.id, resume_id=r1.id, role="extractor",
               prompt_tokens=200, completion_tokens=80, duration_ms=2000),
    ])
    db_session.commit()
    c = _client()
    body = c.get(f"/api/tasks/{seed_task.id}").json()
    # 旧字段保持兼容（TaskProgress/TaskResult 依赖）
    assert body["jd_parsed"] is None and body["summary_report"] is None
    assert len(body["resumes"]) == 2
    # 新字段
    assert body["stage_timeline"] == []
    assert body["llm_usage"] == {"prompt_tokens": 300, "completion_tokens": 130,
                                 "duration_ms": 3000, "calls": 2}
    assert len(body["task_llm_calls"]) == 1
    assert body["task_llm_calls"][0]["role"] == "jd_analyst"
    r = body["resumes"][0]
    assert r["source_type"] == "text" and r["error_message"] is None
    assert r["stage_timeline"] == []
    assert len(r["llm_calls"]) == 1 and r["llm_calls"][0]["role"] == "extractor"


def test_get_resume_report(db_session, seed_evaluated_resume):
    c = _client()
    resp = c.get(f"/api/resumes/{seed_evaluated_resume.id}/report")
    body = resp.json()
    assert body["profile"]["name"] == "张三"
    assert body["evaluation"]["skill_match"] == 80
    assert len(body["evaluation"]["interview_questions"]) > 0


def test_export_markdown(db_session, seed_evaluated_resume):
    c = _client()
    resp = c.get(f"/api/tasks/{seed_evaluated_resume.task_id}/export?format=md")
    assert resp.status_code == 200
    assert "排名" in resp.text


async def test_sse_stream(db_session, seed_task):
    # starlette(1.6)/httpx(0.27) 的 TestClient 会缓冲完整响应体，无法对无限 SSE 流
    # 做 HTTP 级断言。这里 mock event_bus，预置一个含 task_done 的 queue，
    # 直接迭代 StreamingResponse.body_iterator 验证：
    # 1) 事件以 `data: {json}\n\n` 序列化输出；
    # 2) task_done 后 break 终止生成器；
    # 3) finally 中 event_bus.unsubscribe(task_id, q) 被调用。
    import asyncio
    from app.routers import tasks as tasks_mod

    q: asyncio.Queue = asyncio.Queue()
    q.put_nowait({"type": "task_done"})
    fake_bus = Mock()
    fake_bus.subscribe.return_value = q

    with patch.object(tasks_mod, "event_bus", fake_bus):
        resp = await tasks_mod.task_events(seed_task.id, db_session)
        assert resp.status_code == 200
        assert resp.media_type.startswith("text/event-stream")
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        assert chunks, "SSE 生成器应至少产出一个 chunk"
        assert any("task_done" in c for c in chunks), \
            f"应包含 task_done 事件，实际 chunks={chunks!r}"
        fake_bus.unsubscribe.assert_called_once_with(seed_task.id, q)


async def test_sse_finished_task_returns_terminal_event(db_session, seed_task):
    """任务已终态时，SSE 应立即下发结束事件而不是永久挂起。"""
    import asyncio
    from app.routers import tasks as tasks_mod

    seed_task.status = "done"
    db_session.commit()

    q: asyncio.Queue = asyncio.Queue()
    fake_bus = Mock()
    fake_bus.subscribe.return_value = q

    with patch.object(tasks_mod, "event_bus", fake_bus):
        resp = await tasks_mod.task_events(seed_task.id, db_session)
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        assert any("task_done" in c for c in chunks)
        # 不等待任何事件，直接结束
        assert q.empty()
        fake_bus.unsubscribe.assert_called_once_with(seed_task.id, q)


async def test_sse_task_not_found(db_session):
    from app.routers import tasks as tasks_mod
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        await tasks_mod.task_events(99999, db_session)
    assert exc_info.value.status_code == 404
