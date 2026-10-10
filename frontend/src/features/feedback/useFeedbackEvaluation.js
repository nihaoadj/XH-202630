import { nextTick } from 'vue'
import { countTutorTurns } from '../../utils/tutorState.js'
import { createRequestGuard } from '../../utils/requestContext.js'

/** Assessment sessions, answer submission and tutor counts; the page retains shared state. */
export function useFeedbackEvaluation({
  feedbackApi,
  form,
  selectedRunId,
  pendingCorrectionRunId,
  feedbackResults,
  result,
  evaluation,
  evaluationAnswers,
  tutorOpen,
  tutorQuestion,
  tutorHelpCount,
  canSubmit,
  submitting,
  feedbackStatus,
  activeTask,
  store,
  resultPanelRef,
  feedbackScrollBehavior,
  messages,
  contextVersion,
}) {
  const sessionRequests = createRequestGuard(() => ({
    learnerId: form.learner_id,
    batchId: selectedRunId.value,
    correctionRunId: pendingCorrectionRunId.value,
    contextVersion: contextVersion?.value || 0,
  }))
  const submitRequests = createRequestGuard(() => ({
    learnerId: form.learner_id,
    batchId: selectedRunId.value,
    correctionRunId: pendingCorrectionRunId.value,
    contextVersion: contextVersion?.value || 0,
  }))
  const submitLoadingRequests = createRequestGuard(() => ({}))

  function resetEvaluationAnswers() { Object.keys(evaluationAnswers).forEach((key) => delete evaluationAnswers[key]) }

  function buildIdempotencyKey(runId, submittedAt) {
    return `web-${runId.slice(0, 24)}-${submittedAt.toISOString().replace(/[^0-9]/g, '')}`.slice(0, 128)
  }

  function tutorCountKey(batchId = selectedRunId.value) { return `tutor_help_count:${form.learner_id}:${batchId}` }

  function requestTutorHint(question) { tutorQuestion.value = question; tutorOpen.value = true }

  function recordTutorHelp() {
    tutorHelpCount.value += 1
    localStorage.setItem(tutorCountKey(), String(tutorHelpCount.value))
  }

  function restoreTutorHelp({ turns }) {
    const persisted = Number(localStorage.getItem(tutorCountKey()) || 0)
    tutorHelpCount.value = Math.max(tutorHelpCount.value, persisted, countTutorTurns(turns))
    localStorage.setItem(tutorCountKey(), String(tutorHelpCount.value))
  }

  async function loadEvaluationSession({ forceNew = false } = {}) {
    const learnerId = form.learner_id
    const batchId = selectedRunId.value
    const evaluationRunId = pendingCorrectionRunId.value
    const request = sessionRequests.capture()
    if (!request.isCurrent()) return
    const existing = feedbackResults.value.find((item) => (
      item.attempt?.source_run_id === (evaluationRunId || batchId)
      || (!evaluationRunId && item.attempt?.metadata?.session_id === batchId)
    ))
    if (existing && !forceNew) { result.value = existing; return }
    result.value = null
    if (!learnerId || !batchId) return
    try {
      const res = evaluationRunId
        ? await feedbackApi.getRunEvaluationSession(learnerId, evaluationRunId)
        : await feedbackApi.getBatchEvaluationSession(learnerId, batchId)
      if (!request.isCurrent()) return
      evaluation.topic = res.data.topic || ''
      evaluation.questions = res.data.questions || []
      evaluation.resourceIds = res.data.resource_ids || []
      resetEvaluationAnswers()
      evaluation.questions.forEach((question) => {
        evaluationAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : ''
      })
      localStorage.setItem('current_generation_run_id', evaluationRunId || batchId)
      tutorQuestion.value = null
      tutorHelpCount.value = Number(localStorage.getItem(tutorCountKey()) || 0)
    } catch (error) {
      if (!request.isCurrent()) return
      console.error(error); evaluation.topic = ''; evaluation.questions = []; evaluation.resourceIds = []; resetEvaluationAnswers()
      messages.error(error?.response?.data?.message || '测评题加载失败')
    }
  }

  async function submitEvaluation() {
    if (!canSubmit.value) { messages.warning('请先完成全部测评题。'); return }
    const request = submitRequests.capture()
    const loadingRequest = submitLoadingRequests.capture()
    if (!request.isCurrent() || !loadingRequest.isCurrent()) return
    const learnerId = form.learner_id
    const batchId = selectedRunId.value
    const evaluationRunId = pendingCorrectionRunId.value
    const profileAtSubmission = store.currentProfile
    submitting.value = true
    feedbackStatus.value = '已提交反馈，正在生成反馈报告与建议。'
    try {
      const submittedAt = new Date()
      const payload = {
        learner_id: learnerId, source_resource_id: evaluation.resourceIds[0] || activeTask.value?.resources?.[0]?.resource_id,
        idempotency_key: buildIdempotencyKey(evaluationRunId || batchId, submittedAt), expected_profile_version: store.currentProfile?.profile_version || 1,
        submitted_at: submittedAt.toISOString(), duration_ms: (form.time_spent_seconds || 0) * 1000, hint_count: tutorHelpCount.value,
        answers: evaluation.questions.map((question) => ({ question_id: question.question_id, answer: evaluationAnswers[question.question_id] })),
        metadata: {
          source: 'feedback_view',
          client_version: 'web',
          session_id: evaluationRunId || batchId,
          learning_reflection: {
            completed: form.completed,
            time_spent_seconds: form.time_spent_seconds,
            self_rating: form.self_rating,
            difficulty_feeling: form.difficulty_feeling,
            helpful_part: form.helpful_part.trim(),
            confusing_part: form.confusing_part.trim(),
            comment: form.comment.trim()
          }
        },
      }
      const res = evaluationRunId
        ? await feedbackApi.submitRunAttempt({ ...payload, run_id: evaluationRunId })
        : await feedbackApi.submitBatchAttempt({ ...payload, batch_id: batchId })
      if (!request.isCurrent()) return
      result.value = res.data
      feedbackResults.value = [res.data, ...feedbackResults.value.filter((item) => item.attempt?.attempt_id !== res.data.attempt?.attempt_id)]
      if (store.currentProfile && (
        store.currentProfile === profileAtSubmission
        || store.currentProfile.learner_id === learnerId
      )) {
        store.setCurrentProfile({ ...store.currentProfile, profile_version: res.data.profile_version })
      }
      messages.success('本轮练习反馈已提交')
      await nextTick()
      if (!request.isCurrent()) return
      resultPanelRef.value?.scrollIntoView({ behavior: feedbackScrollBehavior(), block: 'start' })
      feedbackStatus.value = ''
    } catch (error) {
      if (!request.isCurrent()) return
      console.error(error)
      feedbackStatus.value = ''
      messages.error(error?.response?.data?.message || '提交失败，请稍后再试')
    } finally {
      if (loadingRequest.isCurrent()) submitting.value = false
    }
  }

  return {
    resetEvaluationAnswers,
    buildIdempotencyKey,
    tutorCountKey,
    requestTutorHint,
    recordTutorHelp,
    restoreTutorHelp,
    loadEvaluationSession,
    submitEvaluation,
    dispose() {
      sessionRequests.dispose()
      submitRequests.dispose()
      submitLoadingRequests.dispose()
    },
  }
}
