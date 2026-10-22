<template>
  <div class="home-view">
    <!-- 果冻环境光：让半透明胶质底与 backdrop-filter 有内容可折射 -->
    <div class="jelly-ambient" aria-hidden="true"></div>
    <header class="deck-welcome">
      <div class="deck-welcome-copy">
        <span class="deck-kicker">DECKPIT · DEVELOPER WORKSPACE</span>
        <h1>你的开发甲板，准备就绪。</h1>
        <p>服务、终端与系统状态，一眼掌握。</p>
      </div>
      <img class="deck-mascot" :src="deckpitLogo" alt="Deckpit 小船长" />
      <span class="deck-welcome-orbit" aria-hidden="true"></span>
    </header>

    <!-- 系统状态：四项合一，整卡可点跳转系统监控 -->
    <el-card shadow="hover" class="section-card jelly sys-panel" @click="$router.push('/system')">
      <template #header>
        <div class="card-header">
          <span>📊 系统状态 <small class="sys-tip">实时采样 · 2s 刷新</small></span>
          <el-button size="small" text type="primary" @click.stop="$router.push('/system')">系统监控 →</el-button>
        </div>
      </template>

      <div class="gauge-row">
        <RingGauge :percent="snapshot.cpu?.total || 0" :color="cpuColor" label="CPU" :detail="cpuDetail" />
        <RingGauge :percent="snapshot.memory?.percent || 0" color="#e6a23c" label="内存" :detail="memDetail" />
        <RingGauge v-if="gpuAvail" :percent="gpuUtil" color="#67c23a" label="GPU" :detail="gpuDetail" />
        <RingGauge :percent="rootDisk?.percent || 0" :color="diskColor" :label="diskLabel" :detail="diskDetail" />
        <RingGauge v-if="swapTotal" :percent="snapshot.swap?.percent || 0" color="#aea79f" label="Swap" :detail="swapDetail" />
      </div>

      <!-- 补充指标条：原来四个横条装不下的信息 -->
      <div class="sys-metrics">
        <span class="metric" title="1 / 5 / 15 分钟平均负载"><i>负载</i>{{ loadText }}</span>
        <span class="metric" title="可用内存"><i>可用内存</i>{{ memAvailableText }}</span>
        <span class="metric" title="网络上行速率"><i>↑ 上传</i>{{ netUpText }}</span>
        <span class="metric" title="网络下行速率"><i>↓ 下载</i>{{ netDownText }}</span>
        <span class="metric" title="已配置服务的运行状态"><i>服务</i>{{ svcRunningText }}</span>
        <span v-if="gpuTemp" class="metric" title="GPU 温度"><i>GPU 温度</i>{{ gpuTemp }}°C</span>
        <span class="metric" title="物理分区数"><i>分区</i>{{ diskCountText }}</span>
      </div>
    </el-card>

    <!-- 模块快捷入口 -->
    <div class="module-grid">
      <el-card v-for="m in modules" :key="m.path" shadow="hover" class="module-card jelly" @click="$router.push(m.path)">
        <el-icon :size="24" :color="m.color"><component :is="m.icon" /></el-icon>
        <div class="module-info">
          <div class="module-name">{{ m.name }}</div>
          <div class="module-status">{{ m.status || m.desc }}</div>
        </div>
      </el-card>
    </div>

    <!-- 常用命令：点击直接发送到终端 -->
    <el-card shadow="hover" class="section-card jelly" v-if="topCommands.length">
      <template #header>
        <div class="card-header">
          <span>⚡ 常用命令 <small class="fav-tip">点击直接发送到终端执行</small></span>
          <el-button size="small" text type="primary" @click="$router.push('/commands')">命令手册 →</el-button>
        </div>
      </template>
      <div class="top-cmds">
        <div v-for="c in topCommands" :key="c.id" class="top-cmd-item" @click="runCommand(c)" :title="c.command">
          <el-icon><CaretRight /></el-icon>
          <code>{{ c.command }}</code>
          <span class="op">{{ c.use_count || 0 }} 次</span>
        </div>
      </div>
    </el-card>

    <!-- 常用终端：备注 + 文件夹路径，一键打开外部终端 -->
    <el-card shadow="hover" class="section-card jelly" v-loading="favLoading">
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
        <div v-for="t in favoriteTerms" :key="t.id" class="fav-item jelly" :class="{ opening: favOpeningId === t.id }" @click="openFav(t)">
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
    <el-card shadow="hover" class="section-card jelly" v-loading="svcLoading">
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
        <div v-for="s in services" :key="s.id" class="svc-item jelly" :class="{ disabled: !s.enabled }">
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
            <el-button size="small" @click.stop="askAiService(s)">
              <el-icon><ChatDotRound /></el-icon> 问 AI
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
        <el-card shadow="hover" class="section-card jelly">
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
  
      <!-- SSH 连接机器：点击直接连，跳终端中心 -->
      <el-col :xs="24" :md="12">
        <el-card shadow="hover" class="section-card jelly">
          <template #header>
            <div class="card-header">
              <span>🔗 SSH 主机</span>
              <el-button size="small" text type="primary" @click="$router.push('/ssh')">SSH 管理 →</el-button>
            </div>
          </template>
          <el-empty v-if="!sshHosts.length" description="还没有保存主机">
            <el-button size="small" type="primary" @click="$router.push('/ssh')">去添加</el-button>
          </el-empty>
          <div v-else class="ssh-list">
            <div v-for="h in sshHosts" :key="h.id" class="ssh-item" @click="connectSsh(h)"
                 :title="`${h.username ? h.username + '@' : ''}${h.host}:${h.port} · ${sshStatusText(h)} — 点击连接`">
              <span class="ssh-dot" :class="{ online: h.status === 'online', warn: h.status === 'ping_only' }"></span>
              <div class="ssh-main">
                <span class="ssh-name">{{ h.name }}</span>
                <span class="ssh-addr">{{ h.username ? h.username + '@' : '' }}{{ h.host }}:{{ h.port }}</span>
              </div>
              <el-tag size="small" :type="h.has_password ? 'warning' : 'info'">
                {{ h.has_password ? '密码' : (h.key_path ? '私钥' : '默认') }}
              </el-tag>
              <el-icon class="ssh-go"><Connection /></el-icon>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import deckpitLogo from '../assets/deckpit-logo.png'
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSystemStore } from '../stores/system'
import { useAiStore } from '../stores/ai'
import { useAiContext } from '../stores/aiContext'
import api from '../api'
import RingGauge from '../components/RingGauge.vue'

