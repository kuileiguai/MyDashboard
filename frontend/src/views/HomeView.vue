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
        <el-progress :percentage="rootDisk?.percent || 0" :color="rootDisk?.percent > 90 ? '#f56c6c' : '#aea79f'" :stroke-width="8" />
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

    <!-- 常用终端：备注 + 文件夹路径，一键打开外部终端 -->
    <el-card shadow="hover" class="section-card" v-loading="favLoading">
      <template #header>
        <div class="card-header">
          <span>🖥️ 常用终端 <small class="fav-tip">点击条目在本机打开一个外部终端</small></span>
          <el-button size="small" type="primary" @click="favOpenDialog()">
            <el-icon><Plus /></el-icon> 添加
          </el-button>
        </div>
      </template>
      <el-empty v-if="!favoriteTerms.length && !favLoading" description="暂无常用终端，点击「添加」配置备注与文件夹路径" :image-size="60" />
      <div v-else class="fav-list">
        <div v-for="t in favoriteTerms" :key="t.id" class="fav-item" :class="{ opening: favOpeningId === t.id }" @click="openFav(t)">
          <el-icon class="fav-icon"><Monitor /></el-icon>
          <div class="fav-info">
            <div class="fav-name">{{ t.name }}</div>
            <div class="fav-path" :title="t.path">{{ t.path }}</div>
          </div>
          <div class="fav-ops" @click.stop>
            <el-icon class="fav-op" title="编辑" @click="favOpenDialog(t)"><EditPen /></el-icon>
            <el-icon class="fav-op danger" title="删除" @click="favRemove(t)"><Delete /></el-icon>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 常用终端 编辑弹窗 -->
    <el-dialog v-model="favDialog" :title="favForm.id ? '编辑常用终端' : '添加常用终端'" width="480px">
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="备注" required>
          <el-input v-model="favForm.name" placeholder="如：MyDashboard 项目、后端日志目录" maxlength="50" @keyup.enter="favSave" />
        </el-form-item>
        <el-form-item label="文件夹路径" required>
          <el-input v-model="favForm.path" placeholder="绝对路径，如 /home/user/project 或 ~/project" @keyup.enter="favSave" />
          <div class="fav-path-hint">打开外部终端时将以此目录作为工作目录</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="favDialog = false">取消</el-button>
        <el-button type="primary" :loading="favSaving" @click="favSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 项目终端运行管理：服务编辑弹窗 -->
    <el-dialog v-model="svcDialog" :title="svcForm.id ? '编辑服务' : '新增服务'" width="560px">
      <el-form label-width="92px" @submit.prevent>
        <el-form-item label="服务名称" required>
          <el-input v-model="svcForm.name" placeholder="如：MyDashboard 后端、Redis、Nginx" maxlength="50" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="svcForm.remark" placeholder="这个服务是做什么的" maxlength="200" />
        </el-form-item>
        <el-form-item label="工作目录">
          <el-input v-model="svcForm.workdir" placeholder="启动命令执行的工作目录，如 /home/user/project 或 ~/project" />
        </el-form-item>
        <el-form-item label="启动步骤" required>
          <div class="cmd-steps">
            <div v-for="(c, i) in svcForm.commands" :key="i" class="cmd-step">
              <span class="cmd-idx">{{ i + 1 }}</span>
              <el-input v-model="svcForm.commands[i]" placeholder="一条启动命令，如 npm run dev" />
              <el-icon class="cmd-del" @click="svcForm.commands.splice(i, 1)" v-if="svcForm.commands.length > 1"><Delete /></el-icon>
            </div>
            <el-button size="small" text type="primary" @click="svcForm.commands.push('')"><el-icon><Plus /></el-icon> 添加步骤</el-button>
          </div>
          <div class="fav-path-hint">多条命令会按从上到下的顺序依次执行（同一 shell 会话内）</div>
        </el-form-item>
        <el-form-item label="占用端口">
          <div class="port-steps">
            <div v-for="(p, i) in svcForm.ports" :key="i" class="port-step">
              <el-input v-model="svcForm.ports[i]" placeholder="端口号，如 8080" />
              <el-icon class="cmd-del" @click="svcForm.ports.splice(i, 1)" v-if="svcForm.ports.length > 1"><Delete /></el-icon>
            </div>
            <el-button size="small" text type="primary" @click="svcForm.ports.push('')"><el-icon><Plus /></el-icon> 添加端口</el-button>
          </div>
          <div class="fav-path-hint">配置启动后会占用的端口，便于后续监控该服务是否正常运行</div>
        </el-form-item>
        <el-form-item label="选项">
          <el-checkbox v-model="svcForm.enabled">启用</el-checkbox>
          <el-checkbox v-model="svcForm.auto_start">开机自启</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="svcDialog = false">取消</el-button>
        <el-button type="primary" :loading="svcSaving" @click="svcSave">保存</el-button>
      </template>
    </el-dialog>


    <!-- 项目终端运行管理 -->
    <el-card shadow="hover" class="section-card" v-loading="svcLoading">
      <template #header>
        <div class="card-header">
          <span>🚀 项目终端运行管理 <small class="svc-tip">配置本机需启动的服务、启动步骤与占用端口，并实时监控是否运行</small></span>
          <el-button size="small" type="primary" @click="svcOpenDialog()">
            <el-icon><Plus /></el-icon> 新增服务
          </el-button>
        </div>
      </template>
      <el-empty v-if="!services.length && !svcLoading" description="暂无服务配置，点击「新增服务」添加需要启动的终端服务" :image-size="60" />
      <div v-else class="svc-list">
        <div v-for="s in services" :key="s.id" class="svc-item" :class="{ disabled: !s.enabled }">
          <div class="svc-head" @click="svcOpenDialog(s)">
            <div class="svc-title">
              <el-icon v-if="statusOf(s.id).running" class="svc-dot on"><SuccessFilled /></el-icon>
              <el-icon v-else class="svc-dot off"><CircleCloseFilled /></el-icon>
              <span class="svc-name">{{ s.name }}</span>
              <el-tag v-if="!s.enabled" size="small" type="info">已禁用</el-tag>
              <el-tag v-if="s.auto_start" size="small" type="warning">自启</el-tag>
            </div>
            <div class="svc-remark" v-if="s.remark">{{ s.remark }}</div>
            <div class="svc-meta">
              <span v-if="s.workdir" class="svc-meta-item" title="工作目录">
                <el-icon><FolderOpened /></el-icon>{{ s.workdir }}
              </span>
              <span class="svc-meta-item" title="启动步骤数">
                <el-icon><List /></el-icon>{{ s.commands.length }} 步
              </span>
              <span v-if="s.ports.length" class="svc-meta-item" title="占用端口">
                <el-icon><Connection /></el-icon>{{ s.ports.join(', ') }}
              </span>
            </div>
            <!-- 端口监控 -->
            <div v-if="statusOf(s.id).ports && statusOf(s.id).ports.length" class="svc-ports">
              <span v-for="p in statusOf(s.id).ports" :key="p.port" class="port-chip" :class="p.listening ? 'listening' : 'dead'">
                :{{ p.port }} {{ p.listening ? '监听中' : '未监听' }}
              </span>
            </div>
          </div>
          <div class="svc-ops">
            <el-button v-if="!statusOf(s.id).running" size="small" type="success" @click.stop="svcStart(s)">
              <el-icon><VideoPlay /></el-icon> 启动
            </el-button>
            <el-button v-else size="small" type="danger" @click.stop="svcStop(s)">
              <el-icon><VideoPause /></el-icon> 停止
            </el-button>
            <el-button size="small" @click.stop="svcOpenDialog(s)"><el-icon><EditPen /></el-icon> 编辑</el-button>
            <el-button size="small" type="danger" plain @click.stop="svcRemove(s)"><el-icon><Delete /></el-icon> 删除</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-row :gutter="16">
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSystemStore } from '../stores/system'
import api from '../api'

