import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { browserOptions } from './browserOptions.mjs'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const distDir = path.join(frontendDir, 'dist')
const evidenceDir = path.join(frontendDir, 'tests', 'test-results', 'history-ui')
const summaryPath = path.join(evidenceDir, 'summary.json')
if (!existsSync(path.join(distDir, 'index.html'))) {
  throw new Error('Run npm --prefix frontend run build before history UI browser verification')
}
mkdirSync(evidenceDir, { recursive: true })

const audit = { requests: [], writes: [], unexpectedApi: [], externalRequests: [], pageErrors: [] }
const summary = {
  status: 'RUNNING',
  evidence_type: 'browser_fixture',
  screenshots: [],
  checks: [],
  layout: [],
  audit,
}
const fixtureProfiles = Array.from({ length: 10 }, (_, index) => {
  const learnerId = ['learner-main', 'learner-mid', 'learner-advanced'][index] || `learner-extra-${index}`
  const skillLevel = ['初级', '中级', '进阶'][index % 3]
  const displayName = ['主画像（初级）', '中级画像', '进阶画像', `画像 ${index + 1}`][index] || `画像 ${index + 1}`
  return {
    learner_id: learnerId,
    learner_type: displayName,
    knowledge_base_id: `kb-${index % 3}`,
    skill_level: skillLevel,
    learning_goal: `熟练掌握验收方向 ${index + 1}`,
    learning_preferences: { metadata: { user_profile_snapshot: { display_name: displayName } } },
  }
})
const deletedLearners = new Set()
const referenceNow = Date.now()
const occurredAt = (daysAgo, hour = 10) => new Date(referenceNow - daysAgo * 86400000 + hour * 3600000).toISOString()

function roundFixture(index) {
  const seed = [
    { status: 'completed', day: 1, topic: '已完成的资源生成与测评' },
    { status: 'running', day: 2, topic: '正在生成的练习任务' },
    { status: 'queued', day: 3, topic: '排队等待的复习任务' },
    { status: 'failed', day: 9, topic: '失败后保留记录的任务' },
    { status: 'completed', day: 4, topic: '反馈后触发的后续学习' },
  ][index] || {
    status: index % 4 === 0 ? 'failed' : ['completed', 'running', 'queued'][index % 3],
    day: 12 + index,
    topic: `分页验收轮次 ${index + 1}`,
  }
  const runId = `run-${index + 1}`
  const hasOutcome = seed.status === 'completed' && index !== 1
  const isFollowup = index === 4
  return {
    round_id: `round-${index + 1}`,
    batch_id: `batch-${index + 1}`,
    run_id: runId,
    run_ids: [runId],
    topic: seed.topic,
    status: seed.status,
    occurred_at: occurredAt(seed.day),
    is_followup: isFollowup,
    parent_run_id: isFollowup ? 'run-1' : null,
    resources: hasOutcome ? [{ resource_type: '讲义', publication_status: 'published' }] : [],
    assessment: hasOutcome ? {
      score: 0.75,
      correct_count: 3,
      total_count: 4,
      knowledge_points: ['检索策略'],
    } : null,
    feedback: hasOutcome ? {
      action: 'practice',
      reason: '本轮练习巩固关键知识点。',
      next_action: '完成下一轮练习',
      followup_run_ids: isFollowup ? [] : index === 0 ? ['run-5'] : ['run-followup'],
    } : null,
    path_change: hasOutcome ? {
      path_version_before: 2,
      path_version_after: 3,
      mutation_type: 'insert_practice',
      assessed_nodes: [{ knowledge_point_id: '检索策略', name: '检索策略' }],
      next_steps: [{ topic: '证据核验' }],
      mastery_changes: [{ knowledge_point_id: '检索策略', before: 0.52, after: 0.75, status: 'improving' }],
    } : null,
    run_summary: seed.status === 'failed'
      ? { availability: 'available', current_node: 'review', review_count: 1, revision_count: 0, error_message: 'fixture 任务失败' }
      : { availability: 'available', current_node: 'completed', review_count: 1, revision_count: 1, error_message: null },
  }
}

const allRounds = Array.from({ length: 45 }, (_, index) => roundFixture(index))
const fixtureEvents = [
  { event_id: 'event-earlier', title: '创建学习画像', description: '画像创建时记录的独立事件。', occurred_at: occurredAt(20, 8), status: 'completed', payload: {} },
  { event_id: 'event-later', title: '完成入门诊断', description: '与生成批次无关联的诊断历史。', occurred_at: occurredAt(2, 11), status: 'completed', payload: {} },
  { event_id: 'event-middle', title: '更新学习目标', description: '保留的画像目标变更记录。', occurred_at: occurredAt(15, 9), status: 'completed', payload: {} },
]

let scenario = 'normal'
let browser
let serverStarted = false
let baseUrl = ''

function writeJson(response, body, status = 200) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  response.end(JSON.stringify(body))
}

function profileList() {
  if (scenario === 'empty-profiles') return []
  return fixtureProfiles.filter((profile) => !deletedLearners.has(profile.learner_id))
}

