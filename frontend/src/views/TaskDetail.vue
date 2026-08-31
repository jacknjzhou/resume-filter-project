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
  if (e.status === 'failed' || e.status === 'needs_review') return 'error'
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
