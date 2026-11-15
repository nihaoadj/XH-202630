import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { createRenderer, nextTick, reactive, ref } from 'vue'
import { defaultRoundMember, primaryRoundRun, resolveRoundSelection } from '../src/features/generation/roundWorkspace.js'
import { buildRoundSubmission, readRoundDraft, requireRoundSession, roundDraftKey } from '../src/features/feedback/roundEvaluationState.js'
import { useRoundEvaluation } from '../src/features/feedback/useRoundEvaluation.js'
import { useLearningRoundWorkspace } from '../src/features/generation/useLearningRoundWorkspace.js'

const checks = []
function check(name, callback) { return Promise.resolve().then(callback).then(() => checks.push(name)) }
const detail = {
  round_id: 'round', learner_id: 'learner', protocol_version: 'learning-round/v1',
  members: [{ member_id: 'a', node_id: 'node-a', node_name: 'A', role: 'primary', state: 'completed' },
    { member_id: 'b', node_id: 'node-b', node_name: 'B', role: 'review', state: 'completed' }],
  stages: [{ stage_id: 'initial', kind: 'initial', ordinal: 0, members: [{ member_id: 'a', job_ids: ['run-a'] }, { member_id: 'b', job_ids: ['run-b'] }] },
    { stage_id: 'correct', kind: 'correction', ordinal: 1, members: [{ member_id: 'a', job_ids: ['run-a-c1', 'run-a-c2'] }, { member_id: 'b', job_ids: ['run-b-c1', 'run-b-c2'] }] }],
}
const session = {
  session_id: 'session', round_id: 'round', stage_id: 'initial', manifest_hash: 'a'.repeat(64),
  groups: [{ member_id: 'a', node_id: 'node-a', role: 'primary', questions: [{ question_id: 'qa', question_type: 'single_choice' }] },
    { member_id: 'b', node_id: 'node-b', role: 'review', questions: [{ question_id: 'qb', question_type: 'multiple_choice' }] }],
}
const result = { round_id: 'round', stage_id: 'initial', session_id: 'session', attempt_id: 'attempt', profile_version: 2, primary_path_action: 'advance', nodes: [{ member_id: 'a', role: 'primary', node_id: 'node-a', score: .9 }, { member_id: 'b', role: 'review', node_id: 'node-b', score: .5 }] }

const renderer = createRenderer({
  createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: () => ({}),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text },
  insert: (node, parent) => { parent.children.push(node); node.parent = parent }, remove: () => {},
  parentNode: node => node.parent, nextSibling: () => null, patchProp: () => {},
})
function mount(factory) {
  let state
  const app = renderer.createApp({ setup() { state = factory(); return () => null } })
  app.mount({ children: [] })
  return { state, close: () => app.unmount() }
}
async function withTimers(callback) {
  const originalSet = globalThis.setTimeout; const originalClear = globalThis.clearTimeout
  const timers = new Map()
  let nextId = 0
  globalThis.setTimeout = (handler, delay) => { const id = ++nextId; timers.set(id, { handler, delay }); return id }
  globalThis.clearTimeout = id => timers.delete(id)
  try {
    await callback({
      count: () => timers.size,
      async tick() {
        assert.equal(timers.size, 1)
        const [id, timer] = timers.entries().next().value
        timers.delete(id)
        await timer.handler()
      },
    })
  } finally { globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear }
}

