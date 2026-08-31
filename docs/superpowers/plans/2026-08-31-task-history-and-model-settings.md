# 任务历史详情 + 模型配置 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「历史任务列表 + 任务执行详情（阶段状态/耗时/tokens）」与「运行参数（模型）配置页（数据库持久化）」两大模块。

**Architecture:** 后端基于现有 SQLAlchemy 模型扩展（stage\_timeline JSON 列、LLMLog.resume\_id、新 AppSetting 表），新增 3 个只读/配置端点；配置通过「DB 覆盖 + 单例 Settings 原地属性赋值」实现热更新（get\_settings() 的 lru\_cache 单例被 tasks.py/runner.py 模块级持有，原地赋值对所有持有者可见）。前端新增 3 个视图（历史列表、执行详情、配置页）+ 全局导航。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + pydantic-settings（后端已栈）；Vue 3 + Element Plus + vue-router（前端已栈）。

***

## 现状分析（Phase 1 探索结论）

| 现状                                                                                                            | 证据                                                                                |
| ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 无任务列表端点，前端无法查看历史                                                                                              | [tasks.py](../../backend/app/routers/tasks.py) 仅有 POST /api/tasks、GET /tasks/{id} |
| Resume.status 有阶段值（parsing/extracting/screening/evaluating/done/failed/needs\_review）但**无时间戳**，任务结束后无法知道各阶段耗时 | [runner.py](../../backend/app/pipeline/runner.py) 只改 status 字段                    |
| LLMLog 记录 role/tokens/duration\_ms 但**无 resume\_id**，无法归到某份简历的某阶段                                             | [llm.py:66-70](../../backend/app/llm.py) `_log` 只写 task\_id                       |
| 配置仅来自 env/.env，`get_settings()` lru\_cache 单例；tasks.py、runner.py 模块级 `settings = get_settings()` 持有同一对象       | [config.py](../../backend/app/config.py)                                          |
| 前端仅 3 个视图、无导航菜单                                                                                               | [main.js](../../frontend/src/main.js)                                             |
| nginx 已有 SPA fallback，新路由可直接用                                                                                 | [nginx.conf](../../frontend/nginx.conf) `try_files ... /index.html`               |
| 测试：conftest.py 内存 SQLite + dependency\_overrides；test\_llm.py 有 FakeAsyncOpenAI 模式                            | backend/tests/                                                                    |

## 已确认的设计决策（用户选定）

1. **配置持久化**：数据库持久化（新表 app\_settings），env 作为初始默认值，页面可覆盖。
2. **配置范围**：全部运行参数（llm\_base\_url、llm\_api\_key、llm\_model、llm\_vlm\_model、llm\_timeout、ocr\_base\_url、ocr\_confidence\_threshold、step\_timeout、max\_concurrency）。`database_url`/`uploads_dir` 为部署级配置，**不可**页面编辑。
3. **执行详情深度**：状态 + 耗时 + tokens（基于 LLMLog 表 + 新增 stage\_timeline 时间戳记录）。

## 关键机制说明（实现者必读）

**配置热更新原理**：`get_settings()` 是 `@lru_cache`，返回**同一个** Settings 实例；`tasks.py`/`runner.py` 模块级 `settings = get_settings()` 持有的是同一对象引用。因此「原地 `setattr` 该单例的属性」即可让所有使用方生效（pydantic v2 BaseSettings 默认非 frozen，可赋值）。`PUT /api/settings` = 校验 → 写 DB → 原地赋值单例。API 启动时（lifespan）从 DB 加载覆盖值。

**JSON 列变更追踪**：SQLAlchemy 的 JSON 列对「就地修改内部元素」不追踪，必须**整体重新赋值**（`entity.stage_timeline = tl`）。

**stage\_timeline 格式**（Task 与 Resume 共用）：

```json
[{"stage": "parsing", "started_at": "2026-08-31T03:00:00.123+00:00",
  "ended_at": "2026-08-31T03:00:02.456+00:00", "status": "ok"}]
```

Task 级阶段：`jd_parse`、`summarize`；Resume 级阶段：`parsing`、`extracting`、`screening`、`evaluating`。失败时 `status: "failed"` 且带 `detail`。

**存量数据迁移**：`Base.metadata.create_all` 只建新表不加列。开发环境推荐 `docker compose down -v` 重置；需保留数据时执行 Task 11 的 ALTER TABLE SQL。

***

## 文件结构总览

| 文件                                    | 动作 | 职责                                                              |
| ------------------------------------- | -- | --------------------------------------------------------------- |
| `backend/app/models.py`               | 修改 | Task/Resume 加 stage\_timeline；LLMLog 加 resume\_id；新增 AppSetting |
| `backend/app/llm.py`                  | 修改 | chat\_json/\_log 透传 resume\_id                                  |
| `backend/app/pipeline/roles.py`       | 修改 | extract/screen/evaluate 传 resume\_id                            |
| `backend/app/pipeline/runner.py`      | 修改 | 阶段时间线记录（start/end/close\_open）                                  |
| `backend/app/routers/tasks.py`        | 修改 | 新增 GET /api/tasks 列表；增强 GET /tasks/{id} 详情                      |
| `backend/app/settings_store.py`       | 新建 | 可编辑键定义、DB 覆盖读写、单例应用                                             |
| `backend/app/routers/settings.py`     | 新建 | GET/PUT /api/settings                                           |
| `backend/app/main.py`                 | 修改 | lifespan 加载 DB 覆盖；注册 settings router                            |
| `backend/tests/test_llm.py`           | 修改 | resume\_id 日志测试                                                 |
| `backend/tests/test_runner.py`        | 修改 | 时间线断言                                                           |
| `backend/tests/test_api.py`           | 修改 | 列表/详情测试                                                         |
| `backend/tests/test_settings.py`      | 新建 | settings\_store + settings 路由测试                                 |
| `frontend/src/api.js`                 | 修改 | listTasks/getSettings/updateSettings                            |
| `frontend/src/main.js`                | 修改 | 新路由                                                             |
| `frontend/src/App.vue`                | 修改 | 全局导航                                                            |
| `frontend/src/views/TaskHistory.vue`  | 新建 | 历史任务列表                                                          |
| `frontend/src/views/TaskDetail.vue`   | 新建 | 执行详情                                                            |
| `frontend/src/views/SettingsView.vue` | 新建 | 配置页                                                             |
| `frontend/src/views/TaskResult.vue`   | 修改 | 加「执行详情」入口                                                       |

