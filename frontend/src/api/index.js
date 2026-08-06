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

export const userApi = {
  list: () => api.get('/users/'),
  get: (id) => api.get(`/users/${id}`),
  create: (data) => api.post('/users/', data),
  update: (id, data) => api.patch(`/users/${id}`, data),
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
  createJob: (data) => api.post('/generate/jobs', data),
  listJobs: (learnerId) => api.get('/generate/jobs', { params: { learner_id: learnerId } }),
  getJobStatus: (runId) => api.get(`/generate/jobs/${runId}`),
}

export const learningHistoryApi = {
  timeline: (learnerId) => api.get(`/learning-history/${learnerId}/timeline`),
}

export const resourceApi = {
  listByLearner: (learnerId, params = {}) => api.get(`/resources/${learnerId}`, { params }),
  downloadUrl: (resourceId) => `/api/resources/file/${resourceId}`,
}

export const feedbackApi = {
  submit: (data) => api.post('/feedback/', data),
  history: (learnerId) => api.get(`/feedback/history/${learnerId}`),
  getEvaluationSession: (learnerId, resourceId) => api.get(`/feedback/evaluation/${learnerId}/${resourceId}`),
  getRunEvaluationSession: (learnerId, runId) => api.get(`/feedback/evaluation/run/${learnerId}/${runId}`),
  submitEvaluation: (data) => api.post('/feedback/evaluation/submit', data),
  submitRunEvaluation: (data) => api.post('/feedback/evaluation/run/submit', data),
}

export const reportApi = {
  get: (id) => api.get(`/report/${id}`),
}
