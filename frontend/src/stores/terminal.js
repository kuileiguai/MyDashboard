import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useTerminalStore = defineStore('terminal', () => {
  const sessions = ref([])
  const activeSessionId = ref(null)
  const loading = ref(false)

  async function fetchSessions() {
    try {
      const { data } = await api.get('/terminal/list')
      sessions.value = data
    } catch (_) {}
  }

  async function createTerminal(name, cwd, shell, command) {
    try {
      const { data } = await api.post('/terminal/create', { name, cwd, shell, command })
      activeSessionId.value = data.session_id
      await fetchSessions()
      return data.session_id
    } catch (e) {
      throw e
    }
  }

  async function closeTerminal(sid) {
    try {
      await api.delete(`/terminal/${sid}`)
      if (activeSessionId.value === sid) activeSessionId.value = null
      await fetchSessions()
    } catch (_) {}
  }

  async function renameTerminal(sid, name) {
    try {
      await api.put(`/terminal/${sid}/rename`, { name })
      await fetchSessions()
    } catch (_) {}
  }

  return { sessions, activeSessionId, loading, fetchSessions, createTerminal, closeTerminal, renameTerminal }
})
