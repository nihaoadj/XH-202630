import { api } from '../../api/client.js'

export const resourceApi = {
  listByLearner: (learnerId, params = {}) => api.get(`/resources/${learnerId}`, { params }),
  get: (resourceId) => api.get(`/resources/items/${encodeURIComponent(resourceId)}`),
  getPreview: (resourceId) => api.get(`/resources/items/${encodeURIComponent(resourceId)}/preview`),
  downloadUrl: (resourceId) => `/api/resources/file/${resourceId}`,
  decideClaimPublication: (resourceId, publish) => api.post(
    `/resources/items/${encodeURIComponent(resourceId)}/claim-publication-decision`,
    { publish },
  ),
}
