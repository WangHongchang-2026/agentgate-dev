import type { EvaluationCase, TargetRef, ValidationIssue } from './dataset'

export type TargetType = 'agent' | 'skill'
export type TurnMode = 'single' | 'multi' | 'mixed'

export interface TargetCatalogItem {
  platform_id: string
  target_type: TargetType
  external_target_id: string
  display_name: string
  description: string
}

export interface TargetVersionItem {
  ref: TargetRef
  display_name: string
  description: string
  descriptor_sha256: string
  reproducibility_limited: boolean
}

export interface GenerationModelProfile {
  id: string
  display_name: string
  provider: string
  model: string
  available: boolean
}

export interface ModelCredentialStatus {
  profile_id: string
  available: boolean
  storage: 'process_memory' | 'environment' | 'none'
  validation_request_id?: string | null
}

export interface GenerationCounts {
  positive: number
  negative: number
  boundary: number
}

export interface DifficultyCounts {
  easy: number
  medium: number
  hard: number
}

export interface GenerateCandidatesRequest {
  draft_id: string
  draft_content_sha256: string
  target_ref: TargetRef
  count: number
  reference_source: { dataset_id: string; version: number } | null
  reference_case_ids: string[]
  turn_mode: TurnMode
  turn_counts: { single: number; multi: number } | null
  max_turns_per_case: number
  category_counts: GenerationCounts
  difficulty_counts: DifficultyCounts
  instructions: string
  model_profile_id: string
}

export interface CandidateIssue extends ValidationIssue {
  code: string
}

export interface GeneratedCandidate {
  candidate_id: string
  slot_index: number | null
  review_status: 'pending'
  case: EvaluationCase | null
  issues: CandidateIssue[]
}

export interface GenerationResult {
  requested_count: number
  generated_count: number
  valid_count: number
  invalid_count: number
  candidates: GeneratedCandidate[]
  batch_issues: CandidateIssue[]
  target_ref: TargetRef
  target_descriptor_sha256: string
  recipe_version: string
  provider: string
  model_profile_id: string
  requested_model: string
  response_model: string | null
  provider_request_id: string | null
  acceptance_token: string
  redacted_count: number
  draft_id: string
  draft_content_sha256: string
}

export interface AcceptGeneratedCasesRequest {
  draft_id: string
  draft_content_sha256: string
  target_ref: TargetRef
  target_descriptor_sha256: string
  recipe_version: string
  acceptance_token: string
  candidates: Array<{ slot_index: number; case: EvaluationCase }>
}

export interface DatasetMutationReceipt {
  draft_id: string
  content_sha256: string
  inserted_case_ids: string[]
}
