<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTag,
} from 'element-plus'
import { datasetGenerationApi } from '@/api/dataset-generation'
import { datasetsApi } from '@/api/datasets'
import { ApiError } from '@/utils/request'
import type { DatasetSummary, DatasetVersion, EvaluationCase } from '@/types/dataset'
import type {
  DifficultyCounts,
  GeneratedCandidate,
  GenerationCounts,
  GenerationModelProfile,
  GenerationResult,
  TargetCatalogItem,
  TargetType,
  TargetVersionItem,
  TurnMode,
} from '@/types/dataset-generation'
import CaseEditor from './CaseEditor.vue'

const props = defineProps<{
  modelValue: boolean
  datasetId: string
  draft: DatasetVersion | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  accepted: [caseIds: string[]]
}>()

const targetType = ref<TargetType>('agent')
const targets = ref<TargetCatalogItem[]>([])
const targetVersions = ref<TargetVersionItem[]>([])
const profiles = ref<GenerationModelProfile[]>([])
const selectedTargetKey = ref('')
const selectedVersionId = ref('')
const selectedProfileId = ref('')
const apiKey = ref('')
const configuringCredential = ref(false)
const count = ref(6)
const turnMode = ref<TurnMode>('single')
const maxTurns = ref(3)
const mixedSingle = ref(3)
const categories = ref<GenerationCounts>({ positive: 2, negative: 2, boundary: 2 })
const difficulties = ref<DifficultyCounts>({ easy: 2, medium: 2, hard: 2 })
const referenceDatasets = shallowRef<DatasetSummary[]>([])
const referenceVersions = shallowRef<DatasetVersion[]>([])
const referenceDatasetId = ref('none')
const referenceVersion = ref('')
const referenceCaseIds = ref<string[]>([])
const instructions = ref('')
const loading = ref(false)
const loadError = ref('')
const accepting = ref(false)
const result = shallowRef<GenerationResult | null>(null)
const selectedCandidateIds = ref<string[]>([])
const activeCandidateId = ref('')
const acceptKey = ref('')
const currentStep = ref<'settings' | 'review'>('settings')
const advancedSections = ref<string[]>([])
const credentialExpanded = ref(false)
const reviewFilter = ref<'all' | 'valid' | 'issues'>('all')

function targetKey(item: TargetCatalogItem) {
  return JSON.stringify([item.platform_id, item.target_type, item.external_target_id])
}
const selectedTarget = computed(
  () => targets.value.find((item) => targetKey(item) === selectedTargetKey.value) ?? null,
)
const selectedVersion = computed(
  () =>
    targetVersions.value.find(
      (item) => item.ref.external_version_id === selectedVersionId.value,
    ) ?? null,
)
const selectedProfile = computed(
  () => profiles.value.find((item) => item.id === selectedProfileId.value) ?? null,
)
const activeCandidate = computed<GeneratedCandidate | null>(() => {
  const candidates: GeneratedCandidate[] = result.value ? result.value.candidates : []
  for (const candidate of candidates) {
    if (candidate.candidate_id === activeCandidateId.value) return candidate
  }
  return null
})
const validCandidates = computed(() =>
  result.value?.candidates.filter((item) => item.case !== null && item.issues.length === 0) ?? [],
)
const visibleCandidates = computed(() => {
  const candidates = result.value?.candidates ?? []
  if (reviewFilter.value === 'valid') {
    return candidates.filter((item) => item.case !== null && item.issues.length === 0)
  }
  if (reviewFilter.value === 'issues') {
    return candidates.filter((item) => item.case === null || item.issues.length > 0)
  }
  return candidates
})
function selectedCases(): Array<{ slot_index: number; case: EvaluationCase }> {
  const cases: Array<{ slot_index: number; case: EvaluationCase }> = []
  const candidates: GeneratedCandidate[] = result.value ? result.value.candidates : []
  for (const candidate of candidates) {
    if (
      selectedCandidateIds.value.includes(candidate.candidate_id) &&
      candidate.case !== null &&
      candidate.slot_index !== null &&
      candidate.issues.length === 0
    ) {
      cases.push({ slot_index: candidate.slot_index, case: candidate.case })
    }
  }
  return cases
}
const categoryTotal = computed(
  () => categories.value.positive + categories.value.negative + categories.value.boundary,
)
const difficultyTotal = computed(
  () => difficulties.value.easy + difficulties.value.medium + difficulties.value.hard,
)
const mixedMulti = computed(() => count.value - mixedSingle.value)
const referenceCases = computed<EvaluationCase[]>(() => {
  for (const version of referenceVersions.value) {
    if (String(version.version) === referenceVersion.value) return version.cases
  }
  return []
})
const canGenerate = computed(
  () =>
    props.draft !== null &&
    selectedVersion.value !== null &&
    selectedProfile.value?.available === true &&
    categoryTotal.value === count.value &&
    difficultyTotal.value === count.value &&
    (referenceDatasetId.value === 'none' || referenceVersion.value !== '') &&
    (turnMode.value !== 'mixed' || (mixedSingle.value > 0 && mixedMulti.value > 0)),
)

