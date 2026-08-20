<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DatasetOption, type EvaluatorOption, type Overview, type Report, type RerunComparison, type Run, type Trace, type Version } from './api/client'
import DatasetWorkspace from './pages/DatasetWorkspace.vue'

const overview = ref<Overview>({ total_runs: 0, completed_runs: 0, case_count: 0, latest: null })
const versions = ref<Version[]>([])
const datasets = ref<DatasetOption[]>([])
const evaluators = ref<EvaluatorOption[]>([])
const runs = ref<Run[]>([])
const selectedVersion = ref('loan-agent-v2-fixed')
const selectedDataset = ref('loan-risk-policy')
const selectedEvaluators = ref<string[]>([])
const report = ref<Report|null>(null)
const trace = ref<Trace|null>(null)
const loading = ref(false)
const traceOpen = ref(false)
const rerunOpen = ref(false)
const rerunLoading = ref(false)
const rerunCaseId = ref('')
const rerunVersion = ref('')
const comparison = ref<RerunComparison|null>(null)
const page = ref<'evaluate'|'datasets'>(location.pathname.startsWith('/datasets') ? 'datasets' : 'evaluate')

const caseNames = computed(() => Object.fromEntries((report.value?.run.snapshot.dataset.cases ?? []).map(c => [c.id, c.name])))
const failed = computed(() => report.value?.results.filter(item => item.outcome === 'fail') ?? [])
const caseResults = computed(() => (report.value?.run.snapshot.dataset.cases ?? [])
  .filter(item => report.value?.results.some(result => result.case_id === item.id))
  .map(item => ({
    case: item,
    results: report.value?.results.filter(result => result.case_id === item.id) ?? [],
  })))
const selectedAgent = computed(() => versions.value.find(item => item.id === selectedVersion.value))
const selectedDatasetInfo = computed(() => datasets.value.find(item => item.id === selectedDataset.value))

async function refresh() {
  const [summary, targetVersions, datasetOptions, evaluatorOptions, recentRuns] = await Promise.all([
    api.overview(), api.versions(), api.datasets(), api.evaluators(), api.runs(),
  ])
  overview.value = summary
  versions.value = targetVersions
  datasets.value = datasetOptions
  evaluators.value = evaluatorOptions
  runs.value = recentRuns
  if (selectedEvaluators.value.length === 0) selectedEvaluators.value = evaluatorOptions.map(item => item.id)
  if (!report.value && summary.latest) report.value = summary.latest
}

async function launch() {
  if (selectedEvaluators.value.length === 0) return ElMessage.warning('请至少选择一个评估器')
  if (selectedDatasetInfo.value?.version == null) return ElMessage.warning('请选择已有发布版本的测评集')
  loading.value = true
  try {
    const run = await api.launch(selectedVersion.value, selectedDataset.value, selectedDatasetInfo.value.version, selectedEvaluators.value)
    report.value = await api.report(run.id)
    await refresh()
    document.querySelector('#result-report')?.scrollIntoView({ behavior: 'smooth' })
    ElMessage.success('评估已完成，指标与证据已持久化')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '评估失败')
  } finally { loading.value = false }
}

async function openRun(id: string) {
  report.value = await api.report(id)
  trace.value = null
  comparison.value = report.value.run.parent_run_id ? await api.comparison(id) : null
}
async function openTrace(caseId: string) { if (!report.value) return; trace.value = await api.trace(report.value.run.id, caseId); traceOpen.value = true }
function openRerun(caseId: string) {
  rerunCaseId.value = caseId
  rerunVersion.value = versions.value.find(item => item.is_latest)?.id ?? versions.value[0]?.id ?? ''
  rerunOpen.value = true
}
async function submitRerun() {
  if (!report.value || !rerunCaseId.value || !rerunVersion.value) return
  rerunLoading.value = true
  try {
    const rerun = await api.rerunCase(report.value.run.id, rerunCaseId.value, rerunVersion.value)
    comparison.value = await api.comparison(rerun.id)
    rerunOpen.value = false
    await refresh()
    ElMessage.success('单用例重跑完成，已生成前后对比')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '单用例重跑失败')
  } finally { rerunLoading.value = false }
}
function navigate(next: 'evaluate'|'datasets') {
  page.value = next
  const path = next === 'datasets' ? '/datasets' : '/'
  if (location.pathname !== path) history.pushState({}, '', path)
}
function onPopState() { page.value = location.pathname.startsWith('/datasets') ? 'datasets' : 'evaluate' }
async function showCreatedRun(run: Run) {
  await openRun(run.id)
  await refresh()
  navigate('evaluate')
  requestAnimationFrame(() => document.querySelector('#result-report')?.scrollIntoView({ behavior: 'smooth' }))
}
const asPercent = (score: number|null) => score === null ? 'N/A' : `${Math.round(score * 100)}%`
const outcomeText: Record<string, string> = { pass: '通过', fail: '失败', review: '待复核', not_applicable: '不适用', error: '评估错误' }
const outcomeType = (outcome: string) => outcome === 'pass' ? 'success' : outcome === 'not_applicable' ? 'info' : outcome === 'review' ? 'warning' : 'danger'
const comparisonText: Record<string, string> = { improved: '改善', regressed: '退化', mixed: '有改善也有退化', unchanged: '无变化', incomparable: '不可比较' }
const comparisonType = (status: string) => status === 'improved' ? 'success' : status === 'regressed' || status === 'mixed' ? 'danger' : status === 'unchanged' ? 'info' : 'warning'

