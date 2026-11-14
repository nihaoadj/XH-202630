export function coursewareTaskSource(task, nodeNames = {}, nodeTiers = {}) {
  const sources = Array.isArray(task?.source_summary) ? task.source_summary : []
  const nodeIds = [...new Set(sources.flatMap(source => source.knowledge_points || []))]
  const names = nodeIds.map(id => nodeNames[id] || id)
  const tiers = nodeIds.map(id => nodeTiers[id] ?? nodeTiers[Object.keys(nodeNames).find(key => nodeNames[key] === id)])
  return {
    nodeIds,
    title: nodeIds.map(id => nodeNames[id]).filter(Boolean).join('、') || sources[0]?.topic || names.join('、') || task?.title || '互动课件',
    sourceTitle: sources.map(source => source.title || source.resource_type).filter(Boolean).join('、'),
    tier: tiers.length && tiers.every(tier => Number.isInteger(tier) && tier === tiers[0]) ? tiers[0] : null,
  }
}
