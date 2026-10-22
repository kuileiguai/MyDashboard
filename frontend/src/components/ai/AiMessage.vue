<template>
  <div class="ai-msg" :class="`is-${message.role}`">
    <template v-if="message.role === 'user'">
      <div class="ai-user-row">
        <div class="ai-bubble ai-user-bubble">{{ message.content }}</div>
        <div class="ai-user-avatar" title="我">
          <el-icon :size="15"><UserFilled /></el-icon>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="ai-assistant-row">
        <div class="ai-avatar">
          <img :src="aiAvatar" alt="Deckpit AI" />
        </div>

        <div class="ai-assistant-body">
          <div class="ai-assistant-head">
            <span class="ai-role">Deckpit 助手</span>
            <el-button
              v-if="message.content"
              text
              size="small"
              class="ai-copy"
              title="复制整条回复"
              @click="copy"
            >
              <el-icon><CopyDocument /></el-icon>
              <span>复制全文</span>
            </el-button>
          </div>

          <div
            v-if="message.content"
            class="ai-markdown"
            v-html="html"
            @click="onMarkdownClick"
          ></div>
          <div v-else-if="message.streaming" class="ai-typing">
            <span></span><span></span><span></span>
          </div>

          <div v-if="usageTotal" class="ai-msg-usage">
            本回合 {{ formatNumber(usageTotal) }} tokens
            <span>输入 {{ formatNumber(message.tokens_in) }} / 输出 {{ formatNumber(message.tokens_out) }}</span>
            <el-tag v-if="message.tokens_estimated" size="small" type="info" effect="plain">估算</el-tag>
          </div>

          <details v-for="(tool, i) in message.tools || []" :key="i" class="ai-tool">
            <summary>
              <span class="ai-tool-name">工具 · {{ tool.name }}</span>
              <el-tag size="small" :type="tool.ok ? 'success' : 'danger'" effect="plain">
                {{ tool.ok ? 'ok' : 'error' }}
              </el-tag>
            </summary>
            <pre>{{ pretty(tool.data) }}</pre>
          </details>

          <AiActionCard
            v-if="message.action"
            :action="message.action"
            @confirm="$emit('confirm', $event)"
            @reject="$emit('reject', $event)"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import AiActionCard from './AiActionCard.vue'
import aiAvatar from '../../assets/deckpit_chat.jpeg'
import { renderMarkdown } from '../../utils/markdown'
import { copyText } from '../../utils/clipboard'

const props = defineProps({
  message: { type: Object, required: true },
})
defineEmits(['confirm', 'reject'])

const html = computed(() => renderMarkdown(props.message.content || ''))
const usageTotal = computed(() =>
  Number(props.message.tokens_in || 0) + Number(props.message.tokens_out || 0))

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function pretty(data) {
  try {
    const text = JSON.stringify(data, null, 2)
    return text.length > 6000 ? text.slice(0, 6000) + '\n…（已截断）' : text
  } catch (_) {
    return String(data)
  }
}

async function copy() {
  const ok = await copyText(props.message.content || '')
  if (ok) ElMessage.success('已复制整条回复')
  else ElMessage.error('复制失败')
}

async function onMarkdownClick(event) {
  const button = event.target?.closest?.('.ai-code-copy')
  if (!button) return
  const block = button.closest('.ai-code-block')
  const code = block?.querySelector('code')?.textContent || ''
  const ok = await copyText(code)
  if (!ok) {
    ElMessage.error('复制失败')
    return
  }
  button.textContent = '已复制'
  setTimeout(() => { button.textContent = '复制' }, 1200)
}
</script>

