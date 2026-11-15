import assert from 'node:assert/strict'
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { api } from '../src/api/client.js'
import { coursewareApi } from '../src/features/courseware/api.js'
import { generateApi } from '../src/features/generation/api.js'
import { fetchReportSnapshot, learningReportApi } from '../src/features/reports/api.js'
import { ReportStreamClient } from '../src/features/reports/reportStreamClient.js'
import { createRunEventClient, isRunSnapshotPayload, isWorkflowEventPayload } from '../src/features/runs/api.js'
import { CoursewareEventSender } from '../src/features/courseware/eventSync.js'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fixtures = JSON.parse(readFileSync(path.join(frontend, '../tests/contracts/v1.json'), 'utf8')).models
const originalAdapter = api.defaults.adapter
function respond(data, status = 200) {
  api.defaults.adapter = async config => ({ data: typeof data === 'string' ? data : JSON.stringify(data), status,
    statusText: String(status), config, headers: { 'content-type': 'application/json' } })
}
try {
  respond(fixtures.CoursewareLearningEventAck)
  const ack = await coursewareApi.ingestLearningEvents('resource_fixture', [])
  assert.deepEqual(ack.data, fixtures.CoursewareLearningEventAck)
  assert.equal(ack.acknowledged_event_ids, undefined, 'the actual Axios response remains wrapped')
  for (const bad of [{}, { acknowledged_event_ids: 'wrong' }, { acknowledged_event_ids: [1] }]) {
    respond(bad)
    await assert.rejects(coursewareApi.ingestLearningEvents('resource_fixture', []), { code: 'INVALID_API_RESPONSE' })
    let removed = 0
    const sender = new CoursewareEventSender({ queue: { error: '', async snapshot() { return { pending: [{ event_id: 'stable' }], blocked: 0, unassigned: 0, unsaved: 0 } },
      async acknowledge() { removed += 1; return 1 }, close() {} }, send: coursewareApi.ingestLearningEvents,
      broadcast: null, locks: null, online: () => true, schedule: () => 0, cancel: () => {} })
    sender.context = { account: 'A', resourceId: 'resource_fixture', releaseId: 'release_fixture' }
    await sender.flush()
    assert.equal(removed, 0, 'an invalid HTTP ACK cannot reach confirmation deletion')
    sender.dispose()
  }
  respond(fixtures.GenerationJobStatusResponse)
  assert.equal((await generateApi.getJobStatus('run_fixture')).data.job_status, 'running')
  respond({ ...fixtures.GenerationJobStatusResponse, job_status: 'interrupted' })
  await assert.rejects(generateApi.getJobStatus('run_fixture'), { code: 'INVALID_API_RESPONSE' })
  respond(fixtures.CurrentReportResponse)
  const report = await fetchReportSnapshot({ learnerId: 'learner_fixture', windowDays: 30 })
  assert.equal(report.revision, fixtures.CurrentReportResponse.report_revision)
  assert.equal(report.data.knowledge_blind_spot_map.cells[0].score, null, 'unmeasured is not zero')
  respond('', 304)
  assert.equal((await learningReportApi.get('learner_fixture', 30, report.revision)).status, 304)
  assert.equal(await fetchReportSnapshot({ learnerId: 'learner_fixture', windowDays: 30, etag: report.revision }), null)
  for (const bad of [
    { ...fixtures.CurrentReportResponse, report_revision: 'bad' },
    { ...fixtures.CurrentReportResponse, learner_id: 'another' },
    { ...fixtures.CurrentReportResponse, window: { window_days: 7 } },
  ]) {
    respond(bad)
    await assert.rejects(fetchReportSnapshot({ learnerId: 'learner_fixture', windowDays: 30 }), { code: 'INVALID_API_RESPONSE' })
  }
} finally { api.defaults.adapter = originalAdapter }

