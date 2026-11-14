
import { createRequestGuard } from '../../utils/requestContext.js'

/** Submit legacy correction choices and navigate to confirmed historical resources. */
export function useFeedbackFollowup({
  feedbackApi,
  form,
  result,
  selectingOption,
  includeClaimCheck,
  includeClaimEvidenceRetrieval,
  claimPostRetrievalMaxIterations,
  generationOptions,
  correctionPackageOption,
  router,
  messages,
  contextVersion,
}) {
  const requests = createRequestGuard(() => ({
    learnerId: form.learner_id,
    contextVersion: contextVersion?.value || 0,
    attemptId: result.value?.attempt?.attempt_id || '',
    snapshotHash: generationOptions.value?.snapshot_hash || '',
  }))

  async function selectCorrectionPackage() {
    const option = correctionPackageOption.value
    if (!option?.eligible || !result.value?.attempt?.attempt_id || !generationOptions.value) return
    const learnerId = form.learner_id
    const attemptId = result.value.attempt.attempt_id
    const request = requests.capture()
    if (!request.isCurrent()) return
    selectingOption.value = option.option_id
    try {
      const res = await feedbackApi.selectFollowup({
        learner_id: learnerId, attempt_id: attemptId,
        option_id: option.option_id, learning_intent: 'reinforce_weakness',
        include_claim_check: includeClaimCheck.value,
        ...(includeClaimCheck.value && includeClaimEvidenceRetrieval?.value ? {
          claim_post_retrieval_max_iterations: claimPostRetrievalMaxIterations?.value ?? 0,
        } : {}),
        include_claim_evidence_retrieval: Boolean(
          includeClaimCheck.value && includeClaimEvidenceRetrieval?.value,
        ),
        selected_skill_node_ids: option.recommended_target_ids,
        next_generation_snapshot_hash: option.snapshot_hash,
      })
      if (!request.isCurrent()) return
      result.value = res.data
      messages.success('纠错包与新测评题正在创建')
    } catch (error) {
      if (!request.isCurrent()) return
      console.error(error)
      messages.error(error?.response?.data?.message || error?.response?.data?.detail || '强化包创建失败')
    } finally {
      if (request.isCurrent() && selectingOption.value === option.option_id) selectingOption.value = ''
    }
  }

  function goToFollowupRun() {
    const runIds = result.value?.followup_run_ids?.length ? result.value.followup_run_ids : [result.value?.followup_run_id]
    const runId = runIds[0]
    if (!runId) return
    localStorage.setItem('current_generation_run_id', runId)
    localStorage.setItem('current_generation_run_ids', JSON.stringify(runIds.filter(Boolean)))
    router.push({ path: '/generate', query: { runId, learnerId: form.learner_id } })
  }

  return {
    selectCorrectionPackage,
    goToFollowupRun,
    dispose: () => requests.dispose(),
  }
}
