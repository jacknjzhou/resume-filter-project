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
      <el-table-column width="160" label="操作">
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
