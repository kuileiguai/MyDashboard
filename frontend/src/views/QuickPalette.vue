<template>
  <div class="palette">
    <div class="palette-head">
      <el-input
        ref="searchRef"
        v-model="query"
        placeholder="搜索命令…"
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
      <el-radio-group v-model="tab" size="small" @change="refresh">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="fav">常用</el-radio-button>
      </el-radio-group>
    </div>

    <div class="palette-body">
      <div
        v-for="(item, i) in filtered"
        :key="item.source + '-' + item.id"
        class="palette-item"
        :class="{ active: i === activeIndex }"
        @mouseenter="activeIndex = i"
        @click="run(item)"
      >
        <span class="cmd" :title="item.command">{{ item.command }}</span>
        <span class="desc" v-if="item.description">{{ item.description }}</span>
        <el-tag size="small" :type="sourceType(item.source)" class="src-tag">{{ sourceLabel(item.source) }}</el-tag>
        <span class="ops" @click.stop>
          <el-icon class="op" :class="{ on: item.is_favorite }" @click="toggleFav(item)">
            <StarFilled v-if="item.is_favorite" /><Star v-else />
          </el-icon>
          <el-icon class="op" @click="copy(item.command)"><CopyDocument /></el-icon>
        </span>
      </div>
      <div v-if="!filtered.length" class="empty">无匹配命令</div>
    </div>

    <div class="palette-foot">
      <span>↑↓ 选择 · Enter 发送 · Esc 关闭 · Ctrl+C 复制</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const query = ref('')
const tab = ref('all')
const all = ref([])
const filtered = ref([])
const activeIndex = ref(0)
const searchRef = ref(null)

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
  if (tab.value === 'fav') list = list.filter(x => x.is_favorite)
  if (q) list = list.filter(x => subsequence(q, x.command) || subsequence(q, x.description))
  return [...list].sort((a, b) => (b.is_favorite - a.is_favorite) || ((b.use_count || 0) - (a.use_count || 0)))
}

function refresh() {
  filtered.value = compute()
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

function move(d) {
  if (!filtered.value.length) return
  activeIndex.value = (activeIndex.value + d + filtered.value.length) % filtered.value.length
  nextTick(() => {
    const el = document.querySelector('.palette-item.active')
    el?.scrollIntoView({ block: 'nearest' })
  })
}

async function run(item) {
  if (!item) return
  try {
    const { data } = await api.post('/terminal/active/send', { command: item.command })
    if (data && data.ok) { ElMessage.success('已发送'); return }
  } catch (_) {}
  await copy(item.command)
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

function runSelected() {
  const item = filtered.value[activeIndex.value]
  if (item) run(item)
}

function onEsc() {
  if (query.value) { query.value = ''; refresh(); return }
  // 通过 pywebview 桥接隐藏悬浮窗（阶段3宿主提供）
  if (window.pywebview?.api?.hide) window.pywebview.api.hide()
}

function onGlobalKey(e) {
  // Ctrl+C：复制选中项（焦点不在输入框时）
  if (e.ctrlKey && (e.key === 'c' || e.key === 'C')) {
    const inp = searchRef.value?.$el?.querySelector('input')
    if (document.activeElement === inp) return // 让输入框保持默认复制
    const item = filtered.value[activeIndex.value]
    if (item) { e.preventDefault(); copy(item.command) }
  }
}

onMounted(() => { load(); window.addEventListener('keydown', onGlobalKey) })
onUnmounted(() => window.removeEventListener('keydown', onGlobalKey))
</script>

<style scoped>
.palette {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  overflow: hidden;
}
.palette-head {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.palette-head .el-input { flex: 1; }
.palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.palette-item:hover { background: var(--el-fill-color-light); }
.palette-item.active { background: var(--el-color-primary-light-9); }
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
