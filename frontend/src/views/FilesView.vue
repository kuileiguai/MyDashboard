<template>
  <div class="files-view">
    <h2 class="page-title">文件管理器</h2>
    <div class="toolbar">
      <el-input v-model="currentPath" @keyup.enter="navigateTo" placeholder="输入路径..." class="path-input">
        <template #prepend><el-icon><FolderOpened /></el-icon></template>
      </el-input>
      <el-button @click="goUp" :disabled="currentPath === '/'"><el-icon><Top /></el-icon> 上级</el-button>
      <el-button @click="fetchDir"><el-icon><Refresh /></el-icon> 刷新</el-button>
      <el-button type="primary" @click="showCreateDialog = true"><el-icon><Plus /></el-icon> 新建</el-button>
      <el-button @click="showTemplates = true"><el-icon><DocumentCopy /></el-icon> 模板</el-button>
      <el-switch v-model="showHidden" active-text="显示隐藏" size="small" @change="fetchDir" />
    </div>

    <el-breadcrumb class="breadcrumb" separator="/">
      <el-breadcrumb-item v-for="(b, i) in breadcrumbs" :key="i" @click="navigateTo(b.path)">{{ b.name }}</el-breadcrumb-item>
    </el-breadcrumb>

    <div class="files-main">
      <div class="bookmarks-panel">
        <div class="panel-header">快捷位置</div>
        <div v-for="bm in bookmarks" :key="bm.id" class="bookmark-item" @click="navigateTo(bm.path)">
          <el-icon><Star /></el-icon> {{ bm.name }}
          <el-icon class="bm-delete" @click.stop="deleteBookmark(bm.id)"><Close /></el-icon>
        </div>
        <el-button size="small" @click="addBookmark" class="add-bm-btn"><el-icon><Plus /></el-icon> 添加当前位置</el-button>

        <!-- 文件夹窗口入口 — 紧凑概要 -->
        <div class="panel-header" style="margin-top: 16px">
          文件夹窗口
          <el-badge :value="nautilusWindows.length" :hidden="!nautilusWindows.length" style="margin-left:6px" />
        </div>
        <div class="bookmark-item" @click="showFolderManager = true; fetchNautilus()" style="justify-content:space-between">
          <span style="font-size:11px;color:var(--el-text-color-secondary)">
            {{ nautilusWindows.length ? `${nautilusWindows.length} 个窗口` : '点击管理' }}
          </span>
          <el-icon :size="12"><ArrowRight /></el-icon>
        </div>

        <div class="panel-header" style="margin-top: 16px">最近文件</div>
        <div v-for="f in recentFiles" :key="f.id" class="bookmark-item" @click="openRecentFile(f)">
          <el-icon><Document /></el-icon> {{ f.path.split('/').pop() }}
        </div>
      </div>

      <div class="files-content">
        <el-table :data="filteredItems" stripe v-loading="loading" @row-dblclick="openItem">
          <el-table-column label="名称" min-width="280">
            <template #default="{ row }">
              <el-icon :size="18"><Folder v-if="row.is_dir" /><Document v-else /></el-icon>
              <span :class="['file-name', { 'is-dir': row.is_dir }]">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="120" :formatter="formatSize" />
          <el-table-column label="修改时间" width="180" :formatter="formatTime" />
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button size="small" @click="openInTerminal(row)" :disabled="!row.is_dir">终端打开</el-button>
              <el-button size="small" @click="copyPath(row)">复制路径</el-button>
              <el-button size="small" type="danger" @click="deleteItem(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- ====== 文件夹窗口管理弹窗 ====== -->
    <el-dialog v-model="showFolderManager" title="文件夹窗口管理" width="800px">
      <div style="margin-bottom:12px;display:flex;gap:12px;align-items:center">
        <el-button size="small" @click="fetchNautilus" :loading="nautilusLoaded === false">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-input v-model="folderFilter" placeholder="搜索窗口..." clearable size="small" style="width:200px" prefix-icon="Search" />
        <span style="font-size:12px;color:var(--el-text-color-secondary)">
          {{ filteredFolders.length }} / {{ nautilusWindows.length }} 个窗口
        </span>
        <el-button v-if="filesDepMissing" size="small" type="primary" @click="filesInstallDeps" :loading="filesInstalling">
          安装依赖
        </el-button>
      </div>
      <el-empty v-if="!nautilusWindows.length && nautilusLoaded" description="未检测到打开的文件夹窗口" />
      <div v-else class="folder-scroll">
        <div v-for="w in filteredFolders" :key="w.id" class="folder-card">
          <div class="folder-card-top">
            <!-- 别名或标题 -->
            <span v-if="folderAliasEditId !== w.id" style="display:flex;align-items:center;gap:6px;flex:1;min-width:0">
              <el-tag v-if="folderAliases[w.id]" type="primary" effect="dark" size="small">{{ folderAliases[w.id] }}</el-tag>
              <strong v-else style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ w.title }}</strong>
              <span v-if="folderAliases[w.id]" style="font-size:11px;color:var(--el-text-color-disabled);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">({{ w.title }})</span>
              <el-icon :size="12" class="folder-alias-btn" @click="startFolderAlias(w)" title="设置别称"><EditPen /></el-icon>
            </span>
            <span v-else style="display:flex;gap:6px;flex:1;align-items:center">
              <el-input v-model="folderAliasText" placeholder="如：项目文档" size="small" style="flex:1;max-width:200px"
                @keyup.enter="saveFolderAlias(w.id)" @keyup.escape="folderAliasEditId = null" />
              <el-button size="small" type="primary" @click="saveFolderAlias(w.id)">保存</el-button>
              <el-button size="small" @click="folderAliasEditId = null">取消</el-button>
            </span>
            <!-- 路径存在检测 -->
            <el-tag v-if="folderPathChecks[w.id] !== undefined" size="small"
              :type="folderPathChecks[w.id] ? 'success' : 'danger'" effect="plain" style="flex-shrink:0">
              {{ folderPathChecks[w.id] ? '路径存在' : '路径不存在' }}
            </el-tag>
          </div>
          <div class="folder-card-path">
            <el-icon :size="12"><FolderOpened /></el-icon>
            <code>{{ w.path || '(无法读取路径)' }}</code>
          </div>
          <div class="folder-card-actions">
            <el-button size="small" type="primary" @click="focusNautilus(w.id)">聚焦窗口</el-button>
            <el-button size="small" @click="addBookmarkFromFolder(w)"><el-icon><Star /></el-icon> 加书签</el-button>
            <el-button size="small" @click="openInVscode(w)" :disabled="!w.path">
              <el-icon><Edit /></el-icon> VSCode
            </el-button>
            <el-button size="small" type="danger" @click="closeNautilus(w.id)">关闭窗口</el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- Create Dialog -->
    <el-dialog v-model="showCreateDialog" title="新建" width="400px">
      <el-input v-model="newItemName" placeholder="文件/文件夹名称" />
      <div style="margin-top: 12px">
        <el-radio v-model="newItemType" value="file">文件</el-radio>
        <el-radio v-model="newItemType" value="dir">文件夹</el-radio>
      </div>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createItem">创建</el-button>
      </template>
    </el-dialog>

    <!-- Templates Dialog -->
    <el-dialog v-model="showTemplates" title="文件模板" width="550px">
      <el-table :data="templates" size="small">
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="extension" label="扩展名" width="80" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="useTemplate(row)">使用</el-button>
          </template>
        </el-table-column>
        <el-table-column label="预览" show-overflow-tooltip>
          <template #default="{ row }">{{ row.content?.substring(0, 80) }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, ArrowRight } from '@element-plus/icons-vue'