const categoryLabels: Record<string, string> = {
  positive: '正例',
  negative: '负例',
  boundary: '边界',
}
const difficultyLabels: Record<string, string> = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
}

function evenly(total: number) {
  const base = Math.floor(total / 3)
  return [base + (total % 3 > 0 ? 1 : 0), base + (total % 3 > 1 ? 1 : 0), base]
}

function resetCounts() {
  const [first, second, third] = evenly(count.value)
  categories.value = { positive: first, negative: second, boundary: third }
  difficulties.value = { easy: first, medium: second, hard: third }
  mixedSingle.value = Math.max(1, Math.floor(count.value / 2))
}

function resetReview() {
  result.value = null
  selectedCandidateIds.value = []
  activeCandidateId.value = ''
  acceptKey.value = ''
  currentStep.value = 'settings'
  reviewFilter.value = 'all'
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.detail && typeof error.detail === 'object') {
    const detail = error.detail as { message?: unknown }
    if (typeof detail.message === 'string') return detail.message
  }
  return error instanceof Error ? error.message : fallback
}

async function loadTargets() {
  targets.value = await datasetGenerationApi.targets(targetType.value)
  selectedTargetKey.value = targets.value[0] ? targetKey(targets.value[0]) : ''
  await loadTargetVersions()
}

async function loadTargetVersions() {
  targetVersions.value = selectedTarget.value
    ? await datasetGenerationApi.targetVersions(selectedTarget.value)
    : []
  selectedVersionId.value = targetVersions.value[0]?.ref.external_version_id ?? ''
}

