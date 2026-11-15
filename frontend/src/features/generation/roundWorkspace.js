/** Stable member identity is essential when two legacy members have the same role. */
export function defaultRoundMember(detail) {
  return detail?.members?.find(member => member.role === 'primary')
    || [...(detail?.members || [])].sort((a, b) => a.node_id.localeCompare(b.node_id) || a.member_id.localeCompare(b.member_id))[0]
}

export function memberStage(detail, memberId, stageId) {
  const stages = (detail?.stages || []).filter(stage => stage.members.some(member => member.member_id === memberId))
  return stages.find(stage => stage.stage_id === stageId) || [...stages].sort((a, b) => b.ordinal - a.ordinal)[0]
}

export function resolveRoundSelection(detail, selection = {}) {
  const member = detail?.members?.find(item => item.member_id === selection.memberId) || defaultRoundMember(detail)
  if (!member) return null
  const stage = memberStage(detail, member.member_id, selection.stageId)
  const scope = stage?.members.find(item => item.member_id === member.member_id)
  const runId = scope?.job_ids.includes(selection.runId) ? selection.runId : scope?.job_ids[0]
  return { memberId: member.member_id, stageId: stage?.stage_id || '', runId: runId || '' }
}

export function primaryRoundRun(detail) {
  const member = detail?.members?.find(item => item.role === 'primary')
  const initial = detail?.stages?.find(item => item.kind === 'initial')
  return initial?.members.find(item => item.member_id === member?.member_id)?.job_ids[0] || ''
}

export function roundRoleLabel(role) {
  return { primary: '主学习', review: '附带复习', legacy: '历史节点' }[role] || '学习节点'
}

export function roundStateLabel(state) {
  return { producing: '生成中', awaiting_assessment: '待测评', completed: '测评已完成', failed: '生成失败' }[state] || '等待状态'
}