import api from '../api'
import { useRouter } from 'vue-router'
import { useTerminalStore } from '../stores/terminal'

const router = useRouter()
const terminalStore = useTerminalStore()
const currentPath = ref('~')
const items = ref([]); const breadcrumbs = ref([]); const bookmarks = ref([]); const recentFiles = ref([])
const loading = ref(false); const showCreateDialog = ref(false); const newItemName = ref(''); const newItemType = ref('file')
const templates = ref([]); const showTemplates = ref(false)
const showHidden = ref(false); const showFolderManager = ref(false)

// ── 文件夹窗口管理 ──
const nautilusWindows = ref([]); const nautilusLoaded = ref(false)
const filesDepMissing = ref(false); const filesInstalling = ref(false)
const folderFilter = ref('')
const folderAliases = ref({})
const folderAliasEditId = ref(null); const folderAliasText = ref('')
const folderPathChecks = ref({})

const filteredFolders = computed(() => {
  if (!folderFilter.value.trim()) return nautilusWindows.value
  const q = folderFilter.value.toLowerCase()
  return nautilusWindows.value.filter(w => {
    const alias = (folderAliases.value[w.id] || '').toLowerCase()
    const title = (w.title || '').toLowerCase()
    const path = (w.path || '').toLowerCase()
    return alias.includes(q) || title.includes(q) || path.includes(q)
  })
})

