# 简历审阅系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Web 版简历审阅系统：用户提供 JD 与 ≤10 份简历，多角色 LLM 流水线模拟 HR 团队完成筛选、评分、排序与面试问题生成。

**Architecture:** FastAPI 单体后端内嵌 asyncio 多角色流水线（JD 解析官 → 结构化提取 → 初筛专员 → 资深面试官 → HR 主管），图片简历走 PaddleOCR + 多模态 LLM 兜底双通道。Vue3 + Element Plus 前端，SSE 实时进度。PostgreSQL 存储，Docker Compose 一键启动，私有大模型通过 OpenAI 兼容接口接入。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / openai SDK / PyMuPDF / python-docx / httpx / pytest / Vue3 / Vite / Element Plus / nginx / PostgreSQL 16

**设计文档:** `docs/superpowers/specs/2026-08-29-resume-review-design.md`（实现有疑问时以它为准）

## Global Constraints

- Python 3.11；依赖尽量精简（YAGNI）
- LLM 全部走 OpenAI 兼容接口，由环境变量配置：`LLM_BASE_URL` / `LLM_API_KEY`（默认 `EMPTY`）/ `LLM_MODEL` / `LLM_VLM_MODEL` / `OCR_CONFIDENCE_THRESHOLD`（默认 0.85）/ `OCR_BASE_URL`（默认 `http://ocr:8866`）
- 流水线并发上限 `asyncio.Semaphore(3)`（`MAX_CONCURRENCY` 可调）；单步超时 120 秒（`STEP_TIMEOUT` 可调）
- LLM JSON 输出校验失败重试 2 次（附错误说明），仍失败标记 `needs_review`，不中断任务
- 简历 `status` 枚举固定：`pending / parsing / extracting / screening / evaluating / done / failed / needs_review`
- OCR 合格线：平均置信度 ≥ 0.85 且有效文本 ≥ 50 字符；疑似乱码判定：非中英文/数字/常用标点字符占比 > 30%
- 扫描版 PDF 判定：PyMuPDF 提取文本 < 200 字符 → 转图片通道
- 评估结果存 JSONB（SQLAlchemy `JSON` 类型，测试用 SQLite、生产用 PostgreSQL）
- 所有 pytest 单测不依赖真实 LLM/OCR 服务，一律 mock
- 每个 Task 结束必须 git commit

## 项目文件结构

```
resume-review/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI 入口、路由注册、启动时建表
│   │   ├── config.py          # Settings（环境变量）
│   │   ├── db.py              # SQLAlchemy engine/Session
│   │   ├── models.py          # ORM: Task/Resume/LLMLog
│   │   ├── schemas.py         # pydantic: 各角色输入输出模型 + API 响应
│   │   ├── llm.py             # LLMClient.chat_json（校验+重试+llm_logs）
│   │   ├── parsers/
│   │   │   ├── __init__.py    # parse_resume() 按文件类型分发
│   │   │   ├── pdf_parser.py
│   │   │   ├── docx_parser.py
│   │   │   └── image_parser.py # OCR 双通道 + VLM 兜底 + LLM 校正
│   │   ├── pipeline/
│   │   │   ├── events.py      # EventBus（进程内 pub/sub，供 SSE）
│   │   │   ├── roles.py       # 五角色提示词调用
│   │   │   └── runner.py      # run_task() 编排
│   │   └── routers/
│   │       ├── tasks.py       # POST /api/tasks, GET 详情/SSE/export
│   │       └── resumes.py     # GET /api/resumes/{id}/report
│   ├── prompts/
│   │   ├── jd_analyst.txt
│   │   ├── extractor.txt
│   │   ├── screener.txt
│   │   ├── interviewer.txt
│   │   ├── hr_manager.txt
│   │   ├── ocr_fallback.txt
│   │   └── text_corrector.txt
│   └── tests/
│       ├── conftest.py
│       ├── test_config.py
│       ├── test_models.py
│       ├── test_llm.py
│       ├── test_parsers_text.py
│       ├── test_parsers_image.py
│       ├── test_roles.py
│       ├── test_runner.py
│       └── test_api.py
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.js
│       ├── api.js
│       └── views/
│           ├── TaskCreate.vue
│           ├── TaskProgress.vue
│           └── TaskResult.vue
└── samples/                    # 端到端验收用样例（E2E 任务创建）
```

---

### Task 1: 后端脚手架与配置模块

**Files:**
- Create: `backend/requirements.txt`, `backend/pytest.ini`, `backend/app/__init__.py`, `backend/app/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings`（pydantic-settings），字段：`database_url: str`、`llm_base_url: str`、`llm_api_key: str = "EMPTY"`、`llm_model: str`、`llm_vlm_model: str = ""`、`ocr_confidence_threshold: float = 0.85`、`ocr_base_url: str = "http://ocr:8866"`、`step_timeout: int = 120`、`max_concurrency: int = 3`、`uploads_dir: str = "./uploads"`；模块级单例 `get_settings() -> Settings`（lru_cache）

- [ ] **Step 1: 创建依赖清单与 pytest 配置**

`backend/requirements.txt`:

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
sqlalchemy==2.0.*
psycopg[binary]==3.2.*
pydantic==2.*
pydantic-settings==2.*
openai==1.*
httpx==0.27.*
python-multipart==0.0.*
PyMuPDF==1.24.*
python-docx==1.1.*
openpyxl==3.1.*
pytest==8.*
pytest-asyncio==0.23.*
aiosqlite==0.20.*
```

`backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_config.py`:

```python
from app.config import Settings

def test_settings_defaults():
    s = Settings(
        database_url="sqlite:///test.db",
        llm_base_url="http://fake/v1",
        llm_model="test-model",
        _env_file=None,
    )
    assert s.llm_api_key == "EMPTY"
    assert s.ocr_confidence_threshold == 0.85
    assert s.step_timeout == 120
    assert s.max_concurrency == 3
    assert s.llm_vlm_model == ""

def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("OCR_CONFIDENCE_THRESHOLD", "0.9")
    monkeypatch.setenv("STEP_TIMEOUT", "60")
    s = Settings(
        database_url="sqlite:///test.db",
        llm_base_url="http://fake/v1",
        llm_model="m",
        _env_file=None,
    )
    assert s.ocr_confidence_threshold == 0.9
    assert s.step_timeout == 60
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: app`）

- [ ] **Step 4: 实现 config.py**

`backend/app/__init__.py` 为空文件。`backend/app/config.py`:

```python
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://resume:resume@db:5432/resume_review"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "qwen2.5-72b-instruct"
    llm_vlm_model: str = ""
    ocr_confidence_threshold: float = 0.85
    ocr_base_url: str = "http://ocr:8866"
    step_timeout: int = 120
    max_concurrency: int = 3
    uploads_dir: str = "./uploads"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/pytest.ini backend/app backend/tests
git commit -m "feat: 后端脚手架与配置模块"
```

---

### Task 2: 数据库模型

**Files:**
- Create: `backend/app/db.py`, `backend/app/models.py`
- Test: `backend/tests/test_models.py`, `backend/tests/conftest.py`

**Interfaces:**
- Produces:
  - `app.db.Base`（DeclarativeBase）、`app.db.get_db()`（FastAPI 依赖，yield Session）
  - `app.models.Task`：`id, jd_raw: Text, jd_parsed: JSON, status: String(20), summary_report: JSON, created_at, updated_at`
  - `app.models.Resume`：`id, task_id: ForeignKey, filename: String(255), source_type: String(20), raw_text: Text, parse_meta: JSON, profile: JSON, screening: JSON, evaluation: JSON, final_grade: String(2), final_rank: Integer, status: String(20), error_message: Text, created_at, updated_at`
  - `app.models.LLMLog`：`id, task_id, role: String(50), prompt_tokens: Integer, completion_tokens: Integer, duration_ms: Integer, created_at`

- [ ] **Step 1: 写 conftest 与失败测试**

`backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")  # 内存库
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
```

`backend/tests/test_models.py`:

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL（`No module named 'app.db'`）

- [ ] **Step 3: 实现 db.py 与 models.py**

`backend/app/db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

`backend/app/models.py`:

```python
from datetime import datetime
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    jd_raw: Mapped[str] = mapped_column(Text)
    jd_parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    summary_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    resumes: Mapped[list["Resume"]] = relationship(back_populates="task")
    llm_logs: Mapped[list["LLMLog"]] = relationship(back_populates="task")


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    filename: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20))  # pdf / docx / image / text
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    screening: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    task: Mapped["Task"] = relationship(back_populates="resumes")


class LLMLog(Base):
    __tablename__ = "llm_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(50))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="llm_logs")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/tests/conftest.py backend/tests/test_models.py
git commit -m "feat: 数据库模型 Task/Resume/LLMLog"
```

---

### Task 3: pydantic 输出模型（各角色 schema）

**Files:**
- Create: `backend/app/schemas.py`
- Test: `backend/tests/test_schemas.py`

**Interfaces:**
- Produces（后续所有角色/流水线/API 共用，字段名必须逐字一致）:
  - `JDRequirement(description: str, weight: float)`
  - `JDParsed(responsibilities: list[str], hard_requirements: list[JDRequirement], bonus_items: list[str])`
  - `Education(school: str, degree: str, major: str, period: str)`
  - `WorkExperience(company: str, title: str, period: str, summary: str)`
  - `ResumeProfile(name: str, education: list[Education], work_experience: list[WorkExperience], skills: list[str], projects: list[str], certificates: list[str])`
  - `ScreeningCheck(requirement: str, met: bool, evidence: str)`
  - `ScreeningResult(passed: bool, checks: list[ScreeningCheck], reject_reason: str | None = None)`
  - `EvaluationResult(skill_match: int, experience_match: int, stability: int, potential: int, highlights: list[str], risks: list[str], gaps: list[str], interview_questions: list[str])`（四个分数约束 `ge=0, le=100`）
  - `FinalRankingItem(resume_id: int, grade: str, rank: int, comment: str)`
  - `FinalReport(rankings: list[FinalRankingItem], summary: str)`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError
