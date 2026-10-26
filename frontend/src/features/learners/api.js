import { api } from '../../api/client.js'

export const profileApi = {
  list: (params) => api.get('/profiles/', { params }),
  get: (id) => api.get(`/profiles/${id}`),
  abilityNodes: (id) => api.get(`/profiles/${id}/ability-nodes`),
  update: (id, data) => api.patch(`/profiles/${id}`, data),
  delete: (id) => api.delete(`/profiles/${id}`),
}

export const userApi = {
  list: () => api.get('/users/'),
  get: (id) => api.get(`/users/${id}`),
  create: (data) => api.post('/users/', data),
  update: (id, data) => api.patch(`/users/${id}`, data),
}

export const diagnosisApi = {
  submit: (data) => api.post('/diagnosis/submit', data),
}

export const learningHistoryApi = {
  timeline: (learnerId) => api.get(`/learning-history/${learnerId}/timeline`),
  journey: (learnerId, params = {}) => api.get(`/learning-history/${learnerId}/journey`, { params }),
}
