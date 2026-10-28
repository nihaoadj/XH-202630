import { api } from '../../api/client.js'
import { requireJobResponse } from '../../contracts/guards.js'

/** @typedef {import('../../contracts/generated/contracts').GenerateRequest} GenerateRequest */
/** @typedef {import('../../contracts/generated/contracts').GenerationJobCreateResponse} CreatedJob */
/** @typedef {import('../../contracts/generated/contracts').GenerationJobStatusResponse} Job */

export const generateApi = {
  /** @param {GenerateRequest} data @returns {Promise<import('axios').AxiosResponse<CreatedJob>>} */
  createJob: data => api.post('/generate/jobs', data).then(requireJobResponse),
  /** @param {GenerateRequest} data @returns {Promise<import('axios').AxiosResponse<CreatedJob>[]>} */
  createJobsForClaim: data => {
    const types = [...new Set(data?.resource_types || [])]
    if (data?.include_claim_check && types.length > 1) {
      return Promise.all(types.map(resource_type => generateApi.createJob({ ...data, resource_types: [resource_type] })))
    }
    return Promise.all([generateApi.createJob(data)])
  },
  /** @param {string} learnerId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').GenerationJobListResponse>>} */
  listJobs: learnerId => api.get('/generate/jobs', { params: { learner_id: learnerId } }),
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<Job>>} */
  getJobStatus: runId => api.get(`/generate/jobs/${runId}`).then(requireJobResponse),
  /** @param {string} batchId @param {import('../../contracts/generated/contracts').ContinueResourceBatchRequest} data @returns {Promise<import('axios').AxiosResponse<CreatedJob>>} */
  continueBatch: (batchId, data) => api.post(`/resources/batches/${batchId}/continuations`, data).then(requireJobResponse),
  /** @param {string} runId @param {string} resourceSpecId @param {string} representation @returns {Promise<import('axios').AxiosResponse<CreatedJob>>} */
  retryResourceRepresentation: (runId, resourceSpecId, representation) => api.post(
    `/generate/jobs/${encodeURIComponent(runId)}/resource-specs/${encodeURIComponent(resourceSpecId)}`
      + `/representations/${encodeURIComponent(representation)}/retry`,
  ).then(requireJobResponse),
}
