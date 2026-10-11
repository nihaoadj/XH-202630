import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildTutorStorageKey,
  countTutorTurns,
  mergeTutorTurn,
} from '../src/utils/tutorState.js'

const key = buildTutorStorageKey({
  learnerId: 'learner-1',
  contextType: 'question_help',
  runId: 'run-1',
  questionId: 'question-1',
})
assert.equal(key, 'tutor_session:learner-1:question_help:run-1:question-1')
assert.equal(buildTutorStorageKey({ learnerId: 'learner-1', contextType: 'question_help', batchId: 'batch-1', runId: 'run-1', questionId: 'question-1' }), 'tutor_session:learner-1:question_help:batch-1:question-1')

const first = { turn_id: 'turn-1', sequence: 1 }
const second = { turn_id: 'turn-2', sequence: 2 }
assert.deepEqual(mergeTutorTurn([], first), [first])
assert.deepEqual(mergeTutorTurn([first], first), [first])
assert.deepEqual(mergeTutorTurn([second], first), [first, second])
assert.equal(countTutorTurns([first, second]), 2)

const drawer = readFileSync(new URL('../src/features/tutor/TutorDrawer.vue', import.meta.url), 'utf8')
const resourcesView = readFileSync(new URL('../src/features/learning-documents/ResourcesView.vue', import.meta.url), 'utf8')
const resourceViewer = readFileSync(new URL('../src/features/learning-documents/ResourceViewer.vue', import.meta.url), 'utf8')
const feedbackView = readFileSync(new URL('../src/features/feedback/FeedbackView.vue', import.meta.url), 'utf8')
assert.match(resourcesView, /向 Tutor 提问/, 'resource page must expose the Tutor entry')
assert.match(resourcesView, /@ask-tutor="askTutorAboutSelection"/, 'selected text must open the resource Tutor')
assert.match(resourceViewer, /captureSelectedText/, 'reader must collect selected material')
assert.match(resourceViewer, /就这段向 Tutor 提问/, 'reader must offer a selected-text Tutor action')
assert.match(drawer, /已引用材料/, 'Tutor composer must display selected material separately from the question')
assert.match(drawer, /引用材料：/, 'Tutor turn must include the quoted material for grounded tutoring')
assert.match(feedbackView, /需要提示/, 'evaluation questions must expose the Tutor entry')
assert.match(drawer, /source_type: props\.contextType === 'question_help' && props\.batchId \? 'batch'/, 'batch feedback must create a batch-scoped Tutor session')
assert.match(drawer, /watch\(\(\) => props\.modelValue,[\s\S]*?ensureSession\(\)/, 'opening the panel must restore or create a session')
assert.match(drawer, /tutorApi\.getSession/, 'refresh restore must load persisted turns')
assert.match(drawer, /:disabled="!canSend"/, 'loading or sending must disable duplicate sends')
assert.match(drawer, /<SourceRefList/, 'Tutor evidence must use the shared source component')
assert.match(drawer, /evidence_insufficient/, 'safe evidence failure must be visible')
assert.doesNotMatch(drawer, /raw_prompt|chain_of_thought|api_key/i)

// The formal attempt is now built by the production evaluation hook.
const { ref, reactive } = await import('vue')
const { useFeedbackEvaluation } = await import('../src/features/feedback/useFeedbackEvaluation.js')
const stored = new Map([['tutor_help_count:learner-1:batch-1', '3']])
globalThis.localStorage = {
  getItem: key => stored.get(key) || null,
  setItem: (key, value) => stored.set(key, value),
}
const submitted = []
const messages = []
const scrolls = []
const session = { topic: '检索', resource_ids: ['resource-1'], questions: [
  { question_id: 'q1', question_type: 'single_choice' },
  { question_id: 'q2', question_type: 'multiple_choice' },
] }
const feedbackApi = {
  getBatchEvaluationSession: async () => ({ data: session }),
  getRunEvaluationSession: async () => ({ data: session }),
  submitBatchAttempt: async payload => {
    submitted.push({ endpoint: 'batch', payload })
    return { data: { attempt: { attempt_id: 'a1' }, profile_version: 8 } }
  },
  submitRunAttempt: async payload => {
    submitted.push({ endpoint: 'run', payload })
    return { data: { attempt: { attempt_id: 'a2' }, profile_version: 9 } }
  },
}
const form = reactive({ learner_id: 'learner-1', completed: true, time_spent_seconds: 90,
  self_rating: 4, difficulty_feeling: 'fit', helpful_part: ' 示例 ', confusing_part: '', comment: ' 复盘 ' })
const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
const evaluationAnswers = reactive({ stale: 'old' })
const tutorHelpCount = ref(1)
const feedbackResults = ref([])
const result = ref(null)
const submitting = ref(false)
const feedbackStatus = ref('')
const pendingCorrectionRunId = ref('')
const store = { currentProfile: { profile_version: 7 }, setCurrentProfile(profile) { this.currentProfile = profile } }
const evaluationFlow = useFeedbackEvaluation({
  feedbackApi, form, selectedRunId: ref('batch-1'), pendingCorrectionRunId, feedbackResults,
  result, evaluation, evaluationAnswers, tutorOpen: ref(false), tutorQuestion: ref(null),
  tutorHelpCount, canSubmit: ref(true), submitting, feedbackStatus, activeTask: ref(null),
  store, resultPanelRef: ref({ scrollIntoView: options => scrolls.push(options) }),
  feedbackScrollBehavior: () => 'auto',
  messages: { success: value => messages.push(value), error: assert.fail, warning: assert.fail },
})
await evaluationFlow.loadEvaluationSession()
assert.equal(evaluation.topic, '检索')
assert.deepEqual({ ...evaluationAnswers }, { q1: '', q2: [] })
assert.equal(tutorHelpCount.value, 3)
evaluationFlow.recordTutorHelp()
assert.equal(tutorHelpCount.value, 4)
evaluationFlow.restoreTutorHelp({ turns: [first, second] })
assert.equal(tutorHelpCount.value, 4, 'restoring turns must not discard a persisted higher hint count')
evaluationAnswers.q1 = 'A'
evaluationAnswers.q2 = ['B']
await evaluationFlow.submitEvaluation()
const payload = submitted[0].payload
assert.equal(submitted[0].endpoint, 'batch')
assert.equal(payload.batch_id, 'batch-1')
assert.equal(payload.hint_count, 4, 'formal batch attempt must carry actual Tutor usage')
assert.equal(payload.expected_profile_version, 7)
assert.equal(payload.duration_ms, 90000)
assert.equal(payload.source_resource_id, 'resource-1')
assert.deepEqual(payload.answers, [{ question_id: 'q1', answer: 'A' }, { question_id: 'q2', answer: ['B'] }])
assert.equal(payload.metadata.learning_reflection.helpful_part, '示例')
assert.equal(payload.metadata.learning_reflection.comment, '复盘')
assert.equal(store.currentProfile.profile_version, 8)
assert.equal(result.value.attempt.attempt_id, 'a1')
assert.equal(feedbackResults.value.length, 1)
assert.equal(submitting.value, false)
assert.equal(feedbackStatus.value, '')
assert.deepEqual(scrolls, [{ behavior: 'auto', block: 'start' }])

pendingCorrectionRunId.value = 'correction-run'
await evaluationFlow.loadEvaluationSession({ forceNew: true })
await evaluationFlow.submitEvaluation()
assert.equal(submitted[1].endpoint, 'run')
assert.equal(submitted[1].payload.run_id, 'correction-run')
assert.equal(submitted[1].payload.metadata.session_id, 'correction-run')
assert.equal(submitted[1].payload.hint_count, 4, 'formal corrective-run attempt must carry Tutor usage too')
assert.equal(submitted[1].payload.expected_profile_version, 8)
assert.equal(store.currentProfile.profile_version, 9)

console.log('tutor state tests passed')
