<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DatasetSummary } from '../../types/dataset'

const props = defineProps<{
  items: DatasetSummary[]
  selectedId: string
  loading?: boolean
}>()
const emit = defineEmits<{
  select: [id: string]
  create: []
  copy: [item: DatasetSummary]
  archive: [item: DatasetSummary]
  import: []
  importExcel: []
}>()

const query = ref('')
const filtered = computed(() => {
  const value = query.value.trim().toLowerCase()
  if (!value) return props.items
  return props.items.filter(item =>
    item.name.toLowerCase().includes(value) || item.description.toLowerCase().includes(value)
  )
})
</script>

<template>
  <aside class="dataset-column dataset-list-panel">
    <div class="dataset-panel-heading">
      <div><span class="step">DATASETS</span><h2>测评集</h2></div>
      <el-button type="primary" size="small" data-testid="create-dataset" @click="emit('create')">新建</el-button>
    </div>
    <el-input v-model="query" clearable placeholder="搜索测评集" aria-label="搜索测评集" />
    <div v-loading="loading" class="dataset-list">
      <button
        v-for="item in filtered"
        :key="item.id"
        class="dataset-list-item"
        :class="{ selected: item.id === selectedId }"
        :data-testid="`dataset-item-${item.id}`"
        @click="emit('select', item.id)"
      >
        <span><b>{{ item.name }}</b><small>{{ item.description || '暂无描述' }}</small></span>
        <span class="dataset-badges">
          <el-tag size="small" effect="plain">v{{ item.version ?? '—' }}</el-tag>
          <el-tag v-if="item.has_draft" size="small" type="warning">草稿</el-tag>
          <small>{{ item.case_count }} 用例</small>
        </span>
      </button>
      <el-empty v-if="!filtered.length" description="暂无测评集" :image-size="72" />
    </div>
    <div class="dataset-list-actions">
      <el-button size="small" @click="emit('import')">导入 JSON</el-button>
      <el-button size="small" data-testid="import-excel" @click="emit('importExcel')">导入 Excel</el-button>
      <el-dropdown v-if="items.find(item => item.id === selectedId)" trigger="click">
        <el-button size="small">更多</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="emit('copy', items.find(item => item.id === selectedId)!)">复制测评集</el-dropdown-item>
            <el-dropdown-item divided @click="emit('archive', items.find(item => item.id === selectedId)!)">归档测评集</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>