**UI 设计规范**（全前端任务遵循，与 frontend-design 技能一致的方向）：统一「专业工具」视觉 —— 页面头部 `标题 + 状态徽标 + 操作按钮` 一行式布局；状态色语义全局统一（pending 灰 / 进行中蓝 / done 绿 / failed 红 / needs\_review 橙）；耗时与 token 数值用 `font-variant-numeric: tabular-nums` 等宽数字；区块标题统一 14px 加粗 + 左侧 3px 强调色竖条；卡片间距 16px。不引入新依赖，基于 Element Plus 现有组件精修。

***

## Task 1: LLM 日志关联简历（LLMLog.resume\_id）

**Files:**

* Modify: `backend/app/models.py`

* Modify: `backend/app/llm.py`

* Modify: `backend/app/pipeline/roles.py`

* Test: `backend/tests/test_llm.py`

* [ ] **Step 1: 写失败测试**（追加到 test\_llm.py 末尾）

```python
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
```

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_llm.py -q -k resume_id`
Expected: FAIL（`chat_json() got an unexpected keyword argument 'resume_id'`）

* [ ] **Step 3: 修改 models.py** — LLMLog 类的 `role` 行之后加：

```python
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id"), nullable=True)
```

* [ ] **Step 4: 修改 llm.py** — `chat_json` 签名与 `_log` 透传：

```python
    async def chat_json(self, role, system_prompt, user_prompt, schema: type[BaseModel],
                        task_id=None, model=None, resume_id=None):
```

`self._log(task_id, role, 0, 0, start)` → `self._log(task_id, role, 0, 0, start, resume_id)`（网络错误分支）；两处成功/校验失败分支的 `self._log(...)` 同样追加第 6 参；`_log` 改为：

```python
    def _log(self, task_id, role, ptok, ctok, start, resume_id=None):
        self.db.add(LLMLog(task_id=task_id, role=role, resume_id=resume_id,
                           prompt_tokens=ptok or 0, completion_tokens=ctok or 0,
                           duration_ms=int((time.monotonic() - start) * 1000)))
        self.db.commit()
```

* [ ] **Step 5: 修改 roles.py** — 三个简历级角色透传（函数签名不变，利用已有的 resume\_id 形参）：

```python
async def extract_profile(llm, resume_text: str, resume_id: int, task_id=None) -> ResumeProfile:
    return await llm.chat_json("extractor", _prompt("extractor"),
                               f"简历文本：\n{resume_text}", ResumeProfile,
                               task_id=task_id, resume_id=resume_id)
```

`screen_resume`、`evaluate_resume` 中的 `chat_json(...)` 同样追加 `resume_id=resume_id`。`analyze_jd`/`summarize_ranking` 不变（任务级）。

* [ ] **Step 6: 运行测试通过**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_llm.py tests/test_runner.py tests/test_roles.py -q`
Expected: 全部 PASS（现有 fake llm 的 `chat_json(..., **kw)` 已兼容新 kwarg）

* [ ] **Step 7: Commit** `git commit -m "feat: LLMLog 关联 resume_id 以支持按简历统计 tokens"`

***

## Task 2: 阶段时间线记录（stage\_timeline）

**Files:**

* Modify: `backend/app/models.py`（Task、Resume 各加一列）

* Modify: `backend/app/pipeline/runner.py`

* Test: `backend/tests/test_runner.py`

* [ ] **Step 1: 写失败测试**（追加到 test\_runner.py；先在文件顶部 import 后加断言进现有 full\_flow 测试）

在 `test_pipeline_full_flow` 的 `for r in task.resumes:` 断言块后追加：

```python
    # 任务级时间线：jd_parse 与 summarize 两阶段均已闭合
    stages = {t["stage"]: t for t in task.stage_timeline}
    assert set(stages) == {"jd_parse", "summarize"}
    for t in task.stage_timeline:
        assert t["started_at"] and t["ended_at"] and t["status"] == "ok"
    # 简历级时间线：四个阶段全部闭合
    for r in task.resumes:
        r_stages = {t["stage"] for t in r.stage_timeline}
        assert r_stages == {"parsing", "extracting", "screening", "evaluating"}
```

新增失败路径测试：

```python
async def test_stage_timeline_closes_open_stages_on_failure(db_session, seed, session_factory):
    task, r1, r2 = seed
    llm = _mk_profile_llm()

    async def boom(*a, **kw):
        raise RuntimeError("llm down")

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
    assert not ext.get("ended_at") is None
```

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_runner.py -q`
Expected: FAIL（stage\_timeline 属性不存在）

* [ ] **Step 3: models.py 加列**（Task 与 Resume 类各加，放在 status 列旁）：

```python
    stage_timeline: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

* [ ] **Step 4: runner.py 实现时间线助手**（文件顶部 import 区加 `from datetime import datetime, timezone`；`_emit` 定义前插入）：

```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _stage_start(entity, stage: str):
    """开启一个阶段。整体重新赋值，确保 JSON 列变更被 SQLAlchemy 追踪。"""
    tl = list(entity.stage_timeline or [])
    tl.append({"stage": stage, "started_at": _now_iso()})
    entity.stage_timeline = tl


def _stage_end(entity, stage: str, status: str = "ok", detail: str | None = None):
    tl = list(entity.stage_timeline or [])
    for t in reversed(tl):
        if t.get("stage") == stage and not t.get("ended_at"):
            t["ended_at"] = _now_iso()
            t["status"] = status
            if detail:
                t["detail"] = detail
            break
    entity.stage_timeline = tl


def _close_open_stages(entity, status: str = "failed", detail: str | None = None):
    """异常收尾：把所有未闭合阶段标记为失败（rollback 后从上次 commit 状态续写）。"""
    tl = list(entity.stage_timeline or [])
    for t in tl:
        if not t.get("ended_at"):
            t["ended_at"] = _now_iso()
            t["status"] = status
            if detail:
                t["detail"] = detail
    entity.stage_timeline = tl
```

