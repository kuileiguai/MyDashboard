import { createRouter, createWebHistory } from 'vue-router'
import { auth, refreshAuth } from '../stores/auth'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'Home', component: () => import('../views/HomeView.vue') },
  { path: '/commands', name: 'Commands', component: () => import('../views/CommandsView.vue') },
  { path: '/files', name: 'Files', component: () => import('../views/FilesView.vue') },
  { path: '/ports', name: 'Ports', component: () => import('../views/PortsView.vue') },
  { path: '/terminal', name: 'Terminal', component: () => import('../views/TerminalView.vue') },
  { path: '/system', name: 'System', component: () => import('../views/SystemView.vue') },
  { path: '/logs', name: 'Logs', component: () => import('../views/LogsView.vue') },
  { path: '/env', name: 'Env', component: () => import('../views/EnvView.vue') },
  { path: '/ssh', name: 'Ssh', component: () => import('../views/SshView.vue') },
  { path: '/docker', name: 'Docker', component: () => import('../views/DockerView.vue') },
  { path: '/quickpalette', name: 'QuickPalette', component: () => import('../views/QuickPalette.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  // 悬浮小窗走本机直连，不参与登录校验
  if (to.name === 'QuickPalette') return true

  if (!auth.checked) await refreshAuth()

  if (auth.authRequired && !auth.authenticated) {
    if (to.path === '/login') return true
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login') return { path: '/' }
  return true
})

export default router
