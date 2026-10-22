import { defineStore } from 'pinia'

export const useAiContext = defineStore('aiContext', {
  state: () => ({
    page: '',
    target: null, // {type, id, name}
  }),
  getters: {
    label(state) {
      if (state.target?.name) return state.target.name
      if (state.target?.id) return `${state.target.type} #${state.target.id}`
      return ''
    },
    payload(state) {
      return {
        route: state.page,
        target_type: state.target?.type || '',
        target_id: state.target?.id ?? '',
        target_name: state.target?.name || '',
      }
    },
  },
  actions: {
    setPage(path) {
      this.page = path || ''
    },
    setTarget(type, id, name = '') {
      this.target = { type, id, name }
    },
    clearTarget() {
      this.target = null
    },
    clear() {
      this.page = ''
      this.target = null
    },
  },
})
