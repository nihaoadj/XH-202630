import assert from 'node:assert/strict'

const storage = new Map()
const previousWindow = globalThis.window
const previousStorage = globalThis.localStorage
const previousEventSource = globalThis.EventSource
const timers = new Map()
const clearedTimers = []
let nextTimerId = 0
globalThis.localStorage = {
  getItem: key => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: key => storage.delete(key),
}
globalThis.window = {
  localStorage: globalThis.localStorage,
  setInterval(callback, intervalMs) {
    const id = ++nextTimerId
    timers.set(id, { callback, intervalMs })
    return id
  },
  clearInterval(id) {
    clearedTimers.push(id)
    timers.delete(id)
  },
}

const { computed, reactive, ref } = await import('vue')
const { createRequestGuard } = await import('../src/utils/requestContext.js')
const { useFeedbackEvaluation } = await import('../src/features/feedback/useFeedbackEvaluation.js')
const { useFeedbackFollowup } = await import('../src/features/feedback/useFeedbackFollowup.js')
const { coursewareApi } = await import('../src/features/courseware/api.js')
const { useCoursewareTracking } = await import('../src/features/courseware/useCoursewareTracking.js')

function deferred() {
  let resolve
  let reject
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail })
  return { promise, resolve, reject }
}

async function settle() {
  await Promise.resolve()
  await Promise.resolve()
}

function makeEvaluationFixture() {
  const messages = { errors: [], successes: [], warnings: [] }
  const feedbackApi = {
    getBatchEvaluationSession: async () => ({ data: {} }),
    getRunEvaluationSession: async () => ({ data: {} }),
    submitBatchAttempt: async () => ({ data: {} }),
    submitRunAttempt: async () => ({ data: {} }),
  }
  const form = reactive({
    learner_id: 'learner-A', completed: true, time_spent_seconds: 900, self_rating: 4,
    difficulty_feeling: 'fit', helpful_part: 'worked', confusing_part: 'unclear', comment: 'continue',
  })
  const selectedRunId = ref('batch-A')
  const pendingCorrectionRunId = ref('')
  const feedbackResults = ref([])
  const result = ref(null)
  const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
  const evaluationAnswers = reactive({})
  const tutorOpen = ref(false)
  const tutorQuestion = ref(null)
  const tutorHelpCount = ref(2)
  const canSubmit = ref(true)
  const submitting = ref(false)
  const feedbackStatus = ref('')
  const activeTask = ref({ resources: [{ resource_id: 'resource-A' }] })
  const contextVersion = ref(0)
  const scrolls = []
  const profileUpdates = []
  const store = {
    currentProfile: { learner_id: 'learner-A', profile_version: 3 },
    setCurrentProfile(profile) { profileUpdates.push(profile); this.currentProfile = profile },
  }
  const hook = useFeedbackEvaluation({
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
    resultPanelRef: ref({ scrollIntoView: options => scrolls.push(options) }),
    feedbackScrollBehavior: () => 'auto',
    messages: {
      error: message => messages.errors.push(message),
      success: message => messages.successes.push(message),
      warning: message => messages.warnings.push(message),
    },
    contextVersion,
  })
  return {
    feedbackApi, form, selectedRunId, pendingCorrectionRunId, feedbackResults, result,
    evaluation, evaluationAnswers, submitting, feedbackStatus, contextVersion,
    messages, scrolls, store, profileUpdates, hook,
  }
}

function evaluationResponse(topic, questionId) {
  return { data: {
    topic,
    resource_ids: [`resource-${topic}`],
    questions: [{ question_id: questionId, question_type: 'single_choice' }],
  } }
}

function resultResponse(attemptId, profileVersion = 4) {
  return { data: { attempt: { attempt_id: attemptId }, profile_version: profileVersion } }
}