function journeyFor(learnerId, offset, limit) {
  const profile = fixtureProfiles.find((item) => item.learner_id === learnerId) || fixtureProfiles[0]
  if (scenario === 'empty-journey' && learnerId === 'learner-main') {
    return { learner_id: learnerId, profile, current_state: { current_nodes: [], completed_nodes: [], next_action: null, latest_assessment: null }, rounds: [], unlinked_events: [], total_rounds: 0, next_offset: null }
  }
  if (scenario === 'isolated-event' && learnerId === 'learner-main') {
    return { learner_id: learnerId, profile, current_state: { current_nodes: [], completed_nodes: [], next_action: null, latest_assessment: null }, rounds: [], unlinked_events: fixtureEvents, total_rounds: 0, next_offset: null }
  }
  if (learnerId !== 'learner-main') {
    const rounds = [roundFixture(0)]
    return { learner_id: learnerId, profile, current_state: { current_nodes: [], completed_nodes: [], next_action: null, latest_assessment: null }, rounds, unlinked_events: [], total_rounds: rounds.length, next_offset: null }
  }
  const isCompact = scenario === 'compact-journey'
  const roundSource = isCompact ? allRounds.slice(0, 5) : allRounds
  const rounds = roundSource.slice(offset, offset + limit)
  const nextOffset = offset + rounds.length < roundSource.length ? offset + rounds.length : null
  return {
    learner_id: learnerId,
    profile,
    current_state: {
      current_nodes: [{ knowledge_point_id: '临床证据检索' }, { knowledge_point_id: '数据校验' }],
      completed_nodes: [{ knowledge_point_id: '基础一' }, { knowledge_point_id: '基础二' }, { knowledge_point_id: '基础三' }],
      next_action: isCompact
        ? '复习证据核验后继续练习。'
        : '下一步建议：先复习临床证据检索的关键步骤，再逐项核对来源和回答之间的对应关系，完成后进入进阶病例分析。'.repeat(2),
      latest_assessment: { score: 0.875, correct_count: 7, total_count: 8, knowledge_points: ['临床证据检索'] },
    },
    rounds,
    unlinked_events: isCompact ? [] : fixtureEvents,
    total_rounds: roundSource.length,
    next_offset: nextOffset,
  }
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', 'http://127.0.0.1')
  const method = (request.method || 'GET').toUpperCase()
  if (url.pathname.startsWith('/api/')) {
    let rawBody = ''
    for await (const chunk of request) rawBody += chunk
    let body = null
    if (rawBody) {
      try { body = JSON.parse(rawBody) } catch { body = rawBody }
    }
    const record = { method, path: url.pathname, query: url.search, body }
    audit.requests.push(record)

    if (method === 'GET' && url.pathname === '/api/auth/me') {
      return writeJson(response, { user: { user_id: 'history-fixture-user', username: 'history.fixture', display_name: '学习历史验收用户' } })
    }
    if (method === 'GET' && url.pathname === '/api/profiles/') {
      const items = profileList()
      return writeJson(response, { items, total: items.length })
    }
    if (method === 'GET' && url.pathname === '/api/knowledge/domains') {
      return writeJson(response, { domains: [{ domain_id: 'domain-history', tracks: [
        { track_id: 'kb-0', name: '临床数据分析' }, { track_id: 'kb-1', name: '急救护理' }, { track_id: 'kb-2', name: '循证药学' },
      ] }] })
    }
    if (method === 'GET' && url.pathname === '/api/skills/nodes') return writeJson(response, { nodes: [] })
    if (method === 'GET' && /^\/api\/resource-library\/learner-[a-z0-9-]+$/.test(url.pathname)) return writeJson(response, [])
    const journeyMatch = url.pathname.match(/^\/api\/learning-history\/([^/]+)\/journey$/)
    if (method === 'GET' && journeyMatch) {
      const offset = Number(url.searchParams.get('offset') || 0)
      const limit = Number(url.searchParams.get('limit') || 20)
      record.pagination = { offset, limit }
      return writeJson(response, journeyFor(decodeURIComponent(journeyMatch[1]), offset, limit))
    }
    if (method === 'DELETE' && url.pathname === '/api/profiles/learner-main') {
      const allowed = scenario === 'delete-fixture'
      audit.writes.push({ method, path: url.pathname, body, allowed })
      if (!allowed) {
        audit.unexpectedApi.push({ method, path: url.pathname, reason: 'DELETE outside fixture confirmation step' })
        return writeJson(response, { detail: 'Unexpected fixture write' }, 403)
      }
      deletedLearners.add('learner-main')
      return writeJson(response, { deleted: true })
    }
    // Destination pages are mounted only by the explicit history route checks below.
    if (method === 'GET' && /^\/api\/resources\/learner-[a-z0-9-]+$/.test(url.pathname)) {
      return writeJson(response, { resources: [] })
    }
    if (method === 'GET' && url.pathname === '/api/generate/jobs') return writeJson(response, { items: [], total: 0 })
    if (method === 'GET' && url.pathname === '/api/resources/courseware/jobs') return writeJson(response, { items: [], total: 0 })

    audit.unexpectedApi.push({ method, path: url.pathname, query: url.search })
    if (method !== 'GET') audit.writes.push({ method, path: url.pathname, body, allowed: false })
    return writeJson(response, { detail: 'Unexpected history UI fixture API request' }, 404)
  }

  const decodedPath = decodeURIComponent(url.pathname)
  const candidatePath = path.resolve(distDir, `.${decodedPath}`)
  const safePrefix = distDir.endsWith(path.sep) ? distDir : distDir + path.sep
  let filePath = candidatePath.startsWith(safePrefix) || candidatePath === path.join(distDir, 'index.html')
    ? candidatePath : path.join(distDir, 'index.html')
  if (!existsSync(filePath)) filePath = path.join(distDir, 'index.html')
  const extension = path.extname(filePath).toLowerCase()
  const types = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2', '.ico': 'image/x-icon',
  }
  response.writeHead(200, { 'content-type': types[extension] || 'application/octet-stream' })
  response.end(readFileSync(filePath))
})

async function openHistoryPage(viewport, { currentScenario = 'normal', reducedMotion = false, collapsed = false } = {}) {
  scenario = currentScenario
  const page = await browser.newPage({ viewport })
  page.setDefaultTimeout(8000)
  page.on('pageerror', (error) => audit.pageErrors.push({ message: error.message, url: page.url() }))
  page.on('request', (request) => {
    const requestUrl = request.url()
    if (/^https?:/.test(requestUrl) && new URL(requestUrl).origin !== new URL(baseUrl).origin) audit.externalRequests.push(requestUrl)
  })
  await page.addInitScript(({ sidebarCollapsed }) => {
    localStorage.clear()
    localStorage.setItem('app_sidebar_collapsed', String(sidebarCollapsed))
  }, { sidebarCollapsed: collapsed })
  if (reducedMotion) await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(`${baseUrl}/learning/history`, { waitUntil: 'domcontentloaded' })
  await page.locator('.history-page').waitFor()
  if (currentScenario !== 'empty-profiles') await page.locator('.profile-entry > .profile-item').first().waitFor()
  return page
}

