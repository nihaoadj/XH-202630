import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const isAuthPage = ['/login', '/register'].includes(window.location.pathname)
    const isAuthRequest = String(error?.config?.url || '').startsWith('/auth/')
    if (error?.response?.status === 401 && !isAuthPage && !isAuthRequest) {
      window.location.assign(`/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`)
    }
    return Promise.reject(error)
  },
)

export const authApi = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  me: () => api.get('/auth/me'),
  logout: () => api.post('/auth/logout'),
}

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
  continueBatch: (batchId, data) => api.post(`/resources/batches/${batchId}/continuations`, data),
}

export const runApi = {
  get: (runId) => api.get(`/runs/${runId}`),
  timeline: (runId, params = {}) => api.get(`/runs/${runId}/timeline`, { params }),
  evidence: (runId) => api.get(`/runs/${runId}/evidence`),
  claims: (runId) => api.get(`/runs/${runId}/claims`),
}

export const learningHistoryApi = {
  timeline: (learnerId) => api.get(`/learning-history/${learnerId}/timeline`),
}

export const resourceApi = {
  listByLearner: (learnerId, params = {}) => api.get(`/resources/${learnerId}`, { params }),
  downloadUrl: (resourceId) => `/api/resources/file/${resourceId}`,
}

export const feedbackApi = {
  getEvaluationSession: (learnerId, resourceId) => api.get(`/feedback/evaluation/${learnerId}/${resourceId}`),
  getRunEvaluationSession: (learnerId, runId) => api.get(`/feedback/evaluation/run/${learnerId}/${runId}`),
  getBatchEvaluationSession: (learnerId, batchId) => api.get(`/feedback/evaluation/batch/${learnerId}/${batchId}`),
  submitAttempt: (data) => api.post('/feedback/attempts', data),
  submitRunAttempt: (data) => api.post('/feedback/attempts/run/submit', data),
  submitBatchAttempt: (data) => api.post('/feedback/attempts/batch/submit', data),
  listAttempts: (learnerId, params = {}) => api.get(`/feedback/attempts/${learnerId}`, { params }),
  getPath: (learnerId) => api.get(`/feedback/path/${learnerId}`),
}

export const reportApi = {
  get: (id) => api.get(`/report/${id}`),
}
