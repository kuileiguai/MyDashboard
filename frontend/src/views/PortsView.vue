<template>
  <div class="ports-view">
    <h2 class="page-title">端口监控</h2>
    <p class="module-purpose">从监听端口追到进程、容器与启动路径，及时发现异常暴露。</p>
    <el-tabs v-model="activeTab" type="border-card" :class="{ 'module-tabs': true, 'is-switching': tabSwitching }">
      <!-- 端口表格 -->
      <el-tab-pane label="监听端口" name="ports">
        <div class="toolbar">
          <el-input v-model="searchPort" placeholder="搜索端口 / 备注" clearable class="search-input" />
          <el-input v-model="searchProc" placeholder="搜索进程" clearable class="search-input" />
          <el-button @click="fetchPorts" :loading="loading"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <el-switch v-model="autoRefresh" active-text="5s自刷" @change="toggleAuto" />
          <el-button @click="takeSnapshot">端口快照</el-button>
          <el-button @click="watchVisible = true">关注端口 ({{ watchPorts.length }})</el-button>
          <el-button @click="gotoAlerts">
            告警<el-badge v-if="unreadAlerts" :value="unreadAlerts" :max="99" type="danger" class="tab-badge" />
          </el-button>
        </div>
        <el-table :data="filteredPorts" stripe v-loading="loading" @row-click="showDetail" class="ports-table">
          <el-table-column prop="port" label="端口" width="95" sortable>
            <template #default="{ row }">
              <el-tag :type="portTagType(row)" size="small">{{ row.port }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="protocol" label="协议" width="80" />
          <el-table-column label="监听地址" width="190">
            <template #default="{ row }">
              <span class="addr-cell">
                <span>{{ row.address || '全部网卡' }}<span v-if="row.iface && row.iface !== '全部网卡'" class="addr-iface"> · {{ row.iface }}</span></span>
                <el-tag :type="exposure(row).type" size="small" effect="plain">{{ exposure(row).text }}</el-tag>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="容器" width="150">
            <template #default="{ row }">
              <el-tag v-if="row.container_name" size="small" type="success" effect="plain">{{ row.container_name }}</el-tag>
              <span v-else-if="row.container_id" class="muted">{{ row.container_id }}</span>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="process_name" label="进程名" width="120" />
          <el-table-column prop="pid" label="PID" width="70" />
          <el-table-column label="备注" width="150">
            <template #default="{ row }">
              <span class="remark-cell" @click.stop="openPortRemark(row)">
                <span v-if="remarkOf(row)" class="remark-text">{{ remarkOf(row) }}</span>
                <el-icon v-else class="remark-add"><EditPen /></el-icon>
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="command" label="启动命令" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" text @click.stop="showDetail(row)">详情</el-button>
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
          <el-table-column prop="status" label="状态" width="90">
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
          <el-select v-model="snapA" placeholder="快照 A（较早）" size="small" class="snap-select" clearable>
            <el-option v-for="s in snapshots" :key="s.id" :label="`#${s.id} · ${s.created_at}`" :value="s.id" />
          </el-select>
          <el-select v-model="snapB" placeholder="快照 B（较新）" size="small" class="snap-select" clearable>
            <el-option v-for="s in snapshots" :key="s.id" :label="`#${s.id} · ${s.created_at}`" :value="s.id" />
          </el-select>
          <el-button @click="compareSelected" :disabled="!snapA || !snapB">对比选中</el-button>
          <el-button @click="compareSnapshots" :disabled="snapshots.length < 2">对比最近两次</el-button>
        </div>
        <div class="snap-config">
          <el-switch v-model="autoSnap" active-text="自动快照" />
          <span class="tip">每</span>
          <el-input-number v-model="autoSnapInterval" :min="1" :max="720" size="small" controls-position="right"
            class="interval-input" />
          <span class="tip">分钟</span>
          <el-checkbox v-model="alertNew" size="small">新增端口告警</el-checkbox>
          <el-checkbox v-model="alertGone" size="small">端口消失告警</el-checkbox>
          <el-button size="small" type="primary" @click="saveConfig">保存设置</el-button>
          <span class="tip">上次自动快照：{{ autoLastHuman || '尚未执行' }}</span>
        </div>
        <el-table :data="snapshots" size="small" max-height="300">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="created_at" label="时间" width="180" />
          <el-table-column label="来源" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'auto' ? 'warning' : 'info'" effect="plain">
                {{ row.source === 'auto' ? '自动' : '手动' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="端口数" width="100">
            <template #default="{ row }">{{ row.count }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button size="small" text @click="snapA = row.id">设为 A</el-button>
              <el-button size="small" text @click="snapB = row.id">设为 B</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="snapCompare" class="compare-box">
          <div v-if="snapCompare.error" class="tip">{{ snapCompare.error }}</div>
          <template v-else>
            <div class="tip">
              对比 #{{ snapCompare.snapshot1.id }} → #{{ snapCompare.snapshot2.id }} ·
              {{ snapCompare.snapshot1.count }} → {{ snapCompare.snapshot2.count }} 个端口 · 未变 {{ snapCompare.unchanged }}
            </div>
            <el-alert v-if="snapCompare.new_ports?.length" :title="`新增端口 (${snapCompare.new_ports.length})`" type="success" :closable="false">
              <div class="diff-line">
                <span v-for="p in snapCompare.new_ports" :key="p.port + p.protocol" class="diff-item">
                  {{ p.port }}/{{ p.protocol }} <span class="muted">{{ p.process_name }}</span>
                  <el-tag v-if="p.exposed" size="small" type="danger" effect="plain">对外</el-tag>
                </span>
              </div>
            </el-alert>
            <el-alert v-if="snapCompare.gone_ports?.length" :title="`消失端口 (${snapCompare.gone_ports.length})`" type="warning"
              :closable="false" style="margin-top: 8px">
              <div class="diff-line">
                <span v-for="p in snapCompare.gone_ports" :key="p.port + p.protocol" class="diff-item">
                  {{ p.port }}/{{ p.protocol }} <span class="muted">{{ p.process_name }}</span>
                </span>
              </div>
            </el-alert>
            <el-alert v-if="!snapCompare.new_ports?.length && !snapCompare.gone_ports?.length"
              title="无变化" type="info" :closable="false" style="margin-top: 8px" />
          </template>
        </div>
      </el-tab-pane>

      <!-- 端口变化告警 -->
      <el-tab-pane name="alerts">
        <template #label>
          <span>端口告警<el-badge v-if="unreadAlerts" :value="unreadAlerts" :max="99" type="danger" class="tab-badge" /></span>
        </template>
        <div class="toolbar">
          <el-button @click="fetchAlerts" :loading="alertLoading"><el-icon><Refresh /></el-icon> 刷新</el-button>
          <el-checkbox v-model="alertUnreadOnly" size="small" @change="fetchAlerts">只看未读</el-checkbox>
          <el-button :disabled="!unreadAlerts" @click="markRead()">全部标为已读</el-button>
          <el-button type="danger" :disabled="!alerts.length" @click="clearAlerts">清空</el-button>
          <span class="tip">自动/手动快照时对比上一条快照产生，关注端口与对外监听端口变化会加重提示</span>
        </div>
        <el-table :data="alerts" size="small" stripe max-height="480">
          <el-table-column prop="created_at" label="时间" width="170" />
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.severity === 'danger' ? 'danger' : row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                {{ severityText(row.severity) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.alert_type === 'new_port' ? '新增端口' : '端口消失' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="port" label="端口" width="90" />
          <el-table-column prop="process_name" label="进程" width="130" show-overflow-tooltip />
          <el-table-column prop="message" label="说明" min-width="320" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_read ? 'info' : 'danger'" effect="plain">{{ row.is_read ? '已读' : '未读' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" text :disabled="!!row.is_read" @click="markRead(row)">标为已读</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- Detail Dialog -->
    <el-dialog v-model="detailVisible" title="端口详情" width="650px">
      <template v-if="detailItem">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="端口">{{ detailItem.port }}</el-descriptions-item>
          <el-descriptions-item label="协议">{{ detailItem.protocol }}</el-descriptions-item>
          <el-descriptions-item label="监听地址">{{ detailItem.address || '全部网卡' }}</el-descriptions-item>
          <el-descriptions-item label="网卡">{{ detailItem.iface || '-' }}</el-descriptions-item>
          <el-descriptions-item label="暴露范围">
            <el-tag :type="exposure(detailItem).type" size="small">{{ exposure(detailItem).text }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="容器">
            {{ detailItem.container_name || detailItem.container_id || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="PID">{{ detailItem.pid }}</el-descriptions-item>
          <el-descriptions-item label="进程名">{{ detailItem.process_name }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detailItem.username || '-' }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ remarkOf(detailItem) || '-' }}</el-descriptions-item>
          <el-descriptions-item label="工作目录" :span="2">{{ detailItem.cwd || '-' }}</el-descriptions-item>
          <el-descriptions-item label="启动命令" :span="2"><code>{{ detailItem.command }}</code></el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button type="danger" @click="killProcess(detailItem, 'term')">SIGTERM</el-button>
        <el-button type="danger" @click="killProcess(detailItem, 'kill')">SIGKILL</el-button>
      </template>
    </el-dialog>

    <!-- 关注端口 -->
    <el-dialog v-model="watchVisible" title="关注端口" width="520px">
      <p class="tip">关注的端口会橙标高亮，且新增 / 消失时告警级别更高。</p>
      <el-select v-model="watchPorts" multiple filterable allow-create default-first-option
        placeholder="输入端口号后回车，或选下方常用端口" style="width: 100%">
        <el-option v-for="p in COMMON_PORTS" :key="p" :label="`${p}`" :value="p" />
      </el-select>
      <template #footer>
        <el-button @click="fetchConfig">重置</el-button>
        <el-button @click="watchVisible = false">取消</el-button>
        <el-button type="primary" @click="saveWatchPorts">保存</el-button>
      </template>
    </el-dialog>

    <!-- 端口备注 -->
    <el-dialog v-model="remarkVisible" :title="`端口备注 — ${remarkTarget.port}/${remarkTarget.protocol}`" width="420px">
      <el-input v-model="remarkText" maxlength="60" show-word-limit placeholder="例如：前端开发服务器" />
      <template #footer>
        <el-button @click="clearPortRemark">清除</el-button>
        <el-button @click="remarkVisible = false">取消</el-button>
        <el-button type="primary" @click="savePortRemark">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const activeTab = ref('ports')
const tabSwitching = ref(false)
let tabMotionTimer
watch(activeTab, () => {
  tabSwitching.value = true
  clearTimeout(tabMotionTimer)
  tabMotionTimer = setTimeout(() => { tabSwitching.value = false }, 320)
})
const ports = ref([]); const processes = ref([])
const loading = ref(false); const searchPort = ref(''); const searchProc = ref('')
const procSearch = ref(''); const autoRefresh = ref(true)
const detailVisible = ref(false); const detailItem = ref(null)
const systemdServices = ref([]); const systemdScope = ref('user'); const sysLoading = ref(false)
const zombies = ref({ zombie_count: 0, orphan_count: 0, zombies: [], orphan_suspects: [] }); const zLoading = ref(false)
const snapshots = ref([]); const snLoading = ref(false); const snapCompare = ref(null)
const snapA = ref(null); const snapB = ref(null)
const alerts = ref([]); const unreadAlerts = ref(0); const alertLoading = ref(false); const alertUnreadOnly = ref(false)
const portRemarks = ref({}); const watchPorts = ref([]); const watchVisible = ref(false)
const autoSnap = ref(false); const autoSnapInterval = ref(30); const autoLastHuman = ref('')
const alertNew = ref(true); const alertGone = ref(true)
const remarkVisible = ref(false); const remarkTarget = ref({}); const remarkText = ref('')
let timer = null; let alertTimer = null

const COMMON_PORTS = [22, 80, 443, 2375, 3000, 3306, 5000, 5432, 5672, 6379, 8000, 8080, 8081, 8443,
  8888, 9000, 9090, 9200, 11211, 15672, 2181, 27017]

const watchSet = computed(() => new Set(watchPorts.value.map(Number)))
function portTagType(row) { return watchSet.value.has(Number(row.port)) ? 'warning' : '' }
function remarkKey(row) { return `${row.port}/${row.protocol || ''}`.replace(/\/$/, '') }
function remarkOf(row) { return row ? (portRemarks.value[remarkKey(row)] || '') : '' }
function exposure(row) {
  if (row?.exposed) return { type: 'danger', text: '对外' }
  const a = row?.address || ''
  if (a === '127.0.0.1' || a === '::1') return { type: 'info', text: '仅本机' }
  return { type: 'warning', text: '内网' }
}
function severityText(s) { return s === 'danger' ? '严重' : s === 'warning' ? '注意' : '提示' }

const filteredPorts = computed(() => {
  const pq = searchPort.value.trim().toLowerCase()
  return ports.value.filter(p => {
    const inPort = !pq || String(p.port).includes(pq) || (remarkOf(p) || '').toLowerCase().includes(pq)
    const inProc = !searchProc.value || (p.process_name || '').toLowerCase().includes(searchProc.value.toLowerCase())
    return inPort && inProc
  })
})

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

async function fetchConfig() {
  try {
    const { data } = await api.get('/ports/config')
    watchPorts.value = data.watch_ports || []
    autoSnap.value = !!data.auto_snapshot
    autoSnapInterval.value = data.interval_min || 30
    autoLastHuman.value = data.auto_last_human || ''
    alertNew.value = data.alert_new !== false
    alertGone.value = data.alert_gone !== false
  } catch (_) {}
}
async function saveConfig() {
  try {
    await api.post('/ports/config', {
      auto_snapshot: autoSnap.value, interval_min: autoSnapInterval.value,
      alert_new: alertNew.value, alert_gone: alertGone.value,
    })
    ElMessage.success('设置已保存')
    await fetchConfig()
  } catch (_) { ElMessage.error('保存失败') }
}
async function saveWatchPorts() {
  const list = [...new Set(watchPorts.value.map(x => Number(String(x).trim())).filter(n => Number.isInteger(n) && n > 0 && n < 65536))]
  try {
    const { data } = await api.post('/ports/config', { watch_ports: list })
    watchPorts.value = data.watch_ports || list
    ElMessage.success(`已保存 ${watchPorts.value.length} 个关注端口`)
    watchVisible.value = false
  } catch (_) { ElMessage.error('保存失败') }
}

async function fetchRemarks() { try { const { data } = await api.get('/ports/remarks'); portRemarks.value = data || {} } catch (_) {} }
function openPortRemark(row) { remarkTarget.value = row; remarkText.value = remarkOf(row); remarkVisible.value = true }
async function savePortRemark() {
  try {
    const { data } = await api.post('/ports/remarks', {
      port: remarkTarget.value.port, protocol: remarkTarget.value.protocol || '', remark: remarkText.value,
    })
    portRemarks.value = data.remarks || {}
    remarkVisible.value = false
    ElMessage.success('备注已保存')
  } catch (_) { ElMessage.error('保存失败') }
}
async function clearPortRemark() {
  remarkText.value = ''
  await savePortRemark()
}

async function fetchAlerts() {
  alertLoading.value = true
  try {
    const { data } = await api.get('/ports/alerts', { params: { limit: 100, unread_only: alertUnreadOnly.value } })
    alerts.value = data.alerts || []
    unreadAlerts.value = data.unread || 0
  } catch (_) {}
  alertLoading.value = false
}
async function markRead(row) {
  try {
    await api.post('/ports/alerts/read', row ? { ids: [row.id] } : { all: true })
    await fetchAlerts()
  } catch (_) { ElMessage.error('操作失败') }
}
async function clearAlerts() {
  try { await ElMessageBox.confirm('清空全部端口告警记录？', '确认', { type: 'warning' }) }
  catch (_) { return }
  try { await api.delete('/ports/alerts', { data: { all: true } }); await fetchAlerts(); ElMessage.success('已清空') }
  catch (_) { ElMessage.error('清空失败') }
}
function gotoAlerts() { activeTab.value = 'alerts'; fetchAlerts() }

async function fetchSnapshots() {
  try {
    const { data } = await api.get('/ports/snapshots', { params: { limit: 50 } })
    snapshots.value = data || []
    if (snapshots.value.length >= 2 && snapA.value === null) {
      snapB.value = snapshots.value[0].id
      snapA.value = snapshots.value[1].id
    }
  } catch (_) {}
}
async function takeSnapshot() {
  snLoading.value = true
  try {
    const { data } = await api.get('/ports/snapshot')
    ElMessage.success(`快照已保存（共 ${data.count} 个端口，新增 ${data.new_ports.length} / 消失 ${data.gone_ports.length}）`)
    await fetchSnapshots(); await fetchAlerts()
  } catch (_) { ElMessage.error('快照失败') }
  snLoading.value = false
}
async function compareSnapshots() {
  try { const { data } = await api.get('/ports/snapshots/compare'); snapCompare.value = data } catch (_) {}
}
async function compareSelected() {
  const a = Number(snapA.value), b = Number(snapB.value)
  if (!a || !b || a === b) { ElMessage.warning('请选择两个不同的快照'); return }
  const [id1, id2] = a < b ? [a, b] : [b, a]
  try {
    const { data } = await api.get('/ports/snapshots/compare', { params: { id1, id2 } })
    snapCompare.value = data
  } catch (_) { ElMessage.error('对比失败') }
}

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

onMounted(() => {
  fetchPorts(); fetchProcesses(); fetchSystemd(); fetchSnapshots(); fetchZombies()
  fetchConfig(); fetchRemarks(); fetchAlerts()
  if (autoRefresh.value) timer = setInterval(fetchPorts, 5000)
  alertTimer = setInterval(fetchAlerts, 60000)
})
onUnmounted(() => { clearInterval(timer); clearInterval(alertTimer) })

watch(activeTab, (v) => {
  if (v === 'processes') fetchZombies()
  if (v === 'systemd') fetchSystemd()
  if (v === 'snapshots') fetchSnapshots()
  if (v === 'alerts') fetchAlerts()
})
</script>

<style scoped>
.ports-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.search-input { width: 180px; }
.ports-table { cursor: pointer; }
.tip { font-size: 12px; color: var(--el-text-color-secondary); }
.muted { color: var(--el-text-color-disabled); }
.tab-badge { margin-left: 6px; }
.addr-cell { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.addr-iface { color: var(--el-text-color-disabled); }
.remark-cell { display: inline-flex; align-items: center; min-width: 40px; cursor: pointer; }
.remark-text { font-size: 12px; color: var(--el-color-warning); }
.remark-add { color: var(--el-text-color-disabled); }
.remark-add:hover { color: var(--el-color-primary); }
.snap-select { width: 200px; }
.interval-input { width: 110px; }
.snap-config {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;
  padding: 8px 10px; border: 1px dashed var(--el-border-color); border-radius: 8px;
}
.compare-box { margin-top: 12px; }
.diff-line { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; }
.diff-item { display: inline-flex; align-items: center; gap: 4px; }
</style>
