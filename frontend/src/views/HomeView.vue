<template>
  <div class="home-view">
    <!-- 系统状态条 -->
    <div class="sys-bar">
      <div class="sys-item" @click="$router.push('/system')" title="点击查看系统监控">
        <span class="sys-label">CPU</span>
        <el-progress :percentage="snapshot.cpu?.total || 0" :color="cpuColor" :stroke-width="8" />
      </div>
      <div class="sys-item" @click="$router.push('/system')" title="点击查看系统监控">
        <span class="sys-label">内存</span>
        <el-progress :percentage="snapshot.memory?.percent || 0" color="#e6a23c" :stroke-width="8" />
      </div>
      <div class="sys-item" v-if="gpuAvail" @click="$router.push('/system')" title="点击查看系统监控">
        <span class="sys-label">GPU</span>
        <el-progress :percentage="gpuUtil" color="#67c23a" :stroke-width="8" />
      </div>
      <div class="sys-item" @click="$router.push('/system')" title="点击查看系统监控">
        <span class="sys-label">磁盘 {{ rootDisk?.mountpoint }}</span>
        <el-progress :percentage="rootDisk?.percent || 0" :color="rootDisk?.percent > 90 ? '#f56c6c' : '#909399'" :stroke-width="8" />
      </div>
    </div>

    <!-- 模块快捷入口 -->
    <div class="module-grid">
      <el-card v-for="m in modules" :key="m.path" shadow="hover" class="module-card" @click="$router.push(m.path)">
        <el-icon :size="24" :color="m.color"><component :is="m.icon" /></el-icon>
        <div class="module-info">
          <div class="module-name">{{ m.name }}</div>
          <div class="module-status">{{ m.status || m.desc }}</div>
        </div>
      </el-card>
    </div>

    <el-row :gutter="16">
      <!-- 常用命令 Top -->
      <el-col :xs="24" :md="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span>🔥 常用命令 Top5</span>
              <el-button size="small" text type="primary" @click="$router.push('/commands')">去命令手册 →</el-button>
            </div>
          </template>
          <el-empty v-if="!topCommands.length" description="暂无使用记录" />
          <div v-else class="top-cmds">
            <div v-for="(c, i) in topCommands" :key="c.id" class="top-cmd-item" @click="runCommand(c)">
              <el-tag type="warning" size="small">#{{ i + 1 }}</el-tag>
              <code>{{ c.command }}</code>
              <small>({{ c.use_count }}次)</small>
              <el-icon class="op" @click.stop="copyText(c.command)" title="复制"><CopyDocument /></el-icon>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 磁盘分区概况 -->
      <el-col :xs="24" :md="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span>💾 磁盘分区</span>
              <el-button size="small" text type="primary" @click="$router.push('/system')">方块图 →</el-button>
            </div>
          </template>
          <el-empty v-if="!disks.length" description="暂无数据" />
          <div v-else class="disk-top">
            <div v-for="d in disks" :key="d.mountpoint" class="disk-item">
              <div class="disk-item-head">
                <span class="disk-name" :title="d.mountpoint">{{ d.mountpoint }}</span>
                <span class="disk-size">{{ d.percent }}% · {{ fmtBytes(d.used) }}/{{ fmtBytes(d.total) }}</span>
              </div>
              <el-progress :percentage="d.percent" :color="d.percent > 90 ? '#f56c6c' : d.percent > 60 ? '#e6a23c' : '#67c23a'" :stroke-width="8" />
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <!-- 活跃终端 -->
      <el-col :xs="24" :md="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span>活跃终端</span>
              <el-button size="small" text type="primary" @click="$router.push('/terminal')">打开终端中心 →</el-button>
            </div>
          </template>
          <el-empty v-if="!terminalStore.sessions.length" description="暂无活跃终端" />
          <div v-else class="terminal-chips">
            <el-tag v-for="s in terminalStore.sessions" :key="s.session_id" :type="s.status === 'yellow' ? 'warning' : 'success'"
              class="chip" @click="$router.push('/terminal')">
              {{ s.name }} <small>({{ (s.cwd || '').split('/').filter(Boolean).pop() || s.cwd }})</small>
            </el-tag>
          </div>
        </el-card>
      </el-col>

      <!-- 最近文件 -->
      <el-col :xs="24" :md="12">
        <el-card shadow="hover" class="section-card">
          <template #header>
            <div class="card-header">
              <span>最近文件</span>
              <el-button size="small" text type="primary" @click="$router.push('/files')">文件管理 →</el-button>
            </div>
          </template>
          <el-empty v-if="!recentFiles.length" description="暂无记录" />
          <div v-else class="recent-list">
            <div v-for="f in recentFiles" :key="f.id" class="recent-item" @click="copyText(f.path)">
              <el-icon><Document /></el-icon><span>{{ f.path }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
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
const recentFiles = ref([])
const topCommands = ref([])
const modules = ref([])

const snapshot = computed(() => systemStore.snapshot)
const disks = computed(() => (snapshot.value?.disks || []).filter(d => d.total > 1024 * 1024 * 1024).slice(0, 6))
const cpuColor = computed(() => { const p = snapshot.value?.cpu?.total || 0; if (p > 80) return '#f56c6c'; if (p > 50) return '#e6a23c'; return '#67c23a' })
const rootDisk = computed(() => (snapshot.value?.disks || []).find(d => d.mountpoint === '/') || (snapshot.value?.disks || [])[0])
const gpuAvail = computed(() => !!snapshot.value?.gpu?.available)
const gpuUtil = computed(() => snapshot.value?.gpu?.devices?.[0]?.gpu_util || 0)

async function fetchDashboard() {
  try {
    const { data } = await api.get('/dashboard/summary')
    recentFiles.value = data.recent_files || []
    topCommands.value = data.top_commands || []
  } catch (_) {}
}

// 各模块实时状态摘要（并行聚合）
async function fetchModules() {
  const base = [
    { path: '/commands', name: '命令手册', icon: 'Document', color: '#409eff', desc: '命令库与历史', status: '' },
    { path: '/files', name: '文件管理', icon: 'FolderOpened', color: '#e6a23c', desc: '目录与文件操作', status: '' },
    { path: '/ports', name: '端口监控', icon: 'Connection', color: '#67c23a', desc: '监听端口与进程', status: '' },
    { path: '/terminal', name: '终端中心', icon: 'Monitor', color: '#909399', desc: 'PTY 终端与外部终端', status: '' },
    { path: '/system', name: '系统监控', icon: 'Odometer', color: '#f56c6c', desc: 'CPU/内存/磁盘/GPU', status: '' },
    { path: '/logs', name: '日志查看', icon: 'Tickets', color: '#8e44ad', desc: '实时日志 tail', status: '' },
    { path: '/env', name: '环境管理', icon: 'Setting', color: '#2980b9', desc: 'Python/Conda 环境', status: '' },
    { path: '/ssh', name: 'SSH 管理', icon: 'Link', color: '#16a085', desc: '远程主机连接', status: '' },
    { path: '/docker', name: 'Docker 管理', icon: 'Box', color: '#0ea5e9', desc: '容器/镜像/Compose', status: '' },
  ]
  modules.value = base

  // 并行拉取状态摘要
  const tasks = [
    api.get('/commands').then(d => { modules.value[0].status = `${(d.data || []).length} 条命令` }).catch(() => {}),
    api.get('/ports').then(d => { modules.value[2].status = `${(d.data || []).length} 个端口` }).catch(() => {}),
    api.get('/env/list').then(d => { modules.value[6].status = `${(d.data || []).length} 个环境` }).catch(() => {}),
    api.get('/ssh/hosts').then(d => { modules.value[7].status = `${(d.data || []).length} 台主机` }).catch(() => {}),
    api.get('/docker/available').then(d => {
      modules.value[8].status = d.data?.available ? `✅ 可用 v${d.data.version || ''}` : '❌ 不可用'
    }).catch(() => { modules.value[8].status = '❌ 不可用' }),
  ]
  await Promise.allSettled(tasks)
  modules.value[3].status = `${terminalStore.sessions.length} 个会话`
}

async function runCommand(cmd) {
  try {
    await api.post('/terminal/create', { name: cmd.command.substring(0, 20), cwd: '~', shell: '/bin/bash', command: cmd.command })
    await api.post(`/commands/${cmd.id}/use`)
    ElMessage.success('已发送到终端')
  } catch (_) { ElMessage.error('发送失败') }
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text) } catch (_) {
    const el = document.createElement('textarea'); el.value = text
    document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el)
  }
  ElMessage.success('已复制')
}

