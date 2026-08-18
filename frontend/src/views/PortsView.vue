<template>
  <div class="ports-view">
    <h2 class="page-title">端口监控</h2>
    <el-tabs v-model="activeTab" type="border-card">
      <!-- 端口表格 -->
      <el-tab-pane label="监听端口" name="ports">
        <div class="toolbar">
          <el-input v-model="searchPort" placeholder="搜索端口..." clearable class="search-input" />
          <el-input v-model="searchProc" placeholder="搜索进程..." clearable class="search-input" />
          <el-button @click="fetchPorts" :loading="loading"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <el-switch v-model="autoRefresh" active-text="5s自刷" @change="toggleAuto" />
          <el-button @click="takeSnapshot">端口快照</el-button>
        </div>
        <el-table :data="filteredPorts" stripe v-loading="loading" @row-click="showDetail" class="ports-table">
          <el-table-column prop="port" label="端口" width="90" sortable>
            <template #default="{ row }">
              <el-tag :type="highlightPort(row.port)" size="small">{{ row.port }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="protocol" label="协议" width="80" />
          <el-table-column prop="process_name" label="进程名" width="140" />
          <el-table-column prop="pid" label="PID" width="80" />
          <el-table-column prop="command" label="启动命令" min-width="260" show-overflow-tooltip />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click.stop="killProcess(row)" :disabled="!row.pid">结束</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 全量进程 + 僵尸 -->
      <el-tab-pane label="全量进程" name="processes">
        <div class="toolbar">
          <el-input v-model="procSearch" placeholder="搜索进程..." clearable class="search-input" />
          <el-button type="warning" @click="fetchZombies" :loading="zLoading">检测僵尸/孤儿</el-button>
        </div>
        <el-alert v-if="zombies.zombie_count" :title="`发现 ${zombies.zombie_count} 个僵尸进程 + ${zombies.orphan_count} 个疑似孤儿`"
          type="error" show-icon :closable="false" style="margin-bottom: 8px" />
        <el-table :data="filteredProcesses" max-height="450" size="small" stripe>
          <el-table-column prop="pid" label="PID" width="70" />
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'zombie' ? 'danger' : row.status === 'orphan_suspect' ? 'warning' : 'info'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="cpu_percent" label="CPU%" width="70" sortable />
          <el-table-column prop="memory_percent" label="MEM%" width="70" sortable />
          <el-table-column prop="username" label="用户" width="80" />
          <el-table-column prop="cmdline" label="命令行" show-overflow-tooltip />
          <el-table-column label="操作" width="70">
            <template #default="{ row }">
              <el-button size="small" type="danger" @click="killProcess(row)">结束</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- systemd 服务 -->
      <el-tab-pane label="systemd 服务" name="systemd">
        <div class="toolbar">
          <el-radio-group v-model="systemdScope" @change="fetchSystemd">
            <el-radio-button value="user">用户服务</el-radio-button>
            <el-radio-button value="system">系统服务</el-radio-button>
          </el-radio-group>
          <el-button @click="fetchSystemd" :loading="sysLoading"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
        <el-table :data="systemdServices" size="small" stripe max-height="450">
          <el-table-column prop="name" label="服务名" min-width="220" />
          <el-table-column prop="load" label="Load" width="80" />
          <el-table-column prop="active" label="Active" width="80">
            <template #default="{ row }">
              <el-tag :type="row.active === 'active' ? 'success' : row.active === 'failed' ? 'danger' : 'info'" size="small">
                {{ row.active }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sub" label="Sub" width="100" />
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button size="small" @click="systemdAction(row, 'start')" :disabled="row.active === 'active'">启动</el-button>
              <el-button size="small" @click="systemdAction(row, 'stop')" :disabled="row.active !== 'active'">停止</el-button>
              <el-button size="small" @click="systemdAction(row, 'restart')">重启</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 端口快照 -->
      <el-tab-pane label="端口快照" name="snapshots">
        <div class="toolbar">
          <el-button @click="takeSnapshot" :loading="snLoading">立即快照</el-button>
          <el-button @click="fetchSnapshots"><el-icon><Refresh /></el-icon></el-button>
          <el-button @click="compareSnapshots" :disabled="snapshots.length < 2">对比最近两次</el-button>
        </div>
        <el-table :data="snapshots" size="small" max-height="300">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="created_at" label="时间" width="180" />
          <el-table-column label="端口数" width="100">
            <template #default="{ row }">{{ row.data?.ports?.length || 0 }}</template>
          </el-table-column>
        </el-table>
        <div v-if="snapCompare" style="margin-top: 16px">
          <el-alert v-if="snapCompare.new_ports?.length" title="新增端口" type="success">
            <span v-for="p in snapCompare.new_ports" :key="p.port">{{ p.port }}/{{ p.protocol }} ({{ p.process_name }}) </span>
          </el-alert>
          <el-alert v-if="snapCompare.gone_ports?.length" title="消失端口" type="warning" style="margin-top: 8px">
            <span v-for="p in snapCompare.gone_ports" :key="p.port">{{ p.port }}/{{ p.protocol }} ({{ p.process_name }}) </span>
          </el-alert>
          <el-alert v-if="!snapCompare.new_ports?.length && !snapCompare.gone_ports?.length"
            title="无变化" type="info" style="margin-top: 8px" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- Detail Dialog -->
    <el-dialog v-model="detailVisible" title="端口详情" width="650px">
      <template v-if="detailItem">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="端口">{{ detailItem.port }}</el-descriptions-item>
          <el-descriptions-item label="协议">{{ detailItem.protocol }}</el-descriptions-item>
          <el-descriptions-item label="PID">{{ detailItem.pid }}</el-descriptions-item>
          <el-descriptions-item label="进程名">{{ detailItem.process_name }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detailItem.username || '-' }}</el-descriptions-item>
          <el-descriptions-item label="工作目录" :span="2">{{ detailItem.cwd || '-' }}</el-descriptions-item>
          <el-descriptions-item label="启动命令" :span="2"><code>{{ detailItem.command }}</code></el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button type="danger" @click="killProcess(detailItem, 'term')">SIGTERM</el-button>
        <el-button type="danger" @click="killProcess(detailItem, 'kill')">SIGKILL</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const activeTab = ref('ports')
const ports = ref([]); const processes = ref([])
const loading = ref(false); const searchPort = ref(''); const searchProc = ref('')
const procSearch = ref(''); const autoRefresh = ref(true)
const detailVisible = ref(false); const detailItem = ref(null)
const systemdServices = ref([]); const systemdScope = ref('user'); const sysLoading = ref(false)
const zombies = ref({ zombie_count: 0, orphan_count: 0, zombies: [], orphan_suspects: [] }); const zLoading = ref(false)
const snapshots = ref([]); const snLoading = ref(false); const snapCompare = ref(null)
let timer = null

const highlightedPorts = [22, 80, 443, 3000, 5000, 5432, 6379, 8000, 8080, 8443, 9090, 27017]
function highlightPort(p) { return highlightedPorts.includes(p) ? 'warning' : '' }

const filteredPorts = computed(() => ports.value.filter(p =>
  (!searchPort.value || String(p.port).includes(searchPort.value)) &&
  (!searchProc.value || (p.process_name || '').toLowerCase().includes(searchProc.value.toLowerCase()))
))

const filteredProcesses = computed(() => {
  const all = [...processes.value, ...zombies.value.zombies, ...zombies.value.orphan_suspects]
  if (!procSearch.value) return all
  const q = procSearch.value.toLowerCase()
  return all.filter(p => p.name?.toLowerCase().includes(q) || (p.cmdline || '').toLowerCase().includes(q))
})

async function fetchPorts() { loading.value = true; try { const { data } = await api.get('/ports'); ports.value = data } catch (_) {}; loading.value = false }
async function fetchProcesses() { try { const { data } = await api.get('/processes'); processes.value = data } catch (_) {} }
async function fetchSystemd() { sysLoading.value = true; try { const { data } = await api.get(`/systemd?scope=${systemdScope.value}`); systemdServices.value = data } catch (_) {}; sysLoading.value = false }
async function fetchZombies() { zLoading.value = true; try { const { data } = await api.get('/processes/zombies'); zombies.value = data; if (data.zombie_count) ElMessage.warning(`发现 ${data.zombie_count} 个僵尸进程`) } catch (_) {}; zLoading.value = false }
async function fetchSnapshots() { try { const { data } = await api.get('/ports/snapshots'); snapshots.value = data } catch (_) {} }
async function takeSnapshot() { snLoading.value = true; try { await api.get('/ports/snapshot'); ElMessage.success('快照已保存'); await fetchSnapshots() } catch (_) {}; snLoading.value = false }
async function compareSnapshots() { try { const { data } = await api.get('/ports/snapshots/compare'); snapCompare.value = data } catch (_) {} }

function toggleAuto(v) { if (v) timer = setInterval(fetchPorts, 5000); else { clearInterval(timer); timer = null } }

async function showDetail(row) {
  if (row.pid > 0) { try { const { data } = await api.get(`/ports/${row.port}/detail`); detailItem.value = data[0] || row } catch (_) { detailItem.value = row } }
  else detailItem.value = row
  detailVisible.value = true
}

async function killProcess(row, sig = 'term') {
  if (!row.pid) return
  try {
    await ElMessageBox.confirm(`确认结束 ${row.process_name || row.name} (PID: ${row.pid})?`, '确认', { confirmButtonText: '确认', type: 'warning' })
    const { data } = await api.delete(`/ports/${row.pid}/kill?sig=${sig}`)
    if (data.ok) ElMessage.success('已结束'); else ElMessage.error(data.error || '失败')
    fetchPorts(); fetchProcesses()
  } catch (_) {}
}

async function systemdAction(row, action) {
  try {
    const { data } = await api.post('/systemd', { service_name: row.name, action, scope: systemdScope.value })
    if (data.ok) ElMessage.success(`${action} ${row.name} 成功`)
    else ElMessage.error(data.stderr || data.error || '操作失败')
    fetchSystemd()
  } catch (_) {}
}

onMounted(() => { fetchPorts(); fetchProcesses(); fetchSystemd(); fetchSnapshots(); fetchZombies(); if (autoRefresh.value) timer = setInterval(fetchPorts, 5000) })
onUnmounted(() => clearInterval(timer))

// Watch for tab activation
import { watch } from 'vue'
watch(activeTab, (v) => {
  if (v === 'processes') fetchZombies()
  if (v === 'systemd') fetchSystemd()
  if (v === 'snapshots') fetchSnapshots()
})
</script>

<style scoped>
.ports-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.search-input { width: 180px; }
.ports-table { cursor: pointer; }
</style>
