<template>
  <div class="ai-action" :class="`is-${action.status || 'pending'}`">
    <div class="ai-action-head">
      <el-icon :color="isDanger ? '#e6a23c' : '#67c23a'">
        <WarningFilled v-if="isDanger" /><CircleCheck v-else />
      </el-icon>
      <span class="ai-action-title">建议动作</span>
      <el-tag size="small" :type="statusType" effect="light">{{ statusLabel }}</el-tag>
    </div>

    <div class="ai-action-target">{{ action.target_name || action.target_id }}</div>

    <div class="ai-action-rows">
      <div class="ai-action-row"><span>动作</span><b>{{ actionLabel }}</b></div>
      <div class="ai-action-row"><span>当前状态</span><b>{{ statusText(action.before_status) }}</b></div>
      <div v-if="action.after_status" class="ai-action-row">
        <span>执行后</span><b>{{ statusText(action.after_status) }}</b>
      </div>
      <div class="ai-action-row" v-if="action.target_type">
        <span>对象类型</span><b>{{ typeLabel }}</b>
      </div>
    </div>

    <div v-if="action.error" class="ai-action-error">{{ action.error }}</div>
    <div v-if="action.result?.message" class="ai-action-result">{{ action.result.message }}</div>

    <div v-if="action.status === 'pending' || !action.status" class="ai-action-ops">
      <el-button size="small" @click="$emit('reject', actionId)">取消</el-button>
      <el-button size="small" type="primary" @click="$emit('confirm', actionId)">
        确认{{ actionLabel }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  action: { type: Object, required: true },
})
defineEmits(['confirm', 'reject'])

const actionId = computed(() => props.action.action_id || props.action.id)
const isDanger = computed(() => ['stop', 'restart', 'down'].includes(props.action.action))

const actionLabel = computed(() => ({
  start: '启动',
  stop: '停止',
  restart: '重启',
  up: '启动',
  open: '打开',
}[props.action.action] || props.action.action))

const typeLabel = computed(() => ({
  service: '服务配置',
  docker_container: 'Docker 容器',
  docker_compose: 'Compose 项目',
  favorite_terminal: '常用终端',
}[props.action.target_type] || props.action.target_type))

const statusLabel = computed(() => ({
  pending: '待确认',
  confirmed: '执行中',
  done: '已完成',
  failed: '失败',
  rejected: '已取消',
  expired: '已过期',
}[props.action.status] || '待确认'))

const statusType = computed(() => ({
  pending: 'warning',
  confirmed: 'info',
  done: 'success',
  failed: 'danger',
  rejected: 'info',
  expired: 'info',
}[props.action.status] || 'warning'))

function statusText(value) {
  return {
    running: '运行中',
    stopped: '已停止',
    unknown: '未知',
    opened: '已打开',
    available: '可用',
  }[value] || value || '未知'
}
</script>

<style scoped>
.ai-action {
  margin-top: 10px;
  border: 1px solid var(--el-border-color-light);
  border-left: 3px solid var(--el-color-warning);
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  padding: 12px 14px;
}
.ai-action.is-done { border-left-color: var(--el-color-success); }
.ai-action.is-failed { border-left-color: var(--el-color-danger); }
.ai-action.is-rejected { border-left-color: var(--el-text-color-placeholder); }
.ai-action-head { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.ai-action-title { font-weight: 700; color: var(--el-text-color-primary); flex: 1; }
.ai-action-target {
  margin: 8px 0 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  word-break: break-all;
}
.ai-action-rows { display: grid; gap: 4px; }
.ai-action-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.ai-action-row b { font-weight: 600; color: var(--el-text-color-primary); }
.ai-action-error {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-color-danger);
  white-space: pre-wrap;
}
.ai-action-result {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-color-success);
}
.ai-action-ops { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
</style>
