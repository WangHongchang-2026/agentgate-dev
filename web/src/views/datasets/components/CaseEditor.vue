<script setup lang="ts">
// 用例编辑器（迁移自 web/src/components/dataset/CaseEditor.vue）
// §6.1：EP 编辑器用 :model-value + @update:modelValue，禁止 v-model
import { ref, watch } from 'vue'
import {
  ElMessage,
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  ElSelect,
  ElOption,
  ElCollapse,
  ElCollapseItem,
  ElTag,
  ElEmpty,
  ElAlert,
} from 'element-plus'
import type { EvaluationCase, ValidationIssue } from '@/types/dataset'
import ExpectationEditor from './ExpectationEditor.vue'

/* eslint-disable @typescript-eslint/no-explicit-any */
const props = defineProps<{
  item: EvaluationCase | null
  editable: boolean
  saving?: boolean
  validationIssues?: ValidationIssue[]
  validationTitle?: string
  showInitialState?: boolean
}>()
const emit = defineEmits<{ save: [item: EvaluationCase] }>()

const form = ref<any | null>(null)
const inputs = ref<string[]>([])
const initialState = ref('{}')
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

watch(
  () => props.item,
  (item) => {
    form.value = item ? cloneJson(item) : null
    inputs.value = item?.turns.map((turn) => JSON.stringify(turn.input, null, 2)) ?? []
    initialState.value = JSON.stringify(item?.initial_state ?? {}, null, 2)
  },
  { immediate: true, deep: true },
)

function addTurn() {
  form.value.turns.push({
    id: crypto.randomUUID(),
    input: {},
    expected_skill: null,
    expectations: [],
    required_tools: [],
    forbidden_tools: [],
    policy_rules: [],
    notes: '',
  })
  inputs.value.push('{}')
}

function removeTurn(index: number) {
  if (form.value.turns.length === 1) return ElMessage.warning('用例至少需要一轮输入')
  form.value.turns.splice(index, 1)
  inputs.value.splice(index, 1)
}

function save() {
  if (!form.value?.name.trim()) return ElMessage.warning('请输入用例名称')
  try {
    form.value.initial_state = JSON.parse(initialState.value || '{}')
    form.value.turns.forEach((turn: any, index: number) => {
      turn.input = JSON.parse(inputs.value[index] || '{}')
    })
  } catch {
    return ElMessage.error('输入和初始状态必须是有效 JSON')
  }
  emit('save', cloneJson(form.value))
}
/* eslint-enable @typescript-eslint/no-explicit-any */
</script>

