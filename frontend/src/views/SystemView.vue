<template>
  <div class="system-view">
    <h2 class="page-title">系统资源监控</h2>

    <el-alert v-if="!snapshot" title="等待数据..." type="info" :closable="false" />

    <template v-if="snapshot">
      <!-- Quick stats bar -->
      <el-row :gutter="12" class="quick-stats">
        <el-col :span="4">
          <el-statistic title="CPU" :value="snapshot.cpu?.total || 0" suffix="%"
            :value-style="{ color: cpuColor }" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="内存" :value="snapshot.memory?.percent || 0" suffix="%"
            :value-style="{ color: memColor }" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="Swap" :value="snapshot.swap?.percent || 0" suffix="%"
            :value-style="{ color: snapshot.swap?.percent > 50 ? '#f56c6c' : '#606266' }" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="Load" :value="snapshot.load?.load1 || 0"
            :value-style="{ color: snapshot.load?.load1 > snapshot.cpu?.count * 2 ? '#f56c6c' : '#606266' }" />
        </el-col>
        <el-col :span="4" v-if="snapshot.gpu?.available">
          <el-statistic title="GPU 显存" :value="snapshot.gpu.devices?.[0]?.memory_percent || 0" suffix="%"
            :value-style="{ color: gpuMemColor }" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="磁盘 /" :value="rootDiskPercent" suffix="%" />
        </el-col>
      </el-row>

      <!-- Charts -->
      <el-row :gutter="16">
        <!-- CPU Chart -->
        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <template #header>CPU 使用率</template>
            <v-chart :option="cpuOption" autoresize style="height: 240px" />
          </el-card>
        </el-col>
        <!-- Memory Chart -->
        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <template #header>内存 / Swap</template>
            <v-chart :option="memOption" autoresize style="height: 240px" />
          </el-card>
        </el-col>
      </el-row>

      <!-- GPU -->
      <el-row :gutter="16" v-if="snapshot.gpu?.available" style="margin-top: 16px">
        <el-col :span="24">
          <el-card shadow="hover" class="chart-card">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span>GPU 监控</span>
                <el-button size="small" @click="fetchAllGpuProcs" :loading="gpuProcsLoading">全部 GPU 进程</el-button>
              </div>
            </template>
            <el-row :gutter="12">
              <el-col :span="12" v-for="gpu in snapshot.gpu.devices" :key="gpu.index">
                <div class="gpu-card">
                  <strong>{{ gpu.name || 'GPU ' + gpu.index }}</strong>
                  <div class="gpu-stats">
                    <span>利用率: {{ gpu.gpu_util }}%</span>
                    <span>显存: {{ fmtBytes(gpu.memory_used) }} / {{ fmtBytes(gpu.memory_total) }}</span>
                    <span v-if="gpu.temperature">温度: {{ gpu.temperature }}°C</span>
                    <span v-if="gpu.fan_speed">风扇: {{ gpu.fan_speed }}%</span>
                  </div>
                  <el-progress :percentage="gpu.memory_percent" :stroke-width="12" />
                  <!-- 每卡进程表 -->
                  <div v-if="gpu.processes?.length" class="gpu-proc-table">
                    <div class="gpu-proc-header">该卡进程 ({{ gpu.processes.length }})</div>
                    <div v-for="p in gpu.processes" :key="p.pid" class="gpu-proc-row">
                      <div class="gpu-proc-main">
                        <el-tag :type="p.type === 'compute' ? 'primary' : 'info'" size="small">{{ p.type }}</el-tag>
                        <span class="gpu-proc-name" :title="p.cmdline">{{ p.name || 'PID ' + p.pid }}</span>
                        <small class="gpu-proc-mem">{{ fmtBytes(p.memory_used) }}</small>
                      </div>
                      <div class="gpu-proc-actions">
                        <el-button size="small" text @click="openGpuProcFolder(p.pid)" title="打开启动目录">
                          <el-icon><FolderOpened /></el-icon>
                        </el-button>
                        <el-button size="small" text @click="copyGpuCmd(p)" title="复制启动命令">
                          <el-icon><CopyDocument /></el-icon>
                        </el-button>
                        <el-button size="small" text @click="showGpuProcDetail(p.pid)" title="详情">
                          <el-icon><View /></el-icon>
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>

      <!-- Network -->
      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <template #header>网络速率</template>
            <v-chart :option="netOption" autoresize style="height: 200px" />
          </el-card>
        </el-col>
        <!-- Disks -->
        <el-col :span="12">
          <el-card shadow="hover" class="chart-card">
            <template #header>
              <div class="card-head-row">
                <span>磁盘使用</span>
                <el-button size="small" text type="primary" @click="diskView = diskView === 'list' ? 'treemap' : 'list'">
                  <el-icon><Grid v-if="diskView === 'list'" /><List v-else /></el-icon>
                  {{ diskView === 'list' ? '方块图' : '列表' }}
                </el-button>
              </div>
            </template>
            <div v-if="diskView === 'list'">
              <div v-for="d in snapshot.disks" :key="d.mountpoint" class="disk-row">
                <span>{{ d.mountpoint }} ({{ d.device }})</span>
                <el-progress :percentage="d.percent" :color="d.percent > 90 ? '#f56c6c' : '#e91e63'" :stroke-width="8" />
                <small>{{ fmtBytes(d.used) }} / {{ fmtBytes(d.total) }}</small>
              </div>
            </div>
            <template v-else>
              <div v-if="diskPath" class="disk-crumbs">
                <el-button size="small" text type="primary" @click="diskBackToRoot">
                  <el-icon><Back /></el-icon> 返回分区
                </el-button>
                <span class="disk-crumb-text">{{ diskPath }}</span>
              </div>
              <VChart :option="diskTreemapOption" class="disk-treemap" autoresize @click="onDiskTreemapClick" @contextmenu="onTreemapContextMenu" />
            </template>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <!-- 全部 GPU 进程 -->
    <el-dialog v-model="gpuProcsVisible" title="全部 GPU 进程" width="800px">
      <el-table :data="allGpuProcs" size="small" stripe max-height="450">
        <el-table-column label="GPU" width="90">
          <template #default="{ row }">#{{ row.gpu_index }}</template>
        </el-table-column>
        <el-table-column prop="name" label="进程名" width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="row.type === 'compute' ? 'primary' : 'info'" size="small">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="显存" width="100">
          <template #default="{ row }">{{ fmtBytes(row.memory_used) }}</template>
        </el-table-column>
        <el-table-column prop="cmdline" label="命令行" show-overflow-tooltip />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openGpuProcFolder(row.pid)" title="打开启动目录">
              <el-icon><FolderOpened /></el-icon> 目录
            </el-button>
            <el-button size="small" text @click="copyGpuCmd(row)" title="复制启动命令">
              <el-icon><CopyDocument /></el-icon>
            </el-button>
            <el-button size="small" text @click="showGpuProcDetail(row.pid)" title="详情">
              <el-icon><View /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- GPU 进程详情 -->
    <el-dialog v-model="gpuDetailVisible" title="GPU 进程详情" width="650px">
      <el-descriptions v-if="gpuDetail.found" :column="2" border size="small">
        <el-descriptions-item label="PID">{{ gpuDetail.pid }}</el-descriptions-item>
        <el-descriptions-item label="进程名">{{ gpuDetail.name }}</el-descriptions-item>
        <el-descriptions-item label="用户">{{ gpuDetail.username }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ gpuDetail.status }}</el-descriptions-item>
        <el-descriptions-item label="内存占用">{{ gpuDetail.memory_percent }}%</el-descriptions-item>
        <el-descriptions-item label="启动时间">
          {{ gpuDetail.create_time ? new Date(gpuDetail.create_time * 1000).toLocaleString() : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="工作目录" :span="2">
          <code>{{ gpuDetail.cwd || '-' }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="完整命令" :span="2">
          <pre class="gpu-cmd">{{ gpuDetail.cmdline_str }}</pre>
        </el-descriptions-item>
        <el-descriptions-item label="父进程链" :span="2">
          <div v-for="(c, i) in gpuDetail.parent_chain" :key="i" style="font-size:12px">
            {{ i > 0 ? '← ' : '' }}{{ c.name }} ({{ c.pid }}) <small>{{ c.cmdline }}</small>
          </div>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert v-else :title="gpuDetail.error || '进程不存在'" type="warning" :closable="false" />
      <template #footer>
        <el-button @click="gpuDetailVisible = false">关闭</el-button>
        <el-button v-if="gpuDetail.cwd" @click="copyText(gpuDetail.cwd)">复制工作目录</el-button>
        <el-button v-if="gpuDetail.cmdline_str" @click="copyText(gpuDetail.cmdline_str)">复制启动命令</el-button>
        <el-button v-if="gpuDetail.cwd" type="primary" @click="openGpuProcFolder(gpuDetail.pid)">打开目录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { use } from 'echarts/core'
import { LineChart, GaugeChart, TreemapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import { useSystemStore } from '../stores/system'

use([LineChart, GaugeChart, TreemapChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])

const systemStore = useSystemStore()
const snapshot = computed(() => systemStore.snapshot)
const history = computed(() => systemStore.history)

// 磁盘视图：列表 / 方块图（treemap，可下钻到文件夹）
const diskView = ref('list')
const diskPath = ref(null)  // null = 分区视图；字符串 = 当前下钻路径
const diskDrill = ref([])   // 当前路径下的子项占用

const diskTreemapOption = computed(() => {
  const colorOf = pct => pct > 85 ? '#f56c6c' : pct > 60 ? '#e6a23c' : '#67c23a'

  // 下钻视图：当前路径下每个文件夹/文件的占用方块
  if (diskPath.value !== null) {
    const items = diskDrill.value
    return {
      tooltip: {
        formatter: info => {
          const d = info.data
          return `<b>${d.name}</b><br/>占用: ${fmtBytes(d.size)}<br/>${d.is_dir ? '左键进入 · 右键打开文件管理器' : '文件'}`
        },
      },
      series: [{
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: p => `${p.name}\n${fmtBytes(p.data.size)}`,
          fontSize: 11,
          color: '#fff',
          fontWeight: 'bold',
        },
        itemStyle: { borderColor: '#fff', borderWidth: 1.5, gapWidth: 1.5 },
        data: items.map(x => ({
          name: x.name,
          value: x.size,
          size: x.size,
          path: x.path,
          is_dir: x.is_dir,
          itemStyle: { color: x.is_dir ? '#e91e63' : '#aea79f' },
        })),
      }],
    }
  }

  // 分区视图
  const disks = snapshot.value?.disks || []
  return {
    tooltip: {
      formatter: info => {
        const d = info.data
        return `<b>${d.name}</b><br/>已用: ${fmtBytes(d.used)} / ${fmtBytes(d.total)}<br/>使用率: ${d.percent}%<br/>左键进入 · 右键打开文件管理器`
      },
    },
    series: [{
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      label: {
        show: true,
        formatter: p => `${p.name}\n${p.data.percent}%`,
        fontSize: 12,
        color: '#fff',
        fontWeight: 'bold',
      },
      itemStyle: { borderColor: '#fff', borderWidth: 2, gapWidth: 2 },
      data: disks
        .filter(d => d.total > 1024 * 1024 * 1024) // 过滤 <1GB 的 snap 微分区，保持方块图清晰
        .map(d => ({
          name: d.mountpoint,
          value: d.used,
          path: d.mountpoint,  // 下钻入口
          is_dir: true,
          percent: d.percent,
          used: d.used,
          total: d.total,
          itemStyle: { color: colorOf(d.percent) },
        })),
    }],
  }
})

// 加载某路径下的子项占用（SpaceSniffer 式下钻）
async function loadDiskUsage(path) {
  try {
    const { data } = await api.get('/files/disk-usage', { params: { path } })
    diskDrill.value = data.items || []
  } catch (_) { diskDrill.value = [] }
}

function diskBackToRoot() {
  diskPath.value = null
  diskDrill.value = []
}

// 方块图点击：分区视图点击分区 → 下钻；下钻视图点击文件夹 → 继续下钻
function onDiskTreemapClick(params) {
  const d = params?.data
  if (!d) return
  if (diskPath.value === null) {
    if (d.path) { diskPath.value = d.path; loadDiskUsage(d.path) }
  } else {
    if (d.is_dir && d.path) { diskPath.value = d.path; loadDiskUsage(d.path) }
  }
}

// 右键方块：用系统文件管理器打开对应路径（方便删除等操作）
async function openInFileManager(path) {
  if (!path) return
  try {
    const { data } = await api.post('/files/open-file-manager', null, { params: { path } })
    if (data && data.ok) ElMessage.success('已打开文件管理器')
    else ElMessage.error(data?.error || '打开失败')
  } catch (_) { ElMessage.error('打开失败') }
}

function onTreemapContextMenu(params) {
  const d = params?.data
  if (d && d.path) openInFileManager(d.path)
}

// CPU chart option
const cpuOption = computed(() => {
  const timestamps = history.value.map(h => new Date(h.ts * 1000).toLocaleTimeString())
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['CPU 总使用率'], top: 0 },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: timestamps.slice(-60), boundaryGap: false },
    yAxis: { type: 'value', max: 100 },
    series: [{
      name: 'CPU 总使用率', type: 'line', smooth: true, symbol: 'none',
      data: history.value.map(h => h.cpu?.total || 0).slice(-60),
      areaStyle: { opacity: 0.15 },
      lineStyle: { color: '#e91e63' },
      itemStyle: { color: '#e91e63' },
    }],
  }
})

