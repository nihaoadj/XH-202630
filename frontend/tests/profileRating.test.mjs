import assert from 'node:assert/strict'
import { currentProfileRating, initialProfileRating, matchesProfileRating } from '../src/utils/profileRating.js'

const profile = { skill_level: '初级', initial_skill_level: '初级', current_skill_level: '中级' }
assert.equal(currentProfileRating(profile), '中级')
assert.equal(initialProfileRating(profile), '初级')
assert.equal(currentProfileRating({ ...profile, current_skill_level: '高级' }), '高级')
assert.equal(currentProfileRating({ ...profile, current_skill_level: '初级' }), '初级')
assert.equal(currentProfileRating({ skill_level: '中级' }), '中级')
assert.equal(initialProfileRating({ skill_level: '中级' }), '中级')
assert.equal(currentProfileRating(null), '')
assert.equal(initialProfileRating(null), '')
assert.equal(profile.skill_level, '初级')
assert.equal(matchesProfileRating(profile, '中级'), true)
assert.equal(matchesProfileRating(profile, '初级'), false)
assert.equal(matchesProfileRating({ skill_level: '进阶' }, '高级'), true)
assert.equal(matchesProfileRating({ current_skill_level: '高级' }, '高级'), true)
assert.equal(matchesProfileRating(null, ''), true)
console.log('profile rating passed')
