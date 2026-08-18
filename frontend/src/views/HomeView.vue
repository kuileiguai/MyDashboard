<template>
  <div class="home-view">
    <h2 class="page-title">首页面板</h2>

    <!-- System Overview Cards -->
    <el-row :gutter="16" class="overview-row">
      <el-col :xs="24" :sm="12" :md="6" v-if="snapshot">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">CPU</div>
          <div class="stat-value">{{ snapshot.cpu?.total || 0 }}%</div>
          <el-progress :percentage="snapshot.cpu?.total || 0" :color="cpuColor" :stroke-width="6" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6" v-if="snapshot">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">内存</div>
          <div class="stat-value">{{ snapshot.memory?.percent || 0 }}%</div>
          <el-progress :percentage="snapshot.memory?.percent || 0" color="#e6a23c" :stroke-width="6" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6" v-if="snapshot?.gpu?.available">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">GPU</div>
          <div class="stat-value" v-if="snapshot.gpu.devices?.[0]">{{ snapshot.gpu.devices[0].gpu_util }}%</div>
          <el-progress v-if="snapshot.gpu.devices?.[0]" :percentage="snapshot.gpu.devices[0].gpu_util" color="#67c23a" :stroke-width="6" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6" v-if="snapshot?.disks?.[0]">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-label">磁盘 {{ snapshot.disks[0].mountpoint }}</div>
          <div class="stat-value">{{ snapshot.disks[0].percent }}%</div>
          <el-progress :percentage="snapshot.disks[0].percent" :color="snapshot.disks[0].percent > 90 ? '#f56c6c' : '#909399'" :stroke-width="6" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Top Commands -->
    <el-card shadow="hover" class="section-card" v-if="topCommands.length">
      <template #header><span>🔥 常用命令 Top5</span></template>
      <div class="top-cmds">
        <div v-for="(c, i) in topCommands" :key="c.id" class="top-cmd-item" @click="runCommand(c)">
          <el-tag type="warning" size="small">#{{ i + 1 }}</el-tag>
          <code>{{ c.command }}</code>
          <small>({{ c.use_count }}次)</small>
        </div>
      </div>
    </el-card>

    <!-- Active Terminals -->
    <el-card shadow="hover" class="section-card">
      <template #header>
        <div class="card-header">
          <span>活跃终端</span>
          <el-button size="small" type="primary" @click="$router.push('/terminal')">打开终端中心</el-button>
        </div>
      </template>
      <el-empty v-if="!terminalStore.sessions.length" description="暂无活跃终端" />
      <div v-else class="terminal-chips">
        <el-tag v-for="s in terminalStore.sessions" :key="s.session_id" :type="s.status === 'yellow' ? 'warning' : 'success'"
          class="chip" @click="$router.push('/terminal')">
          {{ s.name }} <small>({{ s.cwd?.split('/').pop() || s.cwd }})</small>
        </el-tag>
      </div>
    </el-card>

    <!-- Quick Actions -->
    <el-card shadow="hover" class="section-card">
      <template #header><span>⚡ 一键操作</span></template>
      <div class="quick-actions">
        <el-button v-for="a in quickActions" :key="a.name" @click="executeAction(a)" :icon="a.icon">
          {{ a.name }}
        </el-button>
      </div>
    </el-card>

    <!-- Projects -->
    <el-card shadow="hover" class="section-card">
      <template #header>
        <div class="card-header">
          <span>📁 项目</span>
          <el-button size="small" @click="showProjectDialog = true"><el-icon><Plus /></el-icon></el-button>
        </div>
      </template>
      <el-empty v-if="!projects.length" description="暂无项目" />
      <div v-else class="project-list">
        <el-card v-for="p in projects" :key="p.id" shadow="never" class="project-card">
          <strong>{{ p.name }}</strong>
          <div class="project-meta">
            <small>路径: {{ p.root_path }}</small>
            <small v-if="p.env_name">环境: {{ p.env_name }}</small>
          </div>
        </el-card>
      </div>
    </el-card>

    <!-- Recent Files -->
    <el-card shadow="hover" class="section-card">
      <template #header><span>最近文件</span></template>
      <el-empty v-if="!recentFiles.length" description="暂无记录" />
      <div v-else class="recent-list">
        <div v-for="f in recentFiles" :key="f.id" class="recent-item">
          <el-icon><Document /></el-icon><span>{{ f.path }}</span>
        </div>
      </div>
    </el-card>

    <!-- Project Dialog -->
    <el-dialog v-model="showProjectDialog" title="新建项目" width="450px">
      <el-form :model="projectForm" label-width="80px">
        <el-form-item label="名称"><el-input v-model="projectForm.name" /></el-form-item>
        <el-form-item label="根路径"><el-input v-model="projectForm.root_path" placeholder="~/projects/my-app" /></el-form-item>
        <el-form-item label="环境"><el-input v-model="projectForm.env_name" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProjectDialog = false">取消</el-button>
        <el-button type="primary" @click="createProject">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useSystemStore } from '../stores/system'
