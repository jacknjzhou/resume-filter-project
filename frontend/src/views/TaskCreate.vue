<template>
  <el-card>
    <h3>创建筛选任务</h3>
    <el-form label-width="90px">
      <el-form-item label="JD">
        <el-input v-model="jdText" type="textarea" :rows="6"
                  placeholder="粘贴职位描述，或选择 JD 文件" />
      </el-form-item>
      <el-form-item label="JD 文件">
        <input type="file" accept=".txt,.pdf,.docx" @change="onJdFile" />
      </el-form-item>
      <el-form-item label="简历文件">
        <input type="file" multiple accept=".pdf,.docx,.png,.jpg,.jpeg,.txt" @change="onResumes" />
        <el-tag v-for="(f, i) in resumeFiles" :key="i" closable style="margin-left: 8px"
                @close="resumeFiles.splice(i, 1)">{{ f.name }}</el-tag>
      </el-form-item>
      <el-form-item label="粘贴简历">
        <el-input v-model="pastedText" type="textarea" :rows="4"
                  placeholder="也可直接粘贴纯文本简历（与文件合计不超过 10 份）" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="submitting" @click="submit">开始筛选</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTask } from '../api'

const router = useRouter()
const jdText = ref('')
const jdFile = ref(null)
const resumeFiles = ref([])
const pastedText = ref('')
const submitting = ref(false)

function onJdFile(e) { jdFile.value = e.target.files[0] || null }
function onResumes(e) { resumeFiles.value = Array.from(e.target.files || []) }

async function submit() {
  if (!jdText.value && !jdFile.value) return ElMessage.warning('请提供 JD')
  const total = resumeFiles.value.length + (pastedText.value.trim() ? 1 : 0)
  if (total < 1) return ElMessage.warning('请至少提供一份简历')
  if (total > 10) return ElMessage.warning('单次任务最多 10 份简历')
  submitting.value = true
  try {
    const { task_id } = await createTask({
      jdFile: jdFile.value, jdText: jdText.value,
      resumeFiles: resumeFiles.value, pastedTexts: pastedText.value.trim() ? [pastedText.value] : [],
    })
    router.push(`/task/${task_id}/progress`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>
