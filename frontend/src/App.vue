<template>
  <div class="app-container" :class="{ dark: isDark }">
    <router-view v-if="isPalette || isLogin" />
    <template v-else>
    <DependencyBanner ref="depBanner" />
    <el-container>
      <!-- Sidebar -->
      <el-aside :width="isCollapsed ? '64px' : '220px'" class="app-sidebar">
        <div class="sidebar-header" @click="isCollapsed = !isCollapsed">
          <div class="brand-logo">
            <img :src="deckpitLogo" alt="Deckpit" />
          </div>
          <div v-show="!isCollapsed" class="brand-text">
            <span class="sidebar-title">Deckpit</span>
            <span class="sidebar-sub">DEVELOPER DECK</span>
          </div>
        </div>

        <!-- default-active 必须绑到路由：el-menu 没有 active 这个 prop，
             之前用 v-model:active 等于没绑定，程序化 router.push 时侧栏不会跟着变 -->
        <el-menu :default-active="activeMenu" :collapse="isCollapsed" :router="true"
          background-color="transparent" class="sidebar-menu">
          <el-menu-item index="/"><el-icon><HomeFilled /></el-icon><span>首页</span></el-menu-item>
          <el-menu-item index="/commands"><el-icon><Document /></el-icon><span>命令手册</span></el-menu-item>
          <el-menu-item index="/files"><el-icon><FolderOpened /></el-icon><span>文件管理</span></el-menu-item>
          <el-menu-item index="/ports"><el-icon><Connection /></el-icon><span>端口监控</span></el-menu-item>
          <el-menu-item index="/terminal"><el-icon><Monitor /></el-icon><span>终端中心</span></el-menu-item>
          <el-menu-item index="/system"><el-icon><Odometer /></el-icon><span>系统监控</span></el-menu-item>
          <el-menu-item index="/logs"><el-icon><Tickets /></el-icon><span>日志查看</span></el-menu-item>
          <el-menu-item index="/env"><el-icon><Setting /></el-icon><span>环境管理</span></el-menu-item>
          <el-menu-item index="/ssh"><el-icon><Link /></el-icon><span>SSH 管理</span></el-menu-item>
          <el-menu-item index="/docker"><el-icon><Box /></el-icon><span>Docker 管理</span></el-menu-item>
        </el-menu>

        <div class="sidebar-footer">
          <el-tooltip v-if="auth.authenticated" content="退出登录" placement="right">
            <div class="dep-status" @click="onLogout">
              <el-icon :size="14"><SwitchButton /></el-icon>
              <span v-if="!isCollapsed" class="dep-label">退出登录</span>
            </div>
          </el-tooltip>
          <el-switch v-model="isDark" :active-icon="Moon" :inactive-icon="Sunny" size="small" @change="toggleTheme" />
          <div class="dep-status" @click="showDepDialog = true" :title="depStatusText">
            <el-icon :size="14" :color="depFullyOk ? '#67c23a' : '#e6a23c'">
              <CircleCheck v-if="depFullyOk" /><WarningFilled v-else />
            </el-icon>
            <span v-if="!isCollapsed" class="dep-label">
              {{ depFullyOk ? '依赖就绪' : (depRequiredMissing.length ? '缺少依赖' : '可选未装') }}
            </span>
          </div>
        </div>
      </el-aside>

      <!-- Main content -->
      <el-main class="app-main">
        <router-view v-slot="{ Component, route }">
          <Transition name="deck-page" mode="out-in">
            <component :is="Component" :key="route.path" />
          </Transition>
        </router-view>
      </el-main>
    </el-container>

    <!-- 依赖管理弹窗 -->
    <el-dialog v-model="showDepDialog" title="系统依赖管理" width="550px">
      <el-table :data="depList" size="small">
        <el-table-column label="工具" width="120">
          <template #default="{ row }">
            <el-tag :type="row.installed ? 'success' : 'danger'" size="small">{{ row.name }}</el-tag>
            <el-tag v-if="row.optional" size="small" type="info" style="margin-left: 4px">可选</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="用途" show-overflow-tooltip />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-icon v-if="row.installed" color="#67c23a"><CircleCheck /></el-icon>
            <el-icon v-else color="#f56c6c"><Close /></el-icon>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showDepDialog = false">关闭</el-button>
        <el-button @click="refreshDeps"><el-icon><Refresh /></el-icon> 重新检测</el-button>
        <el-button type="primary" @click="installDeps" :loading="depInstalling" :disabled="depFullyOk">
          <el-icon><Download /></el-icon>
          {{ depOptionalMissing.length && !depRequiredMissing.length ? '安装可选依赖' : '一键安装缺失依赖' }}
        </el-button>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Sunny, Moon, CircleCheck, WarningFilled, Download, SwitchButton } from '@element-plus/icons-vue'
import DependencyBanner from './components/DependencyBanner.vue'
import deckpitLogo from './assets/deckpit-logo.png'
import api from './api'
import { auth, refreshAuth, logout } from './stores/auth'

const route = useRoute()
const router = useRouter()
const isCollapsed = ref(false)
const isDark = ref(false)
const isPalette = computed(() => route.name === 'QuickPalette')
const isLogin = computed(() => route.name === 'Login')

