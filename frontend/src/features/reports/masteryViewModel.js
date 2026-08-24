export const MASTERY_STATUS_LABELS = Object.freeze({
  unassessed: '尚未测量',
  self_reported: '低置信自评',
  weak: '客观薄弱',
  learning: '学习中',
  mastered: '已掌握',
})

export const FOCUS_REASON_LABELS = Object.freeze({
  OBJECTIVE_SCORE_BELOW_0_60: '客观测评分低于 60%',
  RECENT_OBJECTIVE_SCORE_REGRESSED: '最近客观表现有所回落',
  LOW_CONFIDENCE_SELF_REPORT_BELOW_0_60: '自评基础偏弱，待客观验证',
  UNASSESSED_BLOCKING_PREREQUISITE: '尚未测量且会影响后续能力',
})

export function masteryPercent(mastery) {
  return typeof mastery?.mastery_score === 'number'
    ? `${Math.round(mastery.mastery_score * 100)}%`
    : '未测量'
}

export function statusLabel(status) {
  return MASTERY_STATUS_LABELS[status] || status || '未知状态'
}

export function focusReason(code) {
  return FOCUS_REASON_LABELS[code] || code
}

export function relationshipLabels(node, nodes) {
  const names = new Map((nodes || []).map((item) => [item.skill_node_id, item.name]))
  return {
    prerequisites: (node?.prerequisites || []).map((id) => names.get(id) || id),
    children: (node?.children || []).map((id) => names.get(id) || id),
  }
}