<template>
  <section class="dataset-column case-editor-panel">
    <div class="dataset-panel-heading">
      <div><span class="step">CASE EDITOR</span><h2>用例编辑</h2></div>
      <ElButton v-if="item && editable" type="primary" size="small" :loading="saving" data-testid="save-case" @click="save">保存用例</ElButton>
    </div>
    <ElEmpty v-if="!form" description="选择或新建一个用例" />
    <ElForm v-else label-position="top" class="case-editor-form" :disabled="!editable">
      <ElAlert
        v-if="validationIssues?.length"
        :title="validationTitle ?? '此用例包含发布问题'"
        type="error"
        :closable="false"
        class="case-validation"
      >
        <ul><li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`">{{ issue.message }}</li></ul>
      </ElAlert>
      <ElAlert
        v-if="form.provenance"
        type="info"
        :closable="false"
        class="case-provenance"
        data-testid="case-provenance"
      >
        <template #title>回归来源 · Run {{ form.provenance.source_run_id }}</template>
        <p>Dataset {{ form.provenance.source_dataset_id }} v{{ form.provenance.source_dataset_version }} · Case {{ form.provenance.source_case_id }}</p>
        <p v-if="form.provenance.reason">加入原因：{{ form.provenance.reason }}</p>
      </ElAlert>
      <ElAlert
        v-if="form.generation_provenance"
        type="info"
        :closable="false"
        class="case-provenance"
      >
        <template #title>AI 生成 · {{ form.generation_provenance.requested_model }}</template>
        <p>
          {{ form.generation_provenance.target_ref.external_target_id }}@
          {{ form.generation_provenance.target_ref.external_version_id }} ·
          {{ form.generation_provenance.recipe_version }}
        </p>
      </ElAlert>
      <div class="case-meta-grid">
        <ElFormItem label="用例名称">
          <ElInput :model-value="form.name" data-testid="case-name" @update:model-value="(v: any) => (form.name = v)" />
        </ElFormItem>
        <ElFormItem label="分类">
          <ElSelect :model-value="form.category" @update:model-value="(v: any) => (form.category = v)">
            <ElOption label="正例" value="positive" />
            <ElOption label="负例" value="negative" />
            <ElOption label="边界" value="boundary" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="难度">
          <ElSelect :model-value="form.difficulty" @update:model-value="(v: any) => (form.difficulty = v)">
            <ElOption label="简单" value="easy" />
            <ElOption label="中等" value="medium" />
            <ElOption label="困难" value="hard" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="标签">
          <ElSelect
            :model-value="form.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入后回车"
            @update:model-value="(v: any) => (form.tags = v)"
          />
        </ElFormItem>
      </div>
      <ElFormItem label="备注">
        <ElInput :model-value="form.notes" type="textarea" :rows="2" @update:model-value="(v: any) => (form.notes = v)" />
      </ElFormItem>
      <ElFormItem v-if="showInitialState !== false" label="初始状态（JSON）">
        <ElInput :model-value="initialState" type="textarea" :rows="3" class="json-editor" @update:model-value="(v: any) => (initialState = v)" />
      </ElFormItem>

      <div class="subsection-heading turn-heading">
        <div><b>对话轮次</b><small>单轮用例保留一轮；多轮会共享会话状态。</small></div>
        <ElButton v-if="editable" size="small" data-testid="add-turn" @click="addTurn">添加轮次</ElButton>
      </div>
      <ElCollapse :model-value="form.turns.map((turn: any) => turn.id)">
        <ElCollapseItem v-for="(turn, index) in form.turns" :key="turn.id" :name="turn.id">
          <template #title>
            <b>第 {{ Number(index) + 1 }} 轮</b>
            <span class="turn-summary">{{ turn.expected_skill || '未设置期望 Skill' }}</span>
          </template>
          <div class="turn-form">
            <div class="turn-actions">
              <ElTag size="small" effect="plain">{{ turn.id }}</ElTag>
              <ElButton v-if="editable" link type="danger" @click.stop="removeTurn(Number(index))">删除此轮</ElButton>
            </div>
            <ElFormItem label="输入（JSON）">
              <ElInput :model-value="inputs[Number(index)]" type="textarea" :rows="5" class="json-editor" :data-testid="`turn-input-${index}`" @update:model-value="(v: any) => (inputs[Number(index)] = v)" />
            </ElFormItem>
            <ElFormItem label="期望 Skill">
              <ElInput :model-value="turn.expected_skill" :data-testid="`expected-skill-${index}`" placeholder="例如 loan_approval；可留空" @update:model-value="(v: any) => (turn.expected_skill = v)" />
            </ElFormItem>
            <div class="case-meta-grid">
              <ElFormItem label="必须调用工具">
                <ElSelect :model-value="turn.required_tools" multiple filterable allow-create default-first-option :data-testid="`required-tools-${index}`" placeholder="输入工具名" @update:model-value="(v: any) => (turn.required_tools = v)" />
              </ElFormItem>
              <ElFormItem label="禁止调用工具">
                <ElSelect :model-value="turn.forbidden_tools" multiple filterable allow-create default-first-option :data-testid="`forbidden-tools-${index}`" placeholder="输入工具名" @update:model-value="(v: any) => (turn.forbidden_tools = v)" />
              </ElFormItem>
              <ElFormItem label="策略规则">
                <ElSelect :model-value="turn.policy_rules" multiple filterable allow-create default-first-option :data-testid="`policy-rules-${index}`" placeholder="输入规则 ID" @update:model-value="(v: any) => (turn.policy_rules = v)" />
              </ElFormItem>
            </div>
            <ElFormItem label="本轮备注">
              <ElInput :model-value="turn.notes" @update:model-value="(v: any) => (turn.notes = v)" />
            </ElFormItem>
            <ExpectationEditor :model-value="turn.expectations" :disabled="!editable" @update:model-value="(v: any) => (turn.expectations = v)" />
          </div>
        </ElCollapseItem>
      </ElCollapse>
      <div v-if="editable" class="editor-save-footer">
        <ElButton type="primary" :loading="saving" data-testid="save-case-bottom" @click="save">保存用例</ElButton>
      </div>
    </ElForm>
  </section>
</template>

<style scoped lang="scss">
.case-editor-panel {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-lg) !important;
  min-height: 480px;
}

.dataset-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);

  h2 {
    font-size: var(--font-size-h4);
    font-weight: var(--font-weight-semibold);
    color: var(--text-primary);
    margin: 0;
  }

  .step {
    display: block;
    font-family: var(--font-family-mono);
    font-size: 10px;
    color: var(--color-primary);
    letter-spacing: 1px;
  }
}

.case-editor-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.case-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--spacing-md);
}

.subsection-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);

  b {
    color: var(--text-primary);
    font-size: var(--font-size-body);
  }

  small {
    color: var(--text-secondary);
    font-size: var(--font-size-small);
    margin-left: var(--spacing-xs);
  }
}

.turn-summary {
  margin-left: var(--spacing-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-small);
}

.turn-form {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding-top: var(--spacing-sm);
}

.turn-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.json-editor {
  :deep(textarea) {
    font-family: var(--font-family-mono);
    font-size: var(--font-size-small);
  }
}

.editor-save-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--spacing-sm);
}
</style>
