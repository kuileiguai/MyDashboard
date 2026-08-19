<template>
  <!-- 全局依赖缺失横幅 -->
  <div v-if="visible && missing.length" class="dep-banner">
    <el-alert type="warning" :closable="false" show-icon>
      <template #title>
        <span>检测到 {{ missing.length }} 个系统工具未安装，部分功能可能不可用</span>
      </template>
      <template #default>
        <div class="dep-list">
          <span v-for="m in missing" :key="m">{{ m }}</span>
        </div>
        <el-button size="small" type="primary" @click="doInstall" :loading="installing" style="margin-top:8px">
          <el-icon><Download /></el-icon> 一键安装（弹窗输密码）
        </el-button>
        <span v-if="installMsg" style="margin-left:12px;font-size:12px">{{ installMsg }}</span>
      </template>
    </el-alert>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const visible = ref(false)
const missing = ref([])
const installing = ref(false)
const installMsg = ref('')

async function check() {
  try {
    const { data } = await api.get('/system/dependencies')
    const missingList = Object.entries(data.tools || {})
      .filter(([_, info]) => !info.installed)
      .map(([name, info]) => name)
    missing.value = missingList
    visible.value = missingList.length > 0
  } catch (_) {}
}

async function doInstall() {
  installing.value = true
  installMsg.value = '正在安装，请在弹出的密码框中输入密码...'
  try {
    const { data } = await api.post('/system/dependencies/install?use_pkexec=true')
    if (data.ok) {
      ElMessage.success(data.message)
      visible.value = false
      missing.value = []
    } else {
      installMsg.value = data.message || '安装失败'
      ElMessage.error(data.message)
    }
  } catch (e) {
    installMsg.value = '安装请求失败: ' + (e.response?.data?.detail || e.message)
  }
  installing.value = false
  // 安装后重新检查
  await check()
}

onMounted(check)

defineExpose({ check })
</script>

<style scoped>
.dep-banner {
  position: fixed;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  z-index: 5000;
  max-width: 700px;
  width: calc(100% - 40px);
  margin-top: 8px;
}
.dep-list { display: flex; gap: 8px; flex-wrap: wrap }
.dep-list span { background: var(--el-color-warning-light); padding: 2px 10px; border-radius: var(--radius-pill); font-size: 12px; font-family: monospace }
</style>