from app.schemas import (
    JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport,
)


def test_jd_parsed_minimal():
    jd = JDParsed(responsibilities=[], hard_requirements=[], bonus_items=[])
    assert jd.responsibilities == []


def test_evaluation_score_bounds():
    with pytest.raises(ValidationError):
        EvaluationResult(skill_match=101, experience_match=0, stability=0,
                         potential=0, highlights=[], risks=[], gaps=[],
                         interview_questions=[])
    ok = EvaluationResult(skill_match=80, experience_match=70, stability=90,
                          potential=60, highlights=["a"], risks=["b"],
                          gaps=["c"], interview_questions=["q1"])
    assert ok.skill_match == 80


def test_screening_reject_reason_optional():
    s = ScreeningResult(passed=False, checks=[], reject_reason=None)
    assert s.passed is False


def test_final_report_shape():
    r = FinalReport(rankings=[{"resume_id": 1, "grade": "A", "rank": 1, "comment": "强推"}],
                    summary="共 1 人")
    assert r.rankings[0].grade == "A"


def test_resume_profile_shape():
    p = ResumeProfile.model_validate({
        "name": "李四",
        "education": [{"school": "X大", "degree": "本科", "major": "CS", "period": "2015-2019"}],
        "work_experience": [{"company": "A公司", "title": "后端", "period": "2019-至今", "summary": "Go 微服务"}],
        "skills": ["Go"], "projects": ["p"], "certificates": [],
    })
    assert p.work_experience[0].company == "A公司"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: FAIL（`No module named 'app.schemas'`）

- [ ] **Step 3: 实现 schemas.py**

`backend/app/schemas.py`:

```python
from pydantic import BaseModel, Field


class JDRequirement(BaseModel):
    description: str
    weight: float


class JDParsed(BaseModel):
    responsibilities: list[str]
    hard_requirements: list[JDRequirement]
    bonus_items: list[str]


class Education(BaseModel):
    school: str
    degree: str
    major: str
    period: str


class WorkExperience(BaseModel):
    company: str
    title: str
    period: str
    summary: str


class ResumeProfile(BaseModel):
    name: str
    education: list[Education]
    work_experience: list[WorkExperience]
    skills: list[str]
    projects: list[str]
    certificates: list[str]


class ScreeningCheck(BaseModel):
    requirement: str
    met: bool
    evidence: str


class ScreeningResult(BaseModel):
    passed: bool
    checks: list[ScreeningCheck]
    reject_reason: str | None = None


class EvaluationResult(BaseModel):
    skill_match: int = Field(ge=0, le=100)
    experience_match: int = Field(ge=0, le=100)
    stability: int = Field(ge=0, le=100)
    potential: int = Field(ge=0, le=100)
    highlights: list[str]
    risks: list[str]
    gaps: list[str]
    interview_questions: list[str]


class FinalRankingItem(BaseModel):
    resume_id: int
    grade: str
    rank: int
    comment: str


class FinalReport(BaseModel):
    rankings: list[FinalRankingItem]
    summary: str
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_schemas.py
git commit -m "feat: 各角色 pydantic 输出模型"
```

---

### Task 4: LLM 客户端（JSON 校验 + 重试 + 日志）

**Files:**
- Create: `backend/app/llm.py`
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Produces:
  - `class LLMError(Exception)`（含 `attempts: int` 属性）
  - `class LLMClient:`
    - `__init__(self, settings: Settings, db: Session)`
    - `async chat_json(role: str, system_prompt: str, user_prompt: str, schema: type[BaseModel], task_id: int | None = None, model: str | None = None) -> BaseModel`
      - 内部用 `AsyncOpenAI(base_url=..., api_key=...)`，model 缺省用 `settings.llm_model`
      - 首次调用 + 校验失败重试共 3 次机会（首次失败后再试 2 次，重试时把上次的 ValidationError 信息拼进 user_prompt）
      - 全部失败抛 `LLMError`
      - 每次调用写一条 `LLMLog`（role/task_id/token 用量/耗时）
    - `async health_check() -> bool`（调 `client.models.list()`，异常返回 False）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_llm.py`:

```python
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


class FakeAsyncOpenAI:
    def __init__(self, script, base_url=None, api_key=None):
        self.chat = FakeChat(FakeCompletions(script))
        self.base_url = base_url


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


async def test_chat_json_exhausted_raises(db_session, patch_openai):
    patch_openai(["bad", "bad", "bad"])
    client = LLMClient(settings=None, db=db_session)
    with pytest.raises(LLMError):
        await client.chat_json("tester", "sys", "user", Out)


async def test_writes_llm_log(db_session, patch_openai):
    patch_openai([json.dumps({"ok": True})])
    client = LLMClient(settings=None, db=db_session)
    await client.chat_json("jd_analyst", "sys", "user", Out, task_id=1)
    from app.models import LLMLog
    logs = db_session.query(LLMLog).all()
    assert len(logs) == 1
    assert logs[0].role == "jd_analyst"
    assert logs[0].prompt_tokens == 10
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_llm.py -v`
Expected: FAIL（`No module named 'app.llm'`）

- [ ] **Step 3: 实现 llm.py**

`backend/app/llm.py`:

```python
import json
import time
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI
from sqlalchemy.orm import Session
from app.models import LLMLog

MAX_ATTEMPTS = 3  # 首次 + 2 次重试


class LLMError(Exception):
    def __init__(self, message: str, attempts: int):
        super().__init__(message)
        self.attempts = attempts


class LLMClient:
    def __init__(self, settings, db: Session):
        self.settings = settings
        self.db = db
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url if settings else None,
            api_key=settings.llm_api_key if settings else "EMPTY",
        )

    async def chat_json(self, role, system_prompt, user_prompt, schema: type[BaseModel],
                        task_id=None, model=None):
        last_err = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = user_prompt
            if attempt > 1 and last_err is not None:
                prompt = (f"{user_prompt}\n\n上次输出未通过校验，错误信息：{last_err}。"
                          f"请严格按 JSON Schema 重新输出，不要输出任何多余文字。")
            start = time.monotonic()
            try:
                resp = await self._client.chat.completions.create(
                    model=model or (self.settings.llm_model if self.settings else "test-model"),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content
                usage = resp.usage
            except Exception as e:  # 网络/服务错误也计一次尝试
                last_err = str(e)
                self._log(task_id, role, 0, 0, start)
                continue
            try:
                result = schema.model_validate_json(content)
            except ValidationError as e:
                last_err = str(e)
                self._log(task_id, role, usage.prompt_tokens, usage.completion_tokens, start)
                continue
            self._log(task_id, role, usage.prompt_tokens, usage.completion_tokens, start)
            return result
        raise LLMError(f"角色 {role} 在 {MAX_ATTEMPTS} 次尝试后仍未产出合法 JSON：{last_err}",
                       attempts=MAX_ATTEMPTS)

    def _log(self, task_id, role, ptok, ctok, start):
        self.db.add(LLMLog(task_id=task_id, role=role,
                           prompt_tokens=ptok or 0, completion_tokens=ctok or 0,
                           duration_ms=int((time.monotonic() - start) * 1000)))
        self.db.commit()

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
```

注意：测试里 `settings=None`，实现需容忍（如上）。若你的 `AsyncOpenAI(base_url=None)` 报错，测试 fake 类已接受任意 kwargs，不影响。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_llm.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py backend/tests/test_llm.py
git commit -m "feat: LLM 客户端 JSON 校验重试与调用日志"
```

---

### Task 5: 文本类简历解析器（text/docx/pdf + 扫描版检测）

**Files:**
- Create: `backend/app/parsers/__init__.py`, `backend/app/parsers/pdf_parser.py`, `backend/app/parsers/docx_parser.py`
- Test: `backend/tests/test_parsers_text.py`

**Interfaces:**
- Produces:
  - `@dataclass ParseResult: text: str; parse_meta: dict; needs_image_channel: bool = False`
  - `parse_pdf(data: bytes) -> ParseResult`（用 PyMuPDF；提取文本 < 200 字符 → `needs_image_channel=True`；抛 `ParseError` 表示加密/损坏）
  - `parse_docx(data: bytes) -> ParseResult`
  - `parse_text(text: str) -> ParseResult`
  - `class ParseError(Exception)`
  - `parse_resume_sync(filename: str, data: bytes) -> ParseResult`（按扩展名分发：`.pdf`/`.docx`；其他扩展名按 utf-8 文本兜底）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_parsers_text.py`:

```python
import io
import fitz  # PyMuPDF，测试里用它生成样例 PDF
from docx import Document
import pytest
from app.parsers import parse_resume_sync, ParseError
from app.parsers.pdf_parser import parse_pdf
from app.parsers.docx_parser import parse_docx


def _make_pdf(words: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), words, fontname="china-s")
    return doc.tobytes()