const activeMenu = computed(() => {
  const path = route.path
  if (path.startsWith('/commands')) return '/commands'
  if (path.startsWith('/files')) return '/files'
  if (path.startsWith('/ports')) return '/ports'
  if (path.startsWith('/terminal')) return '/terminal'
  if (path.startsWith('/system')) return '/system'
  if (path.startsWith('/logs')) return '/logs'
  if (path.startsWith('/env')) return '/env'
  if (path.startsWith('/ssh')) return '/ssh'
  if (path.startsWith('/docker')) return '/docker'
  // 分类字典是命令手册的子页面，高亮保持在「命令手册」
  if (path.startsWith('/taxonomy')) return '/commands'
  return '/'
})

const savedTheme = localStorage.getItem('dash-theme')
if (savedTheme === 'dark') {
  isDark.value = true; document.documentElement.classList.add('dark')
} else if (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches) {
  isDark.value = true; document.documentElement.classList.add('dark')
}

function toggleTheme(val) {
  document.documentElement.classList.toggle('dark', val)
  localStorage.setItem('dash-theme', val ? 'dark' : 'light')
}

// ── 依赖管理 ──
const showDepDialog = ref(false)
const depList = ref([])
const depAllOk = ref(true)
const depInstalling = ref(false)

const depRequiredMissing = computed(() => depList.value.filter(d => !d.installed && !d.optional).map(d => d.name))
const depOptionalMissing = computed(() => depList.value.filter(d => !d.installed && d.optional).map(d => d.name))
const depFullyOk = computed(() => !depRequiredMissing.value.length && !depOptionalMissing.value.length)

const depStatusText = computed(() => {
  const req = depRequiredMissing.value
  const opt = depOptionalMissing.value
  if (!req.length && !opt.length) return '系统依赖就绪'
  const parts = []
  if (req.length) parts.push('缺少: ' + req.join(', '))
  if (opt.length) parts.push('可选未装: ' + opt.join(', '))
  return parts.join('；')
})

async function refreshDeps() {
  try {
    const { data } = await api.get('/system/dependencies')
    const list = []
    for (const [name, info] of Object.entries(data.tools || {})) list.push({ name, ...info })
    depList.value = list
    depAllOk.value = data.all_ok
  } catch (_) {}
}

async function installDeps() {
  depInstalling.value = true
  try {
    // include_optional=true：可选依赖（如 sshpass）也要一起装，否则会提示「已安装」但实际没装
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true&include_optional=true')
    if (data.ok) { ElMessage.success(data.message); await refreshDeps() }
    else {
      ElMessage.error(data.message || '安装失败')
      if (data.stderr) console.error('[依赖安装]', data.stderr)
    }
  } catch (e) { ElMessage.error('安装请求失败') }
  depInstalling.value = false
}

// 会话过期 / 未授权（HTTP 401 或 WS 1008）→ 复核状态并按需跳登录页
async function onUnauthorized() {
  await refreshAuth()
  if (auth.authRequired && !auth.authenticated && route.name !== 'Login') {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
  }
}

async function onLogout() {
  await logout()
  router.push('/login')
}

onMounted(() => {
  window.addEventListener('dash:unauthorized', onUnauthorized)
  if (!isPalette.value && !isLogin.value) refreshDeps()
})

onUnmounted(() => {
  window.removeEventListener('dash:unauthorized', onUnauthorized)
})
</script>

<style scoped>
.app-container { height: 100vh; background: transparent; color: var(--el-text-color-primary); }
.app-sidebar {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--deck-navy);
  color: #f7f3eb;
  border-right: 1px solid rgba(255,255,255,0.08);
  transition: width 0.24s cubic-bezier(.2,.8,.2,1);
  overflow: hidden;
  z-index: 10;
}
.sidebar-header {
  height: 82px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.brand-logo {
  width: 46px;
  height: 46px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 13px;
  background: #fffdf9;
  overflow: hidden;
  box-shadow: 0 3px 14px rgba(0,0,0,.18);
}
.brand-logo img { width: 100%; height: 100%; object-fit: cover; }
.brand-text { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.25; }
.sidebar-title { font-size: 17px; font-weight: 800; letter-spacing: 0.2px; color: #fffaf0; }
.sidebar-sub { font-size: 9px; color: #d6b98f; letter-spacing: 1.35px; }
.sidebar-menu { flex: 1; border-right: none !important; background: transparent; }
.sidebar-footer { padding: 12px; display: flex; flex-direction: column; align-items: center; gap: 10px; border-top: 1px solid rgba(255,255,255,0.1); }
.app-main { height: 100vh; overflow-y: auto; padding: 0; background: transparent; }

.dep-status {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  transition: background 0.15s ease;
}
.dep-status:hover { background: var(--el-fill-color-light); }
.dep-label { color: var(--el-text-color-secondary); white-space: nowrap; font-size: 11px; }
.app-sidebar .el-menu-item { color: #d8dfE8; }
.app-sidebar .el-menu-item .el-icon { color: #c4d0dc; }
.app-sidebar .el-menu-item:not(.is-active):hover { background: rgba(255,255,255,.08); color: #fff; }
.app-sidebar .el-menu-item.is-active { background: var(--deck-amber); color: #171d26; box-shadow: 0 5px 14px rgba(232,121,36,.2); }
.app-sidebar .el-menu-item.is-active .el-icon { color: #171d26; }
.app-sidebar .dep-status { color: #d8dfe8; }
.app-sidebar .dep-label { color: #d8dfe8; }
.app-sidebar .el-switch { --el-switch-on-color: #e87924; }

@media (max-width: 720px) {
  .app-sidebar { max-width: 58px; }
  .sidebar-header { height: 68px; }
  .brand-logo { width: 38px; height: 38px; }
}
</style>