await check('normal default is primary; legacy defaults by unique stable member identity', () => {
  assert.equal(defaultRoundMember(detail).member_id, 'a')
  const legacy = { ...detail, members: [...detail.members].reverse().map(member => ({ ...member, role: 'legacy' })) }
  assert.equal(defaultRoundMember(legacy).member_id, 'a')
  assert.equal(resolveRoundSelection(legacy, { memberId: 'b', stageId: 'correct', runId: 'run-b-c2' }).runId, 'run-b-c2')
  assert.equal(primaryRoundRun(legacy), '')
})
await check('cross-member run is rejected and correction stage stays member-scoped', () => {
  assert.equal(resolveRoundSelection(detail, { memberId: 'b', stageId: 'correct', runId: 'run-a-c1' }).runId, 'run-b-c1')
  assert.equal(primaryRoundRun(detail), 'run-a')
})
await check('one missing node answer cannot create a joint submission', () => {
  assert.throws(() => buildRoundSubmission({ session, answers: { qa: 'A' }, learnerId: 'learner', profileVersion: 1, key: 'stable-key', submittedAt: '2026-11-07T00:00:00Z' }), /全部节点/)
})
await check('Vue reactive multiple-choice answers are safely copied and remain node independent', () => {
  const answers = reactive({ qa: 'A', qb: ['B', 'C'] })
  const payload = buildRoundSubmission({ session, answers, learnerId: 'learner', profileVersion: 1, key: 'stable-key', submittedAt: '2026-11-07T00:00:00Z', reflection: reactive({ completed: true }) })
  answers.qb.push('D')
  assert.deepEqual(payload.answers, [{ question_id: 'qa', answer: 'A' }, { question_id: 'qb', answer: ['B', 'C'] }])
  assert.equal(payload.expected_profile_version, 1)
})
await check('correction of only the review node needs no primary answers', () => {
  const review = { ...session, groups: [session.groups[1]] }
  const payload = buildRoundSubmission({ session: review, answers: { qb: ['B'] }, learnerId: 'learner', profileVersion: 1, key: 'stable-key', submittedAt: '2026-11-07T00:00:00Z' })
  assert.equal(payload.answers.length, 1)
})
await check('malformed duplicate groups and duplicate public question IDs fail closed', () => {
  assert.throws(() => requireRoundSession({ ...session, groups: [session.groups[0], session.groups[0]] }))
  assert.throws(() => requireRoundSession({ ...session, groups: [{ ...session.groups[0], questions: [{ question_id: 'same' }] }, { ...session.groups[1], questions: [{ question_id: 'same' }] }] }))
})
await check('unavailable draft storage cannot masquerade as a valid frozen draft', () => {
  assert.equal(readRoundDraft({ getItem() { throw new Error('disabled') } }, 'key', session), null)
  assert.equal(readRoundDraft({ getItem: () => JSON.stringify({ session_id: 'other', manifest_hash: session.manifest_hash }) }, 'key', session), null)
})

