<template>
  <div class="logs-view">
    <h2 class="page-title">日志查看器</h2>
    <div class="toolbar">
      <el-input v-model="logPath" placeholder="输入日志文件路径..." class="path-input" @keyup.enter="openLog">
        <template #append><el-button @click="openLog">打开</el-button></template>
      </el-input>
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
    <el-empty v-else description="输入日志文件路径并点击「打开」" />

    <!-- 多日志聚合 Dialog -->
    <el-dialog v-model="showAggregate" title="多日志聚合" width="800px">
      <el-input v-model="aggregatePaths" placeholder="多个日志路径，逗号分隔" style="margin-bottom: 8px" />
      <el-input v-model="aggregateKeywords" placeholder="过滤关键词，逗号分隔（可选）" style="margin-bottom: 12px" />
      <el-radio-group v-model="aggregateMode" style="margin-bottom: 12px">
        <el-radio-button value="interleave">交错显示</el-radio-button>
        <el-radio-button value="timeline">时间线对齐</el-radio-button>
      </el-radio-group>
      <el-button type="primary" @click="doAggregate" :loading="aggLoading">加载</el-button>
      <div class="aggregate-result" style="margin-top: 12px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 12px">
        <div v-for="(l, i) in aggregateLines" :key="i" :class="['log-line', l.level]">
          <el-tag size="small" :type="l.source ? 'info' : ''" style="margin-right: 8px">{{ l.source }}</el-tag>
          <span>{{ l.text }}</span>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { subscribeLogTail } from '../api/ws'

const logPath = ref(''); const logTabs = ref([]); const activeTab = ref(0)
const tailMode = ref(false); const filterText = ref(''); const filterLevel = ref('')
const searchPattern = ref(''); const searchResults = ref([])
const showAggregate = ref(false); const aggregatePaths = ref(''); const aggregateKeywords = ref('')
const aggregateMode = ref('interleave'); const aggregateLines = ref([]); const aggLoading = ref(false)
let tailUnsubs = {}

const logLines = computed(() => logTabs.value[activeTab.value]?.lines || [])
const filteredLines = computed(() => {
  let lines = logLines.value
  if (filterText.value) { const q = filterText.value.toLowerCase(); lines = lines.filter(l => l.text.toLowerCase().includes(q)) }
  if (filterLevel.value) lines = lines.filter(l => l.level === filterLevel.value)
  return lines
})

async function openLog() {
  const path = logPath.value.trim(); if (!path) return
  const ex = logTabs.value.findIndex(t => t.path === path)
  if (ex >= 0) { activeTab.value = ex; return }
  try { const { data } = await api.get('/logs', { params: { path, offset: 0, limit: 500 } })
    logTabs.value.push({ path, lines: data.lines || [] }); activeTab.value = logTabs.value.length - 1; logPath.value = '' } catch (_) { ElMessage.error('无法打开') }
}
function switchTab(i) { activeTab.value = i; searchResults.value = [] }
function closeLogTab(i) { const t = logTabs.value[i]; if (tailUnsubs[t.path]) { tailUnsubs[t.path](); delete tailUnsubs[t.path] } logTabs.value.splice(i, 1); if (activeTab.value >= logTabs.value.length) activeTab.value = Math.max(0, logTabs.value.length - 1) }
function toggleTail(v) { const t = logTabs.value[activeTab.value]; if (!t) return
  if (v) { tailUnsubs[t.path] = subscribeLogTail(t.path, (d) => { if (d.text) { t.lines.push(d); if (t.lines.length > 5000) t.lines.shift() } }) }
  else { if (tailUnsubs[t.path]) { tailUnsubs[t.path](); delete tailUnsubs[t.path] } }
}
async function doSearch() { const p = searchPattern.value.trim(); const t = logTabs.value[activeTab.value]; if (!p || !t) return
  try { const { data } = await api.get('/logs/search', { params: { path: t.path, pattern: p } }); searchResults.value = data.matches || [] } catch (_) {} }
async function doAggregate() {
  aggLoading.value = true
  const ep = aggregateMode.value === 'timeline' ? '/logs/timeline' : '/logs/aggregate'
  try { const { data } = await api.get(ep, { params: { paths: aggregatePaths.value, keywords: aggregateKeywords.value, limit: 500 } })
    aggregateLines.value = data.lines || [] } catch (_) { ElMessage.error('加载失败') }
  aggLoading.value = false
}
function getFileName(p) { return p.split('/').pop() || p }

onUnmounted(() => { for (const u of Object.values(tailUnsubs)) if (typeof u === 'function') u() })
</script>

<style scoped>
.logs-view { padding: 20px; height: 100vh; display: flex; flex-direction: column; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; flex-shrink: 0; }
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
.log-line.info { color: #409eff; }
.line-num { width: 50px; flex-shrink: 0; color: var(--el-text-color-disabled); text-align: right; user-select: none; }
</style>
