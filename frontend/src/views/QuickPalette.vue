<template>
  <div class="palette">
    <div class="drag-bar drag-region" title="拖动此条移动窗口"></div>
    <div class="palette-head">
      <el-input
        ref="searchRef"
        v-model="query"
        :placeholder="searchPlaceholder"
        size="large"
        clearable
        @input="refresh"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="runSelected"
        @keydown.esc="onEsc"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-radio-group v-model="mode" size="small" @change="onModeChange">
        <el-radio-button value="cmd">命令</el-radio-button>
        <el-radio-button value="files">文件夹</el-radio-button>
        <el-radio-button value="ports">端口</el-radio-button>
        <el-radio-button value="terms">终端</el-radio-button>
      </el-radio-group>
      <span class="head-ops">
        <el-icon class="head-op" title="刷新当前数据" @click="refreshAll"><Refresh /></el-icon>
        <el-icon class="head-op" title="最小化" @click="minimize"><Minus /></el-icon>
        <el-icon class="head-op" :class="{ on: pinned }" :title="pinned ? '取消固定（恢复跟随）' : '固定窗口（不跟随）'" @click="togglePin">
          <Position v-if="!pinned" /><Lock v-else />
        </el-icon>
      </span>
    </div>

    <div class="palette-body">
      <!-- 命令模式：分类 / 服务 / 场景 三级筛选 -->
      <template v-if="mode === 'cmd'">
        <div class="filter-bar">
          <el-select v-model="cmdCategory" size="small" clearable placeholder="分类" class="f-sel"
                     @change="refresh" @clear="refresh">
            <el-option v-for="c in cmdFacets.categories" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="cmdService" size="small" clearable placeholder="服务" class="f-sel"
                     @change="refresh" @clear="refresh">
            <el-option v-for="s in cmdFacets.services" :key="s" :label="s" :value="s" />
          </el-select>
          <el-select v-model="cmdScenario" size="small" clearable placeholder="场景" class="f-sel"
                     @change="refresh" @clear="refresh">
            <el-option v-for="s in cmdFacets.scenarios" :key="s" :label="s" :value="s" />
          </el-select>
          <el-button v-if="hasCmdFilter" size="small" text type="primary" @click="clearCmdFilters">清除</el-button>
          <span class="filter-count">{{ filtered.length }} 条</span>
        </div>
        <template v-if="historyItems.length">
          <div class="group-title">终端历史</div>
          <div
            v-for="(item, i) in historyItems"
            :key="'h' + item.id"
            class="palette-item"
            :class="{ active: i === activeIndex }"
            @mouseenter="activeIndex = i"
            @click="run(item)"
          >
            <span class="cmd" :title="item.command">{{ item.command }}</span>
            <span class="desc" v-if="item.description">{{ item.description }}</span>
            <span class="meta" v-if="itemMeta(item)" :title="itemMeta(item)">{{ itemMeta(item) }}</span>
            <el-tag size="small" :type="sourceType(item.source)" class="src-tag">{{ sourceLabel(item.source) }}</el-tag>
            <span class="ops" @click.stop>
              <el-icon class="op" :class="{ on: item.is_favorite }" @click="toggleFav(item)">
                <StarFilled v-if="item.is_favorite" /><Star v-else />
              </el-icon>
              <el-icon class="op" @click="copy(item.command)"><CopyDocument /></el-icon>
            </span>
          </div>
        </template>
        <template v-if="manualItems.length">
          <div class="group-title">命令手册</div>
          <div
            v-for="(item, i) in manualItems"
            :key="'m' + item.id"
            class="palette-item"
            :class="{ active: i + historyItems.length === activeIndex }"
            @mouseenter="activeIndex = i + historyItems.length"
            @click="run(item)"
          >
            <span class="cmd" :title="item.command">{{ item.command }}</span>
            <span class="desc" v-if="item.description">{{ item.description }}</span>
            <span class="meta" v-if="itemMeta(item)" :title="itemMeta(item)">{{ itemMeta(item) }}</span>
            <el-tag size="small" :type="sourceType(item.source)" class="src-tag">{{ sourceLabel(item.source) }}</el-tag>
            <span class="ops" @click.stop>
              <el-icon class="op" :class="{ on: item.is_favorite }" @click="toggleFav(item)">
                <StarFilled v-if="item.is_favorite" /><Star v-else />
              </el-icon>
              <el-icon class="op" @click="copy(item.command)"><CopyDocument /></el-icon>
            </span>
          </div>
        </template>
        <div v-if="!filtered.length" class="empty">无匹配命令</div>
      </template>

      <!-- 文件夹模式（Nautilus 窗口管理） -->
      <template v-else-if="mode === 'files'">
        <div
          v-for="(item, i) in filteredNfiles"
          :key="item.id"
          class="palette-item"
          :class="{ active: i === activeIndex }"
          :title="nautilusTooltip(item)"
          @mouseenter="activeIndex = i"
          @click="nautilusAction(item)"
        >
          <el-icon color="#e6a23c"><Folder /></el-icon>
          <span class="cmd">{{ nAliases[item.id] || item.title || item.path || item.class }}</span>
          <span class="desc" v-if="!nAliases[item.id] && item.path">{{ item.path }}</span>
          <span class="ops" @click.stop>
            <el-icon class="op" title="设置备注名" @click="setAlias('nautilus', item)"><EditPen /></el-icon>
          </span>
        </div>
        <div v-if="!filteredNfiles.length" class="empty">未检测到文件夹窗口</div>
      </template>

      <!-- 端口模式 -->
      <template v-else-if="mode === 'ports'">
        <el-tooltip
          v-for="(p, i) in filteredPorts"
          :key="p.port + '-' + p.protocol"
          placement="top-start" :show-after="120" effect="dark"
        >
          <template #content>
            <div class="tip-row"><b>{{ p.port }}/{{ p.protocol }}</b> · {{ p.process_name || '未知进程' }}<template v-if="p.pid"> · PID {{ p.pid }}</template></div>
            <div class="tip-row">监听: {{ p.address || '全部网卡' }}<template v-if="p.iface">（{{ p.iface }}）</template>{{ p.exposed ? ' · 对外暴露' : '' }}</div>
            <div class="tip-row" v-if="p.container_name">容器: {{ p.container_name }}</div>
            <div class="tip-row" v-if="p.cwd">目录: {{ p.cwd }}</div>
            <div class="tip-row" v-if="p.command">命令: {{ p.command }}</div>
          </template>
          <div
            class="palette-item"
            :class="{ active: i === activeIndex }"
            @mouseenter="activeIndex = i"
            @click="portAction(p)"
          >
            <el-tag size="small" :type="p.exposed ? 'warning' : 'primary'" class="port-tag">{{ p.port }}</el-tag>
            <span class="cmd">{{ p.process_name || '未知进程' }}<template v-if="p.container_name"> · {{ p.container_name }}</template></span>
            <span class="desc">{{ portLine(p) }}</span>
          </div>
        </el-tooltip>
        <div v-if="!filteredPorts.length" class="empty">无匹配端口</div>
      </template>

      <!-- 终端模式 -->
      <template v-else>
        <div
          v-for="(t, i) in filteredTerms"
          :key="t.id"
          class="palette-item"
          :class="{ active: i === activeIndex }"
          :title="termTooltip(t)"
          @mouseenter="activeIndex = i"
          @click="termAction(t)"
        >
          <el-icon color="#d96b1e"><Monitor /></el-icon>
          <!-- 主位显示终端所在目录，不再显示 user@host 那类窗口标题 -->
          <span class="cmd">{{ termLabel(t) }}</span>
          <span class="desc" v-if="tAliases[t.id] && t.cwd">{{ t.cwd }}</span>
          <span class="ops" @click.stop>
            <el-icon class="op" title="设置备注名" @click="setAlias('term', t)"><EditPen /></el-icon>
          </span>
        </div>
        <div v-if="!filteredTerms.length" class="empty">未检测到外部终端窗口</div>
      </template>
    </div>

    <div class="palette-foot">
      <span>{{ footHint }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const query = ref('')
const mode = ref('cmd')
const all = ref([])
const filtered = ref([])
const activeIndex = ref(0)
const searchRef = ref(null)
const pinned = ref(false)
let refreshTimer = null

// ── 文件夹模式（Nautilus 窗口）──
const nfiles = ref([])
const nAliases = ref({})
// ── 端口模式 ──
const ports = ref([])
// ── 终端模式 ──
const terms = ref([])
const tAliases = ref({})

// 按来源分组：手册（command）与终端历史（其余）
const manualItems = computed(() => filtered.value.filter(x => x.source === 'command'))
const historyItems = computed(() => filtered.value.filter(x => x.source !== 'command'))

// ── 命令模式：分类 / 服务 / 场景 筛选 ──
const cmdCategory = ref('')
const cmdService = ref('')
const cmdScenario = ref('')
const hasCmdFilter = computed(() => !!(cmdCategory.value || cmdService.value || cmdScenario.value))

/** 从已加载的（最多 300 条）数据里收集可选值，免去额外请求 facets */
const cmdFacets = computed(() => {
  const categories = new Set(), services = new Set(), scenarios = new Set()
  for (const x of all.value) {
    if (x.category) categories.add(x.category)
    if (x.service) services.add(x.service)
    if (x.scenario) scenarios.add(x.scenario)
  }
  const sort = s => [...s].sort((a, b) => a.localeCompare(b, 'zh'))
  return { categories: sort(categories), services: sort(services), scenarios: sort(scenarios) }
})

function clearCmdFilters() {
  cmdCategory.value = ''
  cmdService.value = ''
  cmdScenario.value = ''
  refresh()
}

/** 行尾的分类 · 服务 · 场景 摘要 */
function itemMeta(x) {
  return [x.category, x.service, x.scenario].filter(Boolean).join(' · ')
}

const searchPlaceholder = computed(() => ({
  cmd: '搜索命令…', files: '搜索文件夹…', ports: '搜索端口或进程…', terms: '搜索终端…',
}[mode.value]))

const footHint = computed(() => mode.value === 'cmd'
  ? '↑↓ 选择 · Enter 输入终端 · Esc 关闭 · Ctrl+C 复制'
  : 'Enter 打开/复制/聚焦 · Esc 关闭')

// 各模式过滤列表
const filteredNfiles = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = nfiles.value || []
  return q ? list.filter(x =>
    (nAliases.value[x.id] || '').toLowerCase().includes(q)
    || (x.title || '').toLowerCase().includes(q)
    || (x.path || '').toLowerCase().includes(q)) : list
})
const filteredPorts = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = ports.value || []
  return q ? list.filter(p =>
    String(p.port).includes(q)
    || (p.process_name || '').toLowerCase().includes(q)
    || (p.container_name || '').toLowerCase().includes(q)
    || (p.cwd || '').toLowerCase().includes(q)
    || (p.command || '').toLowerCase().includes(q)) : list
})
const filteredTerms = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = terms.value || []
  return q ? list.filter(t =>
    (tAliases.value[t.id] || '').toLowerCase().includes(q)
    || (t.title || '').toLowerCase().includes(q)
    || (t.cwd || '').toLowerCase().includes(q)) : list
})

