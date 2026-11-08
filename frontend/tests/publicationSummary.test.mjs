// Publication summary: contract guards, presentation mapping and refresh races.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ref } from 'vue'

import { api } from '../src/api/client.js'
import {
  ContractResponseError, isPublishSummary, requireJobListResponse, requireJobResponse,
  requireRunSummaryResponse, requireRunTimelineResponse,
} from '../src/contracts/guards.js'
import { generateApi } from '../src/features/generation/api.js'
import { runApi } from '../src/features/runs/queryApi.js'
import { resourceApi } from '../src/features/learning-documents/api.js'
import {
  readableResourceId, resolveDeliveryCount, resolvePublicationView, selectReadableResource,
} from '../src/features/generation/publicationPresentation.js'
import { buildResourceStatusItems } from '../src/features/generation/resourceStatusPresentation.js'
import { useGenerationClaims } from '../src/features/generation/useGenerationClaims.js'
import { useGenerationResources } from '../src/features/generation/useGenerationResources.js'

const testRoot = path.dirname(fileURLToPath(import.meta.url))
const fixtures = JSON.parse(readFileSync(path.join(testRoot, '../src/contracts/generated/schema.json'), 'utf8'))
const jobFixture = fixtures.properties?.GenerationJobStatusResponse
  ? fixtures.properties.GenerationJobStatusResponse
  : null
void jobFixture

const originalAdapter = api.defaults.adapter
function respond(data, status = 200) {
  api.defaults.adapter = async config => ({
    data: typeof data === 'string' ? data : JSON.stringify(data), status, statusText: String(status),
    config, headers: { 'content-type': 'application/json' },
  })
}

const COMPLETE = Object.freeze({
  schema_version: '1.0', total: 3, published: 2, unpublished: 1, pending_review: 0,
  completeness: 'complete', incomplete_reasons: [],
})
const JOB = Object.freeze({
  run_id: 'run_fixture', learner_id: 'learner_fixture', topic: 'T47', job_status: 'completed',
  resource_ids: [], resource_progress_summary: { total: 3, published: 2 }, request_payload: {},
})

