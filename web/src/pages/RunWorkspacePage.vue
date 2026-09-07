<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { runsApi } from '../api/runs'
import type { RunActivity, RunProgress, RunStatus } from '../types/run'

const emit = defineEmits<{ openReport: [runId: string] }>()

const EMPTY_ACTIVITY: RunActivity = {
  status_counts: {
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
  },
  queued: [],
  running: [],
  recent: [],
}

const activity = ref<RunActivity>(EMPTY_ACTIVITY)
const activeView = ref<'queued' | 'running' | 'history'>('queued')
const loading = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | undefined

const rows = computed(() => {
  if (activeView.value === 'queued') return activity.value.queued
  if (activeView.value === 'running') return activity.value.running
  return activity.value.recent
})
const hasActiveRuns = computed(
  () => activity.value.queued.length > 0 || activity.value.running.length > 0,
)

const statusLabels: Record<RunStatus, string> = {
  pending: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function schedulePoll() {
  if (pollTimer !== undefined) clearTimeout(pollTimer)
  pollTimer = undefined
  if (!hasActiveRuns.value) return
  pollTimer = setTimeout(() => {
    refresh().catch((error) => {
      ElMessage.error(error instanceof Error ? error.message : '刷新运行状态失败')
    })
  }, 2000)
}

async function refresh() {
  loading.value = true
  try {
    activity.value = await runsApi.activity()
  } finally {
    loading.value = false
    schedulePoll()
  }
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function formatDuration(seconds: number | null) {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
}

function openReport(run: RunProgress) {
  if (run.status === 'completed') emit('openReport', run.run_id)
}

onMounted(() => {
  refresh().catch((error) => {
    ElMessage.error(error instanceof Error ? error.message : '加载运行状态失败')
  })
})

onUnmounted(() => {
  if (pollTimer !== undefined) clearTimeout(pollTimer)
})
</script>

<template>
  <main class="run-main">
    <section class="region run-workspace" aria-labelledby="run-workspace-title">
      <div class="region-heading">
        <div>
          <span class="step">EVALUATION ACTIVITY</span>
          <h2 id="run-workspace-title">运行队列</h2>
          <p>查看排队、执行进度与最近运行结果；有活动运行时每两秒自动刷新。</p>
        </div>
        <el-button :loading="loading" data-testid="refresh-runs" @click="refresh">刷新</el-button>
      </div>

      <div class="run-stat-grid" aria-label="运行状态统计">
        <article><strong>{{ activity.status_counts.pending }}</strong><span>排队中</span></article>
        <article><strong>{{ activity.status_counts.running }}</strong><span>运行中</span></article>
        <article><strong>{{ activity.status_counts.completed }}</strong><span>已完成</span></article>
        <article><strong>{{ activity.status_counts.failed }}</strong><span>失败</span></article>
        <article><strong>{{ activity.status_counts.cancelled }}</strong><span>已取消</span></article>
      </div>

      <div class="run-filter" role="tablist" aria-label="运行筛选">
        <button
          type="button"
          :class="{ active: activeView === 'queued' }"
          role="tab"
          data-testid="runs-queued"
          @click="activeView = 'queued'"
        >排队中 · {{ activity.queued.length }}</button>
        <button
          type="button"
          :class="{ active: activeView === 'running' }"
          role="tab"
          data-testid="runs-running"
          @click="activeView = 'running'"
        >运行中 · {{ activity.running.length }}</button>
        <button
          type="button"
          :class="{ active: activeView === 'history' }"
          role="tab"
          data-testid="runs-history"
          @click="activeView = 'history'"
        >最近历史 · {{ activity.recent.length }}</button>
      </div>

      <div class="run-list" :aria-busy="loading">
        <article v-for="run in rows" :key="run.run_id" class="run-row">
          <div class="run-identity">
            <span class="run-status" :class="`status-${run.status}`">{{ statusLabels[run.status] }}</span>
            <b>{{ run.target_name }} · {{ run.target_version }}</b>
            <small>{{ run.dataset_name }} v{{ run.dataset_version }}</small>
          </div>
          <div class="run-progress-cell">
            <div>
              <span>{{ run.completed_cases }} / {{ run.total_cases }} 个用例</span>
              <b>{{ Math.round(run.progress * 100) }}%</b>
            </div>
            <el-progress
              :percentage="Math.round(run.progress * 100)"
              :show-text="false"
              :stroke-width="8"
              :status="run.status === 'failed' ? 'exception' : undefined"
            />
          </div>
          <dl>
            <div><dt>提交</dt><dd>{{ formatTime(run.created_at) }}</dd></div>
            <div><dt>开始</dt><dd>{{ formatTime(run.started_at) }}</dd></div>
            <div><dt>耗时</dt><dd>{{ formatDuration(run.duration_seconds) }}</dd></div>
          </dl>
          <div class="run-action">
            <span v-if="run.queue_position !== null">队列第 {{ run.queue_position }} 位</span>
            <span v-else-if="run.error" class="run-error" :title="run.error">{{ run.error }}</span>
            <el-button
              v-if="run.status === 'completed'"
              link
              type="primary"
              @click="openReport(run)"
            >查看结果</el-button>
          </div>
        </article>
        <el-empty v-if="!loading && rows.length === 0" description="当前筛选下暂无运行" />
      </div>
    </section>
  </main>
</template>
