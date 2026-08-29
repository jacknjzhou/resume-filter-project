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
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { getTask, getResumeReport, exportUrl } from '../api'

const route = useRoute()
const task = ref(null)
const detail = ref(null)
const drawer = ref(false)
const radarEl = ref(null)
let chart = null

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
    chart = echarts.getInstanceByDom(radarEl.value) || echarts.init(radarEl.value)
    chart.setOption({
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
onUnmounted(() => { chart && chart.dispose() })
</script>