async function saveScreenshot(page, name) {
  const target = path.join(evidenceDir, name)
  await page.screenshot({ path: target, fullPage: false, animations: 'disabled' })
  summary.screenshots.push(path.relative(frontendDir, target).replaceAll('\\', '/'))
}

async function chooseOption(page, label, option) {
  const control = page.locator(`[aria-label="${label}"]`).first()
  await control.press('ArrowDown')
  await page.getByRole('option', { name: option, exact: true }).click()
}

async function clearOption(page, control, emptyLabel) {
  control = control.first()
  const emptyOption = page.getByRole('option', { name: emptyLabel, exact: true })
  await control.press('ArrowDown')
  if (await emptyOption.count()) {
    await emptyOption.click()
    return
  }
  await control.press('Escape')
  const selectRoot = control.locator('xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " el-select ")][1]')
  const clear = selectRoot.locator('.el-select__clear')
  if (await clear.count()) await clear.click({ force: true })
  else await control.press('Backspace')
}

async function checkProfileAndJourneyBehaviors(page) {
  const profileButtons = page.locator('.profile-entry')
  assert.equal(await profileButtons.count(), fixtureProfiles.length, 'profile directory should render every fixture profile')
  const firstProfileEntry = profileButtons.first()
  assert.equal(await firstProfileEntry.locator(':scope > .profile-item').getAttribute('aria-pressed'), 'true', 'initial profile should expose selected state')
  const selectionAndDelete = await firstProfileEntry.evaluate((entry) => {
    const selection = entry.querySelector(':scope > .profile-item')
    const deletion = entry.querySelector('.profile-delete-action')
    return {
      selectionIsButton: selection?.tagName === 'BUTTON',
      hasPressedState: selection?.hasAttribute('aria-pressed'),
      deleteIsSibling: Boolean(selection && deletion && selection.parentElement === deletion.parentElement),
      deleteNestedInSelection: Boolean(selection?.contains(deletion)),
    }
  })
  assert.deepEqual(selectionAndDelete, { selectionIsButton: true, hasPressedState: true, deleteIsSibling: true, deleteNestedInSelection: false }, 'profile selection should be a native button and deletion its sibling')
  assert.equal(await page.locator('.state-grid article').count(), 4, 'current learning state must show four metrics')
  const metricText = (await page.locator('.state-grid').innerText()).replaceAll('\n', ' ')
  assert.match(metricText, /当前学习节点[\s\S]*临床证据检索/)
  assert.match(metricText, /最近测评[\s\S]*88%/)
  assert.match(metricText, /已完成节点[\s\S]*3 个/)
  const longAction = page.locator('.state-grid article').nth(3).locator('strong')
  const longText = await longAction.innerText()
  assert.equal(longText, '下一步建议：先复习临床证据检索的关键步骤，再逐项核对来源和回答之间的对应关系，完成后进入进阶病例分析。'.repeat(2), 'long current-state guidance should remain complete')
  const textLayout = await longAction.evaluate((element) => ({
    text: getComputedStyle(element).whiteSpace,
    textOverflow: getComputedStyle(element).textOverflow,
    overflow: getComputedStyle(element).overflow,
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))
  assert.notEqual(textLayout.text, 'nowrap', 'long current-state text must wrap')
  assert.notEqual(textLayout.textOverflow, 'ellipsis', 'long current-state text must not use ellipsis')
  assert.ok(!['hidden', 'clip'].includes(textLayout.overflow), 'long current-state text must remain visibly readable')
  assert.ok(textLayout.scrollHeight <= textLayout.clientHeight + 1, `long current-state text should not be clipped: ${JSON.stringify(textLayout)}`)

  const statusFilter = page.locator('[aria-label="轮次状态"]')
  const timeFilter = page.locator('[aria-label="记录时间范围"]')
  const levelFilter = page.locator('[aria-label="能力层级"]')
  assert.ok(await statusFilter.count() >= 1, 'round status filter should be labeled')
  assert.ok(await timeFilter.count() >= 1, 'round time filter should be labeled')
  assert.ok(await levelFilter.count() >= 1, 'profile level filter should be labeled')
  const reload = page.getByRole('button', { name: '刷新学习画像' })
  assert.equal(await reload.count(), 1, 'profile refresh should be labeled')
  const beforeRefresh = audit.requests.filter((item) => item.method === 'GET' && item.path === '/api/profiles/').length
  const refreshResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/profiles/' && response.request().method() === 'GET')
  await reload.click()
  await refreshResponse
  const afterRefresh = audit.requests.filter((item) => item.method === 'GET' && item.path === '/api/profiles/').length
  assert.ok(afterRefresh > beforeRefresh, 'refresh action should reload the profile directory')

  await chooseOption(page, '能力层级', '进阶')
  const filteredCount = await profileButtons.count()
  assert.equal(filteredCount, fixtureProfiles.filter((item) => item.skill_level === '进阶').length, 'level filter should restrict visible profiles')
  const advanced = profileButtons.filter({ hasText: '进阶画像' }).first().locator(':scope > .profile-item')
  assert.equal(await advanced.count(), 1)
  const advancedJourneyResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/learning-history/learner-advanced/journey')
  await advanced.click()
  await advancedJourneyResponse
  assert.equal(await advanced.getAttribute('aria-pressed'), 'true', 'selecting a profile should update aria-pressed')
  assert.ok(audit.requests.some((item) => item.path === '/api/learning-history/learner-advanced/journey'), 'selection should load that learner journey')

  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.locator('.journey-chain-item').first().waitFor()
  const entry = page.locator('.profile-entry > .profile-item').first()
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0) })
  let focusedByTab = false
  for (let index = 0; index < 70; index += 1) {
    await page.keyboard.press('Tab')
    focusedByTab = await entry.evaluate((element) => element === document.activeElement)
    if (focusedByTab) break
  }
  assert.ok(focusedByTab, 'profile selection button should be reachable with real Tab navigation')
  assert.equal(await entry.evaluate((element) => element.matches(':focus-visible')), true, 'keyboard focus should use visible focus styling')
  await page.keyboard.press('Enter')
  assert.equal(await entry.getAttribute('aria-pressed'), 'true', 'Enter should select the focused profile')

  const roundButtons = page.locator('.journey-chain-item:not(.history-event) .round-summary button')
  const expandButton = roundButtons.first()
  assert.match(await expandButton.innerText(), /展开详情/)
  assert.equal(await expandButton.getAttribute('aria-expanded'), 'false', 'round details should begin collapsed')
  await expandButton.click()
  assert.equal(await expandButton.getAttribute('aria-expanded'), 'true', 'round details should expand')
  const firstRound = page.locator('.journey-chain-item:not(.history-event)').first()
  assert.equal(await firstRound.locator('.journey-stage').count(), 6, 'each round should expose six journey stages')
  for (let index = 0; index < 6; index += 1) {
    assert.notEqual(await firstRound.locator('.journey-stage').nth(index).evaluate((element) => getComputedStyle(element).display), 'none', `stage ${index + 1} should be visible`)
  }
  assert.equal(await firstRound.locator('.round-detail').count(), 1, 'expanded details should retain the original round detail content')
  for (const button of await firstRound.locator('.round-links button').all()) {
    const box = await button.boundingBox()
    assert.ok(box && box.height >= 44, `round navigation buttons should be at least 44px tall: ${JSON.stringify(box)}`)
  }
  await expandButton.click()
  assert.equal(await expandButton.getAttribute('aria-expanded'), 'false', 'round details should collapse again')

  const statusCases = [
    { topic: '已完成的资源生成与测评', status: 'done', statusText: '资源已生成', expected: ['done', 'done', 'done', 'done', 'done', 'done'] },
    { topic: '正在生成的练习任务', status: 'active', statusText: '正在生成', expected: ['active', 'pending', 'pending', 'pending', 'pending', 'pending'] },
    { topic: '排队等待的复习任务', status: 'active', statusText: '等待生成', expected: ['active', 'pending', 'pending', 'pending', 'pending', 'pending'] },
    { topic: '失败后保留记录的任务', status: 'failed', statusText: '生成失败', expected: ['failed', 'pending', 'pending', 'pending', 'pending', 'pending'] },
    { topic: '反馈后触发的后续学习', status: 'done', statusText: '资源已生成', expected: ['done', 'done', 'done', 'done', 'done', 'pending'] },
  ]
  for (const item of statusCases) {
    const row = page.locator('.journey-chain-item:not(.history-event)').filter({ hasText: item.topic }).first()
    assert.equal(await row.count(), 1, `round fixture should include ${item.topic}`)
    const stages = row.locator('.journey-stage')
    assert.equal(await stages.count(), 6, `${item.topic} should have six stages`)
    assert.match(await row.innerText(), new RegExp(item.statusText), `${item.topic} should retain its true status label`)
    const firstClass = await stages.first().getAttribute('class')
    assert.ok(firstClass.split(/\s+/).includes(item.status), `${item.topic} should show ${item.status} generation state: ${firstClass}`)
    for (let index = 0; index < item.expected.length; index += 1) {
      const classes = (await stages.nth(index).getAttribute('class')).split(/\s+/)
      assert.ok(classes.includes(item.expected[index]), `${item.topic} stage ${index + 1} should be ${item.expected[index]}`)
    }
  }
  const followupRound = page.locator('.journey-chain-item.followup').filter({ hasText: '反馈后触发的后续学习' })
  assert.equal(await followupRound.count(), 1, 'follow-up round should be visually distinguished')
  assert.match(await followupRound.innerText(), /由上一轮反馈触发/)

  const events = page.locator('.journey-chain-item.history-event')
  assert.equal(await events.count(), fixtureEvents.length, 'unlinked events should remain visible alongside rounds')
  const eventTitles = await events.locator('h3').allTextContents()
  assert.deepEqual(eventTitles, ['创建学习画像', '更新学习目标', '完成入门诊断'], 'unlinked events should be chronological')
  const originalEventCount = await events.count()
  await chooseOption(page, '轮次状态', '已完成')
  assert.ok(await page.locator('.journey-chain-item:not(.history-event)').count() < allRounds.slice(0, 20).length, 'status filter should reduce only the rounds')
  assert.equal(await events.count(), originalEventCount, 'status filter should keep unlinked events visible')
  await clearOption(page, statusFilter, '全部状态')
  await chooseOption(page, '记录时间范围', '近 7 天')
  assert.equal(await events.count(), 1, '近 7 天应隐藏较早的未关联事件并保留近期事件')
  assert.deepEqual(await events.locator('h3').allTextContents(), ['完成入门诊断'], '时间范围应同时筛选未关联事件')
  assert.ok(await page.locator('.journey-chain-item:not(.history-event)').count() < allRounds.slice(0, 20).length, 'time filter should reduce old rounds')
  await chooseOption(page, '记录时间范围', '全部时间')

  const firstPageRequests = audit.requests.filter((item) => item.path === '/api/learning-history/learner-main/journey')
  assert.ok(firstPageRequests.some((item) => item.pagination?.offset === 0 && item.pagination?.limit === 20), 'first journey page should request offset=0 and limit=20')
  const more = page.getByRole('button', { name: '加载更多轮次' })
  assert.equal(await more.count(), 1, 'server pagination should expose a load-more action')
  await more.click()
  await page.waitForFunction(() => document.querySelectorAll('.journey-chain-item:not(.history-event)').length === 40)
  assert.ok(audit.requests.some((item) => item.path === '/api/learning-history/learner-main/journey' && item.pagination?.offset === 20 && item.pagination?.limit === 20), 'next page should request offset=20 and limit=20')
  await page.getByRole('button', { name: '加载更多轮次' }).click()
  await page.waitForFunction(() => document.querySelectorAll('.journey-chain-item:not(.history-event)').length === 45)
  assert.ok(audit.requests.some((item) => item.path === '/api/learning-history/learner-main/journey' && item.pagination?.offset === 40 && item.pagination?.limit === 20), 'final page should keep the same limit and advance the offset')
  assert.equal(await page.getByRole('button', { name: '加载更多轮次' }).count(), 0, 'pagination control should disappear when no next page remains')
  summary.checks.push({ name: 'profiles-current-state-events-rounds-pagination', status: 'PASS' })
}

