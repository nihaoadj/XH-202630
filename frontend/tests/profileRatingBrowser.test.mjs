// Only local built UI and intercepted fixtures; no user backend or model calls.
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = path.join(frontend, 'tests/test-results/profile-rating')
const server = createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname
  const requested = path.resolve(dist, '.' + pathname)
  const file = requested.startsWith(dist + path.sep) && existsSync(requested) && path.extname(requested)
    ? requested : path.join(dist, 'index.html')
  res.setHeader('content-type', ({ '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[path.extname(file)] || 'text/html')
  res.end(readFileSync(file))
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
const browser = await chromium.launch(browserOptions('PROFILE_RATING_BROWSER_CHANNEL'))
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const errors = []
const writes = []
page.on('pageerror', error => errors.push(error.message))
let rating = '中级'
const profile = () => ({ learner_id: 'rating-learner', user_id: 'rating-user', knowledge_base_id: 'kb',
  learner_type: '评级验收', skill_level: '初级', initial_skill_level: '初级', current_skill_level: rating,
  current_skill_node_id: 'main', learning_goal: 'learn', created_at: '2026-11-14T00:00:00Z' })
await page.route('**/api/**', async route => {
  const req = route.request()
  if (req.method() !== 'GET') writes.push(req.url())
  const url = new URL(req.url())
  let body = { items: [], resources: [], domains: [], rounds: [], learning_rounds: [], events: [] }
  if (url.pathname === '/api/auth/me') body = { user: { user_id: 'rating-user', username: 'rating', display_name: '评级验收' } }
  else if (url.pathname === '/api/profiles/') body = { items: [profile()], total: 1 }
  else if (url.pathname === '/api/knowledge/domains') body = { domains: [{ tracks: [{ track_id: 'kb', knowledge_base_id: 'kb', name: '测试方向' }] }] }
  else if (url.pathname.startsWith('/api/learning-history/')) body = { ...body, learner_id: 'rating-learner', profile: profile(), next_offset: null,
    current_state: { current_nodes: [], completed_nodes: [], latest_assessment: null, next_action: '' } }
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
})
const checks = []
try {
  for (rating of ['中级', '高级', '初级']) {
    await page.goto(base + '/dashboard')
    await page.waitForFunction(expected => {
      const item = [...document.querySelectorAll('.summary-item')].find(item => item.querySelector('.summary-label')?.textContent.trim() === '当前评级')
      return document.querySelector('.learning-summary')?.getAttribute('aria-busy') === 'false'
        && item?.querySelector('strong')?.textContent.trim() === expected
    }, rating)
    const item = page.locator('.summary-item').filter({ hasText: '当前评级' })
    assert.equal(await item.getAttribute('title'), '初始诊断：初级')
    checks.push(`current=${rating}; initial=初级`)
  }
  rating = '高级'
  await page.goto(base + '/learning/history')
  await page.locator('.profile-entry').waitFor()
  assert.match(await page.locator('.profile-entry').innerText(), /高级/)
  await page.getByRole('combobox', { name: '能力层级' }).press('ArrowDown')
  await page.getByRole('option', { name: '高级', exact: true }).click()
  assert.equal(await page.locator('.profile-entry').count(), 1)
  await page.getByRole('combobox', { name: '能力层级' }).press('ArrowDown')
  await page.getByRole('option', { name: '初级', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.profile-entry').length === 0)
  checks.push('history filter uses current rating, not initial diagnosis')
  assert.deepEqual(writes, [])
  assert.deepEqual(errors, [])
  mkdirSync(evidence, { recursive: true })
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify({ status: 'PASS', checks, errors, writes }, null, 2))
  console.log('PASS profile rating browser: ' + checks.length + ' checks')
} finally {
  await browser.close()
  await new Promise(resolve => server.close(resolve))
}
