import { onBeforeUnmount, ref, watch } from 'vue'
import { runApi } from '../runs/queryApi.js'
import { createRequestGuard } from '../../utils/requestContext.js'
import { associatedStepResources } from './generationAudit.js'
import { canInspectStep } from './workflowPresentation.js'

export function useGenerationAudit({ selectedRunId, selectedLearnerId }) {
  const visible = ref(false), loading = ref(false), error = ref(''), claimsError = ref('')
  const snapshot = ref({}), claims = ref({}), step = ref(null), resourceId = ref('')
  let resourceSpecId = ''
  let representation = ''
  const guard = createRequestGuard(() => ({ learner: selectedLearnerId.value, run: selectedRunId.value, visible: visible.value }))

  function reset() {
    guard.invalidate()
    visible.value = false; loading.value = false; error.value = ''; claimsError.value = ''
    snapshot.value = {}; claims.value = {}; step.value = null; resourceId.value = ''
    resourceSpecId = ''
    representation = ''
  }
  watch([selectedRunId, selectedLearnerId], reset, { flush: 'sync' })
  watch(visible, value => { if (!value) guard.invalidate() }, { flush: 'sync' })
  onBeforeUnmount(() => guard.dispose())

  async function refresh() {
    if (!selectedRunId.value || !visible.value) return
    const request = guard.capture(), runId = selectedRunId.value
    loading.value = true; error.value = ''; claimsError.value = ''
    snapshot.value = {}; claims.value = {}
    const [timelineResult, claimsResult] = await Promise.allSettled([
      runApi.timeline(runId, { limit: 500 }), runApi.claims(runId),
    ])
    if (!request.isCurrent()) return
    if (timelineResult.status === 'fulfilled' && (!timelineResult.value.data?.run?.run_id || timelineResult.value.data.run.run_id === runId)) {
      snapshot.value = timelineResult.value.data || {}
      if (step.value) step.value = (snapshot.value.steps || []).find(item => item.step_id === step.value.step_id
        && (!item.run_id || item.run_id === runId)) || step.value
      if (step.value) {
        const linked = associatedStepResources(snapshot.value, step.value, runId)
        if (!linked.some(item => item.resource_id === resourceId.value)) resourceId.value = linked[0]?.resource_id || ''
      } else {
        const candidates = (snapshot.value.resource_versions || []).filter(item => item.run_id === runId
          && (!resourceSpecId || item.resource_spec_id === resourceSpecId)
          && (!representation || (item.representation || 'text') === representation))
          .sort((a, b) => Number(b.version || 0) - Number(a.version || 0))
        if (!resourceId.value && resourceSpecId) resourceId.value = candidates[0]?.resource_id || ''
      }
    } else error.value = '执行详情加载失败，请刷新重试。'
    if (claimsResult.status === 'fulfilled' && (!claimsResult.value.data?.run_id || claimsResult.value.data.run_id === runId)) {
      claims.value = claimsResult.value.data || {}
    } else claimsError.value = 'Claim 判定加载失败，不能据此判断事实已通过。'
    loading.value = false
  }
  function openStep(value) {
    if (!canInspectStep(value) || (value.run_id && value.run_id !== selectedRunId.value)) return
    step.value = value; resourceId.value = value.resource_ids?.[0] || ''
    resourceSpecId = ''
    representation = ''
    visible.value = true; refresh()
  }
  function openResource(value) {
    step.value = null; resourceId.value = value.resource_id || ''
    resourceSpecId = value.resource_spec_id || ''
    representation = value.representation || 'text'
    visible.value = true; refresh()
  }
  return { visible, loading, error, claimsError, snapshot, claims, step, resourceId, refresh, openStep, openResource }
}
