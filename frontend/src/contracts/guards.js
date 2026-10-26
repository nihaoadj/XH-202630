import { JOB_STATUSES, RUN_STATUSES, REPORT_REVISION_PATTERN, REPORT_WINDOW_DAYS } from './generated/constants.js'

/** @param {unknown} value @returns {value is Record<string, unknown>} */
export function isRecord(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
/** @param {unknown} value @returns {value is import('./generated/contracts').GenerationJobStatus} */
export function isJobStatus(value) { return typeof value === 'string' && JOB_STATUSES.includes(value) }
/** @param {unknown} value @returns {value is import('./generated/contracts').RunStatus} */
export function isRunStatus(value) { return typeof value === 'string' && RUN_STATUSES.includes(value) }
/** @param {unknown} value @returns {value is import('./generated/contracts').ReportWindowDays} */
export function isReportWindow(value) { return typeof value === 'number' && REPORT_WINDOW_DAYS.includes(value) }
/** @param {unknown} value @returns {value is string} */
export function isReportRevision(value) { return typeof value === 'string' && new RegExp(REPORT_REVISION_PATTERN).test(value) }

export class ContractResponseError extends Error {
  constructor() { super('服务返回的数据格式不正确，请稍后重试。'); this.code = 'INVALID_API_RESPONSE' }
}

/** @param {unknown} value @returns {value is import('./generated/contracts').CoursewareLearningEventAck} */
export function isLearningEventAck(value) {
  return isRecord(value) && Array.isArray(value.acknowledged_event_ids)
    && value.acknowledged_event_ids.every(id => typeof id === 'string')
}

/** @param {import('axios').AxiosResponse<unknown>} response */
export function requireAckResponse(response) {
  if (!isLearningEventAck(response.data)) throw new ContractResponseError()
  return { ...response, data: response.data }
}

/**
 * The server owns the complete DTO; this checks the critical transport fields.
 * @template {import('./generated/contracts').GenerationJobCreateResponse | import('./generated/contracts').GenerationJobStatusResponse} T
 * @param {import('axios').AxiosResponse<T>} response
 * @returns {import('axios').AxiosResponse<T>}
 */
export function requireJobResponse(response) {
  const value = response.data
  if (!isRecord(value) || typeof value.run_id !== 'string' || typeof value.learner_id !== 'string' || !isJobStatus(value.job_status)) {
    throw new ContractResponseError()
  }
  return response
}

/** @param {unknown} value @returns {value is import('./ports').ReportInvalidationInput} */
export function isReportInvalidation(value) {
  return isRecord(value) && typeof value.learner_id === 'string'
    && isReportWindow(value.window_days) && isReportRevision(value.report_revision)
}

/** @param {unknown} value @returns {number | undefined} */
export function responseStatus(value) {
  if (!isRecord(value) || !isRecord(value.response)) return undefined
  return typeof value.response.status === 'number' ? value.response.status : undefined
}
