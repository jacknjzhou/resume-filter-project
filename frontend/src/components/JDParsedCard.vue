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
