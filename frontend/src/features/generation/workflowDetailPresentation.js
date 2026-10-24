import { workflowNodeMeta } from './workflowPresentation.js'

// Roles describe presentation only. They do not change the execution or audit verdict.
const ROLES = Object.freeze({
  diagnose: { contentKind: 'diagnosis', result: '诊断结果', reason: '诊断建议', code: 'DIAGNOSIS' },
  retrieve: { contentKind: 'evidence', result: '检索证据', code: 'RETRIEVAL' },
  plan: { contentKind: 'path', result: '学习路径', reason: '安排理由', code: 'LEARNING PATH' },
  generate: { contentKind: 'document', result: '生成正文', code: 'RESOURCE OUTPUT' },
  review: { contentKind: 'review', result: '审核结果', code: 'REVIEW' },
  claim_judge: { contentKind: 'claims', result: 'Claim 与证据', code: 'CLAIM VERIFICATION' },
})

export function detailRole(step) {
  const meta = workflowNodeMeta(step)
  return { ...meta, ...(Object.hasOwn(ROLES, meta.key) ? ROLES[meta.key] : {
    contentKind: 'status', result: '执行结果', code: 'EXECUTION',
  }) }
}

// These two persisted templates are deliberately narrow. Anything else is shown intact.
export function projectNodeResult(step) {
  const key = workflowNodeMeta(step).key
  const raw = typeof step?.output_summary === 'string' ? step.output_summary : ''
  if (key === 'diagnose') {
    const match = /^推荐难度：([^\r\n;；]+); 盲区：([^\r\n]+)$/.exec(raw)
    if (match) return { kind: 'diagnosis', difficulty: match[1], blindspots: match[2], raw }
  }
  if (key === 'plan' && raw.startsWith('学习路径：')) {
    const topics = raw.slice('学习路径：'.length).trim().split(' -> ')
    if (topics.length && topics.length <= 4 && topics.every(topic => topic.trim() && !/[\r\n]/.test(topic))) {
      return { kind: 'path', topics, raw }
    }
  }
  return { kind: 'text', raw }
}
