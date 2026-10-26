import assert from 'node:assert/strict'
import { ref } from 'vue'
import { api } from '../src/api/client.js'
import { generateApi } from '../src/features/generation/api.js'
import {
  planRetryGeneration, planRegeneratePending, planAppendResources, planRetryResource, executeGenerationPlan,
} from '../src/features/generation/generationCommands.js'
import { useGenerationResources } from '../src/features/generation/useGenerationResources.js'
import { useGenerationCommands } from '../src/features/generation/useGenerationCommands.js'

const job = { learner_id: 'learner-A', run_id: 'run-A', batch_id: 'batch-A',
  request_payload: { learner_id: 'learner-A', resource_types: ['讲义', '复习清单'], constraints: { continuation_instructions: '保留原要求' } } }
const before = structuredClone(job)
assert.deepEqual(planRetryGeneration(job), [{ batchId: 'batch-A', data: {
  learner_id: 'learner-A', resource_types: ['讲义', '复习清单'], instructions: '保留原要求', source_run_id: 'run-A',
} }])
assert.equal(planRetryGeneration({ run_id: 'run' }), null)
assert.equal(planAppendResources(job, [], true), null)
assert.equal(planRetryResource(job, {}), null)
assert.equal(planRegeneratePending(job, [], false), null)
assert.deepEqual(planRegeneratePending(job, ['复习清单', '讲义'], true)[0].data, {
  learner_id: 'learner-A', resource_types: ['复习清单'], source_run_id: 'run-A', replace_existing_types: true,
  instructions: '统一重新生成本任务中未通过审核的资源：复习清单、讲义。',
})
assert.deepEqual(planRegeneratePending(job, ['复习清单', '讲义'], false)[0].data.resource_types, ['复习清单', '讲义'])
assert.deepEqual(planRetryResource({ ...job, batch_id: null }, { resource_type: '讲义' }), [{ batchId: 'run-A', data: {
  learner_id: 'learner-A', resource_types: ['讲义'], source_run_id: 'run-A', replace_existing_types: true,
  instructions: '重新生成本批次的讲义，用新版本替换学习列表中的旧版本。',
} }])
const split = planAppendResources(job, ['复习清单', '讲义', '复习清单'], true)
assert.deepEqual(split.map(item => item.data.resource_types), [['复习清单'], ['讲义']])
assert.deepEqual(planAppendResources(job, ['复习清单', '讲义'], false).map(item => item.data.resource_types), [['复习清单', '讲义']])
assert.deepEqual(job, before)

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = () => new Promise(resolve => setImmediate(resolve))

// Keep the actual Axios adapter and domain wrapper between plans and HTTP data.
const previousAdapter = api.defaults.adapter
const previousWindow = globalThis.window
globalThis.window = { location: { pathname: '/generate', search: '' } }
try {
  const pending = []
  api.defaults.adapter = config => {
    const held = deferred()
    pending.push({ ...held, config, body: JSON.parse(config.data) })
    return held.promise
  }
  const sending = executeGenerationPlan(split, generateApi.continueBatch)
  assert.equal(pending.length, 2)
  assert.ok(pending.every(item => item.config.url === '/resources/batches/batch-A/continuations'))
  assert.deepEqual(pending.map(item => item.body.resource_types), [['复习清单'], ['讲义']])
  function response(index) {
    return { data: JSON.stringify({ run_id: `created-${index}`, learner_id: 'learner-A', batch_id: 'batch-A', topic: '合成', job_status: 'queued' }),
      status: 200, statusText: 'OK', config: pending[index].config, headers: {} }
  }
  pending[1].resolve(response(1)); await tick()
  pending[0].resolve(response(0))
  const responses = await sending
  assert.deepEqual(responses.map(item => item.data.run_id), ['created-0', 'created-1'])
  const failed = executeGenerationPlan(split.slice(0, 1), generateApi.continueBatch)
  pending[2].reject(Object.assign(new Error('synthetic HTTP failure'), { response: { status: 503 } }))
  await assert.rejects(failed, /synthetic HTTP failure/)
} finally { api.defaults.adapter = previousAdapter; globalThis.window = previousWindow }

