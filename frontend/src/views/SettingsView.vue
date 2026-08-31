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
