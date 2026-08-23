import { api } from '../../api/client.js'

export const coursewareApi = {
  createJob: (data) => api.post('/resources/courseware/jobs', data),
  getJob: (runId) => api.get(`/resources/courseware/jobs/${encodeURIComponent(runId)}`),
  getJobDetail: (runId) => api.get(`/resources/courseware/jobs/${encodeURIComponent(runId)}/detail`),
  eventsUrl: (runId, afterSequence = 0) => `/api/resources/courseware/jobs/${encodeURIComponent(runId)}/events?after_sequence=${Number(afterSequence) || 0}`,
  retryJob: (runId) => api.post(`/resources/courseware/jobs/${encodeURIComponent(runId)}/retry`),
  retryScene: (runId, sceneId) => api.post(`/resources/courseware/jobs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/retry`),
  getSceneReview: (runId, sceneId) => api.get(`/resources/courseware/jobs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/review`),
  get: (resourceId) => api.get(`/resources/courseware/items/${encodeURIComponent(resourceId)}`),
  previewUrl: (resourceId) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/preview`,
  downloadUrl: (resourceId) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/file`,
  packageUrl: (resourceId, format) => `/api/resources/courseware/items/${encodeURIComponent(resourceId)}/packages/${encodeURIComponent(format)}`,
  ingestLearningEvents: (resourceId, events) => api.post(`/resources/courseware/items/${encodeURIComponent(resourceId)}/learning-events`, { events }),
  learningProgress: (resourceId, releaseId) => api.get(`/resources/courseware/items/${encodeURIComponent(resourceId)}/learning-progress?release_id=${encodeURIComponent(releaseId)}`),
}
