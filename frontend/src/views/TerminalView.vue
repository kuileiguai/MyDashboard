<template>
  <div class="terminal-view">
    <!-- Tab bar -->
    <div class="terminal-toolbar">
      <div class="tabs-area">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['tab', { active: activeSid === s.session_id }]"
          @click="switchTab(s.session_id)"
          @dblclick="startRename(s)"
        >
          <span :class="['status-dot', s.status === 'yellow' ? 'yellow' : 'green']"></span>
          <span v-if="renamingId !== s.session_id" class="tab-name">{{ s.name }}</span>
          <el-input
            v-else
            v-model="renameValue"
            size="small"
            class="rename-input"
            @blur="finishRename(s.session_id)"
            @keyup.enter="finishRename(s.session_id)"
            @click.stop
            ref="renameRef"
          />
          <el-icon class="tab-close" @click.stop="closeTab(s.session_id)"><Close /></el-icon>
        </div>
      </div>
      <el-button size="small" type="primary" @click="createTerminal">
        <el-icon><Plus /></el-icon> 新建终端
      </el-button>
      <el-button size="small" @click="showTmux = true">
        <el-icon><Connection /></el-icon> tmux
      </el-button>
      <el-button size="small" type="warning" @click="fetchExternalTerminals">
        <el-icon><Monitor /></el-icon> 外部终端
      </el-button>
    </div>

    <!-- Terminal container -->
    <div class="terminal-area" ref="terminalContainer">
      <div v-if="!activeSid" class="terminal-empty">
        <el-empty description="点击「新建终端」开始" />
      </div>
      <div v-else v-for="s in sessions" :key="s.session_id" v-show="activeSid === s.session_id" :ref="el => setTermEl(s.session_id, el)" class="xterm-wrapper"></div>
    </div>

    <!-- tmux Dialog -->
    <el-dialog v-model="showTmux" title="tmux 会话" width="500px">
      <div v-if="tmuxInfo.running">
        <el-table :data="tmuxSessions" size="small" max-height="300">
          <el-table-column prop="name" label="会话名" />
          <el-table-column prop="windows" label="窗口数" width="80" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="attachTmux(row.name)">接管</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!tmuxSessions.length" description="无 tmux 会话" />
      </div>
      <el-empty v-else description="tmux 未运行" />
    </el-dialog>
    <!-- 外部终端 Dialog -->
    <el-dialog v-model="showExternal" title="外部终端窗口 (本机)" width="850px">
      <div style="margin-bottom:12px;display:flex;gap:12px;align-items:center">
        <el-button size="small" @click="fetchExternalTerminals" :loading="extLoading"><el-icon><Refresh /></el-icon> 刷新</el-button>
        <el-input v-model="extFilter" placeholder="搜索终端（标题/别称/PID/路径）..." clearable size="small" style="flex:1;max-width:320px"
          prefix-icon="Search" />
        <span v-if="externalTerms.length" style="white-space:nowrap;color:var(--el-text-color-secondary);font-size:12px">
          显示 {{ filteredExternalTerms.length }} / {{ externalTerms.length }} 个
        </span>
        <el-alert v-if="extError" type="warning" :closable="false" style="flex:1">
          <template #title>{{ extError }}</template>
          <el-button v-if="extDepMissing" size="small" type="primary" @click="installDeps" :loading="extInstalling" style="margin-top:4px">
            <el-icon><Download /></el-icon> 一键安装依赖
          </el-button>
        </el-alert>
      </div>
      <el-empty v-if="!extLoading && !externalTerms.length && !extError" description="未检测到外部终端窗口（需要安装 wmctrl + xdotool）" />
      <el-empty v-else-if="!extLoading && externalTerms.length && !filteredExternalTerms.length" description="无匹配的终端" />
      <div v-else class="ext-scroll">
        <div v-for="t in filteredExternalTerms" :key="t.id" class="ext-card">
        <div class="ext-card-top">
          <el-tag :type="t.children?.length ? 'warning' : 'success'" size="small" effect="dark">PID {{ t.pid }}</el-tag>
          <!-- 别名 -->
          <el-tag v-if="extAliases[t.id]" type="primary" effect="dark">{{ extAliases[t.id] }}</el-tag>
          <strong v-else>{{ t.title || t.class }}</strong>
          <span v-if="extAliases[t.id]" style="font-size:11px;color:var(--el-text-color-disabled)">({{ t.title || t.class }})</span>
          <span class="ext-alias-btn" @click="extStartAlias(t.id)" :title="extAliases[t.id] ? '修改别称' : '设置别称'">
            <el-icon :size="13"><EditPen /></el-icon>
          </span>
          <small class="ext-class">| {{ t.class }} | 桌面{{ t.desktop }}</small>
        </div>
        <!-- 别称编辑行 -->
        <div v-if="extAliasEditId === t.id" class="ext-card-info">
          <el-input v-model="extAliasText" placeholder="如：AI推理服务、前端-nginx" size="small" style="flex:1;max-width:280px"
            @keyup.enter="extSaveAlias(t.id)" @keyup.escape="extAliasEditId = null" />
          <el-button size="small" type="primary" @click="extSaveAlias(t.id)">保存</el-button>
          <el-button size="small" @click="extAliasEditId = null">取消</el-button>
        </div>
        <div class="ext-card-info">
          <span>📂 {{ t.cwd || '(无法读取)' }}</span>
          <span v-if="t.shell">🐚 {{ t.shell }}</span>
        </div>
        <div v-if="t.children?.length" class="ext-card-procs">
          <small>子进程: </small>
          <el-tag v-for="c in t.children" :key="c.pid" size="small" effect="plain" style="margin:2px">{{ c.name }}({{ c.pid }})</el-tag>
        </div>
        <div class="ext-card-actions">
          <el-button size="small" type="primary" @click="extFocus(t.id)">聚焦窗口</el-button>
          <el-button size="small" @click="extInputId = extInputId === t.id ? null : t.id; extCmdText = ''">发送命令</el-button>
          <el-button size="small" type="danger" @click="extClose(t.id)">关闭窗口</el-button>
        </div>
        <div v-if="extInputId === t.id" class="ext-send-row">
          <el-input v-model="extCmdText" placeholder="输入命令后回车..." size="small" @keyup.enter="extDoSend(t.id)" style="flex:1" />
          <el-button size="small" type="primary" @click="extDoSend(t.id)">执行</el-button>
        </div>
      </div>
      </div> <!-- ext-scroll -->
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import api from '../api'
import { sendTerminalInput, subscribeTerminal } from '../api/ws'

