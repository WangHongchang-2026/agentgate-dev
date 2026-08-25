import { request } from './client'
import type {
  DatasetDetail, DatasetExport, DatasetMutation, DatasetRecord, DatasetSummary,
  DatasetVersion, EvaluationCase,
} from '../types/dataset'

const headers = { 'Content-Type': 'application/json' }
const id = encodeURIComponent

export const datasetApi = {
  list: () => request<DatasetSummary[]>('/api/datasets'),
  create: (name: string, description = '') =>
    request<DatasetMutation>('/api/datasets', {
      method: 'POST', headers, body: JSON.stringify({ name, description }),
    }),
  detail: (datasetId: string) =>
    request<DatasetDetail>(`/api/datasets/${id(datasetId)}`),
  update: (
    datasetId: string,
    changes: Partial<Pick<DatasetRecord, 'name'|'description'|'archived'>>,
  ) => request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, {
    method: 'PATCH', headers, body: JSON.stringify(changes),
  }),
  archive: (datasetId: string) =>
    request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, { method: 'DELETE' }),
  copy: (datasetId: string, name: string, sourceVersion?: number|null) =>
    request<DatasetMutation>(`/api/datasets/${id(datasetId)}/copy`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ name, source_version: sourceVersion ?? null }),
    }),
  versions: (datasetId: string) =>
    request<DatasetVersion[]>(`/api/datasets/${id(datasetId)}/versions`),
  version: (datasetId: string, version: number) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/versions/${version}`),
  currentDraft: (datasetId: string) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/current`),
  createDraft: (datasetId: string, basedOnVersion?: number|null) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/drafts`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ based_on_version: basedOnVersion ?? null }),
    }),
  discardDraft: (datasetId: string) =>
    request<void>(`/api/datasets/${id(datasetId)}/drafts/current`, {
      method: 'DELETE',
    }),
  publish: (datasetId: string) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/publish`, {
      method: 'POST',
    }),
  addCase: (datasetId: string, item: EvaluationCase) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases`, {
      method: 'POST', headers, body: JSON.stringify(item),
    }),
  updateCase: (datasetId: string, item: EvaluationCase) =>
    request<DatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(item.id)}`,
      { method: 'PUT', headers, body: JSON.stringify(item) },
    ),
  removeCase: (datasetId: string, caseId: string) =>
    request<DatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}`,
      { method: 'DELETE' },
    ),
  copyCase: (datasetId: string, caseId: string) =>
    request<DatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}/copy`,
      { method: 'POST' },
    ),
  reorderCases: (datasetId: string, caseIds: string[]) =>
    request<DatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/case-order`, {
      method: 'PUT', headers, body: JSON.stringify({ case_ids: caseIds }),
    }),
  exportVersion: (datasetId: string, version: number) =>
    request<DatasetExport>(
      `/api/datasets/${id(datasetId)}/versions/${version}/export`
    ),
  importDataset: (payload: DatasetExport) =>
    request<{ dataset: DatasetRecord; version: DatasetVersion }>('/api/datasets/import', {
      method: 'POST', headers, body: JSON.stringify(payload),
    }),
}
