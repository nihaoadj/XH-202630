import assert from 'node:assert/strict'
import { buildFeedbackBatchPresentation } from '../src/features/feedback/batchPresentation.js'

const names = new Map([['parse', '文档解析'], ['embed', '向量表示']])
function present(resources, jobs = [], nodeNames = names, status = '待反馈') {
  return buildFeedbackBatchPresentation({
    resources, jobsByRunId: new Map(jobs.map(job => [job.run_id, job])), nodeNames,
    batchLabel: '资源批次 02', finishedAt: '', status,
  })
}

const job = {
  run_id: 'run-1',
  request_payload: { constraints: { target_skill_node_ids: ['parse', 'embed', 'parse'] }, target_skill_nodes: ['ignored'] },
  focus_snapshot: { adopted_node_ids: ['also-ignored'] },
}
const combined = present([{ run_id: 'run-1' }, { run_id: 'run-1' }], [job])
assert.equal(combined.nodeTitle, '文档解析、向量表示')
assert.equal(combined.batchMeta, '资源批次 02 ｜ 2 份资源 ｜ -')
assert.equal(combined.label, '文档解析、向量表示 ｜ 资源批次 02 ｜ 2 份资源 ｜ - ｜ 待反馈')
assert.equal(present([{ run_id: 'run-1' }], [{ run_id: 'run-1', request_payload: { target_skill_nodes: ['parse'] } }]).nodeTitle, '文档解析')
assert.equal(present([{ run_id: 'run-1' }], [{ run_id: 'run-1', focus_snapshot: { adopted_node_ids: ['embed'] } }]).nodeTitle, '向量表示')
assert.equal(present([{ learning_path_node: 'parse', knowledge_points: ['embed'] }]).nodeTitle, '文档解析')
assert.equal(present([{ knowledge_points: ['parse', '正文关键词', 'embed'] }]).nodeTitle, '文档解析、向量表示')
assert.equal(present([{ run_id: 'run-1' }], [job], new Map()).nodeTitle, 'parse、embed')
assert.equal(present([{}]).label, '资源批次 02 ｜ 1 份资源 ｜ - ｜ 待反馈')
assert.equal(present([{}], [], names, '待纠错测评').status, '待纠错测评')
assert.ok(present([{}], [], names, '已反馈').label.endsWith(' ｜ 已反馈'))
console.log('PASS feedback batch presentation: targets, fallbacks, deduplication and status')
