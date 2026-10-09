import assert from 'node:assert/strict'
import { ReportStreamClient } from '../src/features/reports/reportStreamClient.js'

class FakeEventSource {
  static current = null
  constructor() { FakeEventSource.current = this; this.listeners = new Map() }
  addEventListener(name, callback) { this.listeners.set(name, callback) }
  close() { this.closed = true }
  emit(name, payload) { this.listeners.get(name)?.({ data: JSON.stringify(payload) }) }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

globalThis.EventSource = FakeEventSource
Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true })
let fetches = 0
let lastEtag = 'not-called'
let applied = 0
const client = new ReportStreamClient({
  fetchReport: async ({ etag }) => { fetches += 1; lastEtag = etag; return { revision: 'rpt_b'.padEnd(68, '0'), data: { learner_id: 'one', window: { window_days: 30 } } } },
  onReport: () => { applied += 1 },
})
client.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
FakeEventSource.current.emit('report_snapshot', { learner_id: 'one', window_days: 30, report_revision: 'rpt_a'.padEnd(68, '0') })
await new Promise((resolve) => setTimeout(resolve, 300))
assert.equal(fetches, 0, 'an unchanged reconnect snapshot must not fetch again')
FakeEventSource.current.emit('report_changed', { learner_id: 'two', window_days: 30, report_revision: 'rpt_c'.padEnd(68, '0') })
await new Promise((resolve) => setTimeout(resolve, 300))
assert.equal(fetches, 0, 'events for an old learner must be ignored')
FakeEventSource.current.emit('report_changed', { learner_id: 'one', window_days: 30, report_revision: 'rpt_d'.padEnd(68, '0') })
await new Promise((resolve) => setTimeout(resolve, 300))
assert.equal(fetches, 1)
assert.equal(applied, 1)
assert.equal(lastEtag, null, 'report_changed must fetch a full snapshot instead of conditionally requesting the event revision')
client.stop()

const reconnectStatuses = []
const reconnect = new ReportStreamClient({ fetchReport: async () => { throw new Error('unchanged snapshot must not fetch') }, onStatus: status => reconnectStatuses.push(status) })
reconnect.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
FakeEventSource.current.onerror()
FakeEventSource.current.onopen()
FakeEventSource.current.emit('report_snapshot', { learner_id: 'one', window_days: 30, report_revision: 'rpt_a'.padEnd(68, '0') })
await new Promise((resolve) => setTimeout(resolve, 300))
assert.deepEqual(reconnectStatuses.slice(-2), ['reconnecting', 'live'], 'a transport reconnect must converge on the current snapshot')
reconnect.stop()

const statuses = []
const fallback = new ReportStreamClient({ fetchReport: async () => null, onStatus: status => statuses.push(status) })
fallback.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
FakeEventSource.current.onerror(); FakeEventSource.current.onerror(); FakeEventSource.current.onerror()
assert.equal(statuses.at(-1), 'polling', 'three transport errors must fall back to conditional polling')
fallback.stop()

const lateResponse = deferred()
const lateReports = []
const stopped = new ReportStreamClient({
  fetchReport: () => lateResponse.promise,
  onReport: report => lateReports.push(report),
})
stopped.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
const stoppedRequest = stopped.refresh()
assert.equal(stopped.pending, true, 'an active refresh should mark the client pending')
stopped.stop()
lateResponse.resolve({ revision: 'rpt_b', data: { learner_id: 'one', window: { window_days: 30 } } })
await stoppedRequest
assert.deepEqual(lateReports, [], 'a response arriving after stop must not update the report')
assert.equal(stopped.pending, false, 'stop should clear the stopped client pending state')

