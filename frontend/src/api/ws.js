/**
 * WebSocket 客户端 —— 支持自动重连、心跳、按 topic 订阅
 */

const WS_URL_BASE = `ws://${location.host}`

class WsClient {
  constructor() {
    this.connections = new Map() // topic -> { ws, subscribers, reconnectTimer, pingTimer }
  }

  subscribe(topic, onMessage) {
    if (!this.connections.has(topic)) {
      this._connect(topic)
    }
    const conn = this.connections.get(topic)
    if (conn) {
      conn.subscribers.add(onMessage)
    }
    // Return unsubscribe function
    return () => {
      const c = this.connections.get(topic)
      if (c) {
        c.subscribers.delete(onMessage)
        if (c.subscribers.size === 0) {
          this._close(topic)
        }
      }
    }
  }

  send(topic, data) {
    const conn = this.connections.get(topic)
    if (conn && conn.ws && conn.ws.readyState === WebSocket.OPEN) {
      conn.ws.send(data)
    }
  }

  _connect(topic) {
    const url = `${WS_URL_BASE}${topic}`
    const ws = new WebSocket(url)
    const subscribers = new Set()

    const conn = { ws, subscribers, reconnectTimer: null, pingTimer: null }
    this.connections.set(topic, conn)

    ws.onopen = () => {
      // Heartbeat
      conn.pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30000)
    }

    ws.onmessage = (event) => {
      if (event.data === 'pong') return
      let parsed = event.data
      try {
        parsed = JSON.parse(event.data)
      } catch (_) {}
      subscribers.forEach(fn => {
        try { fn(parsed) } catch (_) {}
      })
    }

    ws.onclose = () => {
      clearInterval(conn.pingTimer)
      // Auto reconnect with exponential backoff
      if (subscribers.size > 0) {
        const delay = Math.min(1000 * 2 ** (this.connections.get(topic)?._retries || 0), 10000)
        conn._retries = (conn._retries || 0) + 1
        conn.reconnectTimer = setTimeout(() => this._connect(topic), delay)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  _close(topic) {
    const conn = this.connections.get(topic)
    if (conn) {
      clearInterval(conn.pingTimer)
      clearTimeout(conn.reconnectTimer)
      if (conn.ws) conn.ws.close()
      this.connections.delete(topic)
    }
  }
}

export const wsClient = new WsClient()

// Convenience methods
export function subscribeMonitor(onMessage) {
  return wsClient.subscribe('/ws/system/monitor', onMessage)
}

export function subscribeTerminal(sessionId, onMessage) {
  return wsClient.subscribe(`/ws/terminal/${sessionId}`, onMessage)
}

export function subscribeLogTail(path, onMessage) {
  return wsClient.subscribe(`/ws/logs/tail?path=${encodeURIComponent(path)}`, onMessage)
}

export function sendTerminalInput(sessionId, data) {
  wsClient.send(`/ws/terminal/${sessionId}`, data)
}
