export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export interface JsonObject { [key: string]: JsonValue }

export type CaseCategory = 'positive' | 'negative' | 'boundary'
export type CaseDifficulty = 'easy' | 'medium' | 'hard'
export type DatasetVersionStatus = 'draft' | 'published'

export type Condition =
  | { kind: 'equals'; expected: JsonValue }
  | { kind: 'within_tolerance'; expected: number; epsilon: number }
  | { kind: 'within_range'; minimum: number | null; maximum: number | null }
  | { kind: 'matches_pattern'; pattern: string }
  | { kind: 'one_of'; allowed: JsonValue[] }
  | { kind: 'must_be_missing' }
  | { kind: 'matches_json_schema'; json_schema: JsonObject }

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
}

export interface DatasetRecord {
  id: string
  name: string
  description: string
  archived: boolean
  created_at: string
  updated_at: string
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