* [ ] **Step 5: run\_task 埋点**（对照现有代码逐处插入）：

```python
        task.status = "parsing"
        _stage_start(task, "jd_parse")      # ← 新增
        db.commit()
        _emit(task_id, type="task_started")

        llm = LLMClient(settings, db)
        jd_parsed = await asyncio.wait_for(...)
        _stage_end(task, "jd_parse")        # ← 新增，在 db.commit()（保存 jd_parsed）之前
        task.jd_parsed = jd_parsed.model_dump()
        db.commit()
```

汇总阶段（`if passed:` 块内）：

```python
        if passed:
            _stage_start(task, "summarize")  # ← 新增
            report = await roles.summarize_ranking(llm, jd_parsed, items, task_id=task_id)
            task.summary_report = report.model_dump()
            rank_map = {...}
            for r in resumes:
                ...
            _stage_end(task, "summarize")   # ← 新增，在 task.status = "done" 之前
```

异常分支：

```python
    except Exception as e:
        db.rollback()
        task = db.get(Task, task_id)
        task.status = "failed"
        _close_open_stages(task, detail=str(e))   # ← 新增
        task.summary_report = {"error": str(e)}
        db.commit()
```

* [ ] **Step 6: \_process\_resume 埋点**（四阶段模式一致，`r.status = "xxx"` 后紧跟 `_stage_start`，阶段完成后 `_stage_end`）：

```python
            r.status = "parsing"
            _stage_start(r, "parsing")      # 解析（pdf/docx/图片两条路径共用）
            db.commit()
            _emit(...)
            ...（解析得到 parsed）...
            _stage_end(r, "parsing")        # ← 新增，在 r.raw_text = parsed.text 前
            r.raw_text = parsed.text
            r.parse_meta = parsed.parse_meta

            r.status = "extracting"
            _stage_start(r, "extracting")
            db.commit()
            _emit(...)
            profile = await ...
            _stage_end(r, "extracting")
            r.profile = profile.model_dump()

            r.status = "screening"
            _stage_start(r, "screening")
            db.commit()
            _emit(...)
            screening = await ...
            _stage_end(r, "screening")
            r.screening = screening.model_dump()
```

`evaluating` 阶段同样（`_stage_start(r, "evaluating")` / `r.status = "done"` 前 `_stage_end(r, "evaluating")`）。两个 except 分支在 `db.commit()` 前加：

```python
        except (LLMError, asyncio.TimeoutError) as e:
            db.rollback()
            r = db.get(Resume, resume_id)
            if r is not None:
                _close_open_stages(r, status="needs_review", detail=str(e))  # ← 新增
                r.status = "needs_review"
                ...
        except (ParseError, OSError) as e:
            db.rollback()
            r = db.get(Resume, resume_id)
            if r is not None:
                _close_open_stages(r, detail=str(e))                          # ← 新增
                r.status = "failed"
                ...
```

* [ ] **Step 7: 运行测试通过**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_runner.py -q`
Expected: 全部 PASS

* [ ] **Step 8: Commit** `git commit -m "feat: 记录任务与简历的阶段执行时间线"`

***

## Task 3: 历史任务列表端点 GET /api/tasks

**Files:**

* Modify: `backend/app/routers/tasks.py`

* Test: `backend/tests/test_api.py`

* [ ] **Step 1: 写失败测试**（追加到 test\_api.py；顶部 import 补 `from app.models import Task, Resume, LLMLog`）：

```python
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
```

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_api.py -q -k list_tasks`
Expected: FAIL（404，路由不存在）

* [ ] **Step 3: 实现**（tasks.py 顶部补 `from sqlalchemy import func`、`from app.models import Task, Resume, LLMLog`；在 `create_task` 之前插入）：

```python
@router.get("/tasks")
def list_tasks(page: int = 1, page_size: int = 20, status: str | None = None,
               db: Session = Depends(get_db)):
    page, page_size = max(1, page), min(max(1, page_size), 100)
    q = db.query(Task).order_by(Task.id.desc())
    if status:
        q = q.filter(Task.status == status)
    tasks = q.offset((page - 1) * page_size).limit(page_size).all()
    ids = [t.id for t in tasks]

    grades: dict[int, dict] = {}
    if ids:
        for tid, grade, cnt in (db.query(Resume.task_id, Resume.final_grade, func.count())
                                .filter(Resume.task_id.in_(ids))
                                .group_by(Resume.task_id, Resume.final_grade)):
            grades.setdefault(tid, {})[grade or "未定级"] = cnt

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
        "resume_count": sum(grades.get(t.id, {}).values()),
        "grades": grades.get(t.id, {}),
        "llm": llm.get(t.id),
    } for t in tasks]
    return {"total": q.order_by(None).count(), "page": page,
            "page_size": page_size, "items": items}
```

注意：`total` 用 `q.order_by(None).count()` 去掉排序再 count，避免部分数据库排序+count 兼容问题。

* [ ] **Step 4: 运行测试通过**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_api.py -q -k list_tasks`
Expected: PASS

* [ ] **Step 5: Commit** `git commit -m "feat: GET /api/tasks 历史任务列表（分页/状态过滤/统计）"`

***

## Task 4: 任务详情端点增强

**Files:**

* Modify: `backend/app/routers/tasks.py`（get\_task）

* Test: `backend/tests/test_api.py`

* [ ] **Step 1: 写失败测试**：

```python
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
```

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_api.py -q -k task_detail_with`
Expected: FAIL（KeyError: stage\_timeline）

* [ ] **Step 3: 实现** — 替换 `get_task`：

```python
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
```

* [ ] **Step 4: 运行全部 API 测试**（确认 TaskProgress/TaskResult 依赖的旧字段不回归）

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_api.py -q`
Expected: 全部 PASS

* [ ] **Step 5: Commit** `git commit -m "feat: 任务详情返回阶段时间线与 LLM 调用统计"`

***

## Task 5: 配置存储 settings\_store + 启动加载

**Files:**

* Create: `backend/app/settings_store.py`

* Modify: `backend/app/models.py`（AppSetting）

* Modify: `backend/app/main.py`（lifespan）

* Test: `backend/tests/test_settings.py`（新建）

* [ ] **Step 1: 写失败测试**（新建 tests/test\_settings.py）：

```python
import pytest
from app.pipeline import settings_store
from app.config import get_settings

