// Deliberately local to the report feature: this is a current-state invalidator,
// not a durable event ledger.
export class ReportStreamClient {
  constructor({ fetchReport, onStatus, onReport, pollMs = 30000 }) {
    this.fetchReport = fetchReport
    this.onStatus = onStatus || (() => {})
    this.onReport = onReport || (() => {})
    this.pollMs = pollMs
    this.source = null
    this.timer = null
    this.errors = 0
    this.generation = 0
    this.pending = false
    this.pendingRefresh = false
  }

  start({ learnerId, windowDays, revision }) {
    this.stop()
    this.learnerId = learnerId; this.windowDays = windowDays; this.revision = revision
    this.generation += 1; this.errors = 0
    this._connect(this.generation)
  }

  stop() { if (this.source) this.source.close(); this.source = null; clearInterval(this.timer); this.timer = null; clearTimeout(this.debounce); this.onStatus('closed') }
  refresh(force = false) { return this._refresh(this.generation, force) }

  _connect(generation) {
    if (!this.learnerId || typeof EventSource === 'undefined') return this._poll(generation)
    this.onStatus('connecting')
    const query = new URLSearchParams({ window_days: this.windowDays })
    if (this.revision) query.set('after_revision', this.revision)
    const source = new EventSource(`/api/report/${encodeURIComponent(this.learnerId)}/events?${query}`)
    this.source = source
    source.onopen = () => { if (generation === this.generation) this.onStatus('live') }
    const scheduleRefresh = (payload, { onlyWhenRevisionChanges }) => {
      if (generation !== this.generation) return
      if (payload.learner_id !== this.learnerId || payload.window_days !== this.windowDays) return
      const revisionChanged = payload.report_revision !== this.revision
      this.pendingRefresh = this.pendingRefresh || this.pending
      this.revision = payload.report_revision
      // A reconnect always contains a snapshot.  It is an invalidation only
      // when it represents facts newer than the report already on screen.
      if (onlyWhenRevisionChanges && !revisionChanged) return
      clearTimeout(this.debounce); this.debounce = setTimeout(() => this._refresh(generation), 250)
    }
    source.addEventListener('report_snapshot', (event) => scheduleRefresh(JSON.parse(event.data), { onlyWhenRevisionChanges: true }))
    source.addEventListener('report_changed', (event) => scheduleRefresh(JSON.parse(event.data), { onlyWhenRevisionChanges: false }))
    source.onerror = () => {
      if (generation !== this.generation) return
      this.errors += 1
      if (this.errors >= 3) { source.close(); this.source = null; this._poll(generation) } else this.onStatus('reconnecting')
    }
  }

  _poll(generation) { this.onStatus('polling'); clearInterval(this.timer); this.timer = setInterval(() => this._refresh(generation), this.pollMs) }
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
    } finally {
      this.pending = false
      if (this.pendingRefresh) { this.pendingRefresh = false; this._refresh(generation) }
    }
  }

  _online() { return typeof navigator === 'undefined' || navigator.onLine !== false }
}
