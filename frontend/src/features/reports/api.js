import { api } from '../../api/client.js'
import { ContractResponseError, isRecord, isReportRevision, isReportWindow } from '../../contracts/guards.js'

export const learningReportApi = {
  /** @param {string} learnerId @param {import('../../contracts/generated/contracts').ReportWindowDays} windowDays @param {string | null} etag @returns {Promise<import('../../contracts/ports').ReportHttpResponse>} */
  async get(learnerId, windowDays = 30, etag = null) {
    /** @type {import('axios').AxiosResponse<import('../../contracts/generated/contracts').CurrentReportResponse>} */
    const response = await api.get(`/report/${encodeURIComponent(learnerId)}`, {
      params: { window_days: windowDays },
      headers: etag ? { 'If-None-Match': `"${etag}"` } : {},
      validateStatus: (status) => status === 200 || status === 304,
    })
    if (response.status === 304) return { ...response, status: 304 }
    const data = response.data
    if (!isRecord(data) || data.learner_id !== learnerId || !isRecord(data.window)
      || !isReportWindow(data.window.window_days) || data.window.window_days !== windowDays || !isReportRevision(data.report_revision)) {
      throw new ContractResponseError()
    }
    return { ...response, status: 200 }
  },
}

/** @param {import('../../contracts/ports').ReportFetchRequest} context @returns {Promise<import('../../contracts/ports').ReportSnapshot | null>} */
export async function fetchReportSnapshot({ learnerId, windowDays, etag = null }) {
  const response = await learningReportApi.get(learnerId, windowDays, etag)
  return response.status === 304 ? null : { data: response.data, revision: response.data.report_revision }
}

// Preserve the legacy report request without window or ETag parameters.
export const reportApi = {
  /** @param {string} id */
  get: (id) => api.get(`/report/${id}`),
}
