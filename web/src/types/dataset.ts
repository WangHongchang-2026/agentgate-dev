// Dataset 域类型（对齐后端 Pydantic，迁移自 web/src/types/dataset.ts）
export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export interface JsonObject {
  [key: string]: JsonValue
}

export type CaseCategory = 'positive' | 'negative' | 'boundary'
export type CaseDifficulty = 'easy' | 'medium' | 'hard'
export type DatasetVersionStatus = 'draft' | 'published'
export type DatasetPurpose = 'standard' | 'regression'

export interface CaseProvenance {
  source_type: 'run_result'
  source_run_id: string
  source_dataset_id: string
  source_dataset_version: number
  source_case_id: string
  captured_at: string
  reason: string
}

export interface TargetRef {
  platform_id: string
  target_type: 'agent' | 'skill'
  external_target_id: string
  external_version_id: string
}

export interface GeneratedCaseProvenance {
  source_type: 'llm_generation'
  target_ref: TargetRef
  target_descriptor_sha256: string
  recipe_version: string
  model_profile_id: string
  provider: string
  requested_model: string
  generated_at: string
}

export type Condition =
  | { kind: 'equals'; expected: JsonValue }
  | { kind: 'within_tolerance'; expected: number; epsilon: number }
  | { kind: 'within_range'; minimum: number | null; maximum: number | null }
  | { kind: 'matches_pattern'; pattern: string }
  | { kind: 'one_of'; allowed: JsonValue[] }
  | { kind: 'must_be_missing' }
  | {
      kind: 'matches_json_schema'
      json_schema: JsonObject
      instance_mode?: 'structured' | 'json_text'
    }

interface ExpectationBase {
  id: string
  name: string | null
  condition: Condition
}

export type Expectation =
  | (ExpectationBase & { kind: 'state'; path: string })
  | (ExpectationBase & {
      kind: 'tool_argument'
      tool: string
      path: string
      occurrence: 'first' | 'last' | 'any' | 'all'
    })
  | (ExpectationBase & { kind: 'output'; path: string | null })

export interface CaseTurn {
  id: string
  input: JsonObject
  expected_skill: string | null
  expectations: Expectation[]
  required_tools: string[]
  forbidden_tools: string[]
  policy_rules: string[]
  notes: string
}

export interface EvaluationCase {
  id: string
  name: string
  turns: CaseTurn[]
  initial_state: JsonObject
  category: CaseCategory
  difficulty: CaseDifficulty
  tags: string[]
  notes: string
  provenance: CaseProvenance | null
  generation_provenance: GeneratedCaseProvenance | null
}

export interface DatasetRecord {
  id: string
  name: string
  description: string
  archived: boolean
  created_at: string
  updated_at: string
  purpose: DatasetPurpose
}

export interface DatasetSummary extends DatasetRecord {
  version: number | null
  case_count: number
  has_draft: boolean
}

export interface DatasetVersion {
  id: string
  dataset_id: string
  dataset_name: string
  dataset_description: string
  version: number | null
  status: DatasetVersionStatus
  based_on_version: number | null
  cases: EvaluationCase[]
  notes: string
  created_at: string
  updated_at: string
  published_at: string | null
  content_sha256: string
}

export interface DatasetDetail {
  dataset: DatasetRecord
  versions: DatasetVersion[]
}

export interface DatasetMutation {
  dataset: DatasetRecord
  draft: DatasetVersion
}

export interface DatasetExport {
  format: 'agentgate.dataset'
  format_version: '1'
  dataset: DatasetRecord
  version: DatasetVersion
}

export interface ValidationIssue {
  path: string
  message: string
}

export interface SchemaIssue {
  code: string
  message: string
  limit?: number | null
  actual?: number | null
  ref?: string | null
  declared?: string | null
}

export type SchemaValidationResult = { valid: true } | { valid: false; errors: SchemaIssue[] }

export interface ExcelImportIssue {
  sheet: string
  row: number | null
  column: string | null
  message: string
}

export interface ExcelImportErrorDetail {
  code: string
  total_count: number
  truncated: boolean
  issues: ExcelImportIssue[]
}

export interface AddRegressionCaseRequest {
  regression_dataset_id?: string
  new_dataset_name?: string
  new_dataset_description?: string
  reason?: string
}

export interface AddRegressionCaseResponse {
  dataset: DatasetRecord
  draft: DatasetVersion
  case: EvaluationCase
}