function parseColor(value) {
  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/)
  return match ? [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? 1 : Number(match[4])] : null
}

function luminance(color) {
  const channels = color.slice(0, 3).map((value) => {
    const channel = value / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

function contrastRatio(foreground, background) {
  const foregroundColor = parseColor(foreground)
  const backgroundColor = parseColor(background)
  assert.ok(foregroundColor && backgroundColor, `contrast colors should be parseable: ${foreground} / ${background}`)
  const backgroundOpaque = backgroundColor[3] === 1 ? backgroundColor : [255, 255, 255, 1]
  const foregroundOpaque = foregroundColor[3] === 1
    ? foregroundColor
    : foregroundColor.slice(0, 3).map((value, index) => value * foregroundColor[3] + backgroundOpaque[index] * (1 - foregroundColor[3]))
  const values = [luminance(foregroundOpaque), luminance(backgroundOpaque)].sort((left, right) => right - left)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

async function layoutSnapshot(page, label, viewport, { screenshot = true } = {}) {
  const pageData = await page.evaluate(() => {
    const history = document.querySelector('.history-page')
    const root = document.documentElement
    const primaryButtons = [...document.querySelectorAll('.profile-entry > .profile-item, .history-page .archive-list-head button, .journey-chain-item .round-summary button, .history-page .load-more, .round-links button')]
    const visibleButtons = [...document.querySelectorAll('.history-page button')].filter((button) => {
      const rect = button.getBoundingClientRect()
      const style = getComputedStyle(button)
      return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < window.innerWidth
        && rect.bottom > 0 && rect.top < window.innerHeight && style.visibility !== 'hidden' && style.display !== 'none'
    })
    const rectangles = visibleButtons.map((button) => ({
      label: button.getAttribute('aria-label') || button.innerText.trim().slice(0, 35),
      rect: button.getBoundingClientRect().toJSON(),
    }))
    const activeProfile = document.querySelector('.profile-entry > .profile-item[aria-pressed="true"]')
    return {
      pageWidth: history?.getBoundingClientRect().width || 0,
      documentWidth: root.scrollWidth,
      viewportWidth: window.innerWidth,
      documentHeight: root.scrollHeight,
      viewportHeight: window.innerHeight,
      primaryButtonHeights: primaryButtons.map((button) => ({ label: button.getAttribute('aria-label') || button.innerText.trim().slice(0, 35), height: button.getBoundingClientRect().height })),
      buttons: rectangles,
      activeColors: activeProfile ? { foreground: getComputedStyle(activeProfile).color, background: getComputedStyle(activeProfile).backgroundColor } : null,
      profileScrollHeight: document.querySelector('.profile-scroll')?.scrollHeight || 0,
      profileClientHeight: document.querySelector('.profile-scroll')?.clientHeight || 0,
      profileScrollTop: document.querySelector('.profile-scroll')?.scrollTop || 0,
      mainScrollers: [...document.querySelectorAll('.journey-workspace, .journey-panel, .journey-scroll, .journey-chain')].map((element) => ({
        className: element.className.baseVal || element.className,
        scrollHeight: element.scrollHeight,
        clientHeight: element.clientHeight,
        scrollTop: element.scrollTop,
        overflowY: getComputedStyle(element).overflowY,
      })),
    }
  })
  if (screenshot) await saveScreenshot(page, `history-${label}.png`)
  summary.layout.push({ name: label, viewport, ...pageData })
  assert.ok(pageData.documentWidth <= viewport.width + 1, `${label}: horizontal overflow ${pageData.documentWidth}px > ${viewport.width}px`)
  for (const button of pageData.primaryButtonHeights) {
    assert.ok(button.height >= 44, `${label}: main button is shorter than 44px (${button.label}: ${button.height}px)`)
  }
  for (const button of pageData.buttons) {
    assert.ok(button.rect.left >= -1 && button.rect.right <= viewport.width + 1, `${label}: button is clipped horizontally: ${JSON.stringify(button)}`)
    assert.ok(button.rect.top >= -viewport.height && button.rect.bottom <= viewport.height * 2, `${label}: button is unexpectedly displaced: ${JSON.stringify(button)}`)
  }
  for (let left = 0; left < pageData.buttons.length; left += 1) {
    for (let right = left + 1; right < pageData.buttons.length; right += 1) {
      const a = pageData.buttons[left]
      const b = pageData.buttons[right]
      const overlapWidth = Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left)
      const overlapHeight = Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top)
      assert.ok(overlapWidth <= 2 || overlapHeight <= 2, `${label}: actionable buttons overlap: ${a.label} / ${b.label}`)
    }
  }
  if (pageData.activeColors) {
    const contrast = contrastRatio(pageData.activeColors.foreground, pageData.activeColors.background)
    assert.ok(contrast >= 4.5, `${label}: selected profile text contrast ${contrast.toFixed(2)} is below 4.5:1`)
    pageData.activeColors.contrastRatio = Number(contrast.toFixed(2))
  }
  return pageData
}

async function checkIndependentDesktopScroll(page) {
  const panes = await page.evaluate(() => {
    const left = document.querySelector('.profile-scroll')
    const rightCandidates = [...document.querySelectorAll('.journey-scroll, .journey-panel, .journey-workspace, .journey-chain')]
    const right = rightCandidates.find((element) => element.scrollHeight > element.clientHeight + 30
      && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))
    return {
      left: left ? { scrollHeight: left.scrollHeight, clientHeight: left.clientHeight, scrollTop: left.scrollTop } : null,
      right: right ? { className: right.className.baseVal || right.className, scrollHeight: right.scrollHeight, clientHeight: right.clientHeight, scrollTop: right.scrollTop } : null,
      windowScrollY: window.scrollY,
    }
  })
  assert.ok(panes.left && panes.left.scrollHeight > panes.left.clientHeight + 30, `profile list should scroll independently: ${JSON.stringify(panes.left)}`)
  assert.ok(panes.right, `journey timeline should have its own scroll pane: ${JSON.stringify(panes.right)}`)
  const wheelPoints = await page.evaluate(() => {
    const left = document.querySelector('.profile-scroll').getBoundingClientRect()
    const right = [...document.querySelectorAll('.journey-scroll, .journey-workspace, .journey-panel, .journey-chain')].find((element) => element.scrollHeight > element.clientHeight + 30
      && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY)).getBoundingClientRect()
    return { left: { x: left.x + left.width / 2, y: left.y + left.height / 2 }, right: { x: right.x + right.width / 2, y: right.y + right.height / 2 } }
  })
  await page.mouse.move(wheelPoints.right.x, wheelPoints.right.y)
  await page.mouse.wheel(0, 420)
  await page.waitForTimeout(120)
  const afterRightWheel = await page.evaluate(() => ({
    left: document.querySelector('.profile-scroll')?.scrollTop || 0,
    right: [...document.querySelectorAll('.journey-scroll, .journey-panel, .journey-workspace, .journey-chain')].find((element) => element.scrollHeight > element.clientHeight + 30 && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))?.scrollTop || 0,
    windowScrollY: window.scrollY,
  }))
  assert.ok(afterRightWheel.right > panes.right.scrollTop, `timeline wheel should move the timeline: ${JSON.stringify(afterRightWheel)}`)
  assert.equal(afterRightWheel.left, panes.left.scrollTop, 'timeline scroll should not move the profile list')
  assert.equal(afterRightWheel.windowScrollY, panes.windowScrollY, 'timeline scroll should not drag the document')
  await page.mouse.move(wheelPoints.left.x, wheelPoints.left.y)
  await page.mouse.wheel(0, 380)
  await page.waitForTimeout(120)
  const afterLeftWheel = await page.evaluate(() => ({
    left: document.querySelector('.profile-scroll')?.scrollTop || 0,
    right: [...document.querySelectorAll('.journey-scroll, .journey-panel, .journey-workspace, .journey-chain')].find((element) => element.scrollHeight > element.clientHeight + 30 && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))?.scrollTop || 0,
    windowScrollY: window.scrollY,
  }))
  assert.ok(afterLeftWheel.left > panes.left.scrollTop, `profile-list wheel should move the profile list: ${JSON.stringify(afterLeftWheel)}`)
  assert.equal(afterLeftWheel.right, afterRightWheel.right, 'profile-list scroll should not move the timeline')
  assert.equal(afterLeftWheel.windowScrollY, panes.windowScrollY, 'desktop column scroll should not drag the document')
  summary.checks.push({ name: 'desktop-independent-scroll', status: 'PASS', before: panes, afterRightWheel, afterLeftWheel })
}