async function initialize() {
  loading.value = true
  loadError.value = ''
  try {
    const loaded = await Promise.all([
      datasetGenerationApi.modelProfiles(),
      datasetsApi.list(),
    ])
    profiles.value = loaded[0]
    referenceDatasets.value = loaded[1]
    selectedProfileId.value =
      profiles.value.find((item) => item.available)?.id ?? profiles.value[0]?.id ?? ''
    await loadTargets()
  } catch (error) {
    loadError.value = errorMessage(error, '无法加载生成配置')
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

async function reloadProfiles(profileId = selectedProfileId.value) {
  profiles.value = await datasetGenerationApi.modelProfiles()
  selectedProfileId.value = profiles.value.some((item) => item.id === profileId)
    ? profileId
    : profiles.value[0]?.id ?? ''
}

async function configureCredential() {
  const profile = selectedProfile.value
  const value = apiKey.value.trim()
  if (!profile || value.length < 8) {
    ElMessage.warning('请输入有效的 API Key')
    return
  }
  configuringCredential.value = true
  try {
    await datasetGenerationApi.configureCredential(profile.id, value)
    await reloadProfiles(profile.id)
    ElMessage.success('API Key 验证成功，本次服务运行期间可用')
  } catch (error) {
    ElMessage.error(errorMessage(error, 'API Key 验证失败'))
  } finally {
    apiKey.value = ''
    configuringCredential.value = false
  }
}

async function deleteCredential() {
  const profile = selectedProfile.value
  if (!profile) return
  configuringCredential.value = true
  try {
    const status = await datasetGenerationApi.deleteCredential(profile.id)
    await reloadProfiles(profile.id)
    ElMessage.success(status.available ? '已恢复使用服务端环境变量凭据' : '运行时 API Key 已清除')
  } catch (error) {
    ElMessage.error(errorMessage(error, '清除 API Key 失败'))
  } finally {
    apiKey.value = ''
    configuringCredential.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open && !targets.value.length) void initialize()
  },
  { immediate: true },
)

watch(count, () => resetCounts())

async function changeTargetType(value: string | number | boolean | undefined) {
  targetType.value = value as TargetType
  resetReview()
  await loadTargets()
}

async function changeTarget(value: string | number | boolean | undefined) {
  selectedTargetKey.value = String(value)
  resetReview()
  await loadTargetVersions()
}

async function changeReferenceDataset(value: string | number | boolean | undefined) {
  referenceDatasetId.value = String(value ?? 'none')
  referenceVersions.value = []
  referenceVersion.value = ''
  referenceCaseIds.value = []
  if (referenceDatasetId.value === 'none') return
  const versions = await datasetsApi.versions(referenceDatasetId.value)
  referenceVersions.value = versions.filter((item) => item.status === 'published')
  referenceVersion.value = String(referenceVersions.value[0]?.version ?? '')
}

function changeReferenceVersion(value: string | number | boolean | undefined) {
  referenceVersion.value = String(value ?? '')
  referenceCaseIds.value = []
}

function changeReferenceCases(value: string | number | boolean | object | null) {
  referenceCaseIds.value = ((value as string[]) ?? []).slice(0, 20)
}

async function generate() {
  if (!props.draft || !selectedVersion.value || !selectedProfile.value) return
  loading.value = true
  try {
    const hasReference =
      referenceDatasetId.value !== 'none' && referenceVersion.value !== ''
    const generated = await datasetGenerationApi.generate(props.datasetId, {
      draft_id: props.draft.id,
      draft_content_sha256: props.draft.content_sha256,
      target_ref: selectedVersion.value.ref,
      count: count.value,
      reference_source: hasReference
        ? { dataset_id: referenceDatasetId.value, version: Number(referenceVersion.value) }
        : null,
      reference_case_ids: hasReference ? referenceCaseIds.value : [],
      turn_mode: turnMode.value,
      turn_counts:
        turnMode.value === 'mixed'
          ? { single: mixedSingle.value, multi: mixedMulti.value }
          : null,
      max_turns_per_case: maxTurns.value,
      category_counts: categories.value,
      difficulty_counts: difficulties.value,
      instructions: instructions.value,
      model_profile_id: selectedProfile.value.id,
    })
    result.value = generated
    const valid = generated.candidates.filter(
      (item) => item.case !== null && item.issues.length === 0,
    )
    selectedCandidateIds.value = []
    activeCandidateId.value = generated.candidates[0]?.candidate_id ?? ''
    acceptKey.value = ''
    currentStep.value = 'review'
    reviewFilter.value = 'all'
    if (!valid.length) ElMessage.warning('模型已返回结果，但没有可接收的有效候选')
  } catch (error) {
    ElMessage.error(errorMessage(error, '生成失败'))
  } finally {
    loading.value = false
  }
}

function selectAllValid() {
  selectedCandidateIds.value = validCandidates.value.map((item) => item.candidate_id)
  acceptKey.value = ''
}

function clearSelection() {
  selectedCandidateIds.value = []
  acceptKey.value = ''
}

function changeReviewFilter(value: string | number | boolean | undefined) {
  reviewFilter.value = value as 'all' | 'valid' | 'issues'
  if (!visibleCandidates.value.some((item) => item.candidate_id === activeCandidateId.value)) {
    activeCandidateId.value = visibleCandidates.value[0]?.candidate_id ?? ''
  }
}

function returnToSettings() {
  currentStep.value = 'settings'
}

function continueReview() {
  if (!result.value) return
  currentStep.value = 'review'
  if (!result.value.candidates.some((item) => item.candidate_id === activeCandidateId.value)) {
    activeCandidateId.value = result.value.candidates[0]?.candidate_id ?? ''
  }
}

function toggleCandidate(candidateId: string, checked: boolean) {
  selectedCandidateIds.value = checked
    ? [...new Set([...selectedCandidateIds.value, candidateId])]
    : selectedCandidateIds.value.filter((item) => item !== candidateId)
  acceptKey.value = ''
}

async function validateEditedCase(item: EvaluationCase) {
  if (!result.value || !activeCandidate.value) return
  if (activeCandidate.value.slot_index === null) {
    ElMessage.error('候选缺少生成槽位，请重新生成')
    return
  }
  loading.value = true
  try {
    const checked = await datasetGenerationApi.validate(props.datasetId, {
      draft_id: result.value.draft_id,
      draft_content_sha256: result.value.draft_content_sha256,
      target_ref: result.value.target_ref,
      target_descriptor_sha256: result.value.target_descriptor_sha256,
      recipe_version: result.value.recipe_version,
      acceptance_token: result.value.acceptance_token,
      candidate_id: activeCandidate.value.candidate_id,
      slot_index: activeCandidate.value.slot_index,
      case: item,
    })
    const index = result.value.candidates.findIndex(
      (candidate) => candidate.candidate_id === checked.candidate_id,
    )
    const candidates = result.value.candidates.map((candidate, candidateIndex) =>
      candidateIndex === index ? checked : candidate,
    )
    result.value = {
      ...result.value,
      candidates,
      valid_count: candidates.filter(
        (candidate) => candidate.case !== null && candidate.issues.length === 0,
      ).length,
      invalid_count: candidates.filter(
        (candidate) => candidate.case === null || candidate.issues.length > 0,
      ).length,
    }
    if (checked.issues.length) {
      selectedCandidateIds.value = selectedCandidateIds.value.filter(
        (id) => id !== checked.candidate_id,
      )
      ElMessage.warning('修改已保留，但该候选仍有校验问题')
    } else {
      ElMessage.success('候选修改已通过校验')
    }
    acceptKey.value = ''
  } catch (error) {
    ElMessage.error(errorMessage(error, '候选校验失败'))
  } finally {
    loading.value = false
  }
}

async function acceptSelected() {
  const candidates = selectedCases()
  if (!result.value || !candidates.length) return
  accepting.value = true
  acceptKey.value ||= crypto.randomUUID()
  try {
    const receipt = await datasetGenerationApi.accept(
      props.datasetId,
      {
        draft_id: result.value.draft_id,
        draft_content_sha256: result.value.draft_content_sha256,
        target_ref: result.value.target_ref,
        target_descriptor_sha256: result.value.target_descriptor_sha256,
        recipe_version: result.value.recipe_version,
        acceptance_token: result.value.acceptance_token,
        candidates,
      },
      acceptKey.value,
    )
    resetReview()
    emit('accepted', receipt.inserted_case_ids)
  } catch (error) {
    ElMessage.error(errorMessage(error, '加入草稿失败'))
  } finally {
    accepting.value = false
  }
}

async function requestClose() {
  if (result.value?.candidates.length) {
    try {
      await ElMessageBox.confirm('未加入草稿的候选会丢失，确认关闭？', '关闭生成审核', {
        type: 'warning',
      })
    } catch {
      return
    }
  }
  resetReview()
  apiKey.value = ''
  emit('update:modelValue', false)
}
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    title="AI 生成测评用例"
    width="min(1120px, 96vw)"
    top="4vh"
    :close-on-click-modal="false"
    data-testid="generation-dialog"
    @update:model-value="(value: boolean) => { if (!value) void requestClose() }"
  >
    <div v-loading="loading" class="generation-layout">
      <section v-if="currentStep === 'settings'" class="generation-config" data-testid="generation-settings">
        <ElAlert v-if="loadError" :title="`生成配置加载失败：${loadError}`" type="error" :closable="false" show-icon>
          <ElButton link type="primary" @click="initialize">重新加载</ElButton>
        </ElAlert>
        <ElAlert
          title="AI 根据评测对象的能力声明生成候选；候选通过系统校验并经你审核后，才会加入当前草稿。"
          type="info"
          :closable="false"
          show-icon
        />
        <ElForm label-position="top">
          <div class="settings-card">
            <div class="section-heading">
              <div><b>评测对象</b><small>明确本次要覆盖的 Agent 或 Skill 版本</small></div>
              <ElTag v-if="selectedVersion" effect="plain" type="success">版本已锁定</ElTag>
            </div>
            <div class="form-grid target-grid">
              <ElFormItem label="对象类型">
                <ElRadioGroup :model-value="targetType" @change="changeTargetType">
                  <ElRadioButton value="agent">Agent</ElRadioButton>
                  <ElRadioButton value="skill">Skill</ElRadioButton>
                </ElRadioGroup>
              </ElFormItem>
              <ElFormItem label="评测对象">
                <ElSelect :model-value="selectedTargetKey" @change="changeTarget">
                  <ElOption v-for="item in targets" :key="targetKey(item)" :label="item.display_name" :value="targetKey(item)" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="具体版本">
                <ElSelect :model-value="selectedVersionId" @update:model-value="(v: string) => (selectedVersionId = v)">
                  <ElOption v-for="item in targetVersions" :key="item.ref.external_version_id" :label="`${item.ref.external_version_id}${item.reproducibility_limited ? '（复现受限）' : ''}`" :value="item.ref.external_version_id" />
                </ElSelect>
              </ElFormItem>
            </div>
            <p v-if="selectedTarget?.description" class="object-description">{{ selectedTarget.description }}</p>
          </div>

          <div class="settings-card">
            <div class="section-heading"><div><b>生成规模</b><small>先设置数量和会话形态，其余使用推荐分布</small></div></div>
            <div class="form-grid generation-grid">
              <ElFormItem label="生成数量（1–20）">
                <ElInputNumber :model-value="count" :min="1" :max="20" @update:model-value="(v: number | undefined) => (count = v ?? 1)" />
              </ElFormItem>
              <ElFormItem label="对话轮次">
                <ElSelect :model-value="turnMode" @update:model-value="(v: TurnMode) => (turnMode = v)">
                  <ElOption label="仅单轮" value="single" />
                  <ElOption label="仅多轮" value="multi" />
                  <ElOption label="单轮与多轮混合" value="mixed" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem v-if="turnMode !== 'single'" label="每条最多轮数">
                <ElInputNumber :model-value="maxTurns" :min="2" :max="5" @update:model-value="(v: number | undefined) => (maxTurns = v ?? 2)" />
              </ElFormItem>
              <ElFormItem v-if="turnMode === 'mixed'" label="单轮数量">
                <ElInputNumber :model-value="mixedSingle" :min="1" :max="Math.max(1, count - 1)" @update:model-value="(v: number | undefined) => (mixedSingle = v ?? 1)" />
                <small>其余 {{ mixedMulti }} 条为多轮</small>
              </ElFormItem>
            </div>
          </div>

          <div class="model-row settings-card">
            <div>
              <div class="section-heading compact"><div><b>生成模型</b><small>{{ selectedProfile?.display_name ?? '未选择模型' }}</small></div></div>
              <span class="credential-status" :class="{ ready: selectedProfile?.available }">
                {{ selectedProfile?.available ? '凭据可用' : '需要配置 API Key' }}
              </span>
            </div>
            <div class="model-actions">
              <ElSelect :model-value="selectedProfileId" class="model-select" @update:model-value="(v: string) => (selectedProfileId = v)">
                <ElOption v-for="item in profiles" :key="item.id" :label="`${item.display_name}${item.available ? '' : '（未配置）'}`" :value="item.id" />
              </ElSelect>
              <ElButton data-testid="configure-model-credential" @click="credentialExpanded = !credentialExpanded">
                {{ credentialExpanded ? '收起配置' : '配置 API Key' }}
              </ElButton>
            </div>
            <div v-if="credentialExpanded && selectedProfile" class="credential-panel">
              <div class="credential-control">
                <ElInput :model-value="apiKey" type="password" show-password autocomplete="new-password" placeholder="API Key 只发送给后端验证，不写入浏览器或数据库" @update:model-value="(v: string) => (apiKey = v)" @keyup.enter="configureCredential" />
                <ElButton type="primary" plain :loading="configuringCredential" :disabled="apiKey.trim().length < 8" data-testid="validate-model-credential" @click="configureCredential">验证并使用</ElButton>
                <ElButton v-if="selectedProfile.available" :disabled="configuringCredential" @click="deleteCredential">清除运行时配置</ElButton>
              </div>
              <small>页面配置仅保存在后端内存中，服务重启后失效；验证会产生一次极小的模型调用。</small>
            </div>
          </div>

          <ElCollapse v-model="advancedSections" class="advanced-settings">
            <ElCollapseItem name="coverage" title="覆盖分布（可选调整）">
              <div class="distribution-block">
                <div class="distribution-heading"><b>用例分类</b><span :class="{ invalid: categoryTotal !== count }">合计 {{ categoryTotal }}/{{ count }}</span></div>
                <div class="count-grid">
                  <ElFormItem label="正例"><ElInputNumber :model-value="categories.positive" :min="0" :max="count" @update:model-value="(v: number | undefined) => (categories.positive = v ?? 0)" /></ElFormItem>
                  <ElFormItem label="负例"><ElInputNumber :model-value="categories.negative" :min="0" :max="count" @update:model-value="(v: number | undefined) => (categories.negative = v ?? 0)" /></ElFormItem>
                  <ElFormItem label="边界"><ElInputNumber :model-value="categories.boundary" :min="0" :max="count" @update:model-value="(v: number | undefined) => (categories.boundary = v ?? 0)" /></ElFormItem>
                </div>
                <ElAlert v-if="categoryTotal !== count" title="分类数量之和必须等于生成数量" type="warning" :closable="false" />
              </div>
              <div class="distribution-block">
                <div class="distribution-heading"><b>用例难度</b><span :class="{ invalid: difficultyTotal !== count }">合计 {{ difficultyTotal }}/{{ count }}</span></div>
                <div class="count-grid">
                  <ElFormItem label="简单"><ElInputNumber :model-value="difficulties.easy" :min="0" :max="count" @update:model-value="(v: number | undefined) => (difficulties.easy = v ?? 0)" /></ElFormItem>
                  <ElFormItem label="中等"><ElInputNumber :model-value="difficulties.medium" :min="0" :max="count" @update:model-value="(v: number | undefined) => (difficulties.medium = v ?? 0)" /></ElFormItem>
                  <ElFormItem label="困难"><ElInputNumber :model-value="difficulties.hard" :min="0" :max="count" @update:model-value="(v: number | undefined) => (difficulties.hard = v ?? 0)" /></ElFormItem>
                </div>
                <ElAlert v-if="difficultyTotal !== count" title="难度数量之和必须等于生成数量" type="warning" :closable="false" />
              </div>
            </ElCollapseItem>
            <ElCollapseItem name="reference" title="参考用例（可选）">
              <div class="form-grid">
                <ElFormItem label="参考测评集">
                  <ElSelect :model-value="referenceDatasetId" @change="changeReferenceDataset">
                    <ElOption label="不使用参考用例" value="none" />
                    <ElOption v-for="item in referenceDatasets" :key="item.id" :label="item.name" :value="item.id" />
                  </ElSelect>
                </ElFormItem>
                <ElFormItem v-if="referenceDatasetId !== 'none'" label="已发布版本">
                  <ElSelect :model-value="referenceVersion" @change="changeReferenceVersion">
                    <ElOption v-for="item in referenceVersions" :key="item.id" :label="`v${item.version} · ${item.cases.length} 条`" :value="String(item.version)" />
                  </ElSelect>
                </ElFormItem>
                <ElFormItem v-if="referenceVersion" label="指定用例（最多 20 条）">
                  <ElSelect :model-value="referenceCaseIds" multiple filterable collapse-tags placeholder="留空则自动选取代表性用例" @change="changeReferenceCases">
                    <ElOption v-for="item in referenceCases" :key="item.id" :label="item.name" :value="item.id" :disabled="referenceCaseIds.length >= 20 && !referenceCaseIds.includes(item.id)" />
                  </ElSelect>
                </ElFormItem>
              </div>
            </ElCollapseItem>
            <ElCollapseItem name="instructions" title="补充生成要求（可选）">
              <ElFormItem>
                <ElInput :model-value="instructions" type="textarea" :rows="3" maxlength="4000" show-word-limit placeholder="例如：重点覆盖退款前置条件，不要生成安全攻击类用例" @update:model-value="(v: string) => (instructions = v)" />
              </ElFormItem>
            </ElCollapseItem>
          </ElCollapse>
        </ElForm>
      </section>

      <section v-else-if="result" class="generation-review" data-testid="generation-review">
        <div class="review-heading">
          <div>
            <b>审核候选用例</b>
            <span>逐条检查、修正，只有勾选的有效候选才会加入草稿。</span>
          </div>
        </div>
        <div class="review-summary" data-testid="review-summary">
          <div><b>{{ result.generated_count }}</b><span>已生成</span></div>
          <div class="success"><b>{{ result.valid_count }}</b><span>可加入</span></div>
          <div :class="{ danger: result.invalid_count > 0 }"><b>{{ result.invalid_count }}</b><span>待修正</span></div>
          <div class="selected"><b>{{ selectedCases().length }}</b><span>已选择</span></div>
        </div>
        <ElAlert v-if="result.batch_issues.length" type="warning" :closable="false">
          <ul><li v-for="issue in result.batch_issues" :key="`${issue.code}-${issue.path}`"><code>{{ issue.path }}</code>：{{ issue.message }}</li></ul>
        </ElAlert>
        <div class="review-body">
          <aside class="candidate-sidebar">
            <div class="candidate-toolbar">
              <ElRadioGroup :model-value="reviewFilter" size="small" @change="changeReviewFilter">
                <ElRadioButton value="all">全部</ElRadioButton>
                <ElRadioButton value="valid">有效</ElRadioButton>
                <ElRadioButton value="issues">有问题</ElRadioButton>
              </ElRadioGroup>
              <div><ElButton link type="primary" @click="selectAllValid">全选有效</ElButton><ElButton link @click="clearSelection">清空</ElButton></div>
            </div>
            <div v-if="visibleCandidates.length" class="candidate-list">
              <article v-for="candidate in visibleCandidates" :key="candidate.candidate_id" class="candidate" :class="{ active: candidate.candidate_id === activeCandidateId, invalid: !candidate.case || candidate.issues.length > 0 }" @click="activeCandidateId = candidate.candidate_id">
                <ElCheckbox :model-value="selectedCandidateIds.includes(candidate.candidate_id)" :disabled="!candidate.case || candidate.issues.length > 0" @click.stop @change="(checked: string | number | boolean) => toggleCandidate(candidate.candidate_id, Boolean(checked))" />
                <div>
                  <b>{{ candidate.case?.name ?? '无法解析的候选' }}</b>
                  <span v-if="candidate.case"><ElTag size="small">{{ categoryLabels[candidate.case.category] }}</ElTag><ElTag size="small" type="info">{{ difficultyLabels[candidate.case.difficulty] }}</ElTag>{{ candidate.case.turns.length }} 轮</span>
                  <small v-if="candidate.issues.length">{{ candidate.issues.length }} 项需要修正</small>
                </div>
              </article>
            </div>
            <ElEmpty v-else description="当前筛选下没有候选" :image-size="64" />
          </aside>
          <div class="candidate-detail">
            <CaseEditor v-if="activeCandidate?.case" :item="activeCandidate.case" :editable="true" :saving="loading" :validation-issues="activeCandidate.issues" validation-title="候选用例需要修正" :show-initial-state="false" @save="validateEditedCase" />
            <div v-else class="invalid-detail">该候选无法解析，请返回设置后重新生成。</div>
          </div>
        </div>
      </section>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <ElButton @click="requestClose">关闭</ElButton>
        <div v-if="currentStep === 'settings'" class="footer-primary">
          <span v-if="selectedProfile && !selectedProfile.available" class="footer-hint">请先配置模型 API Key</span>
          <ElButton v-if="result" data-testid="continue-candidate-review" @click="continueReview">继续审核已有候选</ElButton>
          <ElButton type="primary" :disabled="!canGenerate" :loading="loading" data-testid="generate-candidates" @click="generate">{{ result ? '重新生成候选' : '生成候选用例' }}</ElButton>
        </div>
        <div v-else class="footer-primary">
          <ElButton data-testid="back-to-generation-settings" @click="returnToSettings">返回设置</ElButton>
          <ElButton type="primary" :disabled="!selectedCases().length" :loading="accepting" data-testid="accept-candidates" @click="acceptSelected">加入草稿（{{ selectedCases().length }}）</ElButton>
        </div>
      </div>
    </template>
  </ElDialog>
</template>

<style scoped lang="scss">
.generation-layout {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  max-height: 80vh;
  overflow: hidden;
}

.generation-config,
.generation-review {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  overflow: auto;
  padding: 2px;
}

.settings-card {
  border: 1px solid var(--border-color);
  border-radius: calc(var(--radius) + 2px);
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-md);
  background: var(--surface-color, #fff);
}

.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);

  > div {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  b { color: var(--text-primary); }
  small { color: var(--text-secondary); font-size: var(--font-size-small); }
  &.compact { margin-bottom: 4px; }
}