def _make_docx(text: str) -> bytes:
    d = Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_parse_pdf_text():
    data = _make_pdf("张三 后端工程师 Go 微服务 经验丰富 " * 20)
    r = parse_pdf(data)
    assert not r.needs_image_channel
    assert "张三" in r.text
    assert r.parse_meta["channel"] == "pymupdf"


def test_parse_pdf_scanned_detection():
    r = parse_pdf(_make_pdf("短文本"))  # < 200 字符
    assert r.needs_image_channel
    assert r.text == "短文本"


def test_parse_pdf_corrupted():
    with pytest.raises(ParseError):
        parse_pdf(b"%PDF-not-a-real-pdf")


def test_parse_docx():
    r = parse_docx(_make_docx("李四 Python 工程师"))
    assert "李四" in r.text


def test_dispatch_by_filename():
    r = parse_resume_sync("resume.docx", _make_docx("内容"))
    assert "内容" in r.text
    r2 = parse_resume_sync("notes.txt", "纯文本简历".encode("utf-8"))
    assert "纯文本简历" in r2.text
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_parsers_text.py -v`
Expected: FAIL（`No module named 'app.parsers'`）

- [ ] **Step 3: 实现解析器**

`backend/app/parsers/__init__.py`:

```python
class ParseError(Exception):
    """简历文件损坏/加密/无法解析。"""