try {
  // --- guard: legacy payloads stay valid -----------------------------------
  assert.equal(isPublishSummary(undefined), true)
  assert.equal(isPublishSummary(null), true)
  const legacyJob = { ...JOB }
  delete legacyJob.publish_summary
  respond(legacyJob)
  assert.equal((await generateApi.getJobStatus('run_fixture')).data.run_id, 'run_fixture')

  // --- guard: valid complete and partial objects ---------------------------
  assert.equal(isPublishSummary(COMPLETE), true)
  assert.equal(isPublishSummary({ completeness: 'partial', total: 3, published: null, pending_review: null }), true)

  // --- guard: rejects impossible or unknown shapes -------------------------
  const invalid = [
    { ...COMPLETE, published: 3, unpublished: 1 },
    { ...COMPLETE, published: -1, unpublished: 4 },
    { ...COMPLETE, total: 3.5 },
    { ...COMPLETE, published: Number.NaN },
    { ...COMPLETE, unpublished: Number.POSITIVE_INFINITY },
    { ...COMPLETE, schema_version: '2.0' },
    { ...COMPLETE, completeness: 'unknown' },
    { ...COMPLETE, incomplete_reasons: ['made_up'] },
    { ...COMPLETE, incomplete_reasons: ['request_missing'] },
    { ...COMPLETE, pending_review: 2 },
    { ...COMPLETE, published: '2' },
  ]
  for (const value of invalid) {
    assert.equal(isPublishSummary(value), false, `must reject ${JSON.stringify(value)}`)
  }
  // A null counter is never coerced into zero.
  assert.equal(isPublishSummary({ ...COMPLETE, published: null, unpublished: 3 }), false)

  for (const value of invalid) {
    respond({ ...JOB, publish_summary: value })
    await assert.rejects(generateApi.getJobStatus('run_fixture'), { code: 'INVALID_API_RESPONSE' })
  }
  respond({ ...JOB, publish_summary: null })
  assert.equal((await generateApi.getJobStatus('run_fixture')).data.publish_summary, null)
  respond({ ...JOB, publish_summary: COMPLETE })
  assert.equal((await generateApi.getJobStatus('run_fixture')).data.publish_summary.published, 2)

  // --- list, run summary and timeline guards -------------------------------
  respond({ learner_id: 'learner_fixture', total: 1, items: [{ ...JOB, publish_summary: COMPLETE }] })
  assert.equal((await generateApi.listJobs('learner_fixture')).data.items.length, 1)
  respond({ learner_id: 'learner_fixture', total: 1, items: [{ ...JOB, publish_summary: { ...COMPLETE, total: 9 } }] })
  await assert.rejects(generateApi.listJobs('learner_fixture'), { code: 'INVALID_API_RESPONSE' })
  respond({ learner_id: 'learner_fixture', total: 1, items: [JOB] })
  assert.equal((await generateApi.listJobs('learner_fixture')).data.items.length, 1)

  const runSummary = {
    run_id: 'run_fixture', status: 'completed', updated_at: '2026-11-07T09:30:00Z',
    replay_completeness: 'complete', publish_summary: COMPLETE,
  }
  respond(runSummary)
  assert.equal((await runApi.get('run_fixture')).data.publish_summary.published, 2)
  const legacyRun = { ...runSummary }
  delete legacyRun.publish_summary
  respond(legacyRun)
  assert.equal((await runApi.get('run_fixture')).data.run_id, 'run_fixture')
  respond({ ...runSummary, publish_summary: { completeness: 'complete', total: 3 } })
  await assert.rejects(runApi.get('run_fixture'), { code: 'INVALID_API_RESPONSE' })

  respond({ run: runSummary, steps: [], events: [], resource_versions: [] })
  assert.equal((await runApi.timeline('run_fixture', { limit: 1 })).data.run.publish_summary.total, 3)
  respond({ run: { ...runSummary, publish_summary: { ...COMPLETE, pending_review: 5 } }, steps: [], events: [] })
  await assert.rejects(runApi.timeline('run_fixture'), { code: 'INVALID_API_RESPONSE' })
  respond({ event: 'not-a-timeline' })
  await assert.rejects(runApi.timeline('run_fixture'), { code: 'INVALID_API_RESPONSE' })

  // --- guard helpers are the same ones the wrappers use --------------------
  assert.throws(() => requireJobResponse({ data: { ...JOB, publish_summary: { total: -1 } } }), ContractResponseError)
  assert.throws(() => requireJobListResponse({ data: { items: 'nope' } }), ContractResponseError)
  assert.throws(() => requireRunSummaryResponse({ data: { run_id: 'r', status: 'not-a-status' } }), ContractResponseError)
  assert.throws(() => requireRunTimelineResponse({ data: { run: runSummary, events: 'nope' } }), ContractResponseError)
} finally {
  api.defaults.adapter = originalAdapter
}

