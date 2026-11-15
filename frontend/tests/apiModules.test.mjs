// Exercise the real domain modules and Axios adapter, without a backend server.
import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ESLint } from 'eslint'
import * as legacy from '../src/api/index.js'
import { api } from '../src/api/client.js'
import { authApi } from '../src/features/auth/api.js'
import { profileApi, userApi, diagnosisApi, learningHistoryApi } from '../src/features/learners/api.js'
import { onboardingApi } from '../src/features/onboarding/api.js'
import { resourceApi } from '../src/features/learning-documents/api.js'
import { feedbackApi } from '../src/features/feedback/api.js'
import { reportApi } from '../src/features/reports/api.js'
import { coursewareApi } from '../src/features/courseware/api.js'
import { knowledgeApi } from '../src/features/knowledge/api.js'
import { resourceLibraryApi } from '../src/features/resource-library/api.js'
import { generateApi } from '../src/features/generation/api.js'
import { runApi } from '../src/features/runs/queryApi.js'

const exports = { api, authApi, profileApi, userApi, diagnosisApi, learningHistoryApi, onboardingApi,
  resourceApi, feedbackApi, reportApi, coursewareApi, knowledgeApi, resourceLibraryApi, generateApi, runApi }
assert.deepEqual(Object.keys(legacy).sort(), Object.keys(exports).sort())
for (const [name, value] of Object.entries(exports)) assert.equal(legacy[name], value, `${name} must be the same object`)

