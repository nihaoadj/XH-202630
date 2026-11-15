const LEGACY_KEY = 'zhiyu.courseware.learning-events.v1'
const DATABASE = 'zhiyu.courseware.learning-events.v2'
const EVENT_FIELDS = new Set(['event_id', 'event_schema_version', 'occurrence_id', 'event_type', 'resource_id', 'release_id', 'resource_version', 'release_version', 'scene_id', 'scene_version', 'component_id', 'component_version', 'created_at', 'occurred_at', 'state'])
const STATE_FIELDS = new Set(['scene_index', 'scene_count', 'correct', 'completed', 'attempt', 'duration_ms', 'component_state'])
const copy = value => JSON.parse(JSON.stringify(value))
const identity = (account, id) => JSON.stringify([account || '', id])
const belongs = (row, context) => row.account === context.account && row.event?.resource_id === context.resourceId && row.event?.release_id === context.releaseId

export function createCoursewareEvent({ event_type, resource_id, release_id, scene_id = null, component_id = null, component_version = '1.0', state = {} }) {
  const id = `occ_${globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(16).slice(2)}`}`
  const time = new Date().toISOString()
  return { event_id: id, occurrence_id: id, event_type, resource_id, release_id, scene_id, component_id, component_version,
    state: Object.fromEntries(Object.entries(state).filter(([key]) => STATE_FIELDS.has(key))), created_at: time, occurred_at: time }
}

/** IndexedDB owns queue transactions; memory holds only writes that could not commit. */
export class CoursewareEventQueue {
  constructor({ indexedDB = globalThis.indexedDB, storage, name = DATABASE } = {}) {
    this.indexedDB = indexedDB
    this.storage = storage
    this.name = name
    this.connection = null
    this.opening = null
    this.unsaved = new Map()
    this.error = ''
  }

  async open() {
    if (this.connection) return this.connection
    if (this.opening) return this.opening
    this.opening = new Promise((resolve, reject) => {
      if (!this.indexedDB) { reject(new Error('EVENT_STORAGE_UNAVAILABLE')); return }
      const request = this.indexedDB.open(this.name, 1)
      request.onupgradeneeded = () => {
        request.result.createObjectStore('events', { keyPath: 'key' })
        request.result.createObjectStore('metadata', { keyPath: 'key' })
      }
      request.onerror = () => reject(new Error('EVENT_STORAGE_UNAVAILABLE'))
      request.onblocked = () => reject(new Error('EVENT_STORAGE_BLOCKED'))
      request.onsuccess = () => {
        this.connection = request.result
        this.connection.onversionchange = () => this.close()
        resolve(this.connection)
      }
    })
    try { await this.opening } finally { this.opening = null }
    return this.connection
  }

  async transaction(mode, action) {
    const db = await this.open()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['events', 'metadata'], mode)
      let result
      tx.oncomplete = () => resolve(result)
      tx.onerror = tx.onabort = () => reject(new Error('EVENT_STORAGE_WRITE_FAILED'))
      try { action(tx.objectStore('events'), tx.objectStore('metadata'), value => { result = value }) }
      catch (error) { tx.abort(); reject(error) }
    })
  }

  async migrateLegacy() {
    // Legacy records have no trustworthy account identity. Never assign the current user.
    let storage
    try {
      storage = this.storage === undefined ? globalThis.localStorage : this.storage
      const raw = storage?.getItem(LEGACY_KEY)
      if (!raw) return
      let events
      try { events = JSON.parse(raw) } catch { events = [{ legacy_raw: raw }] }
      if (!Array.isArray(events)) events = [events]
      await this.transaction('readwrite', (store) => {
        events.forEach((event, index) => {
          const id = event?.event_id || JSON.stringify(['legacy', index, event])
          const key = identity('', id)
          const request = store.get(key)
          request.onsuccess = () => {
            if (!request.result) store.put({ key, account: '', event, savedAt: event?.created_at || '', blocked: 'unknown_account' })
          }
        })
      })
      // A late legacy writer must not have its newer array removed.
      if (storage.getItem(LEGACY_KEY) === raw) storage.removeItem(LEGACY_KEY)
    } catch { this.error = '旧版进度尚未完成安全迁移，请重试保存。' }
  }

  async enqueue(account, rawEvent) {
    const event = Object.fromEntries(Object.entries(copy(rawEvent)).filter(([key]) => EVENT_FIELDS.has(key)))
    const valid = event.event_id && event.resource_id && event.release_id
    const row = { key: identity(account, event.event_id || crypto.randomUUID()), account: account || '', event,
      savedAt: new Date().toISOString(), blocked: !account ? 'unknown_account' : valid ? '' : 'invalid_event' }
    try {
      await this.transaction('readwrite', store => {
        const request = store.get(row.key)
        request.onsuccess = () => { if (!request.result) store.put(row) }
      })
      this.unsaved.delete(row.key)
      this.error = ''
      return true
    } catch {
      if (!this.unsaved.has(row.key)) this.unsaved.set(row.key, row)
      this.error = '部分学习进度尚未可靠保存，请保留此页面并重试保存。'
      return false
    }
  }

  async retryPersistence() {
    const rows = [...this.unsaved.values()]
    try {
      await this.transaction('readwrite', store => {
        for (const row of rows) {
          const request = store.get(row.key)
          request.onsuccess = () => { if (!request.result) store.put(row) }
        }
      })
      rows.forEach(row => this.unsaved.delete(row.key))
      this.error = ''
      await this.migrateLegacy()
    } catch { this.error = '学习进度尚未可靠保存，请保留此页面并重试保存。' }
  }

  async snapshot(context) {
    let rows = []
    let lastSuccess = null
    try {
      await this.transaction('readonly', (store, meta, result) => {
        const events = store.getAll()
        const success = meta.get(JSON.stringify(context))
        events.onsuccess = () => { rows = events.result }
        success.onsuccess = () => { lastSuccess = success.result?.time || null }
        result(null)
      })
    } catch { this.error = '无法读取本地进度存储，请保留此页面并重试保存。' }
    const savedKeys = new Set(rows.map(row => row.key))
    rows.push(...[...this.unsaved.values()].filter(row => !savedKeys.has(row.key)))
    const scoped = rows.filter(row => belongs(row, context))
    const pending = scoped.filter(row => !row.blocked && !this.unsaved.has(row.key))
      .sort((a, b) => String(a.savedAt).localeCompare(String(b.savedAt)) || a.event.event_id.localeCompare(b.event.event_id))
    return { pending: pending.map(row => copy(row.event)), blocked: rows.filter(row => row.account === context.account && row.account && row.event.resource_id === context.resourceId && (row.blocked || row.event.release_id !== context.releaseId)).length,
      unassigned: rows.filter(row => !row.account).length,
      unsaved: [...this.unsaved.values()].filter(row => row.account === context.account).length,
      lastSuccess, error: this.error }
  }

  async acknowledge(context, sent, acknowledged) {
    const ids = new Set(acknowledged.filter(id => sent.some(event => event.event_id === id)))
    await this.transaction('readwrite', (store, meta) => {
      for (const id of ids) {
        const request = store.get(identity(context.account, id))
        request.onsuccess = () => { if (request.result && belongs(request.result, context)) store.delete(request.result.key) }
      }
      if (ids.size) meta.put({ key: JSON.stringify(context), time: new Date().toISOString() })
    })
    return ids.size
  }

  async quarantine(context, events, reason) {
    await this.transaction('readwrite', store => {
      for (const event of events) {
        const request = store.get(identity(context.account, event.event_id))
        request.onsuccess = () => {
          const row = request.result
          if (row && belongs(row, context)) store.put({ ...row, blocked: reason })
        }
      }
    })
  }

  async exportBlocked(account, context = {}) {
    const rows = await this.transaction('readonly', (store, _, result) => {
      const request = store.getAll()
      request.onsuccess = () => result(request.result)
    })
    return [...rows, ...this.unsaved.values()].filter(row => (!row.account || row.account === account && (row.blocked || row.event.resource_id === context.resourceId && row.event.release_id !== context.releaseId)))
  }

  close() { this.connection?.close(); this.connection = null }
}

export function projectCoursewareProgress(events, { resource_id, release_id }) {
  const relevant = (events || []).filter(item => item.resource_id === resource_id && item.release_id === release_id)
  return { resource_id, release_id,
    viewed_scene_ids: [...new Set(relevant.filter(item => item.event_type === 'scene_viewed').map(item => item.scene_id).filter(Boolean))].sort(),
    completed_scene_ids: [...new Set(relevant.filter(item => item.event_type === 'scene_completed').map(item => item.scene_id).filter(Boolean))].sort(),
    courseware_completed: relevant.some(item => item.event_type === 'courseware_completed'),
    answer_count: relevant.filter(item => item.event_type === 'answer_submitted').length }
}
