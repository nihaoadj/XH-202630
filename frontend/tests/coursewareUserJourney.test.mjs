import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const localStorageValues = new Map()
globalThis.window = {
  location: { pathname: '/', search: '', assign: () => {} },
  setTimeout: (callback) => { callback(); return 1 },
  localStorage: {
    getItem: key => localStorageValues.get(key) || null,
    setItem: (key, value) => localStorageValues.set(key, value),
    removeItem: key => localStorageValues.delete(key),
  },
}

const { ref, computed } = await import('vue')
const { coursewareApi } = await import('../src/features/courseware/api.js')
const { useCoursewareTracking } = await import('../src/features/courseware/useCoursewareTracking.js')
const { useCoursewareJob } = await import('../src/features/courseware/useCoursewareJob.js')
const { buildCoursewareBatchRequest } = await import('../src/features/courseware/sourcePolicy.js')

assert.deepEqual(buildCoursewareBatchRequest({
  learnerId: 'learner-1',
  resourceIds: ['lecture-1', 'practice-1'],
  preferences: { learning_goal: '掌握检索', expected_duration_minutes: 30, interaction_intensity: 'high' },
}), {
  learner_id: 'learner-1', resource_ids: ['lecture-1', 'practice-1'],
  learning_goal: '掌握检索', expected_duration_minutes: 30,
})

let calls = 0
coursewareApi.getJobDetail = async () => ({ data: { run_id: 'long-running', status: ++calls >= 25 ? 'published' : 'composing' } })

const { waitForTerminal } = useCoursewareJob()
const terminal = await waitForTerminal('long-running', { intervalMs: 0, timeoutMs: 1000 })

assert.equal(terminal.status, 'published')
assert.equal(calls, 25)

// Exercise the production hook that replaces the workspace's extracted code.
const intervals = new Map()
const clearedIntervals = []
let timerSequence = 0
window.setInterval = (callback, intervalMs) => {
  const id = ++timerSequence
  intervals.set(id, { callback, intervalMs })
  return id
}
window.clearInterval = (id) => { clearedIntervals.push(id); intervals.delete(id) }
const streams = []
globalThis.EventSource = class {
  constructor(url) { this.url = url; this.handlers = {}; this.closed = false; streams.push(this) }
  addEventListener(name, callback) { this.handlers[name] = callback }
  close() { this.closed = true }
}
const historyCalls = []
const detailsCalls = []
const notifications = []
const routeSyncs = []
const messages = []
const selectedLearnerId = ref('learner-1')
const selectedRunId = ref('')
const jobs = ref([])
const currentJob = ref(null)
const connectionStatus = ref('idle')
const published = computed(() => ['published', 'published_with_warnings'].includes(currentJob.value?.status))
const tracking = useCoursewareTracking({
  selectedLearnerId, selectedRunId, jobs, currentJob, connectionStatus, published,
  rememberedRunId: () => 'restored-run',
  syncRoute: () => routeSyncs.push(selectedRunId.value),
  emit: (...event) => notifications.push(event),
  messages: { error: message => messages.push(message) },
})
coursewareApi.listJobs = async learnerId => {
  historyCalls.push(learnerId)
  throw new Error('list endpoint temporarily unavailable')
}
let detailStatus = 'composing'
coursewareApi.getJobDetail = async runId => {
  detailsCalls.push(runId)
  return { data: { run_id: runId, status: detailStatus, resource_id: 'courseware-1' } }
}
await tracking.loadJobs()
assert.deepEqual(historyCalls, ['learner-1'])
assert.deepEqual(detailsCalls, ['restored-run', 'restored-run'], 'retain detail recovery and the subsequent current-task refresh')
assert.equal(selectedRunId.value, 'restored-run')
assert.equal(jobs.value[0].run_id, 'restored-run')
assert.deepEqual(routeSyncs, ['restored-run'])
assert.deepEqual(messages, [])
assert.equal(connectionStatus.value, 'live')
assert.equal(streams.length, 1)
assert.ok(streams[0].url.includes('restored-run'))

streams[0].onerror()
assert.equal(streams[0].closed, true)
assert.equal(connectionStatus.value, 'polling')
assert.equal(intervals.size, 1)
assert.equal([...intervals.values()][0].intervalMs, 2500)
streams[0].onerror()
assert.equal(intervals.size, 1, 'fallback must not duplicate the polling timer')