const payload = { fixture: 'synthetic', nested: { keep: true } }
const params = { cursor: 'next', limit: 3 }
const calls = [
  [() => authApi.register(payload), 'post', '/auth/register', undefined, payload],
  [() => authApi.login(payload), 'post', '/auth/login', undefined, payload],
  [() => authApi.me(), 'get', '/auth/me'],
  [() => authApi.logout(), 'post', '/auth/logout'],
  [() => profileApi.list(params), 'get', '/profiles/', params],
  [() => profileApi.get('learner'), 'get', '/profiles/learner'],
  [() => profileApi.abilityNodes('learner'), 'get', '/profiles/learner/ability-nodes'],
  [() => profileApi.update('learner', payload), 'patch', '/profiles/learner', undefined, payload],
  [() => profileApi.delete('learner'), 'delete', '/profiles/learner'],
  [() => userApi.list(), 'get', '/users/'],
  [() => userApi.get('user'), 'get', '/users/user'],
  [() => userApi.create(payload), 'post', '/users/', undefined, payload],
  [() => userApi.update('user', payload), 'patch', '/users/user', undefined, payload],
  [() => onboardingApi.getQuestions('direction'), 'get', '/onboarding/questions', { learning_direction_id: 'direction' }],
  [() => onboardingApi.createInitialProfile(payload), 'post', '/onboarding/initial-profile', undefined, payload],
  [() => diagnosisApi.submit(payload), 'post', '/diagnosis/submit', undefined, payload],
  [() => learningHistoryApi.timeline('learner'), 'get', '/learning-history/learner/timeline'],
  [() => learningHistoryApi.journey('learner', params), 'get', '/learning-history/learner/journey', params],
  [() => resourceApi.listByLearner('learner', params), 'get', '/resources/learner', params],
  [() => resourceApi.get('r/a ?'), 'get', '/resources/items/r%2Fa%20%3F'],
  [() => resourceApi.getPreview('r/a ?'), 'get', '/resources/items/r%2Fa%20%3F/preview'],
  [() => resourceApi.decideClaimPublication('r/a ?', false), 'post', '/resources/items/r%2Fa%20%3F/claim-publication-decision', undefined, { publish: false }],
  [() => feedbackApi.getEvaluationSession('learner', 'resource'), 'get', '/feedback/evaluation/learner/resource'],
  [() => feedbackApi.getRunEvaluationSession('learner', 'run'), 'get', '/feedback/evaluation/run/learner/run'],
  [() => feedbackApi.getBatchEvaluationSession('learner', 'batch'), 'get', '/feedback/evaluation/batch/learner/batch'],
  [() => feedbackApi.submitAttempt(payload), 'post', '/feedback/attempts', undefined, payload],
  [() => feedbackApi.submitRunAttempt(payload), 'post', '/feedback/attempts/run/submit', undefined, payload],
  [() => feedbackApi.submitBatchAttempt(payload), 'post', '/feedback/attempts/batch/submit', undefined, payload],
  [() => feedbackApi.selectFollowup(payload), 'post', '/feedback/followups/select', undefined, payload],
  [() => feedbackApi.listResults('learner', params), 'get', '/feedback/results/learner', params],
  [() => feedbackApi.listAttempts('learner', params), 'get', '/feedback/attempts/learner', params],
  [() => feedbackApi.getPath('learner'), 'get', '/feedback/path/learner'],
  [() => reportApi.get('learner/a'), 'get', '/report/learner/a'],
  [() => learningHistoryApi.journey('learner'), 'get', '/learning-history/learner/journey', {}],
  [() => resourceApi.listByLearner('learner'), 'get', '/resources/learner', {}],
  [() => feedbackApi.listResults('learner'), 'get', '/feedback/results/learner', {}],
  [() => feedbackApi.listAttempts('learner'), 'get', '/feedback/attempts/learner', {}],
  [() => profileApi.list(), 'get', '/profiles/'],
]
const originalAdapter = api.defaults.adapter
const originalWindow = globalThis.window
let requests = 0
try {
  for (const [execute, method, url, expectedParams, data] of calls) {
    api.defaults.adapter = async config => {
      requests++
      assert.equal(config.method, method)
      assert.equal(config.url, url)
      assert.deepEqual(config.params, expectedParams)
      assert.deepEqual(config.data === undefined ? undefined : JSON.parse(config.data), data)
      assert.equal(config.baseURL, '/api')
      assert.equal(config.withCredentials, true)
      assert.equal(config.timeout, 120000)
      return { data: JSON.stringify({ synthetic: true }), status: 200, statusText: 'OK', config, headers: {} }
    }
    const response = await execute()
    assert.deepEqual(response.data, { synthetic: true }, 'keep the Axios response wrapper')
    assert.equal(response.status, 200)
  }
  assert.equal(resourceApi.downloadUrl('r/a'), '/api/resources/file/r/a')
  globalThis.window = { location: { pathname: '/fixture', search: '', assign: () => assert.fail('unexpected redirect') } }
  const failure = Object.assign(new Error('synthetic'), { response: { status: 503 }, config: { url: '/report/learner' } })
  api.defaults.adapter = async () => { throw failure }
  await assert.rejects(reportApi.get('learner'), error => error === failure, 'keep the original Axios rejection')
} finally {
  api.defaults.adapter = originalAdapter
  if (originalWindow === undefined) delete globalThis.window
  else globalThis.window = originalWindow
}

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const eslint = new ESLint({ cwd: frontend })
const negative = [
  ['src/features/generation/probe.js', "import { profileApi } from '../../api'"],
  ['src/features/generation/probe.js', "import { profileApi } from '../../api/index.js'"],
  ['src/features/generation/probe.js', "export { profileApi } from '../../api/index'"],
  ['src/stores/probe.js', "import { authApi } from '../api/'"],
  ['src/probe.js', "import { profileApi } from './api/index.js'"],
  ['src/features/generation/Probe.vue', "<script setup>import { profileApi } from '../../api'</script><template><div /></template>"],
]
for (const [filePath, code] of negative) {
  const [result] = await eslint.lintText(code, { filePath })
  assert.ok(result.messages.some(message => message.ruleId === 'no-restricted-imports'), `${filePath}: prohibited import must fail`)
}
for (const code of [
  "import { api } from '../../api/client.js'",
  "import { generateApi } from './api'",
  "import { resourceApi } from '../learning-documents/api.js'",
]) {
  const [result] = await eslint.lintText(code, { filePath: 'src/features/generation/probe.js' })
  assert.equal(result.errorCount, 0, JSON.stringify(result.messages))
}
console.log(`API modules: 15 identical exports, ${requests} request contracts, error propagation, 6 rejected imports and 3 allowed imports passed`)
