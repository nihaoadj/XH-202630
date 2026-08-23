import assert from 'node:assert/strict'

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
const { buildCoursewareRequest } = await import('../src/features/courseware/sourcePolicy.js')

assert.deepEqual(buildCoursewareRequest({
  learnerId: 'learner-1',
  sourceIds: ['lecture-1', 'practice-1'],
  preferences: { learning_goal: '掌握检索', expected_duration_minutes: 30, interaction_intensity: 'high', visual_style_id: 'midnight' },
}), {
  learner_id: 'learner-1', source_resource_ids: ['lecture-1', 'practice-1'], publish_mode: 'automatic',
  learning_goal: '掌握检索', expected_duration_minutes: 30, interaction_intensity: 'high', visual_style_id: 'midnight',
})

let calls = 0
coursewareApi.getJobDetail = async () => ({ data: { run_id: 'long-running', status: ++calls >= 25 ? 'published' : 'composing' } })

const { waitForTerminal } = useCoursewareJob()
const terminal = await waitForTerminal('long-running', { intervalMs: 0, timeoutMs: 1000 })

assert.equal(terminal.status, 'published')
assert.equal(calls, 25)
console.log('courseware user journey tests passed')
