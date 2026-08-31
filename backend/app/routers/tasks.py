import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse, Response, PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.llm import LLMClient
from app.models import Task, Resume, LLMLog
from app.parsers import ParseError, parse_resume_sync
from app.pipeline.events import event_bus
from app.pipeline.runner import run_task, IMAGE_EXTS

router = APIRouter(prefix="/api")
settings = get_settings()
MAX_RESUMES = 10

# 持有后台任务引用，防止 asyncio.create_task 创建的任务被垃圾回收
_background_tasks: set[asyncio.Task] = set()


def _safe_name(filename: str) -> str:
    """仅保留文件名部分，防止路径穿越（如 ../../evil）。"""
    return Path(filename).name or "upload"


def _source_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    return "text"


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    ok = await LLMClient(settings, db).health_check()
    return {"llm": ok}


@router.get("/tasks")
def list_tasks(page: int = 1, page_size: int = 20, status: str | None = None,
               db: Session = Depends(get_db)):
    page, page_size = max(1, page), min(max(1, page_size), 100)
    q = db.query(Task).order_by(Task.id.desc())
    if status:
        q = q.filter(Task.status == status)
    total = q.count()
    tasks = q.offset((page - 1) * page_size).limit(page_size).all()
    ids = [t.id for t in tasks]

    resume_counts: dict[int, int] = {}
    if ids:
        for tid, cnt in (db.query(Resume.task_id, func.count())
                         .filter(Resume.task_id.in_(ids))
                         .group_by(Resume.task_id)):
            resume_counts[tid] = cnt

    # 分档统计：已评级按等级分桶；终态（done/failed）但未评级计「未定级」；
    # pending/处理中的简历不计入，避免任务刚开始时就出现大量「未定级」
    grades: dict[int, dict] = {}
    if ids:
        for tid, grade, cnt in (db.query(Resume.task_id, Resume.final_grade, func.count())
                                .filter(Resume.task_id.in_(ids),
                                        Resume.final_grade.isnot(None))
                                .group_by(Resume.task_id, Resume.final_grade)):
            grades.setdefault(tid, {})[grade] = cnt
        for tid, cnt in (db.query(Resume.task_id, func.count())
                         .filter(Resume.task_id.in_(ids),
                                 Resume.final_grade.is_(None),
                                 Resume.status.in_(("done", "failed")))
                         .group_by(Resume.task_id)):
            grades.setdefault(tid, {})["未定级"] = cnt

    llm: dict[int, dict] = {}
    if ids:
        for tid, pt, ct, dur in (db.query(LLMLog.task_id,
                                          func.coalesce(func.sum(LLMLog.prompt_tokens), 0),
                                          func.coalesce(func.sum(LLMLog.completion_tokens), 0),
                                          func.coalesce(func.sum(LLMLog.duration_ms), 0))
                                 .filter(LLMLog.task_id.in_(ids))
                                 .group_by(LLMLog.task_id)):
            llm[tid] = {"prompt_tokens": pt, "completion_tokens": ct, "duration_ms": dur}

    items = [{
        "task_id": t.id, "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "resume_count": resume_counts.get(t.id, 0),
        "grades": grades.get(t.id, {}),
        "llm": llm.get(t.id),
    } for t in tasks]
    return {"total": total, "page": page,
            "page_size": page_size, "items": items}