const systemStore = useSystemStore()
const ai = useAiStore()
const aiContext = useAiContext()
const router = useRouter()
const recentFiles = ref([])
const topCommands = ref([])
const modules = ref([])

const snapshot = computed(() => systemStore.snapshot)
const disks = computed(() => (snapshot.value?.disks || []).filter(d => d.total > 1024 * 1024 * 1024).slice(0, 6))
const cpuColor = computed(() => { const p = snapshot.value?.cpu?.total || 0; if (p > 80) return '#f56c6c'; if (p > 50) return '#e6a23c'; return '#67c23a' })
const rootDisk = computed(() => (snapshot.value?.disks || []).find(d => d.mountpoint === '/') || (snapshot.value?.disks || [])[0])
const gpuAvail = computed(() => !!snapshot.value?.gpu?.available)
const gpuUtil = computed(() => snapshot.value?.gpu?.devices?.[0]?.gpu_util || 0)
const gpuTemp = computed(() => snapshot.value?.gpu?.devices?.[0]?.temperature || 0)

// ── 环形仪表文案 ──
const cpuDetail = computed(() => {
  const c = snapshot.value?.cpu
  if (!c) return '—'
  const load = snapshot.value?.load?.load1
  return `${c.count || '-'} 核${load != null ? ` · 负载 ${load}` : ''}`
})
const memDetail = computed(() => {
  const m = snapshot.value?.memory
  return m ? `${fmtBytes(m.used)} / ${fmtBytes(m.total)}` : '—'
})
const gpuDetail = computed(() => {
  const g = snapshot.value?.gpu?.devices?.[0]
  return g ? `${fmtBytes(g.memory_used)} / ${fmtBytes(g.memory_total)}` : '—'
})
const diskLabel = computed(() => `磁盘 ${rootDisk.value?.mountpoint || ''}`.trim())
const diskDetail = computed(() => {
  const d = rootDisk.value
  return d ? `${fmtBytes(d.used)} / ${fmtBytes(d.total)}` : '—'
})
const diskColor = computed(() => {
  const p = rootDisk.value?.percent || 0
  return p > 90 ? '#f56c6c' : p > 70 ? '#e6a23c' : '#aea79f'
})
const swapTotal = computed(() => snapshot.value?.swap?.total || 0)
const swapDetail = computed(() => {
  const s = snapshot.value?.swap
  return s ? `${fmtBytes(s.used)} / ${fmtBytes(s.total)}` : '—'
})

