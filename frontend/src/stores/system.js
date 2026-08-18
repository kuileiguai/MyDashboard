import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'
import { subscribeMonitor } from '../api/ws'

export const useSystemStore = defineStore('system', () => {
  const snapshot = ref(null)
  const history = ref([])
  const loading = ref(false)
  let unsub = null

  async function fetchOverview() {
    loading.value = true
    try {
      const { data } = await api.get('/system/overview')
      snapshot.value = data
    } catch (_) {}
    loading.value = false
  }

  function startMonitor() {
    unsub = subscribeMonitor((data) => {
      if (data && data.ts) {
        snapshot.value = data
        history.value.push(data)
        if (history.value.length > 150) history.value.shift()
      }
    })
  }

  function stopMonitor() {
    if (unsub) { unsub(); unsub = null }
  }

  return { snapshot, history, loading, fetchOverview, startMonitor, stopMonitor }
})