globalThis.sessionStorage = (() => { const rows = new Map(); return { getItem: key => rows.get(key) || null, setItem: (key, value) => rows.set(key, value), removeItem: key => rows.delete(key) } })()
await check('uncertain network retry reuses the entire frozen payload and one submission key', async () => {
  const submitted = []
  const harness = mount(() => useRoundEvaluation({ context: () => ({ learnerId: 'learner', roundId: 'round', stageId: 'initial' }), profileVersion: () => 1,
    accountId: () => 'account', onResult: () => {}, api: {
      result: async () => ({ data: { state: 'not_submitted' } }), session: async () => ({ data: session }),
      submit: async (_round, _stage, data) => { submitted.push(JSON.parse(JSON.stringify(data))); if (submitted.length === 1) throw new Error('network lost'); return { status: 200, data: result } },
    } }))
  try {
    await harness.state.load()
    harness.state.answers.qa = 'A'; harness.state.answers.qb = ['B']
    await harness.state.submit({ completed: true })
    assert.equal(harness.state.result.value, null)
    await harness.state.submit({ completed: false })
    assert.equal(submitted.length, 2)
    assert.deepEqual(submitted[0], submitted[1])
    assert.equal(harness.state.result.value.nodes[1].score, .5)
  } finally { harness.close() }
})
await check('expired scoring stops polling and retries the in-memory payload even without storage', () => withTimers(async timers => {
  const storage = globalThis.sessionStorage
  globalThis.sessionStorage = { getItem() { throw new Error('disabled') }, setItem() { throw new Error('disabled') }, removeItem() { throw new Error('disabled') } }
  const sent = []
  let grading = false
  let expired = false
  const harness = mount(() => useRoundEvaluation({ context: () => ({ learnerId: 'learner', roundId: 'round', stageId: 'initial' }),
    profileVersion: () => 1, accountId: () => 'memory-recovery', onResult: () => {}, api: {
      result: async () => ({ status: grading && !expired ? 202 : 200, data: { state: grading && !expired ? 'grading' : 'not_submitted' } }),
      session: async () => ({ data: session }),
      submit: async (_round, _stage, data) => {
        sent.push(JSON.parse(JSON.stringify(data)))
        grading = true
        return sent.length === 1 ? { status: 202, data: { state: 'grading' } } : { status: 200, data: result }
      },
    } }))
  try {
    await harness.state.load()
    harness.state.answers.qa = 'A'; harness.state.answers.qb = ['B']
    await harness.state.submit({ completed: true })
    assert.equal(harness.state.pending.value, true)
    expired = true
    await timers.tick()
    assert.equal(timers.count(), 0)
    assert.equal(harness.state.pending.value, false)
    assert.equal(harness.state.canSubmit.value, true)
    assert.deepEqual(JSON.parse(JSON.stringify(harness.state.draft.value)), sent[0])
    await harness.state.submit({ completed: false })
    assert.equal(sent.length, 2)
    assert.deepEqual(sent[0], sent[1])
    assert.equal(harness.state.result.value.attempt_id, result.attempt_id)
  } finally { harness.close(); globalThis.sessionStorage = storage }
}))
await check('refresh during grading restores frozen answers and original key when the lease expires', () => withTimers(async timers => {
  const saved = buildRoundSubmission({ session, answers: { qa: 'A', qb: ['B'] }, learnerId: 'learner',
    profileVersion: 1, key: 'stored-grading-key', submittedAt: '2026-11-08T00:00:00Z', reflection: { completed: true } })
  sessionStorage.setItem(roundDraftKey('refresh-recovery', 'learner', session.session_id), JSON.stringify(saved))
  let expired = false
  const sent = []
  const harness = mount(() => useRoundEvaluation({ context: () => ({ learnerId: 'learner', roundId: 'round', stageId: 'initial' }),
    profileVersion: () => 2, accountId: () => 'refresh-recovery', onResult: () => {}, api: {
      result: async () => ({ status: expired ? 200 : 202, data: { state: expired ? 'not_submitted' : 'grading' } }),
      session: async () => ({ data: session }),
      submit: async (_round, _stage, data) => { sent.push(JSON.parse(JSON.stringify(data))); return { status: 200, data: result } },
    } }))
  try {
    await harness.state.load()
    assert.equal(harness.state.session.value, null)
    assert.equal(harness.state.pending.value, true)
    expired = true
    await timers.tick()
    assert.equal(harness.state.session.value.session_id, session.session_id)
    assert.deepEqual({ ...harness.state.answers }, { qa: 'A', qb: ['B'] })
    assert.equal(harness.state.canSubmit.value, true)
    await harness.state.submit({ completed: false })
    assert.deepEqual(sent, [saved])
    assert.equal(sessionStorage.getItem(roundDraftKey('refresh-recovery', 'learner', session.session_id)), null)
  } finally { harness.close() }
}))
await check('late recovery session cannot restore a previous learner or leave a polling timer', () => withTimers(async timers => {
  const scope = reactive({ learnerId: 'learner', roundId: 'round', stageId: 'initial' })
  let expired = false
  let resolveSession
  const harness = mount(() => useRoundEvaluation({ context: () => ({ ...scope }), profileVersion: () => 1,
    accountId: () => 'late-recovery', onResult: () => {}, api: {
      result: async () => ({ status: expired ? 200 : 202, data: { state: expired ? 'not_submitted' : 'grading' } }),
      session: () => new Promise(resolve => { resolveSession = resolve }),
    } }))
  try {
    await harness.state.load()
    expired = true
    const ticking = timers.tick()
    await Promise.resolve()
    scope.learnerId = 'other'; harness.state.reset()
    resolveSession({ data: session })
    await ticking
    assert.equal(harness.state.session.value, null)
    assert.deepEqual(Object.keys(harness.state.answers), [])
    assert.equal(timers.count(), 0)
  } finally { harness.close() }
}))
await check('late session response cannot populate a different learner', async () => {
  let resolve
  const scope = reactive({ learnerId: 'learner', roundId: 'round', stageId: 'initial' })
  const harness = mount(() => useRoundEvaluation({ context: () => ({ ...scope }), profileVersion: () => 1, accountId: () => 'account', onResult: () => {},
    api: { result: async () => ({ data: { state: 'not_submitted' } }), session: () => new Promise(done => { resolve = done }) } }))
  try {
    const loading = harness.state.load(); await nextTick(); await Promise.resolve()
    scope.learnerId = 'other'; harness.state.reset()
    resolve({ data: session }); await loading
    assert.equal(harness.state.session.value, null)
    assert.deepEqual(Object.keys(harness.state.answers), [])
  } finally { harness.close() }
})
await check('normal task selector changes same-round member without restoring the previous run', async () => {
  const learnerId = ref('learner'); const runId = ref('run-a')
  const jobs = ref([{ run_id: 'run-a', round_binding: { round_id: 'round', member_id: 'a', stage_id: 'initial' } }, { run_id: 'run-b', round_binding: { round_id: 'round', member_id: 'b', stage_id: 'initial' } }])
  const selectedJob = ref(jobs.value[0])
  const activated = []
  const harness = mount(() => useLearningRoundWorkspace({ learnerId, selectedJob, selectedRunId: runId, jobs,
    route: { query: {} }, router: { replace: async () => {} }, api: { detail: async () => ({ data: detail }) },
    activateRun: async value => { activated.push(value) } }))
  try {
    await nextTick(); await Promise.resolve()
    selectedJob.value = jobs.value[1]; runId.value = 'run-b'
    await nextTick(); await Promise.resolve()
    assert.equal(harness.state.selection.value.memberId, 'b')
    assert.equal(harness.state.selection.value.runId, 'run-b')
    assert.equal(activated.includes('run-a'), false)
  } finally { harness.close() }
})
await check('background polling follows a retry through recovery despite a retained failed source run', () => withTimers(async timers => {
  const previousDocument = globalThis.document
  globalThis.document = { hidden: false }
  const learnerId = ref('learner'); const runId = ref('run-a')
  const jobs = ref([{ run_id: 'run-a', job_status: 'failed', round_binding: { round_id: 'round', member_id: 'a', stage_id: 'initial' } }])
  const selectedJob = ref(jobs.value[0])
  let reads = 0
  const harness = mount(() => useLearningRoundWorkspace({ learnerId, selectedJob, selectedRunId: runId, jobs,
    route: { query: {} }, router: { replace: async () => {} }, activateRun: async () => {}, api: {
      detail: async () => ({ data: { ...detail, members: detail.members.map(member => member.member_id !== 'a' ? member : {
        ...member, state: ++reads === 1 ? 'producing' : 'awaiting_assessment', failed_job_count: 0,
      }) } }),
    } }))
  try {
    await nextTick(); await Promise.resolve()
    assert.equal(harness.state.detail.value.members[0].state, 'producing')
    assert.equal(timers.count(), 1)
    await timers.tick(); await Promise.resolve()
    assert.equal(harness.state.detail.value.members[0].state, 'awaiting_assessment')
    assert.equal(timers.count(), 0)
    assert.equal(selectedJob.value.job_status, 'failed')
  } finally { harness.close(); globalThis.document = previousDocument }
}))

const output = new URL('./test-results/e14-round/', import.meta.url)
mkdirSync(output, { recursive: true })
writeFileSync(new URL('unit.json', output), JSON.stringify({ status: 'PASS', evidence_type: 'deterministic', checks }, null, 2))
console.log(`E14 round unit PASS: ${checks.length} checks`)