EDITABLE = ["llm_base_url", "llm_api_key", "llm_model", "llm_vlm_model",
            "llm_timeout", "ocr_base_url", "ocr_confidence_threshold",
            "step_timeout", "max_concurrency"]


@pytest.fixture
def restore_settings():
    s = get_settings()
    snapshot = {k: getattr(s, k) for k in EDITABLE}
    yield s
    for k, v in snapshot.items():
        setattr(s, k, v)  # 测试后恢复，避免污染其他用例


def test_save_and_load_overrides(db_session):
    settings_store.save_overrides(db_session, {"llm_model": "qwen3-32b",
                                               "max_concurrency": "5"})
    assert settings_store.load_overrides(db_session) == {
        "llm_model": "qwen3-32b", "max_concurrency": "5"}


def test_save_overrides_rejects_unknown_key(db_session):
    with pytest.raises(ValueError):
        settings_store.save_overrides(db_session, {"database_url": "x"})


def test_apply_to_settings_coerces_types(db_session, restore_settings):
    settings_store.save_overrides(db_session, {"step_timeout": "60",
                                               "llm_timeout": "30.5"})
    settings_store.apply_to_settings(
        restore_settings, settings_store.load_overrides(db_session))
    assert restore_settings.step_timeout == 60
    assert isinstance(restore_settings.step_timeout, int)
    assert restore_settings.llm_timeout == 30.5


def test_apply_to_settings_ignores_unknown(db_session, restore_settings):
    before = restore_settings.llm_model
    settings_store.apply_to_settings(restore_settings, {"llm_model2": "x"})
    assert restore_settings.llm_model == before
```

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_settings.py -q`
Expected: FAIL（ModuleNotFoundError: app.settings\_store）

* [ ] **Step 3: models.py 加 AppSetting**（文件末尾追加）：

```python
class AppSetting(Base):
    """页面可编辑的运行参数覆盖值（key-value）。env 为默认，此处为覆盖。"""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
```

* [ ] **Step 4: 新建 settings\_store.py**：

```python
from sqlalchemy.orm import Session
from app.models import AppSetting

# 页面可编辑的运行参数及类型（部署级配置 database_url/uploads_dir 不在此列）
EDITABLE_KEYS: dict[str, type] = {
    "llm_base_url": str,
    "llm_api_key": str,
    "llm_model": str,
    "llm_vlm_model": str,
    "llm_timeout": float,
    "ocr_base_url": str,
    "ocr_confidence_threshold": float,
    "step_timeout": int,
    "max_concurrency": int,
}


def load_overrides(db: Session) -> dict[str, str]:
    rows = db.query(AppSetting).filter(AppSetting.key.in_(EDITABLE_KEYS)).all()
    return {r.key: r.value for r in rows}


def save_overrides(db: Session, values: dict[str, str]):
    for k, v in values.items():
        if k not in EDITABLE_KEYS:
            raise ValueError(f"不可配置项：{k}")
        row = db.get(AppSetting, k)
        if row is None:
            db.add(AppSetting(key=k, value=str(v)))
        else:
            row.value = str(v)
    db.commit()


def apply_to_settings(settings_obj, overrides: dict[str, str]):
    """把 DB 覆盖值原地赋到 Settings 单例上（lru_cache 单例被各模块持有，
    原地赋值即对所有使用方生效）。未知键忽略。"""
    for k, v in overrides.items():
        if k in EDITABLE_KEYS:
            setattr(settings_obj, k, EDITABLE_KEYS[k](v))
```

* [ ] **Step 5: main.py lifespan 加载**：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _load_setting_overrides()
    yield


def _load_setting_overrides():
    from app.config import get_settings
    from app.db import SessionLocal
    from app.settings_store import apply_to_settings, load_overrides
    db = SessionLocal()
    try:
        apply_to_settings(get_settings(), load_overrides(db))
    except Exception:
        pass  # 配置表异常不阻断启动，退回 env 默认值
    finally:
        db.close()
```

（db\_url 指向 sqlite 测试库时表由 conftest 建，main 的 lifespan 在 TestClient 下不触发，不影响测试。）

* [ ] **Step 6: 运行测试通过**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_settings.py -q`
Expected: 全部 PASS

* [ ] **Step 7: Commit** `git commit -m "feat: app_settings 表与运行参数覆盖机制"`

***

## Task 6: 配置端点 GET/PUT /api/settings

**Files:**

* Create: `backend/app/routers/settings.py`

* Modify: `backend/app/main.py`（注册路由）

* Test: `backend/tests/test_settings.py`

* [ ] **Step 1: 写失败测试**（追加到 test\_settings.py）：

```python
def test_get_settings_returns_editable(db_session, restore_settings):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from tests.conftest import _testing_session
    app.dependency_overrides[get_db] = _testing_session
    try:
        resp = TestClient(app).get("/api/settings")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 200
    editable = resp.json()["editable"]
    assert set(editable) == set(EDITABLE)
    assert "value" in editable["llm_model"] and "overridden" in editable["llm_model"]
    assert editable["database_url"] if "database_url" in editable else True


def test_put_settings_persists_and_applies(db_session, restore_settings):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from tests.conftest import _testing_session
    app.dependency_overrides[get_db] = _testing_session
    try:
        resp = TestClient(app).put("/api/settings",
                                   json={"llm_model": "glm-4", "max_concurrency": 6})
        assert resp.status_code == 200
        # 1) DB 持久化
        assert settings_store.load_overrides(db_session)["llm_model"] == "glm-4"
        # 2) 单例生效
        assert restore_settings.llm_model == "glm-4"
        assert restore_settings.max_concurrency == 6
        # 3) GET 能看到 overridden 标记
        body = TestClient(app).get("/api/settings").json()["editable"]
        assert body["llm_model"]["overridden"] is True
        assert body["llm_base_url"]["overridden"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_put_settings_rejects_unknown_and_invalid(db_session, restore_settings):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from tests.conftest import _testing_session
    app.dependency_overrides[get_db] = _testing_session
    try:
        c = TestClient(app)
        assert c.put("/api/settings", json={"database_url": "x"}).status_code == 422
        assert c.put("/api/settings", json={"llm_timeout": "abc"}).status_code == 422
        assert c.put("/api/settings", json={"max_concurrency": 0}).status_code == 422
        assert c.put("/api/settings", json={"ocr_confidenceence": 2}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
```

