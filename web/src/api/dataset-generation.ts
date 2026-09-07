import { http, request } from '@/utils/request'
import type {
  AcceptGeneratedCasesRequest,
  DatasetMutationReceipt,
  GenerateCandidatesRequest,
  GeneratedCandidate,
  GenerationModelProfile,
  GenerationResult,
  ModelCredentialStatus,
  TargetCatalogItem,
  TargetType,
  TargetVersionItem,
} from '@/types/dataset-generation'
import type { EvaluationCase, TargetRef } from '@/types/dataset'

const enc = encodeURIComponent

export const datasetGenerationApi = {
  targets: (targetType?: TargetType) =>
    http.get<TargetCatalogItem[]>('/api/targets', targetType ? { target_type: targetType } : undefined),

  targetVersions: (target: TargetCatalogItem) =>
    http.get<TargetVersionItem[]>(
      `/api/targets/${enc(target.platform_id)}/${enc(target.target_type)}/${enc(target.external_target_id)}/versions`,
    ),

  modelProfiles: () =>
    http.get<GenerationModelProfile[]>('/api/dataset-generation/model-profiles'),

  configureCredential: (profileId: string, apiKey: string) =>
    request<ModelCredentialStatus>({
      url: `/api/dataset-generation/model-profiles/${enc(profileId)}/credential`,
      method: 'PUT',
      data: { api_key: apiKey },
      timeout: 65000,
      headers: { 'Content-Type': 'application/json' },
    }),

  deleteCredential: (profileId: string) =>
    request<ModelCredentialStatus>({
      url: `/api/dataset-generation/model-profiles/${enc(profileId)}/credential`,
      method: 'DELETE',
    }),

  generate: (datasetId: string, payload: GenerateCandidatesRequest) =>
    request<GenerationResult>({
      url: `/api/datasets/${enc(datasetId)}/drafts/generate-candidates`,
      method: 'POST',
      data: payload,
      timeout: 70000,
      headers: { 'Content-Type': 'application/json' },
    }),

  validate: (
    datasetId: string,
    payload: {
      draft_id: string
      draft_content_sha256: string
      target_ref: TargetRef
      target_descriptor_sha256: string
      recipe_version: string
      acceptance_token: string
      candidate_id: string
      slot_index: number
      case: EvaluationCase
    },
  ) =>
    http.post<GeneratedCandidate>(
      `/api/datasets/${enc(datasetId)}/drafts/generated-candidates/validate`,
      payload,
    ),

  accept: (
    datasetId: string,
    payload: AcceptGeneratedCasesRequest,
    idempotencyKey: string,
  ) =>
    request<DatasetMutationReceipt>({
      url: `/api/datasets/${enc(datasetId)}/drafts/cases/batch`,
      method: 'POST',
      data: payload,
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
    }),
}

export default datasetGenerationApi
