/**
 * AI REST + NDJSON 流式客户端。
 *
 * 流式不用 axios（axios 浏览器端不适合增量读取），单独用 fetch + reader。
 */

const BASE = '/api/ai'

function notifyUnauthorized(status) {
  if (status === 401 || status === 403) {
    window.dispatchEvent(new CustomEvent('dash:unauthorized', { detail: { status } }))
  }
}

async function readError(res) {
  let detail = ''
  try {
    const data = await res.json()
    detail = data?.detail
  } catch (_) {}
  if (detail && typeof detail === 'object') {
    return detail.message || detail.code || JSON.stringify(detail)
  }
  return detail || `请求失败（HTTP ${res.status}）`
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    notifyUnauthorized(res.status)
    throw new Error(await readError(res))
  }
  if (res.status === 204) return null
  return res.json()
}

export const aiApi = {
  health(force = false) {
    return request(`/health${force ? '?force=1' : ''}`)
  },
  getConfig() {
    return request('/config')
  },
  saveConfig(payload) {
    return request('/config', { method: 'PUT', body: JSON.stringify(payload) })
  },
  testConfig() {
    return request('/config/test', { method: 'POST', body: '{}' })
  },
  listConversations(limit = 50) {
    return request(`/conversations?limit=${limit}`)
  },
  createConversation(payload = {}) {
    return request('/conversations', { method: 'POST', body: JSON.stringify(payload) })
  },
  getConversation(id) {
    return request(`/conversations/${id}`)
  },
  patchConversation(id, payload) {
    return request(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
  },
  deleteConversation(id) {
    return request(`/conversations/${id}`, { method: 'DELETE' })
  },
  catalog(params = {}) {
    const q = new URLSearchParams()
    if (params.types) q.set('types', params.types)
    if (params.include_env) q.set('include_env', '1')
    const suffix = q.toString() ? `?${q}` : ''
    return request(`/catalog${suffix}`)
  },
  listActions(conversationId) {
    const q = conversationId ? `?conversation_id=${conversationId}` : ''
    return request(`/actions${q}`)
  },
  confirmAction(id) {
    return request(`/actions/${id}/confirm`, { method: 'POST', body: '{}' })
  },
  rejectAction(id) {
    return request(`/actions/${id}/reject`, { method: 'POST', body: '{}' })
  },
  tools() {
    return request('/tools')
  },
}

/**
 * POST /api/ai/chat/stream，逐行解析 NDJSON。
 * onEvent(event) 每个事件调用一次；signal 用于停止。
 */
export async function streamChat(payload, { onEvent, signal } = {}) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!res.ok) {
    notifyUnauthorized(res.status)
    throw new Error(await readError(res))
  }
  if (!res.body) throw new Error('当前浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      const text = line.trim()
      if (!text) continue
      try {
        onEvent?.(JSON.parse(text))
      } catch (e) {
        console.warn('[AI] 无法解析流事件', text, e)
      }
    }
  }

  const tail = buffer.trim()
  if (tail) {
    try {
      onEvent?.(JSON.parse(tail))
    } catch (_) {}
  }
}