const memOption = computed(() => {
  const timestamps = history.value.map(h => new Date(h.ts * 1000).toLocaleTimeString())
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['内存', 'Swap'], top: 0 },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: timestamps.slice(-60), boundaryGap: false },
    yAxis: { type: 'value', max: 100 },
    series: [
      {
        name: '内存', type: 'line', smooth: true, symbol: 'none',
        data: history.value.map(h => h.memory?.percent || 0).slice(-60),
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: '#e6a23c' },
        itemStyle: { color: '#e6a23c' },
      },
      {
        name: 'Swap', type: 'line', smooth: true, symbol: 'none',
        data: history.value.map(h => h.swap?.percent || 0).slice(-60),
        lineStyle: { color: '#aea79f' },
        itemStyle: { color: '#aea79f' },
      },
    ],
  }
})

const netOption = computed(() => {
  const timestamps = []
  const downloadRates = []
  const uploadRates = []

  const hist = history.value
  for (let i = 1; i < hist.length; i++) {
    const prev = hist[i - 1]
    const curr = hist[i]
    const dt = curr.ts - prev.ts
    if (dt <= 0) continue

    const bytesRecv = (curr.network?.bytes_recv || 0) - (prev.network?.bytes_recv || 0)
    const bytesSent = (curr.network?.bytes_sent || 0) - (prev.network?.bytes_sent || 0)

    timestamps.push(new Date(curr.ts * 1000).toLocaleTimeString())
    downloadRates.push(bytesRecv > 0 ? Math.round(bytesRecv / dt) : 0)
    uploadRates.push(bytesSent > 0 ? Math.round(bytesSent / dt) : 0)
  }

  return {
    tooltip: { trigger: 'axis', valueFormatter: v => fmtBytes(v) + '/s' },
    legend: { data: ['下载', '上传'], top: 0 },
    grid: { left: 55, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: timestamps.slice(-60), boundaryGap: false },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtBytes(v) + '/s' } },
    series: [
      {
        name: '下载', type: 'line', smooth: true, symbol: 'none',
        data: downloadRates.slice(-60),
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: '#67c23a' },
        itemStyle: { color: '#67c23a' },
      },
      {
        name: '上传', type: 'line', smooth: true, symbol: 'none',
        data: uploadRates.slice(-60),
        lineStyle: { color: '#e91e63' },
        itemStyle: { color: '#e91e63' },
      },
    ],
  }
})