detailStatus = 'published'
await tracking.refreshCurrentJob()
await tracking.refreshCurrentJob()
assert.equal(connectionStatus.value, 'terminal')
assert.equal(intervals.size, 0)
assert.equal(clearedIntervals.length, 1)
assert.equal(jobs.value[0].status, 'published')
assert.equal(notifications.length, 1, 'repeated terminal refreshes publish one notification per run')
assert.equal(notifications[0][0], 'published')
assert.equal(notifications[0][1].resource_id, 'courseware-1')
await tracking.loadCurrentJob()
assert.equal(notifications.length, 1, 'restoring a terminal task preserves the original notification timing')
tracking.stopTracking()
assert.equal(intervals.size, 0)

selectedRunId.value = 'event-run'
detailStatus = 'composing'
await tracking.loadCurrentJob()
const eventStream = streams.at(-1)
const beforeEvent = detailsCalls.length
eventStream.handlers.courseware_progress()
await Promise.resolve()
await Promise.resolve()
assert.equal(detailsCalls.length, beforeEvent + 1, 'production progress events refresh task details')
tracking.stopTracking()
assert.equal(eventStream.closed, true, 'unmount cleanup closes the active SSE stream')

selectedRunId.value = ''
await tracking.loadCurrentJob()
assert.equal(currentJob.value, null)
assert.equal(connectionStatus.value, 'idle')
selectedLearnerId.value = ''
await tracking.loadJobs()
assert.deepEqual(jobs.value, [])
assert.equal(historyCalls.length, 1, 'an empty learner must not request task history')

const resourcesView = readFileSync(new URL('../src/features/learning-documents/ResourcesView.vue', import.meta.url), 'utf8')
const generationView = readFileSync(new URL('../src/features/generation/GenerateView.vue', import.meta.url), 'utf8')
const coursewareWorkspace = readFileSync(new URL('../src/features/courseware/CoursewareGenerationWorkspace.vue', import.meta.url), 'utf8')
const focusSwitcher = readFileSync(new URL('../src/features/learning-documents/FocusResourceSwitcher.vue', import.meta.url), 'utf8')
assert.match(
  resourcesView,
  /const selected = selectedResource\.value[\s\S]*?\[resourceId\]: \{ \.\.\.selected, \.\.\.detail \}/,
  'courseware detail loading must retain the resource_kind discriminator from the requested library item snapshot',
)
assert.match(resourcesView, /path: '\/generate'/, 'learning resources must hand courseware creation to the generation page')
assert.doesNotMatch(resourcesView, /waitForCoursewareTerminal/, 'learning resources must not wait for courseware generation')
assert.match(generationView, /CoursewareGenerationWorkspace/, 'generation page must host the courseware workspace')
assert.match(generationView, /command="courseware"/, 'generation page must expose a direct courseware workspace switch')
assert.match(generationView, /selectedCoursewareJob/, 'generation page must restore the selected courseware workspace after navigation')
assert.match(generationView, /source_batch_id \|\| publishedJob\.run_id/, 'embedded published courseware must navigate with a stable resource batch or run')
assert.match(coursewareWorkspace, /kind: 'courseware'/, 'courseware creation must keep the generation workspace route')
assert.match(coursewareWorkspace, /courseware_active_run_id/, 'courseware workspace must restore the last active courseware run')
assert.match(coursewareWorkspace, /source_batch_id \|\| currentJob\.value\.run_id/, 'published courseware must fall back to its own run when no source batch exists')
const coursewareViewer = readFileSync(new URL('../src/features/courseware/CoursewareViewer.vue', import.meta.url), 'utf8')
assert.match(coursewareViewer, /:key="lifecycle"/, 'courseware preview iframe must be replaced when the release changes')
assert.match(coursewareViewer, /previewUrl\(resource\.resource_id, resource\.released_release_id \|\| resource\.release_id\)/, 'courseware preview must be bound to the active release')
assert.doesNotMatch(coursewareWorkspace, /视觉主题|v-model="preferences\.visual_style_id"|<el-option label="编辑风"/, 'courseware generation must not expose a selectable visual style')
assert.match(focusSwitcher, /interactive_courseware/, 'shared focus switcher must include courseware resources')
console.log('courseware user journey tests passed')
