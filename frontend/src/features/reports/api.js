import { api } from '../../api/client'

export const learningReportApi = {
  get(learnerId, windowDays = 30, etag = null) {
    return api.get(`/report/${encodeURIComponent(learnerId)}`, {
      params: { window_days: windowDays },
      headers: etag ? { 'If-None-Match': `"${etag}"` } : {},
      validateStatus: (status) => status === 200 || status === 304,
    })
  },
}
