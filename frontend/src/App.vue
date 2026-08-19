<template>
  <div class="app-container" :class="{ dark: isDark }">
    <router-view v-if="isPalette" />
    <template v-else>
    <DependencyBanner ref="depBanner" />
    <el-container>
      <!-- Sidebar -->
      <el-aside :width="isCollapsed ? '64px' : '220px'" class="app-sidebar">
        <div class="sidebar-header" @click="isCollapsed = !isCollapsed">
          <div class="brand-logo">
            <el-icon :size="18"><Monitor /></el-icon>
          </div>
          <div v-show="!isCollapsed" class="brand-text">
            <span class="sidebar-title">Dev Dash</span>
            <span class="sidebar-sub">管理后台</span>
          </div>
        </div>

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
          <el-switch v-model="isDark" :active-icon="Moon" :inactive-icon="Sunny" size="small" @change="toggleTheme" />
          <div class="dep-status" @click="showDepDialog = true" :title="depStatusText">
            <el-icon :size="14" :color="depAllOk ? '#67c23a' : '#e6a23c'">
              <CircleCheck v-if="depAllOk" /><WarningFilled v-else />
            </el-icon>
            <span v-if="!isCollapsed" class="dep-label">{{ depAllOk ? '依赖就绪' : '缺少依赖' }}</span>
          </div>
        </div>
      </el-aside>

      <!-- Main content -->
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 依赖管理弹窗 -->
    <el-dialog v-model="showDepDialog" title="系统依赖管理" width="550px">
      <el-table :data="depList" size="small">
        <el-table-column label="工具" width="120">
          <template #default="{ row }">
            <el-tag :type="row.installed ? 'success' : 'danger'" size="small">{{ row.name }}</el-tag>
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
        <el-button type="primary" @click="installDeps" :loading="depInstalling" :disabled="depAllOk">
          <el-icon><Download /></el-icon> 一键安装缺失依赖
        </el-button>
      </template>
    </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Sunny, Moon, CircleCheck, WarningFilled, Download } from '@element-plus/icons-vue'
import DependencyBanner from './components/DependencyBanner.vue'
import api from './api'

const route = useRoute()
const isCollapsed = ref(false)
const isDark = ref(false)
const isPalette = computed(() => route.name === 'QuickPalette')

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

const depStatusText = computed(() =>
  depAllOk.value ? '系统依赖就绪'
    : '缺少: ' + depList.value.filter(d => !d.installed).map(d => d.name).join(', ')
)

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
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true')
    if (data.ok) { ElMessage.success(data.message); await refreshDeps() }
    else ElMessage.error(data.message || '安装失败')
  } catch (e) { ElMessage.error('安装请求失败') }
  depInstalling.value = false
}

onMounted(() => { if (!isPalette.value) refreshDeps() })
</script>

<style scoped>
.app-container { height: 100vh; background: transparent; color: var(--el-text-color-primary); }
.app-sidebar {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
  border-right: none;
  border-radius: 0 var(--radius-xl) var(--radius-xl) 0;
  box-shadow: 1px 0 0 var(--el-border-color-lighter), var(--shadow-sm);
  transition: width 0.2s;
  overflow: hidden;
  z-index: 10;
}
.sidebar-header {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.brand-logo {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(135deg, var(--ub-rose) 0%, var(--ub-rose-soft) 55%, var(--ub-aubergine) 130%);
  box-shadow: var(--shadow-brand);
}
.brand-text { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.25; }
.sidebar-title { font-size: 16px; font-weight: 800; letter-spacing: 0.5px; color: var(--el-text-color-primary); }
.sidebar-sub { font-size: 10px; color: var(--ub-warm-grey); letter-spacing: 1.5px; }
.sidebar-menu { flex: 1; border-right: none !important; background: transparent; }
.sidebar-footer { padding: 12px; display: flex; flex-direction: column; align-items: center; gap: 10px; border-top: 1px solid var(--el-border-color-lighter); }
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
</style>
