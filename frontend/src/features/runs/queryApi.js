import { api } from '../../api/client.js'

export const runApi = {
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RunSummary>>} */
  get: runId => api.get(`/runs/${runId}`),
  /** @param {string} runId @param {{after_sequence?: number, limit?: number}} params @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').RunTimeline>>} */
  timeline: (runId, params = {}) => api.get(`/runs/${runId}/timeline`, { params }),
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<unknown>>} */
  evidence: runId => api.get(`/runs/${runId}/evidence`),
  /** @param {string} runId @returns {Promise<import('axios').AxiosResponse<unknown>>} */
  claims: runId => api.get(`/runs/${runId}/claims`),
}
