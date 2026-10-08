import assert from 'node:assert/strict'
import { resourceShelfTypeLabel, sortResourcesForShelf } from '../src/utils/resourceShelfOrder.js'

const resources = [
  { resource_id: 'test-old', resource_type: '分阶测试题', created_at: '2026-01-01T00:00:00Z' },
  { resource_id: 'lecture-new', resource_type: '讲义 HTML', created_at: '2026-01-03T00:00:00Z' },
  { resource_id: 'lecture-old', resource_type: '讲义', created_at: '2026-01-01T00:00:00Z' },
  { resource_id: 'courseware', resource_type: '互动HTML课件', resource_kind: 'interactive_courseware', created_at: '2026-01-04T00:00:00Z' },
  { resource_id: 'courseware-lecture', resource_type: '互动HTML课件', resource_kind: 'interactive_courseware', source_resource_type: '讲义', created_at: '2026-01-02T00:00:00Z' },
  { resource_id: 'test-new', resource_type: 'assessment', created_at: '2026-01-05T00:00:00Z' },
]

const ordered = sortResourcesForShelf(resources)

assert.deepEqual(
  ordered.map((resource) => resource.resource_id),
  ['lecture-old', 'courseware-lecture', 'lecture-new', 'courseware', 'test-old', 'test-new'],
)
assert.deepEqual(
  resources.map((resource) => resource.resource_id),
  ['test-old', 'lecture-new', 'lecture-old', 'courseware', 'courseware-lecture', 'test-new'],
)
assert.equal(resourceShelfTypeLabel(resources[4]), '互动讲义')

console.log('resource shelf ordering tests passed')