// --- presentation mapping --------------------------------------------------
assert.deepEqual(
  Object.keys(resolvePublicationView({ publishSummary: null })).sort(),
  ['completeness', 'hasSummary', 'label', 'published', 'tone', 'total'],
)
assert.equal(resolvePublicationView({ publishSummary: null, fallbackPublished: 2, fallbackTotal: 3 }).label, '')
assert.equal(
  resolvePublicationView({ publishSummary: COMPLETE, jobStatus: 'running' }).label,
  '生成中，已发布 2/3',
)
assert.equal(
  resolvePublicationView({ publishSummary: COMPLETE, jobStatus: 'failed' }).label,
  '部分已发布（2/3）',
)
assert.equal(resolvePublicationView({ publishSummary: COMPLETE, jobStatus: 'failed' }).tone, 'warning')
assert.equal(
  resolvePublicationView({ publishSummary: { ...COMPLETE, published: 3, unpublished: 0 } }).label,
  '已发布 3/3',
)
assert.equal(
  resolvePublicationView({ publishSummary: { ...COMPLETE, published: 0, unpublished: 3 } }).label,
  '任务已结束，暂无已发布资源',
)
assert.equal(
  resolvePublicationView({ publishSummary: { ...COMPLETE, total: 1, published: 0, unpublished: 1 } }).label,
  '任务已结束，暂无已发布资源',
)
const partial = resolvePublicationView({
  publishSummary: { completeness: 'partial', total: 3, published: 2, unpublished: null, pending_review: null },
  jobStatus: 'completed',
})
assert.equal(partial.label, '已确认 2 份已发布，汇总不完整')
assert.equal(partial.tone, 'warning')
for (const jobStatus of ['running', 'queued']) {
  const runningPartial = resolvePublicationView({
    publishSummary: { completeness: 'partial', total: 3, published: 1 }, jobStatus,
  })
  assert.equal(runningPartial.label, '生成中，已确认 1 份已发布，汇总不完整')
  assert.equal(runningPartial.tone, 'warning')
  assert.equal(resolvePublicationView({
    publishSummary: { completeness: 'unavailable', published: null }, jobStatus,
  }).label, '生成中，发布情况暂不可用')
}
assert.equal(
  resolvePublicationView({ publishSummary: { completeness: 'unavailable' }, jobStatus: 'completed' }).label,
  '发布情况暂不可用',
)
assert.equal(
  resolvePublicationView({ publishSummary: { completeness: 'partial', published: 0 } }).label,
  '发布情况暂不可用',
)
assert.deepEqual(
  resolveDeliveryCount({ publishSummary: { completeness: 'partial', published: null, total: 3 } }),
  { published: null, total: 3, hasSummary: true },
)
assert.deepEqual(
  resolveDeliveryCount({ publishSummary: null, fallbackPublished: 2, fallbackTotal: 3 }),
  { published: 2, total: 3, hasSummary: false },
)

// --- readable version selection -------------------------------------------
const resources = [
  { resource_id: 'res-old', resource_spec_id: 'spec-a', publication_status: 'published', version: 1, run_id: 'run-a', representation: 'text' },
  { resource_id: 'res-aaa', resource_spec_id: 'spec-a', publication_status: 'published', version: 1, run_id: 'run-a', representation: 'text' },
  { resource_id: 'res-new', resource_spec_id: 'spec-a', publication_status: 'unpublished', version: 3, run_id: 'run-a', representation: 'text' },
  { resource_id: 'res-other-run', resource_spec_id: 'spec-a', publication_status: 'published', version: 9, run_id: 'run-b', representation: 'text' },
  { resource_id: 'res-sibling', resource_spec_id: 'spec-b', publication_status: 'published', version: 4, run_id: 'run-a', representation: 'text' },
]
assert.equal(
  selectReadableResource(resources, { runId: 'run-a', resourceId: 'res-new', resourceSpecId: 'spec-a' }).resource_id,
  'res-aaa',
)
assert.equal(selectReadableResource(resources, { runId: 'run-a', resourceSpecId: 'spec-b' }).resource_id, 'res-sibling')
assert.equal(selectReadableResource(resources, { runId: 'run-a', resourceSpecId: 'spec-missing' }), null)
assert.equal(
  readableResourceId(
    { resource_id: 'res-new', resource_spec_id: 'spec-a', publication_status: 'unpublished' },
    { resources, runId: 'run-a' },
  ),
  'res-aaa',
)
assert.equal(
  readableResourceId({ resource_id: 'res-sibling', publication_status: 'published' }, { resources, runId: 'run-a' }),
  'res-sibling',
)
assert.equal(readableResourceId({}, { resources, runId: 'run-a' }), '')
const parentLinked = [
  { resource_id: 'parent', resource_spec_id: 'spec-a', run_id: 'run-a', version: 1, publication_status: 'unpublished' },
  { resource_id: 'child', parent_resource_id: 'parent', run_id: 'run-a', version: 2, publication_status: 'published' },
]
const parentTarget = { resource_id: 'parent', resource_spec_id: 'spec-a', publication_status: 'unpublished' }
assert.equal(readableResourceId(parentTarget, { resources: parentLinked, runId: 'run-a' }), 'child')
assert.equal(readableResourceId(parentTarget, { resources: parentLinked.slice(1), runId: 'run-a' }), 'child', 'the current attempt anchor need not be in a published-only page')
assert.equal(readableResourceId(parentTarget, { resources: [
  ...parentLinked, { resource_id: 'grandchild', parent_resource_id: 'child', version: 3, run_id: 'run-a', publication_status: 'published' },
], runId: 'run-a' }), 'grandchild')
for (const extra of [
  { run_id: 'run-b' }, { resource_spec_id: 'spec-b' }, { parent_resource_id: 'child' },
]) {
  assert.equal(readableResourceId(parentTarget, {
    resources: [parentLinked[0], { ...parentLinked[1], ...extra }], runId: 'run-a',
  }), '', 'cross-run, conflicting spec and cyclic ancestry must not qualify')
}
for (const extra of [{ run_id: 'run-b' }, { resource_spec_id: 'spec-b' }]) {
  assert.equal(readableResourceId(parentTarget, {
    resources: [{ ...parentLinked[0], ...extra }, parentLinked[1]], runId: 'run-a',
  }), '', 'a present conflicting parent cannot be treated as a missing trusted anchor')
}

