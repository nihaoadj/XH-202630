import { api } from '../../api/client'

export const resourceLibraryApi = {
  listByLearner: (learnerId) => api.get(`/resource-library/${encodeURIComponent(learnerId)}`),
}
