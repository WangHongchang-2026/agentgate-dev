<script setup lang="ts">
// 测评集与用例管理（迁移自 web/src/pages/DatasetWorkspace.vue）
// fetch → Axios，启动评估后跳转 /results/:id
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElMessage,
  ElMessageBox,
  ElSelect,
  ElOption,
  ElOptionGroup,
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElAlert,
} from 'element-plus'
import { runsApi } from '@/api/runs'
import { datasetsApi } from '@/api/datasets'
import { targetsApi } from '@/api/targets'
import { evaluatorsApi } from '@/api/evaluators'
import { ApiError } from '@/utils/request'
import type { EvaluatorOption } from '@/types/evaluator'
import type { Version } from '@/types/target'
import type {
  DatasetExport,
  DatasetSummary,
  DatasetVersion,
  EvaluationCase,
  ExcelImportErrorDetail,
  ExcelImportIssue,
  ValidationIssue,
} from '@/types/dataset'
import PageContainer from '@/components/PageContainer.vue'
import DatasetList from './components/DatasetList.vue'
import VersionSelector from './components/VersionSelector.vue'
import CaseTable from './components/CaseTable.vue'
import CaseEditor from './components/CaseEditor.vue'
import DatasetGenerationDialog from './components/DatasetGenerationDialog.vue'

const router = useRouter()

const datasets = shallowRef<DatasetSummary[]>([])
const versions = shallowRef<DatasetVersion[]>([])
const activeDatasetId = ref('')
const activeVersionId = ref('')
const activeCaseId = ref('')
const editedCase = ref<EvaluationCase | null>(null)
const targetVersions = ref<Version[]>([])
const evaluators = ref<EvaluatorOption[]>([])
const selectedAgent = ref('loan-agent-v2-fixed')
const selectedEvaluators = ref<string[]>([])
const busy = ref(false)
const loading = ref(false)
const validationIssues = ref<ValidationIssue[]>([])
const datasetDialog = ref(false)
const dialogMode = ref<'create' | 'copy'>('create')
const dialogName = ref('')
const dialogDescription = ref('')
const importInput = ref<HTMLInputElement | null>(null)
const excelImportInput = ref<HTMLInputElement | null>(null)
const importErrors = ref<string[]>([])
const excelImportIssues = ref<ExcelImportIssue[]>([])
const excelImportTotalCount = ref(0)
const excelImportTruncated = ref(false)
const generationDialog = ref(false)
const cloneJson = <T,>(value: T): T => JSON.parse(JSON.stringify(value))

const activeVersion = computed<DatasetVersion | null>(
  () => versions.value.find((item) => item.id === activeVersionId.value) ?? null,
)
const editable = computed(() => activeVersion.value?.status === 'draft')
const publishedVersions = computed(() =>
  versions.value.filter((item) => item.status === 'published'),
)
const activeDataset = computed(
  () => datasets.value.find((item) => item.id === activeDatasetId.value) ?? null,
)
const activeCaseIssues = computed(() => {
  const caseIndex =
    activeVersion.value?.cases.findIndex((item) => item.id === activeCaseId.value) ?? -1
  if (caseIndex < 0) return []
  const prefix = `cases[${caseIndex}]`
  return validationIssues.value.filter((issue) => issue.path.startsWith(prefix))
})
const groupedTargetVersions = computed(() => {
  const groups: Record<string, { label: string; items: Version[] }> = {}
  for (const item of targetVersions.value) {
    const key = item.adapter_type ?? 'python_fn'
    if (!groups[key])
      groups[key] = { label: key === 'http' ? 'HTTP Agent' : 'Demo Agent', items: [] }
    groups[key].items.push(item)
  }
  return Object.values(groups)
})

function chooseVersion(preferredId = '') {
  const selected =
    versions.value.find((item) => item.id === preferredId) ??
    versions.value.find((item) => item.status === 'draft') ??
    publishedVersions.value[0] ??
    null
  activeVersionId.value = selected?.id ?? ''
  selectFirstCase(selected)
}

