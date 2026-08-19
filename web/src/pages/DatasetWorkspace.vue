<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, ApiError, type EvaluatorOption, type Run, type Version } from '../api/client'
import { datasetApi } from '../api/datasets'
import DatasetList from '../components/dataset/DatasetList.vue'
import VersionSelector from '../components/dataset/VersionSelector.vue'
import CaseTable from '../components/dataset/CaseTable.vue'
import CaseEditor from '../components/dataset/CaseEditor.vue'
import type {
  DatasetExport, DatasetSummary, DatasetVersion, EvaluationCase, ExcelImportIssue, ValidationIssue,
} from '../types/dataset'

const emit = defineEmits<{ runCreated: [run: Run] }>()

const datasets = shallowRef<DatasetSummary[]>([])
const versions = shallowRef<DatasetVersion[]>([])
const activeDatasetId = ref('')
const activeVersionId = ref('')
const activeCaseId = ref('')
const editedCase = ref<EvaluationCase|null>(null)
const targetVersions = ref<Version[]>([])
const evaluators = ref<EvaluatorOption[]>([])
const selectedAgent = ref('loan-agent-v2-fixed')
const selectedEvaluators = ref<string[]>([])
const busy = ref(false)
const loading = ref(false)
const validationIssues = ref<ValidationIssue[]>([])
const datasetDialog = ref(false)
const dialogMode = ref<'create'|'copy'>('create')
const dialogName = ref('')
const dialogDescription = ref('')
const importInput = ref<HTMLInputElement|null>(null)
const excelImportInput = ref<HTMLInputElement|null>(null)
const excelImportIssues = ref<ExcelImportIssue[]>([])
const importErrors = ref<string[]>([])
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const activeVersion = computed<DatasetVersion|null>(
  () => versions.value.find(item => item.id === activeVersionId.value) ?? null,
)
const editable = computed(() => activeVersion.value?.status === 'draft')
const publishedVersions = computed(() => versions.value.filter(item => item.status === 'published'))
const activeDataset = computed(() => datasets.value.find(item => item.id === activeDatasetId.value) ?? null)
const activeCaseIssues = computed(() => {
  const caseIndex = activeVersion.value?.cases.findIndex(item => item.id === activeCaseId.value) ?? -1
  if (caseIndex < 0) return []
  const prefix = `cases[${caseIndex}]`
  return validationIssues.value.filter(issue => issue.path.startsWith(prefix))
})

function chooseVersion(preferredId = '') {
  const selected = versions.value.find(item => item.id === preferredId)
    ?? versions.value.find(item => item.status === 'draft')
    ?? publishedVersions.value[0]
    ?? null
  activeVersionId.value = selected?.id ?? ''
  selectFirstCase(selected)
}

function selectFirstCase(version: DatasetVersion|null) {
  const selected = version?.cases.find(item => item.id === activeCaseId.value)
    ?? version?.cases[0]
    ?? null
  activeCaseId.value = selected?.id ?? ''
  editedCase.value = selected ? cloneJson(selected) : null
}

async function loadDatasets(preferredDatasetId = activeDatasetId.value) {
  datasets.value = await datasetApi.list()
  const selected = datasets.value.find(item => item.id === preferredDatasetId) ?? datasets.value[0]
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
    const detail = await datasetApi.detail(datasetId)
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
    initial_state: {},
    turns: [{
      id: crypto.randomUUID(),
      input: { skill: 'loan_approval' },
      expected_skill: 'loan_approval',
      expectations: [],
      required_tools: [],
      forbidden_tools: [],
      policy_rules: [],
      notes: '',
    }],
  }
}

function addCase() {
  const item = newCase()
  activeCaseId.value = item.id
  editedCase.value = item
  validationIssues.value = []
}

async function refreshAfterMutation(version: DatasetVersion, caseId = activeCaseId.value) {
  datasets.value = await datasetApi.list()
  versions.value = await datasetApi.versions(activeDatasetId.value)
  activeVersionId.value = version.id
  activeCaseId.value = caseId
  const current = versions.value.find(item => item.id === version.id) ?? version
  const selected = current.cases.find(item => item.id === caseId) ?? current.cases[0] ?? null
  editedCase.value = selected ? cloneJson(selected) : null
}