// State
const sessions = ref([])
const activeSid = ref(null)
const renamingId = ref(null)
const renameValue = ref('')
const renameRef = ref(null)
const terminalContainer = ref(null)

// Terminal instances
const terminals = new Map()    // sid -> Terminal
const fitAddons = new Map()   // sid -> FitAddon
const wsClients = new Map()   // sid -> unsubscribe fn

function setTermEl(sid, el) {
  if (!el) return
  // Create terminal if new
  if (!terminals.has(sid)) {
    createXtermInstance(sid, el)
  }
}

function createXtermInstance(sid, el) {
  const term = new Terminal({
    cursorBlink: true,
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
    theme: {
      background: document.documentElement.classList.contains('dark') ? '#1e1e1e' : '#ffffff',
      foreground: document.documentElement.classList.contains('dark') ? '#d4d4d4' : '#333333',
      cursor: '#528bff',
      selectionBackground: '#264f78',
    },
    allowProposedApi: true,
  })

  const fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(new WebLinksAddon())
  term.open(el)

  // Fit after render
  nextTick(() => fitAddon.fit())

  // Handle input
  const inputBuffer = { text: '', lastCommit: 0 }
  term.onData((data) => {
    sendTerminalInput(sid, data)
    // 命令捕获：累积输入，Enter 提交到历史
    for (const ch of data) {
      if (ch === '\r' || ch === '\n') {
        const cmd = inputBuffer.text.trim()
        if (cmd && cmd.length > 1 && Date.now() - inputBuffer.lastCommit > 2000) {
          try {
            api.post('/commands/history', { session_id: sid, command: cmd, cwd: '', source: 'terminal' })
          } catch (_) {}
        }
        if (cmd) inputBuffer.lastCommit = Date.now()
        inputBuffer.text = ''
      } else if (ch === '\x7f' || ch === '\b') {
        inputBuffer.text = inputBuffer.text.slice(0, -1)
      } else if (ch >= ' ' && ch !== '\x1b') {
        inputBuffer.text += ch
      }
    }
  })

  // Connect WebSocket
  const unsub = subscribeTerminal(sid, (data) => {
    if (typeof data === 'string') {
      term.write(data)
    }
  })

  terminals.set(sid, term)
  fitAddons.set(sid, fitAddon)
  wsClients.set(sid, unsub)

  // Handle resize
  term.onResize(({ cols, rows }) => {
    try {
      api.post(`/terminal/${sid}/resize`, { rows, cols })
    } catch (_) {}
  })

  // Handle window resize
  const ro = new ResizeObserver(() => {
    try { fitAddon.fit() } catch (_) {}
  })
  ro.observe(el)
}

