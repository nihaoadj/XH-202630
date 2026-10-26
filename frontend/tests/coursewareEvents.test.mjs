import assert from 'node:assert/strict'
import { createCoursewareEvent, projectCoursewareProgress } from '../src/features/courseware/offlineEvents.js'
import { CoursewareEventSender } from '../src/features/courseware/eventSync.js'

const context = { account: 'A', resourceId: 'resource', releaseId: 'release' }
const event = id => ({ ...createCoursewareEvent({ event_type: 'scene_viewed', resource_id: 'resource', release_id: 'release', scene_id: id }), event_id: id })
function fixture(events) {
  const rows = events.map(event => ({ account: 'A', event }))
  const sent = []
  const timers = new Set()
  const queue = {
    error: '',
    async snapshot(c) { return { pending: rows.filter(row => row.account === c.account && row.event.resource_id === c.resourceId && row.event.release_id === c.releaseId && !row.blocked).map(row => row.event), blocked: rows.filter(row => row.blocked).length, unassigned: 0, unsaved: 0, error: '', lastSuccess: null } },
    async acknowledge(c, batch, ids) { const confirmed = new Set(ids.filter(id => batch.some(item => item.event_id === id))); for (let i = rows.length - 1; i >= 0; i--) if (rows[i].account === c.account && rows[i].event.release_id === c.releaseId && confirmed.has(rows[i].event.event_id)) rows.splice(i, 1); return confirmed.size },
    async enqueue(account, event) { rows.push({ account, event }); return true },
    async quarantine(c, batch) { rows.filter(row => row.account === c.account && batch.some(e => row.event.event_id === e.event_id)).forEach(row => { row.blocked = true }) },
    async retryPersistence() {}, async migrateLegacy() {}, close() {},
  }
  const sender = new CoursewareEventSender({ queue, send: async (_, batch) => { sent.push(batch); return { data: { acknowledged_event_ids: batch.map(item => item.event_id) } } }, broadcast: null, locks: null,
    schedule: callback => { timers.add(callback); return callback }, cancel: callback => timers.delete(callback) })
  sender.context = context
  return { sender, rows, sent, timers }
}

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

assert.equal(createCoursewareEvent({ state: { scene_index: 1, secret: 'remove' } }).state.secret, undefined)
const a = event('a'), b = { ...event('b'), event_type: 'courseware_completed' }
assert.equal(projectCoursewareProgress([a, b], { resource_id: 'resource', release_id: 'release' }).courseware_completed, true)