function harness(overrides = {}) {
  let context = { learnerId: 'A', runId: 'run-A', textRunId: 'run-A', knowledgeBaseId: 'kb-A', sourceBatchId: 'batch-A' }
  let mounted = true
  const errors = [], reads = []
  const loader = useGenerationResources({
    getContext: () => context, isMounted: () => mounted,
    listNodes: async () => ({ data: { nodes: [{ node_id: 'node', tier: 2 }] } }),
    listRunResources: async (learnerId, params) => { reads.push({ learnerId, params }); return { data: { resources: [{ resource_id: learnerId, knowledge_points: ['node'] }] } } },
    listLibraryResources: async () => ({ data: [] }), messages: { error: message => errors.push(message) },
    ...overrides,
  })
  return { loader, errors, reads, setContext: patch => { context = { ...context, ...patch } },
    unmount: () => { mounted = false; loader.invalidateResources(); loader.invalidateNodeTiers() } }
}
{
  const h = harness()
  await h.loader.loadResourcesForSelectedJob()
  assert.deepEqual(h.reads, [{ learnerId: 'A', params: { run_id: 'run-A', page: 1, page_size: 100 } }])
  assert.equal(h.loader.selectedResourceId.value, 'A')
  assert.equal(h.loader.resources.value[0].tier_label, '第 2 阶')
}
{
  const pending = []
  const h = harness({ listRunResources: (learnerId, params) => {
    const held = deferred(); pending.push({ ...held, learnerId, params }); return held.promise
  } })
  const oldA = h.loader.loadResourcesForSelectedJob(); await tick()
  h.setContext({ learnerId: 'B', textRunId: 'run-B', runId: 'run-B', knowledgeBaseId: 'kb-B' })
  const oldB = h.loader.loadResourcesForSelectedJob(); await tick()
  h.setContext({ learnerId: 'A', textRunId: 'run-A', runId: 'run-A', knowledgeBaseId: 'kb-A' })
  const newA = h.loader.loadResourcesForSelectedJob(); await tick()
  pending[2].resolve({ data: { resources: [{ resource_id: 'current-A' }] } }); await newA
  pending[0].reject(new Error('old A failed')); pending[1].resolve({ data: { resources: [{ resource_id: 'old-B' }] } })
  await Promise.all([oldA, oldB])
  assert.equal(h.loader.resources.value[0].resource_id, 'current-A')
  assert.equal(h.loader.selectedResourceId.value, 'current-A')
  assert.equal(h.loader.loadingResources.value, false)
  assert.deepEqual(h.errors, [])
}
{
  const nodes = []
  const h = harness({ listNodes: () => { const held = deferred(); nodes.push(held); return held.promise } })
  const old = h.loader.loadResourcesForSelectedJob()
  h.loader.invalidateResources(); h.loader.invalidateNodeTiers()
  const current = h.loader.loadResourcesForSelectedJob()
  nodes[1].resolve({ data: { nodes: [{ node_id: 'node', tier: 3 }] } }); await current
  nodes[0].resolve({ data: { nodes: [{ node_id: 'node', tier: 1 }] } }); await old
  assert.equal(h.reads.length, 1, 'no old resource request after its node wait became stale')
  assert.equal(h.loader.nodeTiers.value.node, 3)
  assert.equal(h.loader.resources.value[0].tier_label, '第 3 阶')
  const independent = h.loader.loadNodeTiers()
  h.loader.invalidateResources()
  nodes[2].resolve({ data: { nodes: [{ node_id: 'node', tier: 2 }] } }); await independent
  assert.equal(h.loader.nodeTiers.value.node, 2, 'resource invalidation does not cancel independent node requests')
}
{
  const pending = deferred()
  const h = harness({ listRunResources: () => pending.promise })
  const loading = h.loader.loadResourcesForSelectedJob(); await tick()
  h.unmount(); pending.resolve({ data: { resources: [{ resource_id: 'after-unmount' }] } }); await loading
  assert.deepEqual(h.loader.resources.value, [])
  assert.deepEqual(h.errors, [])
}
{
  const h = harness({ listLibraryResources: async () => ({ data: [
    { resource_id: 'same-batch', batch_id: 'batch-A', knowledge_points: ['node'] },
    { resource_id: 'another-batch', batch_id: 'batch-B' },
    { resource_id: 'courseware', batch_id: 'batch-A', resource_kind: 'interactive_courseware' },
  ] }) })
  h.setContext({ runId: 'courseware-run', textRunId: undefined })
  await h.loader.loadCoursewareSourceResources()
  assert.deepEqual(h.loader.resources.value.map(item => item.resource_id), ['same-batch'])
  assert.equal(h.loader.resources.value[0].tier_label, '第 2 阶')
  await h.loader.loadResourcesForSelectedJob()
  assert.deepEqual(h.loader.resources.value, [])
  assert.equal(h.loader.resourcesLoaded.value, true)
}

