import { ref } from 'vue'
import { runApi } from '../../api/index.js'
import { createRunEventClient } from '../runs/api.js'
import {
  applyRunSnapshot, createInitialTimelineState, hydrateWorkflowTimeline, reduceWorkflowEvent,
} from '../../utils/workflowEventReducer.js'

/** Track the selected text-generation run; the page owns shared state and cleanup. */
export function useGenerationProgress({
  selectedRunId,
  selectedJob,
  timelineState,
  connectionStatus,
  isMounted,
  refreshStatus,
  loadClaimReports,
}) {
  const pollTimer = ref(null)
  let streamClient = null
  let streamGeneration = 0
  let publishedResourceRefreshTimer = null

  function stopPolling() {
    if (pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  }

  function closeRealtime() {
    streamGeneration += 1
    streamClient?.close()
    streamClient = null
  }

  function cancelPublishedResourceRefresh() {
    if (publishedResourceRefreshTimer !== null) {
      clearTimeout(publishedResourceRefreshTimer)
      publishedResourceRefreshTimer = null
    }
  }

  function queuePublishedResourceRefresh(runId) {
    if (runId !== selectedRunId.value || publishedResourceRefreshTimer !== null) return
    // A resource_published event is appended only after the resource itself is
    // durable. Coalesce a burst from the same reviewer/finalizer node so the
    // resource list and job summary refresh once rather than once per resource.
    publishedResourceRefreshTimer = setTimeout(() => {
      publishedResourceRefreshTimer = null
      if (runId === selectedRunId.value) void refreshStatus()
    }, 0)
  }

  async function hydrateTimeline(runId, generation) {
    let state = createInitialTimelineState()
    let afterSequence = 0
    let firstPage = true
    try {
      while (true) {
        const response = await runApi.timeline(runId, { after_sequence: afterSequence, limit: 500 })
        if (!isMounted() || generation !== streamGeneration || runId !== selectedRunId.value) return 0
        if (firstPage) {
          state = hydrateWorkflowTimeline(response.data)
          firstPage = false
        } else {
          for (const event of response.data.events || []) state = reduceWorkflowEvent(state, event)
        }
        if (!response.data.next_event_sequence) break
        afterSequence = response.data.next_event_sequence
      }
    } catch (error) {
      // A queued GenerationJob can legitimately precede AgentRun creation.
      if (error?.response?.status !== 404) throw error
    }
    if (isMounted() && generation === streamGeneration && runId === selectedRunId.value) timelineState.value = state
    return state.lastSequence
  }

  async function startRealtime(runId) {
    if (!isMounted() || (runId && runId !== selectedRunId.value)) return
    closeRealtime()
    stopPolling()
    timelineState.value = createInitialTimelineState()
    if (!runId) {
      connectionStatus.value = 'idle'
      return
    }
    const generation = streamGeneration
    connectionStatus.value = 'connecting'
    let lastSequence = 0
    try {
      lastSequence = await hydrateTimeline(runId, generation)
    } catch (error) {
      if (!isMounted() || generation !== streamGeneration) return
      console.error(error)
      connectionStatus.value = 'fallback'
      startPolling()
      return
    }
    if (generation !== streamGeneration) return
    streamClient = createRunEventClient({
      runId,
      afterSequence: lastSequence,
      onSnapshot: (snapshot) => {
        if (generation !== streamGeneration) return
        timelineState.value = applyRunSnapshot(timelineState.value, snapshot)
        connectionStatus.value = snapshot.is_terminal ? 'terminal' : 'live'
      },
      onWorkflowEvent: (event) => {
        if (generation !== streamGeneration) return
        timelineState.value = reduceWorkflowEvent(timelineState.value, event)
        if (event.event_type === 'resource_published') queuePublishedResourceRefresh(runId)
      },
      onTerminal: async () => {
        if (generation !== streamGeneration) return
        connectionStatus.value = 'terminal'
        await refreshStatus()
        if (generation !== streamGeneration) return
        await loadClaimReports(runId)
        if (generation !== streamGeneration) return
        // The durable Run event can be observed immediately before the
        // background task marks its GenerationJob completed. Keep a short
        // fallback poll only for that hand-off window so the UI cannot remain
        // stuck at "generating" after the SSE stream has ended.
        if (selectedJob.value && ['queued', 'running'].includes(selectedJob.value.job_status)) {
          startPolling()
        }
      },
      onError: (error) => {
        if (generation !== streamGeneration) return
        if (error?.code !== 'SSE_TRANSPORT_DISCONNECTED') connectionStatus.value = 'error'
      },
      onFallback: () => {
        if (generation !== streamGeneration) return
        connectionStatus.value = 'fallback'
        startPolling()
      },
    })
    streamClient.connect()
  }

  function startPolling() {
    stopPolling()
    if (!selectedJob.value || !['queued', 'running'].includes(selectedJob.value.job_status)) {
      return
    }
    pollTimer.value = setInterval(refreshStatus, 5000)
  }

  return {
    stopPolling,
    closeRealtime,
    cancelPublishedResourceRefresh,
    queuePublishedResourceRefresh,
    startRealtime,
    startPolling
  }
}
