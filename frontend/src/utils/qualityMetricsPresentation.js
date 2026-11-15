/**
 * Versioned quality-metric presentation helpers.
 *
 * The backend owns every business definition; these helpers only translate the
 * shipped `RateMetricV1` payloads into labels.  They never recompute a rate,
 * never back-fill a value from a legacy score, and never render an unmeasured
 * state as 0%.
 */

const STATUS_LABELS = {
  complete: '已测量',
  reference: '参考值（待核验）',
  not_requested: '未开启',
  pending: '进行中',
  incomplete: '未完成',
  failed: '失败',
  not_applicable: '不适用',
  unavailable: '暂不可用',
  legacy_unavailable: '历史数据缺失',
}

const SOURCE_LABELS = {
  ordinary_review: '普通审核',
  ordinary_rule_reference: '普通审核参考',
  claim_judge: 'Claim 核验',
  labeled_evaluation: '标注评测',
  none: '无来源',
}

const REASON_LABELS = {
  NO_VISIBLE_RESOURCES: '当前没有可见资源',
  ORDINARY_REVIEW_DISABLED: '普通审核未开启',
  ORDINARY_PROGRAM_GATE_ONLY: '仅程序门禁轮次，未进行模型审核',
  ORDINARY_REVIEW_PENDING: '普通审核尚未完成',
  ORDINARY_REVIEW_FAILED: '普通审核执行失败',
  ORDINARY_REVIEW_INCOMPLETE: '普通审核结果不完整',
  ORDINARY_REVIEW_MISSING: '缺少同版本普通审核记录',
  CLAIM_CHECK_NOT_REQUESTED: '未开启 Claim 核验',
  CLAIM_CHECK_PENDING: 'Claim 判定尚未完成',
  CLAIM_CHECK_FAILED: 'Claim 判定失败',
  CLAIM_CHECK_INCOMPLETE: 'Claim 判定未完成',
  CLAIM_CHECK_NOT_APPLICABLE: 'Claim 核验不适用',
  CLAIM_JUDGEMENT_CONFLICT: '同资源存在冲突判定',
  NO_FACTUAL_CLAIMS: '没有可判定的事实 Claim',
  LEGACY_RUN_WITHOUT_LEDGER: '历史运行缺少私有审核账本',
  SOURCE_READ_UNAVAILABLE: '质量来源读取不可用',
  SOURCE_READ_FAILED: '质量来源读取失败',
  COVERAGE_RESULT_INCOMPLETE: '覆盖结果不完整',
}

/** @param {unknown} metric @returns {metric is Record<string, unknown>} */
function isMetric(metric) {
  return metric !== null && typeof metric === 'object' && typeof metric.status === 'string'
}

/**
 * Percentage text for a measured rate; an unmeasured state always shows an
 * em dash so it can never be misread as 0%.
 * @param {unknown} metric
 * @returns {string}
 */
export function qualityValueText(metric) {
  if (!isMetric(metric)) return '—'
  if (metric.status !== 'complete' && metric.status !== 'reference') return '—'
  // Number(null) is 0: only a real number may become a percentage.
  if (typeof metric.value !== 'number') return '—'
  const value = metric.value
  if (!Number.isFinite(value) || value < 0 || value > 1) return '—'
  return `${(value * 100).toFixed(1)}%`
}

/**
 * @param {unknown} metric
 * @returns {string} e.g. `92.3% · 普通审核 · 已测量`
 */
export function qualityMetricText(metric) {
  if (!isMetric(metric)) return '— · 未记录指标'
  const valueText = qualityValueText(metric)
  const source = sourceLabel(metric)
  const status = statusLabel(metric)
  const reason = reasonText(metric)
  return reason
    ? `${valueText} · ${source} · ${status}（${reason}）`
    : `${valueText} · ${source} · ${status}`
}

/** @param {unknown} metric @returns {string} */
export function statusLabel(metric) {
  if (!isMetric(metric)) return '未记录指标'
  return STATUS_LABELS[metric.status] || String(metric.status)
}

/** @param {unknown} metric @returns {string} */
export function sourceLabel(metric) {
  if (!isMetric(metric)) return '未记录指标'
  return SOURCE_LABELS[metric.source] || String(metric.source)
}

/** @param {unknown} metric @returns {string} */
export function reasonText(metric) {
  if (!isMetric(metric) || !Array.isArray(metric.reason_codes) || !metric.reason_codes.length) return ''
  const known = metric.reason_codes.map(code => REASON_LABELS[code]).filter(Boolean)
  return known.length ? known.join('；') : metric.reason_codes.join('；')
}

/**
 * A 5% ordinary-review reference is an uncalibrated rule value, never a
 * measured pass.  It must never render with a pass/success tone.
 * @param {unknown} metric
 * @returns {boolean}
 */
export function isReferenceMetric(metric) {
  return isMetric(metric) && metric.status === 'reference'
}

/**
 * Display tone for a metric chip.  `success` is reserved for measured values
 * that the backend assessed as `met`; reference values stay `attention`.
 * @param {unknown} metric
 * @returns {'success' | 'attention' | 'muted'}
 */
export function qualityTone(metric) {
  if (!isMetric(metric)) return 'muted'
  if (metric.status === 'complete') return metric.assessment === 'met' ? 'success' : 'attention'
  if (metric.status === 'reference') return 'attention'
  return 'muted'
}

/**
 * Coverage targets come from the ordinary-review per-knowledge-point results.
 * Returns rows ready for template rendering.
 * @param {unknown} item resource quality item
 * @returns {Array<{ target_id: string, covered: boolean, display_name: string, location: string }>}
 */
export function coverageTargetRows(item) {
  if (item === null || typeof item !== 'object' || !Array.isArray(item.target_coverage)) return []
  return item.target_coverage
    .filter(entry => entry && typeof entry === 'object')
    .map(entry => ({
      target_id: String(entry.target_id ?? ''), covered: entry.status === 'covered',
      display_name: String(entry.display_name || entry.target_id || ''),
      location: [entry.paragraph_id, ...(Array.isArray(entry.heading_path) ? entry.heading_path : []), entry.unit_id].filter(Boolean).join(' / '),
    }))
}

/**
 * The reference hallucination value is a fixed rule number shipped by the
 * backend; the UI must label it explicitly as uncalibrated.
 * @param {unknown} metric
 * @returns {string}
 */
export function hallucinationMetricText(metric) {
  if (!isMetric(metric)) return '— · 未记录指标'
  if (metric.status === 'reference') return `5% · ${sourceLabel(metric)} · 未校准 · 待核验`
  return qualityMetricText(metric)
}

/** @param {unknown} value */
export function dimensionStatusLabel(value) {
  return ({ pass: '通过', fail: '未通过', insufficient: '证据不足', not_evaluated: '未评估' })[String(value)] || '未评估'
}
