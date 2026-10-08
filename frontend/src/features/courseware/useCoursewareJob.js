import { ref } from 'vue'
import { coursewareApi } from './api.js'

const TERMINAL_STATES = new Set([
  'published', 'published_with_warnings', 'quarantined',
  'failed', 'rejected_admission', 'release_blocked', 'cancelled', 'timed_out',
])
const ACTIVE_RUN_STORAGE_KEY = 'courseware_active_run_id'

function activeRunStorage() {
  return globalThis.window?.localStorage || null
}

export function useCoursewareJob() {
  const busy = ref(false)
  const currentJob = ref(null)

  async function refresh(runId) {
    if (!runId) return null
    currentJob.value = (await coursewareApi.getJobDetail(runId)).data
    if (TERMINAL_STATES.has(currentJob.value?.status)) activeRunStorage()?.removeItem?.(ACTIVE_RUN_STORAGE_KEY)
    return currentJob.value
  }

  async function waitForTerminal(runId, { timeoutMs = 20 * 60 * 1000, intervalMs = 1000 } = {}) {
    const deadline = Date.now() + Math.max(0, timeoutMs)
    do {
      await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
      const job = await refresh(runId)
      if (job && TERMINAL_STATES.has(job.status)) return job
    } while (Date.now() < deadline)
    return currentJob.value
  }

  function streamProgress(runId) {
    if (!runId || typeof EventSource === 'undefined') return () => {}
    let closed = false
    const stream = new EventSource(coursewareApi.eventsUrl(runId))
    const refreshFromEvent = async () => {
      if (closed) return
      try { await refresh(runId) } catch (_) { /* polling remains the recovery path */ }
    }
    stream.addEventListener('courseware_progress', refreshFromEvent)
    stream.onerror = () => stream.close()
    return () => { closed = true; stream.close() }
  }

  async function create(payload) {
    busy.value = true
    try {
      currentJob.value = (await coursewareApi.createJob(payload)).data
      if (currentJob.value?.run_id) activeRunStorage()?.setItem(ACTIVE_RUN_STORAGE_KEY, currentJob.value.run_id)
      return currentJob.value
    } finally {
      busy.value = false
    }
  }

  async function retry() {
    const runId = currentJob.value?.run_id
    if (!runId) return null
    busy.value = true
    try {
      await coursewareApi.retryJob(runId)
      return await waitForTerminal(runId)
    } finally {
      busy.value = false
    }
  }

  async function retryScene(sceneId) {
    const runId = currentJob.value?.run_id
    if (!runId || !sceneId) return null
    busy.value = true
    try {
      await coursewareApi.retryScene(runId, sceneId)
      return await waitForTerminal(runId)
    } finally {
      busy.value = false
    }
  }

  async function restoreActiveRun() {
    const runId = activeRunStorage()?.getItem(ACTIVE_RUN_STORAGE_KEY)
    return runId ? refresh(runId) : null
  }

  return { busy, create, currentJob, refresh, restoreActiveRun, retry, retryScene, streamProgress, waitForTerminal }
}
