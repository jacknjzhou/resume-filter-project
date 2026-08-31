# 执行详情页步骤结果展示 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在执行详情页展示每个处理步骤的结果详情（JD 解析、汇总排序、简历解析原文、结构化档案、初筛、深度评估）。

**Architecture:** 纯前端改动，后端零改动。任务级结果随 `getTask` 已有数据直接渲染（新组件 JDParsedCard）；简历级结果在折叠面板展开时调用已有 `GET /api/resumes/{id}/report` 懒加载并缓存（新组件 ResumeStepResults 渲染）。TaskDetail.vue 负责集成与缓存管理。

**Tech Stack:** Vue 3 `<script setup>` + Element Plus（现有栈，无新依赖）。

**设计文档：** `.trae/documents/2026-08-31-step-results-display-design.md`

---

## 现状要点（实现者必读）

- `TaskDetail.vue` 位于 `frontend/src/views/`，当前展示：任务级 el-steps（jd_parse/summarize）、每份简历折叠面板（四阶段 el-steps + LLM 调用表）、任务级 LLM 调用表。
- `getTask(id)` 响应已含 `jd_parsed`、`summary_report`（任务级结果），但前端未渲染。
- `getResumeReport(id)`（`frontend/src/api.js` 已存在）返回 `raw_text / parse_meta / profile / screening / evaluation`。
- 数据结构（`backend/app/schemas.py`）：
  - `JDParsed`: `{responsibilities: string[], hard_requirements: [{description, weight}], bonus_items: string[]}`
  - `ResumeProfile`: `{name, education: [{school, degree, major, period}], work_experience: [{company, title, period, summary}], skills: string[], projects: string[], certificates: string[]}`
  - `ScreeningResult`: `{passed, checks: [{requirement, met, evidence}], reject_reason}`
  - `EvaluationReport`: `{skill_match, experience_match, stability, potential, highlights[], risks[], gaps[], interview_questions[]}`（0-100 整数）
  - `summary_report`: `{summary, rankings: [{resume_id, grade, rank, comment}]}`；失败时为 `{error: string}`
- 前端无测试基建，验证方式：`docker compose build web`（构建即语法检查）+ 手动清单。
- UI 规范延续项目风格：区块标题 14px 加粗 + 左侧 3px 强调色竖条、tabular-nums 等宽数字、状态色 done 绿 / failed 红 / needs_review 橙。

## 文件结构总览

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `frontend/src/components/JDParsedCard.vue` | 新建 | 任务级结果：JD 解析 + 汇总排序 |
| `frontend/src/components/ResumeStepResults.vue` | 新建 | 简历级四阶段结果渲染（纯展示，props 驱动） |
| `frontend/src/views/TaskDetail.vue` | 修改 | 集成两个组件 + 面板展开懒加载与缓存 |

---

## Task 1: JDParsedCard.vue 任务级结果组件

**Files:**
- Create: `frontend/src/components/JDParsedCard.vue`

- [ ] **Step 1: 创建组件（完整代码）**