// Exercise the production command pipeline, not just plans or the shared guard.
const commandKinds = ['retry', 'pending', 'append', 'resource']
function commandHarness({ listGate, streamGate } = {}) {
  const context = ref({ learnerId: 'learner-A', runId: 'run-A' })
  const pending = []
  const ui = { run: 'run-A', persisted: 'run-A', resources: ['source-A'], dialog: true,
    notices: [], streams: [], listWrites: 0, stops: 0 }
  const coordinator = useGenerationCommands({
    getContext: () => ({ ...context.value }),
    selectRun: runId => { context.value.runId = runId; ui.run = runId },
    refreshJobs: async isCurrent => {
      const ok = listGate ? await listGate.promise : true
      if (!isCurrent() || !ok) return false
      ui.listWrites += 1
      ui.persisted = context.value.runId
      return true
    },
    startRealtime: async runId => {
      ui.streams.push(runId)
      if (streamGate) await streamGate.promise
    },
  })
  api.defaults.adapter = config => {
    const held = deferred()
    const body = JSON.parse(config.data)
    const index = pending.length
    pending.push({ ...held, body, config,
      succeed: () => held.resolve({ data: JSON.stringify({ run_id: `created-${index}`, learner_id: body.learner_id,
        batch_id: 'batch-A', topic: '合成', job_status: 'queued' }),
      status: 200, statusText: 'OK', config, headers: {} }),
      fail: () => held.reject(Object.assign(new Error('command failed'), { response: { status: 503 } })),
    })
    return held.promise
  }
  const busy = kind => kind === 'append' ? coordinator.appendingResources.value
    : kind === 'resource' ? coordinator.retryingResourceKey.value : coordinator.retrying.value
  function start(kind, { claim = false, key = 'spec-A:text' } = {}) {
    const source = { ...job, learner_id: context.value.learnerId, run_id: context.value.runId }
    const plan = kind === 'retry' ? planRetryGeneration(source)
      : kind === 'pending' ? planRegeneratePending(source, ['复习清单', '讲义'], claim)
        : kind === 'append' ? planAppendResources(source, ['复习清单', '讲义', '复习清单'], claim)
          : planRetryResource(source, { resource_type: '讲义' })
    const command = {
      channel: kind === 'pending' ? 'retry' : kind,
      busyValue: kind === 'resource' ? key : '',
      execute: () => executeGenerationPlan(plan, generateApi.continueBatch),
      succeeded: () => { if (kind === 'append') ui.dialog = false; ui.notices.push(`success:${kind}`) },
      failed: () => ui.notices.push(`error:${kind}`),
    }
    if (kind === 'retry') command.beforeSubmit = () => { ui.resources = []; ui.stops += 1 }
    else command.accepted = runId => { ui.persisted = runId; ui.resources = [] }
    return { done: coordinator.run(command), plan }
  }
  function switchContext(learnerId, runId) {
    context.value.learnerId = learnerId
    context.value.runId = runId
    ui.run = runId
    ui.persisted = runId
    ui.resources = [`source:${learnerId}:${runId}`]
  }
  const snapshot = () => structuredClone({ ...ui, retrying: coordinator.retrying.value,
    appendBusy: coordinator.appendingResources.value, key: coordinator.retryingResourceKey.value })
  return { coordinator, context, pending, ui, busy, start, switchContext, snapshot }
}