// ── 补充指标条 ──
const loadText = computed(() => {
  const l = snapshot.value?.load
  return l ? `${l.load1} / ${l.load5} / ${l.load15}` : '—'
})
const memAvailableText = computed(() => fmtBytes(snapshot.value?.memory?.available) || '—')
const diskCountText = computed(() => {
  const n = disks.value.length
  return n ? `${n} 个` : '—'
})

// 网络速率：用最近两次采样做差分
const netRate = computed(() => {
  const h = systemStore.history
  if (!h || h.length < 2) return null
  const a = h[h.length - 2]
  const b = h[h.length - 1]
  const dt = (b?.ts || 0) - (a?.ts || 0)
  if (dt <= 0) return null
  const up = ((b?.network?.bytes_sent || 0) - (a?.network?.bytes_sent || 0)) / dt
  const down = ((b?.network?.bytes_recv || 0) - (a?.network?.bytes_recv || 0)) / dt
  return { up: Math.max(0, up), down: Math.max(0, down) }
})
const netUpText = computed(() => (netRate.value ? fmtSpeed(netRate.value.up) : '—'))
const netDownText = computed(() => (netRate.value ? fmtSpeed(netRate.value.down) : '—'))

const svcRunningText = computed(() => {
  const total = services.value.length
  if (!total) return '—'
  const running = services.value.filter(s => statusOf(s.id).running).length
  return `${running} / ${total} 运行中`
})