async function testRequestGuardAbaAndDispose() {
  const context = { learnerId: 'learner-A', batchId: 'batch-A' }
  const guard = createRequestGuard(() => context)
  const oldRequest = guard.capture()
  context.learnerId = 'learner-B'
  guard.invalidate()
  context.learnerId = 'learner-A'
  const currentRequest = guard.capture()
  assert.equal(oldRequest.isCurrent(), false, 'A → B → A must invalidate the earlier A request')
  assert.equal(currentRequest.isCurrent(), true)
  guard.dispose()
  assert.equal(currentRequest.isCurrent(), false, 'dispose must invalidate pending callbacks')
}

async function testFeedbackSessionRaceAndFailure() {
  const fixture = makeEvaluationFixture()
  const aOld = deferred()
  const bRequest = deferred()
  const aCurrent = deferred()
  const requests = new Map([
    ['batch-A', [aOld, aCurrent]],
    ['batch-B', [bRequest]],
  ])
  const calls = []
  fixture.feedbackApi.getBatchEvaluationSession = (learnerId, batchId) => {
    calls.push([learnerId, batchId])
    return requests.get(batchId).shift().promise
  }

  const oldA = fixture.hook.loadEvaluationSession({ forceNew: true })
  fixture.selectedRunId.value = 'batch-B'
  fixture.contextVersion.value += 1
  const currentB = fixture.hook.loadEvaluationSession({ forceNew: true })
  fixture.selectedRunId.value = 'batch-A'
  fixture.contextVersion.value += 1
  const currentA = fixture.hook.loadEvaluationSession({ forceNew: true })

  aCurrent.resolve(evaluationResponse('current-A', 'q-current-A'))
  await currentA
  aOld.resolve(evaluationResponse('old-A', 'q-old-A'))
  bRequest.resolve(evaluationResponse('old-B', 'q-old-B'))
  await Promise.all([oldA, currentB])
  assert.deepEqual(calls, [
    ['learner-A', 'batch-A'], ['learner-A', 'batch-B'], ['learner-A', 'batch-A'],
  ])
  assert.equal(fixture.evaluation.topic, 'current-A', 'late success must not overwrite the current A response')
  assert.deepEqual(fixture.evaluation.questions.map(question => question.question_id), ['q-current-A'])

  const staleFailure = deferred()
  const currentFailureCase = makeEvaluationFixture()
  currentFailureCase.feedbackApi.getBatchEvaluationSession = (learnerId, batchId) => (
    batchId === 'batch-A' ? staleFailure.promise : Promise.resolve(evaluationResponse('current-B', 'q-B'))
  )
  const old = currentFailureCase.hook.loadEvaluationSession({ forceNew: true })
  currentFailureCase.selectedRunId.value = 'batch-B'
  currentFailureCase.contextVersion.value += 1
  await currentFailureCase.hook.loadEvaluationSession({ forceNew: true })
  staleFailure.reject(new Error('stale session failure'))
  await old
  assert.equal(currentFailureCase.evaluation.topic, 'current-B', 'late failure must not clear the active session')
  assert.deepEqual(currentFailureCase.messages.errors, [], 'late failure must not show a message in another batch')

  const pendingAtUnmount = deferred()
  const disposed = makeEvaluationFixture()
  disposed.feedbackApi.getBatchEvaluationSession = () => pendingAtUnmount.promise
  const loadOnUnmount = disposed.hook.loadEvaluationSession({ forceNew: true })
  disposed.hook.dispose()
  pendingAtUnmount.resolve(evaluationResponse('after-unmount', 'q-unmounted'))
  await loadOnUnmount
  assert.equal(disposed.evaluation.topic, '', 'unmount must prevent late session writes')
  assert.deepEqual(disposed.messages.errors, [])
}

