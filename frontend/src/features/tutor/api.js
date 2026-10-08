import { api } from '../../api/client'

export const tutorApi = {
  createSession: (data) => api.post('/tutor/sessions', data),
  listSessions: (params) => api.get('/tutor/sessions', { params }),
  getSession: (sessionId) => api.get(`/tutor/sessions/${sessionId}`),
  submitTurn: (sessionId, data) => api.post(`/tutor/sessions/${sessionId}/turns`, data),
  closeSession: (sessionId) => api.post(`/tutor/sessions/${sessionId}/close`),
}
