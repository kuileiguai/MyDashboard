<template>
  <div class="ssh-view">
    <h2 class="page-title">SSH 连接管理</h2>
    <p class="module-purpose">保存常用主机与跳板配置，一键探测并连接。可用私钥免密，也可保存密码（需安装 sshpass）自动登录。</p>
    <div class="toolbar">
      <el-button type="primary" @click="showCreateDialog = true"><el-icon><Plus /></el-icon> 添加主机</el-button>
      <el-button @click="importSshConfig"><el-icon><Upload /></el-icon> 从 ~/.ssh/config 导入</el-button>
      <el-button @click="parseSshConfig">查看 config</el-button>
      <el-button v-if="sshpassMissing" type="warning" :loading="installing" @click="installSshpass">
        <el-icon><Download /></el-icon> 安装 sshpass（密码登录需要）
      </el-button>
    </div>

    <el-table :data="hosts" stripe v-loading="loading">
      <el-table-column prop="name" label="名称" width="140" />
      <!-- 地址列用 min-width 而非 width：主内容区比列宽总和更宽时，
           剩余空间由这一列吸收，避免右侧留出空白条 -->
      <el-table-column label="地址" min-width="240">
        <template #default="{ row }">{{ row.username ? row.username + '@' : '' }}{{ row.host }}:{{ row.port }}</template>
      </el-table-column>
      <el-table-column label="认证" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.has_password ? 'warning' : 'info'">
            {{ row.has_password ? '密码' : (row.key_path ? '私钥' : '默认') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="key_path" label="密钥" show-overflow-tooltip min-width="160" />
      <el-table-column prop="jump_host" label="跳板机" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status?.status === 'online' ? 'success' : row.status?.status === 'ping_only' ? 'warning' : 'danger'" size="small">
            {{ row.status?.status || '...' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="connectHost(row)">连接</el-button>
          <el-button size="small" @click="checkStatus(row)">探测</el-button>
          <el-button size="small" @click="editHost(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="deleteHost(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="showCreateDialog" :title="editId ? '编辑主机' : '添加主机'" width="500px" @closed="resetForm">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="如：prod-server" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.host" placeholder="192.168.1.100" /></el-form-item>
        <el-form-item label="端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="用户名"><el-input v-model="form.username" placeholder="root" /></el-form-item>
        <el-form-item label="密钥"><el-input v-model="form.key_path" placeholder="~/.ssh/id_rsa" /></el-form-item>
        <el-form-item label="跳板机"><el-input v-model="form.jump_host" placeholder="user@jump-host" /></el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password" type="password" show-password autocomplete="new-password"
            :placeholder="formHasPassword ? '已保存密码，留空表示不修改' : '留空则用私钥 / 默认密钥免密登录'"
          />
        </el-form-item>
        <el-form-item v-if="formHasPassword" label="">
          <el-checkbox v-model="form.clear_password">清除已保存的密码</el-checkbox>
        </el-form-item>
        <el-form-item label="">
          <span class="form-hint">保存密码后点「连接」会自动登录，需要本机已安装 sshpass（依赖管理里可一键安装）。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveHost">保存</el-button>
      </template>
    </el-dialog>

    <!-- SSH Config Dialog -->
    <el-dialog v-model="showConfig" title="~/.ssh/config 解析" width="700px">
      <el-table :data="configHosts" size="small" max-height="400">
        <el-table-column prop="name" label="Host" /><el-table-column prop="host" label="Hostname" />
        <el-table-column prop="port" label="Port" width="70" /><el-table-column prop="username" label="User" />
      </el-table>
      <template #footer>
        <el-button @click="showConfig = false">关闭</el-button>
        <el-button type="primary" @click="importSshConfig">全部导入</el-button>
      </template>
    </el-dialog>

    <!-- Remote Bookmarks Dialog -->
    <el-dialog v-model="showRemoteBm" title="远程路径收藏">
      <template v-if="remoteBmHost">
        <h4>{{ remoteBmHost.name }}</h4>
        <div class="toolbar" style="margin-bottom: 12px">
          <el-input v-model="newRemotePath" placeholder="远程路径，如 /var/log" style="width: 250px" />
          <el-button @click="addRemoteBm">添加</el-button>
        </div>
        <el-table :data="remoteBookmarks" size="small">
          <el-table-column prop="name" label="名称" /><el-table-column prop="path" label="路径" />
          <el-table-column label="操作" width="80">
            <template #default="{ row }"><el-button size="small" type="danger" @click="delRemoteBm(row.id)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import api from '../api'

const router = useRouter()
const hosts = ref([]); const loading = ref(false)
const showCreateDialog = ref(false); const editId = ref(null)
const formHasPassword = ref(false)
const emptyForm = () => ({ name: '', host: '', port: 22, username: '', key_path: '', jump_host: '', password: '', clear_password: false })
const form = ref(emptyForm())
const showConfig = ref(false); const configHosts = ref([])
const showRemoteBm = ref(false); const remoteBmHost = ref(null); const remoteBookmarks = ref([]); const newRemotePath = ref('')
const sshpassMissing = ref(false); const installing = ref(false)

async function fetchHosts() { loading.value = true; try { const { data } = await api.get('/ssh/hosts'); hosts.value = data } catch (_) {}; loading.value = false }
async function connectHost(row) {
  try {
    const { data } = await api.post(`/ssh/hosts/${row.id}/connect`)
    ElMessage.success(`已发起: ${row.name}`)
    router.push('/terminal')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '连接失败')
  }
}
async function checkStatus(row) {
  try { const { data } = await api.get(`/ssh/hosts/${row.id}/status`); row.status = data } catch (_) {}
}
function editHost(row) {
  editId.value = row.id
  const { password: _pw, has_password, ...rest } = row
  form.value = { ...rest, password: '', clear_password: false }
  formHasPassword.value = !!has_password
  showCreateDialog.value = true
}
async function saveHost() {
  try { if (editId.value) await api.put(`/ssh/hosts/${editId.value}`, form.value); else await api.post('/ssh/hosts', form.value)
    ElMessage.success('保存成功'); showCreateDialog.value = false; await fetchHosts() } catch (_) { ElMessage.error('保存失败') }
}
async function deleteHost(row) {
  try { await ElMessageBox.confirm(`确认删除 ${row.name}?`, '确认', { type: 'warning' }); await api.delete(`/ssh/hosts/${row.id}`); await fetchHosts() } catch (_) {}
}
async function checkSshpass() {
  try { const { data } = await api.get('/system/dependencies'); sshpassMissing.value = !(data.tools?.sshpass?.installed) } catch (_) {}
}
async function installSshpass() {
  installing.value = true
  try {
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true&include_optional=true')
    if (data.ok) { ElMessage.success(data.message); await checkSshpass() }
    else ElMessage.error(data.message || '安装失败')
  } catch (_) { ElMessage.error('安装请求失败') }
  installing.value = false
}
async function parseSshConfig() { try { const { data } = await api.get('/ssh/config/parse'); configHosts.value = data.hosts || []; showConfig.value = true } catch (_) {} }
async function importSshConfig() {
  try { const { data } = await api.post('/ssh/config/import'); ElMessage.success(`导入 ${data.imported} 台主机`); await fetchHosts(); showConfig.value = false } catch (_) { ElMessage.error('导入失败') }
}
async function showRemoteBookmarks(row) { remoteBmHost.value = row; showRemoteBm.value = true; try { const { data } = await api.get(`/ssh/hosts/${row.id}/remote-bookmarks`); remoteBookmarks.value = data } catch (_) {} }
async function addRemoteBm() {
  if (!newRemotePath.value.trim()) return
  try { await api.post('/ssh/remote-bookmarks', { ssh_host_id: remoteBmHost.value.id, name: newRemotePath.value.split('/').pop() || newRemotePath.value, path: newRemotePath.value }); newRemotePath.value = ''; showRemoteBookmarks(remoteBmHost.value) } catch (_) {}
}
async function delRemoteBm(id) { try { await api.delete(`/ssh/remote-bookmarks/${id}`); showRemoteBookmarks(remoteBmHost.value) } catch (_) {} }
function resetForm() { editId.value = null; form.value = emptyForm(); formHasPassword.value = false }

onMounted(() => { fetchHosts(); checkSshpass() })
</script>

<style scoped>
.ssh-view { padding: 20px; }
.page-title { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
.form-hint { font-size: 12px; line-height: 1.5; color: var(--el-text-color-secondary); }
</style>