async function testFeedbackSubmitPayloadAndStaleCompletions() {
  const fixture = makeEvaluationFixture()
  fixture.evaluation.topic = 'RAG'
  fixture.evaluation.questions = [{ question_id: 'q-one', question_type: 'single_choice' }]
  fixture.evaluation.resourceIds = ['resource-A']
  fixture.evaluationAnswers['q-one'] = 'option-1'
  const pendingSubmit = deferred()
  let submittedPayload
  fixture.feedbackApi.submitBatchAttempt = payload => {
    submittedPayload = payload
    return pendingSubmit.promise
  }
  const submit = fixture.hook.submitEvaluation()
  assert.deepEqual(Object.keys(submittedPayload).sort(), [
    'answers', 'batch_id', 'duration_ms', 'expected_profile_version', 'hint_count',
    'idempotency_key', 'learner_id', 'metadata', 'source_resource_id', 'submitted_at',
  ].sort(), 'batch submit must keep its original request fields')
  assert.equal(submittedPayload.learner_id, 'learner-A')
  assert.equal(submittedPayload.batch_id, 'batch-A')
  assert.equal(submittedPayload.source_resource_id, 'resource-A')
  assert.equal(submittedPayload.expected_profile_version, 3)
  assert.equal(submittedPayload.duration_ms, 900000)
  assert.equal(submittedPayload.hint_count, 2)
  assert.deepEqual(submittedPayload.answers, [{ question_id: 'q-one', answer: 'option-1' }])
  assert.equal(submittedPayload.metadata.session_id, 'batch-A')
  assert.deepEqual(submittedPayload.metadata.learning_reflection, {
    completed: true, time_spent_seconds: 900, self_rating: 4, difficulty_feeling: 'fit',
    helpful_part: 'worked', confusing_part: 'unclear', comment: 'continue',
  })
  assert.match(submittedPayload.idempotency_key, /^web-batch-A-/)
  assert.equal(Number.isNaN(Date.parse(submittedPayload.submitted_at)), false)

  const nextBatchResult = { attempt: { attempt_id: 'batch-B-existing' } }
  fixture.selectedRunId.value = 'batch-B'
  fixture.contextVersion.value += 1
  fixture.feedbackStatus.value = ''
  fixture.result.value = nextBatchResult
  pendingSubmit.resolve(resultResponse('old-submit-A'))
  await submit
  assert.deepEqual(fixture.result.value, nextBatchResult, 'late submit success must not replace the selected batch result')
  assert.deepEqual(fixture.feedbackResults.value, [])
  assert.deepEqual(fixture.profileUpdates, [])
  assert.deepEqual(fixture.messages.successes, [])
  assert.deepEqual(fixture.scrolls, [])
  assert.equal(fixture.submitting.value, false, 'stale submit must still release its loading state')

  const failedFixture = makeEvaluationFixture()
  const pendingFailure = deferred()
  failedFixture.feedbackApi.submitBatchAttempt = () => pendingFailure.promise
  const failedSubmit = failedFixture.hook.submitEvaluation()
  failedFixture.selectedRunId.value = 'batch-B'
  failedFixture.contextVersion.value += 1
  failedFixture.feedbackStatus.value = ''
  pendingFailure.reject(new Error('stale submit failure'))
  await failedSubmit
  assert.deepEqual(failedFixture.messages.errors, [], 'late submit failure must not message the new batch')
  assert.equal(failedFixture.feedbackStatus.value, '')
  assert.equal(failedFixture.submitting.value, false)
}

function makeFollowupFixture() {
  const messages = { errors: [], successes: [] }
  const feedbackApi = { selectFollowup: async () => ({ data: {} }) }
  const form = reactive({ learner_id: 'learner-A' })
  const result = ref({ attempt: { attempt_id: 'attempt-A' } })
  const selectingOption = ref('')
  const selectedResourceTypes = ref(['practice', 'checklist'])
  const includeClaimCheck = ref(true)
  const generationOptions = ref({ snapshot_hash: 'snapshot-A' })
  const selectedDifficulty = ref('advanced')
  const learningIntent = ref('reinforce_weakness')
  const selectedNodesForFollowup = ref(['node-A'])
  const correctionPackageOption = ref({
    eligible: true, option_id: 'correction-A', recommended_target_ids: ['node-weak'], snapshot_hash: 'correction-snapshot-A',
  })
  const contextVersion = ref(0)
  const routes = []
  const hook = useFeedbackFollowup({
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
    router: { push: value => routes.push(value) },
    messages: {
      error: message => messages.errors.push(message),
      success: message => messages.successes.push(message),
    },
    contextVersion,
  })
  return {
    feedbackApi, form, result, selectingOption, selectedResourceTypes, includeClaimCheck,
    generationOptions, selectedDifficulty, learningIntent, selectedNodesForFollowup,
    correctionPackageOption, contextVersion, messages, routes, hook,
  }
}