function sourceLabel(s) {
  return { terminal: '面板终端', external: '外部终端', shell: 'shell历史', command: '手册' }[s] || s || '终端'
}
function sourceType(s) {
  return { terminal: 'info', external: 'warning', shell: 'success', command: 'primary' }[s] || 'info'
}

// 子序列模糊匹配：输入 "dp" 命中 "docker ps"
function subsequence(q, t) {
  if (!q) return true
  q = q.toLowerCase()
  t = (t || '').toLowerCase()
  let i = 0
  for (let j = 0; j < t.length && i < q.length; j++) {
    if (t[j] === q[i]) i++
  }
  return i === q.length
}

function compute() {
  const q = query.value.trim()
  let list = all.value
  if (cmdCategory.value) list = list.filter(x => x.category === cmdCategory.value)
  if (cmdService.value) list = list.filter(x => x.service === cmdService.value)
  if (cmdScenario.value) list = list.filter(x => x.scenario === cmdScenario.value)
  if (q) {
    list = list.filter(x =>
      subsequence(q, x.command) || subsequence(q, x.description)
      || subsequence(q, x.category) || subsequence(q, x.service) || subsequence(q, x.scenario))
  }
  return [...list].sort((a, b) => (b.is_favorite - a.is_favorite) || ((b.use_count || 0) - (a.use_count || 0)))
}

