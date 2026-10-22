<template>
  <el-dialog
    v-model="visible"
    title="AI 模型设置"
    width="560px"
    append-to-body
    @open="load"
  >
    <div class="ai-settings-note" v-if="source === 'env'">
      当前配置来自环境变量。保存后会写入数据库，并优先于环境变量使用。
    </div>

    <el-form label-width="96px" class="ai-settings-form" @submit.prevent>
      <el-form-item label="接入方式">
        <el-select v-model="form.kind" style="width: 100%">
          <el-option label="OpenAI-compatible（Ollama / vLLM / DeepSeek 等）" value="openai-compatible" />
          <el-option label="Mock（本地占位，不用模型）" value="mock" />
        </el-select>
      </el-form-item>

      <template v-if="form.kind !== 'mock'">
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="http://127.0.0.1:11434/v1" />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model" placeholder="qwen2.5:14b / deepseek-chat" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="hasKey ? '已配置，留空则保持不变' : '本地模型可留空'"
          />
          <div class="ai-settings-hint">
            只在服务端加密保存，不会回显明文。
            <el-tag v-if="hasKey" size="small" type="success" effect="plain">已配置 Key</el-tag>
          </div>
        </el-form-item>
      </template>

      <el-form-item label="超时">
        <el-input-number v-model="form.timeout" :min="5" :max="600" :step="5" />
        <span class="ai-settings-unit">秒</span>
      </el-form-item>
      <el-form-item label="工具调用">
        <el-switch v-model="form.supports_tools" />
        <span class="ai-settings-hint inline">模型不支持 function calling 时可关闭；关闭后只能聊天，不能查配置。</span>
      </el-form-item>
      <el-form-item label="网络策略">
        <el-tag :type="allowCloud ? 'warning' : 'success'" size="small" effect="plain">
          {{ allowCloud ? '允许公网模型' : '仅本机/内网' }}
        </el-tag>
        <span class="ai-settings-hint inline">
          {{ allowCloud ? '配置文本会发送到外部模型' : '设置 DASH_AI_ALLOW_CLOUD=1 才允许公网地址' }}
        </span>
      </el-form-item>
    </el-form>

    <template #footer>
      <div class="ai-settings-footer">
        <el-button @click="test" :loading="testing">测试已保存配置</el-button>
        <div class="spacer"></div>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAiStore } from '../../stores/ai'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const ai = useAiStore()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const saving = ref(false)
const testing = ref(false)
const source = ref('env')
const hasKey = ref(false)
const allowCloud = ref(false)

const form = reactive({
  name: 'default',
  kind: 'openai-compatible',
  base_url: '',
  model: '',
  api_key: '',
  timeout: 120,
  supports_tools: true,
})

async function load() {
  try {
    const cfg = await ai.loadConfig()
    source.value = cfg.source || 'env'
    hasKey.value = !!cfg.has_key
    allowCloud.value = !!cfg.allow_cloud
    form.name = cfg.name || 'default'
    form.kind = cfg.kind || 'openai-compatible'
    form.base_url = cfg.base_url || ''
    form.model = cfg.model || ''
    form.api_key = ''
    form.timeout = cfg.timeout || 120
    form.supports_tools = cfg.supports_tools !== false
  } catch (e) {
    ElMessage.error(e.message || '读取配置失败')
  }
}

async function save() {
  if (form.kind !== 'mock' && (!form.base_url.trim() || !form.model.trim())) {
    ElMessage.warning('请填写 Base URL 和模型名')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name || 'default',
      kind: form.kind,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      timeout: form.timeout,
      supports_tools: form.supports_tools,
      enabled: true,
      is_default: true,
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    await ai.saveConfig(payload)
    hasKey.value = !!(ai.config && ai.config.has_key)
    form.api_key = ''
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  try {
    const h = await ai.testConfig()
    if (h.ok) {
      ElMessage.success(`连接成功${h.latency_ms != null ? `（${h.latency_ms} ms）` : ''}`)
    } else {
      ElMessage.error(h.message || '连接失败')
    }
  } catch (e) {
    ElMessage.error(e.message || '连接失败')
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.ai-settings-note {
  margin-bottom: 14px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
  line-height: 1.6;
}
.ai-settings-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.ai-settings-hint.inline { display: inline-flex; margin-left: 8px; margin-top: 0; }
.ai-settings-unit { margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.ai-settings-footer { display: flex; align-items: center; width: 100%; }
.ai-settings-footer .spacer { flex: 1; }
</style>
