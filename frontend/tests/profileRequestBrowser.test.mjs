import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(frontend, 'dist')
const evidence = path.join(frontend, 'tests/test-results/ui-repair/profile-requests')
assert.ok(existsSync(path.join(dist, 'index.html')), 'Build the frontend before browser verification')
mkdirSync(evidence, { recursive: true })
const summary = { status: 'RUNNING', evidence_type: 'browser_fixture', checks: [], screenshots: [], requests: [], unexpectedApi: [], writes: [], pageErrors: [], externalRequests: [] }
const profiles = ['A', 'B'].map((id) => ({
  learner_id: `learner-${id}`, knowledge_base_id: `kb-${id}`, learner_type: `画像${id}`,
  skill_level: id === 'A' ? '初级' : '中级', learning_goal: `方向${id}学习目标`,
  created_at: '2026-10-01T08:00:00Z',
  learning_preferences: { metadata: { user_profile_snapshot: { display_name: `画像${id}` } } },
}))
const streams = new Set()
const gates = []
const failures = new Set()
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done }); return { promise, resolve } }

// Hold a real browser request at an exact endpoint. Releasing it explicitly
// makes the ordering reproducible without guessing network/sleep durations.
function hold(key) {
  const gate = { key, captured: false, ready: deferred(), release: deferred(), done: deferred() }
  gates.push(gate)
  return gate
}
function job(learnerId, runId = `run-${learnerId.at(-1)}`) {
  return { learner_id: learnerId, run_id: runId, batch_id: `batch-${runId}`, job_status: 'completed', status: 'completed',
    created_at: '2026-10-01T08:00:00Z', finished_at: '2026-10-01T08:06:00Z',
    request_payload: { learner_id: learnerId, resource_types: ['讲义'], include_review: true, include_claim_check: false },
    resource_progress_summary: { total: 1, completed: 1, published: 1, failed: 0 } }
}
function material(learnerId, runId = `run-${learnerId.at(-1)}`) {
  const id = learnerId.at(-1)
  return { id: `res-${runId}`, resource_id: `res-${runId}`, learner_id: learnerId, run_id: runId, batch_id: `batch-${runId}`,
    resource_kind: 'learning_document', resource_type: '讲义', title: `材料-${runId}`, difficulty: id === 'A' ? '初级' : '中级',
    topic: `主题${id}`, knowledge_points: [], content_text: `# 材料标题\n\n## 正文-${id}\n\n这是${runId}的学习内容。`,
    created_at: '2026-10-01T08:00:00Z', source_refs: [] }
}
function journey(learnerId, offset) {
  const id = learnerId.at(-1)
  const now = Date.now()
  const round = { round_id: `${learnerId}-${offset}`, batch_id: `batch-${learnerId}`, run_id: `run-${id}`,
    topic: offset ? `分页${id}` : `学习轮次${id}`, status: 'completed', occurred_at: new Date(now).toISOString(),
    resources: [], assessment: null, feedback: null, path_change: null, run_summary: { availability: 'available' } }
  return { learner_id: learnerId, profile: profiles.find((item) => item.learner_id === learnerId),
    current_state: { current_nodes: [{ knowledge_point_id: `节点${id}` }], completed_nodes: [], latest_assessment: null, next_action: `建议${id}` },
    rounds: [round], total_rounds: 2, next_offset: offset ? null : 20,
    unlinked_events: [
      { event_id: `old-${id}`, title: `旧事件${id}`, description: '范围外历史事件', occurred_at: new Date(now - 60 * 86400000).toISOString(), status: 'completed' },
      { event_id: `recent-${id}`, title: `近期事件${id}`, description: '范围内历史事件', occurred_at: new Date(now - 86400000).toISOString(), status: 'completed' },
    ] }
}
function report(learnerId, days) {
  return { learner_id: learnerId, window: { window_days: days }, skill_level: learnerId.endsWith('A') ? '初级' : '中级',
    report_revision: `rpt_${learnerId}_${days}`.padEnd(68, '0'),
    metric_summary: { resource_count: (learnerId.endsWith('A') ? 100 : 200) + days, feedback_count: 1, weak_point_count: 1 },
    next_suggestions: [`报告建议${learnerId.at(-1)}-${days}`] }
}

