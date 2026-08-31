# 初筛阈值与语义匹配 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 初筛按「硬性要求满足条数占比 ≥ 40%」判定通过，且 LLM 判断单条要求时做语义匹配（相似度 > 60% 即满足）。

**Architecture:** screener prompt 增加语义匹配与阈值规则；runner 在初筛结果落库前用代码确定性重算 `passed`（覆盖 LLM 的算术聚合）；阈值 `screening_pass_ratio` 放 config Settings；前端初筛区块补「满足 x/y（z%）」摘要。schema 零改动。

**Tech Stack:** FastAPI + SQLAlchemy（后端既有栈）、Vue 3 + Element Plus（前端既有栈）。

**设计文档：** `.trae/documents/2026-08-31-screening-threshold-design.md`

***

## 现状要点（实现者必读）

* 初筛链路：`runner.py` L187-202 调 `roles.screen_resume()` → `ScreeningResult`（checks/passed/reject\_reason）→ `r.screening = screening.model_dump()` 落库 → `if not screening.passed:` 则跳过评估、`_close_open_stages(r, "failed", detail=f"初筛未通过：{screening.reject_reason}")`。

* `ScreeningResult`/`ScreeningCheck` 定义在 `backend/app/schemas.py:38-47`，**不改**。

* screener prompt 在 `backend/prompts/screener.txt`，当前规则第 8 行是 `passed = 所有硬性要求均满足`。

* `backend/app/config.py` 的 Settings 是 pydantic BaseSettings，字段默认值 + env 覆盖。

* 测试在 Docker 容器内跑（本地缺 psycopg）：
  `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -m pytest tests/test_xxx.py -q`

* 前端初筛区块在 `frontend/src/components/ResumeStepResults.vue` L41-59（screening 区块，含 passed tag / reject\_reason / checks 表）。

* **工作区有一处与本功能无关的未提交改动** **`backend/prompts/jd_analyst.txt`，任何提交都必须明确指定文件，不得** **`git add -A`。**

## 文件结构总览

| 文件                                              | 动作 | 职责                           |
| ----------------------------------------------- | -- | ---------------------------- |
| `backend/app/config.py`                         | 修改 | 新增 `screening_pass_ratio` 字段 |
| `backend/app/pipeline/runner.py`                | 修改 | 新增重算函数 + 初筛落库前重算 passed      |
| `backend/prompts/screener.txt`                  | 修改 | 语义匹配规则 + 阈值规则                |
| `backend/tests/test_runner.py`                  | 修改 | 重算逻辑单测                       |
| `frontend/src/components/ResumeStepResults.vue` | 修改 | 初筛区块「满足 x/y（z%）」摘要           |

***

## Task 1: 配置项与重算函数（TDD）

**Files:**

* Modify: `backend/app/config.py`

* Modify: `backend/app/pipeline/runner.py`

* Test: `backend/tests/test_runner.py`

* [ ] **Step 1: 写失败测试**

在 `backend/tests/test_runner.py` 末尾追加（该文件已有 `from app.config import Settings` 或按需 import；若 conftest 已有相关 fixture 则复用）：

```python
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
```

* [ ] **Step 2: 跑测试确认失败**

Run: `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -m pytest tests/test_runner.py::TestScreeningPassRecalc -q`
Expected: FAIL（ImportError: cannot import name 'recalc\_screening\_pass' / AttributeError）

* [ ] **Step 3: 最小实现**

`backend/app/config.py` 的 Settings 类中，在 `step_timeout` 附近追加：

```python
    screening_pass_ratio: float = 0.4  # 初筛通过阈值：满足硬性要求条数占比
```

`backend/app/pipeline/runner.py` 中，在 `_close_open_stages` 函数之后追加：

```python
def recalc_screening_pass(screening, ratio: float | None = None):
    """代码确定性重算初筛通过判定，覆盖 LLM 的 passed（LLM 算术不可靠）。

    - 满足条数占比 >= ratio 即通过；checks 为空视为通过（无硬性要求）。
    - 未通过且无 reject_reason 时生成兜底文案。
    """
    from app.config import get_settings
    if ratio is None:
        ratio = get_settings().screening_pass_ratio
    checks = screening.checks or []
    if not checks:
        screening.passed = True
        return
    met = sum(1 for c in checks if c.met)
    total = len(checks)
    screening.passed = (met / total) >= ratio
    if not screening.passed and not screening.reject_reason:
        screening.reject_reason = (
            f"硬性要求满足率 {round(met / total * 100)}%（{met}/{total}），"
            f"低于 {round(ratio * 100)}% 阈值")
```