@router.post("/tasks")
async def create_task(
    jd_file: UploadFile | None = File(None),
    jd_text: str | None = Form(None),
    resumes: list[UploadFile] | None = File(None),
    pasted_texts: list[str] | str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not jd_file and not (jd_text and jd_text.strip()):
        raise HTTPException(422, "必须提供 JD 文件或 JD 文本")

    resume_files = resumes or []
    if pasted_texts is None:
        pasted_list = []
    elif isinstance(pasted_texts, str):
        pasted_list = [pasted_texts]
    else:
        pasted_list = pasted_texts

    n = len([r for r in resume_files if r.filename]) + len([t for t in pasted_list if t and t.strip()])
    if n < 1:
        raise HTTPException(422, "至少提供一份简历（文件或粘贴文本）")
    if n > MAX_RESUMES:
        raise HTTPException(422, f"单次任务最多 {MAX_RESUMES} 份简历")

    # 模型预检
    if not await LLMClient(settings, db).health_check():
        raise HTTPException(503, "大模型服务不可用，请检查 LLM_BASE_URL 配置")

    # JD 文件（pdf/docx/txt）先解析出纯文本再入库：
    # 原始二进制（如 docx 的 zip 字节流）含 NUL 字节，PostgreSQL text 字段无法存储
    if jd_text and jd_text.strip():
        jd_raw = jd_text
    elif jd_file is not None:
        try:
            result = await asyncio.to_thread(
                parse_resume_sync, _safe_name(jd_file.filename or "jd"),
                await jd_file.read())
        except ParseError as e:
            raise HTTPException(422, f"JD 文件解析失败：{e}")
        if result.needs_image_channel:
            raise HTTPException(422, "JD 文件是扫描件/图片型 PDF，无法提取文本，请直接粘贴 JD 文本")
        jd_raw = result.text
        if not jd_raw.strip():
            raise HTTPException(422, "JD 文件内容为空，无法提取文本")
    else:
        jd_raw = None

    task = Task(jd_raw=jd_raw, status="pending")
    db.add(task)
    db.flush()

    upload_dir = Path(settings.uploads_dir) / str(task.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    for f in resume_files:
        if not f.filename:
            continue
        data = await f.read()
        name = _safe_name(f.filename)
        await asyncio.to_thread((upload_dir / name).write_bytes, data)
        db.add(Resume(task_id=task.id, filename=name,
                      source_type=_source_type(name), status="pending"))
    for i, text in enumerate(pasted_list):
        if not (text and text.strip()):
            continue
        name = f"{i}_pasted.txt"
        await asyncio.to_thread(
            (upload_dir / name).write_text, text, "utf-8")
        db.add(Resume(task_id=task.id, filename=name, source_type="text", status="pending"))
    db.commit()

    bg = asyncio.create_task(run_task(task.id))
    _background_tasks.add(bg)
    bg.add_done_callback(_background_tasks.discard)
    return {"task_id": task.id}


def _llm_call(log) -> dict:
    return {"role": log.role, "prompt_tokens": log.prompt_tokens,
            "completion_tokens": log.completion_tokens,
            "duration_ms": log.duration_ms,
            "created_at": log.created_at.isoformat() if log.created_at else None}


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    logs = (db.query(LLMLog).filter(LLMLog.task_id == task_id)
            .order_by(LLMLog.id).all())
    task_calls = [_llm_call(l) for l in logs if l.resume_id is None]
    resume_calls: dict[int, list] = {}
    for l in logs:
        if l.resume_id is not None:
            resume_calls.setdefault(l.resume_id, []).append(_llm_call(l))
    usage = {
        "prompt_tokens": sum(l.prompt_tokens for l in logs),
        "completion_tokens": sum(l.completion_tokens for l in logs),
        "duration_ms": sum(l.duration_ms for l in logs),
        "calls": len(logs),
    }
    return {
        "task_id": task.id, "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "jd_parsed": task.jd_parsed,
        "summary_report": task.summary_report,
        "stage_timeline": task.stage_timeline or [],
        "llm_usage": usage,
        "task_llm_calls": task_calls,
        "resumes": [{
            "id": r.id, "filename": r.filename, "status": r.status,
            "source_type": r.source_type,
            "final_grade": r.final_grade, "final_rank": r.final_rank,
            "error_message": r.error_message,
            "stage_timeline": r.stage_timeline or [],
            "llm_calls": resume_calls.get(r.id, []),
        } for r in task.resumes],
    }


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    q = event_bus.subscribe(task_id)

    async def gen():
        try:
            # 任务已结束时立即下发终态事件，避免客户端 SSE 永久挂起/无限重连
            if task.status in ("done", "failed"):
                event = {"type": "task_done" if task.status == "done" else "task_failed"}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                return
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("task_done", "task_failed"):
                    break
        finally:
            event_bus.unsubscribe(task_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/tasks/{task_id}/export")
def export_task(task_id: int, format: str = "md", db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if format == "md":
        return PlainTextResponse(_render_markdown(task))
    if format == "xlsx":
        return Response(_render_xlsx(task),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=task_{task_id}.xlsx"})
    raise HTTPException(422, "format 仅支持 md / xlsx")


def _render_markdown(task: Task) -> str:
    lines = [f"# 简历筛选报告（任务 {task.id}）", ""]
    lines += ["| 排名 | 分档 | 简历 | 评价 |", "|---|---|---|---|"]
    if task.summary_report:
        if task.summary_report.get("summary"):
            lines[1:1] = [task.summary_report.get("summary", ""), ""]
        for item in sorted(task.summary_report.get("rankings", []), key=lambda x: x["rank"]):
            name = next((r.filename for r in task.resumes if r.id == item["resume_id"]), str(item["resume_id"]))
            lines.append(f"| {item['rank']} | {item['grade']} | {name} | {item['comment']} |")
    return "\n".join(lines)


def _render_xlsx(task: Task) -> bytes:
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "筛选汇总"
    ws.append(["排名", "姓名", "文件", "分档", "技能匹配", "经验匹配", "稳定性", "潜力", "初筛结论"])
    rankings = (task.summary_report or {}).get("rankings") or [
        {"resume_id": r.id} for r in task.resumes]
    rows = sorted(rankings, key=lambda x: x.get("rank", 999))
    for item in rows:
        r = next((r for r in task.resumes if r.id == item["resume_id"]), None)
        if r is None:
            continue
        ev = r.evaluation or {}
        ws.append([item.get("rank"), (r.profile or {}).get("name", ""), r.filename,
                   r.final_grade, ev.get("skill_match"), ev.get("experience_match"),
                   ev.get("stability"), ev.get("potential"),
                   "通过" if (r.screening or {}).get("passed") else "淘汰"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
