<template>
  <div class="env-view">
    <h2 class="page-title">环境管理</h2>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- uv 环境 -->
      <el-tab-pane label="uv 环境" name="uv">
        <div class="toolbar">
          <el-button size="small" type="primary" @click="showPathConfig = true">
            <el-icon><Setting /></el-icon> 配置扫描路径
          </el-button>
          <el-button size="small" @click="scanEnvs" :loading="scanLoading">
            <el-icon><Refresh /></el-icon> 扫描发现
          </el-button>
          <span v-if="scanPaths.length" style="font-size:12px;color:var(--el-text-color-secondary)">
            {{ scanPaths.join(', ') }}
          </span>
          <span v-if="envs.uv?.available" style="font-size:12px;color:var(--el-text-color-secondary);margin-left:auto">
            uv {{ envs.uv.version }}
          </span>
        </div>

        <!-- 已纳入管理的环境 -->
        <h4 style="margin-bottom:8px">我的环境 ({{ managedEnvs.length }})</h4>
        <el-empty v-if="!managedEnvs.length" description="点击「扫描发现」找到环境后勾选加入管理" />
        <div v-else>
          <el-input v-model="envFilter" placeholder="搜索..." clearable size="small" style="width:200px;margin-bottom:8px" prefix-icon="Search" />
          <el-table :data="filteredManaged" size="small" stripe>
            <el-table-column label="环境名" min-width="150">
              <template #default="{ row }">
                <strong>{{ row.project_name }}</strong>
                <div v-if="row.remark" style="font-size:11px;color:var(--el-color-primary)">{{ row.remark }}</div>
              </template>
            </el-table-column>
            <el-table-column label="Python" width="90" prop="python_version" />
            <el-table-column label="大小" width="110" sortable prop="size_bytes">
              <template #default="{ row }">{{ row.size_human || '-' }}</template>
            </el-table-column>
            <el-table-column label="路径" show-overflow-tooltip min-width="200">
              <template #default="{ row }"><code style="font-size:11px">{{ row.path }}</code></template>
            </el-table-column>
            <el-table-column label="操作" width="300">
              <template #default="{ row }">
                <template v-if="remarkEditPath === row.path">
                  <el-input v-model="remarkText" placeholder="备注..." size="small" style="width:120px"
                    @keyup.enter="saveRemark(row.path)" @keyup.escape="remarkEditPath = null" />
                  <el-button size="small" type="primary" @click="saveRemark(row.path)" style="margin-left:4px">保存</el-button>
                </template>
                <template v-else>
                  <el-button size="small" text @click="startRemark(row)">{{ row.remark || '备注' }}</el-button>
                </template>
                <el-button size="small" @click="showPackages(row, 'pip')">包列表</el-button>
                <el-button size="small" @click="exportReq(row)">导出 txt</el-button>
                <el-button size="small" type="danger" text @click="removeManaged(row)">移除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top:8px;font-size:12px;color:var(--el-text-color-secondary)">总计 {{ managedEnvs.length }} 个环境，{{ managedTotalSize }}</div>
        </div>

        <!-- 扫描发现（待确认） -->
        <div v-if="unmanagedEnvs.length" style="margin-top: 24px">
          <h4 style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
            扫描发现 ({{ unmanagedEnvs.length }})
            <el-button size="small" type="primary" @click="addAllToManaged" :disabled="!unmanagedEnvs.length">全部纳入</el-button>
          </h4>
          <el-table :data="unmanagedEnvs" size="small" stripe @selection-change="onUnmanagedSelect">
            <el-table-column type="selection" width="40" />
            <el-table-column label="环境名" min-width="150">
              <template #default="{ row }">
                <strong>{{ row.project_name }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="Python" width="90" prop="python_version" />
            <el-table-column label="大小" width="110" prop="size_bytes" sortable>
              <template #default="{ row }">{{ row.size_human || '-' }}</template>
            </el-table-column>
            <el-table-column label="路径" show-overflow-tooltip min-width="200">
              <template #default="{ row }"><code style="font-size:11px">{{ row.path }}</code></template>
            </el-table-column>
          </el-table>
          <div style="margin-top:8px">
            <el-button size="small" type="primary" @click="addSelectedToManaged" :disabled="!unmanagedSelected.length">
              纳入选中 ({{ unmanagedSelected.length }})
            </el-button>
          </div>
        </div>

        <!-- uv 探测到的其他 -->
        <details v-if="envs.uv?.venvs_found?.length" style="margin-top:12px">
          <summary style="cursor:pointer;font-size:13px;color:var(--el-text-color-secondary)">uv 探测到的其他 .venv ({{ envs.uv.venvs_found.length }})</summary>
          <el-table :data="envs.uv.venvs_found" size="small" style="margin-top:8px">
            <el-table-column prop="project" label="项目路径" show-overflow-tooltip />
            <el-table-column prop="path" label="venv 路径" show-overflow-tooltip />
          </el-table>
        </details>
      </el-tab-pane>

      <!-- 系统 Python -->
      <el-tab-pane label="系统 Python" name="python">
        <h4>系统 Python</h4>
        <el-table :data="envs.python || []" size="small">
          <el-table-column prop="name" label="路径" show-overflow-tooltip />
          <el-table-column prop="version" label="版本" width="100" />
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button size="small" @click="showPackages(row, 'pip')">包列表</el-button>
              <el-button size="small" @click="exportReq(row)">导出 requirements</el-button>
            </template>
          </el-table-column>
        </el-table>
        <h4 style="margin-top: 16px">Conda 环境</h4>
        <el-empty v-if="!envs.conda?.length" description="无 Conda 环境" />
        <el-table v-else :data="envs.conda" size="small">
          <el-table-column prop="name" label="名称" /><el-table-column prop="path" label="路径" show-overflow-tooltip />
          <el-table-column label="操作" width="120">
            <template #default="{ row }"><el-button size="small" @click="showPackages(row, 'conda')">包列表</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="Node.js" name="node">
        <el-empty v-if="!envs.node?.length" description="未检测到 Node.js" />
        <div v-else><el-tag v-for="n in envs.node" :key="n.name" style="margin:4px">{{ n.name }}: {{ n.version }}</el-tag></div>
      </el-tab-pane>

      <el-tab-pane label="CUDA" name="cuda">
        <el-empty v-if="!envs.cuda" description="加载中..." />
        <div v-else>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="NVIDIA 驱动">{{ envs.cuda.driver?.version || '未安装' }}</el-descriptions-item>
            <el-descriptions-item label="CUDA Toolkit">{{ envs.cuda.cuda?.version || '未安装' }}</el-descriptions-item>
            <el-descriptions-item label="PyTorch">{{ envs.cuda.pytorch?.version || '未安装' }}</el-descriptions-item>
            <el-descriptions-item label="PyTorch CUDA">{{ envs.cuda.pytorch?.cuda_available ? '✅ 可用' : '❌ 不可用' }}</el-descriptions-item>
            <el-descriptions-item label="TensorFlow">{{ envs.cuda.tensorflow?.version || '未安装' }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-tab-pane>

      <el-tab-pane label=".env 管理" name="dotenv">
        <div class="toolbar">
          <el-input v-model="dotenvPath" placeholder=".env 文件路径" style="width: 300px" />
          <el-button @click="loadDotenv">加载</el-button>
          <el-button @click="showRaw = !showRaw">{{ showRaw ? '打码' : '显示原值' }}</el-button>
          <el-button type="primary" @click="saveDotenv">保存</el-button>
        </div>
        <el-input v-model="dotenvContent" type="textarea" :rows="20" placeholder="加载 .env 文件后在此编辑" />
      </el-tab-pane>
    </el-tabs>

    <!-- 路径配置 Dialog -->
    <el-dialog v-model="showPathConfig" title="配置 uv 环境搜索路径" width="550px">
      <p style="margin-bottom:8px;color:var(--el-text-color-secondary);font-size:13px">
        输入存放 uv 虚拟环境的文件夹路径（每行一个）。扫描发现环境后可勾选纳入管理。
      </p>
      <el-input v-model="pathConfigText" type="textarea" :rows="8" placeholder="/home/kamfu/UV_File" />
      <template #footer>
        <el-button @click="showPathConfig = false">取消</el-button>
        <el-button type="primary" @click="savePathConfig">保存并扫描</el-button>
      </template>
    </el-dialog>

    <!-- Packages Dialog -->
    <el-dialog v-model="pkgsVisible" :title="'包列表 — ' + pkgEnvName" width="700px">
      <el-input v-model="pkgSearch" placeholder="搜索包名..." clearable style="margin-bottom: 12px" />
      <el-table :data="filteredPkgs" size="small" max-height="500" v-loading="pkgsLoading">
        <el-table-column prop="name" label="包名" /><el-table-column prop="version" label="版本" width="140" />
      </el-table>
    </el-dialog>

    <el-dialog v-model="reqVisible" title="requirements.txt" width="600px">
      <el-input v-model="reqContent" type="textarea" :rows="20" readonly />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const envs = ref({ python: [], conda: [], node: [], uv: {}, cuda: null })
const activeTab = ref('uv')
const scanPaths = ref([]); const allScannedEnvs = ref([]); const scanLoading = ref(false)
const showPathConfig = ref(false); const pathConfigText = ref('')
const remarkEditPath = ref(null); const remarkText = ref(''); const envFilter = ref('')
const managedPaths = ref([])
const unmanagedSelected = ref([])
const pkgsVisible = ref(false); const pkgEnvName = ref(''); const packages = ref([]); const pkgSearch = ref(''); const pkgsLoading = ref(false)
const reqVisible = ref(false); const reqContent = ref('')
const dotenvPath = ref('~/.env'); const dotenvContent = ref(''); const showRaw = ref(false)

// 已纳入管理的环境
const managedEnvs = computed(() =>
  allScannedEnvs.value.filter(e => managedPaths.value.includes(e.path))
)
// 未纳入的
const unmanagedEnvs = computed(() =>
  allScannedEnvs.value.filter(e => !managedPaths.value.includes(e.path))
)
const filteredManaged = computed(() => {
  if (!envFilter.value.trim()) return managedEnvs.value
  const q = envFilter.value.toLowerCase()
  return managedEnvs.value.filter(e =>
    (e.project_name || '').toLowerCase().includes(q) || (e.remark || '').toLowerCase().includes(q)
  )
})
const filteredPkgs = computed(() => {
  if (!pkgSearch.value) return packages.value
  const q = pkgSearch.value.toLowerCase()
  return packages.value.filter(p => (p.name || '').toLowerCase().includes(q))
})
const managedTotalSize = computed(() => {
  const total = managedEnvs.value.reduce((s, e) => s + (e.size_bytes || 0), 0)
  if (total < 1024) return total + ' B'
  if (total < 1048576) return (total / 1024).toFixed(1) + ' KB'
  if (total < 1073741824) return (total / 1048576).toFixed(1) + ' MB'
  return (total / 1073741824).toFixed(2) + ' GB'
})

async function fetchEnvs() { try { const { data } = await api.get('/env/list'); envs.value = data } catch (_) {} }
async function fetchPaths() { try { const { data } = await api.get('/env/paths'); scanPaths.value = data.paths || []; pathConfigText.value = (data.paths || []).join('\n') } catch (_) {} }
async function fetchManaged() { try { const { data } = await api.get('/env/remarks'); managedPaths.value = Object.keys(data || {}).filter(k => data[k]) } catch (_) { managedPaths.value = [] } }

async function scanEnvs() {
  scanLoading.value = true
  try { const { data } = await api.get('/env/scan'); allScannedEnvs.value = data.envs || []; scanPaths.value = data.paths || [] } catch (_) { ElMessage.error('扫描失败') }
  scanLoading.value = false
}
async function savePathConfig() {
  const paths = pathConfigText.value.split('\n').map(s => s.trim()).filter(Boolean)
  try { await api.post('/env/paths', { paths }); ElMessage.success('已保存'); showPathConfig.value = false; await scanEnvs() } catch (_) { ElMessage.error('保存失败') }
}

function onUnmanagedSelect(rows) { unmanagedSelected.value = rows }
async function addSelectedToManaged() {
  if (!unmanagedSelected.value.length) return
  const newPaths = [...managedPaths.value, ...unmanagedSelected.value.map(e => e.path)]
  await saveManagedList(newPaths)
}
async function addAllToManaged() {
  const newPaths = [...managedPaths.value, ...unmanagedEnvs.value.map(e => e.path)]
  await saveManagedList(newPaths)
}
async function removeManaged(row) {
  const newPaths = managedPaths.value.filter(p => p !== row.path)
  await saveManagedList(newPaths)
}
async function saveManagedList(paths) {
  // 用 remarks 表存储纳入管理的环境路径（remark 值存 "managed" 标记）
  const unique = [...new Set(paths)]
  for (const p of unique) {
    if (!managedPaths.value.includes(p)) {
      await api.post('/env/remarks', { env_path: p, remark: 'managed' })
    }
  }
  for (const p of managedPaths.value) {
    if (!unique.includes(p)) {
      await api.post('/env/remarks', { env_path: p, remark: '' })
    }
  }
  managedPaths.value = unique
  ElMessage.success('已更新')
}

function startRemark(row) { remarkEditPath.value = row.path; remarkText.value = row.remark && row.remark !== 'managed' ? row.remark : '' }
async function saveRemark(envPath) {
  const v = remarkText.value.trim()
  try { await api.post('/env/remarks', { env_path: envPath, remark: v || 'managed' }); ElMessage.success('已保存'); remarkEditPath.value = null; await scanEnvs(); await fetchManaged() } catch (_) { ElMessage.error('保存失败') }
}

async function showPackages(env) {
  pkgEnvName.value = env.project_name || env.name || env.path; pkgsVisible.value = true; pkgsLoading.value = true
  try { const { data } = await api.get(`/env/${encodeURIComponent(env.path || env.name)}/packages`, { params: { type: 'pip' } }); packages.value = Array.isArray(data) ? data : [] } catch (_) { packages.value = [] }
  pkgsLoading.value = false
}
async function exportReq(env) { try { const { data } = await api.get(`/env/${encodeURIComponent(env.path || env.name)}/requirements`); reqContent.value = typeof data === 'string' ? data : JSON.stringify(data, null, 2); reqVisible.value = true } catch (_) { ElMessage.error('导出失败') } }
async function loadDotenv() { try { const ep = showRaw.value ? '/env/dotenv/raw' : '/env/dotenv'; const { data } = await api.get(ep, { params: { path: dotenvPath.value } }); if (data.exists) dotenvContent.value = data.content || data.lines?.map(l => l.raw).join('\n') || ''; else dotenvContent.value = '' } catch (_) { ElMessage.error('加载失败') } }
async function saveDotenv() { try { await api.post('/env/dotenv', { path: dotenvPath.value, content: dotenvContent.value }); ElMessage.success('已保存') } catch (_) { ElMessage.error('保存失败') } }

onMounted(() => { fetchEnvs(); fetchPaths(); fetchManaged(); scanEnvs() })
</script>

<style scoped>
.env-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }
</style>
