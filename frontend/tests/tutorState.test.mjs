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
const feedbackView = readFileSync(new URL('../src/features/feedback/FeedbackView.vue', import.meta.url), 'utf8')
assert.match(resourcesView, /向 Tutor 提问/, 'resource page must expose the Tutor entry')
assert.match(feedbackView, /需要提示/, 'evaluation questions must expose the Tutor entry')
assert.match(feedbackView, /hint_count: tutorHelpCount\.value/, 'formal attempt must carry Tutor usage')
assert.match(drawer, /source_type: props\.contextType === 'question_help' && props\.batchId \? 'batch'/, 'batch feedback must create a batch-scoped Tutor session')
assert.match(drawer, /watch\(\(\) => props\.modelValue,[\s\S]*?ensureSession\(\)/, 'opening the panel must restore or create a session')
assert.match(drawer, /tutorApi\.getSession/, 'refresh restore must load persisted turns')
assert.match(drawer, /:disabled="!canSend"/, 'loading or sending must disable duplicate sends')
assert.match(drawer, /<SourceRefList/, 'Tutor evidence must use the shared source component')
assert.match(drawer, /evidence_insufficient/, 'safe evidence failure must be visible')
assert.doesNotMatch(drawer, /raw_prompt|chain_of_thought|api_key/i)

console.log('tutor state tests passed')
