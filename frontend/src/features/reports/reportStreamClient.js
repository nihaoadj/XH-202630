import { isRecord, isReportInvalidation } from '../../contracts/guards.js'

// Deliberately local to the report feature: this is a current-state invalidator,
// not a durable event ledger.
export class ReportStreamClient {
  /** @param {{fetchReport: (context: import('../../contracts/ports').ReportFetchRequest) => Promise<import('../../contracts/ports').ReportSnapshot | null>, onStatus?: (status: string) => void, onReport?: (report: import('../../contracts/generated/contracts').CurrentReportResponse) => void, pollMs?: number}} options */
  constructor({ fetchReport, onStatus, onReport, pollMs = 30000 }) {
    this.fetchReport = fetchReport
    this.onStatus = onStatus || (() => {})
    this.onReport = onReport || (() => {})
    this.pollMs = pollMs
    /** @type {EventSource | null} */
    this.source = null
    /** @type {number | null} */
    this.timer = null
    /** @type {number | undefined} */
    this.debounce = undefined
    this.learnerId = ''
    /** @type {import('../../contracts/generated/contracts').ReportWindowDays} */
    this.windowDays = 30
    /** @type {string | null} */
    this.revision = null
    this.errors = 0
    this.generation = 0
    this.pending = false
    this.pendingRefresh = false
  }

  /** @param {import('../../contracts/ports').ReportContext} context */
  start({ learnerId, windowDays, revision }) {
    this.stop()
    this.learnerId = learnerId; this.windowDays = windowDays; this.revision = revision ?? null
    this.generation += 1; this.errors = 0
    this._connect(this.generation)
  }

  stop() {
    this.generation += 1
    if (this.source) this.source.close()
    this.source = null
    if (this.timer !== null) clearInterval(this.timer)
    this.timer = null; clearTimeout(this.debounce)
    this.pending = false; this.pendingRefresh = false
    this.onStatus('closed')
  }
  refresh(force = false) { return this._refresh(this.generation, force) }

  /** @param {number} generation */
  _connect(generation) {
    if (!this.learnerId || typeof EventSource === 'undefined') return this._poll(generation)
    this.onStatus('connecting')
    const query = new URLSearchParams({ window_days: String(this.windowDays) })
    if (this.revision) query.set('after_revision', this.revision)
    const source = new EventSource(`/api/report/${encodeURIComponent(this.learnerId)}/events?${query}`)
    this.source = source
    source.onopen = () => { if (generation === this.generation) this.onStatus('live') }
    /** @param {unknown} payload @param {{onlyWhenRevisionChanges: boolean}} options */
    const scheduleRefresh = (payload, { onlyWhenRevisionChanges }) => {
      if (generation !== this.generation) return
      if (!isReportInvalidation(payload)) return
      if (payload.learner_id !== this.learnerId || payload.window_days !== this.windowDays) return
      const revisionChanged = payload.report_revision !== this.revision
      this.pendingRefresh = this.pendingRefresh || this.pending
      // A reconnect always contains a snapshot.  It is an invalidation only
      // when it represents facts newer than the report already on screen.
      if (onlyWhenRevisionChanges && !revisionChanged) return
      // Keep the on-screen revision until the full payload has arrived. If we
      // set it here, the conditional request below sends the *new* ETag and
      // the server correctly responds 304, leaving stale charts on screen.
      clearTimeout(this.debounce); this.debounce = setTimeout(() => this._refresh(generation, true), 250)
    }
    /** @param {unknown} event @param {boolean} onlyWhenRevisionChanges */
    const receive = (event, onlyWhenRevisionChanges) => {
      if (!isRecord(event) || typeof event.data !== 'string') return
      try { scheduleRefresh(JSON.parse(event.data), { onlyWhenRevisionChanges }) }
      catch { /* A malformed frame cannot replace current report state. */ }
    }
    source.addEventListener('report_snapshot', event => receive(event, true))
    source.addEventListener('report_changed', event => receive(event, false))
    source.onerror = () => {
      if (generation !== this.generation) return
      this.errors += 1
      if (this.errors >= 3) { source.close(); this.source = null; this._poll(generation) } else this.onStatus('reconnecting')
    }
  }

  /** @param {number} generation */
  _poll(generation) {
    this.onStatus('polling')
    if (this.timer !== null) clearInterval(this.timer)
    this.timer = setInterval(() => this._refresh(generation), this.pollMs)
  }
  /** @param {number} generation @param {boolean} force @returns {Promise<void>} */
  async _refresh(generation, force = false) {
    if (generation !== this.generation || !this._online()) return
    if (this.pending) { this.pendingRefresh = true; return }
    this.pending = true
    try {
      const result = await this.fetchReport({ learnerId: this.learnerId, windowDays: this.windowDays, etag: force ? null : this.revision })
      if (generation === this.generation && result && result.data?.learner_id === this.learnerId
        && result.data?.window?.window_days === this.windowDays) {
        this.revision = result.revision
        this.onReport(result.data)
      }
    } catch {
      if (generation === this.generation) this.onStatus('reconnecting')
    } finally {
      if (generation === this.generation) {
        this.pending = false
        if (this.pendingRefresh) { this.pendingRefresh = false; this._refresh(generation) }
      }
    }
  }

  _online() { return typeof navigator === 'undefined' || navigator.onLine !== false }
}