async function checkDeletion(page) {
  scenario = 'normal'
  const mainProfile = page.locator('.profile-entry').filter({ hasText: '主画像（初级）' }).locator('.profile-item')
  await mainProfile.click()
  await page.locator('.profile-entry').filter({ hasText: '主画像（初级）' }).locator('.profile-item[aria-pressed="true"]').waitFor()
  const deleteButton = page.getByRole('button', { name: '删除学习画像' })
  assert.equal(await deleteButton.count(), 1, 'selected profile should have a separate delete action')
  await deleteButton.click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.locator('.el-message-box__wrapper').waitFor({ state: 'hidden' })
  assert.equal(audit.writes.filter((item) => item.method === 'DELETE').length, 0, 'canceling deletion must issue no DELETE')
  scenario = 'delete-fixture'
  await deleteButton.click()
  await page.getByRole('button', { name: '永久删除', exact: true }).click()
  const deletes = audit.writes.filter((item) => item.method === 'DELETE')
  assert.deepEqual(deletes.map((item) => item.path), ['/api/profiles/learner-main'], 'confirmation should delete only the fixture profile')
  assert.deepEqual(deletes.map((item) => item.allowed), [true], 'fixture write should be explicitly authorized inside this test')
  assert.equal(await page.locator('.profile-entry').filter({ hasText: '中级画像' }).count(), 1, 'a remaining profile should be available after deletion')
  await page.locator('.profile-entry').filter({ hasText: '中级画像' }).locator('.profile-item[aria-pressed="true"]').waitFor()
  await page.locator('.journey-chain-item').filter({ hasText: '已完成的资源生成与测评' }).waitFor()
  assert.ok(audit.requests.some((item) => item.method === 'GET' && item.path === '/api/learning-history/learner-mid/journey'), '删除后应请求替代画像的旅程')
  assert.equal(deletes.length, 1, '内部替代选择不得再次 DELETE')
  deletedLearners.clear()
  summary.checks.push({ name: 'delete-cancel-confirm-fixture-only-and-select-replacement', status: 'PASS', replacementLearnerId: 'learner-mid', deleteCount: deletes.length })
}