.form-grid,
.count-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--spacing-md);
}

.count-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.target-grid { grid-template-columns: 0.7fr 1.4fr 1fr; }
.generation-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.object-description {
  margin: -4px 0 0;
  color: var(--text-secondary);
  font-size: var(--font-size-small);
}

.hint,
.form-grid small {
  color: var(--text-secondary);
  font-size: var(--font-size-small);
  margin: 4px 0 0;
}

.credential-control {
  display: flex;
  width: 100%;
  gap: var(--spacing-xs);

  .el-input {
    flex: 1;
  }
}

.model-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto;
  gap: var(--spacing-md);
  align-items: center;
}

.model-actions { display: flex; gap: var(--spacing-xs); align-items: center; }
.model-select { width: 240px; }
.credential-status { color: var(--color-warning); font-size: var(--font-size-small); }
.credential-status.ready { color: var(--color-success); }
.credential-panel { grid-column: 1 / -1; border-top: 1px solid var(--border-color); padding-top: var(--spacing-sm); }
.credential-panel small { display: block; margin-top: 6px; color: var(--text-secondary); }

.advanced-settings {
  border: 1px solid var(--border-color);
  border-radius: calc(var(--radius) + 2px);
  padding: 0 var(--spacing-md);
}

.distribution-block + .distribution-block { margin-top: var(--spacing-md); }
.distribution-heading { display: flex; justify-content: space-between; margin-bottom: var(--spacing-xs); color: var(--text-secondary); }
.distribution-heading span.invalid { color: var(--color-error); }

