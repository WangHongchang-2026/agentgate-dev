import type {
  DatasetSummary, DatasetVersion, EvaluationCase
} from '../types/dataset'

export interface Version { id: string; label: string }
export type DatasetOption = DatasetSummary
export interface EvaluatorOption {
  id: string
  name: string
  kind: 'rule'|'llm_judge'|'hybrid'
  version: string
  dimension: string
  metric: string
  severity: 'standard'|'blocking'
  implementation_id: string
  implementation_version: string
  config: Record<string, unknown>
}
export interface Run {
  id: string
  status: string
  manifest: {
    target: { ref: { external_version_id: string } }
    dataset: DatasetVersion
    evaluator_specs: EvaluatorOption[]
  }
}
export type Outcome = 'pass'|'fail'|'review'|'not_applicable'|'error'
export interface CheckResult {
  id: string
  name: string
  turn_id: string|null
  expectation_id: string|null
  outcome: Outcome
  score: number|null
  reason: string
  expected: unknown
  actual: unknown
  actual_missing: boolean
  span_ids: string[]
  failure_stage: string|null
  failure_sequence: number|null
  failure_span_id: string|null
}
export interface EvaluationResult {
  trace_id: string
  case_id: string
  evaluator_id: string
  evaluator_name: string
  evaluator_kind: string
  dimension: string
  metric: string
  severity: 'standard'|'blocking'
  outcome: Outcome
  score: number|null
  reason: string
  primary_failure_stage?: string
  checks: CheckResult[]
}
export type ReleaseGateReason = 'threshold_met'|'score_below_threshold'|'missing_results'|'evaluator_error'|'blocking_failure'|'review_required'|'no_applicable_results'
export interface ReleaseGate {
  outcome: 'pass'|'fail'
  missing_results: [string, string][]
  score: number|null
  minimum_score: number
  reason_code: ReleaseGateReason
}
export interface Metric {
  key: string
  level: 'overall'|'kind'|'dimension'|'metric'
  score: number|null
  passed: number
  failed: number
  reviewed: number
  not_applicable: number
  errors: number
  applicable: number
  total: number
}
export interface Report { run: Run; results: EvaluationResult[]; release_gate: ReleaseGate; metrics: Metric[] }
export interface TraceOutcome {
  input: Record<string, unknown>
  output: Record<string, unknown>
  state: Record<string, unknown>
}
export interface Trace {
  trace_id: string
  case_id: string
  spans: {
    span_id: string
    name: string
    operation_type: string
    sequence: number
    attributes: Record<string, unknown>
  }[]
  turn_outcomes: Record<string, TraceOutcome>
  final_state: Record<string, unknown>
  final_output: Record<string, unknown>
}
export interface Overview {
  total_runs: number
  completed_runs: number
  case_count: number
  latest: Report|null
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(
      Array.isArray(detail)
        ? detail.map(item => item?.message ?? JSON.stringify(item)).join('；')
        : String(detail ?? `HTTP ${status}`)
    )
    this.status = status
    this.detail = detail
  }
}

export const request = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
    throw new ApiError(response.status, payload.detail)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const api = {
  overview: () => request<Overview>('/api/overview'),
  versions: () => request<Version[]>('/api/versions'),
  datasets: () => request<DatasetSummary[]>('/api/datasets'),
  evaluators: () => request<EvaluatorOption[]>('/api/evaluators'),
  runs: () => request<Run[]>('/api/runs'),
  launch: (
    version: string,
    datasetId: string,
    datasetVersion: number,
    evaluatorIds: string[],
  ) => request<Run>('/api/evaluations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version,
      dataset_id: datasetId,
      dataset_version: datasetVersion,
      evaluator_ids: evaluatorIds,
    }),
  }),
  report: (id: string) => request<Report>(`/api/runs/${id}`),
  trace: (runId: string, caseId: string) =>
    request<Trace>(`/api/runs/${runId}/traces/${caseId}`),
}

export type { DatasetSummary, DatasetVersion, EvaluationCase }
