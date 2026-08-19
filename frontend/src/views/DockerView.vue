<template>
  <div class="docker-view">
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

    <el-tabs v-model="tab" type="border-card" @tab-change="onTab">
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
        </div>
        <el-table :data="images" size="small" max-height="440">
          <el-table-column prop="Repository" label="仓库" show-overflow-tooltip />
          <el-table-column prop="Tag" label="标签" width="120" />
          <el-table-column prop="ID" label="ID" width="110">
            <template #default="{ row }">{{ shortId(row.ID) }}</template>
          </el-table-column>
          <el-table-column prop="Size" label="大小" width="100" />
          <el-table-column prop="CreatedSince" label="创建" width="110" />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="danger" @click="imageOp(row, 'rmi')">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Compose -->
      <el-tab-pane label="Compose" name="compose">
        <div class="toolbar">
          <el-input v-model="composeBase" placeholder="扫描目录（默认 ~）" size="small" style="width: 280px" />
          <el-button size="small" @click="fetchCompose">扫描</el-button>
        </div>
        <el-table :data="composeProjects" size="small" max-height="440">
          <el-table-column prop="name" label="项目" width="160" />
          <el-table-column prop="path" label="路径" show-overflow-tooltip />
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text type="success" @click="composeOp(row, 'up')">up -d</el-button>
              <el-button size="small" text type="warning" @click="composeOp(row, 'down')">down</el-button>
              <el-button size="small" text type="primary" @click="composeOp(row, 'restart')">restart</el-button>
              <el-button size="small" text @click="composeOp(row, 'ps')">ps</el-button>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const tab = ref('overview')
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
const volumes = ref([])
const networks = ref([])
const pullName = ref('')
const volName = ref('')
const netName = ref('')
const logsVisible = ref(false)
const logsText = ref('')
const statsVisible = ref(false)
const statsRows = ref([])

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

async function fetchCompose() {
  try {
    const { data } = await api.get('/docker/compose', { params: { base: composeBase.value } })
    composeProjects.value = data.projects || []
  } catch (_) { composeProjects.value = [] }
}

async function composeOp(row, action) {
  try {
    const { data } = await api.post('/docker/compose/action', { project_dir: row.path, action })
    ElMessage.success(data.ok ? `${action} 成功` : (data.output || `${action} 失败`))
  } catch (_) { ElMessage.error('操作失败') }
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
  else if (name === 'compose') fetchCompose()
  else if (name === 'volumes') fetchVolumes()
  else if (name === 'networks') fetchNetworks()
}

onMounted(() => {
  fetchAvailable()
  fetchSystem()
  fetchContainers()
  fetchImages()
  fetchCompose()
  fetchVolumes()
  fetchNetworks()
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
  border-radius: 6px;
  font-size: 12px;
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
}
.logs-pre {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 500px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