function selectFirstCase(version: DatasetVersion | null) {
  const selected =
    version?.cases.find((item) => item.id === activeCaseId.value) ?? version?.cases[0] ?? null
  activeCaseId.value = selected?.id ?? ''
  editedCase.value = selected ? cloneJson(selected) : null
}

async function loadDatasets(preferredDatasetId = activeDatasetId.value) {
  datasets.value = await datasetsApi.list()
  const selected =
    datasets.value.find((item) => item.id === preferredDatasetId) ?? datasets.value[0]
  if (selected) await selectDataset(selected.id)
  else {
    activeDatasetId.value = ''
    versions.value = []
    chooseVersion()
  }
}

async function selectDataset(datasetId: string, preferredVersionId = '') {
  loading.value = true
  try {
    activeDatasetId.value = datasetId
    const detail = await datasetsApi.detail(datasetId)
    versions.value = detail.versions
    chooseVersion(preferredVersionId)
  } finally {
    loading.value = false
  }
}

function selectVersion(version: DatasetVersion) {
  activeVersionId.value = version.id
  validationIssues.value = []
  selectFirstCase(version)
}

function selectCase(item: EvaluationCase) {
  activeCaseId.value = item.id
  editedCase.value = cloneJson(item)
}

function newCase(): EvaluationCase {
  return {
    id: crypto.randomUUID(),
    name: '新用例',
    category: 'positive',
    difficulty: 'medium',
    tags: [],
    notes: '',
    provenance: null,
    generation_provenance: null,
    initial_state: {},
    turns: [
      {
        id: crypto.randomUUID(),
        input: { skill: 'loan_approval' },
        expected_skill: 'loan_approval',
        expectations: [],
        required_tools: [],
        forbidden_tools: [],
        policy_rules: [],
        notes: '',
      },
    ],
  }
}

async function generationAccepted(caseIds: string[]) {
  generationDialog.value = false
  await selectDataset(activeDatasetId.value)
  const selected = activeVersion.value?.cases.find((item) => caseIds.includes(item.id)) ?? null
  if (selected) selectCase(selected)
  ElMessage.success(`已将 ${caseIds.length} 个生成用例加入草稿`)
}

function addCase() {
  const item = newCase()
  activeCaseId.value = item.id
  editedCase.value = item
  validationIssues.value = []
}

async function refreshAfterMutation(version: DatasetVersion, caseId = activeCaseId.value) {
  datasets.value = await datasetsApi.list()
  versions.value = await datasetsApi.versions(activeDatasetId.value)
  activeVersionId.value = version.id
  activeCaseId.value = caseId
  const current = versions.value.find((item) => item.id === version.id) ?? version
  const selected = current.cases.find((item) => item.id === caseId) ?? current.cases[0] ?? null
  editedCase.value = selected ? cloneJson(selected) : null
}

async function saveCase(item: EvaluationCase) {
  if (!activeDatasetId.value || !editable.value) return
  busy.value = true
  try {
    const exists = activeVersion.value?.cases.some((entry) => entry.id === item.id) ?? false
    const version = exists
      ? await datasetsApi.updateCase(activeDatasetId.value, item)
      : await datasetsApi.addCase(activeDatasetId.value, item)
    await refreshAfterMutation(version, item.id)
    validationIssues.value = []
    ElMessage.success('用例已保存到草稿')
  } catch (error) {
    showError(error, '保存用例失败')
  } finally {
    busy.value = false
  }
}

async function copyCase(item: EvaluationCase) {
  if (!editable.value) return
  const version = await datasetsApi.copyCase(activeDatasetId.value, item.id)
  const copied = version.cases.find(
    (entry) => !activeVersion.value?.cases.some((old) => old.id === entry.id),
  )
  await refreshAfterMutation(version, copied?.id)
  ElMessage.success('已复制用例')
}

async function removeCase(item: EvaluationCase) {
  await ElMessageBox.confirm(`删除草稿中的“${item.name}”？已发布版本不会受影响。`, '删除用例', {
    type: 'warning',
  })
  const version = await datasetsApi.removeCase(activeDatasetId.value, item.id)
  activeCaseId.value = ''
  await refreshAfterMutation(version)
  ElMessage.success('用例已从草稿移除')
}

