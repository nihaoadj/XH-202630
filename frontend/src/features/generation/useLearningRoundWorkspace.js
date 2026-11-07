import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { roundFeedbackApi } from '../feedback/roundApi.js'
import { primaryRoundRun, resolveRoundSelection } from './roundWorkspace.js'

export function useLearningRoundWorkspace({ learnerId, selectedJob, selectedRunId, jobs, route, router, activateRun, api = roundFeedbackApi }) {
  const detail = ref(null)
  const selection = ref({ memberId: '', stageId: '', runId: '' })
  const error = ref('')
  let version = 0
  let timer = null
  let disposed = false
  const primaryJob = computed(() => jobs.value.find(job => job.run_id === primaryRoundRun(detail.value)) || null)
  function stop() { clearTimeout(timer); timer = null }
  async function load(roundId, preserve = true) {
    stop()
    const captured = ++version
    const owner = learnerId.value
    try {
      const response = await api.detail(roundId)
      if (disposed || captured !== version || owner !== learnerId.value) return
      if (response.data.learner_id !== owner) throw new Error('学习轮次不属于当前画像')
      detail.value = response.data
      error.value = ''
      const binding = selectedJob.value?.round_binding
      selection.value = resolveRoundSelection(detail.value, binding?.round_id === roundId
        ? { memberId: binding.member_id, stageId: binding.stage_id, runId: selectedRunId.value }
        : preserve && selection.value.memberId ? { ...selection.value, runId: selectedRunId.value }
          : { memberId: route.query.memberId, stageId: route.query.stageId, runId: selectedRunId.value })
      if (selection.value?.runId && selection.value.runId !== selectedRunId.value) await activateRun(selection.value.runId)
      if (!disposed && captured === version && detail.value.members.some(member => member.state === 'producing')) {
        timer = setTimeout(() => { if (!document.hidden) load(roundId); else scheduleVisible(roundId) }, 5000)
      }
    } catch (caught) {
      if (!disposed && captured === version) error.value = caught?.response?.data?.message || caught.message || '轮次加载失败'
    }
  }
  function scheduleVisible(roundId) { timer = setTimeout(() => { if (!document.hidden) load(roundId); else scheduleVisible(roundId) }, 5000) }
  async function select(changes) {
    if (!detail.value) return
    ++version
    selection.value = resolveRoundSelection(detail.value, {
      ...selection.value, ...changes,
      ...(changes.memberId ? { runId: '', stageId: selection.value.stageId } : changes.stageId ? { runId: '' } : {}),
    })
    const picked = selection.value
    await router.replace({ query: { ...route.query, roundId: detail.value.round_id, memberId: picked.memberId, stageId: picked.stageId, runId: picked.runId } })
    if (!disposed && picked === selection.value && picked.runId) await activateRun(picked.runId)
    if (!disposed) load(detail.value.round_id)
  }
  watch(() => [learnerId.value, selectedJob.value?.round_binding?.round_id, selectedRunId.value], () => {
    ++version; stop()
    const binding = selectedJob.value?.round_binding
    const id = binding?.round_id || (!selectedJob.value && route.query.roundId)
    if (!id) { detail.value = null; selection.value = { memberId: '', stageId: '', runId: '' }; return }
    const same = detail.value?.round_id === id
    if (!same) detail.value = null
    load(id, same)
  }, { immediate: true })
  onBeforeUnmount(() => { disposed = true; ++version; stop() })
  return { detail, selection, primaryJob, error, select, reload: () => detail.value && load(detail.value.round_id) }
}