class FakeEventSource {
  static current
  constructor() { this.listeners = new Map(); FakeEventSource.current = this }
  addEventListener(name, callback) { this.listeners.set(name, callback) }
  emit(name, data) { this.listeners.get(name)?.({ data: JSON.stringify(data) }) }
  close() { this.closed = true }
}
const originalEventSource = globalThis.EventSource
globalThis.EventSource = FakeEventSource
try {
  assert.ok(isRunSnapshotPayload(fixtures.PublicRunSnapshot), 'queued can precede AgentRun')
  assert.ok(isRunSnapshotPayload({ status: 'running' }), 'legacy status alias remains supported')
  assert.equal(isRunSnapshotPayload({ run_id: 'r', run_status: 'queued' }), false)
  assert.equal(isRunSnapshotPayload({ run_id: 'r', job_status: 'finalizing' }), false)
  assert.equal(isRunSnapshotPayload({ run_id: 'r', is_terminal: 'false' }), false)
  assert.equal(isRunSnapshotPayload({ run_id: 'r', last_event_sequence: '2' }), false)
  for (const sequence of [-1, 0, 1.5, '2']) assert.equal(isWorkflowEventPayload({ sequence, event_type: 'step_started' }), false)
  assert.equal(isWorkflowEventPayload({ sequence: 1, event_type: 'step_started', payload: [] }), false)
  assert.ok(isWorkflowEventPayload({ event_sequence: 1, event_type: 'future_event', payload: {} }))
  const events = [], snapshots = [], terminals = []
  const run = createRunEventClient({ runId: 'run_fixture', onWorkflowEvent: event => events.push(event), onSnapshot: value => snapshots.push(value), onTerminal: value => terminals.push(value) })
  run.connect()
  FakeEventSource.current.emit('snapshot', { run_id: 'r', job_status: 'finalizing' })
  FakeEventSource.current.emit('snapshot', fixtures.PublicRunSnapshot)
  FakeEventSource.current.emit('snapshot', { ...fixtures.PublicRunSnapshot, run_id: 'another' })
  FakeEventSource.current.emit('resource_publication_decided', { ...fixtures.PublicRunEvent, run_id: 'another' })
  FakeEventSource.current.emit('resource_publication_decided', fixtures.PublicRunEvent)
  FakeEventSource.current.emit('resource_publication_decided', fixtures.PublicRunEvent)
  FakeEventSource.current.emit('run_interrupted', { event_sequence: 2, event_type: 'run_interrupted' })
  assert.equal(snapshots.length, 1)
  assert.equal(events.length, 2)
  assert.equal(terminals.length, 1)
  assert.ok(run.isClosed())
  let fetches = 0
  const stream = new ReportStreamClient({ fetchReport: async () => { fetches++; return null } })
  stream.start({ learnerId: 'learner_fixture', windowDays: 30, revision: fixtures.ReportInvalidation.report_revision })
  const source = FakeEventSource.current
  assert.doesNotThrow(() => source.listeners.get('report_changed')({ data: '{bad json' }))
  for (const patch of [{ learner_id: 'another' }, { window_days: 7 }, { report_revision: 'bad' }]) source.emit('report_changed', { ...fixtures.ReportInvalidation, ...patch })
  await new Promise(resolve => setTimeout(resolve, 280))
  assert.equal(fetches, 0)
  source.emit('report_changed', fixtures.ReportInvalidation)
  await new Promise(resolve => setTimeout(resolve, 280))
  assert.equal(fetches, 1)
  assert.equal(stream.revision, fixtures.ReportInvalidation.report_revision, '304 does not replace revision')
  stream.stop()
} finally { globalThis.EventSource = originalEventSource }

