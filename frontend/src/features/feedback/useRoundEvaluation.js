import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { roundFeedbackApi } from './roundApi.js'
import { buildRoundSubmission, hasRoundAnswer, readRoundDraft, requireRoundSession, roundDraftKey } from './roundEvaluationState.js'

export function useRoundEvaluation({ context, profileVersion, accountId, onResult, api = roundFeedbackApi }) {
  const session = ref(null)
  const result = ref(null)
  const answers = reactive({})
  const pending = ref(false)
  const error = ref('')
  const draft = ref(null)
  const versionConflict = ref(false)
  let generation = 0
  let timer = null
  let disposed = false
  const signature = () => JSON.stringify({ ...context(), accountId: accountId() })
  const questions = computed(() => session.value?.groups.flatMap(group => group.questions) || [])
  const answeredCount = computed(() => questions.value.filter(question => hasRoundAnswer(answers[question.question_id])).length)
  const canSubmit = computed(() => questions.value.length > 0 && answeredCount.value === questions.value.length && !pending.value)
  function reset() {
    ++generation; clearTimeout(timer); timer = null
    session.value = null; result.value = null; draft.value = null; pending.value = false; error.value = ''; versionConflict.value = false
    Object.keys(answers).forEach(key => delete answers[key])
  }
  function capture() { const token = generation; const key = signature(); return () => !disposed && token === generation && key === signature() }
  function storeDraft(value) {
    if (!session.value) return
    try {
      const key = roundDraftKey(accountId(), context().learnerId, session.value.session_id)
      if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key)
    } catch { /* Storage failures must not prevent a valid submission. */ }
  }
  function accept(value) {
    if (!Array.isArray(value?.nodes) || !value.attempt_id) throw new Error('联合反馈结果格式无效')
    result.value = value; pending.value = false; draft.value = null; storeDraft(null); onResult(value)
  }
  async function restoreSession(isCurrent) {
    if (session.value) return
    const { learnerId, roundId, stageId } = context()
    const response = await api.session(roundId, stageId, learnerId)
    if (!isCurrent()) return
    session.value = requireRoundSession(response.data)
    let saved = draft.value
    if (!saved) {
      try { saved = readRoundDraft(sessionStorage, roundDraftKey(accountId(), learnerId, session.value.session_id), session.value) } catch { /* An in-memory draft remains valid without browser storage. */ }
    }
    draft.value = saved
    for (const question of questions.value) {
      answers[question.question_id] = saved?.answers.find(item => item.question_id === question.question_id)?.answer
        ?? (question.question_type === 'multiple_choice' ? [] : '')
    }
  }
  async function poll(isCurrent) {
    timer = null
    const { roundId, stageId } = context()
    try {
      const response = await api.result(roundId, stageId)
      if (!isCurrent()) return
      if (response.data?.state === 'grading' || response.status === 202) {
        timer = setTimeout(() => poll(isCurrent), 2000)
      } else if (response.data?.attempt_id) accept(response.data)
      else {
        // Do not reset: the in-memory draft is the authoritative payload when
        // storage is unavailable, including its original key and timestamp.
        await restoreSession(isCurrent)
        if (!isCurrent()) return
        pending.value = false
        error.value = draft.value ? '评分已中断，可使用相同提交内容重试。' : '评分已中断，未找到原提交草稿，无法恢复本次提交。'
      }
    } catch (caught) {
      if (isCurrent()) { pending.value = false; error.value = caught?.response?.data?.message || '结果暂不可用，请恢复查询或重试原提交。' }
    }
  }
  async function load() {
    reset()
    const isCurrent = capture()
    const { learnerId, roundId, stageId } = context()
    if (!learnerId || !roundId || !stageId) return
    pending.value = true
    try {
      const existing = await api.result(roundId, stageId)
      if (!isCurrent()) return
      if (existing.data?.attempt_id) { accept(existing.data); return }
      if (existing.status === 202 || existing.data?.state === 'grading') { await poll(isCurrent); return }
      await restoreSession(isCurrent)
    } catch (caught) {
      if (isCurrent()) error.value = caught?.response?.data?.message || caught?.response?.data?.detail || caught.message || '联合测评加载失败'
    } finally { if (isCurrent() && !timer) pending.value = false }
  }
  async function submit(reflection) {
    if (!canSubmit.value || versionConflict.value) return
    const isCurrent = capture()
    const { learnerId, roundId, stageId } = context()
    pending.value = true; error.value = ''
    try {
      if (draft.value) {
        const previous = await api.result(roundId, stageId)
        if (!isCurrent()) return
        if (previous.data?.attempt_id && previous.status !== 202 && previous.data?.state !== 'grading') { accept(previous.data); return }
        if (previous.status === 202 || previous.data?.state === 'grading') { await poll(isCurrent); return }
      }
      if (!draft.value) {
        draft.value = buildRoundSubmission({ session: session.value, answers, learnerId,
          profileVersion: profileVersion(), key: `round-${crypto.randomUUID()}`, submittedAt: new Date().toISOString(), reflection })
        storeDraft(draft.value)
      }
      const response = await api.submit(roundId, stageId, draft.value)
      if (!isCurrent()) return
      if (response.status === 202 || response.data?.state === 'grading') await poll(isCurrent)
      else accept(response.data)
    } catch (caught) {
      if (!isCurrent()) return
      versionConflict.value = caught?.response?.status === 409 && String(caught?.response?.data?.code || caught?.response?.data?.detail).includes('PROFILE_VERSION')
      error.value = caught?.response?.data?.message || caught?.response?.data?.detail || caught.message || '提交结果尚未确认；重试会复用原提交内容。'
    } finally { if (isCurrent() && !timer) pending.value = false }
  }
  function clearRejectedDraft() { storeDraft(null); draft.value = null; versionConflict.value = false; error.value = '' }
  onBeforeUnmount(() => { disposed = true; reset() })
  return { session, result, answers, pending, error, draft, versionConflict, answeredCount, canSubmit, load, submit, reset, clearRejectedDraft }
}
