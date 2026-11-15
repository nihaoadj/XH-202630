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

const PUBLISH_COMPLETENESS = ['complete', 'partial', 'unavailable']
const PUBLISH_INCOMPLETE_REASONS = [
  'request_missing', 'spec_request_mismatch', 'logical_identity_missing',
  'resource_reference_missing', 'unsupported_representation', 'repository_unavailable',
  'lineage_conflict',
]

/** @param {unknown} value @returns {boolean} */
function isOptionalCount(value) {
  return value === undefined || value === null
    || (typeof value === 'number' && Number.isInteger(value) && value >= 0)
}

/**
 * Validate the optional derived publication summary.
 *
 * Missing or `null` keeps legacy responses valid.  When the object exists every
 * counter must stay a finite non-negative integer (or null); `null` is never
 * coerced to zero.  A `complete` summary must satisfy its own invariants.
 *
 * @param {unknown} value
 * @returns {boolean}
 */
export function isPublishSummary(value) {
  if (value === undefined || value === null) return true
  if (!isRecord(value)) return false
  if (value.schema_version !== undefined && value.schema_version !== '1.0') return false
  if (!['total', 'published', 'unpublished', 'pending_review'].every(key => isOptionalCount(value[key]))) return false
  if (value.completeness !== undefined
    && (typeof value.completeness !== 'string' || !PUBLISH_COMPLETENESS.includes(value.completeness))) return false
  if (value.incomplete_reasons !== undefined) {
    if (!Array.isArray(value.incomplete_reasons)) return false
    if (!value.incomplete_reasons.every(reason => (
      typeof reason === 'string' && PUBLISH_INCOMPLETE_REASONS.includes(reason)
    ))) return false
  }
  if (value.completeness === 'complete') {
    const total = value.total
    const published = value.published
    const unpublished = value.unpublished
    const pending = value.pending_review
    if (typeof total !== 'number' || typeof published !== 'number'
      || typeof unpublished !== 'number' || typeof pending !== 'number') return false
    if (published + unpublished !== total) return false
    if (pending > unpublished) return false
    if ((value.incomplete_reasons || []).length) return false
  }
  return true
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
  const value = /** @type {unknown} */ (response.data)
  if (!isRecord(value) || typeof value.run_id !== 'string' || typeof value.learner_id !== 'string' || !isJobStatus(value.job_status)) {
    throw new ContractResponseError()
  }
  if (!isPublishSummary(value.publish_summary)) throw new ContractResponseError()
  return response
}

/**
 * @param {import('axios').AxiosResponse<import('./generated/contracts').GenerationJobListResponse>} response
 * @returns {import('axios').AxiosResponse<import('./generated/contracts').GenerationJobListResponse>}
 */
export function requireJobListResponse(response) {
  const value = /** @type {unknown} */ (response.data)
  if (!isRecord(value) || !Array.isArray(value.items)) throw new ContractResponseError()
  const valid = value.items.every(item => (
    isRecord(item) && typeof item.run_id === 'string' && isJobStatus(item.job_status)
    && isPublishSummary(item.publish_summary)
  ))
  if (!valid) throw new ContractResponseError()
  return response
}

/**
 * @param {import('axios').AxiosResponse<import('./generated/contracts').RunSummary>} response
 * @returns {import('axios').AxiosResponse<import('./generated/contracts').RunSummary>}
 */
export function requireRunSummaryResponse(response) {
  const value = /** @type {unknown} */ (response.data)
  if (!isRecord(value) || typeof value.run_id !== 'string' || !isRunStatus(value.status)) {
    throw new ContractResponseError()
  }
  if (!isPublishSummary(value.publish_summary)) throw new ContractResponseError()
  return response
}

/**
 * @param {import('axios').AxiosResponse<import('./generated/contracts').RunTimeline>} response
 * @returns {import('axios').AxiosResponse<import('./generated/contracts').RunTimeline>}
 */
export function requireRunTimelineResponse(response) {
  const value = /** @type {unknown} */ (response.data)
  if (!isRecord(value) || !isRecord(value.run) || !isRunStatus(value.run.status)) {
    throw new ContractResponseError()
  }
  if (!Array.isArray(value.events)) throw new ContractResponseError()
  if (!isPublishSummary(value.run.publish_summary)) throw new ContractResponseError()
  return response
}

/** @param {unknown} value @returns {value is boolean} */
function isOptionalBoolean(value) {
  return value === undefined || value === null || typeof value === 'boolean'
}

/** @param {unknown} metric @returns {boolean} */
function isOptionalMetric(metric) {
  return metric == null || (isRecord(metric) && typeof metric.status === 'string')
}

/**
 * Run resource-quality transport guard: the server owns the complete DTO.
 * Every metric row must at least carry a status string; null values stay null.
 * @param {import('axios').AxiosResponse<import('./generated/contracts').RunResourceQualityResponseV1>} response
 * @returns {import('axios').AxiosResponse<import('./generated/contracts').RunResourceQualityResponseV1>}
 */
export function requireRunResourceQualityResponse(response) {
  const value = /** @type {unknown} */ (response.data)
  if (!isRecord(value) || typeof value.run_id !== 'string' || !Array.isArray(value.items)) {
    throw new ContractResponseError()
  }
  const valid = value.items.every(item => (
    isRecord(item) && typeof item.resource_id === 'string'
    && isOptionalBoolean(item.claim_requested) && isOptionalMetric(item.coverage)
    && isOptionalMetric(item.hallucination) && isOptionalMetric(item.claim)
  ))
  if (!valid) throw new ContractResponseError()
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