{
  const f = fixture(Array.from({ length: 250 }, (_, i) => event(`event-${i}`)))
  let calls = 0
  f.sender.send = async (_, batch) => {
    f.sent.push(batch)
    if (++calls === 2) throw { response: { status: 503 } }
    return { data: { acknowledged_event_ids: batch.map(item => item.event_id) } }
  }
  await f.sender.flush()
  assert.equal(f.rows.length, 150)
  assert.deepEqual(f.sent.map(batch => batch.length), [100, 100])
  await f.sender.retry()
  assert.deepEqual(f.sent.map(batch => batch.length), [100, 100, 100, 50])
  assert.equal(f.rows.length, 0)
  f.sender.dispose()
}
{
  const f = fixture([a, b])
  f.sender.send = async () => ({ data: { acknowledged_event_ids: ['a', 'foreign'] } })
  await f.sender.flush()
  assert.deepEqual(f.rows.map(row => row.event.event_id), ['b'])
  assert.equal(f.sender.state.error, 'partial_ack')
  f.sender.dispose()
}
{
  const f = fixture([a])
  let release
  const blocked = new Promise(resolve => { release = resolve })
  f.sender.send = async () => { await blocked; return { data: { acknowledged_event_ids: ['a'] } } }
  const active = f.sender.flush()
  await Promise.resolve()
  await f.sender.enqueue(event('new'), 'A')
  const switched = f.sender.setContext({ account: 'B', resourceId: 'resource', releaseId: 'release-new' })
  release()
  await switched
  await active
  assert.deepEqual(f.rows.map(row => row.event.event_id), ['new'])
  assert.equal(f.sender.context.account, 'B')
  f.sender.dispose()
}
for (const patch of [{ account: 'B' }, { resourceId: 'another-resource' }, { releaseId: 'another-release' }, null]) {
  const f = fixture([a])
  const entered = deferred(), release = deferred()
  const snapshot = f.sender.queue.snapshot.bind(f.sender.queue)
  let delayed = false
  f.sender.queue.snapshot = async c => {
    const result = await snapshot(c)
    if (!delayed) { delayed = true; entered.resolve(); await release.promise }
    return result
  }
  const sending = f.sender.flush()
  await entered.promise
  let switching
  if (patch) {
    const current = { ...context, ...patch }
    f.rows.push({ account: current.account, event: { ...event('current'), resource_id: current.resourceId, release_id: current.releaseId } })
    switching = f.sender.setContext(current)
  } else f.sender.dispose()
  release.resolve()
  await Promise.all([sending, switching])
  await f.sender.flush()
  assert.deepEqual(f.sent.flatMap(batch => batch.map(item => item.event_id)), patch ? ['current'] : [])
  assert.deepEqual(f.rows.map(row => row.event.event_id), ['a'])
  f.sender.dispose()
}
for (const [granted, dispose] of [[true, false], [false, false], [true, true], [false, true]]) {
  const f = fixture([a])
  const entered = deferred(), release = deferred()
  let first = true, staleState
  f.sender.locks = { async request(key, options, callback) {
    if (first) {
      first = false; entered.resolve(); await release.promise
      const result = callback(granted ? {} : null)
      staleState = { sending: f.sender.state.sending, timer: f.sender.timer }
      return result
    }
    return callback({})
  } }
  const sending = f.sender.flush()
  await entered.promise
  let switching
  if (dispose) f.sender.dispose()
  else {
    f.rows.push({ account: 'B', event: event('current') })
    switching = f.sender.setContext({ ...context, account: 'B' })
  }
  release.resolve()
  await Promise.all([sending, switching])
  await f.sender.flush()
  assert.deepEqual(staleState, { sending: false, timer: null })
  assert.equal(f.timers.size, 0)
  assert.deepEqual(f.sent.flatMap(batch => batch.map(item => item.event_id)), dispose ? [] : ['current'])
  assert.deepEqual(f.rows.map(row => row.event.event_id), ['a'])
  f.sender.dispose()
}
for (const phase of ['refresh', 'stale-read', 'quarantine']) {
  const f = fixture([a])
  const entered = deferred(), release = deferred()
  const snapshot = f.sender.queue.snapshot.bind(f.sender.queue)
  let reads = 0
  f.sender.queue.snapshot = async c => {
    const result = await snapshot(c)
    if (++reads === 2 && phase !== 'quarantine') { entered.resolve(); await release.promise }
    return result
  }
  if (phase === 'quarantine') {
    const quarantine = f.sender.queue.quarantine.bind(f.sender.queue)
    f.sender.queue.quarantine = async (...args) => { entered.resolve(); await release.promise; return quarantine(...args) }
  }
  if (phase !== 'refresh') f.sender.send = async () => { throw { response: { status: phase === 'stale-read' ? 409 : 422 } } }
  const sending = f.sender.flush()
  await entered.promise
  const switching = f.sender.setContext({ ...context, account: 'B' })
  // A later callback cannot overwrite the new context's current recovery state.
  f.sender.publish({ paused: true, error: 'auth', attempts: 2 })
  release.resolve()
  await Promise.all([sending, switching])
  assert.equal(f.sender.state.error, 'auth')
  assert.equal(f.sender.state.attempts, 2)
  assert.equal(f.sender.state.paused, true)
  if (phase === 'refresh') assert.equal(f.rows.length, 0)
  if (phase === 'stale-read') assert.equal(f.rows[0].blocked, undefined)
  if (phase === 'quarantine') assert.equal(f.rows[0].blocked, true)
  f.sender.dispose()
}
for (const status of [401, 409, 422, 503]) {
  const f = fixture([a])
  let calls = 0
  f.sender.send = async () => { calls++; throw { response: { status } } }
  await f.sender.flush()
  if (status === 401) { await f.sender.onlineAgain(); assert.equal(calls, 1); assert.equal(f.sender.state.paused, true) }
  if ([409, 422].includes(status)) { await f.sender.flush(); assert.equal(calls, 1); assert.equal(f.rows[0].blocked, true) }
  if (status === 503) {
    while (f.timers.size) { const callback = [...f.timers][0]; f.timers.delete(callback); callback(); await f.sender.active }
    assert.equal(calls, 5)
    assert.equal(f.sender.state.attempts, 5)
  }
  f.sender.dispose()
}
console.log('courseware event identity, batching, acknowledgement and recovery passed')
