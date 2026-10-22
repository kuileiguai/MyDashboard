<template>
  <el-drawer
    v-model="ai.open"
    class="ai-drawer"
    direction="rtl"
    size="520px"
    :with-header="false"
    :modal="false"
    :lock-scroll="false"
    :close-on-click-modal="false"
  >
    <div class="ai-shell">
      <header class="ai-head">
        <div class="ai-brand">
          <span class="ai-logo">AI</span>
          <div class="ai-brand-text">
            <div class="ai-title">Deckpit 助手</div>
            <div class="ai-subtitle">配置百科 · 轻量启停</div>
          </div>
        </div>
        <div class="ai-head-ops">
          <el-tooltip :content="healthTooltip" placement="bottom">
            <el-tag
              size="small"
              :type="ai.healthType"
              effect="plain"
              class="ai-health"
              @click="openSettings"
            >
              {{ ai.healthText }}
            </el-tag>
          </el-tooltip>
          <el-button text circle title="新对话" @click="newChat">
            <el-icon><Plus /></el-icon>
          </el-button>
          <el-button text circle title="历史对话" @click="showHistory = !showHistory">
            <el-icon><Clock /></el-icon>
          </el-button>
          <el-button text circle title="模型设置" @click="openSettings">
            <el-icon><Setting /></el-icon>
          </el-button>
          <el-button text circle title="关闭" @click="ai.open = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </header>

      <div v-if="showHistory" class="ai-history">
        <AiConversationList
          :conversations="ai.conversations"
          :active-id="ai.activeId"
          @select="selectConversation"
          @delete="deleteConversation"
          @new="newChat"
        />
      </div>

      <div class="ai-messages" ref="scrollEl">
        <div v-if="!ai.messages.length" class="ai-empty">
          <div class="ai-empty-title">问我系统里已经配置好的东西</div>
          <div class="ai-empty-sub">我只读取配置、查询状态；启停需要你确认。</div>
          <div class="ai-suggestions">
            <button v-for="q in suggestions" :key="q" class="ai-suggestion" @click="ask(q)">
              {{ q }}
            </button>
          </div>
        </div>

        <AiMessage
          v-for="m in ai.messages"
          :key="m.id"
          :message="m"
          @confirm="ai.confirmAction"
          @reject="ai.rejectAction"
        />
      </div>

      <div v-if="ai.error" class="ai-error">
        <span>{{ ai.error }}</span>
        <el-icon class="ai-error-close" @click="ai.error = ''"><Close /></el-icon>
      </div>

      <div v-if="ai.usage && ai.usage.total" class="ai-usage"
           title="本会话累计 token；输入包含每轮重新发送的历史上下文">
        <span class="ai-usage-label">本次对话 Token</span>
        <b>{{ fmtNumber(ai.usage.total) }}</b>
        <span class="ai-usage-detail">
          输入 {{ fmtNumber(ai.usage.input) }} · 输出 {{ fmtNumber(ai.usage.output) }}
        </span>
        <el-tag v-if="ai.usage.estimated" size="small" type="info" effect="plain">估算</el-tag>
      </div>

      <footer class="ai-composer">
        <div v-if="contextLabel" class="ai-context">
          <el-tag size="small" closable effect="plain" @close="ctx.clearTarget">
            上下文：{{ contextLabel }}
          </el-tag>
        </div>
        <el-input
          v-model="draft"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 6 }"
          resize="none"
          placeholder="问我配置了什么，或让我启动/停止某个服务…"
          @keydown.enter.exact="onEnter"
        />
        <div class="ai-composer-foot">
          <span class="ai-hint">Enter 发送 · Shift+Enter 换行</span>
          <el-button v-if="ai.streaming" size="small" @click="ai.stop">停止</el-button>
          <el-button v-else size="small" type="primary" :disabled="!draft.trim()" @click="send()">
            发送
          </el-button>
        </div>
      </footer>
    </div>

    <AiSettingsDialog v-model="settingsOpen" />
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import AiMessage from './AiMessage.vue'
import AiConversationList from './AiConversationList.vue'
import AiSettingsDialog from './AiSettingsDialog.vue'
import { useAiStore } from '../../stores/ai'
import { useAiContext } from '../../stores/aiContext'

const ai = useAiStore()
const ctx = useAiContext()
const route = useRoute()

const draft = ref('')
const showHistory = ref(false)
const settingsOpen = ref(false)
const scrollEl = ref(null)