```vue
<template>
  <el-card style="margin-bottom: 16px">
    <div v-if="jdParsed">
      <h3 class="section-title">JD 解析结果</h3>
      <h4 class="sub-title">岗位职责</h4>
      <ul class="plain-list">
        <li v-for="(r, i) in jdParsed.responsibilities" :key="i">{{ r }}</li>
      </ul>

      <h4 class="sub-title">硬性要求</h4>
      <el-table v-if="jdParsed.hard_requirements?.length"
                :data="jdParsed.hard_requirements" size="small">
        <el-table-column prop="description" label="要求" />
        <el-table-column label="权重" width="90">
          <template #default="{ row }">
            <span class="mono">{{ (row.weight * 100).toFixed(0) }}%</span>
          </template>
        </el-table-column>
      </el-table>

      <template v-if="jdParsed.bonus_items?.length">
        <h4 class="sub-title">加分项</h4>
        <el-tag v-for="(b, i) in jdParsed.bonus_items" :key="i" size="small"
                style="margin: 0 6px 6px 0">{{ b }}</el-tag>
      </template>
    </div>

    <div v-if="summaryReport && !summaryReport.error" :style="jdParsed ? 'margin-top: 16px' : ''">
      <h3 class="section-title">汇总排序结果</h3>
      <p v-if="summaryReport.summary" class="summary-text">{{ summaryReport.summary }}</p>
      <el-table v-if="summaryReport.rankings?.length"
                :data="sortedRankings" size="small">
        <el-table-column prop="rank" label="排名" width="70" />
        <el-table-column label="分档" width="70">
          <template #default="{ row }">
            <el-tag :type="gradeType(row.grade)" size="small">{{ row.grade }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="comment" label="综合评价" />
      </el-table>
    </div>
  </el-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  jdParsed: { type: Object, default: null },
  summaryReport: { type: Object, default: null },
})

const sortedRankings = computed(() =>
  [...(props.summaryReport?.rankings || [])].sort((a, b) =>
    (a.rank || 99) - (b.rank || 99)))

const gradeType = (g) =>
  ({ A: 'success', B: 'warning', C: 'info', D: 'danger' }[g] || 'info')
</script>

<style scoped>
.section-title {
  font-size: 14px; font-weight: 600; margin: 0 0 12px;
  padding-left: 10px; border-left: 3px solid #409eff; line-height: 1.2;
}
.sub-title { font-size: 13px; font-weight: 600; margin: 12px 0 8px; color: #606266; }
.plain-list { margin: 0; padding-left: 20px; font-size: 13px; color: #606266; }
.summary-text { font-size: 13px; color: #606266; margin: 0 0 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 2: 构建验证**

Run: `docker compose build web 2>&1 | tail -5`
Expected: 构建成功（vite 编译无报错退出码 0）

- [ ] **Step 3: Commit**（如用户要求提交）
`git commit -m "feat: JD 解析与汇总排序结果展示组件"`

---

## Task 2: ResumeStepResults.vue 简历级结果组件

**Files:**
- Create: `frontend/src/components/ResumeStepResults.vue`

- [ ] **Step 1: 创建组件（完整代码）**

```vue
<template>
  <div>
    <!-- 解析阶段 -->
    <div v-if="report.raw_text || report.parse_meta">
      <h4 class="stage-title">解析结果</h4>
      <el-collapse>
        <el-collapse-item title="解析详情与简历原文（点击展开）">
          <pre v-if="report.parse_meta" class="meta-block">{{ JSON.stringify(report.parse_meta, null, 2) }}</pre>
          <pre class="raw-text">{{ report.raw_text || '（无原文）' }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 信息提取阶段 -->
    <div v-if="report.profile">
      <h4 class="stage-title">结构化档案</h4>
      <p style="margin: 0 0 8px; font-size: 14px">
        <b>{{ report.profile.name || '未识别姓名' }}</b>
      </p>
      <div v-if="report.profile.skills?.length" style="margin-bottom: 8px">
        <el-tag v-for="s in report.profile.skills" :key="s" size="small"
                style="margin: 0 4px 4px 0">{{ s }}</el-tag>
      </div>
      <el-table v-if="report.profile.work_experience?.length"
                :data="report.profile.work_experience" size="small">
        <el-table-column prop="company" label="公司" min-width="120" />
        <el-table-column prop="title" label="职位" min-width="100" />
        <el-table-column prop="period" label="时间" width="150" />
        <el-table-column prop="summary" label="摘要" show-overflow-tooltip />
      </el-table>
      <el-table v-if="report.profile.education?.length"
                :data="report.profile.education" size="small" style="margin-top: 8px">
        <el-table-column prop="school" label="学校" min-width="120" />
        <el-table-column prop="degree" label="学位" width="90" />
        <el-table-column prop="major" label="专业" min-width="100" />
        <el-table-column prop="period" label="时间" width="150" />
      </el-table>
    </div>

    <!-- 初筛阶段 -->
    <div v-if="report.screening">
      <h4 class="stage-title">初筛结果</h4>
      <el-tag :type="report.screening.passed ? 'success' : 'danger'">
        {{ report.screening.passed ? '通过' : '未通过' }}
      </el-tag>
      <span v-if="!report.screening.passed && report.screening.reject_reason" class="err"
            style="margin-left: 10px">{{ report.screening.reject_reason }}</span>
      <el-table v-if="report.screening.checks?.length"
                :data="report.screening.checks" size="small" style="margin-top: 8px">
        <el-table-column prop="requirement" label="要求" min-width="180" />
        <el-table-column label="是否满足" width="90">
          <template #default="{ row }">
            <el-tag :type="row.met ? 'success' : 'danger'" size="small">
              {{ row.met ? '满足' : '不满足' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="evidence" label="证据" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- 深度评估阶段 -->
    <div v-if="report.evaluation">
      <h4 class="stage-title">深度评估</h4>
      <div class="scores">
        <div v-for="d in SCORE_DIMS" :key="d.key" class="score-item">
          <span class="score-label">{{ d.label }}</span>
          <el-progress :percentage="report.evaluation[d.key] || 0"
                       style="flex: 1; margin-right: 12px" />
          <span class="score-num mono">{{ report.evaluation[d.key] }}</span>
        </div>
      </div>
      <el-row :gutter="16">
        <el-col v-for="g in LIST_GROUPS" :key="g.key" :span="12">
          <h5 class="list-title" :class="g.cls">{{ g.title }}</h5>
          <ul v-if="report.evaluation[g.key]?.length" class="plain-list">
            <li v-for="(item, i) in report.evaluation[g.key]" :key="i">{{ item }}</li>
          </ul>
          <span v-else class="dim">—</span>
        </el-col>
      </el-row>
    </div>

    <!-- 所有阶段均无结果 -->
    <el-empty v-if="noResults" description="该简历暂无步骤结果"
              :image-size="60" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, required: true },
})