async function checkEmptyStates() {
  const emptyProfilesPage = await openHistoryPage({ width: 1393, height: 871 }, { currentScenario: 'empty-profiles' })
  try {
    assert.equal(await emptyProfilesPage.locator('.profile-entry').count(), 0, 'empty profile response should not invent profiles')
    assert.match(await emptyProfilesPage.locator('.history-page').innerText(), /没有匹配的学习画像/)
    summary.checks.push({ name: 'empty-profiles', status: 'PASS' })
  } finally { await emptyProfilesPage.close() }

  const emptyJourneyPage = await openHistoryPage({ width: 1393, height: 871 }, { currentScenario: 'empty-journey' })
  try {
    assert.match(await emptyJourneyPage.locator('.journey-workspace').innerText(), /尚未记录学习链路/)
    assert.equal(await emptyJourneyPage.locator('.journey-chain-item').count(), 0, 'empty journey should contain no fabricated rounds or events')
    summary.checks.push({ name: 'empty-journey', status: 'PASS' })
  } finally { await emptyJourneyPage.close() }

  const isolatedPage = await openHistoryPage({ width: 1393, height: 871 }, { currentScenario: 'isolated-event' })
  try {
    assert.equal(await isolatedPage.locator('.journey-chain-item:not(.history-event)').count(), 0, 'isolated history should not create a round')
    assert.equal(await isolatedPage.locator('.journey-chain-item.history-event').count(), fixtureEvents.length, 'unlinked events should render without a round')
    summary.checks.push({ name: 'isolated-unlinked-events', status: 'PASS' })
  } finally { await isolatedPage.close() }
}

