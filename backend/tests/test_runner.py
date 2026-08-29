import pytest
from unittest.mock import patch, AsyncMock
from app.models import Task, Resume
from app.pipeline.events import EventBus
from app.pipeline import runner as runner_mod
from app.schemas import (
    JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport,
)

JD = JDParsed(responsibilities=[], hard_requirements=[
    {"description": "本科及以上", "weight": 1.0}], bonus_items=[])


def _mk_profile_llm():
    """构造一个可复用的 LLMClient 替身。"""
    fake = AsyncMock()
    async def chat_json(role, system_prompt, user_prompt, schema, **kw):
        if schema is JDParsed:
            return JD
        if schema is ResumeProfile:
            return ResumeProfile(name="张三", education=[], work_experience=[],
                                 skills=["Go"], projects=[], certificates=[])
        if schema is ScreeningResult:
            return ScreeningResult(passed=True, checks=[])
        if schema is EvaluationResult:
            return EvaluationResult(skill_match=80, experience_match=80, stability=80,
                                    potential=80, highlights=[], risks=[], gaps=[],
                                    interview_questions=["q"])
        if schema is FinalReport:
            return FinalReport(
                rankings=[{"resume_id": rid, "grade": "A", "rank": i + 1, "comment": "ok"}
                          for i, rid in enumerate(chat_json.resume_ids)],
                summary="ok")
        raise AssertionError(schema)
    fake.chat_json = chat_json
    fake.chat_json.resume_ids = []
    return fake


@pytest.fixture
def seed(db_session, session_factory):
    task = Task(jd_raw="JD文本", status="pending")
    db_session.add(task)
    db_session.flush()
    r1 = Resume(task_id=task.id, filename="a.txt", source_type="text", status="pending")
    r2 = Resume(task_id=task.id, filename="b.txt", source_type="text", status="pending")
    db_session.add_all([r1, r2])
    db_session.commit()
    return task, r1, r2


async def test_pipeline_full_flow(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r1.id, r2.id]
    runner_mod._set_session_factory(session_factory)

    events = []
    bus = EventBus()
    q = bus.subscribe(task.id)

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "event_bus", bus), \
         patch.object(runner_mod, "_load_file", return_value=b"dummy resume text"):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    task = db_session.get(Task, task.id)
    assert task.status == "done"
    assert task.jd_parsed["hard_requirements"][0]["description"] == "本科及以上"
    for r in task.resumes:
        assert r.status == "done"
        assert r.final_grade == "A"
    assert len(task.summary_report["rankings"]) == 2
    bus.unsubscribe(task.id, q)


async def test_screen_reject_short_circuit(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r2.id]
    original_chat = llm.chat_json

    async def chat_json(role, *a, **kw):
        if role == "screener" and f"resume_id={r1.id}" in a[1]:
            return ScreeningResult(passed=False, checks=[], reject_reason="学历不符")
        return await original_chat(role, *a, **kw)
    llm.chat_json = chat_json
    runner_mod._set_session_factory(session_factory)

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "_load_file", return_value=b"dummy resume text"):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    rejected = db_session.get(Resume, r1.id)
    evaluated = db_session.get(Resume, r2.id)
    assert rejected.final_grade == "D"          # 初筛淘汰
    assert rejected.evaluation is None           # 未进入面评
    assert evaluated.evaluation is not None
    # HR 汇总只含通过者
    assert db_session.get(Task, task.id).status == "done"


async def test_llm_failure_marks_needs_review(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    original_chat = llm.chat_json

    async def chat_json(role, *a, **kw):
        if role == "extractor" and "resume_A_text" in a[1]:
            from app.llm import LLMError
            raise LLMError("boom", attempts=3)
        return await original_chat(role, *a, **kw)
    llm.chat_json = chat_json
    runner_mod._set_session_factory(session_factory)

    def _load_text(resume):
        return b"resume_A_text" if resume.id == r1.id else b"resume_B_text"

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "_load_file", side_effect=_load_text):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    assert db_session.get(Resume, r1.id).status == "needs_review"
    assert db_session.get(Resume, r2.id).status == "done"


async def test_parse_failure_marks_failed(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r2.id]
    runner_mod._set_session_factory(session_factory)

    def boom(filename, data):
        from app.parsers import ParseError, parse_resume_sync
        if filename == "a.txt":
            raise ParseError("bad file")
        return parse_resume_sync(filename, data)

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "parse_resume_sync", side_effect=boom), \
         patch.object(runner_mod, "_load_file", return_value=b"dummy resume text"):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    assert db_session.get(Resume, r1.id).status == "failed"
    assert db_session.get(Resume, r1.id).error_message == "bad file"
    assert db_session.get(Resume, r2.id).status == "done"


async def test_eval_failure_kept_out_of_ranking(db_session, seed, session_factory):
    """过了初筛但 evaluation 失败的简历（needs_review）不应进入 HR 汇总排名。"""
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r2.id]
    original_chat = llm.chat_json

    async def chat_json(role, *a, **kw):
        if role == "interviewer" and f"resume_id={r1.id}" in a[1]:
            from app.llm import LLMError
            raise LLMError("eval boom", attempts=3)
        return await original_chat(role, *a, **kw)
    llm.chat_json = chat_json
    runner_mod._set_session_factory(session_factory)

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "_load_file", return_value=b"dummy resume text"):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    r1_db = db_session.get(Resume, r1.id)
    r2_db = db_session.get(Resume, r2.id)
    task_db = db_session.get(Task, task.id)
    assert r1_db.status == "needs_review"
    assert r1_db.final_grade is None  # 未进入汇总，不被赋 grade
    assert r2_db.status == "done"
    assert task_db.status == "done"
    ranked_ids = [item["resume_id"] for item in task_db.summary_report["rankings"]]
    assert r1.id not in ranked_ids
    assert r2.id in ranked_ids


async def test_load_file_failure_isolated(db_session, seed, session_factory):
    """文件缺失（OSError）只标该简历 failed，不打断其它简历与整个任务。"""
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r2.id]
    runner_mod._set_session_factory(session_factory)

    def _load(resume):
        if resume.id == r1.id:
            raise FileNotFoundError("no such file")
        return b"dummy resume text"

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "_load_file", side_effect=_load):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    r1_db = db_session.get(Resume, r1.id)
    r2_db = db_session.get(Resume, r2.id)
    assert r1_db.status == "failed"
    assert "no such file" in (r1_db.error_message or "")
    assert r2_db.status == "done"
    assert db_session.get(Task, task.id).status == "done"
