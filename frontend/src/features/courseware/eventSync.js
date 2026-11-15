import { responseStatus } from '../../contracts/guards.js'

const localSenders = new Set()
/** @param {import('../../contracts/ports').EventContext} context */
const keyFor = context => JSON.stringify([context.account, context.resourceId, context.releaseId])
/** @returns {import('../../contracts/ports').SyncState} */
const empty = () => ({ pending: 0, blocked: 0, unassigned: 0, unsaved: 0, sending: false, paused: false, attempts: 0, error: '', storageError: '', lastSuccess: null })

/** Upload orchestration never changes event identity or account/release ownership. */
export class CoursewareEventSender {
  /** @param {import('../../contracts/ports').SenderOptions} options */
  constructor({ queue, send, changed = () => {}, locks = globalThis.navigator?.locks,
    online = () => globalThis.navigator?.onLine !== false, schedule = globalThis.setTimeout.bind(globalThis), cancel = globalThis.clearTimeout.bind(globalThis),
    broadcast = typeof BroadcastChannel === 'function' ? new BroadcastChannel('courseware-progress-v2') : null }) {
    this.queue = queue
    this.send = send
    this.changed = changed
    this.locks = locks
    this.online = online
    this.schedule = schedule
    this.cancel = cancel
    this.broadcast = broadcast
    this.context = { account: '', resourceId: '', releaseId: '' }
    this.state = empty()
    this.version = 0
    /** @type {number | null} */
    this.timer = null
    /** @type {Promise<void> | null} */
    this.active = null
    this.disposed = false
    this.wakeRequested = false
    if (broadcast) broadcast.onmessage = event => {
      if (event.data === keyFor(this.context)) { this.refresh(); this.flush() }
    }
  }

  /** @param {Partial<import('../../contracts/ports').SyncState>} patch */
  publish(patch = {}) {
    if (this.disposed) return
    this.state = { ...this.state, ...patch }
    this.changed({ ...this.state })
  }

  /** @param {import('../../contracts/ports').EventContext} context */
  async setContext(context) {
    if (keyFor(context) === keyFor(this.context)) return
    this.version += 1
    this.clearTimer()
    this.context = { ...context }
    this.state = empty()
    await this.refresh()
    return this.flush()
  }

  async initialize() { await this.queue.migrateLegacy(); await this.refresh(); this.flush() }

  async refresh() {
    const version = this.version
    const snapshot = await this.queue.snapshot(this.context)
    if (version === this.version) this.publish({ pending: snapshot.pending.length, blocked: snapshot.blocked,
      unassigned: snapshot.unassigned, unsaved: snapshot.unsaved, storageError: snapshot.error, lastSuccess: snapshot.lastSuccess })
    return snapshot
  }

  /** @param {import('../../contracts/ports').EventContext} context */
  notify(context) { try { this.broadcast?.postMessage(keyFor(context)) } catch { /* advisory only */ } }

  /** @param {import('../../contracts/generated/contracts').CoursewareLearningEvent} event @param {string} account */
  async enqueue(event, account) {
    const persisted = await this.queue.enqueue(account, event)
    this.notify({ account, resourceId: event.resource_id, releaseId: event.release_id })
    await this.refresh()
    if (persisted) this.flush()
    return persisted
  }

  clearTimer() { if (this.timer !== null) this.cancel(this.timer); this.timer = null }

  /** @param {number} delay @param {number} version */
  later(delay, version) {
    this.clearTimer()
    this.timer = this.schedule(() => {
      this.timer = null
      if (version === this.version) this.flush()
    }, delay)
  }

  /** @param {string} error @param {number} version */
  retryLater(error, version) {
    if (version !== this.version || this.disposed) return
    const attempts = this.state.attempts + 1
    this.publish({ error, attempts })
    if (attempts < 5) this.later(Math.min(1000 * 2 ** (attempts - 1), 30000), version)
  }

  /** @returns {Promise<void>} */
  flush() {
    if (this.disposed || this.state.paused || this.timer !== null || this.state.attempts >= 5) return this.active || Promise.resolve()
    if (this.active) { this.wakeRequested = true; return this.active }
    this.wakeRequested = false
    const context = { ...this.context }, version = this.version
    if (!context.account || !context.resourceId || !context.releaseId) return Promise.resolve()
    if (!this.online()) { this.publish({ error: 'offline' }); return this.refresh().then(() => {}) }
    const key = `courseware-send:${keyFor(context)}`
    const execute = async () => {
      if (this.disposed || version !== this.version) return
      if (localSenders.has(key)) { this.later(500, version); return }
      localSenders.add(key)
      this.publish({ sending: true })
      try { await this.drain(context, version) }
      finally { localSenders.delete(key); if (version === this.version) this.publish({ sending: false }) }
    }
    this.active = (async () => {
      try {
        if (this.locks?.request) {
          await this.locks.request(key, { ifAvailable: true }, async lock => {
            if (this.disposed || version !== this.version) return
            if (lock) await execute()
            else this.later(500, version)
          })
        } else await execute()
      } catch {
        if (version === this.version) this.publish({ storageError: '进度同步未能完成本地确认，请重试保存。' })
      } finally {
        this.active = null
        if (!this.disposed) {
          await this.refresh()
          if (version !== this.version || this.wakeRequested) this.flush()
        }
      }
    })()
    return this.active
  }

  /** @param {import('../../contracts/ports').EventContext} context @param {number} version */
  async drain(context, version) {
    while (!this.disposed && version === this.version) {
      const snapshot = await this.queue.snapshot(context)
      if (this.disposed || version !== this.version) return
      const batch = snapshot.pending.slice(0, 100)
      if (!batch.length) return
      if (!this.online()) { this.publish({ error: 'offline' }); return }
      try {
        const response = await this.send(context.resourceId, batch)
        const ids = response?.data?.acknowledged_event_ids
        const confirmed = await this.queue.acknowledge(context, batch, Array.isArray(ids) ? ids : [])
        this.notify(context)
        if (version !== this.version || this.disposed) return
        await this.refresh()
        if (version !== this.version || this.disposed) return
        if (confirmed !== batch.length) { this.retryLater('partial_ack', version); return }
        this.publish({ error: '', attempts: 0 })
      } catch (error) {
        if (version !== this.version || this.disposed) return
        const status = responseStatus(error)
        if (status === 401) { this.publish({ paused: true, error: 'auth' }); return }
        if (status !== undefined && status >= 400 && status < 500 && status !== 429) {
          const rejected = status === 409 ? (await this.queue.snapshot(context)).pending : batch
          if (version !== this.version || this.disposed) return
          await this.queue.quarantine(context, rejected, status === 409 ? 'stale_release' : 'invalid_event')
          this.notify(context)
          if (version !== this.version || this.disposed) return
          this.publish({ error: status === 409 ? 'stale_release' : 'invalid_event' })
          // Bad input is retained and excluded from all future automatic sends.
          if (status === 409) return
          continue
        }
        this.retryLater('temporary', version)
        return
      }
    }
  }

  async retry() {
    this.clearTimer()
    await this.queue.retryPersistence()
    this.publish({ attempts: 0, error: '', paused: false, storageError: this.queue.error })
    await this.refresh()
    return this.flush()
  }

  onlineAgain() {
    // An online event cannot resume an expired authentication session.
    if (this.state.paused) return
    this.clearTimer()
    this.publish({ attempts: 0, error: '' })
    return this.flush()
  }

  dispose() { this.disposed = true; this.version += 1; this.clearTimer(); this.broadcast?.close(); this.queue.close() }
}