def parse_resume_sync(filename: str, data: bytes):
    """按文件类型分发，返回 ParseResult。图片类型由异步管线单独处理。"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        from app.parsers.pdf_parser import parse_pdf
        return parse_pdf(data)
    if lower.endswith(".docx"):
        from app.parsers.docx_parser import parse_docx
        return parse_docx(data)
    # 其他一律按 utf-8 文本兜底
    from app.parsers.pdf_parser import ParseResult  # 复用 dataclass
    return ParseResult(text=data.decode("utf-8", errors="replace"), parse_meta={"channel": "plain_text"})
```

`backend/app/parsers/pdf_parser.py`:

```python
from dataclasses import dataclass, field
import fitz
from app.parsers import ParseError


@dataclass
class ParseResult:
    text: str
    parse_meta: dict = field(default_factory=dict)
    needs_image_channel: bool = False


SCANNED_MIN_CHARS = 200


def parse_pdf(data: bytes) -> ParseResult:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        raise ParseError(f"PDF 无法解析：{e}") from e
    meta = {"channel": "pymupdf", "char_count": len(text)}
    if len(text.strip()) < SCANNED_MIN_CHARS:
        return ParseResult(text=text.strip(), parse_meta=meta, needs_image_channel=True)
    return ParseResult(text=text.strip(), parse_meta=meta)
```

`backend/app/parsers/docx_parser.py`:

```python
import io
from docx import Document
from app.parsers import ParseError
from app.parsers.pdf_parser import ParseResult


def parse_docx(data: bytes) -> ParseResult:
    try:
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        raise ParseError(f"docx 无法解析：{e}") from e
    return ParseResult(text=text, parse_meta={"channel": "python-docx"})
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_parsers_text.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/parsers backend/tests/test_parsers_text.py
git commit -m "feat: text/docx/pdf 解析器与扫描版检测"
```

---

### Task 6: 图片双通道解析器（OCR + VLM 兜底 + LLM 校正）

**Files:**
- Create: `backend/app/parsers/image_parser.py`, `backend/prompts/ocr_fallback.txt`, `backend/prompts/text_corrector.txt`
- Test: `backend/tests/test_parsers_image.py`

**Interfaces:**
- Consumes: `LLMClient.chat_json`（Task 4）、`ParseResult`（Task 5）
- Produces:
  - `class OCRClient: __init__(base_url: str)`; `async recognize(image: bytes) -> list[dict]`（POST `{base_url}`，body 为 multipart `file` 字段，期望响应 JSON：`{"lines": [{"text": "...", "confidence": 0.98}, ...]}`；网络错抛异常）
  - 纯函数 `ocr_confidence(lines: list[dict]) -> float`（空行返回 0.0，否则各行 confidence 平均值）
  - 纯函数 `looks_garbled(text: str) -> bool`（可读字符占比 < 70% 视为乱码）
  - `async parse_image(filename: str, data: bytes, llm: LLMClient, settings) -> ParseResult`
    - 主通道 OCR → 合格（置信度 ≥ 阈值、文本 ≥ 50 字、非乱码）→ 走 LLM 校正 → 返回
    - 不合格：若 `settings.llm_vlm_model` 非空 → VLM 兜底（图片 base64 直出转录文本，role=`ocr_fallback`）→ 走 LLM 校正 → 返回；VLM 未配置或也失败 → 抛 `ParseError`
    - `parse_meta` 记录：`channel`（`paddleocr` / `vlm_fallback`）、`ocr_confidence`、`ocr_raw_text`（校正前文本）

- [ ] **Step 1: 写提示词模板**

`backend/prompts/ocr_fallback.txt`:

```
你是专业的 OCR 识别引擎。请完整转录图片中的所有文字，要求：
1. 按原始版面从上到下、从左到右输出；
2. 保留段落与条目结构（用换行分隔）；
3. 不要翻译、不要总结、不要添加图片中不存在的内容。
```

`backend/prompts/text_corrector.txt`:

```
你是文本校对员。下面是一段 OCR 识别出的简历文本，可能存在形近字错误、断行错误或乱码。
请只修复明显的识别错误，严格遵守：
1. 不改写、不润色、不增删任何事实内容；
2. 修复后输出完整文本；
3. 以 JSON 格式输出：{"corrected": "修复后的完整文本"}
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_parsers_image.py`:

```python
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
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_parsers_image.py -v`
Expected: FAIL（`No module named 'app.parsers.image_parser'`）

- [ ] **Step 4: 实现 image_parser.py**

`backend/app/parsers/image_parser.py`:

```python
import base64
import re
import httpx
from app.parsers import ParseError
from app.parsers.pdf_parser import ParseResult
from app.llm import LLMError

MIN_TEXT_CHARS = 50
GARBLED_MAX_RATIO = 0.30
# 可读字符：中文、英文、数字、常见中英文标点与空白
_READABLE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9\s，。、；：""''（）【】《》,.:;()\-·/&%+]")


def ocr_confidence(lines: list[dict]) -> float:
    if not lines:
        return 0.0
    return sum(l.get("confidence", 0.0) for l in lines) / len(lines)


def looks_garbled(text: str) -> bool:
    if not text:
        return True
    readable = len(_READABLE.findall(text))
    return (readable / len(text)) < (1 - GARBLED_MAX_RATIO)


class OCRClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def recognize(self, image: bytes) -> list[dict]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.base_url, files={"file": image})
            resp.raise_for_status()
            return resp.json().get("lines", [])


def _load_prompt(name: str) -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[2] / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


async def _vlm_transcribe(image: bytes, model: str, prompt: str) -> str:
    """VLM 图片转录。真实实现走 LLMClient 的 OpenAI 兼容接口（chat.completions，image_url 传入 base64）。

    为便于测试，此函数可被 monkeypatch 替换；生产实现见 _vlm_transcribe_real。
    """
    raise NotImplementedError


_VLM_IMPL = None  # 测试替换点：parse_image 统一调用 _vlm_transcribe 的模块级引用


async def _correct(llm, text: str) -> str:
    from app.schemas import TextCorrection
    result = await llm.chat_json(
        role="text_corrector",
        system_prompt=_load_prompt("text_corrector"),
        user_prompt=f"OCR 文本：\n{text}",
        schema=TextCorrection,
    )
    return result.corrected


def _ocr_ok(lines: list[dict], settings) -> bool:
    text = "\n".join(l.get("text", "") for l in lines)
    return (ocr_confidence(lines) >= settings.ocr_confidence_threshold
            and len(text.strip()) >= MIN_TEXT_CHARS
            and not looks_garbled(text))


async def parse_image(filename: str, data: bytes, llm, settings) -> ParseResult:
    """双通道：OCR 主通道 → VLM 兜底 → LLM 校正。"""
    ocr_lines: list[dict] = []
    ocr_error = None
    try:
        ocr_lines = await OCRClient(settings.ocr_base_url).recognize(data)
    except Exception as e:
        ocr_error = str(e)

    ocr_text = "\n".join(l.get("text", "") for l in ocr_lines)
    confidence = ocr_confidence(ocr_lines)

    if _ocr_ok(ocr_lines, settings):
        corrected = await _correct(llm, ocr_text)
        return ParseResult(
            text=corrected,
            parse_meta={"channel": "paddleocr", "ocr_confidence": confidence,
                        "ocr_raw_text": ocr_text},
        )

    # 兜底通道
    if not settings.llm_vlm_model:
        raise ParseError(f"OCR 质量不合格且未配置 VLM 兜底（confidence={confidence:.2f}，"
                         f"ocr_error={ocr_error}）")
    try:
        vlm_text = await _vlm_transcribe(data, settings.llm_vlm_model,
                                         _load_prompt("ocr_fallback"))
        if not vlm_text.strip():
            raise ParseError("VLM 返回空文本")
        corrected = await _correct(llm, vlm_text)
        return ParseResult(
            text=corrected,
            parse_meta={"channel": "vlm_fallback", "ocr_confidence": confidence,
                        "ocr_raw_text": vlm_text},
        )
    except LLMError as e:
        raise ParseError(f"VLM 兜底失败：{e}") from e
```

注意两点：
1. `app.schemas.TextCorrection` 需要补充——在 `schemas.py` 末尾追加：

```python
class TextCorrection(BaseModel):
    corrected: str
```

2. 测试里 `monkeypatch.setattr("app.parsers.image_parser._vlm_transcribe", impl)` 直接替换了模块级函数引用，`parse_image` 内调用 `await _vlm_transcribe(...)` 前需先取模块级引用。为保证 patch 生效，`parse_image` 中的调用写成：

```python
import app.parsers.image_parser as _self
vlm_text = await _self._vlm_transcribe(data, settings.llm_vlm_model, _load_prompt("ocr_fallback"))
```

生产环境的 `_vlm_transcribe` 实现放到 Task 8（`main.py` 启动装配时注入真实 LLM 调用），本任务先 `NotImplementedError` 占位即可——单测全部通过 mock 覆盖。

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_parsers_image.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/parsers/image_parser.py backend/app/schemas.py backend/prompts backend/tests/test_parsers_image.py
git commit -m "feat: OCR+VLM 兜底双通道图片解析器"
```

---

### Task 7: 五角色流水线（提示词 + roles.py）

**Files:**
- Create: `backend/prompts/jd_analyst.txt`, `backend/prompts/extractor.txt`, `backend/prompts/screener.txt`, `backend/prompts/interviewer.txt`, `backend/prompts/hr_manager.txt`, `backend/app/pipeline/__init__.py`, `backend/app/pipeline/roles.py`
- Test: `backend/tests/test_roles.py`

**Interfaces:**
- Consumes: `LLMClient.chat_json`（Task 4）、schemas（Task 3）
- Produces（`backend/app/pipeline/roles.py`，全部为异步函数，`llm` 参数为 `LLMClient`）:
  - `async analyze_jd(llm, jd_text: str, task_id: int | None = None) -> JDParsed`
  - `async extract_profile(llm, resume_text: str, resume_id: int, task_id: int | None = None) -> ResumeProfile`
  - `async screen_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile, resume_id: int, task_id: int | None = None) -> ScreeningResult`
  - `async evaluate_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile, resume_id: int, task_id: int | None = None) -> EvaluationResult`
  - `async summarize_ranking(llm, jd_parsed: JDParsed, items: list[dict], task_id: int | None = None) -> FinalReport`（`items` 元素：`{"resume_id": int, "profile": dict, "screening": dict, "evaluation": dict}`；只包含通过初筛者）

- [ ] **Step 1: 写提示词模板**

`backend/prompts/jd_analyst.txt`:

```
你是资深招聘经理「JD 解析官」。请把用户提供的职位 JD 解析为结构化信息，输出 JSON：
{
  "responsibilities": ["岗位职责列表"],
  "hard_requirements": [{"description": "硬性要求描述", "weight": 1.0}],
  "bonus_items": ["加分项列表"]
}
规则：
1. hard_requirements 只放可客观核验的硬性条件（学历、工作年限、必备技能、证书），weight 为 0-1 之间的重要性权重，合计约等于 1；
2. 主观期望（如"沟通能力强"）不要放入 hard_requirements，可放入 bonus_items；
3. 只输出 JSON。
```

`backend/prompts/extractor.txt`:

```
你是「结构化提取员」。请从简历文本中提取结构化档案，输出 JSON：
{
  "name": "姓名",
  "education": [{"school": "学校", "degree": "学历", "major": "专业", "period": "起止时间"}],
  "work_experience": [{"company": "公司", "title": "职位", "period": "起止时间", "summary": "一句话概括职责与成果"}],
  "skills": ["技能"],
  "projects": ["项目描述"],
  "certificates": ["证书"]
}
规则：忠于原文，简历中不存在的信息留空数组/空字符串，不要推测。只输出 JSON。
```

`backend/prompts/screener.txt`:

```
你是「初筛专员」。给你结构化 JD 与候选人档案，请对每条硬性要求逐条核对，输出 JSON：
{
  "checks": [{"requirement": "要求原文", "met": true/false, "evidence": "简历中的依据原文摘录，或说明缺失"}],
  "passed": true/false,
  "reject_reason": "未通过时给出最主要的淘汰原因，通过则为 null"
}
规则：
1. passed = 所有硬性要求均满足；
2. evidence 必须引用简历档案中的事实，不得推测；
3. 只输出 JSON。
```

`backend/prompts/interviewer.txt`:

```
你是「资深面试官」。给你结构化 JD 与已通过初筛的候选人档案，请深度评估并输出 JSON：
{
  "skill_match": 0-100 技能匹配度,
  "experience_match": 0-100 经验匹配度,
  "stability": 0-100 稳定性（工作年限连续性、跳槽频率）,
  "potential": 0-100 潜力（成长轨迹、项目复杂度）,
  "highlights": ["亮点"],
  "risks": ["风险点"],
  "gaps": ["与 JD 的差距"],
  "interview_questions": ["3-5 个针对性面试问题，聚焦验证疑点与薄弱点"]
}
规则：评分要有依据，亮点与风险必须引用档案事实。只输出 JSON。
```

`backend/prompts/hr_manager.txt`:

```
你是「HR 主管」。给你岗位 JD 与所有通过初筛候选人的评估结果，请做最终裁决，输出 JSON：
{
  "rankings": [{"resume_id": 候选人ID, "grade": "A/B/C", "rank": 名次从1开始, "comment": "一句话综合评价"}],
  "summary": "整批候选人的总体结论（梯队情况、建议推进哪些面试）"
}
规则：
1. grade 划分：A=强烈推荐面试，B=可以面，C=备选/不建议；
2. rank 按（四维评分均值 + 初筛通过度）综合排序，resume_id 必须与输入一致，不得增删候选人；
3. 只输出 JSON。
```

- [ ] **Step 2: 写失败测试**

`backend/tests/test_roles.py`:

```python
import json
from app.pipeline.roles import (
    analyze_jd, extract_profile, screen_resume, evaluate_resume, summarize_ranking,
)
from app.schemas import JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport


class RoleLLMFake:
    """按 role 返回预制 JSON。"""
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def chat_json(self, role, system_prompt, user_prompt, schema, **kw):
        self.calls.append({"role": role, "user_prompt": user_prompt})
        return schema.model_validate(self.responses[role])


JD = JDParsed(responsibilities=["负责服务端开发"],
              hard_requirements=[{"description": "本科及以上", "weight": 0.5}],
              bonus_items=["有大型项目经验"])
PROFILE = {"name": "张三", "education": [], "work_experience": [],
           "skills": ["Go"], "projects": [], "certificates": []}


async def test_analyze_jd():
    llm = RoleLLMFake({"jd_analyst": JD.model_dump()})
    out = await analyze_jd(llm, "资深后端工程师，要求本科...")
    assert out.hard_requirements[0].weight == 0.5


async def test_extract_profile_passes_resume_text():
    llm = RoleLLMFake({"extractor": PROFILE})
    out = await extract_profile(llm, "张三的简历全文", resume_id=1)
    assert out.name == "张三"
    assert "张三的简历全文" in llm.calls[0]["user_prompt"]


async def test_screen_resume_receives_both_inputs():
    llm = RoleLLMFake({"screener": {"passed": False, "checks": [], "reject_reason": "学历不符"}})
    out = await screen_resume(llm, JD, ResumeProfile.model_validate(PROFILE), resume_id=1)
    assert out.passed is False
    prompt = llm.calls[0]["user_prompt"]
    assert "本科及以上" in prompt and "张三" in prompt  # JD 与档案都要在提示词里


async def test_evaluate_resume():
    resp = {"skill_match": 80, "experience_match": 70, "stability": 90, "potential": 60,
            "highlights": ["x"], "risks": ["y"], "gaps": ["z"], "interview_questions": ["q"]}
    llm = RoleLLMFake({"interviewer": resp})
    out = await evaluate_resume(llm, JD, ResumeProfile.model_validate(PROFILE), resume_id=1)
    assert out.skill_match == 80


async def test_summarize_ranking():
    resp = {"rankings": [{"resume_id": 1, "grade": "A", "rank": 1, "comment": "强推"}],
            "summary": "总体优秀"}
    llm = RoleLLMFake({"hr_manager": resp})
    out = await summarize_ranking(llm, JD, [{"resume_id": 1, "profile": PROFILE}])
    assert out.rankings[0].rank == 1
    assert "1" in llm.calls[0]["user_prompt"]  # resume_id 出现在提示词中
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_roles.py -v`
Expected: FAIL（`No module named 'app.pipeline'`）

- [ ] **Step 4: 实现 roles.py**

`backend/app/pipeline/__init__.py` 空文件。`backend/app/pipeline/roles.py`:

```python
import json
from pathlib import Path
from app.schemas import (
    JDParsed, ResumeProfile, ScreeningResult, EvaluationResult, FinalReport,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def analyze_jd(llm, jd_text: str, task_id=None) -> JDParsed:
    return await llm.chat_json("jd_analyst", _prompt("jd_analyst"),
                               f"JD 原文：\n{jd_text}", JDParsed, task_id=task_id)


async def extract_profile(llm, resume_text: str, resume_id: int, task_id=None) -> ResumeProfile:
    return await llm.chat_json("extractor", _prompt("extractor"),
                               f"简历文本：\n{resume_text}", ResumeProfile,
                               task_id=task_id)


async def screen_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile,
                        resume_id: int, task_id=None) -> ScreeningResult:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"候选人档案（resume_id={resume_id}）：\n{_dump(profile.model_dump())}")
    return await llm.chat_json("screener", _prompt("screener"), user,
                               ScreeningResult, task_id=task_id)


async def evaluate_resume(llm, jd_parsed: JDParsed, profile: ResumeProfile,
                          resume_id: int, task_id=None) -> EvaluationResult:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"候选人档案（resume_id={resume_id}）：\n{_dump(profile.model_dump())}")
    return await llm.chat_json("interviewer", _prompt("interviewer"), user,
                               EvaluationResult, task_id=task_id)


async def summarize_ranking(llm, jd_parsed: JDParsed, items: list[dict],
                            task_id=None) -> FinalReport:
    user = (f"结构化 JD：\n{_dump(jd_parsed.model_dump())}\n\n"
            f"通过初筛的候选人评估结果：\n{_dump(items)}")
    return await llm.chat_json("hr_manager", _prompt("hr_manager"), user,
                               FinalReport, task_id=task_id)
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_roles.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/prompts backend/app/pipeline backend/tests/test_roles.py
git commit -m "feat: 五角色提示词与流水线角色函数"
```

---

### Task 8: SSE 事件总线与流水线编排

**Files:**
- Create: `backend/app/pipeline/events.py`, `backend/app/pipeline/runner.py`
- Test: `backend/tests/test_runner.py`

**Interfaces:**
- Consumes: Task 2 模型、Task 4 LLMClient、Task 6 parse_image、Task 7 roles
- Produces:
  - `app.pipeline.events.EventBus`（模块级单例 `event_bus = EventBus()`）:
    - `subscribe(task_id: int) -> asyncio.Queue`、`unsubscribe(task_id: int, q: asyncio.Queue)`
    - `emit(task_id: int, event: dict)`（非阻塞 put；event 形如 `{"type": "resume_status", "resume_id": 3, "status": "evaluating", "detail": "..."}`）
  - `app.pipeline.runner.run_task(task_id: int)`（async，后台任务入口，内部自建 DB Session）：
    1. Task.status → `running`（复用字符串 `pending`，JDParsed 完成前用 `parsing`）；emit `task_started`
    2. `analyze_jd` → 存 `Task.jd_parsed`；emit `jd_parsed`
    3. 逐份简历（`asyncio.Semaphore(settings.max_concurrency)` 并行）：
       - `parsing`：文本类走 `parse_resume_sync`；PDF `needs_image_channel` 或 source_type=image 走 `parse_image`；解析失败 → `failed` + error_message，emit 后跳过
       - `extracting`：`extract_profile` → 存 profile
       - `screening`：`screen_resume` → 存 screening；未通过 → 终态 `done`（final_grade="D"，表筛选淘汰，detail 里注明），emit
       - `evaluating`：`evaluate_resume` → 存 evaluation
       - LLMError / `asyncio.TimeoutError`（单步 `asyncio.wait_for(..., timeout=settings.step_timeout)`）→ 该简历 `needs_review`
    4. 全部完成后 `summarize_ranking`（只含通过初筛者）→ 存 Task.summary_report；为每个 resume 写 `final_grade` / `final_rank`；Task.status → `done`；emit `task_done`
    5. 任何未捕获异常 → Task.status=`failed`，emit `task_failed`
  - 生产 VLM 实现：`runner.py` 中 `app.parsers.image_parser._vlm_transcribe` 装配真实实现（用 LLMClient 的底层 AsyncOpenAI 发送 image_url base64 消息）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_runner.py`:

```python
import asyncio
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
def seed(db_session):
    task = Task(jd_raw="JD文本", status="pending")
    db_session.add(task)
    db_session.flush()
    r1 = Resume(task_id=task.id, filename="a.txt", source_type="text", status="pending")
    r2 = Resume(task_id=task.id, filename="b.txt", source_type="text", status="pending")
    db_session.add_all([r1, r2])
    db_session.commit()
    return task, r1, r2


async def test_pipeline_full_flow(db_session, seed):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r1.id, r2.id]
    runner_mod._set_session_factory(lambda: (lambda: db_session)())  # 见 Step 4 说明

    events = []
    bus = EventBus()
    q = bus.subscribe(task.id)

    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "event_bus", bus):
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


async def test_screen_reject_short_circuit(db_session, seed):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r1.id]
    original_chat = llm.chat_json

    async def chat_json(role, *a, **kw):
        if role == "screener":
            return ScreeningResult(passed=False, checks=[], reject_reason="学历不符")
        return await original_chat(role, *a, **kw)
    llm.chat_json = chat_json
    runner_mod._set_session_factory(lambda: (lambda: db_session)())

    with patch.object(runner_mod, "LLMClient", return_value=llm):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    rejected = db_session.get(Resume, r1.id)
    evaluated = db_session.get(Resume, r2.id)
    assert rejected.final_grade == "D"          # 初筛淘汰
    assert rejected.evaluation is None           # 未进入面评
    assert evaluated.evaluation is not None
    # HR 汇总只含通过者
    assert db_session.get(Task, task.id).status == "done"


async def test_llm_failure_marks_needs_review(db_session, seed):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    original_chat = llm.chat_json

    async def chat_json(role, *a, **kw):
        if role == "extractor":
            from app.llm import LLMError
            raise LLMError("boom", attempts=3)
        return await original_chat(role, *a, **kw)
    llm.chat_json = chat_json
    runner_mod._set_session_factory(lambda: (lambda: db_session)())

    with patch.object(runner_mod, "LLMClient", return_value=llm):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    assert db_session.get(Resume, r1.id).status == "needs_review"
    assert db_session.get(Resume, r2.id).status == "done"


async def test_parse_failure_marks_failed(db_session, seed):
    task, r1, r2 = seed
    llm = _mk_profile_llm()
    llm.chat_json.resume_ids = [r2.id]
    runner_mod._set_session_factory(lambda: (lambda: db_session)())

    def boom(filename, data):
        from app.parsers import ParseError
        raise ParseError("bad file")
    with patch.object(runner_mod, "LLMClient", return_value=llm), \
         patch.object(runner_mod, "parse_resume_sync", side_effect=boom):
        await runner_mod.run_task(task.id)

    db_session.expire_all()
    assert db_session.get(Resume, r1.id).status == "failed"
    assert db_session.get(Resume, r1.id).error_message == "bad file"
    assert db_session.get(Resume, r2.id).status == "done"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_runner.py -v`
Expected: FAIL（`No module named 'app.pipeline.runner'`）

- [ ] **Step 3: 实现 events.py 与 runner.py**

`backend/app/pipeline/events.py`:

```python
import asyncio


class EventBus:
    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, task_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(q)
        return q

    def unsubscribe(self, task_id: int, q: asyncio.Queue):
        self._subscribers.get(task_id, set()).discard(q)

    def emit(self, task_id: int, event: dict):
        for q in self._subscribers.get(task_id, set()):
            q.put_nowait(event)


event_bus = EventBus()
```

`backend/app/pipeline/runner.py`:

```python
import asyncio
import base64
import json
import app.parsers.image_parser as image_parser_mod
from app.config import get_settings
from app.db import SessionLocal
from app.llm import LLMClient, LLMError
from app.models import Task, Resume
from app.parsers import ParseError
from app.parsers.image_parser import parse_image
from app.parsers.pdf_parser import parse_pdf  # noqa: F401  (PDF needs_image_channel 由 parse_resume_sync 返回)
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
        jd_parsed = await roles.analyze_jd(llm, task.jd_raw, task_id=task_id)
        task.jd_parsed = jd_parsed.model_dump()
        db.commit()
        _emit(task_id, type="jd_parsed")

        # 2. 简历并行流水线
        sem = asyncio.Semaphore(settings.max_concurrency)
        resumes = list(task.resumes)

        async def process(resume: Resume):
            async with sem:
                await _process_resume(db, llm, task, resume)

        await asyncio.gather(*(process(r) for r in resumes))

        # 3. HR 主管汇总（只含通过初筛、有 evaluation 者）
        passed = [r for r in resumes if r.screening and r.screening.get("passed")]
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


async def _process_resume(db, llm, task: Task, resume: Resume):
    rid, tid = resume.id, task.id
    try:
        # --- parsing ---
        resume.status = "parsing"
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="parsing")
        if resume.source_type == "image":
            parsed = await asyncio.wait_for(
                parse_image(resume.filename, _load_file(resume), llm, settings),
                timeout=settings.step_timeout)
        else:
            data = _load_file(resume)
            result = await asyncio.wait_for(
                asyncio.to_thread(_parse_sync, resume.filename, data),
                timeout=settings.step_timeout)
            if result.needs_image_channel:
                parsed = await asyncio.wait_for(
                    parse_image(resume.filename, data, llm, settings),
                    timeout=settings.step_timeout)
            else:
                parsed = result
        resume.raw_text = parsed.text
        resume.parse_meta = parsed.parse_meta

        # --- extracting ---
        resume.status = "extracting"
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="extracting")
        profile = await asyncio.wait_for(
            roles.extract_profile(llm, resume.raw_text, rid, task_id=tid),
            timeout=settings.step_timeout)
        resume.profile = profile.model_dump()

        # --- screening ---
        resume.status = "screening"
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="screening")
        screening = await asyncio.wait_for(
            roles.screen_resume(llm, _jd(task), profile, rid, task_id=tid),
            timeout=settings.step_timeout)
        resume.screening = screening.model_dump()

        if not screening.passed:
            resume.status = "done"  # 终态：初筛淘汰，汇总阶段标 D
            db.commit()
            _emit(tid, type="resume_status", resume_id=rid, status="done",
                  detail=f"初筛未通过：{screening.reject_reason}")
            return

        # --- evaluating ---
        resume.status = "evaluating"
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="evaluating")
        evaluation = await asyncio.wait_for(
            roles.evaluate_resume(llm, _jd(task), profile, rid, task_id=tid),
            timeout=settings.step_timeout)
        resume.evaluation = evaluation.model_dump()
        resume.status = "done"
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="done",
              detail="评估完成")
    except (LLMError, asyncio.TimeoutError) as e:
        db.rollback()
        r = db.get(Resume, rid)
        r.status = "needs_review"
        r.error_message = str(e)
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="needs_review",
              detail=str(e))
    except ParseError as e:
        db.rollback()
        r = db.get(Resume, rid)
        r.status = "failed"
        r.error_message = str(e)
        db.commit()
        _emit(tid, type="resume_status", resume_id=rid, status="failed",
              detail=str(e))


def _jd(task: Task):
    from app.schemas import JDParsed
    return JDParsed.model_validate(task.jd_parsed)


def _parse_sync(filename: str, data: bytes):
    from app.parsers import parse_resume_sync
    return parse_resume_sync(filename, data)


def _load_file(resume: Resume) -> bytes:
    from pathlib import Path
    path = Path(settings.uploads_dir) / str(resume.task_id) / resume.filename
    return path.read_bytes()
```

补充两点：
1. **文件存储**：Task 9 的 API 上传时把文件写到 `{settings.uploads_dir}/{task_id}/{filename}`（纯文本粘贴写为 `{i}_pasted.txt`），`source_type` 按扩展名判：`IMAGE_EXTS` → `image`，`.pdf` → `pdf`，`.docx` → `docx`，其余 → `text`。
2. **VLM 生产实现**：在 `runner.py` 底部装配（单测不受影响，因为 `parse_image` 测试全部自己 patch）：

```python
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
```

并在 `run_task` 创建 `llm` 后绑定：

```python
async def _vlm_with_prompt(image, model, prompt_):
    return await _vlm_transcribe_real(llm, image, model, prompt_)
image_parser_mod._vlm_transcribe = _vlm_with_prompt
```

- [ ] **Step 4: 运行确认通过**

`_set_session_factory` 的测试用法说明：测试传入的工厂返回一个"返回 db_session 的函数"，即 `runner.run_task` 里 `db = _session_factory()` 得到 callable，再 `db()` 拿 session——为避免绕弯，实现直接改为 `db = _session_factory() if callable(_session_factory()) is None else _session_factory()()`。**简化方案**：把 runner 里改成

```python
_db_or_factory = _session_factory()
db = _db_or_factory() if callable(_db_or_factory) else _db_or_factory
```

测试里 `_set_session_factory(lambda: db_session)` 直接返回 session（不可再调用则直接用）。按此简化版实现，测试代码中的 `lambda: (lambda: db_session)()` 一律改为 `lambda: db_session`。

Run: `cd backend && python -m pytest tests/test_runner.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/events.py backend/app/pipeline/runner.py backend/tests/test_runner.py
git commit -m "feat: SSE 事件总线与多角色流水线编排"
```

---

### Task 9: REST API（任务创建/详情/SSE/导出）与 FastAPI 入口

**Files:**
- Create: `backend/app/routers/__init__.py`, `backend/app/routers/tasks.py`, `backend/app/routers/resumes.py`, `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 2/4/8 全部模块
- Produces:
  - `POST /api/tasks`（multipart：`jd_file?: UploadFile`、`jd_text?: str`、`resumes?: list[UploadFile]`、`pasted_texts?: list[str]`）→ `{"task_id": int}`；jd_file 与 jd_text 至少一项；简历总数 ≥1 且 ≤10；创建后 `asyncio.create_task(run_task(task_id))` 后台启动
  - `GET /api/tasks/{id}` → `{"task_id", "status", "jd_parsed", "resumes": [{"id","filename","status","final_grade","final_rank"}], "summary_report"}`
  - `GET /api/tasks/{id}/events` → SSE（`StreamingResponse(media_type="text/event-stream")`，订阅 EventBus，`task_done`/`task_failed` 后关闭）
  - `GET /api/tasks/{id}/export?format=md|xlsx` → Markdown 文本 或 Excel（openpyxl，列：排名/姓名/文件/分档/四维分/初筛结论）
  - `GET /api/resumes/{id}/report` → 单人完整报告
  - `GET /api/health` → `{"llm": bool}`（调用 LLMClient.health_check）
  - `app.main.app`（FastAPI 实例；startup 时 `Base.metadata.create_all(engine)`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_api.py`:

```python
import io
import json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


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


def test_get_task_detail(db_session, seed_task):
    c = _client()
    resp = c.get(f"/api/tasks/{seed_task.id}")
    body = resp.json()
    assert body["status"] == "pending"
    assert len(body["resumes"]) == 2


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


def test_sse_stream(db_session, seed_task):
    c = _client()
    with c.get(f"/api/tasks/{seed_task.id}/events", stream=True) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: FAIL（`No module named 'app.main'`）

- [ ] **Step 3: 实现 API**

conftest.py 追加（供 API 测试覆盖 get_db 与造数）：

```python
def _testing_session():
    """FastAPI dependency_overrides 用的 session 依赖。"""
    yield _shared_session
```

同时在 conftest 里加模块级 `_shared_session = None`，并在 `db_session` fixture 中赋值 `_shared_session = session`。

`seed_task` / `seed_evaluated_resume` fixtures 也加到 conftest.py：

```python
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
```

`backend/app/routers/__init__.py` 空文件。

`backend/app/routers/tasks.py`:

```python
import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
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
    resumes: list[UploadFile] = File(default=[]),
    pasted_texts: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    if not jd_file and not (jd_text and jd_text.strip()):
        raise HTTPException(422, "必须提供 JD 文件或 JD 文本")
    n = len([r for r in resumes if r.filename]) + len([t for t in pasted_texts if t and t.strip()])
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
    for f in resumes:
        if not f.filename:
            continue
        data = await f.read()
        (upload_dir / f.filename).write_bytes(data)
        db.add(Resume(task_id=task.id, filename=f.filename,
                      source_type=_source_type(f.filename), status="pending"))
    for i, text in enumerate(pasted_texts):
        if not (text and text.strip()):
            continue
        name = f"{i}_pasted.txt"
        (upload_dir / name).write_text(text, encoding="utf-8")
        db.add(Resume(task_id=task.id, filename=name, source_type="text", status="pending"))
    db.commit()

    asyncio.create_task(run_task(task.id))
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
async def task_events(task_id: int):
    q = event_bus.subscribe(task_id)

    async def gen():
        try:
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
    if task.summary_report:
        lines += [task.summary_report.get("summary", ""), ""]
        lines += ["| 排名 | 分档 | 简历 | 评价 |", "|---|---|---|---|"]
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
    rows = sorted(task.summary_report.get("rankings", [{"resume_id": r.id} for r in task.resumes]),
                  key=lambda x: x.get("rank", 999))
    for item in rows:
        r = next(r for r in task.resumes if r.id == item["resume_id"])
        ev = r.evaluation or {}
        ws.append([item.get("rank"), (r.profile or {}).get("name", ""), r.filename,
                   r.final_grade, ev.get("skill_match"), ev.get("experience_match"),
                   ev.get("stability"), ev.get("potential"),
                   "通过" if (r.screening or {}).get("passed") else "淘汰"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Depends 引用
from fastapi import Depends  # noqa: E402
```

（实现时把 `from fastapi import Depends` 移到文件顶部 import 区。）

`backend/app/routers/resumes.py`:

```python
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Resume

router = APIRouter(prefix="/api")


@router.get("/resumes/{resume_id}/report")
def resume_report(resume_id: int, db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if not r:
        raise HTTPException(404, "简历不存在")
    return {
        "id": r.id,
        "filename": r.filename,
        "status": r.status,
        "parse_meta": r.parse_meta,
        "raw_text": r.raw_text,
        "profile": r.profile,
        "screening": r.screening,
        "evaluation": r.evaluation,
        "final_grade": r.final_grade,
        "final_rank": r.final_rank,
        "error_message": r.error_message,
    }
```

`backend/app/main.py`:

```python
from fastapi import FastAPI
from app.db import Base, engine
from app.routers import tasks, resumes

app = FastAPI(title="简历审阅系统")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)


app.include_router(tasks.router)
app.include_router(resumes.router)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: 7 passed

- [ ] **Step 5: 全量回归**

Run: `cd backend && python -m pytest -v`
Expected: 全部通过（前 8 个 Task 的测试无回归）

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: REST API 任务创建/SSE 进度/导出与健康检查"
```

---

### Task 10: Docker Compose 与部署配置

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.dockerignore`
- Test: 手动构建冒烟（本地无私有模型时用 `docker compose build` 验证可构建性）

**Interfaces:**
- Produces: `docker compose up -d` 可启动 `db` + `api` + `web`（+ `--profile ocr` 时含 `ocr`）

- [ ] **Step 1: 写 .env.example 与 .dockerignore**

`.env.example`:

```
# PostgreSQL
POSTGRES_USER=resume
POSTGRES_PASSWORD=resume
POSTGRES_DB=resume_review
DATABASE_URL=postgresql+psycopg://resume:resume@db:5432/resume_review

# 私有大模型（OpenAI 兼容）
LLM_BASE_URL=http://your-vllm-host:8000/v1
LLM_API_KEY=EMPTY
LLM_MODEL=qwen2.5-72b-instruct
# 多模态兜底模型（留空禁用图片 VLM 兜底）
LLM_VLM_MODEL=qwen-vl
# OCR
OCR_BASE_URL=http://ocr:8866
OCR_CONFIDENCE_THRESHOLD=0.85
```

`.dockerignore`（根目录）:

```
**/__pycache__
**/.pytest_cache
**/node_modules
**/uploads
.git
```

- [ ] **Step 2: 写 docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-resume}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-resume}
      POSTGRES_DB: ${POSTGRES_DB:-resume_review}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-resume}"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: ./backend
    env_file: .env
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://resume:resume@db:5432/resume_review}
    volumes:
      - uploads:/app/uploads
    depends_on:
      db:
        condition: service_healthy
    expose:
      - "8000"

  web:
    build: ./frontend
    ports:
      - "8080:80"
    depends_on:
      - api

  ocr:
    image: paddlepaddle/paddleocr:latest
    profiles: ["ocr"]
    # 部署 PaddleOCR HTTP 服务；具体启动命令按所选镜像文档调整，
    # 必须暴露 POST 接口返回 {"lines": [{"text": "...", "confidence": 0.98}]}
    expose:
      - "8866"

volumes:
  pgdata:
  uploads:
```

- [ ] **Step 3: 写 backend/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY pytest.ini .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: 写前端 Dockerfile 与 nginx.conf**（前端源码在 Task 11 创建，本任务先落配置文件）

`frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`frontend/nginx.conf`:

```nginx
server {
    listen 80;
    client_max_body_size 50m;

    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        # SSE 必需
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 5: 构建冒烟**

Run: `docker compose build api`
Expected: api 镜像构建成功（web 留待 Task 11 前端就绪后验证）

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example .dockerignore backend/Dockerfile frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: Docker Compose 一键部署配置"
```

---

### Task 11: 前端（Vue3 三页面）

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/main.js`, `frontend/src/api.js`, `frontend/src/views/TaskCreate.vue`, `frontend/src/views/TaskProgress.vue`, `frontend/src/views/TaskResult.vue`
- Test: `npm run build` 通过；联调冒烟在 Task 12

**Interfaces:**
- Consumes: Task 9 全部 API
- Produces: `npm run build` 产出 `dist/`；页面路由 `/`（创建）、`/task/:id/progress`（进度）、`/task/:id`（结果）

- [ ] **Step 1: 脚手架文件**

`frontend/package.json`:

```json
{
  "name": "resume-review-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "element-plus": "^2.7.0",
    "echarts": "^5.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.2.0"
  }
}
```

`frontend/vite.config.js`:

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

`frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>简历审阅系统</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

`frontend/src/main.js`:

```javascript
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import TaskCreate from './views/TaskCreate.vue'
import TaskProgress from './views/TaskProgress.vue'
import TaskResult from './views/TaskResult.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: TaskCreate },
    { path: '/task/:id/progress', component: TaskProgress },
    { path: '/task/:id', component: TaskResult },
  ],
})

createApp(App).use(ElementPlus).use(router).mount('#app')
```

`frontend/src/App.vue`:

```vue
<template>
  <el-container style="max-width: 1100px; margin: 0 auto; padding: 24px">
    <el-header style="font-size: 22px; font-weight: bold; height: auto; margin-bottom: 16px">
      简历审阅系统
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>
</template>
```

- [ ] **Step 2: API 封装**

`frontend/src/api.js`:

```javascript
export async function createTask({ jdFile, jdText, resumeFiles, pastedTexts }) {
  const fd = new FormData()
  if (jdFile) fd.append('jd_file', jdFile)
  if (jdText) fd.append('jd_text', jdText)
  resumeFiles.forEach((f) => fd.append('resumes', f))
  pastedTexts.forEach((t) => fd.append('pasted_texts', t))
  const resp = await fetch('/api/tasks', { method: 'POST', body: fd })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `创建失败 (${resp.status})`)
  }
  return resp.json()
}

export async function getTask(id) {
  const resp = await fetch(`/api/tasks/${id}`)
  if (!resp.ok) throw new Error('任务不存在')
  return resp.json()
}

export async function getResumeReport(id) {
  const resp = await fetch(`/api/resumes/${id}/report`)
  if (!resp.ok) throw new Error('报告不存在')
  return resp.json()
}

export function exportUrl(id, format) {
  return `/api/tasks/${id}/export?format=${format}`
}

export function subscribeEvents(taskId, onEvent) {
  const es = new EventSource(`/api/tasks/${taskId}/events`)
  es.onmessage = (e) => onEvent(JSON.parse(e.data))
  return es
}
```

- [ ] **Step 3: 任务创建页**

`frontend/src/views/TaskCreate.vue`:

```vue
<template>
  <el-card>
    <h3>创建筛选任务</h3>
    <el-form label-width="90px">
      <el-form-item label="JD">
        <el-input v-model="jdText" type="textarea" :rows="6"
                  placeholder="粘贴职位描述，或选择 JD 文件" />
      </el-form-item>
      <el-form-item label="JD 文件">
        <input type="file" accept=".txt,.pdf,.docx" @change="onJdFile" />
      </el-form-item>
      <el-form-item label="简历文件">
        <input type="file" multiple accept=".pdf,.docx,.png,.jpg,.jpeg,.txt" @change="onResumes" />
        <el-tag v-for="(f, i) in resumeFiles" :key="i" closable style="margin-left: 8px"
                @close="resumeFiles.splice(i, 1)">{{ f.name }}</el-tag>
      </el-form-item>
      <el-form-item label="粘贴简历">
        <el-input v-model="pastedText" type="textarea" :rows="4"
                  placeholder="也可直接粘贴纯文本简历（与文件合计不超过 10 份）" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="submitting" @click="submit">开始筛选</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTask } from '../api'

const router = useRouter()
const jdText = ref('')
const jdFile = ref(null)
const resumeFiles = ref([])
const pastedText = ref('')
const submitting = ref(false)

function onJdFile(e) { jdFile.value = e.target.files[0] || null }
function onResumes(e) { resumeFiles.value = Array.from(e.target.files || []) }

async function submit() {
  if (!jdText.value && !jdFile.value) return ElMessage.warning('请提供 JD')
  const total = resumeFiles.value.length + (pastedText.value.trim() ? 1 : 0)
  if (total < 1) return ElMessage.warning('请至少提供一份简历')
  if (total > 10) return ElMessage.warning('单次任务最多 10 份简历')
  submitting.value = true
  try {
    const { task_id } = await createTask({
      jdFile: jdFile.value, jdText: jdText.value,
      resumeFiles: resumeFiles.value, pastedTexts: pastedText.value.trim() ? [pastedText.value] : [],
    })
    router.push(`/task/${task_id}/progress`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>
```

- [ ] **Step 4: 进度页（SSE）**

`frontend/src/views/TaskProgress.vue`:

```vue
<template>
  <el-card>
    <h3>筛选进度（任务 #{{ $route.params.id }}）</h3>
    <el-table :data="rows">
      <el-table-column prop="filename" label="简历" />
      <el-table-column label="状态">
        <template #default="{ row }">
          <el-tag :type="tagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          <span style="margin-left: 8px; color: #999">{{ row.detail }}</span>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="finished" style="margin-top: 16px">
      <el-button type="primary" @click="$router.push(`/task/${$route.params.id}`)">
        查看筛选结果
      </el-button>
    </div>
  </el-card>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { getTask, subscribeEvents } from '../api'

const route = useRoute()
const rows = ref([])
const finished = ref(false)
let es = null

const LABELS = {
  pending: '等待', parsing: '解析中', extracting: '信息提取', screening: '初筛',
  evaluating: '深度评估', done: '完成', failed: '解析失败', needs_review: '需人工复核',
}

function statusLabel(s) { return LABELS[s] || s }
function tagType(s) {
  return { done: 'success', failed: 'danger', needs_review: 'warning' }[s] || 'info'
}

onMounted(async () => {
  const task = await getTask(route.params.id)
  rows.value = task.resumes.map((r) => ({ ...r, detail: '' }))
  if (task.status === 'done' || task.status === 'failed') { finished.value = true; return }
  es = subscribeEvents(route.params.id, (ev) => {
    if (ev.type === 'resume_status') {
      const row = rows.value.find((r) => r.id === ev.resume_id)
      if (row) { row.status = ev.status; row.detail = ev.detail || '' }
    } else if (ev.type === 'task_done' || ev.type === 'task_failed') {
      finished.value = true
      es.close()
    }
  })
})
onUnmounted(() => es && es.close())
</script>
```

- [ ] **Step 5: 结果页（排名 + 单人详情 + 雷达图）**

`frontend/src/views/TaskResult.vue`:

```vue
<template>
  <el-card>
    <div style="display: flex; justify-content: space-between; align-items: center">
      <h3>筛选结果（任务 #{{ $route.params.id }}）</h3>
      <div>
        <el-button @click="download('md')">导出 Markdown</el-button>
        <el-button @click="download('xlsx')">导出 Excel</el-button>
      </div>
    </div>
    <el-table :data="ranked" @row-click="selectResume" highlight-current-row>
      <el-table-column prop="final_rank" label="排名" width="70" />
      <el-table-column label="分档" width="70">
        <template #default="{ row }">
          <el-tag :type="{ A: 'success', B: 'warning', C: 'info', D: 'danger' }[row.final_grade]">
            {{ row.final_grade }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="简历" />
      <el-table-column prop="comment" label="综合评价" />
    </el-table>

    <el-drawer v-model="drawer" :title="detail ? detail.filename : ''" size="55%">
      <div v-if="detail">
        <h4>基本信息</h4>
        <p>姓名：{{ detail.profile?.name || '未知' }}；
          技能：{{ (detail.profile?.skills || []).join('、') || '—' }}</p>
        <div v-if="radarOption" ref="radarEl" style="width: 100%; height: 300px"></div>
        <h4>亮点</h4>
        <ul><li v-for="h in detail.evaluation?.highlights || []" :key="h">{{ h }}</li></ul>
        <h4>风险点</h4>
        <ul><li v-for="r in detail.evaluation?.risks || []" :key="r">{{ r }}</li></ul>
        <h4>与 JD 差距</h4>
        <ul><li v-for="g in detail.evaluation?.gaps || []" :key="g">{{ g }}</li></ul>
        <h4>面试建议问题</h4>
        <ol><li v-for="q in detail.evaluation?.interview_questions || []" :key="q">{{ q }}</li></ol>
      </div>
    </el-drawer>
  </el-card>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { getTask, getResumeReport, exportUrl } from '../api'

const route = useRoute()
const task = ref(null)
const detail = ref(null)
const drawer = ref(false)
const radarEl = ref(null)

const ranked = computed(() => {
  if (!task.value) return []
  const comments = {}
  ;(task.value.summary_report?.rankings || []).forEach((r) => (comments[r.resume_id] = r.comment))
  return [...task.value.resumes].sort(
    (a, b) => (a.final_rank || 99) - (b.final_rank || 99))
    .map((r) => ({ ...r, comment: comments[r.id] || (r.final_grade === 'D' ? '初筛未通过' : '') }))
})

async function selectResume(row) {
  detail.value = await getResumeReport(row.id)
  drawer.value = true
  await nextTick()
  const ev = detail.value.evaluation
  if (ev && radarEl.value) {
    echarts.init(radarEl.value).setOption({
      radar: {
        indicator: [
          { name: '技能匹配', max: 100 }, { name: '经验匹配', max: 100 },
          { name: '稳定性', max: 100 }, { name: '潜力', max: 100 }],
      },
      series: [{ type: 'radar', data: [{
        value: [ev.skill_match, ev.experience_match, ev.stability, ev.potential] }] }],
    })
  }
}

function download(format) {
  window.open(exportUrl(route.params.id, format))
}

onMounted(async () => { task.value = await getTask(route.params.id) })
</script>
```

- [ ] **Step 6: 构建验证**

Run: `cd frontend && npm install && npm run build`
Expected: `dist/` 生成，无报错

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: Vue3 前端三页面（创建/进度/结果）"
```

- [ ] **Step 8: 补跑 web 镜像构建**

Run: `docker compose build web`
Expected: 构建成功

```bash
git add -A && git commit -m "chore: 前端镜像构建验证" --allow-empty
```

---

### Task 12: 端到端验收

**Files:**
- Create: `samples/jd_sample.txt`, `samples/make_samples.py`（生成样例简历 PDF/docx/txt 脚本）, `samples/mock_llm.py`（OpenAI 兼容 mock 服务，供无真实模型时 E2E）
- Test: compose 全栈启动 + 手动/脚本走通全流程

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: 写样例生成脚本**

`samples/make_samples.py`:

```python
"""生成端到端验收样例简历。运行：python make_samples.py"""
import io
import fitz
from docx import Document
from pathlib import Path

OUT = Path(__file__).parent
TEXT_OK = ("张三，本科，5 年后端开发经验，精通 Go 与 Python，"
           "负责过日活百万的微服务系统，稳定性高。") * 15
TEXT_SHORT = "王五，大专学历，1 年前端经验。"


def make_pdf(name, text):
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in text.split("。"):
        if line.strip():
            page.insert_text((72, y), line + "。", fontname="china-s")
            y += 20
    doc.save(OUT / name)


def make_docx(name, text):
    d = Document()
    d.add_paragraph(text)
    d.save(OUT / name)


make_pdf("张三_后端.pdf", TEXT_OK)
make_docx("李四_后端.docx", TEXT_OK.replace("张三", "李四"))
(OUT / "王五_前端.txt").write_text(TEXT_SHORT, encoding="utf-8")
print("样例已生成到 samples/")
```

`samples/jd_sample.txt`:

```
岗位：高级后端开发工程师
职责：负责核心业务服务端设计与开发，保障高并发稳定性。
硬性要求：本科及以上学历；5 年及以上后端开发经验；精通 Go 或 Python；有高并发系统经验。
加分项：有微服务架构经验；有开源项目贡献。
```

- [ ] **Step 2: 写 mock LLM 服务（OpenAI 兼容）**

`samples/mock_llm.py`:

```python
"""极简 OpenAI 兼容 mock LLM：按提示词中的角色关键词返回预制 JSON。
运行：uvicorn --app-dir samples mock_llm:app --port 8000"""
import json
import re
from fastapi import FastAPI, Request

app = FastAPI()

JD = {"responsibilities": ["服务端开发"], "hard_requirements": [{"description": "本科", "weight": 0.5}],
      "bonus_items": []}
PROFILE = {"name": "候选人", "education": [], "work_experience": [], "skills": [],
           "projects": [], "certificates": []}
SCREEN_OK = {"passed": True, "checks": [], "reject_reason": None}
SCREEN_REJECT = {"passed": False, "checks": [], "reject_reason": "经验不足"}
EVAL = {"skill_match": 75, "experience_match": 70, "stability": 85, "potential": 65,
        "highlights": ["经验扎实"], "risks": [], "gaps": [],
        "interview_questions": ["介绍最有挑战的项目？"]}
REPORT = {"rankings": [], "summary": "整体符合要求"}  # rankings 由调用方填 resume_id


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "mock"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text = json.dumps(body["messages"], ensure_ascii=False)
    m = re.search(r"resume_id=(\d+)", text)
    rid = int(m.group(1)) if m else 0

    if "jd_analyst" in text or "JD 解析官" in text:
        content = JD
    elif "简历文本" in text and "skills" in text:
        content = PROFILE
    elif "初筛专员" in text:
        content = SCREEN_REJECT if "王五" in text or "1 年" in text else SCREEN_OK
    elif "资深面试官" in text:
        content = EVAL
    else:  # HR 主管
        report = dict(REPORT)
        ids = [int(x) for x in re.findall(r'"resume_id": (\d+)', text)]
        report["rankings"] = [{"resume_id": i, "grade": "B", "rank": n + 1, "comment": "可以面"}
                              for n, i in enumerate(ids)]
        content = report
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
```

- [ ] **Step 3: 全栈启动**

```bash
cd samples && python make_samples.py
cp .env.example .env   # LLM_BASE_URL 指向 mock: http://mock-llm:8000/v1
docker compose up -d --build
docker compose ps
```

Expected: `db`/`api`/`web` 均为 running；`curl http://localhost:8080/api/health` 返回 `{"llm": true}`（mock LLM 需加入 compose 临时跑，或用 `docker run --network` 接入；验收时在 compose 里临时加一个 `mock-llm` 服务映射 `samples/mock_llm.py`）

- [ ] **Step 4: 走通全流程**

```bash
# 创建任务（1 份 pdf + 1 份 docx + 1 份 txt，txt 应被初筛淘汰）
curl -s -X POST http://localhost:8080/api/tasks \
  -F "jd_text=$(cat samples/jd_sample.txt)" \
  -F "resumes=@samples/张三_后端.pdf" \
  -F "resumes=@samples/李四_后端.docx" \
  -F "pasted_texts=王五，大专学历，1 年前端经验。"
```

验证清单：
1. 返回 task_id；浏览器打开 `http://localhost:8080/#/task/{task_id}/progress` 能看到实时进度
2. 完成后结果页显示 3 人：2 人有 A/B/C 分档与排名，王五（粘贴文本）初筛淘汰标 D
3. 点开单人详情：结构化信息、雷达图、面试问题正常渲染
4. `curl "http://localhost:8080/api/tasks/{task_id}/export?format=md"` 输出 Markdown 报告
5. Excel 导出可下载打开
6. `llm_logs` 表有各角色调用记录

- [ ] **Step 5: 收尾**

```bash
docker compose down -v   # 清理验收环境（保留代码与文档）
git add samples
git commit -m "test: 端到端验收样例与 mock LLM"
```

---

## 依赖关系

```
Task 1 → Task 2 → Task 3 ─┐
                           ├→ Task 4 → Task 7 → Task 8 → Task 9
Task 5（依赖 1）───────────┤
Task 6（依赖 4、5）────────┘
Task 9 → Task 10（部署）→ Task 11（前端）→ Task 12（E2E）
```

Task 5/6 与 Task 7 可并行；Task 10 与 Task 11 可并行。

## 自审记录

- **Spec 覆盖**：五角色流水线（Task 7/8）、双通道 OCR+VLM 兜底+校正（Task 6）、四种简历来源（Task 5/6）、JSONB（Task 2）、SSE（Task 8/9/11）、导出 md/xlsx（Task 9/11）、健康检查预检（Task 9）、错误处理矩阵（Task 8 各分支测试）、PostgreSQL+Compose（Task 10）、A/B/C+D 淘汰（Task 8 汇总逻辑）、llm_logs（Task 4）——均已对应任务。
- **占位符**：无 TBD/TODO；`_vlm_transcribe` 生产实现已在 Task 8 给出真实代码。
- **类型一致性**：`chat_json(role, system_prompt, user_prompt, schema, task_id=..., model=...)` 各处签名一致；schemas 字段与 roles 测试逐字对齐；`EventBus.emit/subscribe/unsubscribe` 与 runner/router 用法一致。
