from app.models import Task, Resume, LLMLog


def test_create_task_with_resumes(db_session):
    task = Task(jd_raw="资深后端工程师 JD", status="pending")
    db_session.add(task)
    db_session.flush()
    r1 = Resume(task_id=task.id, filename="a.pdf", source_type="pdf", status="pending")
    r2 = Resume(task_id=task.id, filename="b.png", source_type="image", status="pending")
    db_session.add_all([r1, r2])
    db_session.add(LLMLog(task_id=task.id, role="jd_analyst", prompt_tokens=100, completion_tokens=50, duration_ms=800))
    db_session.commit()

    assert task.id is not None
    assert len(task.resumes) == 2
    assert task.llm_logs[0].role == "jd_analyst"


def test_resume_jsonb_fields(db_session):
    task = Task(jd_raw="jd", status="pending")
    db_session.add(task)
    db_session.flush()
    r = Resume(task_id=task.id, filename="a.pdf", source_type="pdf", status="done",
               parse_meta={"channel": "pymupdf", "ocr_confidence": None},
               profile={"name": "张三"})
    db_session.add(r)
    db_session.commit()
    assert r.parse_meta["channel"] == "pymupdf"
    assert r.profile["name"] == "张三"