function refresh() {
  if (mode.value === 'cmd') filtered.value = compute()
  activeIndex.value = 0
}

async function load() {
  try {
    const { data } = await api.get('/commands/lookup', { params: { limit: 300 } })
    all.value = data || []
  } catch (_) { all.value = [] }
  refresh()
  nextTick(() => searchRef.value?.focus())
}

async function loadNfiles() {
  try {
    const [w, a] = await Promise.all([
      api.get('/files/nautilus-windows'),
      api.get('/files/nautilus-aliases'),
    ])
    nfiles.value = w.data || []
    nAliases.value = a.data || {}
  } catch (_) { nfiles.value = []; nAliases.value = {} }
  activeIndex.value = 0
}

async function loadPorts() {
  try {
    const { data } = await api.get('/ports')
    ports.value = data || []
  } catch (_) { ports.value = [] }
  activeIndex.value = 0
}

async function loadTerms() {
  try {
    const [t, a] = await Promise.all([
      api.get('/terminal/external/list'),
      api.get('/terminal/external/aliases'),
    ])
    terms.value = t.data?.terminals || []
    tAliases.value = a.data || {}
  } catch (_) { terms.value = []; tAliases.value = {} }
  activeIndex.value = 0
}

function refreshAll() {
  if (mode.value === 'cmd') load()
  else if (mode.value === 'files') loadNfiles()
  else if (mode.value === 'ports') loadPorts()
  else loadTerms()
}

