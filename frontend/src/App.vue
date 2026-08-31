<template>
  <el-container style="max-width: 1100px; margin: 0 auto; padding: 24px">
    <el-header style="height: auto; margin-bottom: 8px">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span style="font-size: 22px; font-weight: 700; letter-spacing: 0.5px">
          简历审阅系统
        </span>
        <el-menu mode="horizontal" router :default-active="activeNav"
                 :ellipsis="false" style="border-bottom: none">
          <el-menu-item index="/">新建任务</el-menu-item>
          <el-menu-item index="/tasks">历史任务</el-menu-item>
          <el-menu-item index="/settings">模型配置</el-menu-item>
        </el-menu>
      </div>
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
const route = useRoute()
const activeNav = computed(() => {
  if (route.path.startsWith('/task') && route.path.endsWith('/detail')) return '/tasks'
  if (route.path.startsWith('/task')) return '/'
  return route.path
})
</script>