async function testFollowupPayloadAndStaleCompletion() {
  const fixture = makeFollowupFixture()
  const pending = deferred()
  let selectionPayload
  fixture.feedbackApi.selectFollowup = payload => {
    selectionPayload = payload
    return pending.promise
  }
  const selection = fixture.hook.selectFeedbackOption('custom-selection')
  assert.deepEqual(selectionPayload, {
    learner_id: 'learner-A', attempt_id: 'attempt-A', option_id: 'custom-selection',
    resource_types: ['practice', 'checklist'], include_claim_check: true,
    learning_intent: 'reinforce_weakness', selected_skill_node_ids: ['node-A'],
    next_generation_snapshot_hash: 'snapshot-A',
  })
  fixture.form.learner_id = 'learner-B'
  fixture.contextVersion.value += 1
  const nextResult = { attempt: { attempt_id: 'attempt-B' } }
  fixture.result.value = nextResult
  fixture.selectingOption.value = 'option-B'
  pending.resolve({ data: { attempt: { attempt_id: 'attempt-A' }, followup_run_id: 'run-A' } })
  await selection
  assert.deepEqual(fixture.result.value, nextResult, 'late follow-up success must not replace a new attempt')
  assert.equal(fixture.selectingOption.value, 'option-B', 'stale finally must not clear a newer option spinner')
  assert.deepEqual(fixture.messages.successes, [])

  const failed = makeFollowupFixture()
  const pendingFailure = deferred()
  failed.feedbackApi.selectFollowup = () => pendingFailure.promise
  const staleFailure = failed.hook.selectFeedbackOption('option-A')
  failed.form.learner_id = 'learner-B'
  failed.contextVersion.value += 1
  failed.selectingOption.value = ''
  pendingFailure.reject(new Error('stale follow-up failure'))
  await staleFailure
  assert.deepEqual(failed.messages.errors, [], 'late follow-up failure must not notify another learner')
  assert.equal(failed.selectingOption.value, '')

  const active = makeFollowupFixture()
  let correctionPayload
  active.feedbackApi.selectFollowup = async payload => {
    correctionPayload = payload
    return { data: { attempt: { attempt_id: 'attempt-A' }, followup_run_id: 'run-correction' } }
  }
  await active.hook.selectCorrectionPackage()
  assert.deepEqual(correctionPayload, {
    learner_id: 'learner-A', attempt_id: 'attempt-A', option_id: 'correction-A',
    learning_intent: 'reinforce_weakness', include_claim_check: true,
    selected_skill_node_ids: ['node-weak'], next_generation_snapshot_hash: 'correction-snapshot-A',
  })
  assert.equal(active.result.value.followup_run_id, 'run-correction')
  assert.deepEqual(active.messages.successes, ['纠错包与新测评题正在创建'])
  assert.equal(active.selectingOption.value, '')
}

class FakeEventSource {
  constructor(url) {
    this.url = url
    this.handlers = new Map()
    this.closed = false
    FakeEventSource.instances.push(this)
  }
  addEventListener(name, callback) { this.handlers.set(name, callback) }
  close() { this.closed = true }
  emit(name, event = {}) { this.handlers.get(name)?.(event) }
}
FakeEventSource.instances = []

