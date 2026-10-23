<template>
  <div class="commands-view">
    <h2 class="page-title">命令速查手册</h2>
    <p class="module-purpose">把常用命令、参数和历史收进一处，搜索后即可复制复用。</p>

    <div class="toolbar">
      <el-input v-model="keyword" placeholder="中英文搜索命令..." clearable prefix-icon="Search"
        class="search-input" @clear="fetchCommands" @keyup.enter="fetchCommands" />
      <el-select v-model="category" placeholder="分类" clearable @change="fetchCommands" class="cat-select">
        <el-option v-for="c in facets.categories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="serviceFilter" placeholder="所属服务" clearable @change="fetchCommands" class="cat-select">
        <el-option v-for="c in facets.services" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="scenarioFilter" placeholder="所属场景" clearable @change="fetchCommands" class="cat-select">
        <el-option v-for="c in facets.scenarios" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新增</el-button>
      <el-button @click="exportCommands"><el-icon><Download /></el-icon> 导出</el-button>
      <el-upload :show-file-list="false" accept=".json" :before-upload="importCommands" class="inline-upload">
        <el-button><el-icon><Upload /></el-icon> 导入</el-button>
      </el-upload>
      <el-button @click="showHistory = true"><el-icon><Clock /></el-icon> 终端历史</el-button>
      <el-button @click="$router.push('/taxonomy')"><el-icon><CollectionTag /></el-icon> 分类管理</el-button>
      <el-button @click="rankVisible = true"><el-icon><Histogram /></el-icon> 排行榜</el-button>
    </div>

    <!-- Command Table -->
    <el-table :data="commands" stripe v-loading="loading" @row-click="showDetail" class="cmd-table">
      <el-table-column prop="command" label="命令" min-width="220">
        <template #default="{ row }">
          <el-tag size="small" type="info" class="cmd-tag">{{ row.category }}</el-tag>
          <el-tag v-if="row.service" size="small" type="success" effect="plain" class="cmd-tag">{{ row.service }}</el-tag>
          <el-tag v-if="row.scenario" size="small" type="warning" effect="plain" class="cmd-tag">{{ row.scenario }}</el-tag>
          <code>{{ row.command }}</code>
          <el-tag v-if="row.is_favorite" size="small" type="warning" effect="plain">★</el-tag>
          <el-tag v-if="row.use_count" size="small" type="success" effect="plain" class="count-tag">{{ row.use_count }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click.stop="copyAndUse(row)">复制</el-button>
          <el-button size="small" type="warning" @click.stop="toggleFav(row)">
            {{ row.is_favorite ? '取消' : '收藏' }}
          </el-button>
          <el-button size="small" @click.stop="editCommand(row)">编辑</el-button>
          <el-button size="small" @click.stop="sendToTerminal(row)">发送</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Detail Dialog -->
    <el-dialog v-model="detailVisible" :title="detailCmd?.command" width="650px">
      <template v-if="detailCmd">
        <p><strong>分类：</strong>{{ detailCmd.category }}</p>
        <p>
          <strong>所属服务：</strong>{{ detailCmd.service || '-' }}
          <span class="sep">|</span>
          <strong>所属场景：</strong>{{ detailCmd.scenario || '-' }}
        </p>
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
        <el-button type="primary" @click="copyAndUse(detailCmd)">复制</el-button>
      </template>
    </el-dialog>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="showCreateDialog" :title="editId ? '编辑命令' : '新增命令'" width="550px" @closed="resetForm">
      <el-form :model="form" label-width="90px">
        <el-form-item label="分类">
          <el-select v-model="form.category" filterable allow-create clearable default-first-option
            placeholder="如：网络、Docker、Git..." style="width: 100%">
            <el-option v-for="c in facets.categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属服务">
          <el-select v-model="form.service" filterable allow-create clearable default-first-option
            placeholder="如：nginx、redis、面板后端..." style="width: 100%">
            <el-option v-for="c in facets.services" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属场景">
          <el-select v-model="form.scenario" filterable allow-create clearable default-first-option
            placeholder="如：排障、部署、日常巡检..." style="width: 100%">
            <el-option v-for="c in facets.scenarios" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
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
    <el-dialog v-model="showHistory" title="终端历史" width="860px"
      @opened="onHistoryOpened" @closed="onHistoryClosed">
      <div class="hist-toolbar">
        <el-button size="small" type="primary" @click="importShellHistory" :loading="shellLoading">
          <el-icon><Download /></el-icon> 从 shell 历史导入
        </el-button>
        <el-button size="small" @click="fetchHistory"><el-icon><Refresh /></el-icon> 刷新</el-button>
        <el-input v-model="historyKeyword" placeholder="过滤已收录命令" clearable size="small" class="hist-search" />
        <span class="tip">
          库中共 {{ historyCfg.total || 0 }} 条 · 匹配 {{ historyTotal }} 条 · 当前显示 {{ history.length }} 条
        </span>
      </div>

      <div class="cfg-box">
        <span class="cfg-title">收录设置</span>
        <span class="tip">首次导入/重扫时每个文件最多收录</span>
        <el-input-number v-model="historyCfg.max_entries" :min="1" :max="100000" size="small"
          controls-position="right" class="cfg-num" />
        <span class="tip">条</span>
        <span class="tip">同步间隔</span>
        <el-input-number v-model="historyCfg.interval" :min="1" :max="3600" size="small"
          controls-position="right" class="cfg-num" />
        <span class="tip">秒</span>
        <el-checkbox v-model="historyCfg.global" size="small">同步 /home/* 所有用户</el-checkbox>
        <el-button size="small" @click="saveHistoryCfg">保存</el-button>
        <el-button size="small" type="warning" @click="doRescan" :loading="rescanLoading">
          重新全量扫描
        </el-button>
        <span class="tip">调大上限后点「重新全量扫描」，可把之前没收录进去的老命令补进来</span>
      </div>

      <el-table :data="history" size="small" max-height="380" v-loading="historyLoading">
        <el-table-column prop="command" label="命令" show-overflow-tooltip />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="sourceType(row.source)">{{ sourceLabel(row.source) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ row.created_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openConvert(row)">转存</el-button>
            <el-button size="small" type="danger" @click="deleteHistory(row.id)">删</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="hist-pager">
        <el-pagination
          v-model:current-page="historyPage"
          v-model:page-size="historyPageSize"
          :total="historyTotal"
          :page-sizes="[50, 100, 200, 500, 1000]"
          :pager-count="7"
          layout="total, sizes, prev, pager, next, jumper"
          size="small" background />
      </div>
    </el-dialog>

    <!-- 命令排行榜：按终端历史真实执行次数排序 -->
    <el-dialog v-model="rankVisible" title="🏆 命令排行榜" width="760px" @opened="fetchTop">
      <p class="rank-desc">
        按终端历史里的<strong>真实执行次数</strong>排序（复制不计入）。
        历史数据是去重导入的，次数从接入后开始累加。
      </p>
      <el-table :data="topCommands" size="small" max-height="420" v-loading="topLoading">
        <el-table-column label="#" width="64" align="center">
          <template #default="{ $index }">
            <span class="rank-badge" :class="rankClass($index)">{{ $index + 1 }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="command" label="命令" min-width="240" show-overflow-tooltip />
        <el-table-column label="分类" width="120">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.category || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="exec_count" label="执行次数" width="110" align="center">
          <template #default="{ row }">
            <strong>{{ row.exec_count }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="copyAndUse(row)">复制</el-button>
            <el-button size="small" type="primary" @click="sendToTerminal(row)">发送</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!topLoading && !topCommands.length" description="还没有执行记录" :image-size="80" />
    </el-dialog>

    <!-- 转存：指定分类 / 服务 / 场景 -->
    <el-dialog v-model="convertVisible" title="转存为命令条目" width="480px">
      <p class="convert-cmd"><code>{{ convertRow?.command }}</code></p>
      <el-form label-width="90px">
        <el-form-item label="一级分类">
          <el-select v-model="convertForm.category" filterable allow-create clearable default-first-option
            placeholder="如：Docker、Git、网络" style="width: 100%">
            <el-option v-for="c in facets.categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属服务">
          <el-select v-model="convertForm.service" filterable allow-create clearable default-first-option
            placeholder="如：nginx、redis、面板后端" style="width: 100%">
            <el-option v-for="c in facets.services" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属场景">
          <el-select v-model="convertForm.scenario" filterable allow-create clearable default-first-option
            placeholder="如：排障、部署、日常巡检" style="width: 100%">
            <el-option v-for="c in facets.scenarios" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertVisible = false">取消</el-button>
        <el-button type="primary" @click="doConvert">转存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const keyword = ref('')
const category = ref('')
const serviceFilter = ref('')
const scenarioFilter = ref('')
const commands = ref([])
const topCommands = ref([])
const topLoading = ref(false)
const rankVisible = ref(false)
const loading = ref(false)
const detailVisible = ref(false)
const detailCmd = ref(null)
const showCreateDialog = ref(false)
const showHistory = ref(false)
const history = ref([])
const historyKeyword = ref('')
const historyPage = ref(1)
const historyPageSize = ref(200)
const historyTotal = ref(0)
const historyLoading = ref(false)
const facets = ref({ categories: [], services: [], scenarios: [] })
const form = ref({
  category: '', service: '', scenario: '',
  command: '', description: '', paramsText: '', examplesText: '',
})
const editId = ref(null)

// 收录设置
const historyCfg = ref({ max_entries: 5000, global: false, interval: 5, total: 0 })
const rescanLoading = ref(false)
const shellLoading = ref(false)
let historyPollTimer = null

// 转存弹窗
const convertVisible = ref(false)
const convertRow = ref(null)
const convertForm = ref({ category: '历史转存', service: '', scenario: '' })

// 关键字交给后端过滤（全库匹配，不再只过滤当前页），输入防抖 300ms
let historySearchTimer = null
watch(historyKeyword, () => {
  clearTimeout(historySearchTimer)
  historySearchTimer = setTimeout(() => {
    if (historyPage.value !== 1) historyPage.value = 1  // 触发翻页 watch 去拉取
    else fetchHistory()
  }, 300)
})
watch([historyPage, historyPageSize], () => fetchHistory())

async function fetchCommands() {
  loading.value = true
  try {
    const params = {}
    if (keyword.value) params.keyword = keyword.value
    if (category.value) params.category = category.value
    if (serviceFilter.value) params.service = serviceFilter.value
    if (scenarioFilter.value) params.scenario = scenarioFilter.value
    const { data } = await api.get('/commands', { params })
    commands.value = data.map(c => ({
      ...c, params: safeJson(c.params_json, []), examples: safeJson(c.examples_json, []),
    }))
  } catch (_) {}
  loading.value = false
}

async function fetchFacets() {
  try { const { data } = await api.get('/commands/facets'); facets.value = data } catch (_) {}
}

async function fetchTop() {
  topLoading.value = true
  try {
    const { data } = await api.get('/commands/top?limit=20')
    topCommands.value = data
  } catch (_) {}
  topLoading.value = false
}

// 前三名给金银铜色，其余用默认灰底
function rankClass(i) {
  if (i === 0) return 'rank-1'
  if (i === 1) return 'rank-2'
  if (i === 2) return 'rank-3'
  return ''
}

async function fetchHistory() {
  historyLoading.value = true
  try {
    const { data } = await api.get('/commands/history', {
      params: {
        limit: historyPageSize.value,
        offset: (historyPage.value - 1) * historyPageSize.value,
        q: historyKeyword.value.trim(),
      },
    })
    history.value = data.items || []
    historyTotal.value = data.total || 0
    // 删到最后一页空了就回退一页
    if (!history.value.length && historyPage.value > 1) {
      historyPage.value -= 1
    }
  } catch (_) {}
  historyLoading.value = false
}

async function fetchHistoryConfig() {
  try { const { data } = await api.get('/commands/history/config'); historyCfg.value = data } catch (_) {}
}

async function saveHistoryCfg() {
  try {
    const { data } = await api.post('/commands/history/config', {
      max_entries: historyCfg.value.max_entries,
      history_global: !!historyCfg.value.global,
      interval: historyCfg.value.interval,
    })
    historyCfg.value = { ...historyCfg.value, ...data }
    ElMessage.success('收录设置已保存（后台下一轮即生效）')
  } catch (_) { ElMessage.error('保存失败') }
}

async function doRescan() {
  rescanLoading.value = true
  try {
    await api.post('/commands/history/rescan')
    ElMessage.success('已请求重新全量扫描，约 5 秒后点刷新查看')
    setTimeout(async () => { await fetchHistory(); await fetchHistoryConfig() }, 6000)
  } catch (_) { ElMessage.error('请求失败') }
  rescanLoading.value = false
}

async function importShellHistory() {
  shellLoading.value = true
  try {
    const { data } = await api.get('/commands/history/from-shell?limit=500')
    const cmds = data.commands || []
    if (!cmds.length) { ElMessage.info(data.message || 'shell 历史为空'); return }
    // cmds 是"最近在前"，反过来从旧到新写，后端每写一条时间戳递增，
    // 这样最近用过的才会排在历史列表最前面
    let added = 0
    const existing = new Set(history.value.map(h => h.command))
    for (const cmd of [...cmds].reverse()) {
      if (existing.has(cmd)) continue
      await api.post('/commands/history', { command: cmd, source: 'shell' })
      existing.add(cmd)
      added++
    }
    ElMessage.success(`从 shell 历史导入 ${added} 条命令`)
    await fetchHistory()
    await fetchHistoryConfig()
  } catch (_) { ElMessage.error('导入失败') }
  shellLoading.value = false
}

function stopHistoryPoll() {
  if (historyPollTimer) {
    clearInterval(historyPollTimer)
    historyPollTimer = null
  }
}

function onHistoryOpened() {
  fetchHistory()
  fetchHistoryConfig()
  stopHistoryPoll()
  // 弹窗打开时每 2 秒刷新一次，配合后端 1 秒同步接近实时
  historyPollTimer = setInterval(() => {
    if (!historyLoading.value) fetchHistory()
  }, 2000)
}

function onHistoryClosed() {
  stopHistoryPoll()
}

onUnmounted(stopHistoryPoll)

function sourceLabel(source) {
  return { terminal: '面板终端', external: '外部终端', shell: 'shell历史', command: '手册发送' }[source] || source || '终端'
}
function sourceType(source) {
  return { terminal: 'info', external: 'warning', shell: 'success', command: 'primary' }[source] || 'info'
}

function safeJson(str, fb) { try { return JSON.parse(str) } catch (_) { return fb } }

function showDetail(row) { detailCmd.value = row; detailVisible.value = true }

function openCreate() { editId.value = null; resetForm(); showCreateDialog.value = true }

function editCommand(row) {
  editId.value = row.id
  form.value = {
    category: row.category || '',
    service: row.service || '',
    scenario: row.scenario || '',
    command: row.command || '',
    description: row.description || '',
    paramsText: row.params_json || '[]',
    examplesText: row.examples_json || '[]',
  }
  showCreateDialog.value = true
}

async function copyAndUse(row) {
  try { await navigator.clipboard.writeText(row.command) } catch (_) {
    const el = document.createElement('textarea'); el.value = row.command
    document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el)
  }
  ElMessage.success('已复制')
}

async function toggleFav(row) {
  try { const { data } = await api.post(`/commands/${row.id}/favorite`); row.is_favorite = data.is_favorite } catch (_) {}
}

async function sendToTerminal(row) {
  try {
    const { data } = await api.post('/terminal/create', { name: row.command.substring(0, 20), cwd: '~', shell: '/bin/bash', command: row.command })
    ElMessage.success('已发送到终端')
    await api.post('/commands/history', { command: row.command, cwd: '~', source: 'command' })
    await api.post(`/commands/${row.id}/use`)
    row.use_count = (row.use_count || 0) + 1
  } catch (_) { ElMessage.error('发送失败') }
}

async function saveCommand() {
  const body = {
    category: form.value.category || '',
    service: form.value.service || '',
    scenario: form.value.scenario || '',
    command: form.value.command,
    description: form.value.description,
    params_json: form.value.paramsText || '[]',
    examples_json: form.value.examplesText || '[]',
  }
  try {
    if (editId.value) { await api.put(`/commands/${editId.value}`, body) }
    else { await api.post('/commands', body) }
    ElMessage.success('保存成功')
    showCreateDialog.value = false; editId.value = null
    await Promise.all([fetchCommands(), fetchFacets()])
  } catch (_) { ElMessage.error('保存失败') }
}

function resetForm() {
  form.value = {
    category: '', service: '', scenario: '',
    command: '', description: '', paramsText: '', examplesText: '',
  }
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
    await Promise.all([fetchCommands(), fetchFacets()])
  } catch (_) { ElMessage.error('导入失败：请确保是有效的 JSON 文件') }
  return false
}

function openConvert(row) {
  convertRow.value = row
  convertForm.value = { category: '历史转存', service: '', scenario: '' }
  convertVisible.value = true
}

async function doConvert() {
  if (!convertRow.value) return
  try {
    const { data } = await api.post(`/commands/history/${convertRow.value.id}/convert`, {
      category: convertForm.value.category || '',
      service: convertForm.value.service || '',
      scenario: convertForm.value.scenario || '',
    })
    ElMessage.success(data.duplicate ? '命令已存在，已补齐分类信息' : '已转存为命令条目')
    convertVisible.value = false
    await Promise.all([fetchCommands(), fetchFacets(), fetchHistory()])
  } catch (_) { ElMessage.error('转存失败') }
}

async function deleteHistory(id) {
  try { await api.delete(`/commands/history/${id}`); await fetchHistory() } catch (_) {}
}

onMounted(() => { fetchCommands(); fetchTop(); fetchFacets() })
</script>

<style scoped>
.commands-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
.search-input { max-width: 320px; }
.cat-select { width: 150px; }
.cmd-table { cursor: pointer; }
.cmd-tag { margin-right: 6px; }
.count-tag { margin-left: 6px; font-size: 10px; }
.rank-desc { margin: 0 0 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.rank-badge {
  display: inline-block; width: 24px; height: 24px; line-height: 24px;
  border-radius: 50%; font-size: 12px; font-weight: 700;
  background: var(--el-fill-color); color: var(--el-text-color-secondary);
}
.rank-1 { background: #f5c518; color: #fff; }
.rank-2 { background: #b8c0cc; color: #fff; }
.rank-3 { background: #cd7f32; color: #fff; }
.param-table { margin: 8px 0 12px; }
.examples { background: var(--el-fill-color-light); padding: 12px; border-radius: var(--radius-sm); font-family: monospace; }
.inline-upload { display: inline-block; }
.sep { margin: 0 8px; color: var(--el-text-color-disabled); }
.tip { font-size: 12px; color: var(--el-text-color-secondary); }

/* 终端历史 */
.hist-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.hist-search { width: 200px; }
.hist-pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.cfg-box {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px;
  padding: 8px 10px; border: 1px dashed var(--el-border-color); border-radius: 8px;
}
.cfg-title { font-size: 13px; font-weight: 600; }
.cfg-num { width: 120px; }
.convert-cmd { margin: 0 0 12px; word-break: break-all; }
</style>
