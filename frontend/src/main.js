import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import TaskCreate from './views/TaskCreate.vue'
import TaskProgress from './views/TaskProgress.vue'
import TaskResult from './views/TaskResult.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: TaskCreate },
    { path: '/task/:id/progress', component: TaskProgress },
    { path: '/task/:id', component: TaskResult },
  ],
})

createApp(App).use(ElementPlus).use(router).mount('#app')
