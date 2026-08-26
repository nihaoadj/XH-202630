const RESOURCE_SHELF_TYPE_ORDER = [
  '讲义',
  '实操指南',
  '案例分析',
  '复习清单',
  '个性化纠错训练包',
  '互动HTML课件',
  '分阶测试题',
]

const RESOURCE_SHELF_TYPE_RANK = new Map(
  RESOURCE_SHELF_TYPE_ORDER.map((type, index) => [type, index]),
)

function normalizeResourceType(resource) {
  const sourceSummaryType = Array.isArray(resource?.source_summary)
    ? resource.source_summary.find((item) => item?.resource_type)?.resource_type
    : ''
  const rawType = String(
    resource?.source_resource_type || sourceSummaryType || resource?.resource_type || '',
  ).trim()
  const compactType = rawType.replace(/[\s_-]+/g, '').toLowerCase()

  if (compactType.includes('讲义') || compactType.includes('text')) return '讲义'
  if (compactType.includes('实操') || compactType.includes('practice')) return '实操指南'
  if (compactType.includes('案例') || compactType.includes('case')) return '案例分析'
  if (compactType.includes('清单') || compactType.includes('checklist')) return '复习清单'
  if (compactType.includes('测试') || compactType.includes('assessment')) return '分阶测试题'
  if (resource?.resource_kind === 'interactive_courseware' || compactType.includes('html')) {
    return '互动HTML课件'
  }
  return rawType || '其他资源'
}

export function resourceShelfTypeLabel(resource) {
  const sourceSummaryType = Array.isArray(resource?.source_summary)
    ? resource.source_summary.find((item) => item?.resource_type)?.resource_type
    : ''
  const sourceType = String(resource?.source_resource_type || sourceSummaryType || '').trim()
  if (resource?.resource_kind === 'interactive_courseware' && sourceType) {
    return `互动${sourceType}`
  }
  return resource?.resource_type
    || (resource?.resource_kind === 'interactive_courseware' ? '互动HTML课件' : '学习资源')
}

function resourceTimestamp(resource) {
  const value = resource?.created_at || resource?.published_at || resource?.updated_at
  const timestamp = value ? Date.parse(value) : Number.NaN
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY
}

/**
 * Arrange the learner-facing shelf predictably without mutating the API array.
 * Type groups are fixed; within one group older resources stay left and newer
 * resources move right. The final id tie-break keeps equal timestamps stable.
 */
export function sortResourcesForShelf(resources = []) {
  return resources
    .map((resource, sourceIndex) => ({
      resource,
      sourceIndex,
      shelfType: normalizeResourceType(resource),
    }))
    .sort((left, right) => {
      const typeOrder = (RESOURCE_SHELF_TYPE_RANK.get(left.shelfType) ?? RESOURCE_SHELF_TYPE_ORDER.length)
        - (RESOURCE_SHELF_TYPE_RANK.get(right.shelfType) ?? RESOURCE_SHELF_TYPE_ORDER.length)
      if (typeOrder !== 0) return typeOrder

      const timeOrder = resourceTimestamp(left.resource) - resourceTimestamp(right.resource)
      if (timeOrder !== 0) return timeOrder

      const idOrder = String(left.resource.resource_id || left.resource.id || '')
        .localeCompare(String(right.resource.resource_id || right.resource.id || ''))
      return idOrder || left.sourceIndex - right.sourceIndex
    })
    .map(({ resource }) => resource)
}

export { RESOURCE_SHELF_TYPE_ORDER }
