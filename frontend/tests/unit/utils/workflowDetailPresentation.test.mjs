import assert from 'node:assert/strict'
import { detailRole, projectNodeResult } from '../../../src/features/generation/workflowDetailPresentation.js'
import { iconPaths } from '../../../src/features/generation/workflowNodeIcons.js'

const step = key => ({ node_name: key })

const detailRoles = new Map([
  ['diagnose', 'diagnosis'],
  ['retrieve', 'evidence'],
  ['plan', 'path'],
  ['generate', 'document'],
  ['review', 'review'],
  ['claim_judge', 'claims'],
  ['evidence_gate', 'status'],
  ['claim_extract', 'status'],
])
for (const [key, contentKind] of detailRoles) {
  assert.equal(detailRole(step(key)).contentKind, contentKind, `${key} should expose only its own single-page content role`)
}
assert.equal(detailRole({ agent_name: 'planner' }).contentKind, 'path', 'legacy planner records should retain their mapped role')
assert.equal(detailRole({ node_name: 'unknown_node', agent_name: 'planner' }).contentKind, 'status', 'an explicit unknown node must not gain a detail role through an alias')
assert.equal(detailRole(step('constructor')).contentKind, 'status', 'prototype names must fall back to a passive status role')

const planned = { ...step('plan'), output_summary: '学习路径：Embedding -> 文本向量化 -> 查询编码 -> 相似度' }
assert.deepEqual(projectNodeResult(planned).topics, ['Embedding', '文本向量化', '查询编码', '相似度'])
for (const output of ['学习路径：', '学习路径：A ->  -> B', '学习路径：A -> B -> C -> D -> E', '学习路径：A\nB', '模型调用失败，使用现有输入', '路径：A -> B']) {
  assert.deepEqual(projectNodeResult({ ...step('plan'), output_summary: output }), { kind: 'text', raw: output }, 'unsupported path formats must remain intact')
}

const raw = "推荐难度：初级; 盲区：['Embedding', '文档解析']"
assert.deepEqual(projectNodeResult({ ...step('diagnose'), output_summary: raw }), {
  kind: 'diagnosis', difficulty: '初级', blindspots: "['Embedding', '文档解析']", raw,
})
for (const output of ['推荐难度：初级；盲区：未知', '推荐难度：初级; 盲区：A\n失败详情', '无可用诊断', '推荐难度：; 盲区：A']) {
  assert.deepEqual(projectNodeResult({ ...step('diagnose'), output_summary: output }), { kind: 'text', raw: output }, 'unrecognized diagnosis summaries must be shown intact')
}

const explicitNodeOutputs = [
  ['retrieve', '候选 12 条；证据 2 条；状态 available'],
  ['evidence_gate', '门禁通过'],
  ['generate', '已生成文本表示：实操指南'],
  ['review', '普通审核要求修正一处来源范围。'],
  ['claim_extract', '已抽取三条陈述；后续判定另由 claim_judge 记录。'],
  ['claim_judge', '完成三条陈述的独立判定。'],
]
for (const [key, output_summary] of explicitNodeOutputs) {
  assert.deepEqual(projectNodeResult({ ...step(key), output_summary }), { kind: 'text', raw: output_summary }, `${key} must preserve its persisted summary without borrowing another role's data`)
}
assert.deepEqual(projectNodeResult({ ...step('unknown_node'), output_summary: '未知节点原始输出' }), { kind: 'text', raw: '未知节点原始输出' })

const known = ['diagnose', 'retrieve', 'evidence_gate', 'plan', 'generate', 'review', 'claim_extract', 'claim_judge', 'prepare_revision', 'prepare_claim_revision', 'finalize_draft', 'claim_decide', 'finalize', 'finalize_evidence_insufficient']
assert.equal(new Set(known.map(key => iconPaths(key).join('|'))).size, 14)
assert.deepEqual(iconPaths('constructor'), iconPaths('unknown'))
console.log('workflow single-page detail roles, intact result fallbacks and icon coverage checks passed')
