<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-logo">
          <el-icon :size="20"><Monitor /></el-icon>
        </div>
        <div>
          <div class="brand-title">Deckpit</div>
          <div class="brand-sub">远程访问验证</div>
        </div>
      </div>

      <el-alert
        v-if="!auth.passwordConfigured"
        type="error"
        :closable="false"
        title="服务端未配置访问口令"
        description="请在服务端设置环境变量 DASH_AUTH_PASSWORD 后重启服务，非本机访问才会开放。"
        class="login-alert"
        show-icon
      />

      <el-form @submit.prevent="onSubmit" size="large">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autocomplete="username" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button
          type="primary"
          class="login-btn"
          :loading="loading"
          :disabled="!auth.passwordConfigured"
          @click="onSubmit"
        >
          登录
        </el-button>
      </el-form>

      <div class="login-tip">
        来自非本机的访问需要验证身份；服务端本机（localhost）访问无需登录。
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Monitor } from '@element-plus/icons-vue'
import { auth, login } from '../stores/auth'

const route = useRoute()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await login(form.username, form.password)
    // 整页跳转：重建所有 WebSocket 连接与页面状态
    const redirect = route.query.redirect || '/'
    window.location.href = redirect
  } catch (e) {
    const status = e.response?.status
    if (status === 429) ElMessage.error(e.response?.data?.detail || '尝试过于频繁，请稍后再试')
    else if (status === 403) ElMessage.error(e.response?.data?.detail || '远程访问未启用')
    else ElMessage.error('用户名或密码错误')
  }
  loading.value = false
}
</script>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(1000px 500px at 15% -10%, var(--ub-rose-bg) 0%, transparent 60%),
    var(--el-bg-color-page);
}
.login-card {
  width: 380px;
  padding: 32px 28px 24px;
  border-radius: var(--radius-2xl);
  background: var(--el-bg-color);
  box-shadow: var(--shadow-lg);
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
}
.brand-logo {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  color: #fff;
  background: linear-gradient(135deg, var(--ub-rose) 0%, var(--ub-rose-soft) 55%, var(--ub-aubergine) 130%);
  box-shadow: var(--shadow-brand);
}
.brand-title { font-size: 18px; font-weight: 800; letter-spacing: 0.5px; }
.brand-sub { font-size: 11px; color: var(--ub-warm-grey); letter-spacing: 1px; }
.login-alert { margin-bottom: 16px; }
.login-btn { width: 100%; border-radius: var(--radius-md); font-weight: 600; }
.login-tip {
  margin-top: 16px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  text-align: center;
}
</style>
