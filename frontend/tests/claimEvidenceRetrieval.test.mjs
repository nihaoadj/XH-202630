// T50 unit coverage: switch payload, gating, presentation and request generations.
import assert from 'node:assert/strict'
import { nextTick, ref } from 'vue'
import { runApi } from '../src/features/runs/queryApi.js'
import {
  planAppendResources, planRegeneratePending, planRetryGeneration,
} from '../src/features/generation/generationCommands.js'
import {
  shouldShowSupplement, supplementReasonLabel, supplementSessionRows,
  supplementStatusLabel, supplementSummaryText,
} from '../src/features/generation/claimEvidenceRetrievalPresentation.js'
import { useGenerationAudit } from '../src/features/generation/useGenerationAudit.js'

import { workflowNodeMeta, canInspectStep } from '../src/features/generation/workflowPresentation.js'
import { detailRole } from '../src/features/generation/workflowDetailPresentation.js'
import { iconPaths } from '../src/features/generation/workflowNodeIcons.js'

for (const [node, title, kind] of [
  ['claim_evidence_retrieve', '知识库补检', 'evidence'],
  ['claim_evidence_rejudge', '缺证重判', 'claims'],
]) {
  assert.equal(workflowNodeMeta({ node_name: node }).title, title)
  assert.equal(canInspectStep({ node_name: node }), true)
  assert.equal(canInspectStep({ agent_name: node }), true)
  assert.equal(detailRole({ node_name: node }).contentKind, kind)
  assert.notDeepEqual(iconPaths(node), iconPaths('unknown'))
  assert.equal(canInspectStep({ node_name: 'future_node', agent_name: node }), false)
}

const job = {
  run_id: 'run-A', learner_id: 'learner-A', batch_id: 'batch-A',
  request_payload: {
    learner_id: 'learner-A', resource_types: ['讲义'],
    include_review: true, include_claim_check: true, include_claim_evidence_retrieval: true,
  },
}
const closed = {
  ...job,
  request_payload: { ...job.request_payload, include_claim_check: false, include_claim_evidence_retrieval: false },
}

// 1. Continuation inherits the switch only while Claim audit stays enabled.
assert.equal(planRetryGeneration(job)[0].data.include_claim_evidence_retrieval, true)
// With Claim audit off the flag is not sent at all; the server normalises it.
assert.equal(
  'include_claim_evidence_retrieval' in planRetryGeneration(closed)[0].data,
  false,
)
assert.equal(
  planRetryGeneration({ ...job, request_payload: { ...job.request_payload, include_claim_evidence_retrieval: undefined } })[0]
    .data.include_claim_evidence_retrieval,
  false,
)

// 2. An explicit value wins; omitting it keeps the key absent; Claim off forces false.
assert.equal(planAppendResources(job, ['讲义'], true, true)[0].data.include_claim_evidence_retrieval, true)
assert.equal(planAppendResources(job, ['讲义'], true, false)[0].data.include_claim_evidence_retrieval, false)
assert.equal('include_claim_evidence_retrieval' in planAppendResources(job, ['讲义'], true, undefined)[0].data, false)
assert.equal(planAppendResources(job, ['讲义'], false, true)[0].data.include_claim_evidence_retrieval, false)
assert.equal(planRegeneratePending(job, ['讲义'], true, true)[0].data.include_claim_evidence_retrieval, true)
assert.equal(
  'include_claim_evidence_retrieval' in planRegeneratePending(job, ['讲义'], true, undefined)[0].data,
  false,
)

// 3. Presentation always separates the first round from the effective round.
assert.equal(supplementStatusLabel('rejudging'), '正在重新核对')
assert.equal(supplementReasonLabel('contradicted'), '新增证据与陈述相反')
assert.equal(supplementReasonLabel(null), '')
assert.equal(shouldShowSupplement(null), false)
assert.equal(shouldShowSupplement({ requested: false, sessions: [] }), false)
assert.equal(shouldShowSupplement({ requested: true }), true)
assert.equal(
  supplementSummaryText({ requested: false, sessions: [{ session_id: 's' }] }),
  '历史任务未开启证据补检，展示首次判定。',
)
const rows = supplementSessionRows({
  sessions: [
    {
      session_id: 'a', resource_version: 1, status: 'completed', active: true,
      hard_block: false, target_claim_total: 2, attempted_claim_total: 2,
      remaining_claim_total: 0, query_total: 3, evidence_scope_ids: ['cevs_1'],
    },
    {
      session_id: 'b', resource_version: 2, status: 'blocked', active: false,
      hard_block: true, reason_code: 'evidence_conflict', target_claim_total: 1,
      attempted_claim_total: 1, remaining_claim_total: 0, query_total: 1,
    },
  ],
})
assert.deepEqual(rows.map(row => [row.roundLabel, row.statusLabel, row.hardBlock]), [
  ['补检后（已生效）', '补检完成并已生效', false],
  ['首次判定（仍生效）', '补检发现反证或来源冲突', true],
])
assert.equal(rows[1].reason, '来源之间存在无法区分的冲突')
assert.deepEqual(supplementSessionRows(null), [])