const SCORE_DIMS = [
  { key: 'skill_match', label: '技能匹配' },
  { key: 'experience_match', label: '经验匹配' },
  { key: 'stability', label: '稳定性' },
  { key: 'potential', label: '潜力' },
]
const LIST_GROUPS = [
  { key: 'highlights', title: '亮点', cls: 't-green' },
  { key: 'risks', title: '风险点', cls: 't-red' },
  { key: 'gaps', title: '与 JD 差距', cls: 't-orange' },
  { key: 'interview_questions', title: '面试建议问题', cls: '' },
]

const noResults = computed(() =>
  !props.report.raw_text && !props.report.parse_meta &&
  !props.report.profile && !props.report.screening && !props.report.evaluation)
</script>

<style scoped>
.stage-title {
  font-size: 13px; font-weight: 600; margin: 16px 0 8px; color: #606266;
}
.raw-text {
  margin: 0; white-space: pre-wrap; word-break: break-all;
  font-size: 12px; line-height: 1.6; color: #606266;
  max-height: 400px; overflow-y: auto;
}
.meta-block {
  margin: 0 0 8px; font-size: 12px; color: #909399;
  white-space: pre-wrap; background: #f5f7fa; padding: 8px;
}
.scores { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.score-item { display: flex; align-items: center; gap: 8px; }
.score-label { width: 64px; font-size: 12px; color: #606266; flex-shrink: 0; }
.score-num { width: 28px; text-align: right; font-size: 13px; color: #303133; }
.list-title { font-size: 13px; margin: 8px 0 6px; }
.t-green { color: #67c23a; }
.t-red { color: #f56c6c; }
.t-orange { color: #e6a23c; }
.plain-list { margin: 0; padding-left: 18px; font-size: 13px; color: #606266; }
.dim { color: #909399; font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 2: 构建验证**

Run: `docker compose build web 2>&1 | tail -5`
Expected: 构建成功

- [ ] **Step 3: Commit**（如用户要求提交）
`git commit -m "feat: 简历步骤结果展示组件"`

---

## Task 3: TaskDetail.vue 集成与懒加载

**Files:**
- Modify: `frontend/src/views/TaskDetail.vue`

- [ ] **Step 1: template 修改 —— 任务级卡片之后插入结果卡**

在第一个 `</el-card>`（任务概要卡结束）与简历明细 `<el-card>` 之间插入：

```vue
    <JDParsedCard v-if="task.jd_parsed || (task.summary_report && !task.summary_report.error)"
                  :jd-parsed="task.jd_parsed" :summary-report="task.summary_report" />
```

- [ ] **Step 2: template 修改 —— el-collapse 加 v-model 与 @change**

将简历明细卡的 `<el-collapse>` 改为：

```vue
      <el-collapse v-model="activePanels" @change="onCollapseChange">
```

- [ ] **Step 3: template 修改 —— 面板内步骤条之后、LLM 调用表之前插入结果区**

在每个 `el-collapse-item` 内 `<el-steps ...>...</el-steps>` 之后插入：

```vue
          <div style="margin-bottom: 16px">
            <ResumeStepResults v-if="reportCache[r.id]" :report="reportCache[r.id]" />
            <div v-else-if="loadingReports[r.id]" v-loading="true"
                 style="height: 60px"></div>
            <div v-else-if="reportErrors[r.id]">
              <el-alert type="error" :closable="false"
                        :title="`结果加载失败：${reportErrors[r.id]}`" />
              <el-button size="small" style="margin-top: 8px"
                         @click="ensureReport(r.id)">重试</el-button>
            </div>
          </div>
```

- [ ] **Step 4: script 修改 —— import 与懒加载逻辑**

`<script setup>` 中，将 `import { getTask } from '../api'` 改为：

```js
import { getTask, getResumeReport } from '../api'
import JDParsedCard from '../components/JDParsedCard.vue'
import ResumeStepResults from '../components/ResumeStepResults.vue'
```

在 `const loading = ref(true)` 之后追加：

```js
const activePanels = ref([])
const reportCache = ref({})
const loadingReports = ref({})
const reportErrors = ref({})

async function ensureReport(resumeId) {
  if (reportCache.value[resumeId] || loadingReports.value[resumeId]) return
  loadingReports.value[resumeId] = true
  reportErrors.value[resumeId] = null
  try {
    reportCache.value[resumeId] = await getResumeReport(resumeId)
  } catch (e) {
    reportErrors.value[resumeId] = e.message || '未知错误'
  } finally {
    loadingReports.value[resumeId] = false
  }
}

function onCollapseChange(names) {
  ;(names || []).forEach((n) => ensureReport(Number(n)))
}
```

- [ ] **Step 5: 构建验证**

Run: `docker compose build web 2>&1 | tail -5`
Expected: 构建成功

- [ ] **Step 6: Commit**（如用户要求提交）
`git commit -m "feat: 执行详情页集成步骤结果展示（懒加载）"`

---

## Task 4: 端到端手动验证

- [ ] **Step 1: 启动服务**

Run: `docker compose up -d 2>&1 | tail -3`
Expected: db/api/web 全部 Up

- [ ] **Step 2: 手动验证清单**（打开 http://localhost:8080/tasks）

1. **完成任务**：点「执行详情」→ 任务级出现「JD 解析结果」（职责/硬性要求表/权重/加分项）与「汇总排序结果」（summary + 排名表）；展开简历面板 → 四阶段结果区块齐全（原文折叠可展开、档案含技能 tags 与经历表、初筛 checks 表、评估分数条与四组列表）。
2. **懒加载与缓存**：展开-收起-再展开同一简历，Network 面板确认 `/api/resumes/{id}/report` 仅请求一次。
3. **失败/旧任务**：打开失败任务或旧任务详情页，已到达阶段展示结果、未到达阶段无内容不报错；`stage_timeline` 为空的任务页面正常。
4. **错误重试**：停掉 api 容器（`docker compose stop api`）展开面板 → 显示错误提示；重启 api 后点「重试」→ 结果正常渲染。
5. **回归**：步骤条/耗时/LLM 调用表等既有功能不受影响；TaskResult 页抽屉报告正常。

- [ ] **Step 3: Commit**（如用户要求提交）
`git commit -m "test: 验证步骤结果展示端到端功能"`

---

## Self-Review 结论

- **Spec 覆盖**：JD 解析结果（Task 1）、汇总排序（Task 1）、解析原文折叠（Task 2）、结构化档案（Task 2）、初筛（Task 2）、深度评估（Task 2）、懒加载缓存与错误重试（Task 3）、兼容性与手动验证（Task 4）——全覆盖。
- **占位符扫描**：所有代码步骤均为完整代码，无 TBD/TODO。
- **类型一致性**：`JDParsedCard` props（`jdParsed`/`summaryReport`）与 Task 3 中 `:jd-parsed`/`:summary-report` 对应；`ResumeStepResults` prop（`report`）与 `:report` 对应；`getResumeReport` 已存在于 api.js；`ensureReport`/`onCollapseChange`/`reportCache` 等命名在 Task 3 各步骤间一致。
- **向后兼容**：组件均为条件渲染（`v-if` 数据存在），旧任务无数据时不显示、不报错。
