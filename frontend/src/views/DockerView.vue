<template>
  <div class="docker-view">
    <h2 class="page-title">Docker 管理</h2>
    <p class="module-purpose">查看容器与镜像状态，管理 Compose 项目并检查资源占用。</p>
    <!-- Docker 状态横幅 -->
    <div v-if="available === false" class="docker-warn">
      <el-alert type="error" :closable="false" show-icon>
        <template #title>Docker 不可用：{{ availError || '无法访问 Docker daemon' }}</template>
        <pre v-if="availHint" class="hint-pre">{{ availHint }}</pre>
      </el-alert>
    </div>
    <div v-else-if="available === true" class="docker-ok">
      <el-alert type="success" :closable="false" show-icon
        :title="`Docker 已就绪 · Server v${sysInfo.version} · 容器 ${sysInfo.containers} · 镜像 ${sysInfo.images}`" />
    </div>

    <el-tabs v-model="tab" type="border-card" @tab-change="onTab" :class="{ 'module-tabs': true, 'is-switching': tabSwitching }">
      <!-- 概览 -->
      <el-tab-pane label="概览" name="overview">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="版本">{{ sysInfo.version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Docker 主机">{{ sysInfo.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="容器数">{{ sysInfo.containers ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="镜像数">{{ sysInfo.images ?? '-' }}</el-descriptions-item>
        </el-descriptions>
        <div class="df-box">
          <h4>磁盘占用 (docker system df)</h4>
          <pre class="df-pre">{{ dfRaw || '加载中…' }}</pre>
          <el-button type="danger" size="small" @click="pruneAll">🧹 一键清理 (system prune -a)</el-button>
        </div>
      </el-tab-pane>

      <!-- 容器 -->
      <el-tab-pane label="容器" name="containers">
        <div class="toolbar">
          <el-radio-group v-model="showAll" size="small" @change="fetchContainers">
            <el-radio-button :value="false">运行中</el-radio-button>
            <el-radio-button :value="true">全部</el-radio-button>
          </el-radio-group>
          <el-button size="small" @click="fetchContainers"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <el-button size="small" @click="fetchStats">📊 资源占用</el-button>
        </div>
        <el-table :data="containers" size="small" max-height="440">
          <el-table-column prop="ID" label="ID" width="100">
            <template #default="{ row }">{{ shortId(row.ID) }}</template>
          </el-table-column>
          <el-table-column prop="Names" label="名称" show-overflow-tooltip />
          <el-table-column prop="Image" label="镜像" show-overflow-tooltip />
          <el-table-column prop="Status" label="状态" show-overflow-tooltip />
          <el-table-column prop="Ports" label="端口" show-overflow-tooltip />
          <el-table-column label="操作" width="330" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="success" @click="containerOp(row, 'start')" :disabled="running(row)">启动</el-button>
              <el-button size="small" text type="warning" @click="containerOp(row, 'stop')" :disabled="!running(row)">停止</el-button>
              <el-button size="small" text type="primary" @click="containerOp(row, 'restart')">重启</el-button>
              <el-button size="small" text @click="openLogs(row)">日志</el-button>
              <el-button size="small" text type="danger" @click="containerOp(row, 'rm', true)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 镜像 -->
      <el-tab-pane label="镜像" name="images">
        <div class="toolbar">
          <el-input v-model="pullName" placeholder="镜像名:tag，如 nginx:latest" size="small" style="width: 260px" />
          <el-button size="small" type="primary" @click="pullImage">拉取</el-button>
          <el-button size="small" @click="fetchImages"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <el-button size="small" @click="pruneImages">清理悬空镜像</el-button>
          <el-button size="small" type="success" :disabled="!selectedRows.length" @click="openSave(selectedRows)">
            💾 保存为文件<template v-if="selectedRows.length"> ({{ selectedRows.length }})</template>
          </el-button>
        </div>
        <el-table :data="images" size="small" max-height="440" @selection-change="onImgSelect">
          <el-table-column type="selection" width="42" />
          <el-table-column prop="Repository" label="仓库" show-overflow-tooltip />
          <el-table-column prop="Tag" label="标签" width="120" />
          <el-table-column prop="ID" label="ID" width="110">
            <template #default="{ row }">{{ shortId(row.ID) }}</template>
          </el-table-column>
          <el-table-column prop="Size" label="大小" width="100" />
          <el-table-column prop="CreatedSince" label="创建" width="110" />
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openSave([row])">保存</el-button>
              <el-button size="small" text type="danger" @click="imageOp(row, 'rmi')">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Compose -->
      <el-tab-pane label="Compose" name="compose">
        <div class="toolbar">
          <el-input v-model="composeBase" placeholder="扫描目录（默认 ~），如 /mnt/项目数据" size="small"
            style="width: 300px" @keyup.enter="scanCompose" />
          <el-button size="small" type="primary" @click="scanCompose" :loading="composeLoading">扫描</el-button>
          <el-button size="small" @click="refreshCompose" :loading="composeLoading"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <span class="tip">
            已记录 {{ composeProjects.length }} 个 · 每 10 分钟自动更新
            <template v-if="composeUpdatedAt"> · 上次更新 {{ composeUpdatedAt }}</template>
          </span>
        </div>
        <el-table :data="composeProjects" size="small" max-height="440" v-loading="composeLoading">
          <el-table-column prop="name" label="项目" width="140" show-overflow-tooltip />
          <el-table-column label="路径" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <el-link type="primary" :disabled="!row.dir_exists" @click="openFolder(row.path)">
                <el-icon><FolderOpened /></el-icon> {{ row.path }}
              </el-link>
            </template>
          </el-table-column>
          <el-table-column label="compose 文件" width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="{ 'missing-text': !row.exists }">{{ baseName(row.compose_file) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.exists ? 'success' : 'danger'" size="small" effect="plain">
                {{ row.exists ? '正常' : '已失效' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="380" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="success" :disabled="!row.exists" @click="composeOp(row, 'up')">up -d</el-button>
              <el-button size="small" text type="warning" :disabled="!row.exists" @click="composeOp(row, 'down')">down</el-button>
              <el-button size="small" text type="primary" :disabled="!row.exists" @click="composeOp(row, 'restart')">restart</el-button>
              <el-button size="small" text :disabled="!row.exists" @click="composeOp(row, 'ps')">ps</el-button>
              <el-button size="small" text :disabled="!row.exists" @click="openComposeFile(row)">查看/编辑</el-button>
              <el-button size="small" text type="danger" @click="forgetCompose(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 卷 -->
      <el-tab-pane label="卷" name="volumes">
        <div class="toolbar">
          <el-input v-model="volName" placeholder="卷名称" size="small" style="width: 200px" />
          <el-button size="small" type="primary" @click="volumeOp('create')">创建</el-button>
          <el-button size="small" @click="fetchVolumes"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
        <el-table :data="volumes" size="small" max-height="440">
          <el-table-column prop="Name" label="名称" />
          <el-table-column prop="Driver" label="驱动" width="120" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="danger" @click="volumeOp('rm', row.Name)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 网络 -->
      <el-tab-pane label="网络" name="networks">
        <div class="toolbar">
          <el-input v-model="netName" placeholder="网络名称" size="small" style="width: 200px" />
          <el-button size="small" type="primary" @click="networkOp('create')">创建</el-button>
          <el-button size="small" @click="fetchNetworks"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
        <el-table :data="networks" size="small" max-height="440">
          <el-table-column prop="Name" label="名称" />
          <el-table-column prop="Driver" label="驱动" width="140" />
          <el-table-column prop="Scope" label="作用域" width="100" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="danger" @click="networkOp('rm', row.Name)" :disabled="row.Name === 'bridge' || row.Name === 'host' || row.Name === 'none'">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 容器日志 -->
    <el-dialog v-model="logsVisible" title="容器日志" width="760px" top="6vh">
      <pre class="logs-pre">{{ logsText || '（无日志）' }}</pre>
    </el-dialog>

    <!-- 资源占用 -->
    <el-dialog v-model="statsVisible" title="容器资源占用 (docker stats)" width="760px" top="6vh">
      <el-table :data="statsRows" size="small" max-height="420">
        <el-table-column prop="Name" label="名称" />
        <el-table-column prop="CPUPerc" label="CPU%" width="90" />
        <el-table-column prop="MemUsage" label="内存" width="140" />
        <el-table-column prop="MemPerc" label="内存%" width="90" />
        <el-table-column prop="NetIO" label="网络" width="140" />
      </el-table>
    </el-dialog>

    <!-- 镜像保存为文件 -->
    <el-dialog v-model="saveVisible" title="保存镜像到文件 (docker save)" width="640px" top="6vh">
      <el-form label-width="92px" size="small">
        <el-form-item label="目标镜像">
          <div class="save-targets">
            <el-tag v-for="t in saveForm.images" :key="t" size="small" type="info">{{ t }}</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="保存目录">
          <div class="dir-row">
            <el-input v-model="saveForm.output_dir" placeholder="如 /home/user/docker-images（不存在则自动创建）" />
            <el-button @click="openDirPicker">浏览…</el-button>
          </div>
        </el-form-item>
        <el-form-item label="文件名">
          <el-input v-model="saveForm.filename" placeholder="留空自动按镜像名生成" />
        </el-form-item>
        <el-form-item label="gzip 压缩">
          <el-switch v-model="saveForm.compress" />
          <span class="tip">开启后导出为 .tar.gz，体积更小但耗时更长</span>
        </el-form-item>
      </el-form>
      <el-alert v-if="!saveForm.images.length" type="warning" :closable="false" show-icon title="请先选择镜像" />
      <div v-if="saveResult" class="save-result">
        已保存：<code>{{ saveResult.path }}</code> · {{ saveResult.size_human }}
      </div>
      <template #footer>
        <el-button @click="saveVisible = false">关闭</el-button>
        <el-button v-if="saveResult" @click="openFolder(saveResult.path)">打开所在目录</el-button>
        <el-button type="primary" :loading="saving" @click="doSave">
          {{ saving ? `保存中 ${saveElapsed}s` : '开始保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 目录选择 -->
    <el-dialog v-model="dirVisible" title="选择保存目录" width="560px" top="8vh" append-to-body>
      <div class="dir-nav">
        <el-button v-for="b in dirBreadcrumbs" :key="b.path" size="small" text @click="loadDirs(b.path)">
          {{ b.name }} /
        </el-button>
      </div>
      <div class="dir-list">
        <div v-for="d in dirItems" :key="d.path" class="dir-item">
          <span class="dir-name" @click="loadDirs(d.path)">📁 {{ d.name }}</span>
          <el-button size="small" text type="primary" @click="pickDir(d.path)">选择</el-button>
        </div>
        <div v-if="!dirItems.length" class="dir-empty">（无子目录）</div>
      </div>
      <template #footer>
        <el-button @click="dirVisible = false">取消</el-button>
        <el-button type="primary" @click="pickDir(dirCurrent)">选择当前目录</el-button>
      </template>
    </el-dialog>

    <!-- compose 文件查看 / 编辑 -->
    <el-dialog v-model="composeFileVisible" :title="`compose 文件 · ${composeFileForm.name}`" width="880px" top="5vh">
      <div class="compose-file-bar">
        <code>{{ composeFileForm.path }}</code>
        <span class="tip">{{ composeFileInfo }}</span>
        <el-radio-group v-model="codeMode" size="small">
          <el-radio-button value="view">查看</el-radio-button>
          <el-radio-button value="edit">编辑</el-radio-button>
        </el-radio-group>
        <el-button size="small" text type="primary" @click="openFolder(composeFileForm.dir_path)">打开所在目录</el-button>
      </div>
      <div class="code-box" v-loading="composeFileLoading">
        <pre v-if="codeMode === 'view'" class="code-view" v-html="highlightedCompose || '（空文件）'"></pre>
        <template v-else>
          <pre ref="hlLayerRef" class="hl-layer" aria-hidden="true" v-html="highlightedCompose"></pre>
          <textarea ref="taRef" v-model="composeFileForm.content" class="ta-layer" spellcheck="false"
            placeholder="# docker compose 配置" @scroll="syncCodeScroll" @keydown.tab.prevent="insertCodeTab"></textarea>
        </template>
      </div>
      <template #footer>
        <el-button @click="reloadComposeFile" :loading="composeFileLoading">重新加载</el-button>
        <el-button @click="composeFileVisible = false">关闭</el-button>
        <el-button type="primary" :loading="composeFileSaving" @click="saveComposeFile">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { highlightYaml } from '../utils/yamlHighlight'

const tab = ref('overview')
const tabSwitching = ref(false)
let tabMotionTimer
watch(tab, () => {
  tabSwitching.value = true
  clearTimeout(tabMotionTimer)
  tabMotionTimer = setTimeout(() => { tabSwitching.value = false }, 320)
})
const available = ref(null)
const availError = ref('')
const availHint = ref('')
const sysInfo = ref({})
const dfRaw = ref('')

const showAll = ref(false)
const containers = ref([])
const images = ref([])
const composeBase = ref('')
const composeProjects = ref([])
const composeLoading = ref(false)
const composeUpdatedAt = ref('')
const composeFileVisible = ref(false)
const composeFileLoading = ref(false)
const composeFileSaving = ref(false)
const composeFileForm = ref({ name: '', path: '', dir_path: '', content: '', size: 0 })
const codeMode = ref('view')
const hlLayerRef = ref(null)
const taRef = ref(null)
let composeTimer = null

// 高亮后的 HTML（查看模式直接渲染，编辑模式作为 textarea 底层的对齐图层）
const highlightedCompose = computed(() => highlightYaml(composeFileForm.value.content))

function syncCodeScroll(e) {
  const hl = hlLayerRef.value
  if (!hl) return
  hl.scrollTop = e.target.scrollTop
  hl.scrollLeft = e.target.scrollLeft
}

// Tab 键插入两个空格（YAML 缩进），不跳出输入框
function insertCodeTab(e) {
  const ta = e.target
  const { selectionStart: s = 0, selectionEnd: t = 0, value } = ta
  composeFileForm.value.content = `${value.slice(0, s)}  ${value.slice(t)}`
  requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 2 })
}

// 只显示文件名（路径已在左侧「路径」列）
const baseName = p => (p || '').split('/').filter(Boolean).pop() || '-'

const fmtSize = n => {
  if (n === null || n === undefined) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}

const composeFileInfo = computed(() => {
  const f = composeFileForm.value
  if (composeFileLoading.value) return '加载中…'
  const lines = f.content ? f.content.split('\n').length : 0
  return `${lines} 行 · ${fmtSize(f.size)}`
})
const volumes = ref([])
const networks = ref([])
const pullName = ref('')
const volName = ref('')
const netName = ref('')
const logsVisible = ref(false)
const logsText = ref('')
const statsVisible = ref(false)
const statsRows = ref([])

const selectedRows = ref([])
const defaultSaveDir = ref('')
const saveVisible = ref(false)
const saving = ref(false)
const saveElapsed = ref(0)
const saveResult = ref(null)
const saveForm = ref({ images: [], output_dir: '', filename: '', compress: false })
const dirVisible = ref(false)
const dirCurrent = ref('')
const dirBreadcrumbs = ref([])
const dirItems = ref([])
let saveTimer = null

const shortId = s => (s || '').slice(0, 12)
const running = row => /Up|running/i.test(row.Status || '')

function hasError(list) {
  return Array.isArray(list) && list.length === 1 && list[0]?.error
}

async function fetchAvailable() {
  try {
    const { data } = await api.get('/docker/available')
    available.value = data.available
    availError.value = data.error || ''
    availHint.value = data.hint || ''
  } catch (_) { available.value = false; availError.value = '接口不可用' }
}

async function fetchSystem() {
  try {
    const { data } = await api.get('/docker/system')
    sysInfo.value = data.info || {}
    if (data.df?.ok) dfRaw.value = data.df.raw
    else if (data.df?.error) dfRaw.value = data.df.error
  } catch (_) {}
}

async function pruneAll() {
  await ElMessageBox.confirm('确认执行 docker system prune -af？将删除所有未使用的资源！', '危险操作', { type: 'warning' })
    .then(async () => {
      const { data } = await api.post('/docker/system/prune')
      ElMessage.success(data.ok ? '清理完成' : (data.output || '清理失败'))
      fetchSystem(); fetchContainers(); fetchImages()
    }).catch(() => {})
}

async function fetchContainers() {
  try {
    const { data } = await api.get('/docker/containers', { params: { all: showAll.value } })
    if (hasError(data.containers)) { ElMessage.error(data.containers[0].error); containers.value = [] }
    else containers.value = data.containers || []
  } catch (_) { containers.value = [] }
}

async function containerOp(row, action, confirm = false) {
  if (confirm) {
    try { await ElMessageBox.confirm(`确认删除容器 ${row.Names || row.ID}？`, '确认', { type: 'warning' }) }
    catch (_) { return }
  }
  try {
    const { data } = await api.post(`/docker/containers/${row.ID}/${action}`)
    ElMessage.success(data.ok ? `${action} 成功` : (data.output || `${action} 失败`))
    fetchContainers()
  } catch (_) { ElMessage.error('操作失败') }
}

async function openLogs(row) {
  try {
    const { data } = await api.get(`/docker/containers/${row.ID}/logs`, { params: { tail: 300 } })
    logsText.value = data.logs || ''
    logsVisible.value = true
  } catch (_) { ElMessage.error('获取日志失败') }
}

async function fetchStats() {
  try {
    const { data } = await api.get('/docker/stats')
    statsRows.value = data.stats || []
    statsVisible.value = true
  } catch (_) { ElMessage.error('获取 stats 失败') }
}

async function fetchImages() {
  selectedRows.value = []
  try {
    const { data } = await api.get('/docker/images')
    if (hasError(data.images)) { ElMessage.error(data.images[0].error); images.value = [] }
    else images.value = data.images || []
  } catch (_) { images.value = [] }
}

async function pullImage() {
  const name = pullName.value.trim()
  if (!name) return ElMessage.warning('请输入镜像名')
  const [n, tag] = name.includes(':') ? name.split(':') : [name, 'latest']
  try {
    const { data } = await api.post('/docker/images/pull', { name: n, tag })
    ElMessage.success(data.ok ? '拉取完成' : (data.output || '拉取失败'))
    fetchImages()
  } catch (_) { ElMessage.error('拉取失败') }
}

async function imageOp(row, action) {
  if (action === 'rmi') {
    try { await ElMessageBox.confirm(`确认删除镜像 ${row.Repository}:${row.Tag}？`, '确认', { type: 'warning' }) }
    catch (_) { return }
  }
  try {
    const { data } = await api.post(`/docker/images/${row.ID}/${action}`)
    ElMessage.success(data.ok ? '操作成功' : (data.output || '操作失败'))
    fetchImages()
  } catch (_) { ElMessage.error('操作失败') }
}

async function pruneImages() {
  try {
    const { data } = await api.post('/docker/images/none/prune')
    ElMessage.success(data.ok ? '清理完成' : (data.output || '清理失败'))
    fetchImages()
  } catch (_) { ElMessage.error('清理失败') }
}

// ── 镜像保存为文件 ──

const imageRef = row => {
  const repo = row.Repository && row.Repository !== '<none>' ? row.Repository : ''
  const tag = row.Tag && row.Tag !== '<none>' ? row.Tag : ''
  if (repo && tag) return `${repo}:${tag}`
  return repo || row.ID
}

function onImgSelect(rows) { selectedRows.value = rows || [] }

async function fetchDefaultSaveDir() {
  try {
    const { data } = await api.get('/docker/images/save/default-dir')
    defaultSaveDir.value = data.dir || ''
  } catch (_) { defaultSaveDir.value = '' }
}

function openSave(rows) {
  const list = [...new Set((rows || []).map(imageRef).filter(Boolean))]
  saveResult.value = null
  const base = list.length === 1 ? list[0].replace(/[^A-Za-z0-9._-]/g, '_') : `docker-images-${Date.now()}`
  saveForm.value = {
    images: list,
    output_dir: defaultSaveDir.value,
    filename: base ? `${base}.tar` : '',
    compress: false,
  }
  saveVisible.value = true
}

// 压缩开关联动文件名后缀
watch(() => saveForm.value.compress, v => {
  const f = (saveForm.value.filename || '').trim()
  if (!f) return
  const base = f.replace(/\.(tar\.gz|tgz|tar|gz)$/i, '')
  saveForm.value.filename = v ? `${base}.tar.gz` : `${base}.tar`
})

async function doSave() {
  const { images, output_dir, filename, compress } = saveForm.value
  if (!images.length) return ElMessage.warning('请先选择镜像')
  if (!(output_dir || '').trim()) return ElMessage.warning('请填写保存目录')
  saving.value = true
  saveElapsed.value = 0
  saveResult.value = null
  saveTimer = setInterval(() => { saveElapsed.value += 1 }, 1000)
  try {
    const { data } = await api.post('/docker/images/save', {
      images, output_dir: output_dir.trim(), filename: filename.trim(), compress,
    }, { timeout: 0 })
    if (data.ok) {
      saveResult.value = data
      ElMessage.success(`已保存：${data.path}`)
    } else {
      ElMessage.error(data.output || '保存失败')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    clearInterval(saveTimer); saveTimer = null; saving.value = false
  }
}

async function openDirPicker() {
  dirVisible.value = true
  await loadDirs(saveForm.value.output_dir || defaultSaveDir.value || '~')
}

async function loadDirs(path) {
  try {
    const { data } = await api.get('/files', { params: { path } })
    dirCurrent.value = data.current
    dirBreadcrumbs.value = data.breadcrumbs || []
    dirItems.value = (data.items || []).filter(i => i.is_dir)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '目录读取失败')
  }
}

function pickDir(p) {
  if (p) saveForm.value.output_dir = p
  dirVisible.value = false
}

// 用系统文件管理器打开文件夹（传文件路径时打开其所在目录）
async function openFolder(p) {
  if (!p) return
  try {
    const { data } = await api.post('/files/open-file-manager', null, { params: { path: p } })
    if (data?.ok === false) ElMessage.error(data.error || '打开失败')
  } catch (e) { ElMessage.error(e?.response?.data?.detail || '打开文件夹失败') }
}

// ── Compose ──

async function scanCompose() {
  const base = composeBase.value.trim()
  composeLoading.value = true
  try {
    const { data } = await api.get('/docker/compose', { params: { base, scan: true } })
    composeProjects.value = data.projects || []
    composeUpdatedAt.value = new Date().toLocaleTimeString()
    const added = data.scanned || 0
    ElMessage.success(added ? `扫描到 ${added} 个 compose 项目` : '该目录下未发现 compose 项目')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '扫描失败')
  } finally { composeLoading.value = false }
}

// 复核已记录的项目是否还在（不扫描目录）
async function refreshCompose() {
  composeLoading.value = true
  try {
    const { data } = await api.get('/docker/compose', { params: { scan: false } })
    composeProjects.value = data.projects || []
    composeUpdatedAt.value = new Date().toLocaleTimeString()
  } catch (_) { /* 静默失败，避免自动刷新时打扰 */ }
  finally { composeLoading.value = false }
}

async function composeOp(row, action) {
  try {
    const { data } = await api.post('/docker/compose/action', { project_dir: row.path, action })
    ElMessage.success(data.ok ? `${action} 成功` : (data.output || `${action} 失败`))
  } catch (_) { ElMessage.error('操作失败') }
}

async function forgetCompose(row) {
  try { await ElMessageBox.confirm(`移除此 compose 记录？\n${row.path}`, '确认', { type: 'warning' }) }
  catch (_) { return }
  try {
    await api.post('/docker/compose/forget', { path: row.path })
    ElMessage.success('已移除记录')
    refreshCompose()
  } catch (_) { ElMessage.error('移除失败') }
}

async function openComposeFile(row) {
  composeFileForm.value = {
    name: row.name, path: row.compose_file || `${row.path}/docker-compose.yml`,
    dir_path: row.path, content: '', size: null,
  }
  codeMode.value = 'view'
  composeFileVisible.value = true
  await reloadComposeFile()
}

async function reloadComposeFile() {
  composeFileLoading.value = true
  try {
    const { data } = await api.get('/docker/compose/file', { params: { path: composeFileForm.value.path } })
    if (data.ok) {
      composeFileForm.value.content = data.content ?? ''
      composeFileForm.value.size = data.size ?? 0
      composeFileForm.value.path = data.path || composeFileForm.value.path
    } else {
      composeFileForm.value.content = ''
      ElMessage.error(data.error || '读取失败')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '读取失败')
  } finally { composeFileLoading.value = false }
}

async function saveComposeFile() {
  composeFileSaving.value = true
  try {
    const { data } = await api.post('/docker/compose/file', {
      path: composeFileForm.value.path, content: composeFileForm.value.content,
    })
    if (data.ok) {
      composeFileForm.value.size = data.size ?? composeFileForm.value.size
      ElMessage.success(`已保存（${data.size_human || ''}），旧版本备份为 .bak`)
      refreshCompose()
    } else {
      ElMessage.error(data.error || '保存失败')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally { composeFileSaving.value = false }
}

async function fetchVolumes() {
  try {
    const { data } = await api.get('/docker/volumes')
    if (hasError(data.volumes)) { ElMessage.error(data.volumes[0].error); volumes.value = [] }
    else volumes.value = data.volumes || []
  } catch (_) { volumes.value = [] }
}

async function volumeOp(action, name = '') {
  const n = name || volName.value.trim()
  if (!n) return ElMessage.warning('请输入卷名称')
  try {
    const { data } = await api.post('/docker/volumes/action', { name: n, action })
    ElMessage.success(data.ok ? `${action} 成功` : (data.output || `${action} 失败`))
    volName.value = ''; fetchVolumes()
  } catch (_) { ElMessage.error('操作失败') }
}

async function fetchNetworks() {
  try {
    const { data } = await api.get('/docker/networks')
    if (hasError(data.networks)) { ElMessage.error(data.networks[0].error); networks.value = [] }
    else networks.value = data.networks || []
  } catch (_) { networks.value = [] }
}

async function networkOp(action, name = '') {
  const n = name || netName.value.trim()
  if (!n) return ElMessage.warning('请输入网络名称')
  try {
    const { data } = await api.post('/docker/networks/action', { name: n, action })
    ElMessage.success(data.ok ? `${action} 成功` : (data.output || `${action} 失败`))
    netName.value = ''; fetchNetworks()
  } catch (_) { ElMessage.error('操作失败') }
}

function onTab(name) {
  if (name === 'overview') fetchSystem()
  else if (name === 'containers') fetchContainers()
  else if (name === 'images') fetchImages()
  else if (name === 'compose') refreshCompose()
  else if (name === 'volumes') fetchVolumes()
  else if (name === 'networks') fetchNetworks()
}

onMounted(() => {
  fetchAvailable()
  fetchSystem()
  fetchContainers()
  fetchImages()
  refreshCompose()
  fetchVolumes()
  fetchNetworks()
  fetchDefaultSaveDir()
  // 每 10 分钟自动复核一次已记录的 compose（仅在 Compose 页且无弹窗时）
  composeTimer = setInterval(() => {
    if (tab.value === 'compose' && !composeLoading.value && !composeFileVisible.value) {
      refreshCompose()
    }
  }, 10 * 60 * 1000)
})

onBeforeUnmount(() => {
  if (saveTimer) clearInterval(saveTimer)
  if (composeTimer) clearInterval(composeTimer)
})
</script>

<style scoped>
.docker-view { padding: 4px; }
.docker-warn, .docker-ok { margin-bottom: 8px; }
.hint-pre { margin: 6px 0 0; font-size: 12px; white-space: pre-wrap; line-height: 1.6; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.df-box { margin-top: 12px; }
.df-box h4 { margin: 8px 0; }
.df-pre {
  background: var(--el-fill-color-light);
  padding: 10px;
  border-radius: var(--radius-md);
  font-size: 12px;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
}
.logs-pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: var(--radius-md);
  font-size: 12px;
  max-height: 500px;
  overflow: auto;
  white-space: pre-wrap;
}
.save-targets { display: flex; flex-wrap: wrap; gap: 6px; }
.dir-row { display: flex; gap: 8px; width: 100%; }
.tip { margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.save-result {
  margin-top: 4px; padding: 8px 10px; font-size: 12px;
  background: var(--el-fill-color-light); border-radius: var(--radius-md); word-break: break-all;
}
.dir-nav { display: flex; flex-wrap: wrap; gap: 2px; margin-bottom: 6px; }
.dir-list {
  max-height: 320px; overflow: auto;
  border: 1px solid var(--el-border-color-lighter); border-radius: var(--radius-md);
}
.dir-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 2px 8px; font-size: 13px;
}
.dir-item:hover { background: var(--el-fill-color-light); }
.dir-name { cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dir-empty { padding: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.compose-file-bar {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  font-size: 12px; color: var(--el-text-color-secondary); flex-wrap: wrap;
}
.compose-file-bar code {
  background: var(--el-fill-color-light); padding: 2px 6px; border-radius: 4px;
  font-size: 12px; word-break: break-all;
}
/* ── compose 文件高亮显示 / 编辑 ── */
.code-box {
  position: relative; height: 480px; overflow: hidden;
  background: #1e1e1e; border: 1px solid var(--el-border-color); border-radius: var(--radius-md);
}
.code-view, .hl-layer, .ta-layer {
  margin: 0; padding: 10px 12px; box-sizing: border-box;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px; line-height: 1.55; tab-size: 2;
  white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word;
}
.code-view { height: 100%; overflow: auto; color: #d4d4d4; }
.hl-layer, .ta-layer { position: absolute; inset: 0; overflow: auto; }
/* 高亮层多留一行底部空间：pre 会吞掉末尾空行，避免滚动到底部时两层错位 */
.hl-layer { color: #d4d4d4; pointer-events: none; padding-bottom: calc(10px + 1.55em); }
.ta-layer {
  background: transparent; color: transparent; caret-color: #d4d4d4;
  border: 0; outline: none; resize: none;
}
.ta-layer::placeholder { color: #6a9955; }
.ta-layer::selection { background: rgba(38, 79, 120, 0.75); }

.code-view :deep(.y-key), .hl-layer :deep(.y-key) { color: #9cdcfe; }
.code-view :deep(.y-string), .hl-layer :deep(.y-string) { color: #ce9178; }
.code-view :deep(.y-number), .hl-layer :deep(.y-number) { color: #b5cea8; }
.code-view :deep(.y-keyword), .hl-layer :deep(.y-keyword) { color: #569cd6; font-weight: 600; }
.code-view :deep(.y-variable), .hl-layer :deep(.y-variable) { color: #dcdcaa; }
.code-view :deep(.y-anchor), .hl-layer :deep(.y-anchor) { color: #c586c0; }
.code-view :deep(.y-comment), .hl-layer :deep(.y-comment) { color: #6a9955; font-style: italic; }
.code-view :deep(.y-punct), .hl-layer :deep(.y-punct) { color: #b0b8c4; }
.code-view :deep(.y-value), .hl-layer :deep(.y-value) { color: #d4d4d4; }
.missing-text { color: var(--el-text-color-disabled); text-decoration: line-through; }
</style>