function fmtBytes(n) {
  if (!n && n !== 0) return ''
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB'
  return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

onMounted(async () => {
  systemStore.startMonitor()
  await terminalStore.fetchSessions()
  fetchDashboard()
  fetchModules()
})
onUnmounted(() => { systemStore.stopMonitor() })
</script>

<style scoped>
.home-view { padding: 20px; }
.sys-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px; }
.sys-item { background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color-light); border-radius: 8px; padding: 14px 16px; cursor: pointer; }
.sys-item:hover { border-color: var(--el-color-primary); }
.sys-label { display: block; margin-bottom: 6px; color: var(--el-text-color-secondary); font-size: 13px; }
.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.module-card { cursor: pointer; display: flex; align-items: center; gap: 12px; }
.module-card:hover { border-color: var(--el-color-primary); transform: translateY(-1px); }
.module-info { overflow: hidden; }
.module-name { font-weight: 600; font-size: 14px; }
.module-status { font-size: 12px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.section-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.top-cmds { display: flex; flex-direction: column; gap: 6px; }
.top-cmd-item { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 4px 6px; border-radius: 4px; }
.top-cmd-item:hover { background: var(--el-fill-color-light); }
.top-cmd-item code { font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-cmd-item .op { color: var(--el-text-color-secondary); }
.terminal-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { cursor: pointer; }
.recent-list { display: flex; flex-direction: column; gap: 6px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; cursor: pointer; border-radius: 4px; color: var(--el-text-color-regular); }
.recent-item:hover { background: var(--el-fill-color-light); }
.recent-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.disk-top { display: flex; flex-direction: column; gap: 10px; }
.disk-item-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.disk-item .disk-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.disk-item .disk-size { font-size: 12px; color: var(--el-text-color-secondary); }
</style>