<style scoped>
.ai-msg { margin-bottom: 18px; }
.ai-user-row {
  display: flex;
  justify-content: flex-end;
  align-items: flex-start;
  gap: 8px;
}
.ai-user-bubble {
  max-width: calc(100% - 40px);
  padding: 9px 13px;
  border-radius: 14px 14px 4px 14px;
  background: var(--deck-amber, #e87924);
  color: #171d26;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ai-user-avatar {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-secondary);
  border: 1px solid var(--el-border-color-lighter);
}
.ai-assistant-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.ai-assistant-body { flex: 1; min-width: 0; }
.ai-assistant-head {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
}
.ai-avatar {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  overflow: hidden;
  background: var(--deck-navy, #1d2a38);
  border: 1px solid var(--el-border-color-lighter);
}
.ai-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.ai-role { font-size: 11px; color: var(--el-text-color-secondary); }
.ai-copy { margin-left: auto; }
.ai-copy span { font-size: 11px; }
.ai-markdown {
  font-size: 13px;
  line-height: 1.72;
  color: var(--el-text-color-primary);
  word-break: break-word;
}
.ai-markdown :deep(p) { margin: 0 0 8px; }
.ai-markdown :deep(p:last-child) { margin-bottom: 0; }
.ai-markdown :deep(ul), .ai-markdown :deep(ol) { margin: 4px 0 8px; padding-left: 20px; }
.ai-markdown :deep(code) {
  background: var(--el-fill-color);
  color: var(--el-text-color-primary);
  border-radius: 4px;
  padding: 1px 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
}
.ai-markdown :deep(pre) {
  /* 保持原来的灰底，只提高文字对比度 */
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-primary);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  overflow: auto;
  margin: 8px 0;
}
.ai-markdown :deep(pre code) {
  background: transparent;
  color: var(--el-text-color-primary);
  padding: 0;
  font-size: 12px;
  line-height: 1.55;
}
.ai-markdown :deep(.ai-code-block) {
  position: relative;
  margin: 8px 0;
}
.ai-markdown :deep(.ai-code-block pre) {
  margin: 0;
  padding: 30px 12px 10px;
  background: var(--el-fill-color-dark);
}
.ai-markdown :deep(.ai-code-lang) {
  position: absolute;
  top: 7px;
  left: 11px;
  z-index: 1;
  font-size: 10px;
  line-height: 1;
  color: var(--el-text-color-secondary);
  text-transform: lowercase;
  pointer-events: none;
}
.ai-markdown :deep(.ai-code-copy) {
  position: absolute;
  top: 5px;
  right: 7px;
  z-index: 2;
  border: 1px solid var(--el-border-color);
  border-radius: 5px;
  background: var(--el-fill-color);
  color: var(--el-text-color-primary);
  font-size: 10px;
  line-height: 1;
  padding: 4px 7px;
  cursor: pointer;
  opacity: 1;
  transition: background 0.15s ease;
}
.ai-markdown :deep(.ai-code-copy:hover) {
  background: var(--el-fill-color-dark);
}
.ai-markdown :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}
.ai-markdown :deep(th), .ai-markdown :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 5px 8px;
  text-align: left;
}
.ai-markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 10px;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}
.ai-msg-usage {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
}
.ai-msg-usage span { color: var(--el-text-color-secondary); }
.ai-typing {
  display: inline-flex;
  gap: 4px;
  padding: 8px 2px;
}
.ai-typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
  animation: ai-bounce 1.2s infinite ease-in-out;
}
.ai-typing span:nth-child(2) { animation-delay: 0.15s; }
.ai-typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes ai-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.45; }
  30% { transform: translateY(-4px); opacity: 1; }
}
.ai-tool {
  margin-top: 8px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}
.ai-tool summary { cursor: pointer; display: flex; align-items: center; gap: 8px; }
.ai-tool-name { flex: 1; }
.ai-tool pre {
  max-height: 240px;
  overflow: auto;
  margin: 8px 0 2px;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

<style>
/* 暗色主题下换回高对比 token 颜色；浅色主题仍用 github.css 的深色 token */
html.dark .ai-markdown .hljs { color: #e6edf3; }
html.dark .ai-markdown .hljs-comment,
html.dark .ai-markdown .hljs-quote { color: #8b949e; }
html.dark .ai-markdown .hljs-keyword,
html.dark .ai-markdown .hljs-selector-tag,
html.dark .ai-markdown .hljs-subst { color: #ff7b72; }
html.dark .ai-markdown .hljs-string,
html.dark .ai-markdown .hljs-doctag,
html.dark .ai-markdown .hljs-regexp { color: #a5d6ff; }
html.dark .ai-markdown .hljs-title,
html.dark .ai-markdown .hljs-section,
html.dark .ai-markdown .hljs-selector-id { color: #d2a8ff; }
html.dark .ai-markdown .hljs-number,
html.dark .ai-markdown .hljs-literal,
html.dark .ai-markdown .hljs-variable,
html.dark .ai-markdown .hljs-template-variable { color: #79c0ff; }
html.dark .ai-markdown .hljs-type,
html.dark .ai-markdown .hljs-class .hljs-title,
html.dark .ai-markdown .hljs-built_in { color: #ffa657; }
html.dark .ai-markdown .hljs-attr,
html.dark .ai-markdown .hljs-attribute { color: #79c0ff; }
html.dark .ai-markdown .hljs-name,
html.dark .ai-markdown .hljs-tag { color: #7ee787; }
html.dark .ai-markdown .hljs-meta { color: #8b949e; }
</style>