async function checkCompactJourneyPresentation() {
  const viewport = { width: 1393, height: 1080 }
  const page = await openHistoryPage(viewport, { currentScenario: 'compact-journey' })
  try {
    assert.equal(await page.locator('.journey-chain-item:not(.history-event)').count(), 5, 'compact visual scenario should show five real journey rounds')
    assert.equal(await page.locator('.state-grid article').nth(3).locator('strong').innerText(), '复习证据核验后继续练习。')
    await layoutSnapshot(page, 'compact-journey-1393x1080', viewport)
    const firstRound = page.locator('.journey-chain-item:not(.history-event)').first()
    assert.equal(await firstRound.locator('.journey-stage').count(), 6, 'compact visual scenario should keep all six stages')
    await firstRound.locator('.round-summary button').click()
    await firstRound.locator('.round-detail').waitFor()
    await layoutSnapshot(page, 'compact-journey-expanded-1393x1080', viewport)
    summary.checks.push({ name: 'compact-short-guidance-five-rounds-expanded-detail', status: 'PASS' })
  } finally { await page.close() }
}

async function topbarSignature(page) {
  return page.locator('.topbar').evaluate((element) => {
    const style = getComputedStyle(element)
    const actionStyle = getComputedStyle(element.querySelector('.topbar-action'))
    const contentStyle = getComputedStyle(document.querySelector('.content-area'))
    return {
      shellClass: document.querySelector('.app-shell')?.className || '',
      actionClass: element.querySelector('.topbar-action')?.className || '',
      backgroundColor: style.backgroundColor,
      color: style.color,
      boxShadow: style.boxShadow,
      borderBottomColor: style.borderBottomColor,
      actionBackground: actionStyle.backgroundColor,
      actionColor: actionStyle.color,
      contentBackground: contentStyle.backgroundColor,
      contentColor: contentStyle.color,
    }
  })
}

async function waitForStableTopbar(page) {
  let previous = await topbarSignature(page)
  let stableSamples = 0
  for (let attempt = 0; attempt < 12; attempt += 1) {
    await page.waitForTimeout(80)
    const current = await topbarSignature(page)
    if (JSON.stringify(current) === JSON.stringify(previous)) stableSamples += 1
    else stableSamples = 0
    if (stableSamples >= 2) return current
    previous = current
  }
  throw new Error(`top bar styles did not settle: ${JSON.stringify(previous)}`)
}

async function checkDestinationRoute(page, destination, buttonName, expectedPath, expectedQuery) {
  await page.goto(`${baseUrl}/learning/history`, { waitUntil: 'domcontentloaded' })
  await page.locator('.journey-chain-item:not(.history-event)').first().waitFor()
  const row = page.locator('.journey-chain-item:not(.history-event)').filter({ hasText: '已完成的资源生成与测评' }).first()
  assert.equal(await row.count(), 1, 'route check should target the completed fixture round with stable run and batch ids')
  const toggle = row.locator('.round-summary button')
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
  await row.getByRole('button', { name: buttonName }).click()
  await page.waitForURL((url) => url.pathname === expectedPath && url.searchParams.get('learnerId') === expectedQuery.learnerId && url.searchParams.get('runId') === expectedQuery.runId)
  assert.equal(await page.locator('.app-shell:has(.history-page)').count(), 0, 'history-only shell selector should stop matching after navigation')
  assert.equal(await page.locator('.history-page').count(), 0, 'history view should unmount on destination route')
  await page.locator('.topbar').waitFor({ state: 'visible' })
  assert.match(await page.locator('.topbar h1').innerText(), destination === 'resources' ? /学习资源/ : /资源生成/)
  await waitForStableTopbar(page)
  await saveScreenshot(page, `history-route-${destination}-after-navigation.png`)

  const direct = await browser.newPage({ viewport: { width: 1393, height: 871 } })
  try {
    direct.setDefaultTimeout(8000)
    direct.on('pageerror', (error) => audit.pageErrors.push({ message: error.message, url: direct.url() }))
    direct.on('request', (request) => {
      const requestUrl = request.url()
      if (/^https?:/.test(requestUrl) && new URL(requestUrl).origin !== new URL(baseUrl).origin) audit.externalRequests.push(requestUrl)
    })
    await direct.addInitScript(() => localStorage.clear())
    await direct.goto(`${baseUrl}${expectedPath}?learnerId=${encodeURIComponent(expectedQuery.learnerId)}&runId=${encodeURIComponent(expectedQuery.runId)}`, { waitUntil: 'domcontentloaded' })
    await direct.locator(destination === 'resources' ? '.resources-layout' : '.generate-page').waitFor()
    await waitForStableTopbar(direct)
    await saveScreenshot(direct, `history-route-${destination}-direct.png`)
    assert.deepEqual(await topbarSignature(page), await topbarSignature(direct), `top bar theme should match a direct ${destination} visit`)
  } finally { await direct.close() }
  summary.checks.push({ name: `${destination}-route-and-theme-isolation`, status: 'PASS', url: page.url() })
}

