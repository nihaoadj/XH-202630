import { parseServerDate } from './generationDisplay.js'

function resourceTime(resource) {
  const raw = resource.created_at || resource.published_at || resource.updated_at
  return { raw, value: parseServerDate(raw)?.getTime() ?? Number.NEGATIVE_INFINITY }
}

export function orderStudyBatches(groups) {
  return groups.map(group => {
    const latest = group.resources.map(resourceTime).sort((a, b) => b.value - a.value)[0]
    return { ...group, latestCreatedAt: latest?.raw, latestTime: latest?.value ?? Number.NEGATIVE_INFINITY }
  }).sort((a, b) => a.latestTime - b.latestTime || String(a.runId).localeCompare(String(b.runId)))
    .map((group, index) => ({ ...group, batchNumber: index + 1 })).reverse()
}

export function chooseStudyBatch(groups, { runId = '', resourceId = '' } = {}) {
  const resourceGroup = resourceId && groups.find(group => group.resources.some(resource => resource.resource_id === resourceId))
  if (resourceGroup) return resourceGroup.runId
  const selected = runId && groups.find(group => group.runId === runId || group.resources.some(resource => resource.run_id === runId))
  return (selected || groups[0])?.runId || ''
}
