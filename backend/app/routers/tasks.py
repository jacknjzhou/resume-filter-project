import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse, Response, PlainTextResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.llm import LLMClient
from app.models import Task, Resume
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

    jd_raw = jd_text or (await jd_file.read()).decode("utf-8", errors="replace")
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


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task.id,
        "status": task.status,
        "jd_parsed": task.jd_parsed,
        "summary_report": task.summary_report,
        "resumes": [{
            "id": r.id, "filename": r.filename, "status": r.status,
            "final_grade": r.final_grade, "final_rank": r.final_rank,
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
