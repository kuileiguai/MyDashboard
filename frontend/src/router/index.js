import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/HomeView.vue') },
  { path: '/commands', name: 'Commands', component: () => import('../views/CommandsView.vue') },
  { path: '/files', name: 'Files', component: () => import('../views/FilesView.vue') },
  { path: '/ports', name: 'Ports', component: () => import('../views/PortsView.vue') },
  { path: '/terminal', name: 'Terminal', component: () => import('../views/TerminalView.vue') },
  { path: '/system', name: 'System', component: () => import('../views/SystemView.vue') },
  { path: '/logs', name: 'Logs', component: () => import('../views/LogsView.vue') },
  { path: '/env', name: 'Env', component: () => import('../views/EnvView.vue') },
  { path: '/ssh', name: 'Ssh', component: () => import('../views/SshView.vue') },
  { path: '/quickpalette', name: 'QuickPalette', component: () => import('../views/QuickPalette.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
