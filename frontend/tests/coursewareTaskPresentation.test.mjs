import assert from 'node:assert/strict'
import { coursewareTaskSource } from '../src/features/generation/coursewareTaskPresentation.js'

const job = { source_summary: [{ resource_id: 'guide', title: '固定长度与段落切分实战', topic: 'Chunk切分', knowledge_points: ['chunking'] }] }
const result = coursewareTaskSource(job, { chunking: 'Chunk 切分' }, { chunking: 2 })
assert.equal(result.title, 'Chunk 切分')
assert.equal(result.sourceTitle, '固定长度与段落切分实战')
assert.equal(result.tier, 2)
assert.equal(coursewareTaskSource(job).title, 'Chunk切分')
assert.equal(coursewareTaskSource({ title: '旧课件' }).title, '旧课件')
assert.equal(coursewareTaskSource({}).title, '互动课件')
assert.equal(coursewareTaskSource({ source_summary: [{ title: '节点清单', knowledge_points: ['Chunk 切分'] }] }, { chunking: 'Chunk 切分' }, { chunking: 2 }).tier, 2)
console.log('courseware task presentation passed')