function makeCoursewareFixture() {
  const messages = []
  const routes = []
  const notifications = []
  const calls = []
  const selectedLearnerId = ref('learner-A')
  const selectedRunId = ref('')
  const jobs = ref([])
  const currentJob = ref(null)
  const connectionStatus = ref('idle')
  const published = computed(() => ['published', 'published_with_warnings'].includes(currentJob.value?.status))
  const tracking = useCoursewareTracking({
    selectedLearnerId,
    selectedRunId,
    jobs,
    currentJob,
    connectionStatus,
    published,
    rememberedRunId: () => '',
    syncRoute: () => routes.push({ learnerId: selectedLearnerId.value, runId: selectedRunId.value }),
    emit: (...event) => notifications.push(event),
    messages: { error: message => messages.push(message) },
  })
  return {
    selectedLearnerId, selectedRunId, jobs, currentJob, connectionStatus,
    tracking, messages, routes, notifications, calls,
  }
}

async function testCoursewareListAndDetailRace() {
  const fixture = makeCoursewareFixture()
  const originalListJobs = coursewareApi.listJobs
  const originalGetJobDetail = coursewareApi.getJobDetail
  const listA = deferred()
  coursewareApi.listJobs = learnerId => {
    fixture.calls.push(['list', learnerId])
    return learnerId === 'learner-A' ? listA.promise : Promise.resolve({ data: { items: [{ run_id: 'run-B' }] } })
  }
  coursewareApi.getJobDetail = async runId => {
    fixture.calls.push(['detail', runId])
    return { data: { run_id: runId, status: 'composing' } }
  }
  const oldList = fixture.tracking.loadJobs()
  fixture.selectedLearnerId.value = 'learner-B'
  await fixture.tracking.loadJobs()
  listA.resolve({ data: { items: [{ run_id: 'run-A' }] } })
  await oldList
  assert.deepEqual(fixture.jobs.value.map(job => job.run_id), ['run-B'], 'late task list must not replace the current learner list')
  assert.equal(fixture.selectedRunId.value, 'run-B')
  assert.equal(fixture.currentJob.value.run_id, 'run-B')
  assert.deepEqual(fixture.routes, [{ learnerId: 'learner-B', runId: 'run-B' }])

  const detailA1 = deferred()
  const detailB = deferred()
  const detailA2 = deferred()
  const queuedDetails = new Map([
    ['run-A', [detailA1, detailA2]], ['run-B', [detailB]],
  ])
  coursewareApi.getJobDetail = runId => {
    fixture.calls.push(['detail', runId])
    const queue = queuedDetails.get(runId)
    return queue?.length
      ? queue.shift().promise
      : Promise.resolve({ data: { run_id: runId, status: 'composing' } })
  }
  fixture.jobs.value = [{ run_id: 'run-A' }, { run_id: 'run-B' }]
  fixture.selectedRunId.value = 'run-A'
  const oldA = fixture.tracking.loadCurrentJob()
  fixture.selectedRunId.value = 'run-B'
  const oldB = fixture.tracking.loadCurrentJob()
  fixture.selectedRunId.value = 'run-A'
  const currentA = fixture.tracking.loadCurrentJob()
  detailA2.resolve({ data: { run_id: 'run-A', status: 'composing', title: 'current A' } })
  await currentA
  detailA1.resolve({ data: { run_id: 'run-A', status: 'failed', title: 'old A' } })
  detailB.resolve({ data: { run_id: 'run-B', status: 'published', title: 'old B', resource_id: 'old-resource' } })
  await Promise.all([oldA, oldB])
  assert.equal(fixture.currentJob.value.title, 'current A', 'late A/B details must not overwrite A after returning to it')
  assert.deepEqual(fixture.routes.at(-1), { learnerId: 'learner-B', runId: 'run-A' })
  assert.deepEqual(fixture.notifications, [], 'late terminal detail must not emit a publication notification')

  const oldStream = FakeEventSource.instances.at(-1)
  fixture.selectedRunId.value = 'run-B'
  await fixture.tracking.loadCurrentJob()
  const currentStream = FakeEventSource.instances.at(-1)
  assert.notEqual(oldStream, currentStream)
  assert.equal(oldStream.closed, true)
  const beforeOldCallbacks = fixture.calls.filter(call => call[0] === 'detail').length
  oldStream.onerror()
  oldStream.emit('courseware_progress')
  await settle()
  assert.equal(currentStream.closed, false, 'an old stream error must not close the new stream')
  assert.equal(timers.size, 0, 'an old stream error must not start polling for the new run')
  assert.equal(fixture.calls.filter(call => call[0] === 'detail').length, beforeOldCallbacks)

  currentStream.onerror()
  assert.equal(currentStream.closed, true)
  assert.equal(fixture.connectionStatus.value, 'polling')
  assert.equal(timers.size, 1)
  assert.equal([...timers.values()][0].intervalMs, 2500)
  const stalePoll = [...timers.values()][0].callback
  fixture.selectedRunId.value = 'run-A'
  await fixture.tracking.loadCurrentJob()
  const beforeStalePoll = fixture.calls.filter(call => call[0] === 'detail').length
  stalePoll()
  await settle()
  assert.equal(fixture.calls.filter(call => call[0] === 'detail').length, beforeStalePoll, 'a queued poll from the previous run must be ignored')
  assert.ok(clearedTimers.length >= 1, 'switching task must clear its previous polling interval')

  const pendingRefresh = deferred()
  coursewareApi.getJobDetail = runId => runId === 'run-A'
    ? pendingRefresh.promise
    : Promise.resolve({ data: { run_id: runId, status: 'composing', title: 'current B' } })
  fixture.selectedRunId.value = 'run-A'
  const oldRefresh = fixture.tracking.refreshCurrentJob('run-A')
  fixture.selectedRunId.value = 'run-B'
  await fixture.tracking.loadCurrentJob()
  pendingRefresh.reject(new Error('stale refresh failure'))
  await oldRefresh
  assert.equal(fixture.currentJob.value.title, 'current B', 'late refresh failure must not alter another task state')
  assert.equal(fixture.connectionStatus.value, 'live', 'late refresh failure must not replace the new stream status')
  assert.deepEqual(fixture.messages, [], 'late refresh failure must not start fallback polling or notify')

  const pendingUnmountDetail = deferred()
  coursewareApi.getJobDetail = () => pendingUnmountDetail.promise
  fixture.selectedRunId.value = 'run-unmount'
  const beforeUnmountRoutes = fixture.routes.length
  const beforeUnmountJob = fixture.currentJob.value
  const pendingUnmount = fixture.tracking.loadCurrentJob()
  fixture.tracking.dispose()
  pendingUnmountDetail.resolve({ data: { run_id: 'run-unmount', status: 'published', resource_id: 'late' } })
  await pendingUnmount
  assert.deepEqual(fixture.currentJob.value, beforeUnmountJob, 'unmount must prevent late detail writes')
  assert.equal(fixture.routes.length, beforeUnmountRoutes, 'unmount must prevent route writes')
  assert.equal(timers.size, 0)
  assert.deepEqual(fixture.messages, [])

  coursewareApi.listJobs = originalListJobs
  coursewareApi.getJobDetail = originalGetJobDetail
}

async function run() {
  await testRequestGuardAbaAndDispose()
  await testFeedbackSessionRaceAndFailure()
  await testFeedbackSubmitPayloadAndStaleCompletions()
  await testFollowupPayloadAndStaleCompletion()

  const previousError = console.error
  console.error = () => {}
  try {
    await testCoursewareListAndDetailRace()
  } finally {
    console.error = previousError
  }
  console.log('request context race tests passed')
}

try {
  globalThis.EventSource = FakeEventSource
  await run()
} finally {
  if (previousWindow === undefined) delete globalThis.window
  else globalThis.window = previousWindow
  if (previousStorage === undefined) delete globalThis.localStorage
  else globalThis.localStorage = previousStorage
  if (previousEventSource === undefined) delete globalThis.EventSource
  else globalThis.EventSource = previousEventSource
}