（注意第 4 个断言键名故意拼错 `ocr_confidenceence` 走未知键 422 分支；未知键在 pydantic 模型上直接被忽略，因此路由需显式比对 keys。）

* [ ] **Step 2: 运行验证失败**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_settings.py -q -k settings_endpoint`
Expected: FAIL（404）

* [ ] **Step 3: 新建 routers/settings.py**：

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.pipeline.settings_store import (
    EDITABLE_KEYS, apply_to_settings, load_overrides, save_overrides)

router = APIRouter(prefix="/api")


class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_vlm_model: str | None = None
    llm_timeout: float | None = None
    ocr_base_url: str | None = None
    ocr_confidence_threshold: float | None = None
    step_timeout: int | None = None
    max_concurrency: int | None = None


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    s = get_settings()
    overridden = load_overrides(db)
    return {"editable": {
        k: {"value": getattr(s, k), "overridden": k in overridden,
            "type": t.__name__}
        for k, t in EDITABLE_KEYS.items()
    }}


@router.put("/settings")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    values = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not values:
        raise HTTPException(422, "没有可更新的配置项")
    # 未知键（不在 SettingsUpdate 定义中）会被 pydantic 静默忽略，
    # 但为防模型字段与 EDITABLE_KEYS 漂移，这里再显式校验一次
    bad = set(values) - set(EDITABLE_KEYS)
    if bad:
        raise HTTPException(422, f"不可配置项：{', '.join(sorted(bad))}")
    try:
        SettingsUpdate.model_validate(values)  # 类型兜底校验
        if "llm_timeout" in values and values["llm_timeout"] <= 0:
            raise ValueError("llm_timeout 必须为正数")
        if "step_timeout" in values and values["step_timeout"] <= 0:
            raise ValueError("step_timeout 必须为正数")
        if "max_concurrency" in values and not (1 <= values["max_concurrency"] <= 10):
            raise ValueError("max_concurrency 取值 1-10")
        if "ocr_confidence_threshold" in values and not (
                0 < values["ocr_confidence_threshold"] <= 1):
            raise ValueError("ocr_confidence_threshold 取值 (0, 1]")
    except (ValidationError, ValueError) as e:
        raise HTTPException(422, str(e))

    save_overrides(db, {k: str(v) for k, v in values.items()})
    apply_to_settings(get_settings(), {k: str(v) for k, v in values.items()})
    return {"ok": True}
```

* [ ] **Step 4: main.py 注册**：

```python
from app.routers import tasks, resumes, settings
...
app.include_router(settings.router)
```

* [ ] **Step 5: 运行测试通过**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/test_settings.py -q`
Expected: 全部 PASS

* [ ] **Step 6: Commit** `git commit -m "feat: GET/PUT /api/settings 运行参数配置端点"`

***

## Task 7: 前端 API 层 + 路由 + 全局导航

**Files:**

* Modify: `frontend/src/api.js`

* Modify: `frontend/src/main.js`

* Modify: `frontend/src/App.vue`

* [ ] **Step 1: api.js 追加**：

```js
export async function listTasks(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  ).toString()
  const resp = await fetch(`/api/tasks${qs ? `?${qs}` : ''}`)
  if (!resp.ok) throw new Error('获取任务列表失败')
  return resp.json()
}

export async function getSettings() {
  const resp = await fetch('/api/settings')
  if (!resp.ok) throw new Error('获取配置失败')
  return resp.json()
}