const systemStore = useSystemStore()
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
    { path: '/commands', name: '命令手册', icon: 'Document', color: '#e91e63', desc: '命令库与历史', status: '' },
    { path: '/files', name: '文件管理', icon: 'FolderOpened', color: '#e6a23c', desc: '目录与文件操作', status: '' },
    { path: '/ports', name: '端口监控', icon: 'Connection', color: '#67c23a', desc: '监听端口与进程', status: '' },
    { path: '/terminal', name: '终端中心', icon: 'Monitor', color: '#aea79f', desc: 'PTY 终端与外部终端', status: '' },
    { path: '/system', name: '系统监控', icon: 'Odometer', color: '#f56c6c', desc: 'CPU/内存/磁盘/GPU', status: '' },
    { path: '/logs', name: '日志查看', icon: 'Tickets', color: '#772953', desc: '实时日志 tail', status: '' },
    { path: '/env', name: '环境管理', icon: 'Setting', color: '#d97706', desc: 'Python/Conda 环境', status: '' },
    { path: '/ssh', name: 'SSH 管理', icon: 'Link', color: '#16a085', desc: '远程主机连接', status: '' },
    { path: '/docker', name: 'Docker 管理', icon: 'Box', color: '#5e2750', desc: '容器/镜像/Compose', status: '' },
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
  modules.value[3].status = `${services.value.length} 个服务`
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

// ── 常用终端（备注 + 文件夹路径，一键打开外部终端） ──
const favoriteTerms = ref([])
const favLoading = ref(false)
const favOpeningId = ref(null)
const favDialog = ref(false)
const favSaving = ref(false)
const favForm = reactive({ id: null, name: '', path: '' })

