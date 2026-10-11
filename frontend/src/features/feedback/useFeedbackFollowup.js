
import { createRequestGuard } from '../../utils/requestContext.js'

/** Submit the existing follow-up choices and keep their payloads and navigation intact. */
export function useFeedbackFollowup({
  feedbackApi,
  form,
  result,
  selectingOption,
  selectedResourceTypes,
  includeClaimCheck,
  generationOptions,
  selectedDifficulty,
  learningIntent,
  selectedNodesForFollowup,
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

  async function selectFeedbackOption(optionId) {
    const learnerId = form.learner_id
    const attemptId = result.value?.attempt?.attempt_id
    if (!attemptId) return
    const request = requests.capture()
    if (!request.isCurrent()) return
    selectingOption.value = optionId
    try {
      const res = await feedbackApi.selectFollowup({
        learner_id: learnerId,
        attempt_id: attemptId,
        option_id: optionId,
        resource_types: selectedResourceTypes.value,
        include_claim_check: includeClaimCheck.value,
        ...(!generationOptions.value ? { difficulty: selectedDifficulty.value } : {}),
        ...(generationOptions.value ? {
          learning_intent: learningIntent.value,
          selected_skill_node_ids: selectedNodesForFollowup.value,
          next_generation_snapshot_hash: generationOptions.value.snapshot_hash,
        } : {}),
      })
      if (!request.isCurrent()) return
      result.value = res.data
      messages.success('已确认下一步资源方案，正在创建生成任务')
    } catch (error) {
      if (!request.isCurrent()) return
      console.error(error)
      messages.error(error?.response?.data?.message || error?.response?.data?.detail || '资源方案确认失败')
    } finally {
      if (request.isCurrent() && selectingOption.value === optionId) selectingOption.value = ''
    }
  }

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
    selectFeedbackOption,
    selectCorrectionPackage,
    goToFollowupRun,
    dispose: () => requests.dispose(),
  }
}