export async function updateSettings(values) {
  const resp = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `保存失败 (${resp.status})`)
  }
  return resp.json()
}
```

* [ ] **Step 2: main.js 加路由与懒加载**（现有同步 import 保持，新增懒加载减少首屏体积）：

```js
const routes = [
  { path: '/', component: TaskCreate },
  { path: '/task/:id/progress', component: TaskProgress },
  { path: '/task/:id', component: TaskResult },
  { path: '/tasks', component: () => import('./views/TaskHistory.vue') },
  { path: '/task/:id/detail', component: () => import('./views/TaskDetail.vue') },
  { path: '/settings', component: () => import('./views/SettingsView.vue') },
]
```

注意：`/task/:id/detail` 必须声明在 `/task/:id` **之后或路径更具体**（vue-router 按精确度匹配，`/task/5/detail` 不会命中 `/task/:id`，顺序无碍，但保持上表顺序清晰）。

* [ ] **Step 3: App.vue 改为带导航**（整体替换 template）：

```vue
<template>
  <el-container style="max-width: 1100px; margin: 0 auto; padding: 24px">
    <el-header style="height: auto; margin-bottom: 8px">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span style="font-size: 22px; font-weight: 700; letter-spacing: 0.5px">
          简历审阅系统
        </span>
        <el-menu mode="horizontal" router :default-active="activeNav"
                 :ellipsis="false" style="border-bottom: none">
          <el-menu-item index="/">新建任务</el-menu-item>
          <el-menu-item index="/tasks">历史任务</el-menu-item>
          <el-menu-item index="/settings">模型配置</el-menu-item>
        </el-menu>
      </div>
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
const route = useRoute()
const activeNav = computed(() => {
  if (route.path.startsWith('/task') && route.path.endsWith('/detail')) return '/tasks'
  if (route.path.startsWith('/task')) return '/'
  return route.path
})
</script>
```

* [ ] **Step 4: 手动验证** — `docker compose up -d --build web` 后打开 <http://localhost:8080> ，导航三项可见可点击（/tasks、/settings 页面下一任务实现）。

* [ ] **Step 5: Commit** `git commit -m "feat: 前端路由与全局导航"`

***

## Task 8: TaskHistory.vue 历史任务列表页

**Files:**

* Create: `frontend/src/views/TaskHistory.vue`

设计规范：列表页信息密度优先。状态用 el-tag 语义色；分档分布用一组小型彩色 tag；耗时/tokens 等宽数字；空态用 el-empty 引导去创建任务。

* [ ] **Step 1: 实现完整组件**：

```vue
<template>
  <el-card>
    <div class="page-head">
      <div>
        <h3 class="page-title">历史任务</h3>
        <span class="page-sub">共 {{ total }} 个任务</span>
      </div>
      <el-select v-model="statusFilter" style="width: 140px" clearable
                 placeholder="全部状态" @change="load(1)">
        <el-option v-for="(label, s) in STATUS" :key="s" :value="s" :label="label" />
      </el-select>
    </div>

    <el-table :data="items" v-loading="loading" style="width: 100%"
              @row-click="openDetail" row-class-name="clickable">
      <el-table-column prop="task_id" label="ID" width="60" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="tagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="简历数" width="80" prop="resume_count" />
      <el-table-column label="分档分布" min-width="180">
        <template #default="{ row }">
          <template v-if="Object.keys(row.grades).length">
            <el-tag v-for="(cnt, g) in row.grades" :key="g" size="small"
                    :type="gradeType(g)" style="margin-right: 6px"
                    class="mono">{{ g }}×{{ cnt }}</el-tag>
          </template>
          <span v-else class="dim">—</span>
        </template>
      </el-table-column>
      <el-table-column label="tokens 消耗" min-width="160">
        <template #default="{ row }">
          <span v-if="row.llm" class="mono">
            {{ row.llm.prompt_tokens + row.llm.completion_tokens }}
          </span>
          <span v-else class="dim">—</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">
          <span class="mono dim">{{ fmtTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column width="140" label="操作">
        <template #default="{ row }">
          <el-button size="small" @click.stop="openDetail(row)">执行详情</el-button>
          <el-button size="small" text type="primary"
                     @click.stop="$router.push(`/task/${row.task_id}`)">结果</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !items.length" description="暂无任务">
      <el-button type="primary" @click="$router.push('/')">去创建任务</el-button>
    </el-empty>

    <el-pagination v-if="total > pageSize" style="margin-top: 16px; justify-content: flex-end"
                   layout="prev, pager, next, total" :total="total"
                   :page-size="pageSize" :current-page="page"
                   @current-change="load" />
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listTasks } from '../api'

const router = useRouter()
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const statusFilter = ref('')

const STATUS = {
  pending: '等待', parsing: '解析中', done: '完成', failed: '失败',
}
const statusLabel = (s) => STATUS[s] || s
const tagType = (s) => ({ done: 'success', failed: 'danger' }[s] || 'info')
const gradeType = (g) => ({ A: 'success', B: 'warning', C: 'info', D: 'danger' }[g] || 'info')

async function load(p = 1) {
  page.value = p
  loading.value = true
  try {
    const body = await listTasks({ page: p, page_size: pageSize, status: statusFilter.value })
    items.value = body.items
    total.value = body.total
  } finally {
    loading.value = false
  }
}

function openDetail(row) {
  router.push(`/task/${row.task_id}/detail`)
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => load(1))
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 16px; }
.page-sub { font-size: 12px; color: #909399; margin-left: 8px; }
.mono { font-variant-numeric: tabular-nums; }
.dim { color: #909399; font-size: 12px; }
:deep(.clickable) { cursor: pointer; }
</style>
```

* [ ] **Step 2: 手动验证** — 刷新 /tasks 页面，能看到之前创建的任务（含 resume\_count、grades、tokens），点击行进入详情路由（页面下一任务实现），分页与状态过滤可用（造 >20 条数据可只验证参数传递正确即可）。

* [ ] **Step 3: Commit** `git commit -m "feat: 历史任务列表页"`

***

## Task 9: TaskDetail.vue 执行详情页

**Files:**

* Create: `frontend/src/views/TaskDetail.vue`

设计规范：三层结构 —— ① 任务概要卡（状态 + 时间 + 全局 LLM 用量）；② 任务级阶段 el-steps（JD 解析 → 简历处理 → 汇总排序）；③ 每份简历一个 el-collapse 面板：el-steps 显示四阶段（含耗时、失败原因），下方 LLM 调用明细表。阶段耗时由 `ended_at - started_at` 前端计算并格式化为 `2.3s`。

* [ ] **Step 1: 实现完整组件**：

```vue
<template>
  <div v-if="task" v-loading="loading">
    <el-card style="margin-bottom: 16px">
      <div class="page-head">
        <div>
          <h3 class="page-title">
            执行详情（任务 #{{ task.task_id }}）
            <el-tag :type="tagType(task.status)" style="margin-left: 8px">
              {{ statusLabel(task.status) }}
            </el-tag>
          </h3>
          <span class="page-sub mono">
            创建 {{ fmtTime(task.created_at) }} · 更新 {{ fmtTime(task.updated_at) }}
          </span>
        </div>
        <div>
          <el-button v-if="task.status === 'done'"
                     @click="$router.push(`/task/${task.task_id}`)">查看筛选结果</el-button>
          <el-button @click="$router.push('/tasks')">返回列表</el-button>
        </div>
      </div>

      <el-alert v-if="task.summary_report?.error" type="error" :closable="false"
                style="margin-bottom: 12px"
                :title="`任务失败：${task.summary_report.error}`" />

      <div class="usage mono">
        <span>LLM 调用 {{ task.llm_usage.calls }} 次</span>
        <el-divider direction="vertical" />
        <span>输入 {{ task.llm_usage.prompt_tokens }} tokens</span>
        <el-divider direction="vertical" />
        <span>输出 {{ task.llm_usage.completion_tokens }} tokens</span>
        <el-divider direction="vertical" />
        <span>累计 {{ fmtDuration(task.llm_usage.duration_ms) }}</span>
      </div>

      <el-steps :active="taskStepsActive" align-center style="margin-top: 16px">
        <el-step v-for="s in TASK_STEPS" :key="s.stage" :title="s.label"
                 :status="stepStatus('task', s.stage)"
                 :description="stepDesc('task', s.stage)" />
      </el-steps>
    </el-card>

    <el-card>
      <h3 class="page-title" style="margin-bottom: 12px">简历处理明细（{{ task.resumes.length }}）</h3>
      <el-collapse>
        <el-collapse-item v-for="r in task.resumes" :key="r.id" :name="r.id">
          <template #title>
            <span style="font-weight: 600">{{ r.filename }}</span>
            <el-tag :type="tagType(r.status)" size="small" style="margin-left: 10px">
              {{ statusLabel(r.status) }}
            </el-tag>
            <el-tag v-if="r.final_grade" size="small" :type="gradeType(r.final_grade)"
                    style="margin-left: 6px">{{ r.final_grade }}</el-tag>
            <span v-if="r.error_message" class="err">{{ r.error_message }}</span>
          </template>

          <el-steps :active="resumeStepsActive(r)" align-center style="margin: 8px 0 16px">
            <el-step v-for="s in RESUME_STEPS" :key="s.stage" :title="s.label"
                     :status="stepStatus(r.id, s.stage)"
                     :description="stepDesc(r.id, s.stage)" />
          </el-steps>

          <el-table v-if="r.llm_calls.length" :data="r.llm_calls" size="small">
            <el-table-column prop="role" label="角色" width="130" />
            <el-table-column prop="prompt_tokens" label="输入 tokens" width="110" />
            <el-table-column prop="completion_tokens" label="输出 tokens" width="110" />
            <el-table-column label="耗时" width="100">
              <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
            </el-table-column>
            <el-table-column label="时间">
              <template #default="{ row }">
                <span class="mono dim">{{ fmtTime(row.created_at) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="该简历无 LLM 调用（可能为粘贴文本且处理早期失败）" :image-size="60" />
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card v-if="task.task_llm_calls.length" style="margin-top: 16px">
      <h3 class="page-title" style="margin-bottom: 12px">任务级 LLM 调用（JD 解析 / 汇总）</h3>
      <el-table :data="task.task_llm_calls" size="small">
        <el-table-column prop="role" label="角色" width="130" />
        <el-table-column prop="prompt_tokens" label="输入 tokens" width="110" />
        <el-table-column prop="completion_tokens" label="输出 tokens" width="110" />
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">{{ fmtDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="时间">
          <template #default="{ row }">
            <span class="mono dim">{{ fmtTime(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getTask } from '../api'

const route = useRoute()
const task = ref(null)
const loading = ref(true)

const TASK_STEPS = [
  { stage: 'jd_parse', label: 'JD 解析' },
  { stage: 'summarize', label: '汇总排序' },
]
const RESUME_STEPS = [
  { stage: 'parsing', label: '解析' },
  { stage: 'extracting', label: '信息提取' },
  { stage: 'screening', label: '初筛' },
  { stage: 'evaluating', label: '深度评估' },
]

const STATUS_LABELS = {
  pending: '等待', parsing: '解析中', extracting: '信息提取', screening: '初筛',
  evaluating: '深度评估', done: '完成', failed: '失败', needs_review: '需人工复核',
}
const statusLabel = (s) => STATUS_LABELS[s] || s
const tagType = (s) => ({
  done: 'success', failed: 'danger', needs_review: 'warning' }[s] || 'info')
const gradeType = (g) => ({ A: 'success', B: 'warning', C: 'info', D: 'danger' }[g] || 'info')

// 时间线查询：task 用字符串 'task' 作 key，简历用 resume id
function timelineOf(key) {
  if (key === 'task') return task.value.stage_timeline || []
  const r = task.value.resumes.find((x) => x.id === key)
  return r ? (r.stage_timeline || []) : []
}
function stageEntry(key, stage) {
  return timelineOf(key).find((t) => t.stage === stage)
}

function stepStatus(key, stage) {
  const e = stageEntry(key, stage)
  if (!e) return 'wait'
  if (e.status === 'failed') return 'error'
  if (e.status === 'needs_review') return 'error'
  if (e.ended_at) return 'finish'
  return 'process'
}
function stepDesc(key, stage) {
  const e = stageEntry(key, stage)
  if (!e) return ''
  const dur = e.ended_at ? fmtDuration(new Date(e.ended_at) - new Date(e.started_at)) : ''
  return [dur, e.detail].filter(Boolean).join(' · ')
}
function taskStepsActive() {
  const tl = timelineOf('task')
  return tl.filter((t) => t.ended_at).length
}
function resumeStepsActive(r) {
  const tl = r.stage_timeline || []
  return tl.filter((t) => t.ended_at).length
}

function fmtDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}
function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  try {
    task.value = await getTask(route.params.id)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.page-title { margin: 0; font-size: 16px; display: flex; align-items: center; }
.page-sub { font-size: 12px; color: #909399; }
.usage { color: #606266; font-size: 13px; }
.mono { font-variant-numeric: tabular-nums; }
.dim { color: #909399; font-size: 12px; }
.err { color: #f56c6c; font-size: 12px; margin-left: 10px; }
</style>
```

* [ ] **Step 2: 手动验证** — 打开历史任务的 /task/{id}/detail：能看到任务级步骤（JD 解析/汇总排序）与耗时；展开每份简历看到四阶段步骤、每阶段耗时、LLM 调用明细表（角色/tokens/耗时/时间）。

* [ ] **Step 3: Commit** `git commit -m "feat: 任务执行详情页（阶段状态/耗时/LLM 调用）"`

***

## Task 10: SettingsView\.vue 配置页 + TaskResult 入口

**Files:**

* Create: `frontend/src/views/SettingsView.vue`

* Modify: `frontend/src/views/TaskResult.vue`

设计规范：分组表单（模型服务 / OCR / 流水线），每组一个带左侧强调条的区块标题；API Key 用密码框可切换明文；被 DB 覆盖过的项显示「已覆盖」小徽标；保存后用 ElMessage 反馈。

* [ ] **Step 1: 实现完整组件**：

```vue
<template>
  <el-card v-loading="loading">
    <div class="page-head">
      <div>
        <h3 class="page-title">运行参数配置</h3>
        <span class="page-sub">修改即时生效（对新任务），并持久化到数据库</span>
      </div>
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
    </div>

    <template v-if="form">
      <div class="group">
        <div class="group-title">模型服务</div>
        <el-form label-width="150px">
          <el-form-item label="Base URL">
            <el-input v-model="form.llm_base_url" placeholder="http://host.docker.internal:8000/v1" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input v-model="form.llm_api_key" show-password />
          </el-form-item>
          <el-form-item label="对话模型">
            <el-input v-model="form.llm_model" />
          </el-form-item>
          <el-form-item label="视觉模型（VLM）">
            <el-input v-model="form.llm_vlm_model" placeholder="留空则图片简历仅走 OCR" />
          </el-form-item>
          <el-form-item label="单次请求超时（秒）">
            <el-input-number v-model="form.llm_timeout" :min="1" :max="3600" />
          </el-form-item>
        </el-form>
      </div>

      <div class="group">
        <div class="group-title">OCR 服务</div>
        <el-form label-width="150px">
          <el-form-item label="OCR Base URL">
            <el-input v-model="form.ocr_base_url" />
          </el-form-item>
          <el-form-item label="置信度阈值">
            <el-input-number v-model="form.ocr_confidence_threshold"
                             :min="0.01" :max="1" :step="0.05" />
          </el-form-item>
        </el-form>
      </div>

      <div class="group">
        <div class="group-title">流水线</div>
        <el-form label-width="150px">
          <el-form-item label="单步骤超时（秒）">
            <el-input-number v-model="form.step_timeout" :min="1" :max="3600" />
          </el-form-item>
          <el-form-item label="简历并发数">
            <el-input-number v-model="form.max_concurrency" :min="1" :max="10" />
          </el-form-item>
        </el-form>
      </div>
    </template>
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettings, updateSettings } from '../api'

const loading = ref(true)
const saving = ref(false)
const form = ref(null)

onMounted(async () => {
  try {
    const body = await getSettings()
    const values = {}
    Object.entries(body.editable).forEach(([k, v]) => { values[k] = v.value })
    form.value = values
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  try {
    await updateSettings(form.value)
    ElMessage.success('配置已保存并生效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { margin: 0; font-size: 16px; }
.page-sub { font-size: 12px; color: #909399; }
.group { margin-bottom: 8px; }
.group-title {
  font-size: 14px; font-weight: 600; margin-bottom: 12px;
  padding-left: 10px; border-left: 3px solid #409eff; line-height: 1.2;
}
</style>
```

* [ ] **Step 2: TaskResult.vue 加入口**（操作按钮区 `<el-button @click="download('md')">` 之前插入）：

```vue
        <el-button @click="$router.push(`/task/${$route.params.id}/detail`)">执行详情</el-button>
```

* [ ] **Step 3: 手动验证** — /settings 页修改 `llm_model` 保存 → 刷新页面值保留（DB 持久化）；创建新任务时 LLM 请求使用新模型（可在 LLM 服务日志或 llm\_logs 表确认）；输入非法值（如超时 -1）保存提示 422 错误信息。

* [ ] **Step 4: Commit** `git commit -m "feat: 运行参数配置页与结果页详情入口"`

***

## Task 11: 全量验证与存量数据迁移

* [ ] **Step 1: 容器内全量测试**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/work" -w /work api pytest tests/ -q`
Expected: 全部 PASS（test\_config.py 的 `test_settings_defaults` 若因容器 env 注入 `LLM_API_KEY` 失败，为既有环境产物，非本次引入，可忽略）

* [ ] **Step 2: 存量数据库迁移（如需保留数据）**

```bash
docker compose exec db psql -U resume -d resume_review -c '
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS stage_timeline JSON;
ALTER TABLE resumes ADD COLUMN IF NOT EXISTS stage_timeline JSON;
ALTER TABLE llm_logs ADD COLUMN IF NOT EXISTS resume_id INTEGER REFERENCES resumes(id);
CREATE TABLE IF NOT EXISTS app_settings (key VARCHAR(100) PRIMARY KEY, value VARCHAR(500));
'
```

开发环境也可直接 `docker compose down -v` 重置（会清空所有任务数据与 uploads 卷）。

* [ ] **Step 3: 重建并端到端验证**

```bash
docker compose up -d --build
```

验证清单：

1. <http://localhost:8080> 导航三项可切换
2. 创建一个任务（JD 文件 + 2 份简历），进度页正常
3. /tasks 列表出现新任务，含简历数/分档/tokens
4. 任务完成后点「执行详情」：任务级两步骤、每份简历四阶段含耗时、LLM 调用明细齐全
5. /settings 修改模型名保存 → 创建新任务 → `docker compose exec db psql -U resume -d resume_review -c "SELECT DISTINCT role, task_id FROM llm_logs ORDER BY task_id DESC LIMIT 3"` 确认新任务日志写入；重建容器 `docker compose restart api` 后 /settings 值仍为修改后的（DB 持久化）
6. 存量旧任务打开详情页：stage\_timeline 为空数组时步骤全部 wait 态、不报错（向后兼容）

* [ ] **Step 4: Commit** `git commit -m "test: 全量验证任务详情与配置模块"`

***

## Self-Review 结论

* **Spec 覆盖**：历史任务列表（Task 3/8）、执行详情含各阶段状态/耗时/tokens（Task 1/2/4/9）、模型信息页面配置（Task 5/6/10）、交互信息展示扩充（导航/详情入口，Task 7/10）——全覆盖。

* **类型一致性**：`stage_timeline` 元素结构 `{stage, started_at, ended_at, status, detail?}` 在 runner（写）与 API（透传）、TaskDetail.vue（读）三处一致；`EDITABLE_KEYS` 在 settings\_store 与 SettingsUpdate 字段一一对应。

* **向后兼容**：GET /tasks/{id} 保留全部旧字段（TaskProgress/TaskResult 不需改动即工作）；LLMLog.resume\_id 可空；旧任务 stage\_timeline 为 null → API 输出 `[]`。

* **无占位符**：所有代码步骤均含完整代码。

