<template>
  <div class="commands-view">
    <h2 class="page-title">命令速查手册</h2>

    <div class="toolbar">
      <el-input v-model="keyword" placeholder="中英文搜索命令..." clearable prefix-icon="Search"
        class="search-input" @clear="fetchCommands" @keyup.enter="fetchCommands" />
      <el-select v-model="category" placeholder="分类筛选" clearable @change="fetchCommands" class="cat-select">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button type="primary" @click="showCreateDialog = true"><el-icon><Plus /></el-icon> 新增</el-button>
      <el-button @click="exportCommands"><el-icon><Download /></el-icon> 导出</el-button>
      <el-upload :show-file-list="false" accept=".json" :before-upload="importCommands" class="inline-upload">
        <el-button><el-icon><Upload /></el-icon> 导入</el-button>
      </el-upload>
      <el-button @click="showHistory = true"><el-icon><Clock /></el-icon> 终端历史</el-button>
    </div>

    <!-- Top 5 横幅 -->
    <div class="top-bar" v-if="topCommands.length">
      <el-tag type="warning" effect="dark" v-for="(c, i) in topCommands" :key="c.id" class="top-tag"
        @click="copyAndUse(c)">
        🏆 #{{ i + 1 }} {{ c.command?.substring(0, 40) }}
        <small>({{ c.use_count }}次)</small>
      </el-tag>
    </div>

    <!-- Command Table -->
    <el-table :data="commands" stripe v-loading="loading" @row-click="showDetail" class="cmd-table">
      <el-table-column prop="command" label="命令" min-width="200">
        <template #default="{ row }">
          <el-tag size="small" type="info" class="cmd-tag">{{ row.category }}</el-tag>
          <code>{{ row.command }}</code>
          <el-tag v-if="row.is_favorite" size="small" type="warning" effect="plain">★</el-tag>
          <el-tag v-if="row.use_count" size="small" type="success" effect="plain" class="count-tag">{{ row.use_count }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="260" show-overflow-tooltip />
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="copyAndUse(row)">复制</el-button>
          <el-button size="small" type="warning" @click.stop="toggleFav(row)">
            {{ row.is_favorite ? '取消' : '收藏' }}
          </el-button>
          <el-button size="small" @click.stop="sendToTerminal(row)">发送</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Detail Dialog -->
    <el-dialog v-model="detailVisible" :title="detailCmd?.command" width="650px">
      <template v-if="detailCmd">
        <p><strong>分类：</strong>{{ detailCmd.category }}</p>
        <p><strong>说明：</strong>{{ detailCmd.description }}</p>
        <p><strong>使用次数：</strong>{{ detailCmd.use_count || 0 }}</p>
        <div v-if="detailCmd.params.length">
          <strong>参数：</strong>
          <el-table :data="detailCmd.params" size="small" class="param-table">
            <el-table-column prop="flag" label="参数" width="120" />
            <el-table-column prop="meaning" label="含义" />
          </el-table>
        </div>
        <div v-if="detailCmd.examples.length">
          <strong>示例：</strong>
          <pre class="examples">{{ detailCmd.examples.join('\n') }}</pre>
        </div>
        <el-button type="primary" @click="copyAndUse(detailCmd)">复制并记录</el-button>
      </template>
    </el-dialog>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="showCreateDialog" title="新增命令" width="550px" @closed="resetForm">
      <el-form :model="form" label-width="80px">
        <el-form-item label="分类"><el-input v-model="form.category" placeholder="如：网络、Docker、Git..." /></el-form-item>
        <el-form-item label="命令"><el-input v-model="form.command" placeholder="如：ss -tlnp" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="参数"><el-input v-model="form.paramsText" placeholder='JSON' type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="示例"><el-input v-model="form.examplesText" placeholder='JSON' type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCommand">保存</el-button>
      </template>
    </el-dialog>

    <!-- Terminal History Dialog -->
    <el-dialog v-model="showHistory" title="终端历史" width="780px" @opened="fetchHistory">
      <div style="margin-bottom:10px;display:flex;gap:8px;align-items:center">
        <el-button size="small" type="primary" @click="importShellHistory" :loading="shellLoading">
          <el-icon><Download /></el-icon> 从 shell 历史导入
        </el-button>
        <el-button size="small" @click="fetchHistory"><el-icon><Refresh /></el-icon> 刷新</el-button>
        <span style="font-size:12px;color:var(--el-text-color-secondary)">
          已收录 {{ history.length }} 条 · 转存后可在命令手册检索
        </span>
      </div>
      <el-table :data="history" size="small" max-height="400">
        <el-table-column prop="command" label="命令" show-overflow-tooltip />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="sourceType(row.source)">{{ sourceLabel(row.source) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ row.created_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="convertHistory(row)">转存</el-button>
            <el-button size="small" type="danger" @click="deleteHistory(row.id)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const keyword = ref('')
const category = ref('')
const commands = ref([])
const topCommands = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const detailCmd = ref(null)
const showCreateDialog = ref(false)
const showHistory = ref(false)
const history = ref([])
const form = ref({ category: '', command: '', description: '', paramsText: '', examplesText: '' })
const editId = ref(null)

const categories = computed(() => [...new Set(commands.value.map(c => c.category))].filter(Boolean).sort())

async function fetchCommands() {
  loading.value = true
  try {
    const params = {}
    if (keyword.value) params.keyword = keyword.value
    if (category.value) params.category = category.value
    const { data } = await api.get('/commands', { params })
    commands.value = data.map(c => ({
      ...c, params: safeJson(c.params_json, []), examples: safeJson(c.examples_json, []),
    }))
  } catch (_) {}
  loading.value = false
}

async function fetchTop() {
  try {
    const { data } = await api.get('/commands/top?limit=5')
    topCommands.value = data
  } catch (_) {}
}

async function fetchHistory() {
  try {
    const { data } = await api.get('/commands/history?limit=50')
    history.value = data
  } catch (_) {}
}

const shellLoading = ref(false)

async function importShellHistory() {
  shellLoading.value = true
  try {
    const { data } = await api.get('/commands/history/from-shell?limit=80')
    const cmds = data.commands || []
    if (!cmds.length) { ElMessage.info(data.message || 'shell 历史为空'); return }
    // 逐条写入历史（去重由后端 list 不保证，但写入时跳过与现有重复的）
    let added = 0
    const existing = new Set(history.value.map(h => h.command))
    for (const cmd of cmds) {
      if (existing.has(cmd)) continue
      await api.post('/commands/history', { command: cmd, source: 'shell' })
      existing.add(cmd)
      added++
    }
    ElMessage.success(`从 shell 历史导入 ${added} 条命令`)
    await fetchHistory()
  } catch (_) { ElMessage.error('导入失败') }
  shellLoading.value = false
}

function sourceLabel(source) {
  return { terminal: '面板终端', external: '外部终端', shell: 'shell历史', command: '手册发送' }[source] || source || '终端'
}
function sourceType(source) {
  return { terminal: 'info', external: 'warning', shell: 'success', command: 'primary' }[source] || 'info'
}

function safeJson(str, fb) { try { return JSON.parse(str) } catch (_) { return fb } }

function showDetail(row) { detailCmd.value = row; detailVisible.value = true }

async function copyAndUse(row) {
  try { await navigator.clipboard.writeText(row.command) } catch (_) {
    const el = document.createElement('textarea'); el.value = row.command
    document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el)
  }
  try { await api.post(`/commands/${row.id}/use`) } catch (_) {}
  row.use_count = (row.use_count || 0) + 1
  ElMessage.success('已复制')
}

async function toggleFav(row) {
  try { const { data } = await api.post(`/commands/${row.id}/favorite`); row.is_favorite = data.is_favorite } catch (_) {}
}

async function sendToTerminal(row) {
  try {
    const { data } = await api.post('/terminal/create', { name: row.command.substring(0, 20), cwd: '~', shell: '/bin/bash', command: row.command })
    ElMessage.success('已发送到终端')
    // Record history
    await api.post('/commands/history', { command: row.command, cwd: '~', source: 'command' })
    await api.post(`/commands/${row.id}/use`)
    row.use_count = (row.use_count || 0) + 1
  } catch (_) { ElMessage.error('发送失败') }
}

async function saveCommand() {
  const body = { category: form.value.category, command: form.value.command, description: form.value.description,
    params_json: form.value.paramsText || '[]', examples_json: form.value.examplesText || '[]' }
  try {
    if (editId.value) { await api.put(`/commands/${editId.value}`, body) }
    else { await api.post('/commands', body) }
    ElMessage.success('保存成功')
    showCreateDialog.value = false; editId.value = null
    await fetchCommands()
  } catch (_) { ElMessage.error('保存失败') }
}

function resetForm() {
  form.value = { category: '', command: '', description: '', paramsText: '', examplesText: '' }
  editId.value = null
}

async function exportCommands() {
  try {
    const { data } = await api.get('/commands/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'commands.json'; a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`导出 ${data.length} 条命令`)
  } catch (_) { ElMessage.error('导出失败') }
}

async function importCommands(file) {
  try {
    const text = await file.text()
    const commands = JSON.parse(text)
    const body = Array.isArray(commands) ? { commands } : { commands: [commands] }
    const { data } = await api.post('/commands/import', body)
    ElMessage.success(`导入 ${data.imported} 条命令`)
    await fetchCommands()
  } catch (_) { ElMessage.error('导入失败：请确保是有效的 JSON 文件') }
  return false
}

async function convertHistory(row) {
  try {
    const { data } = await api.post(`/commands/history/${row.id}/convert`)
    ElMessage.success('已转存为命令条目')
    await fetchCommands()
    await fetchHistory()
  } catch (_) { ElMessage.error('转存失败') }
}

async function deleteHistory(id) {
  try { await api.delete(`/commands/history/${id}`); await fetchHistory() } catch (_) {}
}

onMounted(() => { fetchCommands(); fetchTop() })
</script>

<style scoped>
.commands-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.search-input { max-width: 320px; }
.cat-select { width: 150px; }
.cmd-table { cursor: pointer; }
.cmd-tag { margin-right: 8px; }
.count-tag { margin-left: 6px; font-size: 10px; }
.top-bar { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.top-tag { cursor: pointer; }
.param-table { margin: 8px 0 12px; }
.examples { background: var(--el-fill-color-light); padding: 12px; border-radius: var(--radius-sm); font-family: monospace; }
.inline-upload { display: inline-block; }
</style>
