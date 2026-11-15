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


export const evaluationApi = {
  /** @returns {Promise<import('axios').AxiosResponse<import('../../contracts/generated/contracts').EvaluationSummary>>} */
  async summary() {
    const response = await api.get('/evaluation/summary')
    const data = response.data
    if (!isRecord(data) || !Number.isInteger(data.sample_count) || !isRecord(data.metrics)) throw new ContractResponseError()
    // An old server can omit the additive collection; old averages are not v2 measurements.
    const groups = data.resource_quality_evaluations ?? []
    if (data.resource_quality_invalid_row_total != null && (!Number.isInteger(data.resource_quality_invalid_row_total) || Number(data.resource_quality_invalid_row_total) < 0)) throw new ContractResponseError()
    if (!Array.isArray(groups) || groups.some(group => !isRecord(group)
      || !isRecord(group.manifest) || group.manifest.metric_definition_version !== 'resource-quality/v2'
      || !['offline_gold', 'live_model'].includes(String(group.manifest.evidence_mode))
      || !['complete', 'incomplete', 'invalid'].includes(String(group.status))
      || ![group.coverage, group.hallucination, group.difficulty].every(metric => isRecord(metric)
        && typeof metric.status === 'string'
        && (metric.value === null || (typeof metric.value === 'number' && Number.isFinite(metric.value) && metric.value >= 0 && metric.value <= 1))))) {
      throw new ContractResponseError()
    }
    return { ...response, data: /** @type {import('../../contracts/generated/contracts').EvaluationSummary} */ ({ ...data, resource_quality_evaluations: groups }) }
  },
}
