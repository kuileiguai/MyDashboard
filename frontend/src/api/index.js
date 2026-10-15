import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 会话失效/未授权统一派发事件，由 App.vue 决定是否跳转登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    if ((status === 401 || status === 403) && !url.startsWith('/auth/')) {
      window.dispatchEvent(new CustomEvent('dash:unauthorized', { detail: { status } }))
    }
    return Promise.reject(error)
  }
)

export default api
