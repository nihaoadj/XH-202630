export function buildTutorStorageKey({ learnerId, contextType, resourceId = '', runId = '', questionId = '' }) {
  return ['tutor_session', learnerId, contextType, resourceId || runId, questionId || 'resource'].join(':')
}

export function mergeTutorTurn(turns, incoming) {
  const items = Array.isArray(turns) ? turns : []
  if (!incoming?.turn_id || items.some((item) => item.turn_id === incoming.turn_id)) return items
  return [...items, incoming].sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
}

export function countTutorTurns(turns) {
  return (Array.isArray(turns) ? turns : []).filter((item) => item?.turn_id).length
}