function destroyXterm(sid) {
  const unsub = wsClients.get(sid)
  if (unsub) unsub()
  const term = terminals.get(sid)
  if (term) term.dispose()
  terminals.delete(sid)
  fitAddons.delete(sid)
  wsClients.delete(sid)
}

// Tab management
async function fetchSessions() {
  try {
    const { data } = await api.get('/terminal/list')
    sessions.value = data
  } catch (_) {}
}

async function createTerminal() {
  try {
    const { data } = await api.post('/terminal/create', {
      name: `终端 ${sessions.value.length + 1}`,
      cwd: '~',
      shell: '/bin/bash',
    })
    await fetchSessions()
    activeSid.value = data.session_id
  } catch (e) {
    ElMessage.error('创建终端失败: ' + (e.response?.data?.detail || e.message))
  }
}

function switchTab(sid) {
  activeSid.value = sid
  nextTick(() => {
    const fit = fitAddons.get(sid)
    if (fit) try { fit.fit() } catch (_) {}
  })
}

async function closeTab(sid) {
  try {
    await ElMessageBox.confirm('确认关闭此终端?', '确认', { confirmButtonText: '关闭', type: 'warning' })
    destroyXterm(sid)
    await api.delete(`/terminal/${sid}`)
    if (activeSid.value === sid) activeSid.value = null
    await fetchSessions()
  } catch (_) {}
}

function startRename(s) {
  renamingId.value = s.session_id
  renameValue.value = s.name
  nextTick(() => {
    const el = document.querySelector('.rename-input input')
    if (el) el.focus()
  })
}

async function finishRename(sid) {
  if (renameValue.value.trim()) {
    try {
      await api.put(`/terminal/${sid}/rename`, { name: renameValue.value.trim() })
      await fetchSessions()
    } catch (_) {}
  }
  renamingId.value = null
}

// ── tmux ──
const showTmux = ref(false)
const tmuxSessions = ref([])
const tmuxInfo = ref({ running: false })

async function fetchTmux() {
  try { const { data } = await api.get('/terminal/tmux/list')
    tmuxSessions.value = data.sessions || []
    tmuxInfo.value = data.info || {} } catch (_) {}
}
async function attachTmux(name) {
  try { const { data } = await api.post(`/terminal/tmux/attach?name=${encodeURIComponent(name)}`)
    await fetchSessions(); activeSid.value = data.session_id; showTmux.value = false
  } catch (_) { ElMessage.error('tmux 连接失败') }
}

// ── 外部终端 ──
const showExternal = ref(false)
const externalTerms = ref([])
const extLoading = ref(false)
const extError = ref('')
const extInputId = ref(null)
const extCmdText = ref('')
const extAliases = ref({})
const extAliasEditId = ref(null)
const extAliasText = ref('')
const extFilter = ref('')
const extDepMissing = ref(false)
const extInstalling = ref(false)

const filteredExternalTerms = computed(() => {
  if (!extFilter.value.trim()) return externalTerms.value
  const q = extFilter.value.toLowerCase()
  return externalTerms.value.filter(t => {
    const alias = (extAliases.value[t.id] || '').toLowerCase()
    const title = (t.title || '').toLowerCase()
    const cls = (t.class || '').toLowerCase()
    const cwd = (t.cwd || '').toLowerCase()
    const pid = String(t.pid)
    return alias.includes(q) || title.includes(q) || cls.includes(q) || cwd.includes(q) || pid.includes(q)
  })
})

