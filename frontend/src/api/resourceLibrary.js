import { api } from './client'

export const resourceLibraryApi = {
  listByLearner: (learnerId) => api.get(`/resource-library/${encodeURIComponent(learnerId)}`),
}