// 4. A stale response from the previous run never overwrites the new selection.
const calls = []
const previous = {
  timeline: runApi.timeline, claims: runApi.claims,
  claimEvidenceRetrieval: runApi.claimEvidenceRetrieval,
}
for (const kind of ['timeline', 'claims', 'claimEvidenceRetrieval']) {
  runApi[kind] = runId => {
    let resolve, reject
    const promise = new Promise((yes, no) => { resolve = yes; reject = no })
    calls.push({ runId, kind, resolve, reject })
    return promise
  }
}
const latest = (runId, kind) => [...calls].reverse()
  .find(call => call.runId === runId && call.kind === kind)
const settle = async (runId, supplement) => {
  latest(runId, 'timeline').resolve({ data: { run: { run_id: runId }, steps: [], resource_versions: [] } })
  latest(runId, 'claims').resolve({ data: { run_id: runId, claims: [], judgements: [], resource_metrics: {} } })
  latest(runId, 'claimEvidenceRetrieval').resolve({
    data: { run_id: runId, requested: true, sessions: [supplement] },
  })
  await nextTick()
  await new Promise(resolve => setImmediate(resolve))
}

try {
  const selectedRunId = ref('run-A')
  const guard = useGenerationAudit({ selectedRunId, selectedLearnerId: ref('learner-A') })
  guard.visible.value = true
  const first = guard.refresh()
  await nextTick()
  assert.deepEqual(calls.map(call => `${call.runId}:${call.kind}`), [
    'run-A:timeline', 'run-A:claims', 'run-A:claimEvidenceRetrieval',
  ])

  // Switching the run hides the panel and invalidates the pending request.
  selectedRunId.value = 'run-B'
  await nextTick()
  assert.equal(guard.visible.value, false)
  const skipped = guard.refresh()
  await skipped
  assert.equal(calls.length, 3, 'a hidden panel must not fetch')

  guard.visible.value = true
  const second = guard.refresh()
  await nextTick()
  await settle('run-B', { session_id: 'session-B', resource_version: 2, status: 'rejudging' })
  await second
  assert.equal(guard.claimRetrieval.value.sessions[0].session_id, 'session-B')

  // The abandoned A response arrives later and is dropped.
  await settle('run-A', { session_id: 'session-A', resource_version: 1, status: 'completed' })
  await first
  assert.equal(guard.claimRetrieval.value.sessions[0].session_id, 'session-B')

  // Returning to A issues a fresh request whose payload is accepted.
  selectedRunId.value = 'run-A'
  await nextTick()
  guard.visible.value = true
  const third = guard.refresh()
  await nextTick()
  await settle('run-A', { session_id: 'session-A2', resource_version: 1, status: 'completed' })
  await third
  assert.equal(guard.claimRetrieval.value.sessions[0].session_id, 'session-A2')

  // A failed summary never fabricates a passed state.
  const fourth = guard.refresh()
  await nextTick()
  latest('run-A', 'timeline').resolve({ data: { run: { run_id: 'run-A' } } })
  latest('run-A', 'claims').resolve({ data: { run_id: 'run-A' } })
  latest('run-A', 'claimEvidenceRetrieval').reject({ response: { status: 500 } })
  await fourth
  assert.equal(guard.claimRetrieval.value, null)
} finally {
  runApi.timeline = previous.timeline
  runApi.claims = previous.claims
  runApi.claimEvidenceRetrieval = previous.claimEvidenceRetrieval
}

console.log('claimEvidenceRetrieval: PASS')
