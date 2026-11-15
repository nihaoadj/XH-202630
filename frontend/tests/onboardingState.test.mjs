import assert from 'node:assert/strict'
import { answersFor, clearAllDrafts, clearDraft, exclusiveSelection, findDirectionProfiles, isDomainAvailable, isTrackAvailable, jobsAllowRestart, profileMatchesDirection, readDraft, writeDraft } from '../src/features/onboarding/onboardingState.js'
const question = { question_id: 'q', type: 'multiple_choice', options: ['A', 'B', '都不了解'], validation: { exclusive_option_values: ['都不了解'] } }
assert.deepEqual(exclusiveSelection(['A', 'B', '都不了解'], ['A', 'B'], question), ['都不了解'])
assert.deepEqual(exclusiveSelection(['都不了解', 'B'], ['都不了解'], question), ['B'])
assert.deepEqual(exclusiveSelection(['A', 'B'], ['A'], question), ['A', 'B'])
assert.deepEqual(exclusiveSelection(['B', 'B', 'unknown'], [], question), ['B'])
assert.deepEqual(exclusiveSelection(['都不了解'], ['都不了解'], question), ['都不了解'])
assert.deepEqual(answersFor([question], { q: ['A', '都不了解'] }), { q: ['都不了解'] })
assert.deepEqual(exclusiveSelection(['A. 都不了解', 'B'], ['A. 都不了解'], { options: ['A. 都不了解', 'B'] }), ['B'])
assert.equal(isDomainAvailable({ domain_id: 'ai_application' }), true)
assert.equal(isDomainAvailable({ domain_id: 'other', enabled: true }), false)
assert.equal(isTrackAvailable({ metadata: { available: false } }), false)
const storageMap = new Map()
const storage = { getItem: key => storageMap.get(key), setItem: (key, value) => storageMap.set(key, value), removeItem: key => storageMap.delete(key), key: i => [...storageMap.keys()][i], get length() { return storageMap.size } }
const draft = { stage: 'questionnaire', form: { q: ['A'] }, diagnosticAnswers: {} }
writeDraft('A', draft, storage, 1000)
assert.deepEqual(readDraft('A', storage, 1001), draft)
assert.equal(readDraft('B', storage, 1001), null)
assert.equal(readDraft('A', storage, 1000 + 25 * 3600000), null)
storage.setItem('onboarding_draft_v1:A', '{broken')
assert.equal(readDraft('A', storage, 1001), null)
storage.setItem('onboarding_draft_v1:A', JSON.stringify({ version: 1, userId: 'B', savedAt: 1000, state: draft }))
assert.equal(readDraft('A', storage, 1001), null)
writeDraft('A', draft, storage, 1000)
writeDraft('B', draft, storage, 1000)
clearDraft('A', storage)
assert.equal(readDraft('A', storage, 1001), null)
clearAllDrafts(storage)
assert.equal(storage.length, 0)
assert.equal(writeDraft('A', { ...draft, text: 'A'.repeat(512001) }, storage), false)
const denied = { getItem() { throw Error('denied') }, setItem() { throw Error('denied') }, removeItem() { throw Error('denied') } }
writeDraft('A', draft, denied, 1000)
assert.deepEqual(readDraft('A', denied, 1001), draft)
clearAllDrafts(storage)
const previousStorage = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
Object.defineProperty(globalThis, 'sessionStorage', { configurable:true, get() { throw Error('blocked storage getter') } })
try {
  assert.equal(writeDraft('blocked', draft), true)
  assert.deepEqual(readDraft('blocked'), draft)
  clearAllDrafts()
} finally {
  if (previousStorage) Object.defineProperty(globalThis, 'sessionStorage', previousStorage)
  else delete globalThis.sessionStorage
}
const direction = { track_id: 'track', knowledge_base_id: 'kb' }
const profile = { learner_id: 'real-random-id', user_id: 'A', knowledge_base_id: 'kb' }
assert.equal(profileMatchesDirection(profile, direction, 'A'), true)
assert.equal(profileMatchesDirection(profile, direction, 'B'), false)
assert.equal(profileMatchesDirection({ ...profile, learning_preferences: { metadata: { onboarding: { learning_direction_id: 'another-track' } } } }, direction, 'A'), false)
const pages = []
const list = async ({ page }) => { pages.push(page); return { data: { total: 2, items: page === 1 ? [{ ...profile, learner_id: 'unrelated', knowledge_base_id: 'elsewhere' }] : [profile] } } }
assert.deepEqual(await findDirectionProfiles(list, direction, 'A'), [profile])
assert.deepEqual(pages, [1, 2])
assert.equal(await findDirectionProfiles(list, direction, 'A', () => false), null)
await assert.rejects(findDirectionProfiles(async () => ({ data: { items: [], total: 1 } }), direction, 'A'))
await assert.rejects(findDirectionProfiles(async () => ({ data: { items: [] } }), direction, 'A'))
await assert.rejects(findDirectionProfiles(async () => ({ data: { items: [profile], total: 2 } }), direction, 'A'))
assert.equal(jobsAllowRestart({ data: { items: [{ status: 'published' }] } }, 'status'), true)
assert.equal(jobsAllowRestart({ data: { items: [{ status: 'rendering' }] } }, 'status'), false)
assert.equal(jobsAllowRestart({ data: { items: [{ status: 'unknown' }] } }, 'status'), false)
assert.equal(jobsAllowRestart({ data: { items: [], total: 2 } }, 'status'), false)
console.log('PASS onboarding mutual exclusion, scoped bounded drafts, exact paginated matches and conservative restart checks')