async function fetchNautilus() {
  nautilusLoaded.value = false; filesDepMissing.value = false
  try {
    const [res, depRes, aliasRes] = await Promise.all([
      api.get('/files/nautilus-windows'),
      api.get('/system/dependencies/missing'),
      api.get('/terminal/external/aliases'),  // 复用终端别名存储
    ])
    const wins = res.data || []
    folderAliases.value = aliasRes.data || {}
    nautilusWindows.value = wins
    nautilusLoaded.value = true
    if (!wins.length && (depRes.data?.missing || []).includes('wmctrl')) {
      filesDepMissing.value = true
    }
    // 异步检测每个窗口路径是否存在
    for (const w of wins) {
      if (w.path) {
        checkPathExists(w.id, w.path)
      }
    }
  } catch (_) { nautilusLoaded.value = true }
}

async function checkPathExists(winId, path) {
  try {
    const { data } = await api.get('/files/path-exists', { params: { path } })
    folderPathChecks.value[winId] = data.exists
  } catch (_) {}
}

async function focusNautilus(id) { try { await api.post(`/files/nautilus-windows/${id}/focus`) } catch (_) {} }
async function closeNautilus(id) {
  try { await ElMessageBox.confirm('确认关闭?', '确认', { type: 'warning' })
    await api.post(`/files/nautilus-windows/${id}/close`); ElMessage.success('已关闭')
    await new Promise(r => setTimeout(r, 500)); await fetchNautilus() } catch (_) {}
}

function startFolderAlias(w) {
  folderAliasEditId.value = w.id
  folderAliasText.value = folderAliases.value[w.id] || ''
}
async function saveFolderAlias(winId) {
  const alias = folderAliasText.value.trim()
  try {
    await api.post('/terminal/external/aliases', { win_id: winId, alias })
    folderAliases.value[winId] = alias || undefined
    folderAliasEditId.value = null; folderAliasText.value = ''
  } catch (_) { ElMessage.error('保存失败') }
}

async function addBookmarkFromFolder(w) {
  const name = folderAliases.value[w.id] || w.title
  const path = w.path || ''
  if (!path) { ElMessage.warning('无法获取路径'); return }
  try {
    await api.post('/files/bookmarks', null, { params: { name, path } })
    ElMessage.success('已添加书签'); fetchBookmarks()
  } catch (_) { ElMessage.error('添加失败') }
}

async function openInVscode(w) {
  if (!w.path) return
  try {
    const { data } = await api.post('/files/open-in-vscode', null, { params: { path: w.path } })
    if (data.ok) ElMessage.success('已在 VSCode 中打开')
    else ElMessage.error(data.error || '打开失败')
  } catch (_) { ElMessage.error('请求失败') }
}

async function filesInstallDeps() {
  filesInstalling.value = true
  try {
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true')
    if (data.ok) { ElMessage.success(data.message); filesDepMissing.value = false; fetchNautilus() }
    else ElMessage.error(data.message || '安装失败')
  } catch (_) { ElMessage.error('安装请求失败') }
  filesInstalling.value = false
}

// ── 文件操作 ──
async function fetchDir() {
  loading.value = true
  try { const { data } = await api.get('/files', { params: { path: currentPath.value } })
    items.value = data.items || []; breadcrumbs.value = data.breadcrumbs || []; currentPath.value = data.current
  } catch (_) { ElMessage.error('无法访问') } loading.value = false
}
async function fetchBookmarks() { try { const { data } = await api.get('/files/bookmarks'); bookmarks.value = data } catch (_) {} }
async function fetchRecent() { try { const { data } = await api.get('/files/recent'); recentFiles.value = data } catch (_) {} }
async function fetchTemplates() { try { const { data } = await api.get('/files/templates'); templates.value = data } catch (_) {} }

function navigateTo(p) { currentPath.value = p; fetchDir(); try { api.post('/files/recent', null, { params: { path: p } }) } catch (_) {} }
function goUp() { if (currentPath.value !== '/') { currentPath.value = currentPath.value.substring(0, currentPath.value.lastIndexOf('/')) || '/'; fetchDir() } }
function openItem(row) { if (row.is_dir) navigateTo(row.path) }
function openRecentFile(f) { currentPath.value = f.path.split('/').slice(0, -1).join('/') || '/'; fetchDir() }

