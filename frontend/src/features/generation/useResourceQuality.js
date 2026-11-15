import { watch } from 'vue'
import { runApi } from '../runs/queryApi.js'

/**
 * Load the versioned run quality projection without recomputing any metric.
 *
 * The hook keeps the request-generation discipline used by the other loaders:
 * a response is accepted only when it still belongs to the selected learner/run
 * and the run has not been switched meanwhile.  Failures degrade to an empty
 * map (the cards then show "—" with a reason), never to a fake number.
 *
 * @param {{
 *   selectedRunId: import('vue').Ref<string>,
 *   selectedLearnerId: import('vue').Ref<string>,
 *   resourceQuality: import('vue').Ref<Record<string, unknown>>,
 *   isMounted: () => boolean,
 *   requestVersion: () => number,
 *   nextRequestVersion: () => number,
 * }} options
 */
export function useResourceQuality({
  selectedRunId,
  selectedLearnerId,
  resourceQuality,
  isMounted,
  requestVersion,
  nextRequestVersion,
}) {
  watch([selectedRunId, selectedLearnerId], () => {
    nextRequestVersion()
    resourceQuality.value = {}
  }, { flush: 'sync' })

  async function loadResourceQuality(runId = selectedRunId.value) {
    if (!runId) return
    const version = nextRequestVersion()
    const learnerId = selectedLearnerId.value
    const isCurrent = () => isMounted() && version === requestVersion()
      && learnerId === selectedLearnerId.value && runId === selectedRunId.value
    try {
      const response = await runApi.resourceQuality(runId)
      if (!isCurrent()) return
      if (response.data.run_id !== runId) throw new Error('Resource-quality response Run mismatch')
      const next = {}
      for (const item of response.data.items || []) {
        // One item per resource version; the card binds by resource_id and the
        // backend guarantees the newest published version per resource.
        const existing = next[item.resource_id]
        if (!existing || (item.published && !existing.published)) next[item.resource_id] = item
      }
      resourceQuality.value = next
    } catch (error) {
      if (!isCurrent()) return
      resourceQuality.value = {}
      if (error?.response?.status !== 404) console.error(error)
    }
  }

  return { loadResourceQuality }
}