async function fetchFavorites() {
  favLoading.value = true
  try {
    const { data } = await api.get('/terminal/favorites')
    favoriteTerms.value = data || []
  } catch (_) {}
  favLoading.value = false
}

function favOpenDialog(item) {
  favForm.id = item?.id || null
  favForm.name = item?.name || ''
  favForm.path = item?.path || ''
  favDialog.value = true
}

async function favSave() {
  const name = favForm.name.trim()
  const path = favForm.path.trim()
  if (!name) { ElMessage.warning('请填写备注'); return }
  if (!path) { ElMessage.warning('请填写文件夹路径'); return }
  favSaving.value = true
  try {
    if (favForm.id) {
      await api.put(`/terminal/favorites/${favForm.id}`, { name, path })
    } else {
      await api.post('/terminal/favorites', { name, path })
    }
    ElMessage.success('已保存')
    favDialog.value = false
    await fetchFavorites()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
  favSaving.value = false
}

async function openFav(t) {
  if (favOpeningId.value) return
  favOpeningId.value = t.id
  try {
    const { data } = await api.post(`/terminal/favorites/${t.id}/open`)
    ElMessage.success(`已在 ${data.terminal} 中打开：${t.path}`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '打开失败')
  }
  favOpeningId.value = null
}

async function favRemove(t) {
  try { await ElMessageBox.confirm(`删除常用终端「${t.name}」?`, '确认', { type: 'warning' }) } catch (_) { return }
  try {
    await api.delete(`/terminal/favorites/${t.id}`)
    ElMessage.success('已删除')
    await fetchFavorites()
  } catch (_) { ElMessage.error('删除失败') }
}

// ── 项目终端运行管理 ──
const services = ref([])
const svcLoading = ref(false)
const svcStatuses = ref({})  // { [id]: {running, ports, process_alive, pid} }
let svcTimer = null

async function fetchServices() {
  svcLoading.value = true
  try {
    const { data } = await api.get('/terminal/services')
    services.value = data || []
    await fetchStatuses()
  } catch (_) {}
  svcLoading.value = false
}

async function fetchStatuses() {
  try {
    const { data } = await api.get('/terminal/services/status/all')
    const map = {}
    for (const s of data || []) map[s.id] = s
    svcStatuses.value = map
  } catch (_) {}
}

function statusOf(id) {
  return svcStatuses.value[id] || { running: false, ports: [], process_alive: false, pid: null }
}

// 编辑/新增弹窗
const svcDialog = ref(false)
const svcSaving = ref(false)
const svcForm = reactive({
  id: null,
  name: '',
  remark: '',
  workdir: '',
  commands: [''],
  ports: [''],
  auto_start: false,
  enabled: true,
})

function svcOpenDialog(item) {
  svcForm.id = item?.id || null
  svcForm.name = item?.name || ''
  svcForm.remark = item?.remark || ''
  svcForm.workdir = item?.workdir || ''
  svcForm.commands = item ? [...item.commands, ''] : ['']
  svcForm.ports = item ? item.ports.map(String).concat(['']) : ['']
  svcForm.auto_start = item ? !!item.auto_start : false
  svcForm.enabled = item ? !!item.enabled : true
  svcDialog.value = true
}

async function svcSave() {
  const name = svcForm.name.trim()
  if (!name) { ElMessage.warning('请填写服务名称'); return }
  const commands = svcForm.commands.map(c => c.trim()).filter(Boolean)
  if (!commands.length) { ElMessage.warning('请至少配置一条启动命令步骤'); return }
  const ports = svcForm.ports.map(p => String(p).trim()).filter(Boolean).map(Number).filter(n => !isNaN(n))
  svcSaving.value = true
  try {
    const payload = {
      name, remark: svcForm.remark.trim(), workdir: svcForm.workdir.trim(),
      commands, ports, auto_start: svcForm.auto_start, enabled: svcForm.enabled,
    }
    if (svcForm.id) {
      await api.put(`/terminal/services/${svcForm.id}`, payload)
    } else {
      await api.post('/terminal/services', payload)
    }
    ElMessage.success('已保存')
    svcDialog.value = false
    await fetchServices()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
  svcSaving.value = false
}

async function svcStart(s) {
  try {
    await api.post(`/terminal/services/${s.id}/start`)
    ElMessage.success(`服务「${s.name}」已启动`)
    await fetchStatuses()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '启动失败')
  }
}

async function svcStop(s) {
  try {
    await api.post(`/terminal/services/${s.id}/stop`)
    ElMessage.success(`服务「${s.name}」已停止`)
    await fetchStatuses()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '停止失败')
  }
}

