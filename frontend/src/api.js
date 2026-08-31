export async function createTask({ jdFile, jdText, resumeFiles, pastedTexts }) {
  const fd = new FormData()
  if (jdFile) fd.append('jd_file', jdFile)
  if (jdText) fd.append('jd_text', jdText)
  resumeFiles.forEach((f) => fd.append('resumes', f))
  pastedTexts.forEach((t) => fd.append('pasted_texts', t))
  const resp = await fetch('/api/tasks', { method: 'POST', body: fd })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `创建失败 (${resp.status})`)
  }
  return resp.json()
}

export async function getTask(id) {
  const resp = await fetch(`/api/tasks/${id}`)
  if (!resp.ok) throw new Error('任务不存在')
  return resp.json()
}

export async function getResumeReport(id) {
  const resp = await fetch(`/api/resumes/${id}/report`)
  if (!resp.ok) throw new Error('报告不存在')
  return resp.json()
}

export function exportUrl(id, format) {
  return `/api/tasks/${id}/export?format=${format}`
}

export function subscribeEvents(taskId, onEvent) {
  const es = new EventSource(`/api/tasks/${taskId}/events`)
  es.onmessage = (e) => onEvent(JSON.parse(e.data))
  return es
}

export async function listTasks(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  ).toString()
  const resp = await fetch(`/api/tasks${qs ? `?${qs}` : ''}`)
  if (!resp.ok) throw new Error('获取任务列表失败')
  return resp.json()
}

export async function getSettings() {
  const resp = await fetch('/api/settings')
  if (!resp.ok) throw new Error('获取配置失败')
  return resp.json()
}

export async function updateSettings(values) {
  const resp = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `保存失败 (${resp.status})`)
  }
  return resp.json()
}
