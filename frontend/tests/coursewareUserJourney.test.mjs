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

const { coursewareApi } = await import('../src/features/courseware/api.js')
const { useCoursewareJob } = await import('../src/features/courseware/useCoursewareJob.js')
const { buildCoursewareBatchRequest } = await import('../src/features/courseware/sourcePolicy.js')

assert.deepEqual(buildCoursewareBatchRequest({
  learnerId: 'learner-1',
  resourceIds: ['lecture-1', 'practice-1'],
  preferences: { learning_goal: '掌握检索', expected_duration_minutes: 30, interaction_intensity: 'high' },
}), {
  learner_id: 'learner-1', resource_ids: ['lecture-1', 'practice-1'],
  learning_goal: '掌握检索', expected_duration_minutes: 30, interaction_intensity: 'high',
})

let calls = 0
coursewareApi.getJobDetail = async () => ({ data: { run_id: 'long-running', status: ++calls >= 25 ? 'published' : 'composing' } })

const { waitForTerminal } = useCoursewareJob()
const terminal = await waitForTerminal('long-running', { intervalMs: 0, timeoutMs: 1000 })

assert.equal(terminal.status, 'published')
assert.equal(calls, 25)

const resourcesView = readFileSync(new URL('../src/features/learning-documents/ResourcesView.vue', import.meta.url), 'utf8')
const generationView = readFileSync(new URL('../src/features/generation/GenerateView.vue', import.meta.url), 'utf8')
const coursewareWorkspace = readFileSync(new URL('../src/features/courseware/CoursewareGenerationWorkspace.vue', import.meta.url), 'utf8')
const focusSwitcher = readFileSync(new URL('../src/features/learning-documents/FocusResourceSwitcher.vue', import.meta.url), 'utf8')
assert.match(
  resourcesView,
  /\[resourceId\]: \{ \.\.\.selectedResource\.value, \.\.\.detail \}/,
  'courseware detail loading must retain the resource_kind discriminator from the library item',
)
assert.match(resourcesView, /path: '\/generate'/, 'learning resources must hand courseware creation to the generation page')
assert.doesNotMatch(resourcesView, /waitForCoursewareTerminal/, 'learning resources must not wait for courseware generation')
assert.match(generationView, /CoursewareGenerationWorkspace/, 'generation page must host the courseware workspace')
assert.match(generationView, /互动课件生成/, 'generation page must expose a direct courseware workspace switch')
assert.match(generationView, /generation_workspace_kind/, 'generation page must restore the selected workspace after navigation')
assert.match(coursewareWorkspace, /coursewareApi\.listJobs/, 'courseware workspace must restore learner task history')
assert.match(coursewareWorkspace, /kind: 'courseware'/, 'courseware creation must keep the generation workspace route')
assert.match(coursewareWorkspace, /courseware_active_run_id/, 'courseware workspace must restore the last active courseware run')
assert.doesNotMatch(coursewareWorkspace, /视觉主题|v-model="preferences\.visual_style_id"|<el-option label="编辑风"/, 'courseware generation must not expose a selectable visual style')
assert.match(coursewareWorkspace, /coursewareApi\.getJobDetail\(restoredRunId\)/, 'courseware workspace must recover the saved task when the task-list API is temporarily unavailable')
assert.match(focusSwitcher, /interactive_courseware/, 'shared focus switcher must include courseware resources')
console.log('courseware user journey tests passed')
