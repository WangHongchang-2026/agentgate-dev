<script setup lang="ts">
type Page = 'evaluate' | 'datasets'

defineProps<{
  page: Page
  open: boolean
}>()

const emit = defineEmits<{
  navigate: [page: Page]
  close: []
}>()
</script>

<template>
  <aside
    id="app-navigation"
    class="app-sidebar"
    :class="{ open }"
    aria-label="主导航"
  >
    <div class="sidebar-brand">
      <button class="sidebar-home" aria-label="返回评估运行" @click="emit('navigate', 'evaluate')">
        <span class="brand-mark">AG</span>
        <span>
          <b>AgentGate</b>
          <small>AGENT QUALITY GATE</small>
        </span>
      </button>
      <button
        class="sidebar-close"
        type="button"
        aria-label="关闭导航"
        data-testid="close-navigation"
        @click="emit('close')"
      >×</button>
    </div>

    <nav class="sidebar-nav">
      <span class="sidebar-section-label">工作台</span>
      <button
        type="button"
        :class="{ active: page === 'evaluate' }"
        :aria-current="page === 'evaluate' ? 'page' : undefined"
        data-testid="nav-evaluate"
        @click="emit('navigate', 'evaluate')"
      >
        <span class="nav-icon">运</span>
        <span><b>评估运行</b><small>配置、执行与结果报告</small></span>
      </button>
      <button
        type="button"
        :class="{ active: page === 'datasets' }"
        :aria-current="page === 'datasets' ? 'page' : undefined"
        data-testid="nav-datasets"
        @click="emit('navigate', 'datasets')"
      >
        <span class="nav-icon">集</span>
        <span><b>测评集管理</b><small>数据集、版本与用例</small></span>
      </button>
    </nav>

    <div class="sidebar-footer">
      <span class="p1-dot" aria-hidden="true"></span>
      <span><b>P1 演示</b><small>SQLite · Rule Evaluators</small></span>
    </div>
  </aside>
</template>
