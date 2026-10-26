import { api } from '../../api/client.js'

export const resourceLibraryApi = {
  listByLearner: (learnerId) => api.get(`/resource-library/${encodeURIComponent(learnerId)}`),
}