const cpuColor = computed(() => {
  const v = snapshot.value?.cpu?.total || 0
  return v > 80 ? '#f56c6c' : v > 50 ? '#e6a23c' : '#67c23a'
})
const memColor = computed(() => (snapshot.value?.memory?.percent || 0) > 80 ? '#f56c6c' : '#606266')
const gpuMemColor = computed(() => {
  const v = snapshot.value?.gpu?.devices?.[0]?.memory_percent || 0
  return v > 90 ? '#f56c6c' : v > 70 ? '#e6a23c' : '#67c23a'
})
const rootDiskPercent = computed(() => snapshot.value?.disks?.find(d => d.mountpoint === '/')?.percent || 0)

function fmtBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return bytes.toFixed(1) + ' ' + units[i]
}

// ── GPU 进程操作 ──
import { ElMessage } from 'element-plus'
import api from '../api'

const gpuProcsVisible = ref(false)
const allGpuProcs = ref([])
const gpuProcsLoading = ref(false)
const gpuDetailVisible = ref(false)
const gpuDetail = ref({})

async function fetchAllGpuProcs() {
  gpuProcsVisible.value = true
  gpuProcsLoading.value = true
  try {
    const { data } = await api.get('/system/gpu/processes')
    allGpuProcs.value = data.processes || []
  } catch (_) { allGpuProcs.value = [] }
  gpuProcsLoading.value = false
}

