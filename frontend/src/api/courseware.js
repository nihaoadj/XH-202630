import { api } from './client'

export const coursewareApi = {
  createJob: (data) => api.post('/resources/courseware/jobs', data),
  getJob: (runId) => api.get(`/resources/courseware/jobs/${encodeURIComponent(runId)}`),
  getJobDetail: (runId) => api.get(`/resources/courseware/jobs/${encodeURIComponent(runId)}/detail`),
  eventsUrl: (runId, afterSequence = 0) => `/api/resources/courseware/jobs/${encodeURIComponent(runId)}/events?after_sequence=${Number(afterSequence) || 0}`,
  retryJob: (runId) => api.post(`/resources/courseware/jobs/${encodeURIComponent(runId)}/retry`),
  retryScene: (runId, sceneId) => api.post(`/resources/courseware/jobs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/retry`),
  publishJob: (runId) => api.post(`/resources/courseware/jobs/${encodeURIComponent(runId)}/publish`),
  get: (resourceId) => api.get(`/resources/courseware/items/${encodeURIComponent(resourceId)}`),
  previewUrl: (resourceId) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/preview`,
  downloadUrl: (resourceId) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/file`,
  packageUrl: (resourceId, format) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/packages/${encodeURIComponent(format)}`,
}
