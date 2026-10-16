<template>
  <div class="taxonomy-view">
    <div class="crumb">
      <el-button link :icon="ArrowLeft" @click="$router.push('/commands')">返回命令手册</el-button>
    </div>
    <h2 class="page-title">分类字典</h2>
    <p class="page-desc">
      维护命令手册里「一级分类 / 所属服务 / 所属场景」三个下拉框的选项。删除会把命令里引用的字段清空；改名会同步到命令里。
    </p>

    <el-tabs v-model="activeType" @tab-change="onTabChange">
      <el-tab-pane
        v-for="t in TYPES"
        :key="t.value"
        :name="t.value"
        :label="`${t.label}（${counts[t.value]}）`" />
    </el-tabs>

    <div class="toolbar">
      <el-input
        v-model="newValue"
        :placeholder="`新增${TYPES.find(x=>x.value===activeType).label}`"
        clearable
        size="default"
        style="max-width: 320px"
        @keyup.enter="onAdd" />
      <el-input-number
        v-model="newSort"
        :min="0" :max="9999"
        size="default"
        controls-position="right"
        style="width: 140px" />
      <el-button type="primary" :icon="Plus" @click="onAdd" :loading="adding">新增</el-button>
      <span class="tip">已用值会自动加入字典（在「命令手册」新增命令时）</span>
    </div>

    <el-table :data="rows" v-loading="loading" size="default" stripe>
      <el-table-column prop="value" label="值" min-width="200" />
      <el-table-column prop="sort" label="排序" width="120">
        <template #default="{ row }">
          <el-input-number v-model="row.sort" :min="0" :max="9999" size="small"
            controls-position="right" style="width: 110px"
            @change="(v) => onSortChange(row, v)" />
        </template>
      </el-table-column>
      <el-table-column prop="ref_count" label="被引用" width="100" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="row.ref_count > 0 ? 'success' : 'info'">
            {{ row.ref_count }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openRename(row)">改名</el-button>
          <el-button size="small" type="danger" :disabled="row.ref_count > 0"
            @click="onDelete(row)">
            {{ row.ref_count > 0 ? '删除（先清空引用）' : '删除' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 改名弹窗 -->
    <el-dialog v-model="renameVisible" title="改名" width="420px" @closed="resetRenameForm">
      <el-form label-width="80px">
        <el-form-item label="当前值">
          <span>{{ renameForm.oldValue }}</span>
        </el-form-item>
        <el-form-item label="新值">
          <el-input v-model="renameForm.newValue" placeholder="新名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="renameForm.newType">
            <el-option v-for="t in TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <span class="tip">改类型会把命令里引用的字段一起迁移（如 category→service）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" :loading="renameLoading" @click="onRename">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ArrowLeft } from '@element-plus/icons-vue'
import api from '../api'

const TYPES = [
  { value: 'category', label: '一级分类' },
  { value: 'service',  label: '所属服务' },
  { value: 'scenario', label: '所属场景' },
]

const activeType = ref('category')
const rows = ref([])
const loading = ref(false)
const adding = ref(false)
const newValue = ref('')
const newSort = ref(0)
const counts = ref({ category: 0, service: 0, scenario: 0 })

const renameVisible = ref(false)
const renameLoading = ref(false)
const renameForm = reactive({ row: null, oldValue: '', newValue: '', newType: 'category' })

async function fetchList() {
  loading.value = true
  try {
    const { data } = await api.get('/commands/taxonomy', { params: { type: activeType.value } })
    rows.value = data
    counts.value[activeType.value] = data.length
  } catch (_) {}
  loading.value = false
}

async function refreshAllCounts() {
  for (const t of TYPES) {
    try {
      const { data } = await api.get('/commands/taxonomy', { params: { type: t.value } })
      counts.value[t.value] = data.length
    } catch (_) { counts.value[t.value] = 0 }
  }
}

function onTabChange() {
  newValue.value = ''
  newSort.value = 0
  fetchList()
}

async function onAdd() {
  const v = newValue.value.trim()
  if (!v) { ElMessage.warning('请输入值'); return }
  try {
    adding.value = true
    await api.post('/commands/taxonomy', { type: activeType.value, value: v, sort: newSort.value || 0 })
    ElMessage.success('已新增')
    newValue.value = ''
    newSort.value = 0
    await fetchList()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '新增失败')
  }
  adding.value = false
}

async function onSortChange(row, v) {
  try {
    await api.put('/commands/taxonomy', {
      type: row.type, value: row.value, sort: v, new_value: row.value, new_type: row.type,
    })
  } catch (e) {
    ElMessage.error('更新排序失败')
  }
}

function openRename(row) {
  renameForm.row = row
  renameForm.oldValue = row.value
  renameForm.newValue = row.value
  renameForm.newType = row.type
  renameVisible.value = true
}

function resetRenameForm() {
  renameForm.row = null
  renameForm.oldValue = ''
  renameForm.newValue = ''
  renameForm.newType = activeType.value
}

async function onRename() {
  if (!renameForm.newValue.trim()) { ElMessage.warning('新值不能为空'); return }
  try {
    renameLoading.value = true
    await api.put('/commands/taxonomy', {
      type: renameForm.row.type,
      value: renameForm.row.value,
      new_value: renameForm.newValue.trim(),
      new_type: renameForm.newType,
    })
    ElMessage.success('已改名（命令里的引用已同步）')
    renameVisible.value = false
    if (renameForm.newType !== activeType.value) {
      // 跨类型移动：切到目标 tab
      activeType.value = renameForm.newType
    }
    await Promise.all([fetchList(), refreshAllCounts()])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '改名失败')
  }
  renameLoading.value = false
}

async function onDelete(row) {
  if (row.ref_count > 0) {
    ElMessage.warning('该值仍被 ' + row.ref_count + ' 条命令引用，请先手动改命令')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除「${row.value}」？如有命令引用此值，引用会被清空。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (_) { return }
  try {
    await api.delete('/commands/taxonomy', { params: { type: row.type, value: row.value, cascade: 'clear' } })
    ElMessage.success('已删除')
    await Promise.all([fetchList(), refreshAllCounts()])
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await refreshAllCounts()
  await fetchList()
})
</script>

<style scoped>
.taxonomy-view { padding: 20px; }
.crumb { margin-bottom: 8px; }
.page-title { margin: 0 0 8px; font-size: 20px; font-weight: 600; }
.page-desc { margin: 0 0 16px; font-size: 13px; color: var(--el-text-color-secondary); }
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.tip { font-size: 12px; color: var(--el-text-color-secondary); }
</style>
