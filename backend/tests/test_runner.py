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
    # 任务级时间线：jd_parse 与 summarize 两阶段均已闭合
    stages = {t["stage"]: t for t in task.stage_timeline}
    assert set(stages) == {"jd_parse", "summarize"}
    for t in task.stage_timeline:
        assert t["started_at"] and t["ended_at"] and t["status"] == "ok"
    # 简历级时间线：四个阶段全部闭合
    for r in task.resumes:
        r_stages = {t["stage"] for t in r.stage_timeline}
        assert r_stages == {"parsing", "extracting", "screening", "evaluating"}
    bus.unsubscribe(task.id, q)


async def test_stage_timeline_closes_open_stages_on_failure(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()

    async def fake_extract(llm_, text, rid, task_id=None):
        raise RuntimeError("extract exploded")

    runner_mod._set_session_factory(session_factory)
    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "_load_file", return_value=b"text"), \
         patch.object(runner_mod.roles, "extract_profile", fake_extract):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    task = db_session.get(Task, task.id)
    assert task.status == "failed"
    jd_stage = next(t for t in task.stage_timeline if t["stage"] == "jd_parse")
    assert jd_stage["status"] == "ok"  # JD 阶段成功，之后才失败
    r = db_session.get(type(r1), r1.id)
    ext = next(t for t in r.stage_timeline if t["stage"] == "extracting")
    assert ext["status"] == "failed" and ext["detail"]
    assert ext.get("ended_at") is not None


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


class TestScreeningPassRecalc:
    """初筛通过判定重算：满足条数占比 >= screening_pass_ratio 才通过"""

    def _make_screening(self, met_flags):
        from app.schemas import ScreeningResult
        return ScreeningResult(
            passed=all(met_flags),  # 模拟 LLM 保守输出
            checks=[{"requirement": f"要求{i}", "met": m, "evidence": "依据"}
                    for i, m in enumerate(met_flags)],
        )

    def test_recalc_pass_at_threshold(self):
        from app.pipeline.runner import recalc_screening_pass
        s = self._make_screening([True, True, False, False, False])  # 2/5 = 40%
        recalc_screening_pass(s)
        assert s.passed is True  # 命中阈值即通过
        assert s.reject_reason is None

    def test_recalc_fail_below_threshold_overrides_llm_pass(self):
        from app.pipeline.runner import recalc_screening_pass
        s = self._make_screening([True, False])  # 1/2 = 50%...
        s.passed = True  # LLM 说通过
        s.checks[0].met = False  # 0/2 = 0%
        recalc_screening_pass(s)
        assert s.passed is False  # 代码覆盖 LLM 判断
        assert "0%" in s.reject_reason and "40%" in s.reject_reason

    def test_recalc_fail_fills_reject_reason(self):
        from app.pipeline.runner import recalc_screening_pass
        s = self._make_screening([True, False, False, False])  # 1/4 = 25%
        s.passed = False
        s.reject_reason = None
        recalc_screening_pass(s)
        assert s.passed is False
        assert s.reject_reason == "硬性要求满足率 25%（1/4），低于 40% 阈值"

    def test_recalc_fail_keeps_llm_reject_reason(self):
        from app.pipeline.runner import recalc_screening_pass
        s = self._make_screening([False, False, False, False])
        s.reject_reason = "缺少核心技能"
        recalc_screening_pass(s)
        assert s.reject_reason == "缺少核心技能"  # 已有原因不覆盖

    def test_recalc_empty_checks_passes(self):
        from app.pipeline.runner import recalc_screening_pass
        s = self._make_screening([])
        s.passed = False  # LLM 误判
        recalc_screening_pass(s)
        assert s.passed is True  # 无硬性要求视为通过

    def test_recalc_ratio_from_settings(self):
        from app.pipeline.runner import recalc_screening_pass
        from app.config import get_settings
        s = self._make_screening([True, True, False])  # 2/3 ≈ 66.7%
        # 默认 0.4 阈值下应通过
        recalc_screening_pass(s, ratio=get_settings().screening_pass_ratio)
        assert s.passed is True