function onModeChange(m) {
  mode.value = m
  activeIndex.value = 0
  if (m === 'files') loadNfiles()
  else if (m === 'ports') loadPorts()
  else if (m === 'terms') loadTerms()
  else load()
  nextTick(() => searchRef.value?.focus())
}

function currentList() {
  if (mode.value === 'cmd') return filtered.value
  if (mode.value === 'files') return filteredNfiles.value
  if (mode.value === 'ports') return filteredPorts.value
  return filteredTerms.value
}

function move(d) {
  const list = currentList()
  if (!list.length) return
  activeIndex.value = (activeIndex.value + d + list.length) % list.length
  nextTick(() => {
    const el = document.querySelector('.palette-item.active')
    el?.scrollIntoView({ block: 'nearest' })
  })
}

function runSelected() {
  const list = currentList()
  const item = list[activeIndex.value]
  if (item) dispatch(item)
}

function dispatch(item) {
  if (mode.value === 'cmd') run(item)
  else if (mode.value === 'files') nautilusAction(item)
  else if (mode.value === 'ports') portAction(item)
  else termAction(item)
}

async function run(item) {
  if (!item) return
  try {
    const { data } = await api.post('/terminal/active/send', { command: item.command })
    if (data && data.ok) { ElMessage.success('已输入到终端，按回车执行'); return }
  } catch (_) {}
  await copy(item.command)
}

async function nautilusAction(item) {
  try {
    const { data } = await api.post(`/files/nautilus-windows/${item.id}/focus`)
    if (data && data.ok) ElMessage.success('已聚焦该文件夹窗口')
  } catch (_) { ElMessage.error('聚焦失败') }
}

async function portAction(p) {
  const text = `${p.port}/${p.protocol} ${p.process_name || ''}${p.pid ? ' pid:' + p.pid : ''}`.trim()
  await copy(text)
}

async function termAction(t) {
  try {
    const { data } = await api.post(`/terminal/external/${t.id}/focus`)
    if (data && data.ok) ElMessage.success('已聚焦该终端')
  } catch (_) { ElMessage.error('聚焦失败') }
}

// ── 端口模式：副标题 + 悬浮详情 ──
function portLine(p) {
  const parts = []
  if (p.pid) parts.push(`PID ${p.pid}`)
  if (p.address) parts.push(p.address)
  if (p.exposed) parts.push('对外暴露')
  if (p.cwd) parts.push(shortPath(p.cwd))
  return parts.join(' · ')
}

/** /a/b/c/d → …/c/d，避免长路径挤掉其它信息 */
function shortPath(p) {
  if (!p) return ''
  const parts = String(p).split('/').filter(Boolean)
  if (parts.length <= 2) return p
  return '…/' + parts.slice(-2).join('/')
}

// ── 终端模式：标题（user@host 之类）不占主位，改显所在目录 ──
function termLabel(t) {
  if (tAliases.value[t.id]) return tAliases.value[t.id]
  return t.cwd || t.class || t.id
}

// 完整信息 tooltip（平时隐藏，hover 显示）
function nautilusTooltip(item) {
  return [
    nAliases.value[item.id] ? `备注: ${nAliases.value[item.id]}` : '',
    `标题: ${item.title || '-'}`,
    item.path ? `路径: ${item.path}` : '',
    item.class ? `类型: ${item.class}` : '',
    `ID: ${item.id}`,
  ].filter(Boolean).join('\n')
}

