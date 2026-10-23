const NODE_META = Object.freeze({
  diagnose: { title: '学情诊断', description: '学习基础与目标' },
  retrieve: { title: '知识检索', description: '匹配学习所需知识' },
  evidence_gate: { title: '证据门禁', description: '核对来源与证据条件' },
  plan: { title: '学习规划', description: '安排学习内容与资源' },
  generate: { title: '资源生成', description: '生成学习资源正文' },
  review: { title: '审核纠偏', description: '审核问题与定向修订' },
  claim_extract: { title: '事实抽取', description: '提取需要核验的陈述' },
  claim_judge: { title: '事实核验', description: '对照冻结证据判定陈述' },
  prepare_revision: { title: '返工准备', description: '准备资源定向修订' },
  prepare_claim_revision: { title: '事实修订准备', description: '准备事实问题修订' },
  finalize_draft: { title: '草稿整理', description: '整理生成草稿' },
  claim_decide: { title: '事实审核决策', description: '汇总事实核验结果' },
  finalize: { title: '流程收尾', description: '整理本轮执行结果' },
  finalize_evidence_insufficient: { title: '证据不足处理', description: '记录证据不足结果' },
})

const INSPECTABLE_NODES = new Set([
  'diagnose', 'retrieve', 'plan', 'generate', 'review', 'claim_judge',
])

const LEGACY_AGENT_NODES = Object.freeze({
  diagnosis: 'diagnose',
  retriever: 'retrieve',
  evidence_gate: 'evidence_gate',
  planner: 'plan',
  generator: 'generate',
  reviewer: 'review',
  claim_extractor: 'claim_extract',
  claim_judge: 'claim_judge',
})

function recordedName(value) {
  return typeof value === 'string' ? value.trim() : ''
}

export function workflowNodeMeta(step) {
  const nodeName = recordedName(step?.node_name)
  const agentName = recordedName(step?.agent_name)
  // An existing unknown node is never promoted through an agent alias.
  const legacyKey = Object.hasOwn(LEGACY_AGENT_NODES, agentName) ? LEGACY_AGENT_NODES[agentName] : null
  const key = nodeName || legacyKey || agentName || 'unknown'
  const meta = Object.hasOwn(NODE_META, key) ? NODE_META[key] : null
  return {
    key,
    title: meta?.title || '其他处理',
    description: meta?.description || nodeName || agentName || '未命名记录',
    inspectable: Boolean((nodeName || legacyKey) && INSPECTABLE_NODES.has(key)),
  }
}

export function canInspectStep(step) {
  return workflowNodeMeta(step).inspectable
}

export function formatDuration(ms) {
  if (ms == null || ms === '') return '—'
  const duration = Number(ms)
  if (!Number.isFinite(duration) || duration < 0) return '—'
  if (duration < 1000) return `${Math.round(duration)} ms`
  if (duration < 60000) return `${Number((duration / 1000).toFixed(1))} 秒`

  const totalSeconds = Math.round(duration / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours) return [hours + ' 小时', minutes ? minutes + ' 分' : ''].filter(Boolean).join(' ')
  return [minutes + ' 分', seconds ? seconds + ' 秒' : ''].filter(Boolean).join(' ')
}
