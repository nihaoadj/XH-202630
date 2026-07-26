import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export const profileApi = {
  list: (params) => api.get('/profiles/', { params }),
  get: (id) => api.get(`/profiles/${id}`),
  update: (id, data) => api.patch(`/profiles/${id}`, data),
  delete: (id) => api.delete(`/profiles/${id}`),
}

export const knowledgeApi = {
  listDomains: () => api.get('/knowledge/domains'),
  listDirections: () => api.get('/knowledge/directions'),
  getInfo: (learningDirectionId) => api.get('/knowledge/info', { params: { knowledge_base_id: learningDirectionId } }),
}

export const onboardingApi = {
  getQuestions: (learningDirectionId) => api.get('/onboarding/questions', { params: { learning_direction_id: learningDirectionId } }),
  createInitialProfile: (data) => api.post('/onboarding/initial-profile', data),
}

export const diagnosisApi = {
  submit: (data) => api.post('/diagnosis/submit', data),
}

export const generateApi = {
  generate: (data) => api.post('/generate/', data),
}

export const resourceApi = {
  listByLearner: (learnerId) => api.get(`/resources/${learnerId}`),
}

export const feedbackApi = {
  submit: (data) => api.post('/feedback/', data),
  history: (learnerId) => api.get(`/feedback/history/${learnerId}`),
}

export const reportApi = {
  get: (id) => api.get(`/report/${id}`),
}
