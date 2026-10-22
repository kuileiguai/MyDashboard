<template>
  <div class="ai-conv-list">
    <div class="ai-conv-head">
      <span>历史对话</span>
      <el-button text size="small" @click="$emit('new')">
        <el-icon><Plus /></el-icon> 新对话
      </el-button>
    </div>
    <div v-if="!conversations.length" class="ai-conv-empty">还没有对话</div>
    <div
      v-for="c in conversations"
      :key="c.id"
      class="ai-conv-item"
      :class="{ active: c.id === activeId }"
      @click="$emit('select', c.id)"
    >
      <div class="ai-conv-title">{{ c.title || '新对话' }}</div>
      <div class="ai-conv-meta">{{ formatTime(c.updated_at || c.created_at) }}</div>
      <el-button
        text
        size="small"
        class="ai-conv-del"
        title="删除会话"
        @click.stop="$emit('delete', c.id)"
      >
        <el-icon><Delete /></el-icon>
      </el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: [Number, String], default: null },
})
defineEmits(['select', 'delete', 'new'])

function formatTime(raw) {
  if (!raw) return ''
  const d = new Date(String(raw).replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return String(raw)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.ai-conv-list { padding: 4px 0 8px; }
.ai-conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 0 2px 6px;
}
.ai-conv-empty { font-size: 12px; color: var(--el-text-color-placeholder); padding: 10px 2px; }
.ai-conv-item {
  position: relative;
  padding: 8px 30px 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}
.ai-conv-item:hover { background: var(--el-fill-color-light); }
.ai-conv-item.active { background: var(--el-color-primary-light-9); }
.ai-conv-title {
  font-size: 13px;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-conv-meta { font-size: 11px; color: var(--el-text-color-placeholder); margin-top: 2px; }
.ai-conv-del {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0;
  transition: opacity 0.15s ease;
}
.ai-conv-item:hover .ai-conv-del { opacity: 1; }
</style>
