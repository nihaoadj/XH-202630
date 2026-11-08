/**
 * Presentation-only mapping from the authoritative publication summary to user
 * copy, tone and readable-version selection.
 *
 * Everything here consumes server facts. It never re-derives review gates,
 * publication permission or run counts from the currently loaded page.
 */

const RUNNING_STATUSES = new Set(['queued', 'running'])

/**
 * @typedef {import('../../contracts/generated/contracts').RunPublishSummary} RunPublishSummary
 * @typedef {import('../../contracts/generated/contracts').LearningResource} LearningResource
 * @typedef {{ label: string, tone: 'ready' | 'warning', published: number | null,
 *   total: number | null, completeness: string | null, hasSummary: boolean }} PublicationView
 */

/** @param {unknown} value @returns {value is number} */
function isCount(value) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * @param {{ publishSummary?: RunPublishSummary | null, jobStatus?: string,
 *   fallbackPublished?: number, fallbackTotal?: number }} [source]
 * @returns {PublicationView}
 */
export function resolvePublicationView({
  publishSummary = null, jobStatus = '', fallbackPublished = 0, fallbackTotal = 0,
} = {}) {
  if (!isRecord(publishSummary)) {
    return {
      label: '', tone: 'ready', published: isCount(fallbackPublished) ? fallbackPublished : null,
      total: isCount(fallbackTotal) ? fallbackTotal : null, completeness: null, hasSummary: false,
    }
  }
  const published = isCount(publishSummary.published) ? publishSummary.published : null
  const total = isCount(publishSummary.total) ? publishSummary.total : null
  const completeness = typeof publishSummary.completeness === 'string' ? publishSummary.completeness : null
  /**
   * @param {string} label
   * @param {'ready' | 'warning'} [tone]
   * @returns {PublicationView}
   */
  const view = (label, tone = 'ready') => ({
    label, tone, published, total, completeness, hasSummary: true,
  })

  const runningPrefix = RUNNING_STATUSES.has(jobStatus) ? '生成中，' : ''
  if (completeness === 'unavailable' || published === null) return view(`${runningPrefix}发布情况暂不可用`, 'warning')
  if (completeness === 'partial') {
    return view(`${runningPrefix}${published > 0 ? `已确认 ${published} 份已发布，汇总不完整` : '发布情况暂不可用'}`, 'warning')
  }
  if (RUNNING_STATUSES.has(jobStatus)) {
    if (published && total) return view(`生成中，已发布 ${published}/${total}`)
    return view('')
  }
  if (!total) return view('任务已结束，暂无已发布资源', 'warning')
  if (published === 0) return view('任务已结束，暂无已发布资源', 'warning')
  if (published < total) return view(`部分已发布（${published}/${total}）`, 'warning')
  return view(`已发布 ${published}/${total}`)
}

/**
 * Delivery counter for the resource-status header.
 *
 * `null` stays `null` so the view can render an explicit unknown marker instead
 * of an invented zero.
 *
 * @param {{ publishSummary?: RunPublishSummary | null, fallbackPublished?: number,
 *   fallbackTotal?: number }} [source]
 * @returns {{ published: number | null, total: number | null, hasSummary: boolean }}
 */
export function resolveDeliveryCount({ publishSummary = null, fallbackPublished = 0, fallbackTotal = 0 } = {}) {
  if (!isRecord(publishSummary)) {
    return {
      published: isCount(fallbackPublished) ? fallbackPublished : null,
      total: isCount(fallbackTotal) ? fallbackTotal : null,
      hasSummary: false,
    }
  }
  return {
    published: isCount(publishSummary.published) ? publishSummary.published : null,
    total: isCount(publishSummary.total) ? publishSummary.total : null,
    hasSummary: true,
  }
}

/**
 * Pick the published body a reader should open for one logical resource.
 *
 * Candidates must already be published, belong to the same run (a legacy row
 * without a run id is tolerated) and match the exact id, the same spec or a
 * trusted family or same-run parent chain. Siblings of the same type never
 * qualify, and conflicting explicit identities are never overridden.
 *
 * @param {LearningResource[]} resources
 * @param {{ runId?: string, resourceId?: string, resourceSpecId?: string, familyId?: string }} [target]
 * @returns {LearningResource | null}
 */
export function selectReadableResource(resources = [], {
  runId = '', resourceId = '', resourceSpecId = '', familyId = '',
} = {}) {
  const scoped = (resources || []).filter(resource => (
    resource
    && (!runId || !resource.run_id || resource.run_id === runId)
    && (resource.representation || 'text') === 'text'
  ))
  const byId = new Map(scoped.map(resource => [resource.resource_id, resource]))
  const knownIds = new Set(resources.map(resource => resource.resource_id))
  /** @param {LearningResource} resource */
  function matchesTarget(resource) {
    /** @type {LearningResource | undefined} */
    let current = resource
    const seen = new Set()
    while (current) {
      if (seen.has(current.resource_id)) return false
      seen.add(current.resource_id)
      // An explicit different identity cannot be overridden by ancestry.
      if (resourceSpecId && current.resource_spec_id) return current.resource_spec_id === resourceSpecId
      if (familyId && current.resource_family_id) return current.resource_family_id === familyId
      if (resourceId && current.resource_id === resourceId) return true
      const parentId = current.parent_resource_id
      if (!parentId) return false
      current = byId.get(parentId)
      // Published-only pages can omit the unpublished anchor itself. If an
      // ancestor is present, verify its scope and explicit identity instead.
      if (!current) return Boolean(resourceId && parentId === resourceId && !knownIds.has(parentId))
    }
    return false
  }
  const candidates = scoped.filter(resource => resource.publication_status === 'published' && matchesTarget(resource))
  if (!candidates.length) return null
  if (resourceId) {
    const exact = candidates.find(resource => resource.resource_id === resourceId)
    if (exact) return exact
  }
  return [...candidates].sort((left, right) => (
    Number(right.version || 0) - Number(left.version || 0)
    || String(left.resource_id).localeCompare(String(right.resource_id))
  ))[0]
}

/**
 * Resolve the readable resource id for one status item without touching its
 * execution linkage (`item.resource_id` still drives Claim, retry and review).
 *
 * @param {Record<string, unknown>} item
 * @param {{ resources?: LearningResource[], runId?: string }} [context]
 * @returns {string}
 */
export function readableResourceId(item, { resources = [], runId = '' } = {}) {
  const selected = selectReadableResource(resources, {
    runId,
    resourceId: typeof item?.resource_id === 'string' ? item.resource_id : '',
    resourceSpecId: typeof item?.resource_spec_id === 'string' ? item.resource_spec_id : '',
    familyId: typeof item?.resource_family_id === 'string' ? item.resource_family_id : '',
  })
  if (selected) return selected.resource_id
  if (item?.publication_status === 'published' && typeof item?.resource_id === 'string'
    && !resources.some(resource => resource.resource_id === item.resource_id)) return item.resource_id
  return ''
}
