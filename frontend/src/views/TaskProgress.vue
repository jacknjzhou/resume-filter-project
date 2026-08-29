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

// 全量刷新一次任务状态：覆盖初始查询与 SSE 订阅建立之间丢失的事件
async function syncTask() {
  const task = await getTask(route.params.id)
  task.resumes.forEach((r) => {
    const row = rows.value.find((x) => x.id === r.id)
    if (row && r.status !== 'pending') row.status = r.status
  })
  if (task.status === 'done' || task.status === 'failed') {
    finished.value = true
    if (es) es.close()
    return true
  }
  return false
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
  // 订阅建立后再同步一次，防止订阅前发生的状态变更丢失
  await syncTask()
  // 断连（服务端已结束流/网络中断）时检查终态，避免 EventSource 无效重连
  es.onerror = () => { syncTask().catch(() => {}) }
})
onUnmounted(() => es && es.close())
</script>