function termTooltip(t) {
  return [
    tAliases.value[t.id] ? `备注: ${tAliases.value[t.id]}` : '',
    `标题: ${t.title || '-'}`,
    t.cwd ? `目录: ${t.cwd}` : '',
    t.pid ? `PID: ${t.pid}` : '',
    t.class ? `类型: ${t.class}` : '',
  ].filter(Boolean).join('\n')
}

// 设置窗口备注名（nautilus / term）
async function setAlias(kind, item) {
  const cur = kind === 'nautilus' ? (nAliases.value[item.id] || '') : (tAliases.value[item.id] || '')
  const { value } = await ElMessageBox.prompt('输入备注名（留空清除）', '设置备注', {
    inputValue: cur,
    confirmButtonText: '保存', cancelButtonText: '取消',
  }).catch(() => ({ value: null }))
  if (value === null) return
  try {
    if (kind === 'nautilus') {
      await api.post('/files/nautilus-aliases', { win_id: item.id, alias: value.trim() })
      if (value.trim()) nAliases.value[item.id] = value.trim()
      else delete nAliases.value[item.id]
    } else {
      await api.post('/terminal/external/aliases', { win_id: item.id, alias: value.trim() })
      if (value.trim()) tAliases.value[item.id] = value.trim()
      else delete tAliases.value[item.id]
    }
    ElMessage.success(value.trim() ? '已设置备注' : '已清除备注')
  } catch (_) { ElMessage.error('保存失败') }
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text) } catch (_) {
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  }
  ElMessage.success('已复制')
}

async function toggleFav(item) {
  try {
    const url = item.source === 'command'
      ? `/commands/${item.id}/favorite`
      : `/commands/history/${item.id}/favorite`
    const { data } = await api.post(url)
    item.is_favorite = data.is_favorite
    refresh()
  } catch (_) { ElMessage.error('操作失败') }
}

function onEsc() {
  if (query.value) { query.value = ''; refresh(); return }
  if (window.pywebview?.api?.hide) window.pywebview.api.hide()
}

async function minimize() {
  try { if (window.pywebview?.api?.minimize) await window.pywebview.api.minimize() } catch (_) {}
}

async function togglePin() {
  try {
    if (window.pywebview?.api?.togglePin) pinned.value = await window.pywebview.api.togglePin()
    else pinned.value = !pinned.value
  } catch (_) {}
}

function onGlobalKey(e) {
  if (e.ctrlKey && (e.key === 'c' || e.key === 'C')) {
    const inp = searchRef.value?.$el?.querySelector('input')
    if (document.activeElement === inp) return
    const list = currentList()
    const item = list[activeIndex.value]
    if (item) {
      e.preventDefault()
      const text = mode.value === 'cmd' ? item.command
        : mode.value === 'files' ? item.path
        : mode.value === 'ports' ? `${item.port}/${item.protocol}`
        : (item.title || '')
      copy(text)
    }
  }
}

