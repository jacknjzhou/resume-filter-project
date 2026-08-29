import asyncio
import base64

from app.config import get_settings
from app.db import SessionLocal
from app.llm import LLMClient, LLMError
from app.models import Task, Resume
from app.parsers import ParseError, parse_resume_sync
from app.parsers.image_parser import parse_image
from app.pipeline import roles
from app.pipeline.events import event_bus

settings = get_settings()

# 测试替换点：返回 DB Session 的工厂
_session_factory = lambda: SessionLocal()


def _set_session_factory(factory):
    global _session_factory
    _session_factory = factory


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _emit(task_id, **event):
    event_bus.emit(task_id, event)


async def run_task(task_id: int):
    db = _session_factory()
    try:
        task = db.get(Task, task_id)
        task.status = "parsing"
        db.commit()
        _emit(task_id, type="task_started")

        llm = LLMClient(settings, db)

        # 1. JD 解析
        jd_parsed = await asyncio.wait_for(
            roles.analyze_jd(llm, task.jd_raw, task_id=task_id),
            timeout=settings.step_timeout)
        task.jd_parsed = jd_parsed.model_dump()
        db.commit()
        _emit(task_id, type="jd_parsed")

        # 2. 简历并行流水线 —— 每个协程独立 Session/LLM，jd_parsed 只读共享
        sem = asyncio.Semaphore(settings.max_concurrency)
        resumes = list(task.resumes)
        resume_ids = [r.id for r in resumes]

        await asyncio.gather(*(_process_resume(rid, task_id, jd_parsed, sem)
                               for rid in resume_ids))

        # 3. 刷新主会话（其他协程的 commit 状态需要重新查询才能见到）
        db.expire_all()
        resumes = db.query(Resume).filter(Resume.task_id == task_id).all()

        # HR 主管汇总（只含通过初筛、有 evaluation 者）
        passed = [r for r in resumes if r.screening and r.screening.get("passed") and r.evaluation is not None]
        items = [{"resume_id": r.id, "profile": r.profile,
                  "screening": r.screening, "evaluation": r.evaluation} for r in passed]
        if passed:
            report = await roles.summarize_ranking(llm, jd_parsed, items, task_id=task_id)
            task.summary_report = report.model_dump()
            rank_map = {item.resume_id: item for item in report.rankings}
            for r in resumes:
                item = rank_map.get(r.id)
                if item:
                    r.final_grade = item.grade
                    r.final_rank = item.rank
        for r in resumes:
            if r.status not in ("failed", "needs_review") and r.final_grade is None:
                r.final_grade = "D"  # 初筛淘汰
        task.status = "done"
        db.commit()
        _emit(task_id, type="task_done")
    except Exception as e:
        db.rollback()
        task = db.get(Task, task_id)
        task.status = "failed"
        task.summary_report = {"error": str(e)}
        db.commit()
        _emit(task_id, type="task_failed", detail=str(e))
    finally:
        db.close()


async def _process_resume(resume_id: int, task_id: int, jd_parsed, sem: asyncio.Semaphore):
    """独立 Session/LLM 处理单份简历；vlm_transcribe 显式绑定本协程 llm。"""
    async with sem:
        db = _session_factory()
        try:
            llm = LLMClient(settings, db)

            # VLM 显式注入：闭包绑定本协程 llm，不污染模块属性。
            async def vlm_transcribe(image, model, prompt):
                return await _vlm_transcribe_real(llm, image, model, prompt)

            # --- parsing ---
            r = db.get(Resume, resume_id)
            if r is None:
                return
            r.status = "parsing"
            db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="parsing")
            if r.source_type == "image":
                parsed = await asyncio.wait_for(
                    parse_image(r.filename, await asyncio.to_thread(_load_file, r),
                                llm, settings, vlm_transcribe=vlm_transcribe),
                    timeout=settings.step_timeout)
            else:
                data = await asyncio.to_thread(_load_file, r)
                result = await asyncio.wait_for(
                    asyncio.to_thread(_parse_sync, r.filename, data),
                    timeout=settings.step_timeout)
                if result.needs_image_channel:
                    parsed = await asyncio.wait_for(
                        parse_image(r.filename, data, llm, settings,
                                    vlm_transcribe=vlm_transcribe),
                        timeout=settings.step_timeout)
                else:
                    parsed = result
            r.raw_text = parsed.text
            r.parse_meta = parsed.parse_meta

            # --- extracting ---
            r.status = "extracting"
            db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="extracting")
            profile = await asyncio.wait_for(
                roles.extract_profile(llm, r.raw_text, resume_id, task_id=task_id),
                timeout=settings.step_timeout)
            r.profile = profile.model_dump()

            # --- screening ---
            r.status = "screening"
            db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="screening")
            screening = await asyncio.wait_for(
                roles.screen_resume(llm, jd_parsed, profile, resume_id, task_id=task_id),
                timeout=settings.step_timeout)
            r.screening = screening.model_dump()

            if not screening.passed:
                r.status = "done"  # 终态：初筛淘汰，汇总阶段标 D
                db.commit()
                _emit(task_id, type="resume_status", resume_id=resume_id, status="done",
                      detail=f"初筛未通过：{screening.reject_reason}")
                return

            # --- evaluating ---
            r.status = "evaluating"
            db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="evaluating")
            evaluation = await asyncio.wait_for(
                roles.evaluate_resume(llm, jd_parsed, profile, resume_id, task_id=task_id),
                timeout=settings.step_timeout)
            r.evaluation = evaluation.model_dump()
            r.status = "done"
            db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="done",
                  detail="评估完成")
        except (LLMError, asyncio.TimeoutError) as e:
            db.rollback()
            r = db.get(Resume, resume_id)
            if r is not None:
                r.status = "needs_review"
                r.error_message = str(e)
                db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="needs_review",
                  detail=str(e))
        except (ParseError, OSError) as e:
            db.rollback()
            r = db.get(Resume, resume_id)
            if r is not None:
                r.status = "failed"
                r.error_message = str(e)
                db.commit()
            _emit(task_id, type="resume_status", resume_id=resume_id, status="failed",
                  detail=str(e))
        finally:
            db.close()


def _parse_sync(filename: str, data: bytes):
    return parse_resume_sync(filename, data)


def _load_file(resume: Resume) -> bytes:
    from pathlib import Path
    path = Path(settings.uploads_dir) / str(resume.task_id) / resume.filename
    return path.read_bytes()  # 调用处用 asyncio.to_thread 包装，避免阻塞事件循环


async def _vlm_transcribe_real(llm: LLMClient, image: bytes, model: str, prompt: str) -> str:
    b64 = base64.b64encode(image).decode()
    resp = await llm._client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    )
    return resp.choices[0].message.content or ""