onMounted(() => {
  window.addEventListener('popstate', onPopState)
  refresh().catch(error => ElMessage.error(`无法连接后端：${error.message}`))
})
onUnmounted(() => window.removeEventListener('popstate', onPopState))
</script>

<template>
  <div class="shell">
    <header>
      <div><p class="eyebrow">AGENT QUALITY GATE</p><h1>AgentGate 评估台</h1><p>配置评估对象，运行用例，并用可追溯指标判断是否达到发布门槛。</p></div>
      <div class="header-actions">
        <el-tag effect="dark" type="success">P1 演示</el-tag>
        <nav aria-label="主导航">
          <button :class="{ active: page === 'evaluate' }" data-testid="nav-evaluate" @click="navigate('evaluate')">评估运行</button>
          <button :class="{ active: page === 'datasets' }" data-testid="nav-datasets" @click="navigate('datasets')">测评集管理</button>
        </nav>
      </div>
    </header>

    <main v-if="page === 'evaluate'">
      <section class="region config-region" aria-labelledby="config-title">
        <div class="region-heading"><div><span class="step">01 · EVALUATION SETUP</span><h2 id="config-title">评估配置</h2><p>选择 Agent、数据集与评估器，然后启动一次真实评估。</p></div><div class="run-count">已完成 {{ overview.completed_runs }} 次运行</div></div>

        <div class="config-grid">
          <article class="config-card">
            <div class="card-index">A</div><label>Agent</label>
            <el-select v-model="selectedVersion" data-testid="agent-select" aria-label="Agent 版本">
              <el-option v-for="item in versions" :key="item.id" :label="`${item.label} · ${item.id}`" :value="item.id" />
            </el-select>
            <p>{{ selectedAgent?.label }}，使用确定性 Provider 执行。</p>
          </article>

          <article class="config-card">
            <div class="card-index">D</div><label>Dataset</label>
            <el-select v-model="selectedDataset" data-testid="dataset-select" aria-label="数据集">
              <el-option v-for="item in datasets" :key="item.id" :label="`${item.name} · v${item.version}`" :value="item.id" />
            </el-select>
            <p>{{ selectedDatasetInfo?.description }} · {{ selectedDatasetInfo?.case_count ?? 0 }} 个用例</p>
          </article>

          <article class="config-card evaluator-card">
            <div class="card-index">E</div><label>Evaluators & Metrics</label>
            <div class="evaluator-kinds" aria-label="评估器分类">
              <span class="active-kind">规则评估器</span>
              <span>LLM Judge · P2</span>
              <span>Hybrid · P2</span>
            </div>
            <el-checkbox-group v-model="selectedEvaluators" class="evaluator-list">
              <el-checkbox v-for="item in evaluators" :key="item.id" :value="item.id" border>
                <span class="eval-name">{{ item.name }}</span><small>{{ item.metric }} · {{ item.dimension }}</small>
              </el-checkbox>
            </el-checkbox-group>
          </article>
        </div>

        <div class="launch-bar">
          <div><b>{{ selectedEvaluators.length }}</b> 个评估器已启用 <span>· 结果将写入 SQLite</span></div>
          <el-button type="primary" size="large" :loading="loading" :disabled="selectedEvaluators.length === 0" @click="launch">运行评估 <span>→</span></el-button>
        </div>
      </section>

      <section id="result-report" class="region report-region" aria-labelledby="report-title">
        <div class="region-heading report-heading">
          <div><span class="step">02 · RESULT REPORT</span><h2 id="report-title">结果报告</h2><p v-if="report">{{ report.run.snapshot.target.version }} · {{ report.run.snapshot.dataset.dataset_name }} v{{ report.run.snapshot.dataset.version }}</p><p v-else>运行评估后在此查看指标、失败证据和轨迹。</p></div>
          <el-tag v-if="report" :type="report.gate.outcome === 'pass' ? 'success' : 'danger'" effect="dark" size="large">{{ report.gate.outcome === 'pass' ? '发布门槛通过' : '发布门槛未通过' }}</el-tag>
        </div>

        <template v-if="report">
          <div class="metric-grid" aria-label="评估指标">
            <article v-for="metric in report.metrics" :key="`${metric.level}-${metric.key}`" class="metric-card" :data-testid="`metric-${metric.level}-${metric.key}`">
              <span>{{ metric.label }} · {{ metric.level }}</span><strong>{{ asPercent(metric.score) }}</strong>
              <el-progress :percentage="Math.round((metric.score ?? 0) * 100)" :show-text="false" :stroke-width="7" :color="(metric.score ?? 0) >= .95 ? '#20b486' : '#e85d75'" />
              <small>{{ metric.passed }} 通过 · {{ metric.failed }} 失败 · {{ metric.not_applicable }} 不适用<span v-if="metric.errors"> · {{ metric.errors }} 错误</span></small>
            </article>
            <article class="metric-card gate-card"><span>发布门槛</span><strong>{{ Math.round(report.gate.threshold * 100) }}%</strong><small>{{ report.gate.reason }}</small></article>
          </div>

          <div class="report-grid">
            <article class="report-panel">
              <div class="panel-title"><h3>全部检查结果</h3><el-tag type="danger" plain>{{ failed.length }} 项失败</el-tag></div>
              <div v-for="group in caseResults" :key="group.case.id" class="case-result-group" :data-testid="`case-result-${group.case.id}`">
                <div class="case-result-title">
                  <b>{{ group.case.name }}</b>
                  <span><el-button link type="primary" @click="openTrace(group.case.id)">查看Trace</el-button><el-button type="primary" plain size="small" :data-testid="`rerun-case-${group.case.id}`" @click="openRerun(group.case.id)">重新运行此Case</el-button></span>
                </div>
                <div v-for="item in group.results" :key="`${item.case_id}-${item.evaluator_id}`" class="result-item">
                  <div class="result-head">
                    <span><b>{{ item.evaluator_name }}</b><small>{{ item.reason }}</small></span>
                    <el-tag :type="outcomeType(item.outcome)" size="small">{{ outcomeText[item.outcome] }}</el-tag>
                  </div>
                  <ul v-if="item.checks.length" class="check-list">
                    <li v-for="check in item.checks" :key="check.id">
                      <span>{{ check.name }} · {{ check.reason }}<small v-if="check.expected !== null || check.actual !== null" class="expected-actual">期望 {{ JSON.stringify(check.expected) }} · 实际 {{ check.actual_missing ? '字段不存在' : JSON.stringify(check.actual) }}</small></span>
                      <el-tag :type="outcomeType(check.outcome)" size="small" effect="plain">{{ outcomeText[check.outcome] }}</el-tag>
                    </li>
                  </ul>
                </div>
              </div>
            </article>

            <article class="report-panel">
              <div class="panel-title"><h3>最近运行</h3><span>{{ runs.length }} 条</span></div>
              <el-table :data="runs" empty-text="暂无运行" size="small">
                <el-table-column label="Agent" min-width="190"><template #default="scope">{{ scope.row.snapshot.target.version }}</template></el-table-column>
                <el-table-column prop="status" label="状态" width="95" />
                <el-table-column label="操作" width="70"><template #default="scope"><el-button link type="primary" @click="openRun(scope.row.id)">查看</el-button></template></el-table-column>
              </el-table>
            </article>
          </div>
        </template>
        <el-empty v-else description="尚无结果，请先在上方运行评估" />
        <article v-if="comparison" class="rerun-comparison" data-testid="rerun-comparison">
          <div class="panel-title"><div><h3>单用例重跑对比 · {{ comparison.case_name }}</h3><small>{{ comparison.before_target_version }} → {{ comparison.after_target_version }}</small></div><el-tag :type="comparisonType(comparison.overall)" effect="dark">{{ comparisonText[comparison.overall] }}</el-tag></div>
          <div class="comparison-summary">{{ comparison.counts.improved }} 改善 · {{ comparison.counts.regressed }} 退化 · {{ comparison.counts.unchanged }} 无变化 · {{ comparison.counts.incomparable }} 不可比较</div>
          <el-table :data="comparison.evaluators" size="small">
            <el-table-column prop="evaluator_name" label="评估器" min-width="150" />
            <el-table-column label="原结果" min-width="180"><template #default="scope">{{ scope.row.before ? `${outcomeText[scope.row.before.outcome]} · ${asPercent(scope.row.before.score)}` : '—' }}</template></el-table-column>
            <el-table-column label="新结果" min-width="180"><template #default="scope">{{ scope.row.after ? `${outcomeText[scope.row.after.outcome]} · ${asPercent(scope.row.after.score)}` : '—' }}</template></el-table-column>
            <el-table-column label="变化" width="110"><template #default="scope"><el-tag :type="comparisonType(scope.row.status)" size="small">{{ comparisonText[scope.row.status] }}</el-tag></template></el-table-column>
          </el-table>
          <el-button link type="primary" @click="openRun(comparison.rerun_run_id)">打开重跑完整报告 →</el-button>
        </article>
      </section>
    </main>
    <main v-else class="dataset-main"><DatasetWorkspace @run-created="showCreatedRun" /></main>

    <el-dialog v-model="rerunOpen" title="重新运行单个Case" width="500px">
      <template v-if="report">
        <p><b>Case：</b>{{ caseNames[rerunCaseId] }}</p>
        <p><b>固定Dataset：</b>{{ report.run.snapshot.dataset.dataset_name }} v{{ report.run.snapshot.dataset.version }}</p>
        <p><b>原Agent版本：</b>{{ report.run.snapshot.target.version }}</p>
        <el-form label-position="top"><el-form-item label="重跑Agent版本"><el-select v-model="rerunVersion" data-testid="rerun-version-select" style="width: 100%"><el-option v-for="item in versions" :key="item.id" :label="`${item.label} · ${item.id}${item.is_latest ? '（最新）' : ''}`" :value="item.id" /></el-select></el-form-item></el-form>
        <el-alert type="info" :closable="false" show-icon title="Case、评估器、Metric和Gate均复用原Run配置。" />
      </template>
      <template #footer><el-button @click="rerunOpen = false">取消</el-button><el-button type="primary" :loading="rerunLoading" :disabled="!rerunVersion" data-testid="submit-rerun" @click="submitRerun">开始重跑</el-button></template>
    </el-dialog>

    <el-drawer v-model="traceOpen" title="用例轨迹" size="min(520px, 92vw)">
      <template v-if="trace">
        <p class="trace-case">{{ caseNames[trace.case_id] }}</p>
        <div v-if="trace.turns.length" class="trace-turns">
          <h3>各轮输入与输出</h3>
          <el-card v-for="(turn, index) in trace.turns" :key="turn.turn_id" shadow="never">
            <b>第 {{ index + 1 }} 轮 · {{ turn.turn_id }}</b>
            <small>输入</small><pre>{{ JSON.stringify(turn.input, null, 2) }}</pre>
            <small>输出</small><pre>{{ JSON.stringify(turn.output, null, 2) }}</pre>
            <small>轮次结束状态</small><pre>{{ JSON.stringify(turn.state, null, 2) }}</pre>
          </el-card>
        </div>
        <h3>执行轨迹</h3>
        <el-timeline><el-timeline-item v-for="span in trace.spans" :key="span.id" :timestamp="`步骤 ${span.sequence}`" placement="top"><el-card shadow="never"><b>{{ span.name }}</b><el-tag size="small">{{ span.kind }}</el-tag><small v-if="span.attributes.turn_id">轮次 {{ span.attributes.turn_id }}</small><pre>{{ JSON.stringify(span.attributes, null, 2) }}</pre></el-card></el-timeline-item></el-timeline>
        <h3>最终状态</h3><pre>{{ JSON.stringify(trace.final_state, null, 2) }}</pre>
        <h3>最终输出</h3><pre>{{ JSON.stringify(trace.final_output, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>