async function reorderCases(ids: string[]) {
  const version = await datasetsApi.reorderCases(activeDatasetId.value, ids)
  await refreshAfterMutation(version)
}

function openCreate() {
  dialogMode.value = 'create'
  dialogName.value = ''
  dialogDescription.value = ''
  datasetDialog.value = true
}

function openCopy(item: DatasetSummary) {
  dialogMode.value = 'copy'
  dialogName.value = `${item.name}（副本）`
  dialogDescription.value = item.description
  datasetDialog.value = true
}

async function submitDatasetDialog() {
  if (!dialogName.value.trim()) return ElMessage.warning('请输入测评集名称')
  busy.value = true
  try {
    const result =
      dialogMode.value === 'create'
        ? await datasetsApi.create(dialogName.value, dialogDescription.value)
        : await datasetsApi.copy(
            activeDatasetId.value,
            dialogName.value,
            activeVersion.value?.status === 'published' ? activeVersion.value.version : undefined,
          )
    datasetDialog.value = false
    await loadDatasets(result.dataset.id)
    ElMessage.success(dialogMode.value === 'create' ? '测评集已创建' : '测评集已复制')
  } catch (error) {
    showError(error, '操作失败')
  } finally {
    busy.value = false
  }
}

async function archiveDataset(item: DatasetSummary) {
  await ElMessageBox.confirm(`归档“${item.name}”？历史版本和运行记录仍可读取。`, '归档测评集', {
    type: 'warning',
  })
  await datasetsApi.archive(item.id)
  await loadDatasets('')
  ElMessage.success('测评集已归档')
}

async function createDraft(base: number | null) {
  busy.value = true
  try {
    const draft = await datasetsApi.createDraft(activeDatasetId.value, base)
    await selectDataset(activeDatasetId.value, draft.id)
    ElMessage.success('新版本草稿已创建')
  } catch (error) {
    showError(error, '创建草稿失败')
  } finally {
    busy.value = false
  }
}

async function discardDraft() {
  await ElMessageBox.confirm('放弃当前草稿？草稿中的修改将无法恢复。', '放弃草稿', {
    type: 'warning',
  })
  await datasetsApi.discardDraft(activeDatasetId.value)
  await selectDataset(activeDatasetId.value)
  ElMessage.success('草稿已放弃')
}

async function publishDraft() {
  busy.value = true
  validationIssues.value = []
  try {
    const published = await datasetsApi.publish(activeDatasetId.value)
    await selectDataset(activeDatasetId.value, published.id)
    datasets.value = await datasetsApi.list()
    ElMessage.success(`已发布 v${published.version}`)
  } catch (error) {
    if (error instanceof ApiError && Array.isArray(error.detail)) {
      validationIssues.value = datasetsApi.asValidationIssues(error.detail)
    }
    showError(error, '发布失败，请检查用例')
  } finally {
    busy.value = false
  }
}

