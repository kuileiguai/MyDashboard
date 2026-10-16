<template>
  <div class="logs-view">
    <h2 class="page-title">日志查看器</h2>
    <p class="module-purpose">集中打开多份日志，搜索关键字并追踪实时输出。</p>

    <div class="logs-body" ref="logsBodyRef">
      <!-- 左侧：日志库（可折叠 / 可拖拽调宽） -->
      <div class="lib-pane" :style="{ width: paneWidth + 'px' }">
        <div v-if="libCollapsed" class="lib-collapsed" title="展开日志库" @click="toggleCollapse">
          <el-icon><Expand /></el-icon>
          <span class="lib-collapsed-text">日志库</span>
        </div>
        <aside v-else class="log-library">
          <div class="lib-head">
            <span class="lib-title">日志库</span>
            <div class="lib-head-actions">
              <el-button size="small" type="primary" @click="importVisible = true">导入</el-button>
              <el-button size="small" :loading="libLoading" @click="loadLibrary">
                <el-icon><Refresh /></el-icon>
              </el-button>
              <el-button size="small" title="收起日志库" @click="toggleCollapse">
                <el-icon><Fold /></el-icon>
              </el-button>
            </div>
          </div>

          <el-input v-model="treeFilter" placeholder="搜索日志名 / 备注" clearable size="small"
            prefix-icon="Search" @input="applyFilter" @keyup.enter="openFirstMatch" />

          <div class="lib-meta">
            共 {{ libFiles.length }} 个文件
            <template v-if="filterActive"> · 匹配 {{ matchedCount }} 个（回车打开第一个）</template>
          </div>

          <div class="lib-tree">
            <el-empty v-if="!logTree.length" description="还没有导入日志文件" :image-size="60" />
            <el-tree v-else ref="treeRef" :data="logTree" node-key="path" :props="treeProps"
              :filter-node-method="filterNode" :expand-on-click-node="false" highlight-current
              :indent="12" @node-click="onNodeClick">
              <template #default="{ data }">
                <span class="tree-node">
                  <el-icon class="node-icon">
                    <Folder v-if="data.type === 'dir'" /><Document v-else />
                  </el-icon>
                  <el-tooltip :content="data.path" placement="top-start" :show-after="500">
                    <span class="node-name" :class="{ missing: data.type === 'file' && !data.exists }">
                      {{ data.name }}
                    </span>
                  </el-tooltip>
                  <el-tag v-if="data.remark" size="small" effect="plain" type="warning" class="node-remark">
                    {{ data.remark }}
                  </el-tag>
                  <span v-if="data.type === 'dir'" class="node-meta">{{ data.file_count }} 个</span>
                  <span v-else class="node-meta">{{ data.exists ? data.size_human : '已失效' }}</span>
                  <span class="node-actions">
                    <el-tooltip content="备注" placement="top">
                      <el-icon @click.stop="openRemark(data)"><EditPen /></el-icon>
                    </el-tooltip>
                    <el-tooltip v-if="data.type === 'file'" content="从日志库移除" placement="top">
                      <el-icon @click.stop="removeFromLibrary(data)"><Delete /></el-icon>
                    </el-tooltip>
                  </span>
                </span>
              </template>
            </el-tree>
          </div>
        </aside>
        <div v-if="!libCollapsed" class="lib-resizer" title="拖动调整宽度" @mousedown="startResize"></div>
      </div>

      <!-- 右侧：日志查看器 -->
      <section class="log-viewer">
        <div class="toolbar">
          <el-input v-model="logPath" placeholder="输入日志文件路径..." class="path-input" @keyup.enter="openLog">
            <template #append><el-button @click="openLog">打开</el-button></template>
          </el-input>
          <el-button @click="addCurrentToLibrary" title="把当前路径加入日志库">加入日志库</el-button>
          <el-switch v-model="tailMode" active-text="实时" @change="toggleTail" />
          <el-input v-model="filterText" placeholder="关键词..." clearable class="filter-input" />
          <el-select v-model="filterLevel" clearable placeholder="级别" style="width: 100px">
            <el-option label="ERROR" value="error" /><el-option label="WARN" value="warn" /><el-option label="INFO" value="info" />
          </el-select>
          <el-input v-model="searchPattern" placeholder="正则搜索..." class="search-input" @keyup.enter="doSearch" />
          <el-button @click="doSearch">搜索</el-button>
          <el-button @click="showAggregate = true">多日志聚合</el-button>
        </div>

        <div class="logs-main" v-if="logTabs.length">
          <div class="log-tabs">
            <div v-for="(t, i) in logTabs" :key="i" :class="['log-tab', { active: activeTab === i }]" @click="switchTab(i)">
              {{ getFileName(t.path) }}
              <el-icon class="log-tab-close" @click.stop="closeLogTab(i)"><Close /></el-icon>
            </div>
          </div>
          <div class="log-content" ref="logContainer">
            <div v-if="searchResults.length">
              <h4>搜索结果 ({{ searchResults.length }})</h4>
              <div v-for="(r, i) in searchResults" :key="i" :class="['log-line', r.level]">
                <span class="line-num">{{ r.line_num }}</span><span>{{ r.text }}</span>
              </div>
            </div>
            <div v-else-if="logLines.length">
              <div v-for="(l, i) in filteredLines" :key="i" :class="['log-line', l.level]">
                <span class="line-num">{{ i + 1 }}</span><span>{{ l.text }}</span>
              </div>
            </div>
            <el-empty v-else description="输入路径并打开" />
          </div>
        </div>
        <el-empty v-else description="从左侧日志库选择文件，或输入路径打开" />
      </section>
    </div>

    <!-- 导入日志文件 -->
    <el-dialog v-model="importVisible" title="导入日志文件" width="620px">
      <p class="tip">
        每行一个路径：可以是日志文件，也可以是目录（会递归扫描其中的 .log / .txt / .out / .err 等日志文件，最多 200 个）。
      </p>
      <el-input v-model="importText" type="textarea" :rows="8"
        placeholder="/var/log/nginx/access.log&#10;/home/kamfu/myapp/logs" />
      <div style="margin-top: 8px">
        <el-button @click="openBrowse"><el-icon><FolderOpened /></el-icon> 通过文件夹树选择…</el-button>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importLoading" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 文件夹树选择 -->
    <el-dialog v-model="browseVisible" title="从文件夹树选择" width="720px">
      <div class="browse-toolbar">
        <el-input v-model="browsePathInput" placeholder="跳转到目录，如 /var/log" size="small"
          style="flex: 1" @keyup.enter="jumpBrowse" />
        <el-button size="small" @click="jumpBrowse">跳转</el-button>
        <el-button size="small" @click="jumpTo('~')">主目录</el-button>
        <el-button size="small" @click="jumpTo('/')">根目录</el-button>
        <el-button size="small" @click="jumpTo('/var/log')">/var/log</el-button>
        <el-checkbox v-model="browseLogsOnly" size="small" @change="reloadBrowse">只显示日志文件</el-checkbox>
      </div>
      <p class="tip">勾选目录 = 导入该目录下扫描到的日志文件；勾选文件 = 直接导入该文件。</p>
      <div class="browse-tree-box">
        <el-tree ref="browseTreeRef" :data="browseData" :props="browseProps" node-key="path"
          lazy :load="loadBrowseNode" show-checkbox check-strictly :expand-on-click-node="false"
          @check-change="collectBrowseSelected">
          <template #default="{ data }">
            <span class="browse-node">
              <el-icon class="node-icon"><Folder v-if="data.is_dir" /><Document v-else /></el-icon>
              <span>{{ data.name }}</span>
              <span v-if="data.size_human" class="node-meta">{{ data.size_human }}</span>
            </span>
          </template>
        </el-tree>
      </div>
      <template #footer>
        <span class="browse-count">已选 {{ browseSelected.length }} 项</span>
        <el-button @click="browseVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!browseSelected.length" @click="confirmBrowse">加入导入列表</el-button>
      </template>
    </el-dialog>

    <!-- 备注 -->
    <el-dialog v-model="remarkVisible" :title="`备注 — ${remarkTarget.name || ''}`" width="460px">
      <div class="tip remark-path">{{ remarkTarget.path }}</div>
      <el-input v-model="remarkText" type="textarea" :rows="3" maxlength="200" show-word-limit
        placeholder="例如：生产环境 Nginx 访问日志" />
      <template #footer>
        <el-button @click="clearRemark">清除备注</el-button>
        <el-button @click="remarkVisible = false">取消</el-button>
        <el-button type="primary" :loading="remarkLoading" @click="saveRemark">保存</el-button>
      </template>
    </el-dialog>

    <!-- 从日志库选择具体文件（聚合用，多选） -->
    <el-dialog v-model="pickVisible" title="选择日志文件（可多选）" width="760px">
      <el-input v-model="pickFilter" placeholder="搜索日志名 / 备注 / 路径" clearable size="small"
        prefix-icon="Search" style="margin-bottom: 8px" />
      <el-table ref="pickTableRef" :data="pickRows" size="small" max-height="420" row-key="path"
        @selection-change="onPickSelection">
        <el-table-column type="selection" width="46" :reserve-selection="true" />
        <el-table-column prop="name" label="文件" width="150" show-overflow-tooltip />
        <el-table-column label="备注" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="{ 'lib-empty-remark': !row.remark }">{{ row.remark || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="path" label="路径" min-width="240" show-overflow-tooltip />
        <el-table-column label="大小" width="90">
          <template #default="{ row }">
            <span :class="{ 'missing-text': !row.exists }">{{ row.exists ? row.size_human : '已失效' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <span class="browse-count">已选 {{ pickedFiles.length }} 个文件</span>
        <el-button @click="pickVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!pickedFiles.length" @click="confirmPick">确定</el-button>
      </template>
    </el-dialog>

    <!-- 多日志聚合 Dialog（可最大化） -->
    <el-dialog v-model="showAggregate" width="800px" :fullscreen="aggFullscreen">
      <template #header>
        <div class="agg-header">
          <span class="agg-title">多日志聚合</span>
          <el-button text size="small" :title="aggFullscreen ? '还原' : '最大化'"
            @click="aggFullscreen = !aggFullscreen">
            <el-icon><FullScreen v-if="!aggFullscreen" /><ScaleToOriginal v-else /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="agg-row">
        <el-input v-model="aggregatePaths" placeholder="多个日志路径，逗号分隔" style="flex: 1" />
        <el-button @click="openPickFiles">从日志库选择…</el-button>
      </div>
      <el-input v-model="aggregateKeywords" placeholder="过滤关键词，逗号分隔（可选）" class="agg-gap" />
      <el-radio-group v-model="aggregateMode" style="margin-bottom: 12px">
        <el-radio-button value="interleave">交错显示</el-radio-button>
        <el-radio-button value="timeline">时间线对齐</el-radio-button>
      </el-radio-group>
      <el-button type="primary" @click="doAggregate" :loading="aggLoading">加载</el-button>

      <div v-if="aggSources.length > 1" class="agg-legend">
        <span v-for="s in aggSources" :key="s" class="agg-legend-item">
          <span class="agg-dot" :style="{ background: colorOfSource(s) }"></span>
          <span :style="{ color: colorOfSource(s) }">{{ s }}</span>
        </span>
      </div>

      <div class="aggregate-result" :style="{ maxHeight: aggFullscreen ? 'calc(100vh - 250px)' : '400px' }">
        <div v-for="(l, i) in aggregateLines" :key="i" :class="['log-line', l.level, 'agg-line']"
          :style="{ borderLeftColor: colorOfSource(l.source) }">
          <span class="agg-source" :style="{ color: colorOfSource(l.source) }">{{ l.source }}</span>
          <span class="agg-text">{{ l.text }}</span>
        </div>
        <el-empty v-if="!aggregateLines.length" description="加载后这里显示聚合结果" :image-size="60" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { subscribeLogTail } from '../api/ws'

const logPath = ref(''); const logTabs = ref([]); const activeTab = ref(0)
const tailMode = ref(false); const filterText = ref(''); const filterLevel = ref('')
const searchPattern = ref(''); const searchResults = ref([])
const showAggregate = ref(false); const aggregatePaths = ref(''); const aggregateKeywords = ref('')
const aggregateMode = ref('interleave'); const aggregateLines = ref([]); const aggLoading = ref(false)
let tailUnsubs = {}

// 日志库
const logTree = ref([]); const libFiles = ref([]); const libLoading = ref(false)
const treeRef = ref(null); const treeFilter = ref('')
const treeProps = { children: 'children', label: 'name' }
const importVisible = ref(false); const importText = ref(''); const importLoading = ref(false)
const remarkVisible = ref(false); const remarkTarget = ref({}); const remarkText = ref(''); const remarkLoading = ref(false)
// 日志库面板：宽度 / 折叠
const logsBodyRef = ref(null)
const libWidth = ref(340)
const libCollapsed = ref(false)
const paneWidth = computed(() => libCollapsed.value ? 30 : libWidth.value)
const LS_WIDTH = 'dash.loglib.width'; const LS_COLLAPSED = 'dash.loglib.collapsed'
try {
  const w = parseInt(localStorage.getItem(LS_WIDTH) || '', 10)
  if (w >= 240) libWidth.value = w
  libCollapsed.value = localStorage.getItem(LS_COLLAPSED) === '1'
} catch (_) { /* localStorage 不可用时用默认值 */ }

function toggleCollapse() {
  libCollapsed.value = !libCollapsed.value
  try { localStorage.setItem(LS_COLLAPSED, libCollapsed.value ? '1' : '0') } catch (_) {}
}

function startResize(e) {
  e.preventDefault()
  const onMove = (ev) => {
    const rect = logsBodyRef.value?.getBoundingClientRect()
    if (!rect) return
    const max = Math.max(360, rect.width - 360)
    libWidth.value = Math.min(Math.max(Math.round(ev.clientX - rect.left), 240), max)
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    try { localStorage.setItem(LS_WIDTH, String(libWidth.value)) } catch (_) {}
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// 聚合：最大化 + 按来源文件着色（同一文件始终同一颜色）
const aggFullscreen = ref(false)
const AGG_COLORS = ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#7E57C2',
  '#26A69A', '#EC407A', '#8D6E63', '#5C6BC0', '#9CCC65']
const aggSources = computed(() => {
  const seen = []
  for (const l of aggregateLines.value) {
    const s = l.source || ''
    if (s && !seen.includes(s)) seen.push(s)
  }
  return seen
})
// 按“来源名排序后”的顺序取色：同一组文件多次加载颜色不变，且尽量互不相同
const aggSourceColors = computed(() => {
  const m = {}
  ;[...aggSources.value].sort().forEach((s, i) => { m[s] = AGG_COLORS[i % AGG_COLORS.length] })
  return m
})
function colorOfSource(s) {
  return aggSourceColors.value[s || ''] || 'var(--el-text-color-secondary)'
}

// 聚合：从日志库选择具体文件（多选）
const pickVisible = ref(false); const pickFilter = ref(''); const pickedFiles = ref([])
const pickTableRef = ref(null)
const pickRows = computed(() => {
  const q = pickFilter.value.trim().toLowerCase()
  if (!q) return libFiles.value
  return libFiles.value.filter(f => matchFile(f, q))
})

// 文件夹树选择
const browseVisible = ref(false); const browseData = ref([]); const browseTreeRef = ref(null)
const browsePathInput = ref('~'); const browseLogsOnly = ref(true); const browseSelected = ref([])
const browseProps = { label: 'name', children: 'children', isLeaf: 'isLeaf' }

const logLines = computed(() => logTabs.value[activeTab.value]?.lines || [])
const filteredLines = computed(() => {
  let lines = logLines.value
  if (filterText.value) { const q = filterText.value.toLowerCase(); lines = lines.filter(l => l.text.toLowerCase().includes(q)) }
  if (filterLevel.value) lines = lines.filter(l => l.level === filterLevel.value)
  return lines
})
const filterActive = computed(() => !!treeFilter.value.trim())
const matchedCount = computed(() => {
  const q = treeFilter.value.trim().toLowerCase()
  if (!q) return 0
  return libFiles.value.filter(f => matchFile(f, q)).length
})

function matchFile(f, q) {
  return (f.name || '').toLowerCase().includes(q)
    || (f.remark || '').toLowerCase().includes(q)
    || (f.path || '').toLowerCase().includes(q)
}

// ── 日志库操作 ──
async function loadLibrary() {
  libLoading.value = true
  try {
    const { data } = await api.get('/logs/library')
    logTree.value = data.tree || []
    libFiles.value = data.files || []
    await nextTick()
    logTree.value.forEach(n => {
      const node = treeRef.value?.getNode(n.path)
      if (node && !node.isLeaf) node.expand()
    })
    if (treeFilter.value) applyFilter()
  } catch (_) { ElMessage.error('日志库加载失败') }
  libLoading.value = false
}

function filterNode(value, data) {
  if (!value) return true
  const q = value.toLowerCase()
  if ((data.name || '').toLowerCase().includes(q)) return true
  if ((data.remark || '').toLowerCase().includes(q)) return true
  if (data.type === 'file' && (data.path || '').toLowerCase().includes(q)) return true
  return false
}

function applyFilter() { treeRef.value?.filter(treeFilter.value) }

function onNodeClick(data) {
  if (data.type === 'dir') return
  openPath(data.path)
}

function openFirstMatch() {
  const q = treeFilter.value.trim().toLowerCase()
  if (!q) return
  const hit = libFiles.value.find(f => matchFile(f, q))
  if (hit) openPath(hit.path)
  else ElMessage.warning('没有匹配的日志文件')
}

async function doImport() {
  const paths = importText.value.split('\n').map(s => s.trim()).filter(Boolean)
  if (!paths.length) return
  await importPaths(paths, true)
}

async function addCurrentToLibrary() {
  const p = logPath.value.trim() || logTabs.value[activeTab.value]?.path
  if (!p) { ElMessage.warning('请先输入或打开一个日志文件'); return }
  await importPaths([p], false)
  logPath.value = ''
}

async function importPaths(paths, closeDialog) {
  importLoading.value = true
  try {
    const { data } = await api.post('/logs/library', { paths })
    if (data.errors?.length) ElMessage.warning(data.errors.join('；'))
    if (data.added) ElMessage.success(`已导入 ${data.added} 个日志文件`)
    else if (!data.errors?.length) ElMessage.info('这些文件已经在日志库中')
    if (closeDialog) { importText.value = ''; importVisible.value = false }
    await loadLibrary()
  } catch (_) { ElMessage.error('导入失败') }
  importLoading.value = false
}

// ── 文件夹树选择 ──
function openBrowse() {
  browseVisible.value = true
  browseSelected.value = []
  jumpTo('~')
}

function jumpTo(p) {
  browsePathInput.value = p
  browseData.value = [{ name: p === '~' ? '主目录' : p, path: p, is_dir: true, isLeaf: false }]
  browseTreeRef.value?.setCheckedKeys([])
  browseSelected.value = []
}

function jumpBrowse() {
  const p = browsePathInput.value.trim() || '~'
  jumpTo(p)
}

function reloadBrowse() {
  const cur = browseData.value[0]?.path || '~'
  jumpTo(cur)
}

async function loadBrowseNode(node, resolve) {
  if (node.level === 0) { resolve([]); return }
  try {
    const { data } = await api.get('/logs/browse', {
      params: { path: node.data.path, logs_only: browseLogsOnly.value },
    })
    if (data.error) { ElMessage.warning(data.error); resolve([]); return }
    const items = (data.items || []).map(it => ({
      name: it.name, path: it.path, is_dir: it.is_dir, size_human: it.size_human,
      isLeaf: !it.is_dir,
    }))
    resolve(items)
  } catch (_) { resolve([]) }
}

function collectBrowseSelected() {
  const nodes = browseTreeRef.value?.getCheckedNodes(false) || []
  browseSelected.value = nodes.map(n => ({ path: n.path, is_dir: !!n.is_dir }))
}

function confirmBrowse() {
  collectBrowseSelected()
  const lines = importText.value.split('\n').map(s => s.trim()).filter(Boolean)
  for (const s of browseSelected.value) {
    if (!lines.includes(s.path)) lines.push(s.path)
  }
  importText.value = lines.join('\n')
  browseVisible.value = false
  ElMessage.success(`已加入 ${browseSelected.value.length} 个路径`)
}

async function removeFromLibrary(data) {
  try { await ElMessageBox.confirm(`从日志库移除？\n${data.path}`, '确认', { type: 'warning' }) }
  catch (_) { return }
  try {
    await api.delete('/logs/library', { data: { path: data.path } })
    ElMessage.success('已移除')
    await loadLibrary()
  } catch (_) { ElMessage.error('移除失败') }
}

function openRemark(data) {
  remarkTarget.value = { name: data.name, path: data.path, type: data.type }
  remarkText.value = data.remark || ''
  remarkVisible.value = true
}
async function saveRemark() {
  remarkLoading.value = true
  try {
    await api.post('/logs/remarks', { path: remarkTarget.value.path, remark: remarkText.value })
    remarkVisible.value = false
    await loadLibrary()
  } catch (_) { ElMessage.error('备注保存失败') }
  remarkLoading.value = false
}
async function clearRemark() { remarkText.value = ''; await saveRemark() }

// ── 日志查看 ──
async function openLog() {
  const path = logPath.value.trim(); if (!path) return
  await openPath(path)
  logPath.value = ''
}

async function openPath(path) {
  if (!path) return
  const ex = logTabs.value.findIndex(t => t.path === path)
  if (ex >= 0) { activeTab.value = ex; searchResults.value = []; return }
  try {
    const { data } = await api.get('/logs', { params: { path, offset: 0, limit: 500 } })
    if (data.error) { ElMessage.error(data.error); return }
    logTabs.value.push({ path, lines: data.lines || [] })
    activeTab.value = logTabs.value.length - 1
    searchResults.value = []
  } catch (_) { ElMessage.error('无法打开') }
}

function switchTab(i) { activeTab.value = i; searchResults.value = [] }
function closeLogTab(i) { const t = logTabs.value[i]; if (tailUnsubs[t.path]) { tailUnsubs[t.path](); delete tailUnsubs[t.path] } logTabs.value.splice(i, 1); if (activeTab.value >= logTabs.value.length) activeTab.value = Math.max(0, logTabs.value.length - 1) }
function toggleTail(v) { const t = logTabs.value[activeTab.value]; if (!t) return
  if (v) { tailUnsubs[t.path] = subscribeLogTail(t.path, (d) => { if (d.text) { t.lines.push(d); if (t.lines.length > 5000) t.lines.shift() } }) }
  else { if (tailUnsubs[t.path]) { tailUnsubs[t.path](); delete tailUnsubs[t.path] } }
}
async function doSearch() { const p = searchPattern.value.trim(); const t = logTabs.value[activeTab.value]; if (!p || !t) return
  try { const { data } = await api.get('/logs/search', { params: { path: t.path, pattern: p } }); searchResults.value = data.matches || [] } catch (_) {} }
function openPickFiles() {
  if (!libFiles.value.length) { ElMessage.warning('日志库还没有文件，请先导入'); return }
  pickVisible.value = true
  pickedFiles.value = []
  pickFilter.value = ''
  nextTick(() => {
    const current = new Set(aggregatePaths.value.split(',').map(s => s.trim()).filter(Boolean))
    pickTableRef.value?.clearSelection()
    pickRows.value.forEach(r => { if (current.has(r.path)) pickTableRef.value?.toggleRowSelection(r, true) })
  })
}

function onPickSelection(rows) { pickedFiles.value = rows || [] }

function confirmPick() {
  const rows = pickTableRef.value?.getSelectionRows?.() || pickedFiles.value
  const paths = (rows || []).map(r => r.path).filter(Boolean)
  if (!paths.length) return
  aggregatePaths.value = paths.join(',')
  pickedFiles.value = rows
  pickVisible.value = false
  ElMessage.success(`已选择 ${paths.length} 个日志文件`)
}
async function doAggregate() {
  aggLoading.value = true
  const ep = aggregateMode.value === 'timeline' ? '/logs/timeline' : '/logs/aggregate'
  try { const { data } = await api.get(ep, { params: { paths: aggregatePaths.value, keywords: aggregateKeywords.value, limit: 500 } })
    aggregateLines.value = data.lines || [] } catch (_) { ElMessage.error('加载失败') }
  aggLoading.value = false
}
function getFileName(p) { return p.split('/').pop() || p }

onMounted(() => { loadLibrary() })
onUnmounted(() => { for (const u of Object.values(tailUnsubs)) if (typeof u === 'function') u() })
</script>

<style scoped>
.logs-view { padding: 20px; height: 100vh; display: flex; flex-direction: column; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; flex-shrink: 0; }
.logs-body { flex: 1; display: flex; gap: 14px; overflow: hidden; }

/* 左侧日志库（可折叠 / 可拖拽调宽） */
.lib-pane { position: relative; flex-shrink: 0; display: flex; min-width: 0; }
.log-library {
  flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px;
  padding: 10px; border: 1px solid var(--el-border-color-light); border-radius: var(--radius-md, 8px);
  background: var(--el-bg-color-page); overflow: hidden;
}
.lib-resizer {
  position: absolute; top: 0; right: -4px; width: 8px; height: 100%;
  cursor: col-resize; z-index: 3; border-radius: 4px;
}
.lib-resizer:hover { background: var(--el-color-primary-light-5); }
.lib-collapsed {
  width: 100%; display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 12px;
  cursor: pointer; color: var(--el-text-color-secondary);
  border: 1px solid var(--el-border-color-light); border-radius: var(--radius-md, 8px);
  background: var(--el-bg-color-page);
}
.lib-collapsed:hover { color: var(--el-color-primary); border-color: var(--el-color-primary-light-5); }
.lib-collapsed-text { writing-mode: vertical-rl; font-size: 12px; letter-spacing: 2px; }
.lib-head { display: flex; align-items: center; justify-content: space-between; }
.lib-title { font-size: 14px; font-weight: 600; }
.lib-head-actions { display: flex; gap: 6px; }
.lib-meta { font-size: 12px; color: var(--el-text-color-secondary); }
/* 纵向滚动，横向不出现滚动条（深层节点溢出时由 sticky 操作区兜底显示） */
.lib-tree { flex: 1; overflow-y: auto; overflow-x: hidden; }
/* 层级越深，行内容可用宽度越小：名称可压缩并省略，操作按钮保持固定宽度，
   sticky 兜底让它们始终贴在行右侧可见区域内，不会被挤压到视口外 */
.tree-node { display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; font-size: 13px; }
.node-icon { flex: 0 0 auto; font-size: 14px; color: var(--el-text-color-secondary); }
.node-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-name.missing { color: var(--el-color-danger); text-decoration: line-through; }
.node-remark { flex: 0 1 auto; min-width: 0; max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-meta { flex: 0 0 auto; margin-left: auto; font-size: 11px; color: var(--el-text-color-disabled); }
.node-actions {
  position: sticky; right: 0; flex: 0 0 auto; margin-left: 4px; padding-left: 4px;
  display: flex; gap: 6px; opacity: 0; color: var(--el-text-color-secondary);
}
.tree-node:hover .node-actions { opacity: 1; }

/* 右侧查看器 */
.log-viewer { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; flex-shrink: 0; }
.path-input { flex: 1; min-width: 200px; }
.filter-input { width: 180px; }
.search-input { width: 180px; }
.logs-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.log-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--el-border-color-light); flex-shrink: 0; }
.log-tab { display: flex; align-items: center; gap: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; border-radius: 6px 6px 0 0; color: var(--el-text-color-secondary); }
.log-tab.active { color: var(--el-text-color-primary); border-color: var(--el-border-color-light); border-bottom-color: transparent; background: var(--el-bg-color); }
.log-tab-close { opacity: 0; font-size: 12px; } .log-tab:hover .log-tab-close { opacity: 0.6; }
.log-content { flex: 1; overflow-y: auto; background: var(--el-bg-color); padding: 8px 12px; font-family: monospace; font-size: 13px; line-height: 1.6; }
.log-line { display: flex; gap: 12px; border-bottom: 1px solid var(--el-border-color-extra-light); }
.log-line.error { background: rgba(245,108,108,0.08); color: #f56c6c; }
.log-line.warn { background: rgba(230,162,60,0.06); color: #e6a23c; }
.log-line.info { color: #d96b1e; }
.line-num { width: 50px; flex-shrink: 0; color: var(--el-text-color-disabled); text-align: right; user-select: none; }
.tip { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.remark-path { word-break: break-all; }

/* 多日志聚合：路径输入与选择按钮同一行 */
.agg-row { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.agg-gap { margin-bottom: 12px; }
.agg-header { display: flex; align-items: center; gap: 8px; padding-right: 26px; }
.agg-title { font-size: 16px; font-weight: 600; }
.aggregate-result {
  margin-top: 12px; overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px;
}
.agg-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; font-size: 12px; }
.agg-legend-item { display: flex; align-items: center; gap: 5px; }
.agg-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }
.agg-line { border-left: 3px solid transparent; padding-left: 8px; align-items: flex-start; }
.agg-source { flex-shrink: 0; min-width: 120px; font-weight: 600; }
.agg-text { min-width: 0; white-space: pre-wrap; word-break: break-word; }
.lib-empty-remark { color: var(--el-text-color-disabled); }
.missing-text { color: var(--el-text-color-disabled); text-decoration: line-through; }

/* 文件夹树选择 */
.browse-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.browse-tree-box {
  max-height: 380px; overflow: auto; padding: 6px;
  border: 1px solid var(--el-border-color-light); border-radius: var(--radius-md, 8px);
}
.browse-node { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.browse-count { margin-right: auto; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
