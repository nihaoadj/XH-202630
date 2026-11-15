import { api } from '../../api/client.js'
import { requireRunResourceQualityResponse, requireRunSummaryResponse, requireRunTimelineResponse } from '../../contracts/guards.js'

export const runApi = {
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RunSummary>>} */
  get: runId => api.get(`/runs/${runId}`).then(requireRunSummaryResponse),
  /** @param {string} runId @param {{after_sequence?: number, limit?: number}} params @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RunTimeline>>} */
  timeline: (runId, params = {}) => api.get(`/runs/${runId}/timeline`, { params }).then(requireRunTimelineResponse),
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<unknown>>} */
  evidence: runId => api.get(`/runs/${runId}/evidence`),
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<unknown>>} */
  claims: runId => api.get(`/runs/${runId}/claims`),
  /**
   * Versioned quality projection; the response binds every metric to the
   * exact run/resource version.  The frontend never recomputes these values.
   * @param {string} runId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RunResourceQualityResponseV1>>}
   */
  resourceQuality: runId => api.get(`/runs/${runId}/resource-quality`).then(requireRunResourceQualityResponse),
  /**
   * Read-only supplement summary.  It never triggers retrieval and exposes only
   * status, counts and evidence scope ids.
   * @param {string} runId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').ClaimEvidenceRetrievalSummaryV1>>}
   */
  claimEvidenceRetrieval: runId => api.get(`/runs/${runId}/claim-evidence-retrieval`),
}