async function exportVersion(version: number) {
  const payload = await datasetsApi.exportVersion(activeDatasetId.value, version)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${activeDataset.value?.name ?? 'dataset'}-v${version}.json`
  link.click()
  URL.revokeObjectURL(url)
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function excelFilename(name: string, version: number) {
  const safeName = name.replace(/[\\/:*?"<>|]/g, '_').trim() || 'dataset'
  return `${safeName}-v${version}.xlsx`
}

async function exportExcelVersion(version: number) {
  try {
    const blob = await datasetsApi.exportExcel(activeDatasetId.value, version)
    downloadBlob(blob, excelFilename(activeDataset.value?.name ?? 'dataset', version))
  } catch (error) {
    showError(error, '导出 Excel 失败')
  }
}

async function downloadExcelTemplate() {
  try {
    downloadBlob(await datasetsApi.excelTemplate(), 'agentgate-dataset-template.xlsx')
  } catch (error) {
    showError(error, '下载 Excel 模板失败')
  }
}

function openImport() {
  importErrors.value = []
  excelImportIssues.value = []
  importInput.value?.click()
}

function importErrorMessages(error: unknown, fallback: string) {
  if (error instanceof ApiError && Array.isArray(error.detail)) {
    return error.detail.map((item) => {
      if (typeof item === 'object' && item !== null && 'message' in item) {
        return String((item as { message: unknown }).message)
      }
      return JSON.stringify(item)
    })
  }
  return [error instanceof Error ? error.message : fallback]
}

async function importDataset(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const payload = JSON.parse(await file.text()) as DatasetExport
    const result = await datasetsApi.importDataset(payload)
    importErrors.value = []
    await loadDatasets(result.dataset.id)
    ElMessage.success('测评集已导入')
  } catch (error) {
    importErrors.value = importErrorMessages(error, 'JSON 导入失败').map(
      (message) => `JSON：${message}`,
    )
  } finally {
    input.value = ''
  }
}

function openExcelImport() {
  importErrors.value = []
  excelImportIssues.value = []
  excelImportTotalCount.value = 0
  excelImportTruncated.value = false
  excelImportInput.value?.click()
}

function datasetNameFromExcel(file: File) {
  return file.name.replace(/\.xlsx$/i, '').trim() || 'Excel Dataset'
}

function isExcelImportIssue(value: unknown): value is ExcelImportIssue {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ExcelImportIssue).sheet === 'string' &&
    typeof (value as ExcelImportIssue).message === 'string'
  )
}

function isExcelImportErrorDetail(value: unknown): value is ExcelImportErrorDetail {
  return (
    typeof value === 'object' &&
    value !== null &&
    'issues' in value &&
    Array.isArray((value as ExcelImportErrorDetail).issues) &&
    'total_count' in value
  )
}

async function importExcelDataset(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  excelImportIssues.value = []
  excelImportTotalCount.value = 0
  excelImportTruncated.value = false
  try {
    const result = await datasetsApi.importExcel(file, datasetNameFromExcel(file))
    await loadDatasets(result.dataset.id)
    ElMessage.success('Excel 已导入为草稿')
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = isExcelImportErrorDetail(error.detail)
        ? error.detail.issues
        : Array.isArray(error.detail)
          ? error.detail
          : []
      if (isExcelImportErrorDetail(error.detail)) {
        excelImportTotalCount.value = error.detail.total_count
        excelImportTruncated.value = error.detail.truncated
      }
      excelImportIssues.value = detail.filter(isExcelImportIssue)
      if (excelImportIssues.value.length) return
    }
    importErrors.value = importErrorMessages(error, 'Excel 导入失败').map(
      (message) => `Excel：${message}`,
    )
  } finally {
    busy.value = false
    input.value = ''
  }
}

async function launchEvaluation() {
  if (!activeVersion.value?.version) return ElMessage.warning('只能运行已发布版本')
  if (!selectedEvaluators.value.length) return ElMessage.warning('请至少选择一个评估器')
  busy.value = true
  try {
    const run = await runsApi.launch({
      version: selectedAgent.value,
      dataset_id: activeDatasetId.value,
      dataset_version: activeVersion.value.version,
      evaluator_ids: selectedEvaluators.value,
    })
    ElMessage.success('评估已完成，正在打开结果报告')
    router.push(`/results/${run.id}`)
  } catch (error) {
    showError(error, '运行评估失败')
  } finally {
    busy.value = false
  }
}

function showError(error: unknown, fallback: string) {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

function onAgentChange(value: string | number | boolean | object | null) {
  selectedAgent.value = String(value)
}
function onEvaluatorsChange(value: string | number | boolean | object | null) {
  selectedEvaluators.value = (value as string[]) ?? []
}

onMounted(async () => {
  try {
    const [agents, evaluatorItems] = await Promise.all([
      targetsApi.versions(),
      evaluatorsApi.evaluators(),
    ])
    targetVersions.value = agents
    evaluators.value = evaluatorItems
    selectedEvaluators.value = evaluatorItems.map((item) => item.id)
    await loadDatasets()
  } catch (error) {
    showError(error, '无法加载测评集')
  }
})
</script>

<template>
  <PageContainer
    title="测评集与用例管理"
    description="编辑草稿、发布不可变版本，并用选定版本运行真实评估。"
  >
    <template #extra>
      <div v-if="activeDataset" class="workspace-status">
        <b>{{ activeDataset.name }}</b>
        <span>{{
          activeVersion?.status === 'draft' ? '编辑草稿' : `查看 v${activeVersion?.version ?? '—'}`
        }}</span>
      </div>
    </template>

    <VersionSelector
      v-if="activeDatasetId"
      :versions="versions"
      :active-id="activeVersionId"
      :busy="busy"
      @select="selectVersion"
      @create-draft="createDraft"
      @publish="publishDraft"
      @discard="discardDraft"
      @export="exportVersion"
      @export-excel="exportExcelVersion"
    />

    <div v-if="activeDatasetId" class="dataset-actions">
      <ElButton
        type="primary"
        plain
        :disabled="!editable"
        data-testid="open-ai-generation"
        @click="generationDialog = true"
      >
        AI 生成用例
      </ElButton>
      <span>{{ editable ? '候选经人工审核后才会加入草稿' : '请先创建或切换到草稿' }}</span>
    </div>

    <ElAlert
      v-if="importErrors.length || excelImportIssues.length"
      class="validation-alert"
      title="导入失败"
      type="error"
      :closable="false"
      show-icon
      data-testid="dataset-import-errors"
    >
      <ul v-if="excelImportIssues.length" data-testid="excel-import-issues">
        <li
          v-for="(issue, index) in excelImportIssues"
          :key="`${issue.sheet}-${issue.row}-${issue.column}-${issue.message}`"
          :data-testid="`excel-import-issue-${index}`"
        >
          工作表 <b data-testid="excel-import-issue-sheet">{{ issue.sheet }}</b> · 行
          <span data-testid="excel-import-issue-row">{{ issue.row ?? '—' }}</span> · 列
          <span data-testid="excel-import-issue-column">{{ issue.column ?? '—' }}</span
          >：{{ issue.message }}
        </li>
      </ul>
      <p v-if="excelImportTruncated">
        共发现 {{ excelImportTotalCount }} 个问题，仅展示前 {{ excelImportIssues.length }} 个。
      </p>
      <ul v-else>
        <li v-for="message in importErrors" :key="message">{{ message }}</li>
      </ul>
    </ElAlert>

    <ElAlert
      v-if="validationIssues.length"
      class="validation-alert"
      title="草稿尚不能发布"
      type="error"
      :closable="false"
      show-icon
    >
      <ul>
        <li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`">
          <code>{{ issue.path }}</code
          >：{{ issue.message }}
        </li>
      </ul>
    </ElAlert>

    <div v-loading="loading" class="dataset-layout">
      <DatasetList
        :items="datasets"
        :selected-id="activeDatasetId"
        :loading="loading"
        @select="selectDataset"
        @create="openCreate"
        @copy="openCopy"
        @archive="archiveDataset"
        @import="openImport"
        @import-excel="openExcelImport"
        @download-excel-template="downloadExcelTemplate"
      />
      <CaseTable
        :items="activeVersion?.cases ?? []"
        :selected-id="activeCaseId"
        :editable="editable"
        @select="selectCase"
        @add="addCase"
        @copy="copyCase"
        @remove="removeCase"
        @reorder="reorderCases"
      />
      <CaseEditor
        :item="editedCase"
        :editable="editable"
        :saving="busy"
        :validation-issues="activeCaseIssues"
        @save="saveCase"
      />
    </div>

    <div v-if="activeDatasetId" class="dataset-run-bar">
      <div class="run-bar-info">
        <b>用此版本运行评估</b>
        <span v-if="activeVersion?.status === 'published'">
          v{{ activeVersion.version }} · {{ activeVersion.cases.length }} 个用例 · 内容
          {{ activeVersion.content_sha256.slice(0, 10) }}
        </span>
        <span v-else>草稿不能运行，请先验证并发布。</span>
      </div>
      <ElSelect
        :model-value="selectedAgent"
        data-testid="dataset-agent-select"
        aria-label="运行 Agent 版本"
        @update:model-value="onAgentChange"
      >
        <ElOptionGroup
          v-for="group in groupedTargetVersions"
          :key="group.label"
          :label="group.label"
        >
          <ElOption
            v-for="item in group.items"
            :key="item.id"
            :label="`${item.label} · ${item.id}${item.is_latest ? '（最新）' : ''}`"
            :value="item.id"
          />
        </ElOptionGroup>
      </ElSelect>
      <ElSelect
        :model-value="selectedEvaluators"
        multiple
        collapse-tags
        aria-label="运行评估器"
        @update:model-value="onEvaluatorsChange"
      >
        <ElOption v-for="item in evaluators" :key="item.id" :label="item.name" :value="item.id" />
      </ElSelect>
      <ElButton
        type="primary"
        :disabled="activeVersion?.status !== 'published'"
        :loading="busy"
        data-testid="run-dataset-version"
        @click="launchEvaluation"
        >运行此版本 →</ElButton
      >
    </div>

    <input
      ref="importInput"
      class="hidden-file-input"
      type="file"
      accept="application/json,.json"
      @change="importDataset"
    />
    <input
      ref="excelImportInput"
      class="hidden-file-input"
      type="file"
      accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      data-testid="excel-import-file"
      @change="importExcelDataset"
    />

    <ElDialog
      :model-value="datasetDialog"
      :title="dialogMode === 'create' ? '新建测评集' : '复制测评集'"
      width="min(460px, 92vw)"
      @update:model-value="(v: boolean) => (datasetDialog = v)"
    >
      <ElForm label-position="top">
        <ElFormItem label="名称">
          <ElInput
            :model-value="dialogName"
            data-testid="dataset-name"
            @update:model-value="(v: string) => (dialogName = v)"
          />
        </ElFormItem>
        <ElFormItem v-if="dialogMode === 'create'" label="描述">
          <ElInput
            :model-value="dialogDescription"
            type="textarea"
            :rows="3"
            @update:model-value="(v: string) => (dialogDescription = v)"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="datasetDialog = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="busy"
          data-testid="submit-dataset"
          @click="submitDatasetDialog"
          >确认</ElButton
        >
      </template>
    </ElDialog>

    <DatasetGenerationDialog
      :model-value="generationDialog"
      :dataset-id="activeDatasetId"
      :draft="editable ? activeVersion : null"
      @update:model-value="(v: boolean) => (generationDialog = v)"
      @accepted="generationAccepted"
    />
  </PageContainer>
</template>

<style scoped lang="scss">
.workspace-status {
  display: flex;
  flex-direction: column;
  padding: var(--spacing-sm) var(--spacing-lg);
  background-color: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  text-align: right;

  b {
    color: var(--text-primary);
    font-size: var(--font-size-body);
  }

  span {
    color: var(--text-secondary);
    font-size: var(--font-size-small);
  }
}

.validation-alert {
  border-radius: var(--radius);

  code {
    font-family: var(--font-family-mono);
    background-color: var(--gray-100);
    padding: 0 var(--spacing-xs);
    border-radius: var(--radius-small);
  }
}

.dataset-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);

  span {
    color: var(--text-secondary);
    font-size: var(--font-size-small);
  }
}

.dataset-layout {
  display: grid;
  grid-template-columns: 280px 320px 1fr;
  gap: var(--spacing-lg);
  align-items: start;
  min-height: 400px;

  :deep(.dataset-column) {
    background-color: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-card);
    box-shadow: var(--elevation-1);
    overflow: hidden;
  }
}

.dataset-run-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-lg) var(--spacing-xl);
  background-color: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-card);
  box-shadow: var(--elevation-1);
  flex-wrap: wrap;
}

.run-bar-info {
  flex: 1;
  min-width: 200px;

  b {
    display: block;
    color: var(--text-primary);
    font-size: var(--font-size-body);
    margin-bottom: 2px;
  }

  span {
    color: var(--text-secondary);
    font-size: var(--font-size-small);
  }
}

.hidden-file-input {
  display: none;
}

@include respond-to(lg) {
  .dataset-layout {
    grid-template-columns: 1fr;
  }
}
</style>