async function saveCase(item: EvaluationCase) {
  if (!activeDatasetId.value || !editable.value) return
  busy.value = true
  try {
    const exists = activeVersion.value?.cases.some(entry => entry.id === item.id) ?? false
    const version = exists
      ? await datasetApi.updateCase(activeDatasetId.value, item)
      : await datasetApi.addCase(activeDatasetId.value, item)
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
  const version = await datasetApi.copyCase(activeDatasetId.value, item.id)
  const copied = version.cases.find(entry => !activeVersion.value?.cases.some(old => old.id === entry.id))
  await refreshAfterMutation(version, copied?.id)
  ElMessage.success('已复制用例')
}

async function removeCase(item: EvaluationCase) {
  await ElMessageBox.confirm(`删除草稿中的“${item.name}”？已发布版本不会受影响。`, '删除用例', { type: 'warning' })
  const version = await datasetApi.removeCase(activeDatasetId.value, item.id)
  activeCaseId.value = ''
  await refreshAfterMutation(version)
  ElMessage.success('用例已从草稿移除')
}

async function reorderCases(ids: string[]) {
  const version = await datasetApi.reorderCases(activeDatasetId.value, ids)
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
    const result = dialogMode.value === 'create'
      ? await datasetApi.create(dialogName.value, dialogDescription.value)
      : await datasetApi.copy(
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
  await ElMessageBox.confirm(`归档“${item.name}”？历史版本和运行记录仍可读取。`, '归档测评集', { type: 'warning' })
  await datasetApi.archive(item.id)
  await loadDatasets('')
  ElMessage.success('测评集已归档')
}

async function createDraft(base: number|null) {
  busy.value = true
  try {
    const draft = await datasetApi.createDraft(activeDatasetId.value, base)
    await selectDataset(activeDatasetId.value, draft.id)
    ElMessage.success('新版本草稿已创建')
  } catch (error) {
    showError(error, '创建草稿失败')
  } finally {
    busy.value = false
  }
}

async function discardDraft() {
  await ElMessageBox.confirm('放弃当前草稿？草稿中的修改将无法恢复。', '放弃草稿', { type: 'warning' })
  await datasetApi.discardDraft(activeDatasetId.value)
  await selectDataset(activeDatasetId.value)
  ElMessage.success('草稿已放弃')
}

async function publishDraft() {
  busy.value = true
  validationIssues.value = []
  try {
    const published = await datasetApi.publish(activeDatasetId.value)
    await selectDataset(activeDatasetId.value, published.id)
    datasets.value = await datasetApi.list()
    ElMessage.success(`已发布 v${published.version}`)
  } catch (error) {
    if (error instanceof ApiError && Array.isArray(error.detail)) {
      validationIssues.value = error.detail as ValidationIssue[]
    }
    showError(error, '发布失败，请检查用例')
  } finally {
    busy.value = false
  }
}

async function exportVersion(version: number) {
  const payload = await datasetApi.exportVersion(activeDatasetId.value, version)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${activeDataset.value?.name ?? 'dataset'}-v${version}.json`
  link.click()
  URL.revokeObjectURL(url)
}

function excelFilename(name: string, version: number) {
  const sanitized = name.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[.-]+|[.-]+$/g, '')
  return `${sanitized || 'dataset'}-v${version}.xlsx`
}

async function exportExcelVersion(version: number) {
  try {
    const blob = await datasetApi.exportExcel(activeDatasetId.value, version)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = excelFilename(activeDataset.value?.name ?? 'dataset', version)
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    showError(error, '导出 Excel 失败')
  }
}

function openImport() {
  importErrors.value = []
  excelImportIssues.value = []
  importInput.value?.click()
}

function importErrorMessages(error: unknown, fallback: string) {
  if (error instanceof ApiError && Array.isArray(error.detail)) {
    return error.detail.map(item => {
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
    const result = await datasetApi.importDataset(payload)
    importErrors.value = []
    await loadDatasets(result.dataset.id)
    ElMessage.success('测评集已导入')
  } catch (error) {
    importErrors.value = importErrorMessages(error, 'JSON 导入失败').map(message => `JSON：${message}`)
  } finally {
    input.value = ''
  }
}

function openExcelImport() {
  importErrors.value = []
  excelImportIssues.value = []
  excelImportInput.value?.click()
}

function datasetNameFromExcel(file: File) {
  return file.name.replace(/\.xlsx$/i, '').trim() || 'Excel Dataset'
}

function isExcelImportIssue(value: unknown): value is ExcelImportIssue {
  return typeof value === 'object' && value !== null
    && typeof (value as ExcelImportIssue).sheet === 'string'
    && typeof (value as ExcelImportIssue).message === 'string'
}

async function importExcelDataset(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  excelImportIssues.value = []
  try {
    const result = await datasetApi.importExcel(file, datasetNameFromExcel(file), '')
    await loadDatasets(result.dataset.id)
    ElMessage.success('Excel 已导入为草稿')
  } catch (error) {
    if (error instanceof ApiError && Array.isArray(error.detail)) {
      excelImportIssues.value = error.detail.filter(isExcelImportIssue)
      if (excelImportIssues.value.length) return
    }
    importErrors.value = importErrorMessages(error, 'Excel 导入失败').map(message => `Excel：${message}`)
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
    const run = await api.launch(
      selectedAgent.value,
      activeDatasetId.value,
      activeVersion.value.version,
      selectedEvaluators.value,
    )
    emit('runCreated', run)
    ElMessage.success('评估已完成，正在打开结果报告')
  } catch (error) {
    showError(error, '运行评估失败')
  } finally {
    busy.value = false
  }
}

function showError(error: unknown, fallback: string) {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    const [agents, evaluatorItems] = await Promise.all([api.versions(), api.evaluators()])
    targetVersions.value = agents
    evaluators.value = evaluatorItems
    selectedEvaluators.value = evaluatorItems.map(item => item.id)
    await loadDatasets()
  } catch (error) {
    showError(error, '无法加载测评集')
  }
})
</script>

<template>
  <section class="dataset-workspace" aria-labelledby="dataset-workspace-title">
    <div class="workspace-heading">
      <div>
        <span class="step">DATASET WORKSPACE</span>
        <h1 id="dataset-workspace-title">测评集与用例管理</h1>
        <p>编辑草稿、发布不可变版本，并用选定版本运行真实评估。</p>
      </div>
      <div v-if="activeDataset" class="workspace-status">
        <b>{{ activeDataset.name }}</b>
        <span>{{ activeVersion?.status === 'draft' ? '编辑草稿' : `查看 v${activeVersion?.version ?? '—'}` }}</span>
      </div>
    </div>

    <el-alert
      v-if="importErrors.length || excelImportIssues.length"
      class="validation-alert"
      title="导入失败"
      type="error"
      :closable="false"
      show-icon
      data-testid="dataset-import-errors"
    >
      <ul v-if="excelImportIssues.length" data-testid="excel-import-issues">
        <li v-for="(issue, index) in excelImportIssues" :key="`${issue.sheet}-${issue.row}-${issue.column}-${issue.message}`" :data-testid="`excel-import-issue-${index}`">
          工作表 <b data-testid="excel-import-issue-sheet">{{ issue.sheet }}</b> · 行 <span data-testid="excel-import-issue-row">{{ issue.row ?? '—' }}</span> · 列 <span data-testid="excel-import-issue-column">{{ issue.column ?? '—' }}</span>：{{ issue.message }}
        </li>
      </ul>
      <ul v-else><li v-for="message in importErrors" :key="message">{{ message }}</li></ul>
    </el-alert>

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

    <el-alert
      v-if="validationIssues.length"
      class="validation-alert"
      title="草稿尚不能发布"
      type="error"
      :closable="false"
      show-icon
    >
      <ul><li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`"><code>{{ issue.path }}</code>：{{ issue.message }}</li></ul>
    </el-alert>

    <div class="dataset-layout" v-loading="loading">
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
      <div>
        <b>用此版本运行评估</b>
        <span v-if="activeVersion?.status === 'published'">v{{ activeVersion.version }} · {{ activeVersion.cases.length }} 个用例 · 内容 {{ activeVersion.content_sha256.slice(0, 10) }}</span>
        <span v-else>草稿不能运行，请先验证并发布。</span>
      </div>
      <el-select v-model="selectedAgent" data-testid="dataset-agent-select" aria-label="运行 Agent 版本">
        <el-option v-for="item in targetVersions" :key="item.id" :label="item.label" :value="item.id" />
      </el-select>
      <el-select v-model="selectedEvaluators" multiple collapse-tags aria-label="运行评估器">
        <el-option v-for="item in evaluators" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-button type="primary" :disabled="activeVersion?.status !== 'published'" :loading="busy" data-testid="run-dataset-version" @click="launchEvaluation">运行此版本 →</el-button>
    </div>

    <input ref="importInput" class="hidden-file-input" type="file" accept="application/json,.json" @change="importDataset" />
    <input ref="excelImportInput" class="hidden-file-input" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" data-testid="excel-import-file" @change="importExcelDataset" />

    <el-dialog v-model="datasetDialog" :title="dialogMode === 'create' ? '新建测评集' : '复制测评集'" width="min(460px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="dialogName" data-testid="dataset-name" /></el-form-item>
        <el-form-item v-if="dialogMode === 'create'" label="描述"><el-input v-model="dialogDescription" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="datasetDialog = false">取消</el-button><el-button type="primary" :loading="busy" data-testid="submit-dataset" @click="submitDatasetDialog">确认</el-button></template>
    </el-dialog>

  </section>
</template>