import { useTerminalStore } from '../stores/terminal'
import api from '../api'

const systemStore = useSystemStore()
const terminalStore = useTerminalStore()
const recentFiles = ref([]); const topCommands = ref([]); const quickActions = ref([]); const projects = ref([])
const showProjectDialog = ref(false); const projectForm = ref({ name: '', root_path: '', env_name: '' })

const snapshot = computed(() => systemStore.snapshot)
const cpuColor = computed(() => { const p = systemStore.snapshot?.cpu?.total || 0; if (p > 80) return '#f56c6c'; if (p > 50) return '#e6a23c'; return '#67c23a' })

async function fetchDashboard() {
  try {
    const { data } = await api.get('/dashboard/summary')
    recentFiles.value = data.recent_files || []
    topCommands.value = data.top_commands || []
    projects.value = data.projects || []
  } catch (_) {}
}
async function fetchQuickActions() { try { const { data } = await api.get('/dashboard/quick-actions'); quickActions.value = data } catch (_) {} }
async function executeAction(action) {
  try { const { data } = await api.post('/dashboard/execute-action', null, { params: { command: action.command } })
    ElMessage.success(`已发送: ${action.name}`) } catch (_) { ElMessage.error('执行失败') }
}
async function runCommand(cmd) {
  try { await api.post('/terminal/create', { name: cmd.command.substring(0, 20), cwd: '~', shell: '/bin/bash', command: cmd.command })
    await api.post(`/commands/${cmd.id}/use`); ElMessage.success('已发送到终端') } catch (_) {}
}
async function createProject() {
  try { await api.post('/dashboard/projects', projectForm.value); ElMessage.success('项目已创建'); showProjectDialog.value = false; fetchDashboard() } catch (_) { ElMessage.error('创建失败') }
}

onMounted(() => { systemStore.startMonitor(); terminalStore.fetchSessions(); fetchDashboard(); fetchQuickActions() })
onUnmounted(() => { systemStore.stopMonitor() })
</script>

<style scoped>
.home-view { padding: 20px; }
.page-title { margin-bottom: 20px; font-size: 20px; font-weight: 600; }
.overview-row { margin-bottom: 16px; }
.stat-card { text-align: center; }
.stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
.stat-value { font-size: 28px; font-weight: 700; margin: 8px 0; }
.section-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.terminal-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { cursor: pointer; }
.recent-list { display: flex; flex-direction: column; gap: 8px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; color: var(--el-text-color-regular); border-bottom: 1px solid var(--el-border-color-lighter); }
.top-cmds { display: flex; flex-direction: column; gap: 8px; }
.top-cmd-item { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 4px 0; }
.top-cmd-item:hover { background: var(--el-fill-color-light); }
.top-cmd-item code { font-size: 13px; }
.quick-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.project-list { display: flex; gap: 12px; flex-wrap: wrap; }
.project-card { width: 250px; }
.project-meta { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; color: var(--el-text-color-secondary); }
</style>