function fmtSpeed(bytesPerSec) {
  if (!bytesPerSec) return '0 KB/s'
  if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
  if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`
  return `${(bytesPerSec / 1024 / 1024).toFixed(1)} MB/s`
}

async function fetchDashboard() {
  try {
    const { data } = await api.get('/dashboard/summary')
    recentFiles.value = data.recent_files || []
    topCommands.value = data.top_commands || []
  } catch (_) {}
}

// ── SSH 主机：列表 + 一键连接 ──
const sshHosts = ref([])

async function fetchSshHosts() {
  try {
    const { data } = await api.get('/ssh/hosts')
    sshHosts.value = data || []
  } catch (_) {}
}

function sshStatusText(h) {
  return { online: '在线', ping_only: '主机可达，端口未开', offline: '离线' }[h.status] || '未知'
}

async function connectSsh(h) {
  try {
    await api.post(`/ssh/hosts/${h.id}/connect`)
    ElMessage.success(`已连接 ${h.name}`)
    router.push('/terminal')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '连接失败')
  }
}

// 各模块实时状态摘要（并行聚合）
async function fetchModules() {
  const base = [
    { path: '/commands', name: '命令手册', icon: 'Document', color: '#d96b1e', desc: '命令库与历史', status: '' },
    { path: '/files', name: '文件管理', icon: 'FolderOpened', color: '#e6a23c', desc: '目录与文件操作', status: '' },
    { path: '/ports', name: '端口监控', icon: 'Connection', color: '#67c23a', desc: '监听端口与进程', status: '' },
    { path: '/terminal', name: '终端中心', icon: 'Monitor', color: '#aea79f', desc: 'PTY 终端与外部终端', status: '' },
    { path: '/system', name: '系统监控', icon: 'Odometer', color: '#f56c6c', desc: 'CPU/内存/磁盘/GPU', status: '' },
    { path: '/logs', name: '日志查看', icon: 'Tickets', color: '#15243a', desc: '实时日志 tail', status: '' },
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

function askAiService(s) {
  aiContext.setTarget('service', s.id, s.name)
  ai.open = true
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
  fetchSshHosts()
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
.home-view { padding: 28px clamp(18px, 3vw, 42px) 40px; max-width: 1640px; margin: 0 auto; }
.deck-welcome {
  min-height: 178px; margin-bottom: 22px; padding: 28px 34px; position: relative; overflow: hidden;
  display: flex; align-items: center; justify-content: space-between;
  color: #fff8eb; background: var(--deck-navy); border-radius: var(--radius-xl);
  box-shadow: 0 12px 28px rgba(13, 23, 40, .16); isolation: isolate;
  animation: deck-arrive .55s cubic-bezier(.2,.8,.2,1) both;
}
.deck-welcome::before {
  content: ''; position: absolute; inset: auto -3% -72% 32%; height: 220px; border-radius: 50%;
  background: var(--deck-wood); opacity: .32; transform: rotate(-5deg); z-index: -1;
}
.deck-welcome-copy { z-index: 1; }
.deck-kicker { display: block; margin-bottom: 12px; color: #f3b65f; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.deck-welcome h1 { margin: 0; font-size: clamp(25px, 3vw, 36px); line-height: 1.15; letter-spacing: -.6px; color: #fffaf2; }
.deck-welcome p { margin: 10px 0 0; color: #c7d0db; font-size: 14px; }
.deck-mascot { width: 154px; height: 154px; object-fit: contain; z-index: 1; filter: drop-shadow(0 8px 12px rgba(0,0,0,.2)); animation: mascot-float 5s ease-in-out infinite; }
.deck-welcome-orbit { position: absolute; width: 280px; height: 280px; right: 6%; top: -125px; border: 1px solid rgba(255,255,255,.12); border-radius: 50%; z-index: -1; }
.sys-panel { cursor: pointer; }
.gauge-row {
  display: flex; flex-wrap: wrap; justify-content: space-around;
  gap: 20px 14px; padding: 6px 0 2px;
}
.sys-metrics {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-top: 18px; padding-top: 14px;
  border-top: 1px dashed rgba(21, 36, 58, 0.12);
}
.metric {
  display: inline-flex; align-items: baseline; gap: 6px;
  padding: 5px 11px; border-radius: var(--radius-pill);
  background: rgba(21, 36, 58, 0.04);
  font-size: 12px; color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
}
.metric i { font-style: normal; font-size: 11px; color: var(--el-text-color-secondary); }
.sys-tip { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; margin-left: 6px; }
html.dark .metric { background: rgba(255, 255, 255, 0.06); }
html.dark .sys-metrics { border-top-color: rgba(255, 255, 255, 0.1); }
.module-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; margin-bottom: 20px; }
.module-card { cursor: pointer; display: flex; align-items: center; gap: 12px; }
.module-icon { flex-shrink: 0; }
.module-info { overflow: hidden; }
.module-name { font-weight: 600; font-size: 14px; }
.module-status { font-size: 12px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.section-card { margin-bottom: 18px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.top-cmds { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 8px; }
.top-cmd-item {
  display: flex; align-items: center; gap: 8px;
  cursor: pointer; padding: 9px 12px; border-radius: var(--radius-md);
  background: rgba(21, 36, 58, 0.03);
  transition:
    transform 0.3s var(--jelly-squish),
    background-color 0.2s ease,
    box-shadow 0.2s ease;
}
.top-cmd-item:hover { background: var(--el-fill-color-light); transform: translateY(-2px); box-shadow: var(--shadow-sm); }
.top-cmd-item:active { transform: translateY(0) scale(0.985); }
.top-cmd-item code { font-size: 13px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-cmd-item .op { color: var(--el-text-color-secondary); font-size: 11px; flex-shrink: 0; }
html.dark .top-cmd-item { background: rgba(255, 255, 255, 0.05); }
.terminal-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { cursor: pointer; }
.recent-list { display: flex; flex-direction: column; gap: 6px; }
.recent-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; cursor: pointer; border-radius: var(--radius-sm); color: var(--el-text-color-regular); }
.recent-item:hover { background: var(--el-fill-color-light); }
.recent-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ssh-list { display: flex; flex-direction: column; gap: 8px; }
.ssh-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: var(--radius-md);
  background: rgba(21, 36, 58, 0.03); cursor: pointer;
  transition:
    transform 0.3s var(--jelly-squish),
    background-color 0.2s ease,
    box-shadow 0.2s ease;
}
.ssh-item:hover { background: var(--el-fill-color-light); transform: translateY(-2px); box-shadow: var(--shadow-sm); }
.ssh-item:active { transform: translateY(0) scale(0.985); }
.ssh-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--el-color-danger); flex-shrink: 0; }
.ssh-dot.online { background: var(--el-color-success); box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.16); }
.ssh-dot.warn { background: var(--el-color-warning); box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.16); }
.ssh-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ssh-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ssh-addr { font-size: 11px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ssh-go { color: var(--el-text-color-placeholder); flex-shrink: 0; }
html.dark .ssh-item { background: rgba(255, 255, 255, 0.05); }

/* 常用终端 */
.fav-tip { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; margin-left: 6px; }
.fav-list { display: flex; flex-wrap: wrap; gap: 10px; }
.fav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; min-width: 220px; max-width: 100%;
  cursor: pointer;
}
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
}
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

@keyframes deck-arrive { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

/* ================================================================
   果冻（Jelly / Soft-3D）试点层 —— 仅作用于首页
   体积感 = 顶部内高光 + 底部内胶影 + 半透明胶质底 + 双层外投影
   果冻感 = 回弹缓动 var(--jelly-squish) + 按下回弹
   ================================================================ */
.home-view { position: relative; }
.jelly-ambient {
  position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(46% 26% at 8% 0%, rgba(232, 121, 36, 0.22), transparent 68%),
    radial-gradient(38% 24% at 94% 4%, rgba(94, 39, 80, 0.13), transparent 70%),
    radial-gradient(50% 30% at 72% 98%, rgba(22, 160, 133, 0.14), transparent 72%);
}
html.dark .jelly-ambient {
  background:
    radial-gradient(46% 26% at 8% 0%, rgba(240, 154, 69, 0.18), transparent 68%),
    radial-gradient(38% 24% at 94% 4%, rgba(120, 60, 140, 0.16), transparent 70%),
    radial-gradient(50% 30% at 72% 98%, rgba(22, 160, 133, 0.12), transparent 72%);
}

/* 胶质基座 */
.home-view .jelly {
  position: relative;
  background-color: var(--jelly-glass);
  background-image: var(--jelly-sheen);
  border: 1px solid var(--jelly-edge);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(18px) saturate(1.4);
  -webkit-backdrop-filter: blur(18px) saturate(1.4);
  box-shadow: var(--jelly-shadow);
  transition:
    transform 0.42s var(--jelly-squish),
    box-shadow 0.28s ease,
    background-color 0.28s ease;
}
/* WebView 不支持 backdrop-filter 时加厚胶质底，保证可读性 */
@supports not ((backdrop-filter: blur(2px)) or (-webkit-backdrop-filter: blur(2px))) {
  .home-view .jelly { background-color: var(--jelly-glass-strong); }
}

/* 模块快捷入口（module-card）：明显悬浮 + 颜色呼应 */
.home-view .module-card.jelly { border-radius: var(--radius-xl); }
.home-view .el-card.module-card.jelly:hover {
  transform: translateY(-8px) scale(1.04);
  box-shadow: var(--jelly-shadow-lift);
}
.home-view .el-card.module-card.jelly:active {
  transform: translateY(-2px) scale(0.99);
  box-shadow: var(--jelly-shadow-press);
  transition-duration: 0.1s;
}
.home-view .module-card.jelly:hover .module-name { color: var(--el-color-primary); }

/* 分区大卡（section-card）：体积感保留，位移收敛，避免阅读抖动 */
.home-view .section-card.jelly { border-radius: var(--radius-xl); }
.home-view .el-card.section-card.jelly:hover {
  transform: translateY(-3px);
  box-shadow: var(--jelly-shadow-lift);
}

/* 内层小卡（fav-item / svc-item）：不用 blur，改用更实的胶质底，控制重绘成本 */
.home-view .fav-item.jelly,
.home-view .svc-item.jelly {
  border-radius: var(--radius-lg);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  background-color: var(--jelly-glass-strong);
}
.home-view .fav-item.jelly:hover,
.home-view .svc-item.jelly:hover {
  transform: translateY(-4px) scale(1.015);
  box-shadow: var(--jelly-shadow-lift);
}
.home-view .fav-item.jelly:active,
.home-view .svc-item.jelly:active {
  transform: translateY(-1px) scale(0.985);
  box-shadow: var(--jelly-shadow-press);
  transition-duration: 0.1s;
}

/* 欢迎区：深色果冻（顶部高光、底部沉影） */
.home-view .deck-welcome {
  border: 1px solid rgba(255, 255, 255, 0.14);
  background-image: linear-gradient(155deg,
      rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0.02) 42%, transparent 62%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    inset 0 -26px 34px -26px rgba(0, 0, 0, 0.55),
    0 10px 20px -8px rgba(13, 23, 40, 0.26),
    0 30px 48px -16px rgba(13, 23, 40, 0.34);
  transition: transform 0.5s var(--jelly-squish), box-shadow 0.3s ease;
}
.home-view .deck-welcome:hover { transform: translateY(-4px); }

/* 进度条：胶质轨道 + 内高光（按需作用于 el-progress 子节点） */
.home-view :deep(.el-progress-bar__outer) {
  background: var(--el-fill-color);
  box-shadow:
    inset 0 2px 3px rgba(21, 36, 58, 0.14),
    inset 0 -1px 0 rgba(255, 255, 255, 0.55);
}
.home-view :deep(.el-progress-bar__inner) {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
}
html.dark .home-view :deep(.el-progress-bar__outer) {
  box-shadow:
    inset 0 2px 4px rgba(0, 0, 0, 0.45),
    inset 0 -1px 0 rgba(255, 255, 255, 0.06);
}

/* 按钮：果冻回弹 + 顶部高光带 */
.home-view .el-button {
  transition:
    transform 0.3s var(--jelly-squish),
    box-shadow 0.22s ease,
    background-color 0.18s ease;
}
.home-view .el-button--primary {
  background-image: linear-gradient(180deg,
      rgba(255, 255, 255, 0.3), rgba(255, 255, 255, 0) 52%, rgba(0, 0, 0, 0.07));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),
    inset 0 -2px 4px rgba(0, 0, 0, 0.12),
    0 4px 10px rgba(217, 107, 30, 0.26);
}
.home-view .el-button--primary:hover {
  transform: translateY(-2px) scale(1.04);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.6),
    0 8px 18px rgba(217, 107, 30, 0.32);
}
.home-view .el-button:active {
  transform: translateY(1px) scale(0.95);
  transition-duration: 0.1s;
}

/* 无障碍：尊重系统的「减少动态效果」偏好 */
@media (prefers-reduced-motion: reduce) {
  .home-view .jelly,
  .home-view .deck-welcome,
  .home-view .el-button { transform: none !important; }
}
@keyframes mascot-float { 0%, 100% { transform: translateY(0) rotate(-1deg); } 50% { transform: translateY(-5px) rotate(1deg); } }
@media (prefers-reduced-motion: reduce) {
  .deck-welcome, .deck-mascot { animation: none; }
}
@media (max-width: 640px) {
  .home-view { padding: 16px 14px 28px; }
  .deck-welcome { min-height: 148px; padding: 22px 20px; }
  .deck-mascot { width: 104px; height: 104px; margin-right: -8px; }
  .deck-welcome h1 { max-width: 250px; }
}
</style>
