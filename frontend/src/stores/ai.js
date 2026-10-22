import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { aiApi, streamChat } from '../api/ai'

// AbortController 不放进 Pinia state，避免被 Vue 深度代理后 brand check 失败
let streamController = null

function localId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export const useAiStore = defineStore('ai', {
  state: () => ({
    open: false,
    conversations: [],
    activeId: null,
    messages: [],
    streaming: false,
    error: '',
    health: null,
    config: null,
    usage: { input: 0, output: 0, total: 0, estimated: false },
    loaded: false,
  }),

  getters: {
    healthText(state) {
      if (!state.health) return '未检测'
      if (state.health.ok) return state.health.model || '已连接'
      return state.health.code === 'not_configured' ? '未配置模型' : '不可用'
    },
    healthType(state) {
      if (!state.health) return 'info'
      if (state.health.ok) return 'success'
      return state.health.code === 'not_configured' ? 'warning' : 'danger'
    },
    activeTitle(state) {
      const c = state.conversations.find(x => x.id === state.activeId)
      return c?.title || '新对话'
    },
  },

  actions: {
    async loadHealth(force = false) {
      try {
        const data = await aiApi.health(force)
        this.health = data.health
        this.config = data.config
      } catch (e) {
        this.health = { ok: false, code: 'request_failed', message: e.message }
      }
    },

    async loadConfig() {
      this.config = await aiApi.getConfig()
      return this.config
    },

    async saveConfig(payload) {
      const cfg = await aiApi.saveConfig(payload)
      this.config = cfg
      await this.loadHealth(true)
      return cfg
    },

    async testConfig() {
      const data = await aiApi.testConfig()
      this.health = data.health || data
      return this.health
    },

    async loadConversations() {
      try {
        this.conversations = await aiApi.listConversations()
        this.loaded = true
      } catch (e) {
        this.error = e.message || '加载会话失败'
      }
    },

    newChat() {
      this.activeId = null
      this.messages = []
      this.usage = { input: 0, output: 0, total: 0, estimated: false }
      this.error = ''
    },

    async openChat(cid) {
      this.activeId = cid
      this.error = ''
      await this.loadConversation(cid)
    },

    async loadConversation(cid) {
      const detail = await aiApi.getConversation(cid)
      const actions = detail.actions || []
      const byMessage = new Map()
      for (const a of actions) {
        if (a.message_id) byMessage.set(a.message_id, a)
      }
      this.messages = (detail.messages || []).map(m => ({
        ...m,
        streaming: false,
        tools: [],
        action: byMessage.get(m.id) || null,
      }))
      this.usage = detail.usage || { input: 0, output: 0, total: 0, estimated: false }
      // 动作没有对应消息时，补一条，避免历史里丢失
      for (const a of actions) {
        if (!a.message_id) {
          this.messages.push({
            id: localId('action'),
            role: 'assistant',
            content: '',
            streaming: false,
            tools: [],
            action: a,
          })
        }
      }
    },

    async deleteConversation(cid) {
      await aiApi.deleteConversation(cid)
      if (this.activeId === cid) this.newChat()
      await this.loadConversations()
    },

    _handleEvent(ev, assistant) {
      switch (ev.type) {
        case 'start':
          if (ev.conversation_id) this.activeId = ev.conversation_id
          break
        case 'token':
          assistant.content += ev.delta || ''
          break
        case 'tool_result':
          assistant.tools.push({
            name: ev.name,
            ok: ev.ok,
            data: ev.data,
            truncated: ev.truncated,
          })
          break
        case 'action_proposed':
          assistant.action = ev
          break
        case 'done':
          assistant.streaming = false
          if (ev.usage) {
            assistant.tokens_in = ev.usage.in || 0
            assistant.tokens_out = ev.usage.out || 0
            assistant.tokens_estimated = !!ev.usage.estimated
          }
          if (ev.conversation_usage) {
            this.usage = ev.conversation_usage
          } else if (ev.usage) {
            this.usage = {
              input: ev.usage.in || 0,
              output: ev.usage.out || 0,
              total: (ev.usage.in || 0) + (ev.usage.out || 0),
              estimated: !!ev.usage.estimated,
            }
          }
          break
        case 'error':
          this.error = ev.message || 'AI 请求失败'
          assistant.content += `\n\n> 错误：${this.error}`
          assistant.streaming = false
          break
        default:
          break
      }
    },

    async sendMessage(text, context = {}) {
      const content = (text || '').trim()
      if (!content || this.streaming) return

      this.error = ''
      const user = { id: localId('u'), role: 'user', content, tools: [], streaming: false }
      const assistant = reactive({
        id: localId('a'),
        role: 'assistant',
        content: '',
        tools: [],
        streaming: true,
        action: null,
      })
      this.messages.push(user, assistant)
      this.streaming = true
      streamController = new AbortController()

      try {
        await streamChat(
          { conversation_id: this.activeId, message: content, context },
          {
            signal: streamController.signal,
            onEvent: ev => this._handleEvent(ev, assistant),
          },
        )
      } catch (e) {
        if (e.name === 'AbortError') {
          if (!assistant.content) assistant.content = '（已停止）'
        } else {
          this.error = e.message || String(e)
          assistant.content += `\n\n> 请求失败：${this.error}`
        }
      } finally {
        this.streaming = false
        assistant.streaming = false
        streamController = null
        await this.loadConversations()
      }
    },

    stop() {
      if (streamController) streamController.abort()
    },

    async confirmAction(actionId) {
      this.error = ''
      try {
        await aiApi.confirmAction(actionId)
        if (this.activeId) await this.loadConversation(this.activeId)
      } catch (e) {
        this.error = e.message || '动作执行失败'
        if (this.activeId) await this.loadConversation(this.activeId)
      }
    },

    async rejectAction(actionId) {
      this.error = ''
      try {
        await aiApi.rejectAction(actionId)
        if (this.activeId) await this.loadConversation(this.activeId)
      } catch (e) {
        this.error = e.message || '取消动作失败'
      }
    },

    toggleOpen(value) {
      this.open = typeof value === 'boolean' ? value : !this.open
      if (this.open && !this.loaded) this.loadConversations()
      if (this.open) this.loadHealth()
    },
  },
})
