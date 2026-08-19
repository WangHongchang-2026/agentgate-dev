import type {
  DatasetSummary, DatasetVersion, EvaluationCase, JsonObject,
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
  evaluator_type: string
  operator: string|null
}
export interface Run {
  id: string
  status: string
  snapshot: {
    target: { version: string }
    dataset: DatasetVersion
    evaluator_specs: EvaluatorOption[]
  }
}
export interface Evidence { trace_id: string; span_ids: string[]; description: string }
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
  evidence: Evidence[]
}
export interface Result {
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
  primary_failure_step?: string
  evidence: Evidence[]
  checks: CheckResult[]
}
export interface Gate {
  outcome: 'pass'|'fail'
  passed: number
  failed: number
  reviewed: number
  not_applicable: number
  errors: number
  score: number|null
  threshold: number
  reason: string
}
export interface Metric {
  key: string
  label: string
  level: 'overall'|'kind'|'dimension'|'metric'
  score: number|null
  passed: number
  failed: number
  reviewed: number
  not_applicable: number
  errors: number
  applicable: number
  total: number
  incomplete: boolean
}
export interface Report { run: Run; results: Result[]; gate: Gate; metrics: Metric[] }
export interface TraceTurn {
  turn_id: string
  input: JsonObject
  output: JsonObject
  state: JsonObject
}
export interface Trace {
  case_id: string
  spans: {
    id: string
    name: string
    kind: string
    sequence: number
    attributes: Record<string, unknown>
  }[]
  turns: TraceTurn[]
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

const requestResponse = async (url: string, init?: RequestInit): Promise<Response> => {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
    throw new ApiError(response.status, payload.detail)
  }
  return response
}

export const request = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await requestResponse(url, init)
  if (response.status === 204) return undefined as T
  return response.json()
}

export const requestBlob = async (url: string, init?: RequestInit): Promise<Blob> =>
  (await requestResponse(url, init)).blob()

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