const suggestions = [
  '我配置了哪些服务？',
  'MyDashboard 后端怎么启动？端口是多少？',
  '我有哪些常用终端？',
  '哪些 Docker 容器在运行？',
  '你好，你能做什么？',
]

const contextLabel = computed(() => ctx.label)
const healthTooltip = computed(() => {
  const h = ai.health
  if (!h) return '点击配置模型'
  if (h.ok) return `${h.model || '模型'} · ${h.latency_ms ?? '-'} ms`
  return h.message || h.code || '模型不可用'
})

watch(
  () => route.path,
  path => ctx.setPage(path),
  { immediate: true },
)

watch(
  () => ai.open,
  open => {
    if (!open) {
      settingsOpen.value = false
      return
    }
    if (!ai.loaded) ai.loadConversations()
    ai.loadHealth()
    nextTick(scrollToBottom)
  },
)

watch(
  () => [ai.messages.length, ai.messages[ai.messages.length - 1]?.content],
  () => nextTick(scrollToBottom),
)

function scrollToBottom() {
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function fmtNumber(value) {
  const n = Number(value || 0)
  return n.toLocaleString('zh-CN')
}

function onEnter(e) {
  if (e.isComposing) return
  e.preventDefault()
  send()
}

async function send(text = draft.value) {
  const content = (text || '').trim()
  if (!content || ai.streaming) return
  draft.value = ''
  await ai.sendMessage(content, ctx.payload)
  nextTick(scrollToBottom)
}

function ask(q) {
  send(q)
}

function newChat() {
  if (ai.streaming) ai.stop()
  ai.newChat()
  showHistory.value = false
  draft.value = ''
  nextTick(scrollToBottom)
}

async function selectConversation(cid) {
  if (ai.streaming) ai.stop()
  showHistory.value = false
  try {
    await ai.openChat(cid)
    nextTick(scrollToBottom)
  } catch (e) {
    ElMessage.error(e.message || '加载会话失败')
  }
}

async function deleteConversation(cid) {
  try {
    await ElMessageBox.confirm('删除这个会话？删除后不可恢复。', '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await ai.deleteConversation(cid)
  } catch (_) {}
}

function openSettings() {
  settingsOpen.value = true
}

defineExpose({ send })
</script>

<style scoped>
.ai-shell {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
}
.ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.ai-brand { display: flex; align-items: center; gap: 9px; min-width: 0; }
.ai-logo {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--deck-navy, #1d2a38);
  color: #f7f3eb;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.4px;
}
.ai-brand-text { min-width: 0; }
.ai-title { font-size: 14px; font-weight: 800; color: var(--el-text-color-primary); }
.ai-subtitle { font-size: 10px; color: var(--el-text-color-secondary); margin-top: 1px; }
.ai-head-ops { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.ai-health { cursor: pointer; max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
.ai-history {
  padding: 8px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  max-height: 240px;
  overflow: auto;
  background: var(--el-fill-color-blank);
}
.ai-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 16px 8px;
  scroll-behavior: smooth;
}
.ai-empty { padding: 28px 4px 12px; }
.ai-empty-title { font-size: 15px; font-weight: 700; color: var(--el-text-color-primary); }
.ai-empty-sub { margin-top: 5px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.ai-suggestions { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.ai-suggestion {
  text-align: left;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-fill-color-lighter);
  color: var(--el-text-color-regular);
  border-radius: 9px;
  padding: 9px 11px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.ai-suggestion:hover {
  border-color: var(--el-color-primary-light-5);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.ai-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 16px 8px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  font-size: 12px;
  line-height: 1.5;
}
.ai-error span { flex: 1; }
.ai-error-close { cursor: pointer; margin-top: 1px; }
.ai-usage {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 16px 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  font-size: 11px;
  color: var(--el-text-color-secondary);
  flex-wrap: wrap;
}
.ai-usage-label { color: var(--el-text-color-regular); }
.ai-usage b { color: var(--el-text-color-primary); font-size: 12px; }
.ai-usage-detail { color: var(--el-text-color-secondary); }
.ai-composer {
  padding: 10px 16px 14px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.ai-context { margin-bottom: 8px; }
.ai-composer-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.ai-hint { margin-right: auto; font-size: 11px; color: var(--el-text-color-placeholder); }
</style>

<style>
/* el-drawer 会 teleport 到 body，scoped 选择器覆盖不到，用全局类名 */
.ai-drawer .el-drawer__body { padding: 0; overflow: hidden; height: 100%; }
.ai-drawer .el-drawer__header { display: none; }
@media (max-width: 640px) {
  .ai-drawer { width: 100% !important; }
}
</style>
