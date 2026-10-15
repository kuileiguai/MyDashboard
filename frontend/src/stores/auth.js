/**
 * 认证状态 —— 本机来源免登录，非本机来源需登录。
 * 用模块级 reactive 而非 Pinia，便于 api/ws.js 等模块直接引用。
 */

import { reactive } from 'vue'
import api from '../api'
import { setWsBlocked } from '../api/ws'

export const auth = reactive({
  checked: false,       // 是否已完成首次状态查询
  local: true,          // 当前来源是否为本机
  authRequired: false,  // 当前来源是否需要登录
  authenticated: false, // 是否已通过登录
  passwordConfigured: true, // 服务端是否配置了口令
  user: null,
  lockedSeconds: 0,
})

export async function refreshAuth() {
  try {
    const { data } = await api.get('/auth/status')
    auth.local = !!data.local
    auth.authRequired = !!data.auth_required
    auth.authenticated = !!data.authenticated
    auth.passwordConfigured = data.password_configured !== false
    auth.user = data.user || null
    auth.lockedSeconds = data.locked_seconds || 0
  } catch (_) {
    // 查询失败时保守处理，具体由后续 401 拦截兜底
  }
  auth.checked = true
  return auth
}

export async function login(username, password) {
  const { data } = await api.post('/auth/login', { username, password })
  await refreshAuth()
  setWsBlocked(false)
  return data
}

export async function logout() {
  try {
    await api.post('/auth/logout')
  } catch (_) {}
  markExpired()
}

export function markExpired() {
  auth.authenticated = false
  auth.user = null
  setWsBlocked(true)
}