// --- status items keep the exact attempt id separate ----------------------
const statusItems = buildResourceStatusItems([
  {
    resource_id: 'res-new', resource_spec_id: 'spec-a', resource_type: '讲义', representation: 'text',
    resource_execution_state: 'human_review', publication_status: 'unpublished',
    claim_publish_decision_pending: true, display_order: 1,
  },
], { resources, runId: 'run-a', jobStatus: 'completed' })
assert.equal(statusItems[0].resource_id, 'res-new', 'the current attempt id still drives Claim/retry')
assert.equal(statusItems[0].readable_resource_id, 'res-aaa', 'reading opens the published version')

// --- Claim decision races --------------------------------------------------
const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const runId = ref('run-a')
const learnerId = ref('learner-a')
const claimReports = ref({})
const claimReportVisible = ref(false)
const selectedClaimReportId = ref('res-new')
const claimDecisionLoading = ref(false)
const refreshCalls = []
const messages = { success: [], error: [] }
let reportVersion = 0
const { decideClaimPublication, loadClaimReports } = useGenerationClaims({
  selectedRunId: runId, selectedLearnerId: learnerId, timelineState: ref({ resourceExecutions: [] }),
  resources: ref([]), claimReports, selectedClaimReportId, claimReportVisible, claimDecisionLoading,
  isMounted: () => true,
  requestVersion: () => reportVersion,
  nextRequestVersion: () => { reportVersion += 1; return reportVersion },
  refreshStatus: options => { refreshCalls.push(options) },
  messages: { success: text => messages.success.push(text), error: text => messages.error.push(text) },
})
assert.ok(typeof loadClaimReports === 'function')
assert.ok(typeof decideClaimPublication === 'function')

