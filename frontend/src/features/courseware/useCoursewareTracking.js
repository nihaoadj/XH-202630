import { coursewareApi } from './api.js'
import { createRequestGuard } from '../../utils/requestContext.js'

const terminalStates = new Set(['published', 'published_with_warnings', 'quarantined', 'failed', 'rejected_admission', 'release_blocked', 'cancelled', 'timed_out'])

/** Production task history, restoration, SSE and polling. Dispose on unmount. */
export function useCoursewareTracking({
  selectedLearnerId,
  selectedRunId,
  jobs,
  currentJob,
  connectionStatus,
  published,
  rememberedRunId,
  syncRoute,
  emit,
  messages,
}) {
  let stream = null
  let pollTimer = null
  let publishedRunId = ''
  const listRequests = createRequestGuard(() => ({ learnerId: selectedLearnerId.value }))
  const detailRequests = createRequestGuard(() => ({
    learnerId: selectedLearnerId.value,
    runId: selectedRunId.value,
  }))
  const trackingRequests = createRequestGuard(() => ({
    learnerId: selectedLearnerId.value,
    runId: selectedRunId.value,
  }))

  function stopTracking() {
    trackingRequests.invalidate()
    const activeStream = stream
    stream = null
    activeStream?.close()
    if (pollTimer !== null) {
      window.clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function dispose() {
    stopTracking()
    listRequests.dispose()
    detailRequests.dispose()
    trackingRequests.dispose()
  }

  async function loadJobs() {
    const learnerId = selectedLearnerId.value
    const request = listRequests.capture()
    if (!request.isCurrent()) return
    if (!learnerId) {
      stopTracking()
      jobs.value = []
      selectedRunId.value = ''
      currentJob.value = null
      connectionStatus.value = 'idle'
      return
    }

    const restoredRunId = rememberedRunId()
    try {
      const response = await coursewareApi.listJobs(learnerId)
      if (!request.isCurrent()) return
      jobs.value = response.data.items || []
    } catch (error) {
      if (!request.isCurrent()) return
      // Keep detail recovery for rolling deployments whose list endpoint is older.
      jobs.value = []
      if (!restoredRunId) {
        stopTracking()
        selectedRunId.value = ''
        currentJob.value = null
        connectionStatus.value = 'error'
        messages.error(error?.response?.data?.detail || '课件任务列表加载失败')
        return
      }
      try {
        const response = await coursewareApi.getJobDetail(restoredRunId)
        if (!request.isCurrent()) return
        jobs.value = [response.data]
      } catch (restoreError) {
        if (!request.isCurrent()) return
        stopTracking()
        selectedRunId.value = ''
        currentJob.value = null
        connectionStatus.value = 'error'
        messages.error(restoreError?.response?.data?.detail || '无法恢复已创建的课件任务')
        return
      }
    }
    if (!request.isCurrent()) return
    if (!jobs.value.some((job) => job.run_id === selectedRunId.value)) {
      selectedRunId.value = jobs.value.some((job) => job.run_id === restoredRunId) ? restoredRunId : jobs.value[0]?.run_id || ''
    }
    await loadCurrentJob()
  }

  async function loadCurrentJob() {
    const learnerId = selectedLearnerId.value
    const runId = selectedRunId.value
    const request = detailRequests.capture()
    stopTracking()
    if (!request.isCurrent()) return
    if (!learnerId || !runId) {
      currentJob.value = null
      connectionStatus.value = 'idle'
      return
    }
    try {
      const response = await coursewareApi.getJobDetail(runId)
      if (!request.isCurrent()) return
      currentJob.value = response.data
      const position = jobs.value.findIndex((job) => job.run_id === runId)
      if (position >= 0) jobs.value.splice(position, 1, { ...jobs.value[position], ...response.data })
      syncRoute()
      if (terminalStates.has(currentJob.value.status)) {
        connectionStatus.value = 'terminal'
        return
      }
      startTracking(runId)
    } catch (error) {
      if (!request.isCurrent()) return
      connectionStatus.value = 'error'
      messages.error(error?.response?.data?.detail || '课件任务加载失败')
    }
  }

  function startTracking(runId) {
    if (!runId || runId !== selectedRunId.value) return
    if (typeof EventSource === 'undefined') {
      startPolling(runId)
      return
    }
    const request = trackingRequests.capture()
    if (!request.isCurrent()) return
    connectionStatus.value = 'live'
    const newStream = new EventSource(coursewareApi.eventsUrl(runId))
    stream = newStream
    const isCurrentStream = () => request.isCurrent()
      && stream === newStream
      && selectedRunId.value === runId
    newStream.addEventListener('courseware_progress', () => {
      if (isCurrentStream()) void refreshCurrentJob(runId)
    })
    newStream.onerror = () => {
      newStream.close()
      if (!isCurrentStream()) return
      stream = null
      startPolling(runId)
    }
  }

  function startPolling(runId = selectedRunId.value) {
    if (pollTimer !== null || !runId || runId !== selectedRunId.value || terminalStates.has(currentJob.value?.status)) return
    const activeStream = stream
    stream = null
    activeStream?.close()
    const request = trackingRequests.capture()
    if (!request.isCurrent()) return
    connectionStatus.value = 'polling'
    pollTimer = window.setInterval(() => {
      if (request.isCurrent() && selectedRunId.value === runId) void refreshCurrentJob(runId)
    }, 2500)
  }

  function notifyPublished() {
    if (currentJob.value?.run_id !== selectedRunId.value) return
    if (!published.value || !currentJob.value?.resource_id || publishedRunId === currentJob.value.run_id) return
    publishedRunId = currentJob.value.run_id
    emit('published', currentJob.value)
  }

  async function refreshCurrentJob(expectedRunId = selectedRunId.value) {
    const learnerId = selectedLearnerId.value
    const runId = expectedRunId
    if (!learnerId || !runId || runId !== selectedRunId.value) return
    const request = detailRequests.capture()
    if (!request.isCurrent()) return
    try {
      const response = await coursewareApi.getJobDetail(runId)
      if (!request.isCurrent()) return
      currentJob.value = response.data
      const position = jobs.value.findIndex((job) => job.run_id === runId)
      if (position >= 0) jobs.value.splice(position, 1, { ...jobs.value[position], ...response.data })
      if (terminalStates.has(currentJob.value.status)) {
        stopTracking()
        connectionStatus.value = 'terminal'
        notifyPublished()
      }
    } catch (_) {
      if (request.isCurrent()) startPolling(runId)
    }
  }

  return {
    stopTracking,
    dispose,
    loadJobs,
    loadCurrentJob,
    startTracking,
    startPolling,
    notifyPublished,
    refreshCurrentJob,
  }
}
