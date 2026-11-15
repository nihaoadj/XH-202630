import { api } from '../../api/client.js'

export const feedbackApi = {
  getEvaluationSession: (learnerId, resourceId) => api.get(`/feedback/evaluation/${learnerId}/${resourceId}`),
  getRunEvaluationSession: (learnerId, runId) => api.get(`/feedback/evaluation/run/${learnerId}/${runId}`),
  getBatchEvaluationSession: (learnerId, batchId) => api.get(`/feedback/evaluation/batch/${learnerId}/${batchId}`),
  submitAttempt: (data) => api.post('/feedback/attempts', data),
  submitRunAttempt: (data) => api.post('/feedback/attempts/run/submit', data),
  submitBatchAttempt: (data) => api.post('/feedback/attempts/batch/submit', data),
  selectFollowup: (data) => api.post('/feedback/followups/select', data),
  listResults: (learnerId, params = {}) => api.get(`/feedback/results/${learnerId}`, { params }),
  listAttempts: (learnerId, params = {}) => api.get(`/feedback/attempts/${learnerId}`, { params }),
  getPath: (learnerId) => api.get(`/feedback/path/${learnerId}`),
}
