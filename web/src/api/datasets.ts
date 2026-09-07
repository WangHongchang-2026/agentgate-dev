import { request } from './client'
import type {
  CaseTurn, Condition,
  DatasetDetail, DatasetExport, DatasetMutation, DatasetRecord, DatasetSummary,
  DatasetVersion, EvaluationCase, Expectation,
} from '../types/dataset'

const headers = { 'Content-Type': 'application/json' }
const id = encodeURIComponent

interface ApiExpectationBase {
  id: string
  name: string | null
}

type ApiExpectation = Expectation
  | (ApiExpectationBase & { kind: 'skill_route'; condition: Condition })
  | (ApiExpectationBase & {
      kind: 'tool_call'
      tool: string
      mode: 'required' | 'forbidden'
    })
  | (ApiExpectationBase & { kind: 'policy'; policy_id: string })

type ApiCaseTurn = Omit<CaseTurn,
  'expected_skill' | 'expectations' | 'required_tools' | 'forbidden_tools' | 'policy_rules'
> & { expectations: ApiExpectation[] }
type ApiEvaluationCase = Omit<EvaluationCase, 'turns'> & { turns: ApiCaseTurn[] }
type ApiDatasetVersion = Omit<DatasetVersion, 'cases'> & { cases: ApiEvaluationCase[] }
type ApiDatasetDetail = Omit<DatasetDetail, 'versions'> & { versions: ApiDatasetVersion[] }
type ApiDatasetMutation = Omit<DatasetMutation, 'draft'> & { draft: ApiDatasetVersion }

const editableExpectationKinds = new Set(['state', 'tool_argument', 'output'])

function toEditorCase(item: ApiEvaluationCase): EvaluationCase {
  return {
    ...item,
    turns: item.turns.map(turn => {
      const skill = turn.expectations.find(item => item.kind === 'skill_route')
      return {
        ...turn,
        expected_skill: skill?.kind === 'skill_route'
          && skill.condition.kind === 'equals'
          && typeof skill.condition.expected === 'string'
          ? skill.condition.expected
          : null,
        expectations: turn.expectations.filter(
          (item): item is Expectation => editableExpectationKinds.has(item.kind),
        ),
        required_tools: turn.expectations
          .filter(item => item.kind === 'tool_call' && item.mode === 'required')
          .map(item => item.kind === 'tool_call' ? item.tool : ''),
        forbidden_tools: turn.expectations
          .filter(item => item.kind === 'tool_call' && item.mode === 'forbidden')
          .map(item => item.kind === 'tool_call' ? item.tool : ''),
        policy_rules: turn.expectations
          .filter(item => item.kind === 'policy')
          .map(item => item.kind === 'policy' ? item.policy_id : ''),
      }
    }),
  }
}

function toEditorVersion(version: ApiDatasetVersion): DatasetVersion {
  return { ...version, cases: version.cases.map(toEditorCase) }
}

function toApiCase(item: EvaluationCase): ApiEvaluationCase {
  return {
    ...item,
    turns: item.turns.map(({
      expected_skill, required_tools, forbidden_tools, policy_rules, ...turn
    }) => ({
      ...turn,
      expectations: [
        ...(expected_skill ? [{
          id: crypto.randomUUID(), kind: 'skill_route' as const, name: null,
          condition: { kind: 'equals' as const, expected: expected_skill },
        }] : []),
        ...required_tools.map(tool => ({
          id: crypto.randomUUID(), kind: 'tool_call' as const, name: null,
          tool, mode: 'required' as const,
        })),
        ...forbidden_tools.map(tool => ({
          id: crypto.randomUUID(), kind: 'tool_call' as const, name: null,
          tool, mode: 'forbidden' as const,
        })),
        ...policy_rules.map(policy_id => ({
          id: crypto.randomUUID(), kind: 'policy' as const, name: null, policy_id,
        })),
        ...turn.expectations,
      ],
    })),
  }
}

export const datasetApi = {
  list: () => request<DatasetSummary[]>('/api/datasets'),
  create: (name: string, description = '') =>
    request<ApiDatasetMutation>('/api/datasets', {
      method: 'POST', headers, body: JSON.stringify({ name, description }),
    }).then(result => ({ ...result, draft: toEditorVersion(result.draft) })),
  detail: (datasetId: string) =>
    request<ApiDatasetDetail>(`/api/datasets/${id(datasetId)}`).then(result => ({
      ...result, versions: result.versions.map(toEditorVersion),
    })),
  update: (
    datasetId: string,
    changes: Partial<Pick<DatasetRecord, 'name'|'description'|'archived'>>,
  ) => request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, {
    method: 'PATCH', headers, body: JSON.stringify(changes),
  }),
  archive: (datasetId: string) =>
    request<DatasetRecord>(`/api/datasets/${id(datasetId)}`, { method: 'DELETE' }),
  copy: (datasetId: string, name: string, sourceVersion?: number|null) =>
    request<ApiDatasetMutation>(`/api/datasets/${id(datasetId)}/copy`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ name, source_version: sourceVersion ?? null }),
    }).then(result => ({ ...result, draft: toEditorVersion(result.draft) })),
  versions: (datasetId: string) =>
    request<ApiDatasetVersion[]>(`/api/datasets/${id(datasetId)}/versions`)
      .then(versions => versions.map(toEditorVersion)),
  version: (datasetId: string, version: number) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/versions/${version}`)
      .then(toEditorVersion),
  currentDraft: (datasetId: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/current`)
      .then(toEditorVersion),
  createDraft: (datasetId: string, basedOnVersion?: number|null) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ based_on_version: basedOnVersion ?? null }),
    }).then(toEditorVersion),
  discardDraft: (datasetId: string) =>
    request<void>(`/api/datasets/${id(datasetId)}/drafts/current`, {
      method: 'DELETE',
    }),
  publish: (datasetId: string) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/publish`, {
      method: 'POST',
    }).then(toEditorVersion),
  addCase: (datasetId: string, item: EvaluationCase) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/cases`, {
      method: 'POST', headers, body: JSON.stringify(toApiCase(item)),
    }).then(toEditorVersion),
  updateCase: (datasetId: string, item: EvaluationCase) =>
    request<ApiDatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(item.id)}`,
      { method: 'PUT', headers, body: JSON.stringify(toApiCase(item)) },
    ).then(toEditorVersion),
  removeCase: (datasetId: string, caseId: string) =>
    request<ApiDatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}`,
      { method: 'DELETE' },
    ).then(toEditorVersion),
  copyCase: (datasetId: string, caseId: string) =>
    request<ApiDatasetVersion>(
      `/api/datasets/${id(datasetId)}/drafts/cases/${id(caseId)}/copy`,
      { method: 'POST' },
    ).then(toEditorVersion),
  reorderCases: (datasetId: string, caseIds: string[]) =>
    request<ApiDatasetVersion>(`/api/datasets/${id(datasetId)}/drafts/case-order`, {
      method: 'PUT', headers, body: JSON.stringify({ case_ids: caseIds }),
    }).then(toEditorVersion),
  exportVersion: (datasetId: string, version: number) =>
    request<DatasetExport>(
      `/api/datasets/${id(datasetId)}/versions/${version}/export`
    ),
  importDataset: (payload: DatasetExport) =>
    request<{ dataset: DatasetRecord; version: DatasetVersion }>('/api/datasets/import', {
      method: 'POST', headers, body: JSON.stringify(payload),
    }),
}