const server = createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1')
  const reportEvents = url.pathname.match(/^\/api\/report\/(learner-[AB])\/events$/)
  const runEvents = url.pathname.match(/^\/api\/runs\/(run-[AB])\/events$/)
  if (reportEvents || runEvents) {
    response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' })
    const client = { path: url.pathname, response }
    streams.add(client)
    response.on('close', () => streams.delete(client))
    if (reportEvents) {
      const learnerId = reportEvents[1]; const days = Number(url.searchParams.get('window_days'))
      response.write(`event: report_snapshot\ndata: ${JSON.stringify({ learner_id: learnerId, window_days: days, report_revision: report(learnerId, days).report_revision })}\n\n`)
    } else response.write(': connected\n\n')
    return
  }
  const candidate = path.resolve(dist, '.' + decodeURIComponent(url.pathname))
  const contained = candidate.startsWith(dist + path.sep)
  const file = contained && existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, 'index.html')
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }
  response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' })
  response.end(readFileSync(file))
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const baseUrl = `http://127.0.0.1:${server.address().port}`
let browser
let activePage

function responseFor(url) {
  const p = url.pathname
  if (p === '/api/auth/me') return { user: { user_id: 'repair-fixture', username: 'repair', display_name: '验收用户' } }
  if (p === '/api/profiles/') return { items: profiles, total: profiles.length }
  if (p === '/api/knowledge/domains') return { domains: [{ domain_id: 'domain', tracks: profiles.map((item) => ({ track_id: item.knowledge_base_id, name: `方向${item.learner_id.at(-1)}` })) }] }
  if (p === '/api/skills/nodes') return { nodes: [] }
  if (p === '/api/resources/courseware/jobs') return { items: [], total: 0 }
  if (p === '/api/generate/jobs') {
    const learnerId = url.searchParams.get('learner_id')
    const items = [job(learnerId)]
    return { items, total: items.length }
  }
  let m = p.match(/^\/api\/learning-history\/(learner-[AB])\/journey$/)
  if (m) return journey(m[1], Number(url.searchParams.get('offset') || 0))
  m = p.match(/^\/api\/report\/(learner-[AB])$/)
  if (m) return report(m[1], Number(url.searchParams.get('window_days')))
  m = p.match(/^\/api\/resource-library\/(learner-[AB])$/)
  if (m) return [material(m[1])]
  m = p.match(/^\/api\/resources\/(learner-[AB])$/)
  if (m) return { resources: [material(m[1], url.searchParams.get('run_id') || undefined)] }
  m = p.match(/^\/api\/resources\/items\/res-(run-[AB](?:-extra)?)$/)
  if (m) return material(`learner-${m[1][4]}`, m[1])
  m = p.match(/^\/api\/generate\/jobs\/(run-[AB](?:-extra)?)$/)
  if (m) return job(`learner-${m[1][4]}`, m[1])
  m = p.match(/^\/api\/runs\/(run-[AB](?:-extra)?)\/timeline$/)
  if (m) return { events: [], has_more: false, last_sequence: 0 }
  m = p.match(/^\/api\/runs\/(run-[AB](?:-extra)?)\/claims$/)
  if (m) return { resource_reports: [] }
  return undefined
}
function keyFor(url) { return url.pathname + url.search }
async function open(routePath) {
  const context = await browser.newContext({ viewport: { width: 1393, height: 871 } })
  context.setDefaultTimeout(10000)
  await context.addInitScript((profile) => {
    localStorage.clear(); localStorage.setItem('last_learner_id', profile.learner_id)
    localStorage.setItem('current_profile', JSON.stringify(profile))
    localStorage.setItem('learning_direction_id', profile.knowledge_base_id)
    localStorage.setItem('learning_direction_name', '方向A')
    localStorage.setItem('app_sidebar_collapsed', 'true')
  }, profiles[0])
  await context.route('**/*', async (route) => {
    const request = route.request(); const url = new URL(request.url())
    if (url.origin !== baseUrl) { summary.externalRequests.push(request.url()); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const record = { method: request.method(), path: url.pathname, query: url.search }
    summary.requests.push(record)
    if (record.method !== 'GET') { summary.writes.push(record); return route.fulfill({ status: 403, json: { message: 'Fixture is read only' } }) }
    if (url.pathname.endsWith('/events')) return route.continue()
    const payload = responseFor(url)
    if (payload === undefined) { summary.unexpectedApi.push(record); return route.fulfill({ status: 404, json: { message: 'Unexpected fixture endpoint' } }) }
    const key = keyFor(url)
    const gate = gates.find((item) => !item.captured && item.key === key)
    const failed = failures.has(key)
    if (gate) { gate.captured = true; gate.ready.resolve(); await gate.release.promise }
    try {
      await route.fulfill({ status: failed ? 503 : 200, json: failed ? { message: 'fixture 暂时不可用，请重试' } : payload })
      record.status = failed ? 503 : 200
    } catch (error) { record.cancelled = String(error) }
    finally { gate?.done.resolve() }
  })
  const page = await context.newPage(); activePage = page
  page.on('pageerror', (error) => summary.pageErrors.push(String(error)))
  await page.goto(baseUrl + routePath)
  return { context, page }
}
async function choose(page, field, text) {
  await field.locator('.el-select__wrapper').click()
  await page.getByRole('option').filter({ hasText: text }).first().click()
}
async function release(page, gate) {
  const delivered = page.waitForResponse((res) => keyFor(new URL(res.url())) === gate.key)
  gate.release.resolve()
  const [, response] = await Promise.all([gate.done.promise, delivered])
  await response.finished()
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))))
}
async function waitForGate(gate) {
  let timeout
  try {
    await Promise.race([gate.ready.promise, new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error(`Request was not captured: ${gate.key}`)), 10000)
    })])
  } finally { clearTimeout(timeout) }
}
async function capture(name, page) {
  const file = path.join(evidence, name + '.png')
  await page.keyboard.press('Escape')
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  summary.screenshots.push(file)
}
async function check(name, page) {
  await capture(name, page)
  summary.checks.push(name)
}
async function textEquals(locator, value) {
  await locator.page().waitForFunction(({ selector, expected }) => document.querySelector(selector)?.textContent.trim() === expected,
    { selector: await locator.evaluate((el) => { el.setAttribute('data-repair-value', 'current'); return '[data-repair-value="current"]' }), expected: value })
  assert.equal((await locator.textContent()).trim(), value)
}

