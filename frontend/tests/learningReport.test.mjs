import assert from 'node:assert/strict'
import { ReportStreamClient } from '../src/features/reports/reportStreamClient.js'

class FakeEventSource {
  static current = null
  constructor() { FakeEventSource.current = this; this.listeners = new Map() }
  addEventListener(name, callback) { this.listeners.set(name, callback) }
  close() { this.closed = true }
  emit(name, payload) { this.listeners.get(name)?.({ data: JSON.stringify(payload) }) }
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
