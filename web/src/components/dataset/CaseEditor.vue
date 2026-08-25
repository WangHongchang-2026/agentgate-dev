<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { EvaluationCase, ValidationIssue } from '../../types/dataset'
import ExpectationEditor from './ExpectationEditor.vue'

const props = defineProps<{
  item: EvaluationCase|null
  editable: boolean
  saving?: boolean
  validationIssues?: ValidationIssue[]
}>()
const emit = defineEmits<{ save: [item: EvaluationCase] }>()
const form = ref<any|null>(null)
const inputs = ref<string[]>([])
const initialState = ref('{}')
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

watch(
  () => props.item,
  item => {
    form.value = item ? cloneJson(item) : null
    inputs.value = item?.turns.map(turn => JSON.stringify(turn.input, null, 2)) ?? []
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
</script>

<template>
  <section class="dataset-column case-editor-panel">
    <div class="dataset-panel-heading">
      <div><span class="step">CASE EDITOR</span><h2>用例编辑</h2></div>
      <el-button v-if="item && editable" type="primary" size="small" :loading="saving" data-testid="save-case" @click="save">保存用例</el-button>
    </div>
    <el-empty v-if="!form" description="选择或新建一个用例" />
    <el-form v-else label-position="top" class="case-editor-form" :disabled="!editable">
      <el-alert
        v-if="validationIssues?.length"
        title="此用例包含发布问题"
        type="error"
        :closable="false"
        class="case-validation"
      >
        <ul><li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`">{{ issue.message }}</li></ul>
      </el-alert>
      <div class="case-meta-grid">
        <el-form-item label="用例名称">
          <el-input v-model="form.name" data-testid="case-name" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category">
            <el-option label="正例" value="positive" />
            <el-option label="负例" value="negative" />
            <el-option label="边界" value="boundary" />
          </el-select>
        </el-form-item>
        <el-form-item label="难度">
          <el-select v-model="form.difficulty">
            <el-option label="简单" value="easy" />
            <el-option label="中等" value="medium" />
            <el-option label="困难" value="hard" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple filterable allow-create default-first-option placeholder="输入后回车" />
        </el-form-item>
      </div>
      <el-form-item label="备注">
        <el-input v-model="form.notes" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="初始状态（JSON）">
        <el-input v-model="initialState" type="textarea" :rows="3" class="json-editor" />
      </el-form-item>

      <div class="subsection-heading turn-heading">
        <div><b>对话轮次</b><small>单轮用例保留一轮；多轮会共享会话状态。</small></div>
        <el-button v-if="editable" size="small" data-testid="add-turn" @click="addTurn">添加轮次</el-button>
      </div>
      <el-collapse :model-value="form.turns.map((turn: any) => turn.id)">
        <el-collapse-item v-for="(turn, index) in form.turns" :key="turn.id" :name="turn.id">
          <template #title>
            <b>第 {{ Number(index) + 1 }} 轮</b>
            <span class="turn-summary">{{ turn.expected_skill || '未设置期望 Skill' }}</span>
          </template>
          <div class="turn-form">
            <div class="turn-actions">
              <el-tag size="small" effect="plain">{{ turn.id }}</el-tag>
              <el-button v-if="editable" link type="danger" @click.stop="removeTurn(Number(index))">删除此轮</el-button>
            </div>
            <el-form-item label="输入（JSON）">
              <el-input v-model="inputs[Number(index)]" type="textarea" :rows="5" class="json-editor" :data-testid="`turn-input-${index}`" />
            </el-form-item>
            <el-form-item label="期望 Skill">
              <el-input v-model="turn.expected_skill" :data-testid="`expected-skill-${index}`" placeholder="例如 loan_approval；可留空" />
            </el-form-item>
            <div class="case-meta-grid">
              <el-form-item label="必须调用工具">
                <el-select v-model="turn.required_tools" multiple filterable allow-create default-first-option :data-testid="`required-tools-${index}`" placeholder="输入工具名" />
              </el-form-item>
              <el-form-item label="禁止调用工具">
                <el-select v-model="turn.forbidden_tools" multiple filterable allow-create default-first-option :data-testid="`forbidden-tools-${index}`" placeholder="输入工具名" />
              </el-form-item>
              <el-form-item label="策略规则">
                <el-select v-model="turn.policy_rules" multiple filterable allow-create default-first-option :data-testid="`policy-rules-${index}`" placeholder="输入规则 ID" />
              </el-form-item>
            </div>
            <el-form-item label="本轮备注">
              <el-input v-model="turn.notes" />
            </el-form-item>
            <ExpectationEditor v-model="turn.expectations" :disabled="!editable" />
          </div>
        </el-collapse-item>
      </el-collapse>
      <div v-if="editable" class="editor-save-footer">
        <el-button type="primary" :loading="saving" data-testid="save-case-bottom" @click="save">保存用例</el-button>
      </div>
    </el-form>
  </section>
</template>