async function checkNavigation(page) {
  await checkDestinationRoute(page, 'resources', '查看本轮资源', '/resources', { learnerId: 'learner-main', runId: 'batch-1' })
  await checkDestinationRoute(page, 'generate', '查看运行进度', '/generate', { learnerId: 'learner-main', runId: 'run-1' })
}

async function checkReducedMotion() {
  const page = await openHistoryPage({ width: 390, height: 844 }, { reducedMotion: true })
  try {
    const motion = await page.locator('.profile-entry > .profile-item').first().evaluate((element) => ({
      preference: matchMedia('(prefers-reduced-motion: reduce)').matches,
      transitionProperty: getComputedStyle(element).transitionProperty,
      transitionDuration: getComputedStyle(element).transitionDuration.split(',').map((value) => Number.parseFloat(value) || 0),
      animationDuration: getComputedStyle(element).animationDuration.split(',').map((value) => Number.parseFloat(value) || 0),
    }))
    assert.equal(motion.preference, true)
    assert.ok(Math.max(...motion.transitionDuration) <= 0.05, `history controls should honor reduced motion: ${JSON.stringify(motion)}`)
    assert.ok(Math.max(...motion.animationDuration) <= 0.05, `history controls should honor reduced motion: ${JSON.stringify(motion)}`)
    await layoutSnapshot(page, 'mobile-reduced-motion-390x844', { width: 390, height: 844 })
    summary.checks.push({ name: 'reduced-motion', status: 'PASS', motion })
  } finally { await page.close() }
}

let thrown = null
try {
  browser = await chromium.launch(browserOptions('HISTORY_BROWSER_CHANNEL'))
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  serverStarted = true
  baseUrl = `http://127.0.0.1:${server.address().port}`

  const desktop = await openHistoryPage({ width: 1393, height: 871 })
  try {
    assert.equal(await desktop.locator('.app-shell').evaluate((element) => element.classList.contains('is-sidebar-collapsed')), false, 'expanded desktop evidence should use the expanded sidebar')
    await pageReady(desktop)
    await checkProfileAndJourneyBehaviors(desktop)
    // Reload to restore a clean first page before independent scrolling and route checks.
    await desktop.reload({ waitUntil: 'domcontentloaded' })
    await desktop.locator('.journey-chain-item:not(.history-event)').first().waitFor()
    await layoutSnapshot(desktop, 'desktop-expanded-1393x871', { width: 1393, height: 871 })
    await checkIndependentDesktopScroll(desktop)
    await checkDeletion(desktop)
  } finally { await desktop.close() }

  const collapsed = await openHistoryPage({ width: 1331, height: 871 }, { collapsed: true })
  try {
    assert.equal(await collapsed.locator('.app-shell').evaluate((element) => element.classList.contains('is-sidebar-collapsed')), true, 'collapsed desktop evidence should use the collapsed sidebar')
    await layoutSnapshot(collapsed, 'desktop-collapsed-1331x871', { width: 1331, height: 871 })
  } finally { await collapsed.close() }

  const wide = await openHistoryPage({ width: 1920, height: 1080 })
  try {
    await layoutSnapshot(wide, 'wide-1920x1080', { width: 1920, height: 1080 })
  } finally { await wide.close() }

  await checkCompactJourneyPresentation()

  for (const viewport of [{ width: 390, height: 844 }, { width: 375, height: 667 }, { width: 1393, height: 620 }]) {
    const label = viewport.width === 1393 ? 'short-window-1393x620' : `mobile-${viewport.width}x${viewport.height}`
    const page = await openHistoryPage(viewport)
    try {
      await layoutSnapshot(page, label, viewport)
      if (viewport.width <= 390) {
        const loadMore = page.getByRole('button', { name: '加载更多轮次' })
        await loadMore.scrollIntoViewIfNeeded()
        const target = await loadMore.boundingBox()
        assert.ok(target && target.y >= -1 && target.y + target.height <= viewport.height + 1, `${label}: lower-page action should be naturally reachable: ${JSON.stringify(target)}`)
        summary.checks.push({ name: `${label}-natural-reachability`, status: 'PASS', target })
      }
    } finally { await page.close() }
  }

  const routePage = await openHistoryPage({ width: 1393, height: 871 })
  try { await checkNavigation(routePage) } finally { await routePage.close() }

  await checkEmptyStates()
  await checkReducedMotion()
  assert.deepEqual(audit.unexpectedApi, [], `unexpected API requests: ${JSON.stringify(audit.unexpectedApi)}`)
  assert.deepEqual(audit.externalRequests, [], `external requests: ${JSON.stringify(audit.externalRequests)}`)
  assert.deepEqual(audit.pageErrors, [], `browser page errors: ${JSON.stringify(audit.pageErrors)}`)
  const deniedWrites = audit.writes.filter((item) => item.allowed !== true)
  assert.deepEqual(deniedWrites, [], `fixture writes outside the confirmed delete: ${JSON.stringify(deniedWrites)}`)
  assert.deepEqual(audit.writes.filter((item) => item.method === 'DELETE').map((item) => item.path), ['/api/profiles/learner-main'])
  summary.status = 'PASS'
} catch (error) {
  thrown = error
  summary.status = 'FAIL'
  summary.failure = { message: error.message, stack: error.stack }
} finally {
  summary.audit = audit
  summary.summary = {
    browser: 'Playwright Edge/Chromium via browserOptions',
    screenshotCount: summary.screenshots.length,
    checkCount: summary.checks.length,
    layoutCount: summary.layout.length,
    writes: audit.writes,
    unexpectedApiCount: audit.unexpectedApi.length,
    externalRequestCount: audit.externalRequests.length,
    pageErrorCount: audit.pageErrors.length,
  }
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + '\n')
  if (browser) await browser.close()
  if (serverStarted) await new Promise((resolve) => server.close(resolve))
}
if (thrown) throw thrown

async function pageReady(page) {
  await page.locator('.state-grid article').nth(3).waitFor()
  await page.locator('.journey-chain-item:not(.history-event)').first().waitFor()
  await page.waitForFunction(() => document.querySelectorAll('.profile-entry').length === 10)
}
