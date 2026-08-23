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

let calls = 0
coursewareApi.getJobDetail = async () => ({ data: { run_id: 'long-running', status: ++calls >= 25 ? 'published' : 'composing' } })

const { waitForTerminal } = useCoursewareJob()
const terminal = await waitForTerminal('long-running', { intervalMs: 0, timeoutMs: 1000 })

assert.equal(terminal.status, 'published')
assert.equal(calls, 25)
console.log('courseware user journey tests passed')