async function svcRemove(s) {
  try { await ElMessageBox.confirm(`删除服务「${s.name}」?`, '确认', { type: 'warning' }) } catch (_) { return }
  try {
    await api.delete(`/terminal/services/${s.id}`)
    ElMessage.success('已删除')
    await fetchServices()
  } catch (_) { ElMessage.error('删除失败') }
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
  fetchDashboard()
  fetchFavorites()
  await fetchServices()
  fetchModules()
  svcTimer = setInterval(fetchStatuses, 5000)
})
onUnmounted(() => {
  systemStore.stopMonitor()
  if (svcTimer) clearInterval(svcTimer)
})
</script>

<style scoped>
.home-view { padding: 20px; }
.sys-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px; }
.sys-item {
  background: var(--el-bg-color);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s ease, transform 0.2s ease;
}
.sys-item:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.sys-label { display: block; margin-bottom: 6px; color: var(--el-text-color-secondary); font-size: 13px; }
.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.module-card { cursor: pointer; display: flex; align-items: center; gap: 12px; }
.module-card:hover { transform: translateY(-2px); }
.module-icon { flex-shrink: 0; }
.module-info { overflow: hidden; }
.module-name { font-weight: 600; font-size: 14px; }
.module-status { font-size: 12px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.section-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.top-cmds { display: flex; flex-direction: column; gap: 6px; }
.top-cmd-item { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 4px 6px; border-radius: var(--radius-sm); }
.top-cmd-item:hover { background: var(--el-fill-color-light); }
.top-cmd-item code { font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-cmd-item .op { color: var(--el-text-color-secondary); }
.terminal-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { cursor: pointer; }
.recent-list { display: flex; flex-direction: column; gap: 6px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; cursor: pointer; border-radius: var(--radius-sm); color: var(--el-text-color-regular); }
.recent-item:hover { background: var(--el-fill-color-light); }
.recent-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.disk-top { display: flex; flex-direction: column; gap: 10px; }
.disk-item-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.disk-item .disk-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.disk-item .disk-size { font-size: 12px; color: var(--el-text-color-secondary); }

/* 常用终端 */
.fav-tip { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; margin-left: 6px; }
.fav-list { display: flex; flex-wrap: wrap; gap: 10px; }
.fav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; min-width: 220px; max-width: 100%;
  background: var(--el-bg-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  cursor: pointer; transition: all 0.2s;
}
.fav-item:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.fav-item.opening { opacity: 0.6; pointer-events: none; }
.fav-icon { color: var(--el-color-primary); font-size: 18px; flex-shrink: 0; }
.fav-info { flex: 1; min-width: 0; }
.fav-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fav-path { font-size: 12px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fav-ops { display: none; gap: 6px; flex-shrink: 0; }
.fav-item:hover .fav-ops { display: flex; }
.fav-op { cursor: pointer; color: var(--el-text-color-secondary); }
.fav-op:hover { color: var(--el-color-primary); }
.fav-op.danger:hover { color: #f56c6c; }
.fav-path-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.4; margin-top: 4px; }

/* 项目终端运行管理 */
.svc-tip { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; margin-left: 6px; }
.svc-list { display: flex; flex-direction: column; gap: 12px; }
.svc-item {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  padding: 14px 16px;
  background: var(--el-bg-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  transition: all 0.2s;
}
.svc-item:hover { box-shadow: var(--shadow-md); }
.svc-item.disabled { opacity: 0.6; }
.svc-head { flex: 1; min-width: 0; cursor: pointer; }
.svc-title { display: flex; align-items: center; gap: 8px; }
.svc-dot { font-size: 16px; }
.svc-dot.on { color: #67c23a; }
.svc-dot.off { color: #c0c4cc; }
.svc-name { font-weight: 600; font-size: 14px; }
.svc-remark { font-size: 12px; color: var(--el-text-color-secondary); margin: 4px 0 0 24px; }
.svc-meta { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 0 24px; font-size: 12px; color: var(--el-text-color-secondary); }
.svc-meta-item { display: inline-flex; align-items: center; gap: 4px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.svc-ports { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 0 24px; }
.port-chip { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.port-chip.listening { background: rgba(103,194,58,0.15); color: #67c23a; }
.port-chip.dead { background: rgba(245,108,108,0.12); color: #f56c6c; }
.svc-ops { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; align-items: stretch; }
.svc-ops .el-button { margin-left: 0; }

/* 弹窗步骤 */
.cmd-steps, .port-steps { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.cmd-step, .port-step { display: flex; align-items: center; gap: 8px; }
.cmd-idx { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary); color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; }
.cmd-del { color: var(--el-text-color-secondary); cursor: pointer; flex-shrink: 0; }
.cmd-del:hover { color: #f56c6c; }
</style>
