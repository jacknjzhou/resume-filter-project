import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base
import app.models  # noqa: F401  确保 Base.metadata 已注册所有表


_shared_session = None


def _new_session_setup():
    """内存库：用 StaticPool + check_same_thread=False 保证跨线程（TestClient 线程）
    共享同一个 SQLite 连接，避免 "no such table" / "objects created in a thread"。

    Returns: (engine, Session(sessionmaker), session)
    - engine 绑定的 Session 通过 StaticPool 共享同一连接
    - expire_on_commit=False 让 commit 后的属性访问不触发过期 lazy load
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    return engine, Session, session


@pytest.fixture
def engine():
    """共享同一 SQLite 连接的 engine，作为多个 session 的根。"""
    e, _, _ = _new_session_setup()
    try:
        yield e
    finally:
        e.dispose()


@pytest.fixture
def session_factory(engine):
    """返回 sessionmaker；可被 run_task/_process_resume 等并发协程反复调用得到新 session，
    这些 session 与 db_session 共享同一个 engine（同一 SQLite 连接）。"""
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session


@pytest.fixture
def db_session(engine):
    """单个 session，给只需要一个连接的测试用（test_models/test_llm/test_api 等）。

    也通过 _shared_session 全局提供给 FastAPI dependency_overrides（_testing_session）。
    """
    global _shared_session
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    _shared_session = session
    try:
        yield session
    finally:
        _shared_session = None
        session.close()


def _testing_session():
    """FastAPI dependency_overrides 用的 session 依赖。"""
    if _shared_session is not None:
        yield _shared_session
    else:
        engine, _, session = _new_session_setup()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()


@pytest.fixture
def seed_task(db_session):
    from app.models import Task, Resume
    task = Task(jd_raw="JD", status="pending")
    db_session.add(task)
    db_session.flush()
    db_session.add_all([
        Resume(task_id=task.id, filename="a.txt", source_type="text", status="pending"),
        Resume(task_id=task.id, filename="b.txt", source_type="text", status="pending"),
    ])
    db_session.commit()
    return task


@pytest.fixture
def seed_evaluated_resume(db_session, seed_task):
    from app.models import Resume
    r = Resume(task_id=seed_task.id, filename="a.txt", source_type="text",
               status="done", final_grade="A", final_rank=1,
               profile={"name": "张三", "education": [], "work_experience": [],
                        "skills": [], "projects": [], "certificates": []},
               screening={"passed": True, "checks": []},
               evaluation={"skill_match": 80, "experience_match": 70, "stability": 90,
                           "potential": 60, "highlights": ["x"], "risks": ["y"],
                           "gaps": ["z"], "interview_questions": ["q1", "q2"]})
    db_session.add(r)
    db_session.commit()
    return r
