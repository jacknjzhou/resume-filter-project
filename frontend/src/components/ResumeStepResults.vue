<template>
  <div>
    <!-- 解析阶段 -->
    <div v-if="report?.raw_text || report?.parse_meta">
      <h4 class="stage-title">解析结果</h4>
      <el-collapse>
        <el-collapse-item title="解析详情与简历原文（点击展开）">
          <pre v-if="report.parse_meta" class="meta-block">{{ JSON.stringify(report.parse_meta, null, 2) }}</pre>
          <pre class="raw-text">{{ report.raw_text || '（无原文）' }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 信息提取阶段 -->
    <div v-if="report?.profile">
      <h4 class="stage-title">结构化档案</h4>
      <p style="margin: 0 0 8px; font-size: 14px">
        <b>{{ report.profile.name || '未识别姓名' }}</b>
      </p>
      <div v-if="report.profile.skills?.length" style="margin-bottom: 8px">
        <el-tag v-for="(s, i) in report.profile.skills" :key="i" size="small"
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
    <div v-if="report?.screening">
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
    <div v-if="report?.evaluation">
      <h4 class="stage-title">深度评估</h4>
      <div class="scores">
        <div v-for="d in SCORE_DIMS" :key="d.key" class="score-item">
          <span class="score-label">{{ d.label }}</span>
          <el-progress :percentage="fmtScore(report.evaluation[d.key])"
                       style="flex: 1; margin-right: 12px" />
          <span class="score-num mono">{{ fmtScoreText(report.evaluation[d.key]) }}</span>
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
  !props.report ||
  (!props.report.raw_text && !props.report.parse_meta &&
   !props.report.profile && !props.report.screening && !props.report.evaluation))

const fmtScore = (v) =>
  typeof v === 'number' && Number.isFinite(v) ? v : 0

const fmtScoreText = (v) =>
  typeof v === 'number' && Number.isFinite(v) ? v : '—'
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
.err { color: #f56c6c; font-size: 12px; }
.mono { font-variant-numeric: tabular-nums; }
</style>