onMounted(() => {
  // html/body 默认透明（透桌面）由 palette-host 提供；仅当透明窗口被禁用/不可用时补 palette-opaque 兜底
  document.documentElement.classList.add('palette-host')
  document.body.classList.add('palette-host')
  if (window.pywebview?.api?.isTransparent) {
    window.pywebview.api.isTransparent().then(v => {
      if (!v) {
        document.documentElement.classList.add('palette-opaque')
        document.body.classList.add('palette-opaque')
      }
    }).catch(() => {
      document.documentElement.classList.add('palette-opaque')
      document.body.classList.add('palette-opaque')
    })
  }
  load()
  window.addEventListener('keydown', onGlobalKey)
  // 定时自动刷新：命令/端口/终端 5s；文件夹窗口 5s（窗口开合变化）
  refreshTimer = setInterval(() => {
    if (mode.value === 'cmd') load()
    else if (mode.value === 'files') loadNfiles()
    else if (mode.value === 'ports') loadPorts()
    else if (mode.value === 'terms') loadTerms()
  }, 5000)
  if (window.pywebview?.api?.isPinned) window.pywebview.api.isPinned().then(v => { pinned.value = v }).catch(() => {})
})
onUnmounted(() => {
  document.documentElement.classList.remove('palette-host', 'palette-opaque')
  document.body.classList.remove('palette-host', 'palette-opaque')
  window.removeEventListener('keydown', onGlobalKey)
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.palette {
  position: absolute;
  inset: 8px;
  display: flex;
  flex-direction: column;
  color: var(--el-text-color-primary);
  overflow: hidden;
  border-radius: var(--radius-xl);

  /* 立体玻璃：半透明胶质底 + 顶部高光/底部暗角，靠 inset 高光与双层投影造厚度。
     有合成器（真透明窗口）时直接透出桌面；无合成器时透出兜底渐变画布，立体感仍在。 */
  background-color: rgba(255, 253, 249, 0.82);
  background-image:
    linear-gradient(180deg, rgba(255, 255, 255, 0.72) 0%, rgba(255, 255, 255, 0) 46%),
    linear-gradient(0deg, rgba(13, 23, 40, 0.08) 0%, rgba(13, 23, 40, 0) 30%);
  backdrop-filter: blur(16px) saturate(1.35);
  -webkit-backdrop-filter: blur(16px) saturate(1.35);
  border: 1px solid rgba(255, 255, 255, 0.62);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    inset 0 -1px 0 rgba(13, 23, 40, 0.07),
    0 20px 44px -14px rgba(13, 23, 40, 0.38),
    0 3px 10px -2px rgba(13, 23, 40, 0.14);
}
html.dark .palette {
  background-color: rgba(24, 34, 48, 0.84);
  background-image:
    linear-gradient(180deg, rgba(255, 255, 255, 0.10) 0%, rgba(255, 255, 255, 0) 46%),
    linear-gradient(0deg, rgba(0, 0, 0, 0.20) 0%, rgba(0, 0, 0, 0) 32%);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.13),
    inset 0 -1px 0 rgba(0, 0, 0, 0.30),
    0 20px 44px -14px rgba(0, 0, 0, 0.55),
    0 3px 10px -2px rgba(0, 0, 0, 0.34);
}
/* 不支持 backdrop-filter 时提高不透明度，保证命令文字可读 */
@supports not ((backdrop-filter: blur(2px)) or (-webkit-backdrop-filter: blur(2px))) {
  .palette { background-color: rgba(255, 253, 249, 0.95); }
  html.dark .palette { background-color: rgba(24, 34, 48, 0.96); }
}
/* 圆角面板四周留出呼吸感：底部/两侧内边距让内容不贴边 */
.palette-body {
  border-radius: 0 0 var(--radius-xl) var(--radius-xl);
}
.drag-bar {
  height: 12px;
  flex-shrink: 0;
  cursor: move;
  background: transparent;
}
.drag-bar:hover { background: var(--el-fill-color-light); }
.palette-head {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.palette-head .el-input { flex: 1; }
.head-ops { display: flex; gap: 2px; align-items: center; flex-shrink: 0; }
.head-op { cursor: pointer; color: var(--el-text-color-secondary); padding: 3px; border-radius: 3px; }
.head-op:hover { background: var(--el-fill-color-light); color: var(--el-color-primary); }
.head-op.on { color: #e6a23c; }
.palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.group-title {
  padding: 8px 10px 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-weight: 600;
  user-select: none;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
}
.palette-item:hover { background: var(--el-fill-color-light); }
.palette-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.palette-item .cmd {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.palette-item .desc {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 40%;
}
.palette-item .src-tag { flex-shrink: 0; }
.palette-item .meta {
  flex-shrink: 0; max-width: 30%;
  font-size: 11px; color: var(--el-text-color-placeholder);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
/* 命令模式的三级筛选条 */
.filter-bar {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 6px 8px;
  border-bottom: 1px dashed var(--el-border-color-lighter);
  margin-bottom: 4px;
}
.filter-bar .f-sel { flex: 1; min-width: 0; }
.filter-count { flex-shrink: 0; font-size: 11px; color: var(--el-text-color-secondary); }
.palette-item .port-tag { flex-shrink: 0; min-width: 52px; text-align: center; }
.palette-item .ops { display: flex; gap: 6px; flex-shrink: 0; }
.palette-item .op { color: var(--el-text-color-secondary); cursor: pointer; }
.palette-item .op:hover { color: var(--el-color-primary); }
.palette-item .op.on { color: #e6a23c; }
.palette-item .empty { padding: 24px; text-align: center; color: var(--el-text-color-secondary); font-size: 13px; }
.palette-foot {
  padding: 6px 12px;
  border-top: 1px solid var(--el-border-color-light);
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: center;
}
</style>
