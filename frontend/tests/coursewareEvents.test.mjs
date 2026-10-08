import assert from 'node:assert/strict'
import {
  acknowledgeCoursewareEvents,
  createCoursewareEvent,
  enqueueCoursewareEvent,
  pendingCoursewareEvents,
  projectCoursewareProgress,
} from '../src/features/courseware/offlineEvents.js'

function storage() {
  const values = new Map()
  return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value) }
}

const store = storage()
const viewed = createCoursewareEvent({ event_type: 'scene_viewed', resource_id: 'resource-1', release_id: 'release-a', scene_id: 'scene-1', state: { scene_index: 0, secret: 'drop' } })
assert.equal(viewed.state.secret, undefined)
enqueueCoursewareEvent(viewed, store)
enqueueCoursewareEvent(viewed, store)
assert.equal(pendingCoursewareEvents(store).length, 1)

const completed = createCoursewareEvent({ event_type: 'scene_completed', resource_id: 'resource-1', release_id: 'release-a', scene_id: 'scene-1', state: { completed: true } })
const oldRelease = createCoursewareEvent({ event_type: 'scene_completed', resource_id: 'resource-1', release_id: 'release-old', scene_id: 'scene-1', state: { completed: true } })
assert.deepEqual(projectCoursewareProgress([viewed, completed, oldRelease], { resource_id: 'resource-1', release_id: 'release-a' }), {
  resource_id: 'resource-1', release_id: 'release-a', viewed_scene_ids: ['scene-1'], completed_scene_ids: ['scene-1'], courseware_completed: false, answer_count: 0,
})
acknowledgeCoursewareEvents([viewed.event_id], store)
assert.equal(pendingCoursewareEvents(store).length, 0)
console.log('courseware offline event tests passed')