const generationRequests = []
const generationReports = []
const generationClient = new ReportStreamClient({
  fetchReport: ({ learnerId }) => {
    const request = deferred()
    generationRequests.push({ learnerId, ...request })
    return request.promise
  },
  onReport: report => generationReports.push(report),
})
generationClient.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
const oldGenerationRequest = generationClient.refresh()
generationClient.start({ learnerId: 'two', windowDays: 30, revision: 'rpt_c'.padEnd(68, '0') })
const newGenerationRequest = generationClient.refresh()
assert.equal(generationRequests.length, 2)
assert.equal(generationClient.pending, true, 'the new generation should own a pending request')
generationRequests[0].resolve({ revision: 'rpt_old', data: { learner_id: 'one', window: { window_days: 30 } } })
await oldGenerationRequest
assert.equal(generationClient.pending, true, 'the old request finally must not clear the new generation pending state')
assert.deepEqual(generationReports, [], 'the old generation response must not reach the current report')
generationRequests[1].resolve({ revision: 'rpt_new', data: { learner_id: 'two', window: { window_days: 30 } } })
await newGenerationRequest
assert.equal(generationClient.pending, false, 'the current request should release its own pending state')
assert.deepEqual(generationReports.map(report => report.learner_id), ['two'])
generationClient.stop()

const staleStatuses = []
let staleFetches = 0
const staleEvents = new ReportStreamClient({
  fetchReport: async () => { staleFetches += 1; return null },
  onStatus: status => staleStatuses.push(status),
})
const realSetTimeout = globalThis.setTimeout
const realClearTimeout = globalThis.clearTimeout
const scheduledTimeouts = new Map()
let nextTimeoutId = 0
globalThis.setTimeout = (callback, delay) => {
  const id = ++nextTimeoutId
  scheduledTimeouts.set(id, { callback, delay })
  return id
}
globalThis.clearTimeout = id => scheduledTimeouts.delete(id)
try {
  staleEvents.start({ learnerId: 'one', windowDays: 30, revision: 'rpt_a'.padEnd(68, '0') })
  const oldSource = FakeEventSource.current
  staleEvents.start({ learnerId: 'two', windowDays: 30, revision: 'rpt_b'.padEnd(68, '0') })
  oldSource.onopen()
  oldSource.onerror()
  oldSource.emit('report_changed', { learner_id: 'one', window_days: 30, report_revision: 'rpt_c'.padEnd(68, '0') })
  assert.equal(oldSource.closed, true, 'restarting should close the previous EventSource')
  assert.equal(staleEvents.errors, 0, 'a stale EventSource error must not alter the current retry count')
  assert.equal(scheduledTimeouts.size, 0, 'a stale SSE change must not schedule a current refresh')
  assert.equal(staleFetches, 0)
  assert.equal(staleStatuses.includes('live'), false, 'a stale open callback must not report the current stream live')
  assert.equal(staleStatuses.includes('reconnecting'), false, 'a stale error callback must not change current stream status')
} finally {
  globalThis.setTimeout = realSetTimeout
  globalThis.clearTimeout = realClearTimeout
  staleEvents.stop()
}

const retryStatuses = []
const retryReports = []
let retryAttempts = 0
const retryClient = new ReportStreamClient({
  fetchReport: async () => {
    retryAttempts += 1
    if (retryAttempts === 1) throw new Error('temporary report failure')
    return { revision: 'rpt_retry', data: { learner_id: 'retry', window: { window_days: 7 } } }
  },
  onStatus: status => retryStatuses.push(status),
  onReport: report => retryReports.push(report),
})
retryClient.start({ learnerId: 'retry', windowDays: 7, revision: 'rpt_before'.padEnd(68, '0') })
await retryClient.refresh()
assert.equal(retryClient.pending, false, 'a rejected fetch should be caught and release pending')
assert.ok(retryStatuses.includes('reconnecting'), 'a rejected current fetch should report reconnecting')
await retryClient.refresh()
assert.equal(retryAttempts, 2, 'a later refresh should retry after a fetch failure')
assert.deepEqual(retryReports.map(report => report.learner_id), ['retry'])
retryClient.stop()