try {
  browser = await chromium.launch(browserOptions('PROFILE_REQUEST_BROWSER_CHANNEL'))

  // History: failures clear the previous profile; old pagination and a slow
  // B request cannot write into A. The newer request owns its loading state.
  {
    const { page, context } = await open('/learning/history')
    const node = page.locator('.state-grid strong').first()
    await textEquals(node, '节点A')
    await choose(page, page.locator('.round-filters .el-select').nth(1), '近 7 天')
    assert.equal(await page.locator('.history-event').filter({ hasText: '旧事件A' }).count(), 0)
    assert.equal(await page.locator('.history-event').filter({ hasText: '近期事件A' }).count(), 1)
    await check('history-period-filters-events', page)
    const bKey = '/api/learning-history/learner-B/journey?offset=0&limit=20'
    failures.add(bKey)
    await page.locator('.profile-item').filter({ hasText: '画像B' }).click()
    await page.getByRole('heading', { name: '学习记录暂未载入' }).waitFor()
    assert.equal(await page.locator('.state-grid').count(), 0)
    assert.match(await page.locator('.timeline-empty').textContent(), /fixture 暂时不可用/)
    await capture('history-profile-error', page)
    failures.delete(bKey)
    await page.getByRole('button', { name: '重新加载', exact: true }).click()
    await textEquals(node, '节点B')
    await check('history-profile-failure-retry', page)
    await page.locator('.profile-item').filter({ hasText: '画像A' }).click(); await textEquals(node, '节点A')
    const pagination = hold('/api/learning-history/learner-A/journey?offset=20&limit=20')
    await page.getByRole('button', { name: /加载更多轮次/ }).click(); await waitForGate(pagination)
    await page.locator('.profile-item').filter({ hasText: '画像B' }).click(); await textEquals(node, '节点B')
    await release(page, pagination)
    assert.equal(await page.locator('.journey-chain-item').filter({ hasText: '分页A' }).count(), 0)
    await check('history-stale-pagination', page)
    await page.locator('.profile-item').filter({ hasText: '画像A' }).click(); await textEquals(node, '节点A')
    const old = hold(bKey); const current = hold('/api/learning-history/learner-A/journey?offset=0&limit=20')
    await page.locator('.profile-item').filter({ hasText: '画像B' }).click(); await waitForGate(old)
    await page.locator('.profile-item').filter({ hasText: '画像A' }).click(); await waitForGate(current)
    await release(page, old)
    assert.equal(await page.locator('.journey-workspace').getAttribute('aria-busy'), 'true')
    assert.equal(await page.locator('.state-grid').count(), 0)
    await release(page, current); await textEquals(node, '节点A')
    assert.equal(await page.locator('.journey-workspace').getAttribute('aria-busy'), 'false')
    await check('history-latest-profile-owns-loading', page)
    await context.close()
  }

  // Report: a failed new window must show no old metric and no old stream.
  // Profile and time-window races are exercised independently.
  {
    const { page, context } = await open('/report')
    const metric = page.locator('.summary-metric strong').first()
    await textEquals(metric, '130')
    await page.waitForFunction(() => document.querySelector('.summary-metric.amber small')?.textContent === '自动更新已开启')
    const windowKey = '/api/report/learner-A?window_days=7'; failures.add(windowKey)
    await choose(page, page.locator('.report-window-field .el-select'), '近 7 天')
    await page.locator('.report-state-error').waitFor(); await textEquals(metric, '0')
    assert.equal((await page.locator('.summary-metric.amber small').textContent()).trim(), '自动更新已停止')
    await page.waitForFunction(() => document.querySelector('.report-refresh-button')?.classList.contains('is-loading') === false)
    assert.equal([...streams].filter((item) => item.path.startsWith('/api/report/')).length, 0)
    await capture('report-window-error', page)
    failures.delete(windowKey)
    await page.getByRole('button', { name: '重新加载', exact: true }).click(); await textEquals(metric, '107')
    await check('report-window-failure-retry', page)
    const old = hold('/api/report/learner-B?window_days=7')
    await choose(page, page.locator('.report-profile-field .el-select'), '画像B'); await waitForGate(old)
    await choose(page, page.locator('.report-profile-field .el-select'), '画像A'); await textEquals(metric, '107')
    await release(page, old); await textEquals(metric, '107')
    assert.match(await page.locator('.report-focus b').textContent(), /初级/)
    await check('report-stale-profile-response', page)
    const oldWindow = hold('/api/report/learner-A?window_days=30')
    await choose(page, page.locator('.report-window-field .el-select'), '近 30 天'); await waitForGate(oldWindow)
    await choose(page, page.locator('.report-window-field .el-select'), '近 90 天'); await textEquals(metric, '190')
    await release(page, oldWindow); await textEquals(metric, '190')
    await check('report-stale-window-response', page)
    await context.close()
  }

  {
    const { page, context } = await open('/generate')
    const code = page.locator('.summary-code')
    await textEquals(code, 'RUN-A')
    await page.locator('.resource-stage').getByRole('heading', { name: '正文-A' }).waitFor()
    const old = hold('/api/generate/jobs?learner_id=learner-B')
    await choose(page, page.locator('.task-selector .el-select').first(), '画像B'); await waitForGate(old)
    await choose(page, page.locator('.task-selector .el-select').first(), '画像A'); await textEquals(code, 'RUN-A')
    await release(page, old); await textEquals(code, 'RUN-A')
    assert.match(await page.locator('.resource-stage').textContent(), /正文-A/)
    assert.doesNotMatch(await page.locator('.resource-stage').textContent(), /正文-B/)
    await check('generation-stale-job-list', page)
    const oldResource = hold('/api/resources/learner-B?run_id=run-B&page=1&page_size=100')
    await choose(page, page.locator('.task-selector .el-select').first(), '画像B'); await waitForGate(oldResource)
    await choose(page, page.locator('.task-selector .el-select').first(), '画像A')
    await page.locator('.resource-stage').getByRole('heading', { name: '正文-A' }).waitFor()
    await release(page, oldResource)
    assert.match(await page.locator('.resource-stage').textContent(), /正文-A/)
    assert.doesNotMatch(await page.locator('.resource-stage').textContent(), /正文-B/)
    assert.equal(await page.evaluate(() => localStorage.getItem('current_generation_run_id')), 'run-A')
    await check('generation-stale-resource-chain', page)
    await context.close()
  }

  {
    const { page, context } = await open('/resources')
    const reader = page.locator('.resources-page .reader-card')
    await reader.getByRole('heading', { name: '正文-A' }).waitFor()
    const old = hold('/api/resource-library/learner-B')
    await choose(page, page.locator('.toolbar-fields .el-select').first(), '方向B'); await waitForGate(old)
    await choose(page, page.locator('.toolbar-fields .el-select').first(), '方向A')
    await reader.getByRole('heading', { name: '正文-A' }).waitFor()
    await release(page, old)
    assert.match(await reader.textContent(), /正文-A/); assert.doesNotMatch(await reader.textContent(), /正文-B/)
    await check('resources-stale-library-response', page)
    // Detail requests are separate from the library response and must also
    // keep their original resource/profile context when they arrive late.
    const oldDetail = hold('/api/resources/items/res-run-B')
    await choose(page, page.locator('.toolbar-fields .el-select').first(), '方向B'); await waitForGate(oldDetail)
    await choose(page, page.locator('.toolbar-fields .el-select').first(), '方向A')
    await reader.getByRole('heading', { name: '正文-A' }).waitFor()
    await release(page, oldDetail)
    assert.match(await reader.textContent(), /正文-A/); assert.doesNotMatch(await reader.textContent(), /正文-B/)
    const key = '/api/resource-library/learner-B'; failures.add(key)
    await choose(page, page.locator('.toolbar-fields .el-select').first(), '方向B')
    await page.getByRole('heading', { name: '学习材料暂未载入' }).waitFor()
    assert.equal(await page.locator('.resources-page .reader-card').count(), 0)
    await capture('resources-library-error', page)
    failures.delete(key)
    await page.getByRole('button', { name: '重新加载', exact: true }).click()
    await reader.getByRole('heading', { name: '正文-B' }).waitFor()
    await check('resources-detail-isolation-failure-retry', page)
    await context.close()
  }
  assert.deepEqual(summary.unexpectedApi, [])
  assert.deepEqual(summary.writes, [])
  assert.deepEqual(summary.externalRequests, [])
  assert.deepEqual(summary.pageErrors, [])
  summary.status = 'PASS'
  console.log(`Profile request browser checks passed: ${summary.checks.length}; ${summary.requests.length} fixture requests`)
} catch (error) {
  summary.status = 'FAIL'; summary.error = String(error.stack || error)
  if (activePage && !activePage.isClosed()) await activePage.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  for (const gate of gates) gate.release.resolve()
  writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify(summary, null, 2))
  await browser?.close()
  for (const client of streams) client.response.end()
  server.closeAllConnections()
  await new Promise((resolve) => server.close(resolve))
}