// Compile isolated negative fixtures. Production files never receive ignores or mutations.
const output = path.join(frontend, 'tests/test-results/contracts')
mkdirSync(output, { recursive: true })
const temporary = mkdtempSync(path.join(output, 'types-'))
const compilerOptions = JSON.parse(readFileSync(path.join(frontend, 'tsconfig.quality.json'), 'utf8')).compilerOptions
const modulePath = relative => path.join(frontend, relative).replaceAll('\\', '/')
function compile(source, name) {
  const file = path.join(temporary, name + '.js')
  writeFileSync(file, source)
  const config = path.join(temporary, name + '.json')
  writeFileSync(config, JSON.stringify({ compilerOptions, files: [file] }))
  return spawnSync(process.execPath, [path.join(frontend, 'node_modules/typescript/bin/tsc'), '-p', config], { encoding: 'utf8', timeout: 30000 })
}
const positive = compile(`import { coursewareApi } from '${modulePath('src/features/courseware/api.js')}'
import { fetchReportSnapshot } from '${modulePath('src/features/reports/api.js')}'
async function valid() {
 const response = await coursewareApi.ingestLearningEvents('resource', [])
 response.data.acknowledged_event_ids.map(id => id.toUpperCase())
 const report = await fetchReportSnapshot({ learnerId: 'learner', windowDays: 30 })
 if (report) report.revision.toUpperCase()
}`, 'positive')
assert.equal(positive.status, 0, positive.stdout + positive.stderr)
for (const [name, source] of [
  ['ack-layer', `import { coursewareApi } from '${modulePath('src/features/courseware/api.js')}'; async function bad() { (await coursewareApi.ingestLearningEvents('r', [])).acknowledged_event_ids }`],
  ['job-state', `/** @type {import('${modulePath('src/contracts/generated/contracts')}').GenerationJobStatus} */ const status = 'interrupted'; export { status }`],
  ['window', `import { fetchReportSnapshot } from '${modulePath('src/features/reports/api.js')}'; fetchReportSnapshot({ learnerId: 'x', windowDays: 14 })`],
  ['revision', `/** @type {import('${modulePath('src/contracts/generated/contracts')}').ReportInvalidation} */ const value = {learner_id:'x', window_days:30, report_revision:42}; export {value}`],
  ['nullable', `/** @type {import('${modulePath('src/contracts/generated/contracts')}').BlindSpotCellV1} */ const cell = {skill_node_id:'n', dimension:'concept', score:null, status:'unassessed', confidence:'none', objective_evidence_count:0}; cell.score.toFixed(2); export {cell}`],
]) {
  const result = compile(source, name)
  assert.notEqual(result.status, 0, `${name} must fail compilation`)
  assert.match(result.stdout, /error TS\d+/)
}
const copied = path.join(temporary, 'src/features/courseware')
mkdirSync(copied, { recursive: true })
// Node 24's native recursive cp can terminate the process on Windows paths.
// Copy this controlled fixture tree explicitly, keeping the same test inputs.
function copyFixtureTree(source, destination) {
  mkdirSync(destination, { recursive: true })
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name)
    const to = path.join(destination, entry.name)
    if (entry.isDirectory()) copyFixtureTree(from, to)
    else if (entry.isFile()) copyFileSync(from, to)
    else throw new Error('Unexpected non-file contract fixture')
  }
}
copyFixtureTree(path.join(frontend, 'src/contracts'), path.join(temporary, 'src/contracts'))
const sender = readFileSync(path.join(frontend, 'src/features/courseware/eventSync.js'), 'utf8')
const mutant = sender.replace('response?.data?.acknowledged_event_ids', 'response?.acknowledged_event_ids')
assert.notEqual(mutant, sender)
writeFileSync(path.join(copied, 'eventSync.js'), mutant)
const mutationResult = compile(`import '${path.join(copied, 'eventSync.js').replaceAll('\\', '/')}'`, 'actual-sender-mutation')
assert.notEqual(mutationResult.status, 0)
assert.match(mutationResult.stdout, /acknowledged_event_ids.*AxiosResponse/)
console.log('API/SSE boundary fixtures and 6 compile-time negative cases passed')