async function deleteItem(row) {
  try { await ElMessageBox.confirm(`确认删除 ${row.name}?`, '确认', { type: 'warning' })
    await api.delete('/files', { data: { path: row.path, confirm: true } }); ElMessage.success('已删除'); fetchDir() } catch (_) {}
}
function copyPath(row) { navigator.clipboard.writeText(row.path).then(() => ElMessage.success('已复制')) }
async function openInTerminal(row) {
  if (!row.is_dir) return
  try { await terminalStore.createTerminal(row.name, row.path); router.push('/terminal') } catch (_) {}
}
async function createItem() {
  if (!newItemName.value.trim()) return
  const full = (currentPath.value === '/' ? '' : currentPath.value) + '/' + newItemName.value.trim()
  try { if (newItemType.value === 'dir') await api.post('/files/mkdir', { path: full })
    else await api.post('/files/touch', { path: full })
    ElMessage.success('已创建'); showCreateDialog.value = false; newItemName.value = ''; fetchDir() } catch (_) { ElMessage.error('创建失败') }
}
async function addBookmark() {
  try { await api.post('/files/bookmarks', null, { params: { name: currentPath.value.split('/').pop() || currentPath.value, path: currentPath.value } })
    fetchBookmarks(); ElMessage.success('已添加') } catch (_) {}
}
async function deleteBookmark(id) { try { await api.delete(`/files/bookmarks/${id}`); fetchBookmarks() } catch (_) {} }
async function useTemplate(row) {
  try { await api.post('/files/touch', { path: (currentPath.value === '/' ? '' : currentPath.value) + '/new' + row.extension })
    ElMessage.success('模板已创建'); showTemplates.value = false; fetchDir() } catch (_) { ElMessage.error('创建失败') }
}

function formatSize(r) { if (r.is_dir) return '-'; const s = r.size; if (s < 1024) return s + ' B'; if (s < 1048576) return (s / 1024).toFixed(1) + ' KB'; return (s / 1048576).toFixed(1) + ' MB' }
function formatTime(r) { if (!r.mtime) return '-'; return new Date(r.mtime * 1000).toLocaleString() }

const filteredItems = computed(() => showHidden.value ? items.value : items.value.filter(f => !f.name.startsWith('.')))

onMounted(() => { fetchDir(); fetchBookmarks(); fetchRecent(); fetchTemplates(); fetchNautilus() })
</script>

<style scoped>
.files-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.path-input { flex: 1; min-width: 200px; }
.breadcrumb { margin-bottom: 12px; cursor: pointer; }
.files-main { display: flex; gap: 16px; }
.bookmarks-panel { width: 200px; flex-shrink: 0; border: 1px solid var(--el-border-color-light); border-radius: var(--radius-md); padding: 12px; background: var(--el-bg-color-overlay); }
.panel-header { font-weight: 600; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--el-border-color-lighter); display:flex; align-items:center }
.bookmark-item { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px; }
.bookmark-item:hover { background: var(--el-fill-color-light); }
.bm-delete { margin-left: auto; opacity: 0; font-size: 12px; }
.bookmark-item:hover .bm-delete { opacity: 1; }
.add-bm-btn { margin-top: 8px; width: 100%; }
.files-content { flex: 1; min-width: 0; }
.file-name { margin-left: 8px; }
.file-name.is-dir { color: var(--el-color-primary); font-weight: 500; }

/* 文件夹窗口管理弹窗 */
.folder-scroll { max-height: 55vh; overflow-y: auto; padding-right: 4px }
.folder-card { border:1px solid var(--el-border-color-light); border-radius:var(--radius-md); padding:12px; margin-bottom:8px }
.folder-card-top { display:flex; align-items:center; gap:8px; margin-bottom:6px }
.folder-card-path { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--el-text-color-secondary); margin-bottom:8px }
.folder-card-path code { font-size:12px; background:var(--el-fill-color-light); padding:2px 6px; border-radius:4px }
.folder-card-actions { display:flex; gap:6px }
.folder-alias-btn { cursor:pointer; opacity:0.4; flex-shrink:0 }
.folder-alias-btn:hover { opacity:1; color:var(--el-color-primary) }
</style>