.review-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);

  div {
    display: flex;
    flex-direction: column;
  }

  span {
    color: var(--text-secondary);
    font-size: var(--font-size-small);
  }
}

.review-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-sm);

  > div {
    display: flex;
    align-items: baseline;
    gap: var(--spacing-xs);
    padding: var(--spacing-sm) var(--spacing-md);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    background: var(--surface-color, #fff);
  }

  b { font-size: var(--font-size-h3); }
  span { color: var(--text-secondary); font-size: var(--font-size-small); }
  .success b { color: var(--color-success); }
  .danger b { color: var(--color-error); }
  .selected b { color: var(--color-primary); }
}

.review-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: var(--spacing-md);
  align-items: start;
}

.candidate-sidebar {
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  overflow: hidden;
}

.candidate-toolbar {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm);
  border-bottom: 1px solid var(--border-color);

  > div { display: flex; justify-content: flex-end; }
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  max-height: 62vh;
  overflow: auto;
  padding: var(--spacing-xs);
}

.candidate {
  display: flex;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  cursor: pointer;

  &.active {
    border-color: var(--color-primary);
    background: var(--color-primary-lighter);
  }

  &.invalid { background: var(--color-error-lighter, #fff5f5); }

  > div {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  b {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--text-secondary);
    font-size: var(--font-size-small);
  }

  small {
    color: var(--color-error);
  }
}

.candidate-detail :deep(.case-editor-panel) {
  max-height: 62vh;
  overflow: auto;
  box-shadow: none;
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
}

.invalid-detail {
  padding: var(--spacing-xl);
  color: var(--text-secondary);
  text-align: center;
}

.dialog-footer { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.footer-primary { display: flex; align-items: center; gap: var(--spacing-sm); }
.footer-hint { color: var(--color-warning); font-size: var(--font-size-small); }

@include respond-to(lg) {
  .review-body {
    grid-template-columns: 1fr;
  }

  .target-grid,
  .generation-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

  .candidate-list { max-height: 260px; }
}

@include respond-to(sm) {
  .form-grid,
  .target-grid,
  .generation-grid,
  .count-grid,
  .review-summary { grid-template-columns: 1fr; }
  .model-row { grid-template-columns: 1fr; }
  .model-actions { align-items: stretch; flex-direction: column; }
  .model-select { width: 100%; }
  .dialog-footer { align-items: stretch; gap: var(--spacing-sm); }
  .footer-primary { justify-content: flex-end; }
}
</style>