async function fetchExternalTerminals() {
  showExternal.value = true; extLoading.value = true; extError.value = ''; extDepMissing.value = false
  try {
    const [res, aliasRes, depRes] = await Promise.all([
      api.get('/terminal/external/list'),
      api.get('/terminal/external/aliases'),
      api.get('/system/dependencies/missing'),
    ])
    extAliases.value = aliasRes.data || {}
    const terms = res.data.terminals || []
    const seen = new Set()
    externalTerms.value = terms.filter(t => { if (seen.has(t.id)) return false; seen.add(t.id); return true })
    if (!externalTerms.value.length) {
      const missing = depRes.data?.missing || []
      if (missing.length) {
        extDepMissing.value = true
        extError.value = `未检测到外部终端窗口。需要安装: ${missing.join(', ')}`
      } else {
        extError.value = '未检测到外部终端窗口。请确认已安装 wmctrl 和 xdotool'
      }
    }
  } catch (e) {
    extError.value = '检测失败: ' + (e.response?.data?.detail || e.message)
  }
  extLoading.value = false
}
async function installDeps() {
  extInstalling.value = true
  try {
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true')
    if (data.ok) { ElMessage.success(data.message); extDepMissing.value = false; await fetchExternalTerminals() }
    else ElMessage.error(data.message || '安装失败')
  } catch (e) { ElMessage.error('安装请求失败') }
  extInstalling.value = false
}
async function extFocus(winId) {
  try { await api.post(`/terminal/external/${winId}/focus`); ElMessage.success('已聚焦') } catch (_) {}
}
async function extClose(winId) {
  try {
    await ElMessageBox.confirm('确认关闭此终端窗口?', '确认', { type: 'warning' })
  } catch (_) { return }  // 用户取消
  try {
    await api.post(`/terminal/external/${winId}/close`)
    ElMessage.success('已关闭')
  } catch (e) {
    ElMessage.error('关闭失败: ' + (e.response?.data?.detail || e.message))
  }
  // 等窗口销毁后自动刷新
  await new Promise(r => setTimeout(r, 800))
  await fetchExternalTerminals()
}
async function extDoSend(winId) {
  if (!extCmdText.value.trim()) return
  const cmd = extCmdText.value.trim()
  try { await api.post(`/terminal/external/${winId}/send`, { command: cmd })
    // 记录到命令历史（外部终端来源）
    try { await api.post('/commands/history', { command: cmd, source: 'external' }) } catch (_) {}
    ElMessage.success('命令已发送'); extCmdText.value = ''; extInputId.value = null } catch (_) { ElMessage.error('发送失败') }
}
async function extSaveAlias(winId) {
  const alias = extAliasText.value.trim()
  try {
    await api.post('/terminal/external/aliases', { win_id: winId, alias })
    extAliases.value[winId] = alias || undefined
    extAliasEditId.value = null; extAliasText.value = ''
    ElMessage.success(alias ? '别名已保存' : '别名已清除')
  } catch (_) { ElMessage.error('保存失败') }
}
function extStartAlias(winId) {
  extAliasEditId.value = winId
  extAliasText.value = extAliases.value[winId] || ''
}

// Persist - reconnect on page load
onMounted(async () => {
  await fetchSessions()
  // Reconnect to existing sessions
  for (const s of sessions.value) {
    // Delay to let DOM render
    await nextTick()
  }
  if (sessions.value.length > 0 && !activeSid.value) {
    activeSid.value = sessions.value[0].session_id
  }
})

onUnmounted(() => {
  for (const [sid] of terminals) {
    destroyXterm(sid)
  }
})
</script>

<style scoped>
.terminal-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
}

.terminal-toolbar {
  display: flex;
  align-items: center;
  padding: 4px 12px;
  border-bottom: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color-overlay);
  min-height: 44px;
  gap: 8px;
}

.tabs-area {
  flex: 1;
  display: flex;
  overflow-x: auto;
  gap: 2px;
}

.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
  border: 1px solid transparent;
  color: var(--el-text-color-secondary);
  user-select: none;
  transition: all 0.15s;
}

.tab:hover { background: var(--el-fill-color-light); }
.tab.active {
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  border-color: var(--el-border-color-light);
  border-bottom-color: transparent;
}

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.green { background: #67c23a; }
.status-dot.yellow { background: #e6a23c; }

.tab-name { max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.tab-close { font-size: 12px; opacity: 0.5; }
.tab-close:hover { opacity: 1; color: #f56c6c; }

.rename-input { width: 140px; height: 24px; }

.terminal-area {
  flex: 1;
  position: relative;
  overflow: hidden;
}

.terminal-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.xterm-wrapper {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
}

/* External terminal cards */
.ext-card { border:1px solid var(--el-border-color-light); border-radius:8px; padding:10px; margin-bottom:8px }
.ext-card-top { display:flex; align-items:center; gap:8px; margin-bottom:4px }
.ext-class { color:var(--el-text-color-disabled); font-size:11px }
.ext-card-info { display:flex; gap:16px; font-size:12px; color:var(--el-text-color-secondary); margin-bottom:4px; flex-wrap:wrap }
.ext-card-procs { margin-bottom:6px }
.ext-card-actions { display:flex; gap:6px }
.ext-send-row { display:flex; gap:6px; margin-top:8px }
.ext-scroll { max-height:55vh; overflow-y:auto; padding-right:4px }
.ext-alias-btn { cursor:pointer; opacity:0.4; flex-shrink:0 }
.ext-alias-btn:hover { opacity:1; color:var(--el-color-primary) }
</style>
