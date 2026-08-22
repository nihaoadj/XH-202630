import { ref } from 'vue'
import { coursewareApi } from '../../api/courseware'

const TERMINAL_STATES = new Set([
  'approved_pending_publish', 'published', 'published_with_warnings',
  'failed', 'rejected_admission',
])

export function useCoursewareJob() {
  const busy = ref(false)
  const currentJob = ref(null)

  async function refresh(runId) {
    if (!runId) return null
    currentJob.value = (await coursewareApi.getJobDetail(runId)).data
    return currentJob.value
  }

  async function waitForTerminal(runId, { attempts = 20, intervalMs = 500 } = {}) {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
      const job = await refresh(runId)
      if (job && TERMINAL_STATES.has(job.status)) return job
    }
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

  async function publish() {
    const runId = currentJob.value?.run_id
    if (!runId) return null
    busy.value = true
    try {
      await coursewareApi.publishJob(runId)
      return await refresh(runId)
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

  return { busy, create, currentJob, publish, refresh, retry, retryScene, streamProgress, waitForTerminal }
}
