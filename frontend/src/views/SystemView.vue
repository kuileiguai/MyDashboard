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
                <span>磁盘使用<span v-if="diskPath" style="font-weight: 400; font-size: 12px; color: var(--el-text-color-secondary)"> · {{ diskPath }}</span></span>
                <el-button size="small" text type="primary" @click="toggleDiskView">
                  <el-icon><Grid v-if="diskView === 'list'" /><List v-else /></el-icon>
                  {{ diskView === 'list' ? '方块图' : '列表' }}
                </el-button>
              </div>
            </template>
            <div v-if="diskView === 'list'">
              <!-- 顶部状态条：下钻路径下显示面包屑（与 treemap 一致） -->
              <div v-if="diskPath" class="disk-crumbs">
                <el-button size="small" text type="primary" @click="diskBackToRoot">
                  <el-icon><Back /></el-icon> 分区
                </el-button>
                <span class="disk-crumb-sep">/</span>
                <template v-for="(seg, idx) in diskPathSegments" :key="idx">
                  <el-button
                    size="small"
                    :type="idx === diskPathSegments.length - 1 ? 'primary' : 'default'"
                    text
                    :title="`下钻到 ${seg.full}`"
                    @click="loadDiskUsage(seg.full)">
                    {{ seg.name }}
                  </el-button>
                  <span v-if="idx < diskPathSegments.length - 1" class="disk-crumb-sep">/</span>
                </template>
                <span v-if="diskLoading" class="disk-meta">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  已扫 {{ diskScanned }}/{{ diskTotalDirs }}
                </span>
              </div>

              <!-- 分区视图：渲染真实分区 -->
              <template v-if="diskPath === null">
                <div v-for="d in snapshot.disks" :key="d.mountpoint" class="disk-row disk-row-clickable"
                     @click="onDiskRowClick(d)" :title="`点击下钻到 ${d.mountpoint}`">
                  <div class="disk-row-head">
                    <span>{{ d.mountpoint }} <small class="disk-row-device">({{ d.device }})</small></span>
                    <small>
                      <template v-if="d.du_used != null">
                        <b>{{ fmtBytes(d.du_used) }}</b> / {{ fmtBytes(d.total) }}
                        <span class="disk-row-delta" v-if="Math.abs(d.du_used - d.used) > 1024 * 1024">
                          (df: {{ fmtBytes(d.used) }})
                        </span>
                      </template>
                      <template v-else>
                        {{ fmtBytes(d.used) }} / {{ fmtBytes(d.total) }}
                        <span class="disk-row-delta">du 计算中…</span>
                      </template>
                    </small>
                  </div>
                  <el-progress :percentage="diskRowPercent(d)" :color="diskRowPercent(d) > 90 ? '#f56c6c' : '#e91e63'" :stroke-width="8" />
                </div>
              </template>

              <!-- 下钻视图：渲染当前目录的子项（与 treemap 同一份数据） -->
              <template v-else>
                <div v-if="diskItems.length === 0 && !diskLoading" class="disk-empty">
                  <el-icon><WarningFilled /></el-icon>
                  <span>该目录为空或无法读取</span>
                </div>
                <div v-for="d in diskItems" :key="d.path"
                     class="disk-row disk-row-clickable"
                     :class="{ 'disk-row-disabled': !d.is_dir || d.is_vfs || d.is_others || d.pending }"
                     @click="onDiskRowClick(d)"
                     :title="d.is_dir && !d.is_vfs && !d.is_others && !d.pending ? `点击下钻到 ${d.path}` : (d.is_vfs ? '虚拟文件系统，不能下钻' : d.is_others ? '聚合方块，不能下钻' : d.pending ? '正在计算…' : '文件，不能下钻')">
                  <div class="disk-row-head">
                    <span>
                      <el-icon v-if="d.is_dir && !d.is_vfs && !d.is_others"><Folder /></el-icon>
                      <el-icon v-else-if="d.is_vfs"><Warning /></el-icon>
                      <el-icon v-else><Document /></el-icon>
                      {{ d.name }}
                    </span>
                    <small>
                      <template v-if="d.pending">
                        <span class="disk-row-delta">计算中…</span>
                      </template>
                      <template v-else-if="d.size_timeout">
                        <span class="disk-row-delta">du 超时</span>
                      </template>
                      <template v-else>
                        {{ fmtBytes(d.size) }}
                      </template>
                    </small>
                  </div>
                  <!-- 进度条：相对于当前路径总和 -->
                  <el-progress v-if="!d.pending && !d.size_timeout"
                               :percentage="diskChildPercent(d)"
                               :color="diskChildPercent(d) > 90 ? '#f56c6c' : '#e91e63'"
                               :stroke-width="6"
                               :show-text="false" />
                  <div v-else class="disk-row-progress-placeholder"></div>
                </div>
                <!-- "其他" 行（聚合）：diskItems.length 是后端 limit（默认 80），
                     实际未展示的子项数 = 后端 items_all 长度 - limit；此处按"未渲染"估算为 0 不显示具体数字 -->
                <div v-if="diskOthersSize > 0 && !diskTruncated" class="disk-row disk-row-disabled disk-row-others">
                  <div class="disk-row-head">
                    <span>其他（剩余子项汇总）</span>
                    <small>{{ fmtBytes(diskOthersSize) }}</small>
                  </div>
                </div>
              </template>
            </div>
            <template v-else>
              <div v-if="diskPath" class="disk-crumbs">
                <el-button size="small" text type="primary" @click="diskBackToRoot">
                  <el-icon><Back /></el-icon> 分区
                </el-button>
                <span class="disk-crumb-sep">/</span>
                <!-- 路径面包屑：每一段都可点击跳回 -->
                <template v-for="(seg, idx) in diskPathSegments" :key="idx">
                  <el-button
                    size="small"
                    :type="idx === diskPathSegments.length - 1 ? 'primary' : 'default'"
                    text
                    :title="`下钻到 ${seg.full}`"
                    @click="loadDiskUsage(seg.full)">
                    {{ seg.name }}
                  </el-button>
                  <span v-if="idx < diskPathSegments.length - 1" class="disk-crumb-sep">/</span>
                </template>
                <span v-if="diskLoading" class="disk-meta">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  已扫 {{ diskScanned }}/{{ diskTotalDirs }}
                </span>
                <span v-else-if="diskTruncated" class="disk-warn">
                  <el-icon><Warning /></el-icon>
                  部分目录超时，已显示前 {{ diskItems.length }} 项；其他占 {{ fmtBytes(diskOthersSize) }}
                </span>
                <span v-else-if="diskElapsed > 800" class="disk-meta">
                  扫描 {{ (diskElapsed / 1000).toFixed(1) }}s
                </span>
              </div>
              <div class="disk-treemap-wrap">
                <!-- vue-echarts 6.x 根元素是自定义元素 x-vue-echarts（自带 height:100%），
                     父级高度 auto 时会塌陷成 0 → 必须用内联高度（与 CPU/内存/网络图表一致） -->
                <VChart :key="diskPath || '__root__'" :option="diskTreemapOption" style="height: 260px" autoresize
                        @click="onDiskTreemapClick" @contextmenu="onTreemapContextMenu" />
                <div v-if="diskLoading && diskItems.length === 0" class="disk-loading">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>扫描 {{ diskPath }}</span>
                </div>
                <div v-else-if="diskPath && !diskLoading && diskItems.length === 0" class="disk-loading">
                  <el-icon><WarningFilled /></el-icon>
                  <span>该目录为空或无法读取</span>
                </div>
              </div>
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
          <div v-if="!gpuDetail.cwd && gpuDetail.cwd_error_text" class="gpu-cwd-hint">
            {{ gpuDetail.cwd_error_text }}
          </div>
          <div v-if="!gpuDetail.cwd && gpuDetail.cwd_guess" class="gpu-cwd-hint">
            推断目录: {{ gpuDetail.cwd_guess }}
          </div>
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
        <el-button v-if="gpuDetail.cwd || gpuDetail.cwd_guess" type="primary" @click="openGpuProcFolder(gpuDetail.pid)">
          {{ gpuDetail.cwd ? '打开目录' : '打开推断目录' }}
        </el-button>
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
const diskPath = ref(null)       // null = 分区视图；字符串 = 当前下钻路径
const diskDrill = ref([])        // 当前路径下的子项占用
const diskLoading = ref(false)   // 是否正在扫描
const diskTruncated = ref(false) // 后端 du 是否超时（结果不完整）
const diskOthersSize = ref(0)    // "其他" 子项汇总占用
const diskElapsed = ref(0)       // 扫描耗时 ms
const diskScanned = ref(0)       // 已并发 du 完的目录数
const diskTotalDirs = ref(0)     // 总目录数
let _diskUsageAbort = null       // 当前进行中的请求 AbortController