globalThis.window = { location: { pathname: '/generate', search: '' } }
try {
  for (const kind of commandKinds) for (const claim of [false, true]) {
    const h = commandHarness()
    const { done, plan } = h.start(kind, { claim })
    assert.ok(h.busy(kind), `${kind}: busy starts before POST`)
    assert.deepEqual(h.pending.map(item => item.body), plan.map(item => item.data))
    assert.ok(h.pending.every(item => item.config.url === '/resources/batches/batch-A/continuations'))
    const count = h.pending.length
    assert.equal(await h.start(kind, { claim }).done, false, `${kind}: same busy action cannot duplicate POST`)
    assert.equal(h.pending.length, count)
    for (const item of [...h.pending].reverse()) { item.succeed(); await tick() }
    assert.equal(await done, true, `${kind}: own child adoption must survive synchronous watch`)
    assert.equal(h.ui.run, 'created-0', 'Promise.all preserves the first planned response despite reverse completion')
    assert.equal(h.ui.persisted, 'created-0')
    assert.deepEqual(h.ui.resources, [])
    assert.deepEqual(h.ui.streams, ['created-0'])
    assert.deepEqual(h.ui.notices, [`success:${kind}`])
    assert.equal(h.ui.listWrites, 1)
    assert.equal(Boolean(h.busy(kind)), false)
    assert.equal(h.ui.dialog, kind !== 'append')
    h.coordinator.dispose()
  }
  for (const kind of commandKinds) {
    const h = commandHarness()
    const { done } = h.start(kind)
    h.pending[0].fail()
    assert.equal(await done, false)
    assert.deepEqual(h.ui.notices, [`error:${kind}`], 'current failure remains visible and releases its busy state')
    assert.equal(Boolean(h.busy(kind)), false)
    assert.equal(h.ui.persisted, 'run-A')
    assert.deepEqual(h.ui.streams, [])
    h.coordinator.dispose()
  }
  for (const kind of commandKinds) for (const transition of ['run', 'learner', 'ABA', 'unmount']) {
    for (const outcome of ['succeed', 'fail']) {
      const h = commandHarness()
      const { done } = h.start(kind)
      if (transition === 'unmount') h.coordinator.dispose()
      else if (transition === 'learner') h.switchContext('learner-B', 'run-B')
      else {
        h.switchContext('learner-A', 'run-B')
        if (transition === 'ABA') h.switchContext('learner-A', 'run-A')
      }
      assert.equal(Boolean(h.busy(kind)), false, 'context switch synchronously releases old busy')
      const beforeCompletion = h.snapshot()
      h.pending[0][outcome]()
      assert.equal(await done, false)
      assert.deepEqual(h.snapshot(), beforeCompletion, `${kind}/${transition}/${outcome}: no late UI effect`)
      assert.equal(h.pending.length, 1, 'context invalidation does not submit or cancel server tasks')
      h.coordinator.dispose()
    }
  }
  for (const kind of commandKinds) for (const outcome of ['succeed', 'fail']) {
    const h = commandHarness()
    const old = h.start(kind)
    h.switchContext('learner-A', 'run-B')
    const current = h.start(kind, { key: 'spec-B:text' })
    const busyBefore = h.busy(kind)
    h.pending[0][outcome]()
    await old.done
    assert.equal(h.busy(kind), busyBefore, `${kind}: old finally must not clear current owner`)
    assert.ok(h.busy(kind))
    assert.deepEqual(h.ui.notices, [])
    h.pending[1].succeed()
    assert.equal(await current.done, true)
    assert.equal(h.ui.run, 'created-1')
    assert.deepEqual(h.ui.notices, [`success:${kind}`])
    h.coordinator.dispose()
  }
  {
    const h = commandHarness()
    const first = h.start('resource')
    const second = h.start('resource', { key: 'spec-B:text' })
    h.pending[0].succeed(); await first.done
    assert.equal(h.coordinator.retryingResourceKey.value, 'spec-B:text', 'a different resource owns the shared busy key')
    assert.deepEqual(h.ui.notices, [])
    h.pending[1].succeed(); assert.equal(await second.done, true)
    h.coordinator.dispose()
  }
  {
    const h = commandHarness()
    const retry = h.start('retry'), append = h.start('append'), resource = h.start('resource')
    assert.equal(h.pending.length, 3, 'independent busy channels do not block each other')
    h.pending[0].fail(); await retry.done
    assert.ok(h.coordinator.appendingResources.value)
    assert.ok(h.coordinator.retryingResourceKey.value)
    h.pending[1].succeed(); assert.equal(await append.done, true)
    h.pending[2].succeed(); assert.equal(await resource.done, false, 'adopting a child invalidates other source-run commands')
    assert.deepEqual(h.ui.notices, ['error:retry', 'success:append'])
    assert.deepEqual(h.ui.streams, ['created-1'])
    h.coordinator.dispose()
  }
  for (const kind of commandKinds) for (const outcome of ['succeed', 'fail']) {
    const listGate = deferred(), h = commandHarness({ listGate })
    const { done } = h.start(kind)
    h.pending[0].succeed(); await tick()
    assert.equal(h.ui.run, 'created-0', 'POST was applied before holding the list refresh')
    h.switchContext('learner-A', 'run-B')
    const beforeCompletion = h.snapshot()
    if (outcome === 'succeed') listGate.resolve(true)
    else listGate.reject(new Error('old list failure'))
    assert.equal(await done, false)
    assert.deepEqual(h.snapshot(), beforeCompletion, `${kind}: list ${outcome} after switch has no effect`)
    h.coordinator.dispose()
  }
  for (const kind of commandKinds) {
    const listGate = deferred(), h = commandHarness({ listGate })
    const { done } = h.start(kind)
    h.pending[0].succeed(); await tick(); listGate.resolve(false)
    assert.equal(await done, false, 'a false list result cannot become command success')
    assert.deepEqual(h.ui.streams, [])
    assert.deepEqual(h.ui.notices, [])
    assert.equal(h.ui.dialog, true, 'failed refresh cannot close the append dialog')
    assert.equal(Boolean(h.busy(kind)), false)
    h.coordinator.dispose()
  }
  for (const outcome of ['resolve', 'reject']) {
    const streamGate = deferred(), h = commandHarness({ streamGate })
    const { done } = h.start('append')
    h.pending[0].succeed(); await tick()
    assert.deepEqual(h.ui.streams, ['created-0'])
    h.switchContext('learner-A', 'run-B')
    const current = h.start('append')
    streamGate[outcome](outcome === 'reject' ? new Error('old stream failed') : undefined)
    await done
    assert.equal(h.coordinator.appendingResources.value, true, 'subscription completion cannot release a newer command')
    assert.deepEqual(h.ui.notices, [])
    h.pending[1].fail(); await current.done
    h.coordinator.dispose()
  }
  {
    const h = commandHarness()
    h.coordinator.dispose()
    assert.equal(await h.start('append').done, false)
    assert.equal(h.pending.length, 0, 'disposed coordinator cannot submit')
  }
} finally { api.defaults.adapter = previousAdapter; globalThis.window = previousWindow }
console.log('Generation plans, Axios ordering, resource races and production command context/ownership matrix passed')