async function showGpuProcDetail(pid) {
  try {
    const { data } = await api.get(`/system/gpu/proc/${pid}`)
    gpuDetail.value = data
    gpuDetailVisible.value = true
  } catch (_) { ElMessage.error('获取详情失败') }
}

async function openGpuProcFolder(pid) {
  try {
    const { data } = await api.post(`/system/gpu/proc/${pid}/open-folder`)
    if (data.ok) ElMessage.success('已打开: ' + data.path)
    else ElMessage.error(data.error || '打开失败')
  } catch (_) { ElMessage.error('请求失败') }
}

async function copyGpuCmd(proc) {
  const cmd = proc.cmdline || ''
  await copyText(cmd)
}

async function copyText(text) {
  if (!text) { ElMessage.warning('无内容可复制'); return }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch (_) {
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el)
    ElMessage.success('已复制')
  }
}

onMounted(() => {
  systemStore.startMonitor()
})

onUnmounted(() => {
  systemStore.stopMonitor()
})
</script>

<style scoped>
.system-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.quick-stats { margin-bottom: 20px; }
.chart-card { margin-bottom: 0; }
.gpu-card { margin-bottom: 12px; }
.gpu-stats { display: flex; gap: 16px; margin: 8px 0; font-size: 13px; color: var(--el-text-color-secondary); flex-wrap: wrap; }
.gpu-proc-table { margin-top: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: var(--radius-md); padding: 6px; }
.gpu-proc-header { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.gpu-proc-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 3px 0; border-bottom: 1px solid var(--el-border-color-extra-light); }
.gpu-proc-row:last-child { border-bottom: none; }
.gpu-proc-main { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1; }
.gpu-proc-name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gpu-proc-mem { color: var(--el-text-color-secondary); font-size: 11px; flex-shrink: 0; }
.gpu-proc-actions { display: flex; flex-shrink: 0; }
.gpu-cmd { background: var(--el-fill-color-light); padding: 8px; border-radius: var(--radius-sm); font-size: 12px; word-break: break-all; }
.disk-row { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.disk-row:last-child { border-bottom: none; }
.disk-treemap { width: 100%; height: 260px; }
.card-head-row { display: flex; justify-content: space-between; align-items: center; }
.disk-crumbs { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.disk-crumb-text { font-size: 12px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