const originalDecide = resourceApi.decideClaimPublication
const originalClaims = runApi.claims
const originalTimeline = runApi.timeline
try {
  runApi.claims = async () => ({ data: { run_id: runId.value, resource_metrics: {} } })
  runApi.timeline = async () => ({ data: { run: { run_id: runId.value }, events: [], resource_metrics: {} } })

  // Switched context must be able to submit again immediately.
  const firstRequest = deferred()
  resourceApi.decideClaimPublication = () => firstRequest.promise
  selectedClaimReportId.value = 'res-new'
  const first = decideClaimPublication(true)
  assert.equal(claimDecisionLoading.value, true)

  runId.value = 'run-b'
  selectedClaimReportId.value = 'res-new'
  assert.equal(claimDecisionLoading.value, false, 'switching resets the in-flight decision state')

  const secondRequest = deferred()
  let secondSubmitted = 0
  resourceApi.decideClaimPublication = () => { secondSubmitted += 1; return secondRequest.promise }
  const second = decideClaimPublication(true)
  assert.equal(secondSubmitted, 1, 'a new run can submit a decision')
  assert.equal(claimDecisionLoading.value, true)

  // The stale request resolving later must not clear the new loading flag.
  firstRequest.resolve({ data: { resource: { resource_id: 'res-new' } } })
  await first
  assert.equal(claimDecisionLoading.value, true, 'the old finally cannot clear the newer loading')
  assert.equal(messages.success.length, 0, 'a stale success is not reported for the new run')

  secondRequest.resolve({ data: { resource: { resource_id: 'res-new' } } })
  await second
  assert.equal(claimDecisionLoading.value, false)
  assert.deepEqual(messages.success, ['资源已发布。'])
  assert.deepEqual(refreshCalls, [{ forceResources: true, forceClaims: true }])

  // A rejection keeps the loading flag for the retryable context only.
  runId.value = 'run-c'
  selectedClaimReportId.value = 'res-new'
  const failing = deferred()
  resourceApi.decideClaimPublication = () => failing.promise
  const failure = decideClaimPublication(false)
  failing.reject({ response: { data: { detail: '该资源当前不处于待用户决策状态' } } })
  await failure
  assert.equal(claimDecisionLoading.value, false)
  assert.deepEqual(messages.error, ['该资源当前不处于待用户决策状态'])
  assert.equal(refreshCalls.length, 1, 'a rejected decision must not refresh publication facts')
} finally {
  resourceApi.decideClaimPublication = originalDecide
  runApi.claims = originalClaims
  runApi.timeline = originalTimeline
}

// --- a failed later page retains readable results without crossing contexts --
let pageCalls = 0
let selectedRun = 'run-pages'
const pageNotices = []
const firstPage = Array.from({ length: 100 }, (_, index) => ({
  resource_id: `page-${index}`, run_id: selectedRun, knowledge_points: [],
}))
let reader = async () => {
  pageCalls += 1
  if (pageCalls === 2) throw new Error('expected second-page failure')
  return { data: { total: 101, has_next: true, resources: firstPage } }
}
const resourceHook = useGenerationResources({
  getContext: () => ({ learnerId: 'learner-pages', textRunId: selectedRun, knowledgeBaseId: '' }),
  isMounted: () => true, listNodes: async () => ({ data: [] }),
  listRunResources: (...args) => reader(...args), listLibraryResources: async () => ({ data: [] }),
  messages: { warning: text => pageNotices.push(text), error: text => pageNotices.push(text) },
})
const originalConsoleError = console.error
const expectedErrors = []
console.error = error => expectedErrors.push(error.message)
try {
  await resourceHook.loadResourcesForSelectedJob()
  assert.equal(pageCalls, 2)
  assert.equal(resourceHook.resources.value.length, 100)
  assert.equal(resourceHook.resourcesLoaded.value, true)
  assert.equal(resourceHook.selectedResourceId.value, 'page-0')
  assert.ok(pageNotices.some(text => text.includes('已加载部分')))
  reader = async () => { throw new Error('expected first-page failure') }
  await resourceHook.loadResourcesForSelectedJob()
  assert.equal(resourceHook.resources.value.length, 100, 'a failed first page does not erase the last readable result')

  const secondPage = deferred()
  const secondStarted = deferred()
  let oldPages = 0
  reader = async (_, params) => {
    if (params.run_id === 'run-new') return { data: { resources: [{ resource_id: 'new-only', run_id: 'run-new' }], total: 1, has_next: false } }
    oldPages += 1
    if (oldPages === 1) return { data: { resources: firstPage, total: 101, has_next: true } }
    secondStarted.resolve()
    return secondPage.promise
  }
  const oldRead = resourceHook.loadResourcesForSelectedJob()
  await secondStarted.promise
  selectedRun = 'run-new'
  resourceHook.invalidateResources()
  await resourceHook.loadResourcesForSelectedJob()
  secondPage.reject(new Error('stale page failure'))
  await oldRead
  assert.deepEqual(resourceHook.resources.value.map(item => item.resource_id), ['new-only'])
  assert.deepEqual(expectedErrors, ['expected second-page failure', 'expected first-page failure'])
} finally {
  console.error = originalConsoleError
}

console.log('publicationSummary: PASS')
