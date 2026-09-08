import { request } from './client'
import type {
  EvaluationRun,
  RunActivity,
  RunProgress,
  RunStatus,
} from '../types/run'

export interface LaunchEvaluationRequest {
  version: string
  datasetId: string
  datasetVersion: number
  evaluatorIds: string[]
  caseIds?: string[]
}

export const runsApi = {
  launch: (input: LaunchEvaluationRequest) => request<RunProgress>('/api/evaluations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version: input.version,
      dataset_id: input.datasetId,
      dataset_version: input.datasetVersion,
      evaluator_ids: input.evaluatorIds,
      case_ids: input.caseIds,
    }),
  }),
  list: (status?: RunStatus, limit = 50) => {
    const query = new URLSearchParams({ limit: String(limit) })
    if (status) query.set('status', status)
    return request<EvaluationRun[]>(`/api/runs?${query}`)
  },
  activity: (recentLimit = 20) =>
    request<RunActivity>(`/api/runs/activity?recent_limit=${recentLimit}`),
  status: (runId: string) =>
    request<RunProgress>(`/api/runs/${runId}/status`),
}