const diskItems = computed(() => diskDrill.value)

// 当前下钻路径分段：['/', '/home', '/home/user'] → 每段都是可点击的下钻目标
const diskPathSegments = computed(() => {
  const p = diskPath.value
  if (!p) return []
  const parts = p.split('/').filter(Boolean)  // 去掉空段（针对以 / 开头的绝对路径）
  const segs = []
  let acc = ''
  // 始终以 / 开头
  if (p.startsWith('/')) acc = '/'
  for (const part of parts) {
    acc = (acc === '/' ? '' : acc) + '/' + part
    segs.push({ name: part, full: acc })
  }
  // 根路径是 '/' 时
  if (segs.length === 0 && p === '/') {
    segs.push({ name: '/', full: '/' })
  }
  return segs
})

// 工具：把目录项按"文件优先 + size 降序"排序（流式更新时维持稳定排序）
function _sortDiskDrill() {
  diskDrill.value.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? 1 : -1
    return (b.size || 0) - (a.size || 0)
  })
}

const diskTreemapOption = computed(() => {
  const colorOf = pct => pct > 85 ? '#f56c6c' : pct > 60 ? '#e6a23c' : '#67c23a'

  // 下钻视图：当前路径下每个文件夹/文件的占用方块
  if (diskPath.value !== null) {
    const items = diskDrill.value
    const data = items.map(x => {
      const is_vfs = !!x.is_vfs
      // pending：还在并发 du 中的目录，用最小占位让 treemap 仍能渲染
      // vfs：procfs/sysfs/devtmpfs，不占真实空间，给 1KB 占位即可
      const v = is_vfs ? 1024
              : (x.size > 0 ? x.size : (x.is_dir ? 1024 : 1))
      return {
        name: is_vfs ? `⊘ ${x.name}`
              : x.pending ? `${x.name}…`
              : x.name,
        value: v,
        size: x.size,
        path: x.path,
        is_dir: x.is_dir,
        pending: x.pending || false,
        is_vfs,
        size_timeout: !!x.size_timeout,
        itemStyle: {
          color: is_vfs ? '#bbb'
                : x.pending ? '#cfcfcf'
                : x.size_timeout ? '#f0ad4e'
                : (x.is_dir ? '#e91e63' : '#aea79f'),
        },
      }
    })
    // 若有 "其他"，追加一个聚合方块（不可下钻）
    if (diskOthersSize.value > 0 && !diskTruncated.value) {
      data.push({
        name: '其他',
        value: diskOthersSize.value,
        size: diskOthersSize.value,
        path: null,  // 不可下钻
        is_dir: false,
        is_others: true,  // 标记"其他"方块
        itemStyle: { color: '#bbb' },
      })
    }
    return {
      tooltip: {
        formatter: info => {
          const d = info.data
          if (d.is_others) return `<b>${d.name}</b><br/>占用: ${fmtBytes(d.size)}<br/>（剩余子项的汇总）`
          if (d.is_vfs) return `<b>${d.name}</b><br/>虚拟文件系统（procfs/sysfs/devtmpfs 等）<br/>不计入磁盘占用`
          if (d.pending) return `<b>${d.name}</b><br/>正在计算…`
          if (d.size_timeout) return `<b>${d.name}</b><br/>du 超时（占用未知）<br/>左键可重试`
          return `<b>${d.name}</b><br/>占用: ${fmtBytes(d.size)}<br/>${d.is_dir ? '左键进入下钻 · 右键打开文件管理器' : '文件（不可下钻）'}`
        },
      },
      series: [{
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: p => p.data.is_vfs
            ? `${p.name}\n虚拟文件系统`
            : p.data.pending
              ? `${p.name}\n计算中…`
              : p.data.size_timeout
                ? `${p.name}\ndu 超时`
                : p.data.is_others
                  ? p.name
                  : `${p.name}\n${fmtBytes(p.data.size)}`,
          fontSize: 11,
          // label.color 不支持回调（ECharts 会把函数源码当颜色字符串用），只能给固定值
          color: '#fff',
          fontWeight: 'bold',
        },
        itemStyle: { borderColor: '#fff', borderWidth: 1.5, gapWidth: 1.5 },
        cursor: 'default',  // 默认不可点
        // 用 emphasis + upperLabel 提示哪些可点
        upperLabel: { show: false },
        data: data.map(d => ({
          ...d,
          itemStyle: {
            ...(d.itemStyle || {}),
            // pending / 其他 / vfs / 文件 = 不可下钻（鼠标变 not-allowed）
            // 目录 = 可下钻
            cursor: d.pending || d.is_others || d.is_vfs || !d.is_dir
              ? 'not-allowed'
              : 'pointer',
          },
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
        return `<b>${d.name}</b><br/>已用: ${fmtBytes(d.used)} / ${fmtBytes(d.total)}<br/>使用率: ${d.percent}%<br/>左键下钻 · 右键打开文件管理器`
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
      cursor: 'default',
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
          cursor: 'pointer',  // 分区都可下钻
        })),
    }],
  }
})