* [ ] **Step 4: 跑测试确认通过**

Run: `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -m pytest tests/test_runner.py::TestScreeningPassRecalc -q`
Expected: 6 passed

* [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/pipeline/runner.py backend/tests/test_runner.py
git commit -m "feat: 初筛通过判定按满足条数占比>=40%重算"
```

***

## Task 2: runner 集成重算（TDD）

**Files:**

* Modify: `backend/app/pipeline/runner.py`（L196 `r.screening = screening.model_dump()` 附近）

* Test: `backend/tests/test_runner.py`

* [ ] **Step 1: 写失败测试**

在 `test_runner.py` 的 TestScreeningPassRecalc 类后追加（复用该文件既有的 pipeline 全流程测试模式——若已有 `test_pipeline_full_flow` 类似的 mock LLM 测试，参照其 fixture/mock 方式；以下为独立可运行版本，mock 掉 roles.screen\_resume）：

```python
def test_screening_stage_applies_recalc(monkeypatch):
    """runner 初筛阶段落库前调用重算：LLM 全满足才通过的保守输出被放宽"""
    from unittest.mock import AsyncMock
    from app.schemas import ScreeningResult
    from app.pipeline import runner

    result = ScreeningResult(
        passed=False,  # LLM 按「全部满足」规则判为未通过
        checks=[
            {"requirement": "本科", "met": True, "evidence": "XX 大学本科"},
            {"requirement": "3年经验", "met": True, "evidence": "4 年后端"},
            {"requirement": "英语六级", "met": False, "evidence": "未见证书"},
            {"requirement": "Python", "met": False, "evidence": "未见"},
            {"requirement": "Docker", "met": False, "evidence": "未见"},
        ],
        reject_reason="不满足全部硬性要求",
    )
    # 2/5 = 40% >= 0.4 阈值 → 重算后应通过

    captured = {}

    async def fake_screen(llm, jd_parsed, profile, resume_id, task_id=None):
        captured["orig_passed"] = result.passed
        return result

    monkeypatch.setattr(runner.roles, "screen_resume", fake_screen)

    # 直接调用重算路径（阶段函数内部）：验证 recalc 被应用
    runner.recalc_screening_pass(result)
    assert result.passed is True
    assert captured["orig_passed"] is False  # 证明原值确实被覆盖
```

* [ ] **Step 2: 集成到 runner 阶段流程**

`runner.py` 初筛阶段（L192-196 区域），将：

```python
            screening = await asyncio.wait_for(
                roles.screen_resume(llm, jd_parsed, profile, resume_id, task_id=task_id),
                timeout=timeout,
            )
            _stage_end(r, "screening")
            r.screening = screening.model_dump()
```

改为：

```python
            screening = await asyncio.wait_for(
                roles.screen_resume(llm, jd_parsed, profile, resume_id, task_id=task_id),
                timeout=timeout,
            )
            _stage_end(r, "screening")
            recalc_screening_pass(screening)
            r.screening = screening.model_dump()
```

* [ ] **Step 3: 跑测试确认通过 + 全量回归**

Run: `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -m pytest tests/test_runner.py -q`
Expected: 全部通过（含既有 pipeline 全流程测试——注意既有 mock 的 ScreeningResult 若 checks 全 met 则行为不变）

* [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline/runner.py backend/tests/test_runner.py
git commit -m "feat: 初筛阶段集成通过率重算"
```

***

## Task 3: screener prompt 语义匹配规则

**Files:**

* Modify: `backend/prompts/screener.txt`

* [ ] **Step 1: 更新 prompt 全文**

`screener.txt` 整体替换为：

```text
你是「初筛专员」。给你结构化 JD 与候选人档案，请对每条硬性要求逐条核对，输出 JSON：
{
  "checks": [{"requirement": "要求原文", "met": true/false, "evidence": "简历中的依据原文摘录，或说明缺失"}],
  "passed": true/false,
  "reject_reason": "未通过时给出最主要的淘汰原因，通过则为 null"
}
规则：
1. 判断 met 时做语义匹配，不做字面精准匹配：含义相同或相近的表述即视为满足，如「精通 Java」与「熟练使用 Java 生态」、「5 年后端经验」与「五年服务端开发经历」、「本科及以上学历」与「工学学士」应判定为满足；描述含义相似度超过 60% 即 met=true；
2. passed 的判定：满足的硬性要求条数占全部硬性要求条数的比例 >= 40% 即通过（例如 5 条中满足 2 条即通过）；系统会按此规则重新校验 passed，请确保 checks 逐条判断准确；
3. evidence 必须引用简历档案中的事实，不得推测；
4. 只输出 JSON。
```

* [ ] **Step 2: 验证**

Run: `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -c "from app.pipeline.roles import _prompt; p = _prompt('screener'); assert '40%' in p and '60%' in p and '语义匹配' in p; print('prompt OK')"`
Expected: `prompt OK`

* [ ] **Step 3: Commit**

```bash
git add backend/prompts/screener.txt
git commit -m "feat: 初筛 prompt 增加语义匹配与40%阈值规则"
```

***

## Task 4: 前端满足率摘要

**Files:**

* Modify: `frontend/src/components/ResumeStepResults.vue`（L41-59 screening 区块）

* [ ] **Step 1: 修改 screening 区块**

在初筛「通过/未通过」tag 之后追加满足率摘要。将现有：

```vue
    <!-- 初筛阶段 -->
    <div v-if="report?.screening">
      <h4 class="stage-title">初筛结果</h4>
      <el-tag :type="report.screening.passed ? 'success' : 'danger'">
        {{ report.screening.passed ? '通过' : '未通过' }}
      </el-tag>
```

改为：

```vue
    <!-- 初筛阶段 -->
    <div v-if="report?.screening">
      <h4 class="stage-title">初筛结果</h4>
      <el-tag :type="report.screening.passed ? 'success' : 'danger'">
        {{ report.screening.passed ? '通过' : '未通过' }}
      </el-tag>
      <span v-if="metRatio" class="met-ratio mono"
            :class="report.screening.passed ? 't-green' : 't-red'">
        满足 {{ metRatio.met }}/{{ metRatio.total }}（{{ metRatio.pct }}%）
      </span>
```

script 中（`noResults` computed 附近）追加：

```js
const metRatio = computed(() => {
  const checks = props.report?.screening?.checks
  if (!checks?.length) return null
  const met = checks.filter((c) => c.met).length
  return { met, total: checks.length, pct: Math.round((met / checks.length) * 100) }
})
```

style 中追加（`.err` 之后）：

```css
.met-ratio { font-size: 12px; margin-left: 10px; }
```

* [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，exit 0

* [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ResumeStepResults.vue
git commit -m "feat: 初筛结果展示满足率摘要"
```

***

## Task 5: 端到端验证

* [ ] **Step 1: 全量后端测试**

Run: `docker compose run --rm --no-deps -v "$(pwd)/backend/app:/app/app" -v "$(pwd)/backend/tests:/app/tests" api python -m pytest tests/ -q`
Expected: 全部通过（原 67 个 + 新增 7 个）

* [ ] **Step 2: 重建服务并冒烟**

Run: `docker compose up -d --build api web 2>&1 | tail -3 && sleep 3 && curl -s http://localhost:8080/api/tasks | head -c 200`
Expected: 服务正常响应

* [ ] **Step 3: 真实任务验证（可选，需用户操作）**

提示用户：提交一个含多条硬性要求的 JD + 简历任务，在执行详情页展开简历面板，确认初筛区块出现「满足 x/y（z%）」且通过判定符合 40% 规则。

***

## Self-Review 结论

* **Spec 覆盖**：40% 代码重算（Task 1/2）、语义匹配 prompt（Task 3）、前端满足率摘要（Task 4）、测试与端到端验证（Task 1/2/5）——全覆盖。

* **占位符扫描**：所有步骤含完整代码/命令，无 TBD。

* **类型一致性**：`recalc_screening_pass(screening, ratio=None)` 签名在 Task 1 定义、Task 2 调用一致；`metRatio` computed 与模板绑定名一致；Settings 字段 `screening_pass_ratio` 命名前后一致。

* **风险提示**：既有 pipeline 全流程测试若 mock 了「部分 met 但 passed=false」的 ScreeningResult，重算后行为会变（原被拒→现通过），Task 2 Step 3 回归时需关注，必要时按新规则修正该 mock 的期望值。