// 加载某路径下的子项占用（仿 ncdu/Baobab：scandir 一级立即返回 + 并发 du 渐进式推送）
// 用 fetch + ReadableStream 订阅 NDJSON 流，每完成一个子目录的 du 就更新 UI
async function loadDiskUsage(path) {
  // 取消上一次
  if (_diskUsageAbort) {
    try { _diskUsageAbort.abort() } catch (_) {}
  }
  const controller = new AbortController()
  _diskUsageAbort = controller

  diskPath.value = path
  diskDrill.value = []
  diskLoading.value = true
  diskTruncated.value = false
  diskOthersSize.value = 0
  diskElapsed.value = 0
  diskScanned.value = 0
  diskTotalDirs.value = 0

  const params = new URLSearchParams({
    path,
    limit: '80',
    timeout: '15',
    concurrent: '8',
    stream: 'true',
  })

  let res
  try {
    res = await fetch(`/api/files/disk-usage?${params}`, {
      signal: controller.signal,
      headers: { Accept: 'application/x-ndjson' },
    })
  } catch (err) {
    if (controller.signal.aborted) return
    diskLoading.value = false
    diskDrill.value = []
    ElMessage.error(`扫描 ${path} 失败: ${err?.message || '网络错误'}`)
    return
  }

  if (!res.ok) {
    diskLoading.value = false
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || detail
    } catch (_) {}
    ElMessage.error(`扫描 ${path} 失败: ${detail}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })

      // 按 NDJSON 行切分（每行一个 JSON 对象）
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim()
        buf = buf.slice(nl + 1)
        if (!line) continue
        let msg
        try { msg = JSON.parse(line) } catch (_) { continue }
        if (controller.signal.aborted) return
        _applyStreamEvent(msg)
        if (msg.phase === 'done') return
      }
    }
    // 流自然结束
    buf += decoder.decode()
    if (buf.trim()) {
      try { _applyStreamEvent(JSON.parse(buf.trim())) } catch (_) {}
    }
  } catch (err) {
    if (controller.signal.aborted) return
    console.error('disk-usage stream error:', err)
    ElMessage.error(`扫描 ${path} 中断: ${err?.message || '未知错误'}`)
  } finally {
    if (!controller.signal.aborted) {
      diskLoading.value = false
    }
    try { reader.releaseLock() } catch (_) {}
  }
}

function _applyStreamEvent(msg) {
  if (msg.phase === 'initial') {
    // 第一批：一级子项立刻可见（文件 size 已就位，目录 pending）
    diskDrill.value = (msg.items || []).map(x => ({ ...x }))
    diskOthersSize.value = msg.others_size || 0
    const stats = msg.stats || {}
    diskTotalDirs.value = stats.dirs || 0
    diskScanned.value = 0
  } else if (msg.phase === 'update') {
    // 增量更新某个目录的 size
    const it = msg.item
    if (!it || !it.path) return
    const idx = diskDrill.value.findIndex(x => x.path === it.path)
    if (idx >= 0) {
      diskDrill.value[idx] = {
        ...diskDrill.value[idx],
        size: it.size,
        pending: false,
        size_timeout: !!it.size_timeout,
        is_vfs: !!it.is_vfs,
      }
      diskScanned.value += 1
      // 重新排序（保持文件优先 + 大小降序）
      _sortDiskDrill()
    }
  } else if (msg.phase === 'done') {
    diskTruncated.value = !!msg.truncated
    diskElapsed.value = msg.elapsed_ms || 0
    // 重新计算 others_size（用最新数据）
    const top = 80
    if (diskDrill.value.length > top) {
      diskOthersSize.value = diskDrill.value.slice(top).reduce((s, x) => s + (x.size || 0), 0)
    }
    if (msg.truncated) {
      ElMessage.warning(`扫描 ${diskPath.value} 部分超时，结果可能不完整`)
    }
  }
}

function diskBackToRoot() {
  if (_diskUsageAbort) { try { _diskUsageAbort.abort() } catch (_) {} }
  diskPath.value = null
  diskDrill.value = []
  diskLoading.value = false
  diskTruncated.value = false
  diskOthersSize.value = 0
  diskElapsed.value = 0
  diskScanned.value = 0
  diskTotalDirs.value = 0
}

// 方块图点击：分区视图点击分区 → 下钻；下钻视图点击文件夹 → 继续下钻
function onDiskTreemapClick(params) {
  let d = params?.data
  // 兜底：treemap 的 click params.data 可能为空，此时按 name 反查当前层数据
  if (!d || !d.path) {
    const pool = diskPath.value === null
      ? (snapshot.value?.disks || []).map(x => ({ ...x, name: x.mountpoint, path: x.mountpoint, is_dir: true }))
      : diskDrill.value
    d = pool.find(x => x.name === params?.name) || d
  }
  if (!d || !d.path) {
    console.warn('[disk treemap] 点击未命中数据项', params)
    return
  }

  // pending（正在 du）的方块 → 跳过，du 完成后才能下钻
  if (d.pending) {
    return
  }
  // "其他"聚合方块 → 不可下钻
  if (d.is_others) {
    return
  }
  // vfs（虚拟文件系统）方块 → 不可下钻（没有真实占用数据）
  if (d.is_vfs) {
    ElMessage.info(`${d.name} 是虚拟文件系统（procfs/sysfs/devtmpfs 等），没有下钻意义`)
    return
  }
  // 文件方块 → 不能下钻
  if (!d.is_dir) {
    ElMessage.info(`${d.name} 是文件，不能下钻`)
    return
  }
  // 必须有 path
  if (!d.path) return

  // 下钻：直接调用
  loadDiskUsage(d.path)
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

// 列表行进度条：优先用 du 算的实际占用百分比，否则 fallback 到 df 百分比
function diskRowPercent(d) {
  if (d.du_used != null && d.total) {
    return Math.min(100, Math.round(d.du_used / d.total * 1000) / 10)
  }
  return d.percent || 0
}

// 下钻视图列表行进度条：相对于当前路径下最大项的百分比
// （让大项更显眼，不强制归一化到 100%）
const diskChildMax = computed(() => {
  if (diskDrill.value.length === 0) return 0
  return Math.max(...diskDrill.value.map(x => x.size || 0))
})
function diskChildPercent(d) {
  if (!d.size || diskChildMax.value === 0) return 0
  return Math.min(100, Math.round(d.size / diskChildMax.value * 1000) / 10)
}

// 列表行点击：始终留在当前视图内下钻（列表 → 列表子项，方块图 → 方块图子项）
// 注意：不要把列表强行切成方块图，否则"在列表里下钻看不到下级占用"
function onDiskRowClick(d) {
  if (!d) return
  const path = d.mountpoint || d.path
  if (!path) return
  // 文件 / 虚拟文件系统 / 聚合"其他" / 还在 du 的项 → 不下钻
  if (d.is_dir === false || d.is_vfs || d.is_others) return
  loadDiskUsage(path)
}

// 切换列表/方块图视图。保留当前 diskPath（不重置），下钻路径下也能切换。
function toggleDiskView() {
  diskView.value = diskView.value === 'list' ? 'treemap' : 'list'
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
    if (!data.ok) { ElMessage.error(data.error || '打开失败'); return }
    if (data.guessed) ElMessage.warning(`工作目录不可读，已打开推断目录: ${data.path}`)
    else ElMessage.success('已打开: ' + data.path)
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
  if (_diskUsageAbort) { try { _diskUsageAbort.abort() } catch (_) {} }
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
.gpu-cwd-hint { margin-top: 4px; font-size: 12px; color: var(--el-color-warning); }
.disk-row { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.disk-row:last-child { border-bottom: none; }
.disk-row-clickable { cursor: pointer; transition: background 0.15s; padding-left: 6px; padding-right: 6px; border-radius: 4px; }
.disk-row-clickable:hover { background: var(--el-fill-color-light); }
.disk-row-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.disk-row-device { color: var(--el-text-color-placeholder); font-weight: normal; }
.disk-row-delta { color: var(--el-text-color-secondary); margin-left: 4px; font-size: 11px; }
.disk-row-disabled { cursor: not-allowed !important; opacity: 0.7; }
.disk-row-disabled:hover { background: transparent !important; }
.disk-row-others { cursor: default; opacity: 0.6; }
.disk-row-others:hover { background: var(--el-fill-color-lighter); }
.disk-row-progress-placeholder { height: 6px; background: var(--el-fill-color-lighter); border-radius: 3px; }
.disk-empty { display: flex; align-items: center; gap: 8px; padding: 20px 0; color: var(--el-text-color-secondary); font-size: 13px; }
.disk-empty .el-icon { font-size: 18px; color: var(--el-color-warning); }
/* min-height 兜底：即使图表容器塌陷，覆盖层（扫描中/空目录）也能显示 */
.disk-treemap-wrap { position: relative; min-height: 260px; }
.disk-loading {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  gap: 8px; background: rgba(255,255,255,0.72); color: var(--el-text-color-secondary);
  font-size: 13px; pointer-events: none; z-index: 1;
}
.disk-loading .el-icon { font-size: 16px; color: var(--el-color-primary); }
.card-head-row { display: flex; justify-content: space-between; align-items: center; }
.disk-crumbs { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; flex-wrap: wrap; }
.disk-crumb-text { font-size: 12px; color: var(--el-text-color-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.disk-crumb-sep { color: var(--el-text-color-placeholder); font-size: 12px; }
.disk-warn { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--el-color-warning); }
.disk-warn .el-icon { font-size: 14px; }
.disk-meta { font-size: 12px; color: var(--el-text-color-placeholder); }
</style>
